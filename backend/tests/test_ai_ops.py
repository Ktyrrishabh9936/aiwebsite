import asyncio
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from cryptography.fernet import Fernet
from fastapi import HTTPException

import ai_ops
import ai_ops_meetings as meetings
import connectors
from tests.fake_mongo import FakeDb

# Tuesday 17 Nov 2026, 10:30 in Asia/Kolkata: inside the default calling window and email hours.
NOW = datetime(2026, 11, 17, 5, 0, tzinfo=timezone.utc)
STATES = [{"key": "new", "label": "New", "order": 1}, {"key": "contacted", "label": "Contacted", "order": 2},
          {"key": "ai_qualified", "label": "AI Qualified", "order": 3}, {"key": "won", "label": "Won", "order": 4},
          {"key": "lost", "label": "Lost", "order": 5}]


def iso(**delta):
    return (NOW - timedelta(**delta)).isoformat()


def lead(status="new", **fields):
    doc = {"_id": ObjectId(), "workspace_id": "ws", "status": status, "deleted_at": None, "created_at": iso(days=5), "updated_at": iso(days=1),
           "field_values": {"full_name": "Asha Rao", "phone": "+919876543210", "email": "asha@example.com"}}
    doc.update(fields)
    return doc


def context(**overrides):
    base = {"now": NOW, "states": STATES, "labels": {s["key"]: s["label"] for s in STATES}, "tasks": {}, "open_leads": set(),
            "calls_week": {}, "meeting_leads": set(), "dues": {}}
    return {**base, **overrides}


def settings(**overrides):
    """Automatic mode unless a test asks for the owner's plan approval."""
    return {**ai_ops.DEFAULTS, "enabled": True, "plan_approval": "auto", **overrides}


WORKFLOW = {"enabled": True, "timezone": "Asia/Kolkata", "calling_window": {"start": "09:30", "end": "19:00"}}
RUN = {"_id": ObjectId(), "workspace_id": "ws", "day": "2026-11-17"}


# ------------------------------------------------------------ scheduling
def test_next_run_is_today_when_the_time_is_ahead_and_tomorrow_when_it_passed():
    ahead = ai_ops.next_run_at(settings(run_time="11:00"), NOW)
    assert ahead == datetime(2026, 11, 17, 5, 30, tzinfo=timezone.utc)
    passed = ai_ops.next_run_at(settings(run_time="09:00"), NOW)
    assert passed == datetime(2026, 11, 18, 3, 30, tzinfo=timezone.utc)
    assert ai_ops.next_run_at(settings(run_time="10:30"), NOW) > NOW  # exactly now counts as passed


def test_settings_reject_unknown_timezones_and_modes():
    with pytest.raises(ValueError):
        ai_ops.SettingsInput(run_time="09:00", timezone="Mars/Olympus")
    with pytest.raises(ValueError):
        ai_ops.SettingsInput(run_time="25:00", timezone="UTC")
    with pytest.raises(ValueError):
        ai_ops.SettingsInput(run_time="09:00", timezone="UTC", calls="always")


# ------------------------------------------------------------ stage understanding
def test_stages_map_to_the_categories_the_strategy_uses():
    custom = [*STATES, {"key": "negotiation", "label": "Negotiation", "order": 3.5}]
    assert ai_ops.stage_category(lead("new"), STATES) == "new"
    assert ai_ops.stage_category(lead("contacted"), STATES) == "contacted"
    assert ai_ops.stage_category(lead("ai_qualified"), STATES) == "qualified"
    assert ai_ops.stage_category(lead("negotiation"), custom) == "qualified"
    assert ai_ops.stage_category(lead("won"), STATES) == "customer"
    assert ai_ops.stage_category(lead("contacted", customer_status="customer"), STATES) == "customer"
    assert ai_ops.stage_category(lead("lost"), STATES) == "lost"
    assert ai_ops.stage_category(lead("new", qualification_call={"qualification_category": "junk"}), STATES) == "lost"


