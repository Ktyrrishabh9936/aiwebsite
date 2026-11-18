"""Meetings arranged by the AI: a lead asks on a call, the calendar is checked, admin and lead are told.

The owner can always pick a different time. The lead is then emailed the new time and, when they can be
called, the Follow-up Agent phones them to agree it. What the lead answers on that call comes back here
(``lead_reply``): the owner is told, and a new time the lead asks for goes through the same steps again.
"""
import logging
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_ops import (PURPOSES, access, add_lead_note, clean, lead_contact, minutes_of, out, owner_email, parse, settings_of,
                    stable_id, stage_category, utcnow, zone_of)
from connectors import booking_link, calendar_for, send_workspace_email

logger = logging.getLogger("ai_ops.meetings")
router = APIRouter(prefix="/workspaces/{ws_id}/ai-ops/meetings", tags=["Daily AI operations"])

SLOT_MINUTES = 30
SEARCH_DAYS = 14


def overlaps(start, end, busy):
    return any(start < busy_end and end > busy_start for busy_start, busy_end in busy)


def within_hours(start, settings, zone):
    local = start.astimezone(zone)
    begin = local.hour * 60 + local.minute
    hours = settings["meeting_hours"]
    return local.weekday() in settings["meeting_days"] and minutes_of(hours["start"]) <= begin \
        and begin + settings["meeting_duration_minutes"] <= minutes_of(hours["end"])