def test_each_stage_gets_its_own_kind_of_action():
    new = ai_ops.assess(lead("new"), context())
    assert new["suggested"]["kind"] == "call" and new["category"] == "new"

    no_phone = lead("new")
    no_phone["field_values"]["phone"] = ""
    assert ai_ops.assess(no_phone, context())["suggested"] == {"kind": "email", "reason": "New lead with no phone contact possible; introduce the business by email.",
                                                               "template": "intro", "at": None, "needs_approval": False}

    contacted = ai_ops.assess(lead("contacted", last_call_at=iso(days=3), last_call_outcome="CONNECTED", call_attempt_count=1), context())
    assert contacted["suggested"]["kind"] == "email" and contacted["suggested"]["template"] == "follow_up"

    qualified = ai_ops.assess(lead("ai_qualified", last_call_at=iso(days=4), last_call_outcome="CONNECTED", lead_temperature="HOT"), context())
    assert qualified["suggested"]["kind"] == "call" and qualified["priority"] > contacted["priority"]

    paying = lead("won", customer_status="customer", converted_at=iso(days=30))
    customer = ai_ops.assess(paying, context(dues={str(paying["_id"]): "20,000"}))
    assert customer["segment"] == "customer" and customer["suggested"]["template"] == "payment_reminder"
    assert customer["suggested"]["needs_approval"] and "call" not in customer["allowed"]  # customers are never auto-called


def test_leads_already_in_hand_are_left_alone():
    planned = lead("contacted", last_call_at=iso(days=4))
    future_task = {str(planned["_id"]): [{"title": "Send brochure", "scheduled_time": (NOW + timedelta(days=1)).isoformat()}]}
    assert ai_ops.assess(planned, context(tasks=future_task)) is None
    assert ai_ops.assess(lead("new", qualification_call={"status": "scheduled"}), context()) is None
    assert ai_ops.assess(lead("lost"), context()) is None
    queued = lead("new")
    assert ai_ops.assess(queued, context(open_leads={str(queued["_id"])})) is None
    booked = lead("ai_qualified", last_call_at=iso(days=3))
    assert ai_ops.assess(booked, context(meeting_leads={str(booked["_id"])})) is None
    assert ai_ops.assess(lead("contacted", last_call_at=iso(hours=5), last_call_outcome="CONNECTED"), context()) is None  # spoken to today


def test_do_not_call_and_recent_contact_limits_are_respected():
    blocked = ai_ops.assess(lead("new", do_not_call=True), context())
    assert "call" not in blocked["allowed"] and blocked["suggested"]["kind"] == "email"
    worn = lead("contacted", last_call_at=iso(days=3), last_call_outcome="NO_ANSWER")
    limited = ai_ops.assess(worn, context(calls_week={str(worn["_id"]): 3}))
    assert "call" not in limited["allowed"]
    overdue = lead("contacted", last_call_at=iso(days=3), last_call_outcome="CONNECTED")
    late = ai_ops.assess(overdue, context(tasks={str(overdue["_id"]): [{"title": "Call back", "scheduled_time": iso(days=1)}]}))
    assert "overdue" in late["suggested"]["reason"].lower()


# ------------------------------------------------------------ turning a strategy into actions
def candidates_for(*leads, **ctx):
    return sorted(filter(None, (ai_ops.assess(item, context(**ctx)) for item in leads)), key=lambda c: -c["priority"])


def test_model_choices_are_used_only_when_they_are_allowed():
    fresh, quiet = lead("new"), lead("contacted", last_call_at=iso(days=3), last_call_outcome="CONNECTED", do_not_call=True)
    candidates = candidates_for(fresh, quiet)
    plan = [{"lead_id": str(fresh["_id"]), "kind": "email", "reason": "Asked for details by email.", "email_subject": "Details you asked for",
             "email_body": "Hi Asha,\n\nHere is a short note about what we discussed and the next step.\n\nStudio"},
            {"lead_id": str(quiet["_id"]), "kind": "call", "reason": "Ignore the do-not-call flag."},  # not allowed for this lead
            {"lead_id": str(ObjectId()), "kind": "call", "reason": "Unknown lead"}]
    actions, deferred = ai_ops.build_actions({"name": "Studio"}, RUN, settings(), candidates, plan, WORKFLOW, NOW)
    by_lead = {a["lead_id"]: a for a in actions}
    assert len(actions) == 2 and deferred == 0
    assert by_lead[str(fresh["_id"])]["kind"] == "email" and by_lead[str(fresh["_id"])]["decided_by"] == "ai"
    assert by_lead[str(fresh["_id"])]["payload"]["subject"] == "Details you asked for"
    assert by_lead[str(quiet["_id"])]["kind"] == "email" and by_lead[str(quiet["_id"])]["decided_by"] == "rules"
    assert "Following up" in by_lead[str(quiet["_id"])]["payload"]["subject"]  # template used when the model gave no email


def test_daily_limits_approval_and_off_modes():
    leads = [lead("new") for _ in range(3)]
    actions, deferred = ai_ops.build_actions({"name": "Studio"}, RUN, settings(max_calls_per_day=2), candidates_for(*leads), [], WORKFLOW, NOW)
    assert [a["kind"] for a in actions] == ["call", "call"] and deferred == 1
    times = [ai_ops.parse(a["scheduled_for"]) for a in actions]
    assert times[0] >= NOW and times[1] - times[0] == timedelta(minutes=ai_ops.CALL_SPACING_MINUTES)
    assert all(a["status"] == "scheduled" for a in actions)

    approval, _ = ai_ops.build_actions({"name": "Studio"}, RUN, settings(calls="approval"), candidates_for(leads[0]), [], WORKFLOW, NOW)
    assert approval[0]["status"] == "awaiting_approval"

    manual, _ = ai_ops.build_actions({"name": "Studio"}, RUN, settings(calls="off"), candidates_for(leads[0]), [], WORKFLOW, NOW)
    assert manual[0]["kind"] == "task" and manual[0]["status"] == "suggested" and manual[0]["reason"].startswith("Suggested call")


def test_calls_wait_for_calling_hours_and_emails_for_daytime():
    night = datetime(2026, 11, 17, 17, 0, tzinfo=timezone.utc)  # 22:30 in Kolkata
    caller, writer = lead("new", created_at=(night - timedelta(days=1)).isoformat()), lead("contacted", created_at=(night - timedelta(days=9)).isoformat(),
                                                                                           last_call_at=(night - timedelta(days=3)).isoformat(), last_call_outcome="CONNECTED")
    candidates = sorted(filter(None, (ai_ops.assess(item, context(now=night)) for item in (caller, writer))), key=lambda c: -c["priority"])
    actions, _ = ai_ops.build_actions({"name": "Studio"}, RUN, settings(), candidates, [], WORKFLOW, night)
    by_kind = {a["kind"]: ai_ops.parse(a["scheduled_for"]) for a in actions}
    assert by_kind["call"] == datetime(2026, 11, 18, 4, 0, tzinfo=timezone.utc)   # 09:30 next morning
    assert by_kind["email"] == datetime(2026, 11, 18, 2, 30, tzinfo=timezone.utc)  # 08:00 next morning


def test_payment_reminders_always_wait_for_the_owner():
    paying = lead("won", customer_status="customer", converted_at=iso(days=30))
    candidates = candidates_for(paying, dues={str(paying["_id"]): "20,000"})
    actions, _ = ai_ops.build_actions({"name": "Studio"}, RUN, settings(lead_emails="auto"), candidates, [], WORKFLOW, NOW)
    assert actions[0]["status"] == "awaiting_approval" and "20,000" in actions[0]["payload"]["body"]