def find_slot(preferred, busy, settings, now):
    """The lead's requested time when it is free, otherwise the nearest free slot in meeting hours.

    Returns (start or None, note for the owner).
    """
    zone = zone_of(settings)
    duration = timedelta(minutes=settings["meeting_duration_minutes"])
    earliest = now + timedelta(hours=1)
    if preferred and preferred >= earliest:
        local = preferred.astimezone(zone)
        if 7 <= local.hour < 21 and not overlaps(preferred, preferred + duration, busy):
            return preferred, "" if within_hours(preferred, settings, zone) else "This is the time the lead asked for; it is outside your usual meeting hours."
    if preferred and preferred >= earliest:
        cursor, note = preferred, "The time the lead asked for is not free, so this is the nearest free slot."
    else:  # no time was mentioned: start from the next day rather than surprising anyone today
        tomorrow = (now.astimezone(zone) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        cursor, note = tomorrow.astimezone(timezone.utc), "The lead did not name a time, so this is your first free slot."
    cursor = cursor.replace(second=0, microsecond=0)
    if cursor.minute % SLOT_MINUTES:
        cursor += timedelta(minutes=SLOT_MINUTES - cursor.minute % SLOT_MINUTES)
    limit = cursor + timedelta(days=SEARCH_DAYS)
    while cursor < limit:
        if within_hours(cursor, settings, zone) and not overlaps(cursor, cursor + duration, busy):
            return cursor, note
        cursor += timedelta(minutes=SLOT_MINUTES)
    return None, "No free slot was found in the next two weeks. Choose a time yourself."


async def busy_times(db, ws_id, calendar, start, end, exclude_id=None):
    """Calendar events plus meetings this system already holds. Returns (busy list, calendar was read)."""
    busy, read = [], False
    if calendar:
        try:
            busy, read = await calendar.busy(start, end), True
        except Exception as exc:
            logger.warning("calendar_busy_unavailable workspace=%s error_type=%s", ws_id, type(exc).__name__)
    held = await db.ai_ops_meetings.find({"workspace_id": ws_id, "status": {"$in": ["proposed", "confirmed"]}, "start": {"$gte": start.isoformat()}}).to_list(500)
    for meeting in held:
        begin = parse(meeting.get("start"))
        if begin and meeting["_id"] != exclude_id:
            busy.append((begin, begin + timedelta(minutes=meeting.get("duration_minutes") or 30)))
    return busy, read


def event_text(ws, meeting):
    lines = [f"Meeting with {meeting['lead_name']} arranged by your AI Manager."]
    if meeting.get("topic"):
        lines.append(f"Topic: {meeting['topic']}")
    if meeting.get("requested_text"):
        lines.append(f"The lead said: {meeting['requested_text']}")
    if meeting.get("lead_phone"):
        lines.append(f"Phone: {meeting['lead_phone']}")
    return f"{meeting['lead_name']} × {ws.get('name') or 'Meeting'}", "\n".join(lines)


async def book(db, ws, meeting, calendar, change):
    """Put a confirmed meeting on the calendar and tell the lead. Returns the fields to save."""
    from ai_ops_emails import lead_email, meeting_lead_text, when_text
    ws_id, settings = str(ws["_id"]), settings_of(ws)
    start = parse(meeting["start"])
    end = start + timedelta(minutes=meeting["duration_minutes"])
    updates = {}
    if calendar:
        try:
            summary, description = event_text(ws, meeting)
            event = await (calendar.update(meeting["calendar_event_id"], summary, description, start, end, meeting.get("lead_email") or "")
                           if meeting.get("calendar_event_id") else calendar.create(summary, description, start, end, meeting.get("lead_email") or ""))
            updates.update({"calendar_event_id": event["event_id"], "calendar_link": event["link"], "calendar_provider": calendar.name, "calendar_error": None})
            if event.get("meet_link"):  # the video link both sides join from
                updates["meeting_link"] = event["meet_link"]
        except Exception as exc:
            logger.warning("calendar_booking_failed workspace=%s error_type=%s", ws_id, type(exc).__name__)
            updates["calendar_error"] = "The calendar event could not be saved. Add it to your calendar manually."
    business = ws.get("name") or "our team"
    if meeting.get("lead_email"):
        subject = {"rescheduled": "Your meeting time has changed", "changed": "A new time for our meeting", "confirmed": "Your meeting is confirmed"}[change]
        sent = await send_workspace_email(db, ws, meeting["lead_email"], f"{subject} · {business}",
                                          lead_email(business, meeting_lead_text(business, meeting["lead_name"], {**meeting, **updates}, settings["timezone"], change)),
                                          reply_to=await owner_email(db, ws, settings))
        updates["lead_notified"] = bool(sent["sent"])
        updates["lead_notified_at"] = utcnow().isoformat() if sent["sent"] else meeting.get("lead_notified_at")
    else:
        updates["lead_notified"] = False
    label = "Meeting moved to" if change == "rescheduled" else "New meeting time offered:" if change == "changed" else "Meeting confirmed for"
    await add_lead_note(db, ws_id, meeting["lead_id"], f"{label} {when_text(start, settings['timezone'])}."
                        + (" The lead was emailed." if updates["lead_notified"] else " The lead was not emailed (no email address or delivery failed)."),
                        f"{label} {when_text(start, settings['timezone'])}", extra={"ai_ops.meeting_at": start.isoformat()})
    return updates


async def send_booking_link(db, ws, lead, contact, found, link, now):
    """Calendly is connected: the lead picks their own time from the owner's booking page."""
    from ai_ops_emails import lead_email, simple_email
    ws_id, lead_id, settings, business = str(ws["_id"]), str(lead["_id"]), settings_of(ws), ws.get("name") or "our team"
    meeting = {"_id": stable_id("meeting", ws_id, lead_id, lead.get("last_call_at")), "workspace_id": ws_id, "lead_id": lead_id,
               "lead_name": contact["name"], "lead_email": contact["email"], "lead_phone": contact["phone"],
               "requested_text": clean(found.get("preferred_time_text"), 200), "topic": clean(found.get("meeting_topic"), 200),
               "start": None, "duration_minutes": settings["meeting_duration_minutes"], "status": "link_sent", "booking_link": link,
               "slot_note": "Your Calendly link was emailed to the lead so they can pick a time.", "lead_notified": False, "source": "call",
               "history": [{"at": now.isoformat(), "by": "AI Manager", "event": "booking link sent"}],
               "created_at": now.isoformat(), "updated_at": now.isoformat()}
    created = await db.ai_ops_meetings.update_one({"_id": meeting["_id"]}, {"$setOnInsert": {k: v for k, v in meeting.items() if k != "_id"}}, upsert=True)
    if not created.upserted_id:
        return None
    owner_address = await owner_email(db, ws, settings)
    first = (contact["name"] or "").split(" ")[0] or "there"
    body = (f"Hi {first},\n\nThank you for speaking with us. Please pick a time that suits you for our meeting here:\n{link}"
            f"\n\nReply to this email if you need any help.\n\n{business}")
    sent = await send_workspace_email(db, ws, contact["email"], f"Book your meeting · {business}", lead_email(business, body), reply_to=owner_address)
    meeting["lead_notified"] = bool(sent["sent"])
    await db.ai_ops_meetings.update_one({"_id": meeting["_id"]}, {"$set": {"lead_notified": meeting["lead_notified"]}})
    await add_lead_note(db, ws_id, lead_id, "The lead asked for a meeting. " + ("Your Calendly booking link was emailed to them." if sent["sent"]
                                                                               else "The booking link could not be emailed."),
                        "Meeting booking link sent" if sent["sent"] else "Meeting requested")
    if owner_address:
        said = f" They said: {meeting['requested_text']}." if meeting["requested_text"] else ""
        lines = [f"{contact['name']} asked for a meeting during a call.{said}",
                 "I emailed them your Calendly link so they can pick a time. The booking will reach you from Calendly." if sent["sent"]
                 else "I could not email them your Calendly link. Please send it to them yourself."]
        await send_workspace_email(db, ws, owner_address, f"Meeting requested: {contact['name']}",
                                   simple_email("Booking link sent" if sent["sent"] else "Meeting requested", "Meeting", lines))
    return meeting


async def open_meeting(db, ws_id, lead_id, now):
    """The lead's meeting that is still being arranged or is yet to happen, if any."""
    return await db.ai_ops_meetings.find_one({"workspace_id": ws_id, "lead_id": lead_id, "status": {"$in": ["proposed", "confirmed", "needs_time"]},
                                              "$or": [{"start": None}, {"start": {"$gte": now.isoformat()}}]})


async def lead_details(db, ws_id, lead):
    """What the owner needs to know about who is asking: their stage and what the call was about."""
    from crm import ensure_crm_settings
    stage = str(lead.get("status") or "new")
    states = (await ensure_crm_settings(db, ws_id)).get("states") or []
    call = lead.get("qualification_call") or {}
    summary = call.get("summary") or lead.get("conversation_summary") or (lead.get("communication_summary") or {}).get("latest_summary")
    return {"lead_stage": next((state.get("label") for state in states if state.get("key") == stage), None) or stage.replace("_", " ").title(),
            "call_summary": clean(summary, 600)}


async def time_call_plan(db, ws, lead):
    """(action fields, "") when the Follow-up Agent can phone the lead about a meeting time, else (None, why not)."""
    from ai_agents import ensure_agents, handles
    from crm import ensure_crm_settings
    ws_id, settings, contact = str(ws["_id"]), settings_of(ws), lead_contact(lead)
    if not settings["enabled"] or settings["calls"] == "off":
        return None, "AI calls are switched off, so the lead was not called."
    if lead.get("do_not_call") or not contact["phone"]:
        return None, "The lead is marked do-not-call or has no phone number, so they were not called."
    states = (await ensure_crm_settings(db, ws_id)).get("states") or []
    category, stage = stage_category(lead, states), str(lead.get("status") or "new")
    if category in {"customer", "lost"}:
        return None, "The AI does not call customers or lost leads, so they were not called."
    agents = [agent for agent in await ensure_agents(db, ws_id) if agent.get("enabled") and "call" in (agent.get("actions") or [])]
    agent = next((a for a in agents if a.get("role") == "follow_up"), None) or next((a for a in agents if handles(a, stage, category)), None)
    if not agent:
        return None, "No active agent can make calls, so the lead was not called."
    label = next((state.get("label") for state in states if state.get("key") == stage), None) or stage.replace("_", " ").title()
    return {"kind": "call", "category": category, "stage": stage, "stage_label": label, "segment": "pipeline", "agent_id": str(agent["_id"]),
            "agent_name": agent["name"], "agent_role": agent.get("role"), "purpose": "meeting_call", "purpose_label": PURPOSES["meeting_call"]}, ""


async def queue_time_call(db, ws, meeting, fields, expected, now):
    """Queue the call that tells the lead the owner's time and asks whether it works. Runs in calling hours."""
    from ai_ops_emails import when_text
    ws_id, zone, meeting_id = str(ws["_id"]), settings_of(ws)["timezone"], str(meeting["_id"])
    business = ws.get("name") or "The team"
    was = f"They expected to meet on {when_text(expected, zone)}. " if expected else ""
    reason = clean(f"Meeting time change. {was}{business} is not available then and proposes {when_text(meeting['start'], zone)}. Tell them, and ask if "
                   "that works. If it does not, ask which day and time suits them and say the team will confirm it.", 420)
    # Only the newest time is ever phoned through.
    await db.ai_ops_actions.update_many({"workspace_id": ws_id, "payload.meeting_id": meeting_id, "status": "scheduled"},
                                        {"$set": {"status": "superseded", "updated_at": now.isoformat()}})
    run = await db.ai_ops_runs.find_one({"workspace_id": ws_id}, sort=[("created_at", -1)])
    action_id = stable_id("meeting_call", meeting_id, meeting["start"])
    doc = {**fields, "workspace_id": ws_id, "run_id": str(run["_id"]) if run else None, "day": (run or {}).get("day"), "lead_id": meeting["lead_id"],
           "lead_name": meeting["lead_name"], "allowed": ["call"], "reason": reason, "priority": 100, "status": "scheduled",
           "scheduled_for": now.isoformat(), "payload": {"meeting_id": meeting_id}, "decided_by": "owner", "attempts": 0, "proposal": False,
           "result": None, "created_at": now.isoformat(), "updated_at": now.isoformat()}
    await db.ai_ops_actions.update_one({"_id": action_id}, {"$set": doc}, upsert=True)
    return action_id


async def lead_reply(db, ws, lead, meeting, found, now):
    """The lead answered about the meeting time on a call. Act on it and tell the owner. Returns the outcome, or None."""
    from ai_ops_emails import meeting_reply_email, when_text
    response = found.get("meeting_response")
    if response not in {"accepted", "other_time", "declined"} or (response == "accepted" and not meeting.get("start")):
        return None
    ws_id, settings = str(ws["_id"]), settings_of(ws)
    zone, said = settings["timezone"], clean(found.get("preferred_time_text"), 200)
    updates = {"awaiting_lead_reply": False, "lead_reply": response, "lead_reply_text": said, "lead_reply_at": now.isoformat(), "will_call": False}
    meeting = {**meeting, "will_call": False}
    if response == "accepted":
        outcome, event, updates["lead_confirmed"] = "accepted", "the lead agreed to the time", True
        note = f"On the call the lead agreed to meet on {when_text(meeting['start'], zone)}."
    elif response == "declined":
        outcome, event, updates["lead_confirmed"] = "declined", "the lead said they no longer want the meeting", False
        note = "On the call the lead said they no longer want the meeting. The owner was told; nothing was cancelled."
    else:
        preferred = found.get("preferred_time")
        calendar = await calendar_for(db, ws_id)
        start, slot_note = None, ""
        if preferred:
            busy, _ = await busy_times(db, ws_id, calendar, max(now, preferred - timedelta(hours=2)), preferred + timedelta(days=SEARCH_DAYS + 2), exclude_id=meeting["_id"])
            start, slot_note = find_slot(preferred, busy, settings, now)
        updates.update({"lead_confirmed": False, "requested_text": said or meeting.get("requested_text"), "requested_start": preferred.isoformat() if preferred else None})
        if not start:
            outcome, event = "needs_time", "the lead asked for a different time"
            updates.update({"status": "needs_time", "start": None, "slot_note": "The lead could not make your time. Choose a new one."})
            note = "On the call the lead asked for a different meeting time. Waiting for the owner to choose one."
        else:
            meeting.update({"start": start.isoformat(), "requested_start": updates["requested_start"], "requested_text": updates["requested_text"]})
            updates["start"] = start.isoformat()
            if settings["meeting_mode"] == "auto" and start == preferred:  # their time is free: move it straight away
                outcome, event = "moved", "moved to the time the lead asked for"
                updates.update({"status": "confirmed", "slot_note": "", "lead_confirmed": True})
                updates.update(await book(db, ws, {**meeting, "status": "confirmed"}, calendar, "rescheduled"))
                note = ""  # book() already wrote the note
            else:
                outcome, event = "proposed", "the lead asked for a different time"
                updates.update({"status": "proposed", "slot_note": slot_note or "This is the time the lead asked for on the follow-up call."})
                note = f"On the call the lead asked to move the meeting ({said or when_text(start, zone)}). Waiting for the owner to confirm."
    updates["updated_at"] = now.isoformat()
    await db.ai_ops_meetings.update_one({"_id": meeting["_id"]}, {"$set": updates, "$push": {"history": {
        "at": now.isoformat(), "by": "the lead, on a call", "event": event, "start": updates.get("start", meeting.get("start"))}}})
    if note:
        await add_lead_note(db, ws_id, meeting["lead_id"], note, "Meeting: " + event)
    recipient = await owner_email(db, ws, settings)
    if recipient:
        subject = {"accepted": "Meeting time agreed", "moved": "Meeting moved", "declined": "Meeting no longer wanted"}.get(outcome, "Meeting time needs your decision")
        await send_workspace_email(db, ws, recipient, f"{subject}: {meeting['lead_name']}",
                                   meeting_reply_email(ws, {**meeting, **updates, **await lead_details(db, ws_id, lead)}, zone, outcome, said))
    return outcome


async def request_meeting(db, ws, lead, found, now):
    """A lead asked for a meeting on a call: find a time, then book or propose it and email the owner."""
    from ai_ops_emails import meeting_admin_email
    ws_id, lead_id, settings = str(ws["_id"]), str(lead["_id"]), settings_of(ws)
    if await open_meeting(db, ws_id, lead_id, now):
        return None  # one open meeting per lead; the owner can change its time
    contact = lead_contact(lead)
    link = await booking_link(db, ws_id)
    if link and contact["email"]:
        return await send_booking_link(db, ws, lead, contact, found, link, now)
    calendar = await calendar_for(db, ws_id)
    # Read the calendar only around the dates that can be offered (keeps the request small).
    window_start = max(now, found["preferred_time"] - timedelta(hours=2)) if found.get("preferred_time") else now
    busy, calendar_read = await busy_times(db, ws_id, calendar, window_start, window_start + timedelta(days=SEARCH_DAYS + 2))
    start, note = find_slot(found.get("preferred_time"), busy, settings, now)
    automatic = settings["meeting_mode"] == "auto" and start is not None
    meeting = {"_id": stable_id("meeting", ws_id, lead_id, lead.get("last_call_at")), "workspace_id": ws_id, "lead_id": lead_id,
               "lead_name": contact["name"], "lead_email": contact["email"], "lead_phone": contact["phone"],
               "requested_text": clean(found.get("preferred_time_text"), 200), "topic": clean(found.get("meeting_topic"), 200),
               "requested_start": found["preferred_time"].isoformat() if found.get("preferred_time") else None,
               "start": start.isoformat() if start else None, "duration_minutes": settings["meeting_duration_minutes"],
               "status": "confirmed" if automatic else "proposed" if start else "needs_time", "slot_note": note,
               "calendar_checked": calendar_read, "lead_notified": False, "source": "call", **await lead_details(db, ws_id, lead),
               "history": [{"at": now.isoformat(), "by": "AI Manager", "event": "requested on a call", "start": start.isoformat() if start else None}],
               "created_at": now.isoformat(), "updated_at": now.isoformat()}
    created = await db.ai_ops_meetings.update_one({"_id": meeting["_id"]}, {"$setOnInsert": {k: v for k, v in meeting.items() if k != "_id"}}, upsert=True)
    if not created.upserted_id:
        return None
    if automatic:
        updates = await book(db, ws, meeting, calendar, "confirmed")
        meeting.update(updates)
        await db.ai_ops_meetings.update_one({"_id": meeting["_id"]}, {"$set": updates})
    else:
        await add_lead_note(db, ws_id, lead_id, "The lead asked for a meeting. Waiting for the owner to confirm a time.", "Meeting requested")
    recipient = await owner_email(db, ws, settings)
    if recipient:
        subject = f"Meeting {'booked' if automatic else 'requested'}: {contact['name']}"
        await send_workspace_email(db, ws, recipient, subject, meeting_admin_email(ws, meeting, settings["timezone"], bool(calendar)))
    return meeting


# ---------------------------------------------------------------- API
class MeetingTime(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: datetime | None = None
    note: str = Field(default="", max_length=500)
    call_lead: bool = True  # when the time differs from what the lead expects, also phone them to agree it

    @field_validator("start")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("The time must include a timezone")
        return value.astimezone(timezone.utc) if value else value


class CancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notify_lead: bool = True


async def load(db, ws_id, meeting_id):
    meeting = await db.ai_ops_meetings.find_one({"_id": ObjectId(meeting_id), "workspace_id": ws_id}) if ObjectId.is_valid(meeting_id) else None
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    return meeting


@router.get("")
async def list_meetings(ws_id: str, request: Request):
    db, _, _ = await access(request, ws_id)
    docs = await db.ai_ops_meetings.find({"workspace_id": ws_id}).sort("created_at", -1).to_list(200)
    return [out(doc) for doc in docs]


@router.post("/{meeting_id}/confirm")
async def confirm_meeting(ws_id: str, meeting_id: str, request: Request, body: MeetingTime):
    """Confirm the proposed time, or set the owner's own time. The lead is emailed the result, and phoned when the time is not the one they expect."""
    db, user, ws = await access(request, ws_id)
    meeting = await load(db, ws_id, meeting_id)
    if meeting["status"] == "cancelled":
        raise HTTPException(409, "This meeting was cancelled")
    now = utcnow()
    start = body.start or parse(meeting.get("start"))
    if not start:
        raise HTTPException(422, "Choose a time for the meeting")
    if start <= now:
        raise HTTPException(422, "Choose a time in the future")
    moved = meeting.get("start") != start.isoformat()
    if meeting["status"] == "confirmed" and not moved and not body.note.strip():
        return {**out(meeting), "conflict": False}
    calendar = await calendar_for(db, ws_id)
    busy, _ = await busy_times(db, ws_id, calendar, start - timedelta(hours=4), start + timedelta(hours=4), exclude_id=meeting["_id"])
    conflict = overlaps(start, start + timedelta(minutes=meeting["duration_minutes"]), busy)
    # What the lead currently expects: the time they were last told, otherwise the time they asked for.
    expected = parse(meeting.get("start")) if meeting.get("lead_notified") else parse(meeting.get("requested_start"))
    differs = expected is not None and abs((expected - start).total_seconds()) >= 60
    change = "confirmed" if not differs else "rescheduled" if meeting.get("lead_notified") else "changed"
    lead = await db.crm_leads.find_one({"_id": ObjectId(meeting["lead_id"]), "workspace_id": ws_id}) if ObjectId.is_valid(str(meeting["lead_id"])) else None
    call_fields, call_note = (None, "")
    if differs and body.call_lead and lead:
        call_fields, call_note = await time_call_plan(db, ws, lead)
    meeting.update({"start": start.isoformat(), "status": "confirmed", "admin_note": body.note.strip(), "slot_note": "", "will_call": bool(call_fields)})
    updates = await book(db, ws, meeting, calendar, change)
    event = {"at": now.isoformat(), "by": user.get("email") or "owner", "event": "time changed by the owner" if moved else "confirmed by the owner", "start": start.isoformat()}
    if call_fields:
        updates["time_call_action_id"] = str(await queue_time_call(db, ws, meeting, call_fields, expected, now))
        event["lead_call"] = "queued"
    await db.ai_ops_meetings.update_one({"_id": meeting["_id"]}, {
        "$set": {**updates, "start": start.isoformat(), "status": "confirmed", "admin_note": body.note.strip(), "slot_note": "", "updated_at": now.isoformat(),
                 "will_call": bool(call_fields), "awaiting_lead_reply": bool(call_fields), "lead_confirmed": not differs,
                 "call_note": call_note if differs else ""},
        "$push": {"history": event}})
    return {**out(await load(db, ws_id, meeting_id)), "conflict": conflict, "lead_call": "queued" if call_fields else "none"}


@router.post("/{meeting_id}/cancel")
async def cancel_meeting(ws_id: str, meeting_id: str, request: Request, body: CancelInput):
    from ai_ops_emails import lead_email, meeting_lead_text
    db, user, ws = await access(request, ws_id)
    meeting = await load(db, ws_id, meeting_id)
    if meeting["status"] == "cancelled":
        return out(meeting)
    now, settings = utcnow(), settings_of(ws)
    if meeting.get("calendar_event_id"):
        calendar = await calendar_for(db, ws_id)
        try:
            if calendar:
                await calendar.cancel(meeting["calendar_event_id"])
        except Exception as exc:
            logger.warning("calendar_cancel_failed workspace=%s error_type=%s", ws_id, type(exc).__name__)
    told = False
    if body.notify_lead and meeting.get("lead_notified") and meeting.get("lead_email") and meeting.get("start"):
        business = ws.get("name") or "our team"
        sent = await send_workspace_email(db, ws, meeting["lead_email"], f"Your meeting has been cancelled · {business}",
                                          lead_email(business, meeting_lead_text(business, meeting["lead_name"], meeting, settings["timezone"], "cancelled")),
                                          reply_to=await owner_email(db, ws, settings))
        told = bool(sent["sent"])
    await db.ai_ops_meetings.update_one({"_id": meeting["_id"]}, {
        "$set": {"status": "cancelled", "updated_at": now.isoformat()},
        "$push": {"history": {"at": now.isoformat(), "by": user.get("email") or "owner", "event": "cancelled", "lead_told": told}}})
    await add_lead_note(db, ws_id, meeting["lead_id"], "Meeting cancelled by the owner." + (" The lead was emailed." if told else ""), "Meeting cancelled",
                        extra={"ai_ops.meeting_at": None})
    return out(await load(db, ws_id, meeting_id))