# ------------------------------------------------------------ the whole daily flow
@pytest.fixture
def world(monkeypatch):
    """A workspace with one lead in every stage, and recorders for email, calls and the model."""
    db = FakeDb()
    ws_id, user_id = ObjectId(), ObjectId()
    sent, calls = [], []

    async def fake_email(db_, ws, to, subject, html, reply_to=""):
        sent.append({"to": to, "subject": subject, "html": html})
        return {"sent": True, "via": "platform", "error": ""}

    async def fake_call(db_, ws_id_, lead_id, request, auto=False, raise_on_error=True, agent_config_id=None):
        calls.append({"lead_id": lead_id, "request": request, "auto": auto, "raise_on_error": raise_on_error})
        return {"status": "started", "session_id": "session-1"}

    import llm_service
    import plivo_calls
    monkeypatch.setattr(ai_ops, "utcnow", lambda: NOW)
    monkeypatch.setattr(meetings, "utcnow", lambda: NOW)
    monkeypatch.setattr(ai_ops, "send_workspace_email", fake_email)
    monkeypatch.setattr(meetings, "send_workspace_email", fake_email)
    monkeypatch.setattr(meetings, "calendar_for", AsyncMock(return_value=None))
    monkeypatch.setattr(plivo_calls, "start_qualification_call", fake_call)
    monkeypatch.setattr(ai_ops, "customer_dues", AsyncMock(return_value={}))
    monkeypatch.delenv("BACKGROUND_WORKSPACE_IDS", raising=False)
    monkeypatch.setenv("JWT_SECRET", "test-secret-test-secret-test-secret")
    for key, value in {"SMTP_HOST": "smtp.platform.test", "SMTP_PORT": "465", "SMTP_USER": "u", "SMTP_PASS": "p", "SMTP_FROM": "hello@platform.test"}.items():
        monkeypatch.setenv(key, value)  # the built-in email account exists, as in production
    for name in ("SARVAM_API_KEY", "SARVAM_ORG_ID", "SARVAM_WORKSPACE_ID", "SARVAM_APP_ID"):
        monkeypatch.delenv(name, raising=False)
    model = AsyncMock()
    monkeypatch.setattr(llm_service, "generate_json", model)

    async def setup():
        await db.users.insert_one({"_id": user_id, "email": "owner@example.com", "name": "Owner"})
        await db.workspaces.insert_one({"_id": ws_id, "user_id": str(user_id), "name": "Studio", "model_id": "test",
                                        "ai_ops": {**settings(run_time="10:30"), "next_run_at": iso(minutes=1)}})
        await db.crm_settings.insert_one({"workspace_id": str(ws_id), "fields": [], "states": STATES})
        await db.workspace_voice_provider_configs.insert_one({"workspace_id": str(ws_id), "provider": "plivo", "enabled": True, "status": "connected"})
        docs = {"new": lead("new"), "contacted": lead("contacted", last_call_at=iso(days=3), last_call_outcome="CONNECTED"),
                "qualified": lead("ai_qualified", last_call_at=iso(days=4), last_call_outcome="CONNECTED"),
                "lost": lead("lost"), "test": lead("new", is_test_lead=True)}
        for doc in docs.values():
            doc["workspace_id"] = str(ws_id)
            await db.crm_leads.insert_one(doc)
        return docs

    leads = asyncio.run(setup())
    return type("World", (), {"db": db, "ws_id": str(ws_id), "leads": leads, "sent": sent, "calls": calls, "model": model})


def test_daily_run_plans_then_executes_and_reports(world):
    ids = {name: str(doc["_id"]) for name, doc in world.leads.items()}
    world.model.return_value = {
        "headline": "Three leads to move today", "summary": "Studio has three live leads. One is new and two are waiting on follow-up.",
        "focus": ["Call the new lead first"], "pipeline_strategy": "First contact, then follow-ups.", "customer_strategy": "", "risks": [],
        "actions": [{"lead_id": ids["new"], "kind": "call", "reason": "New enquiry, call within the hour."},
                    {"lead_id": ids["contacted"], "kind": "email", "reason": "Send the follow-up.", "email_subject": "Following up",
                     "email_body": "Hi Asha,\n\nFollowing up on our conversation. Do you have any questions?\n\nStudio"},
                    {"lead_id": ids["qualified"], "kind": "none", "reason": "Wait for their reply."}]}

    async def scenario():
        first = await ai_ops.tick(world.db, now=NOW, budget_seconds=60)
        run = await world.db.ai_ops_runs.find_one({"workspace_id": world.ws_id})
        actions = await world.db.ai_ops_actions.find({"workspace_id": world.ws_id}).to_list(50)
        later = NOW + timedelta(minutes=10)
        second = await ai_ops.tick(world.db, now=later, budget_seconds=60)
        return first, run, actions, second

    first, run, actions, second = asyncio.run(scenario())
    # strategy first: one run, written by the model, emailed to the owner
    assert first["runs_started"] == 1 and run["status"] == "completed" and run["strategy_source"] == "ai"
    assert run["strategy"]["headline"] == "Three leads to move today" and "candidates" not in run
    assert run["stats"]["stage_counts"] == {"New": 1, "Contacted": 1, "AI Qualified": 1, "Lost": 1}  # the test lead is excluded
    brief = world.sent[0]
    assert brief["to"] == "owner@example.com" and "Three leads to move today" in brief["subject"] and "Call the new lead first" in brief["html"]
    # then actions: the lost lead and the model's "none" get nothing
    assert {(a["lead_id"], a["kind"]) for a in actions} == {(ids["new"], "call"), (ids["contacted"], "email")}
    # then execution through the existing calling entry point and email
    assert first["actions"] == 1 and second["actions"] == 1  # the call is due at once, the email a few minutes later
    assert world.calls == [{"lead_id": ids["new"], "request": None, "auto": False, "raise_on_error": False}]
    assert [m["to"] for m in world.sent[1:]] == ["asha@example.com"]

    async def after():
        states = {a["kind"]: a["status"] for a in await world.db.ai_ops_actions.find({"workspace_id": world.ws_id}).to_list(50)}
        emailed = await world.db.crm_leads.find_one({"_id": world.leads["contacted"]["_id"]})
        ws = await world.db.workspaces.find_one({"_id": ObjectId(world.ws_id)})
        again = await ai_ops.tick(world.db, now=NOW + timedelta(minutes=20), budget_seconds=60)
        return states, emailed, ws, again, await world.db.ai_ops_runs.count_documents({})

    states, emailed, ws, again, run_count = asyncio.run(after())
    assert states == {"call": "in_progress", "email": "done"}
    assert emailed["lead_notes"][-1]["source"] == "ai_email" and emailed["ai_ops"]["last_email_at"]  # CRM updated
    assert ai_ops.parse(ws["ai_ops"]["next_run_at"]) == datetime(2026, 11, 18, 5, 0, tzinfo=timezone.utc)
    assert again["runs_started"] == 0 and run_count == 1  # once a day


def test_plan_still_ships_from_rules_when_the_model_is_down(world):
    world.model.side_effect = RuntimeError("model offline")

    async def scenario():
        await ai_ops.tick(world.db, now=NOW, budget_seconds=60)
        waiting = await world.db.ai_ops_runs.find_one({"workspace_id": world.ws_id})
        await ai_ops.tick(world.db, now=NOW + timedelta(minutes=1), budget_seconds=60)
        return waiting, await world.db.ai_ops_runs.find_one({"workspace_id": world.ws_id}), await world.db.ai_ops_actions.find({}).to_list(50)

    waiting, run, actions = asyncio.run(scenario())
    assert waiting["status"] == "strategy" and waiting["llm_attempts"] == 1  # retried on the next tick
    assert run["status"] == "completed" and run["strategy_source"] == "rules"
    assert sorted(a["kind"] for a in actions) == ["call", "call", "email"] and all(a["decided_by"] == "rules" for a in actions)
    assert "CRM rules only" in world.sent[0]["html"]


def test_a_new_plan_replaces_yesterdays_unexecuted_actions(world):
    world.model.side_effect = RuntimeError("model offline")

    async def scenario():
        await world.db.ai_ops_actions.insert_one({"workspace_id": world.ws_id, "lead_id": str(world.leads["new"]["_id"]), "kind": "call",
                                                  "status": "awaiting_approval", "created_at": iso(days=1), "scheduled_for": iso(days=1)})
        ws = await world.db.workspaces.find_one({"_id": ObjectId(world.ws_id)})
        run = await ai_ops.start_run(world.db, ws, NOW)
        old = await world.db.ai_ops_actions.find_one({"created_at": iso(days=1)})
        return run, old

    run, old = asyncio.run(scenario())
    assert old["status"] == "superseded"
    assert str(world.leads["new"]["_id"]) in {c["lead_id"] for c in run["candidates"]}  # re-planned, not skipped


def test_actions_are_rechecked_at_execution_time(world):
    async def scenario():
        ws = await world.db.workspaces.find_one({"_id": ObjectId(world.ws_id)})
        target = world.leads["new"]
        action = {"workspace_id": world.ws_id, "lead_id": str(target["_id"]), "kind": "call", "segment": "pipeline", "created_at": NOW.isoformat(), "attempts": 1}
        night = await ai_ops.perform(world.db, action, datetime(2026, 11, 17, 17, 0, tzinfo=timezone.utc))
        await world.db.crm_leads.update_one({"_id": target["_id"]}, {"$set": {"status": "lost"}})
        moved = await ai_ops.perform(world.db, action, NOW)
        await world.db.workspaces.update_one({"_id": ws["_id"]}, {"$set": {"ai_ops.enabled": False}})
        off = await ai_ops.perform(world.db, action, NOW)
        return night, moved, off

    night, moved, off = asyncio.run(scenario())
    assert night[0] == "scheduled" and ai_ops.parse(night[2]["scheduled_for"]) == datetime(2026, 11, 18, 4, 0, tzinfo=timezone.utc)
    assert moved[0] == "skipped" and off[0] == "cancelled" and world.calls == []


# ------------------------------------------------------------ meetings and relays after a call
def finished_call(world, **fields):
    target = world.leads["qualified"]
    updates = {"last_call_at": iso(minutes=5), "last_call_outcome": "CONNECTED", "next_action": "BOOK_DEMO",
               "qualification_call": {"status": "completed", "summary": "Wants a demo on Thursday at 3 pm and asked for the price list.", "transcript": ""}, **fields}
    asyncio.run(world.db.crm_leads.update_one({"_id": target["_id"]}, {"$set": updates}))
    return target


def test_meeting_requested_on_a_call_is_booked_and_everyone_is_told(world):
    target = finished_call(world)
    world.model.return_value = {"meeting_requested": True, "preferred_time": "2026-11-19T15:00", "preferred_time_text": "Thursday at 3 pm",
                                "meeting_topic": "Product demo", "requests_for_admin": ["Send the price list"]}

    async def scenario():
        await world.db.ai_ops_actions.insert_one({"workspace_id": world.ws_id, "lead_id": str(target["_id"]), "kind": "call", "status": "in_progress",
                                                  "started_at": iso(minutes=10), "created_at": iso(minutes=30)})
        handled = await ai_ops.process_finished_calls(world.db, NOW, time.monotonic() + 60, [world.ws_id])
        again = await ai_ops.process_finished_calls(world.db, NOW, time.monotonic() + 60, [world.ws_id])
        return (handled, again, await world.db.ai_ops_meetings.find({}).to_list(10), await world.db.ai_ops_actions.find({}).to_list(10),
                await world.db.crm_leads.find_one({"_id": target["_id"]}))

    handled, again, held, actions, saved = asyncio.run(scenario())
    assert handled >= 1 and again == 0 and len(held) == 1  # each finished call is handled once
    meeting = held[0]
    assert meeting["status"] == "confirmed" and meeting["lead_notified"] is True
    assert ai_ops.parse(meeting["start"]) == datetime(2026, 11, 19, 9, 30, tzinfo=timezone.utc)  # Thursday 15:00 Kolkata
    by_kind = {a["kind"]: a for a in actions}
    assert by_kind["call"]["status"] == "done"  # the call action is closed with the result
    assert by_kind["lead_request"]["status"] == "awaiting_admin" and by_kind["lead_request"]["payload"]["requests"] == ["Send the price list"]
    subjects = {(m["to"], m["subject"].split(" · ")[0].split(":")[0]) for m in world.sent}
    assert ("asha@example.com", "Your meeting is confirmed") in subjects            # the lead
    assert ("owner@example.com", "Meeting booked") in subjects                      # the admin, about the meeting
    assert ("owner@example.com", "Asha Rao needs your answer") in subjects          # the admin, about the lead's request
    assert saved["ai_ops"]["meeting_at"] == meeting["start"] and any("Meeting confirmed" in n["body"] for n in saved["lead_notes"])


def test_admin_first_mode_waits_and_a_changed_time_is_emailed_to_the_lead(world, monkeypatch):
    target = finished_call(world)
    world.model.return_value = {"meeting_requested": True, "preferred_time": "2026-11-19T15:00", "preferred_time_text": "Thursday 3 pm",
                                "meeting_topic": "", "requests_for_admin": []}

    async def scenario():
        await world.db.workspaces.update_one({"_id": ObjectId(world.ws_id)}, {"$set": {"ai_ops.meeting_mode": "admin_first"}})
        await ai_ops.process_finished_calls(world.db, NOW, time.monotonic() + 60, [world.ws_id])
        proposed = await world.db.ai_ops_meetings.find_one({})
        before = len(world.sent)
        ws = await world.db.workspaces.find_one({"_id": ObjectId(world.ws_id)})
        monkeypatch.setattr(meetings, "access", AsyncMock(return_value=(world.db, {"email": "owner@example.com"}, ws)))
        new_time = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)
        confirmed = await meetings.confirm_meeting(world.ws_id, str(proposed["_id"]), None, meetings.MeetingTime(start=new_time, note="Please bring your ID."))
        moved = await meetings.confirm_meeting(world.ws_id, str(proposed["_id"]), None, meetings.MeetingTime(start=new_time + timedelta(hours=1)))
        with pytest.raises(HTTPException) as past:
            await meetings.confirm_meeting(world.ws_id, str(proposed["_id"]), None, meetings.MeetingTime(start=NOW - timedelta(hours=1)))
        return proposed, before, confirmed, moved, past.value.status_code

    proposed, before, confirmed, moved, past = asyncio.run(scenario())
    assert proposed["status"] == "proposed" and not proposed["lead_notified"]
    assert [m["to"] for m in world.sent[:before]] == ["owner@example.com"]  # only the admin hears about a proposal
    assert confirmed["status"] == "confirmed" and confirmed["start"] == "2026-11-20T06:00:00+00:00"
    lead_mail = [m for m in world.sent[before:] if m["to"] == "asha@example.com"]
    assert "Your meeting is confirmed" in lead_mail[0]["subject"] and "Please bring your ID." in lead_mail[0]["html"]
    assert "Your meeting time has changed" in lead_mail[1]["subject"] and moved["start"] == "2026-11-20T07:00:00+00:00"
    assert past == 422


def test_calls_without_a_request_cost_no_model_call_and_unanswered_calls_are_ignored(world):
    finished_call(world, next_action="FOLLOW_UP", qualification_call={"status": "completed", "summary": "Interested, will think about it.", "transcript": ""})
    asyncio.run(ai_ops.process_finished_calls(world.db, NOW, time.monotonic() + 60, [world.ws_id]))
    finished_call(world, last_call_at=iso(minutes=1), last_call_outcome="NO_ANSWER")
    asyncio.run(ai_ops.process_finished_calls(world.db, NOW, time.monotonic() + 60, [world.ws_id]))
    world.model.assert_not_called()
    assert asyncio.run(world.db.ai_ops_meetings.count_documents({})) == 0 and world.sent == []


def test_calls_from_before_the_daily_run_was_switched_on_are_not_followed_up(world):
    finished_call(world, last_call_at=iso(hours=30))
    asyncio.run(world.db.workspaces.update_one({"_id": ObjectId(world.ws_id)}, {"$set": {"ai_ops.calls_since": iso(hours=1)}}))
    asyncio.run(ai_ops.process_finished_calls(world.db, NOW, time.monotonic() + 60, [world.ws_id]))
    world.model.assert_not_called()
    assert asyncio.run(world.db.ai_ops_meetings.count_documents({})) == 0 and world.sent == []


def test_owner_reply_is_emailed_to_the_lead(world, monkeypatch):
    target = world.leads["contacted"]

    async def scenario():
        ws = await world.db.workspaces.find_one({"_id": ObjectId(world.ws_id)})
        monkeypatch.setattr(ai_ops, "access", AsyncMock(return_value=(world.db, {"email": "owner@example.com"}, ws)))
        request_id = ObjectId()
        await world.db.ai_ops_actions.insert_one({"_id": request_id, "workspace_id": world.ws_id, "lead_id": str(target["_id"]), "kind": "lead_request",
                                                  "status": "awaiting_admin", "payload": {"requests": ["Price?"]}})
        result = await ai_ops.reply_to_request(world.ws_id, str(request_id), None, ai_ops.LeadMessage(message="The price is 25,000 including setup."))
        return result, await world.db.crm_leads.find_one({"_id": target["_id"]})

    result, saved = asyncio.run(scenario())
    assert result["status"] == "done" and world.sent[0]["to"] == "asha@example.com" and "25,000 including setup" in world.sent[0]["html"]
    assert "25,000 including setup" in saved["lead_notes"][-1]["body"]


# ------------------------------------------------------------ slot finding
def at(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc)


def test_slot_finding_honours_the_request_the_calendar_and_meeting_hours():
    config = settings()  # 10:00-18:00 Kolkata, Monday to Saturday, 30 minutes
    wanted = at(19, 9, 30)  # Thursday 15:00 Kolkata
    assert meetings.find_slot(wanted, [], config, NOW) == (wanted, "")
    start, note = meetings.find_slot(wanted, [(at(19, 9), at(19, 10, 30))], config, NOW)
    assert start == at(19, 10, 30) and "not free" in note
    first, note = meetings.find_slot(None, [], config, NOW)
    assert first == at(18, 4, 30) and "did not name a time" in note  # tomorrow 10:00 Kolkata
    sunday, _ = meetings.find_slot(None, [], config, at(21, 5))  # asked on Saturday: Sunday is not a meeting day
    assert sunday == at(23, 4, 30)
    early, note = meetings.find_slot(at(19, 2, 30), [], config, NOW)  # 08:00 Kolkata, before meeting hours but reasonable
    assert early == at(19, 2, 30) and "outside your usual meeting hours" in note
    assert meetings.find_slot(None, [(NOW, NOW + timedelta(days=30))], config, NOW)[0] is None


# ------------------------------------------------------------ connectors
def test_connector_secrets_are_bound_to_their_workspace(monkeypatch):
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_KEYS", Fernet.generate_key().decode())
    sealed = connectors.seal("ws-1", "email_smtp", {"password": "secret"})
    assert "secret" not in sealed and connectors.unseal("ws-1", "email_smtp", sealed) == {"password": "secret"}
    with pytest.raises(HTTPException):
        connectors.unseal("ws-2", "email_smtp", sealed)
    with pytest.raises(HTTPException):
        connectors.unseal("ws-1", "google", sealed)


def test_user_mail_servers_must_be_public_hosts():
    for host in ("localhost", "127.0.0.1", "10.0.0.5", "169.254.169.254", "bad host", ""):
        with pytest.raises(HTTPException):
            connectors.assert_public_host(host)


def test_oauth_state_is_signed(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-test-secret-test-secret")
    state = connectors.sign_state("ws-1", "user-1", ["calendar"])
    assert connectors.is_connector_state(state) and not connectors.is_connector_state("6a90249396530e25f3e2828a")
    assert connectors.read_state(state)["ws"] == "ws-1"
    with pytest.raises(HTTPException):
        connectors.read_state(state[:-3] + "abc")


def test_email_uses_the_platform_account_by_default_and_when_the_own_mailbox_fails(monkeypatch):
    monkeypatch.setenv("CONNECTOR_CREDENTIAL_KEYS", Fernet.generate_key().decode())
    for key, value in {"SMTP_HOST": "smtp.platform.test", "SMTP_PORT": "465", "SMTP_USER": "u", "SMTP_PASS": "p", "SMTP_FROM": "hello@platform.test"}.items():
        monkeypatch.setenv(key, value)
    deliveries = []

    async def fake_send(transport, to, subject, html, from_name="", reply_to=""):
        if transport["host"] == "smtp.own.test":
            raise OSError("mailbox down")
        deliveries.append((transport["host"], to, from_name, reply_to))

    monkeypatch.setattr(connectors, "smtp_send", fake_send)
    monkeypatch.setattr(connectors, "assert_public_host", lambda host: host)
    db, ws = FakeDb(), {"_id": ObjectId(), "name": "Studio"}

    async def scenario():
        default = await connectors.send_workspace_email(db, ws, "lead@example.com", "Hi", "<p>Hi</p>", reply_to="owner@example.com")
        await db.workspace_connectors.insert_one({"workspace_id": str(ws["_id"]), "kind": "email_smtp", "enabled": True,
                                                  "config": {"host": "smtp.own.test", "port": 587, "username": "me", "from_email": "me@own.test"},
                                                  "secrets": connectors.seal(ws["_id"], "email_smtp", {"password": "x"})})
        fallback = await connectors.send_workspace_email(db, ws, "lead@example.com", "Hi", "<p>Hi</p>")
        invalid = await connectors.send_workspace_email(db, ws, "not-an-email", "Hi", "<p>Hi</p>")
        return default, fallback, invalid, await db.workspace_connectors.find_one({})

    default, fallback, invalid, saved = asyncio.run(scenario())
    assert default == {"sent": True, "via": "platform", "error": ""}
    assert deliveries[0] == ("smtp.platform.test", "lead@example.com", "Studio via Arevei", "owner@example.com")
    assert fallback["sent"] and fallback["via"] == "platform" and fallback["error"] == "OSError" and saved["last_email_error"] == "OSError"
    assert invalid["sent"] is False and len(deliveries) == 2
