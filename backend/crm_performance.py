"""Read-only CRM reporting and human review of existing qualification results."""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from crm import db_from, lead_query, require_workspace_access
from models import now_iso
from plivo_calls import is_junk_lead, lead_phone_from_doc, parse_iso_datetime, session_counts_as_call_attempt

router = APIRouter(prefix="/workspaces/{ws_id}/crm", tags=["CRM performance"])


def oid(value):
    if not ObjectId.is_valid(value):
        raise HTTPException(422, "Invalid identifier")
    return ObjectId(value)


def qualification_source(lead):
    q = lead.get("qualification_call") or {}
    return {"call_uuid": q.get("call_uuid"), "session_id": q.get("session_id"),
            "engine_result": q.get("engine_result") or {},
            "structured_qualification": q.get("structured_qualification") or {},
            "qualification_status": q.get("qualification_status"),
            "qualification_data": lead.get("qualification_data") or {}}


def has_qualification(source):
    return bool(source["engine_result"] or source["structured_qualification"] or source["qualification_data"])


def source_version(source):
    return hashlib.sha256(json.dumps(source, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def review_state(lead):
    source = qualification_source(lead)
    saved = lead.get("qualification_review") or {}
    current = saved.get("source_version") == source_version(source)
    review = {k: saved.get(k) for k in ("status", "reviewed_by", "reviewed_by_name", "reviewed_at", "note", "incorrect_fields")} if current else {}
    return {"has_qualification": has_qualification(source), "source_version": source_version(source),
            "source": source, "stale": bool(saved) and not current,
            "review": {"status": "not_reviewed", "note": "", "incorrect_fields": [], **review}}


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["not_reviewed", "correct", "incorrect"]
    source_version: str = Field(min_length=64, max_length=64)
    note: str = Field(default="", max_length=4000)
    incorrect_fields: list[str] = Field(default_factory=list, max_length=50)


async def owned_lead(ws_id, lead_id, request):
    oid(ws_id)
    user, _ = await require_workspace_access(request, ws_id)
    lead = await db_from(request).crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not lead:
        raise HTTPException(404, "Lead not found")
    return user, lead


@router.get("/leads/{lead_id}/qualification-review")
async def get_review(ws_id: str, lead_id: str, request: Request):
    _, lead = await owned_lead(ws_id, lead_id, request)
    return review_state(lead)


@router.put("/leads/{lead_id}/qualification-review")
async def save_review(ws_id: str, lead_id: str, request: Request, body: ReviewInput):
    user, lead = await owned_lead(ws_id, lead_id, request)
    state = review_state(lead)
    if not state["has_qualification"]:
        raise HTTPException(409, "This lead has no AI qualification to review")
    if body.source_version != state["source_version"]:
        raise HTTPException(409, "The AI qualification changed. Reload the review before saving.")
    source = state["source"]
    facts = source["engine_result"].get("qualification_data") or source["structured_qualification"] or source["qualification_data"]
    fields = sorted(set(body.incorrect_fields))
    if any(field not in facts for field in fields):
        raise HTTPException(422, "Incorrect fields must belong to the displayed qualification facts")
    if fields and body.status != "incorrect":
        raise HTTPException(422, "Only an Incorrect review can mark incorrect fields")
    now = now_iso()
    review = {"status": body.status, "note": body.note.strip(), "incorrect_fields": fields,
              "reviewed_by": str(user["_id"]), "reviewed_by_name": user.get("name") or "Workspace user",
              "reviewed_at": now, "source_version": state["source_version"]}
    # Both writes are atomic on the lead. A concurrent webhook or review cannot be overwritten.
    query = {"_id": lead["_id"], "workspace_id": ws_id,
             "qualification_call": lead.get("qualification_call"),
             "qualification_data": lead.get("qualification_data"),
             "qualification_review": lead.get("qualification_review")}
    audit = {**review, "type": "qualification_review", "created_at": now,
             "label": f"AI qualification review: {state['review']['status']} → {body.status}",
             "previous_status": state["review"]["status"], "new_status": body.status,
             "previous_review": lead.get("qualification_review"), "source": source}
    result = await db_from(request).crm_leads.update_one(query, {
        "$set": {"qualification_review": review, "updated_at": now},
        "$push": {"timeline": audit}})
    if not result.matched_count:
        raise HTTPException(409, "The lead changed while saving. Reload the review and try again.")
    return review_state({**lead, "qualification_review": review})


def date_bounds(start, end):
    end = end or datetime.now(timezone.utc).date()
    start = start or end - timedelta(days=29)
    if start > end:
        raise HTTPException(422, "Start date must be on or before end date")
    if end == date.max:
        raise HTTPException(422, "End date is out of range")
    return (datetime.combine(start, datetime.min.time(), timezone.utc),
            datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc))


def performance_pipeline(ws_id, start, end, status=None):
    match = lead_query(ws_id)
    match["created_at"] = {"$gte": start.isoformat(), "$lt": end.isoformat()}
    if status:
        match["status"] = status
    pipeline = [{"$match": match}, {"$project": {key: 1 for key in (
        "created_at", "status", "lead_status", "do_not_call", "phone", "field_values.phone",
        "qualification_call.call_uuid", "qualification_call.session_id", "qualification_call.engine_result",
        "qualification_call.structured_qualification", "qualification_call.qualification_status",
        "qualification_call.qualification_category", "qualification_call.qualification_profile_id",
        "qualification_call.call_timestamp", "qualification_call.created_at", "qualification_call.status",
        "qualification_call.duration", "qualification_data", "qualification_review", "qualification_profile_id",
        "next_action")}}]
    # Existing workspace/lead indexes support these joins. No provider payloads or transcripts leave Mongo.
    projections = {
        "plivo_call_sessions": ("provider", "provider_identifiers", "provider_call_id", "call_uuid", "started_at", "created_at", "status", "call_status", "duration", "answered_at", "engine_result", "profile_id"),
        "crm_call_logs": ("provider", "provider_call_id", "created_at", "profile_id", "result", "call_result.duration_seconds", "call_result.call_status", "call_result.answered_at", "call_result.terminal"),
        "tasks": ("action_type", "status"),
    }
    for collection, fields in projections.items():
        extra = {"kind": "qualification_engine"} if collection == "crm_call_logs" else {"source": "qualification_engine", "status": {"$in": ["pending", "running"]}} if collection == "tasks" else {}
        pipeline.append({"$lookup": {"from": collection, "let": {"lead": {"$toString": "$_id"}},
            "pipeline": [{"$match": {"workspace_id": ws_id, **extra, "$expr": {"$eq": ["$lead_id", "$$lead"]}}},
                         {"$project": {key: 1 for key in fields}}], "as": collection}})
    return pipeline


def in_period(value, start, end):
    parsed = parse_iso_datetime(value)
    return parsed is not None and start <= parsed < end


def canonical_calls(lead):
    """Count a session once, merging its decision log; callbacks are never additional calls."""
    calls, aliases = [], {}
    for session in lead.get("plivo_call_sessions", []):
        if not session_counts_as_call_attempt(session):
            continue
        provider = session.get("provider") or "plivo"
        item = {"created_at": session.get("created_at"), "status": session.get("call_status") or session.get("status"),
                "duration": session.get("duration"), "answered_at": session.get("answered_at"),
                "result": session.get("engine_result") or {},
                "profile_id": session.get("profile_id")}
        calls.append(item)
        for ident in [str(session["_id"]), session.get("provider_call_id"), session.get("call_uuid"), *(session.get("provider_identifiers") or {}).values()]:
            if ident and isinstance(ident, str):
                aliases[(provider, ident)] = item
    for log in lead.get("crm_call_logs", []):
        key = (log.get("provider") or "plivo", log.get("provider_call_id") or str(log["_id"]))
        item = aliases.get(key)
        if item is None:
            item = {"created_at": log.get("created_at")}
            calls.append(item)
            aliases[key] = item
        call = log.get("call_result") or {}
        for field, value in {"status": call.get("call_status"), "duration": call.get("duration_seconds"),
                             "answered_at": call.get("answered_at"), "result": log.get("result"),
                             "terminal": call.get("terminal"), "profile_id": log.get("profile_id")}.items():
            if value is not None:
                item[field] = value
    # Legacy leads may predate sessions/history. Use only their latest recorded call, never invent past attempts.
    q = lead.get("qualification_call") or {}
    if not calls and q.get("call_uuid"):
        calls.append({"created_at": q.get("call_timestamp") or q.get("created_at"), "status": q.get("status"),
                      "duration": q.get("duration"), "result": q.get("engine_result") or {},
                      "profile_id": q.get("qualification_profile_id")})
    return calls


def rate(numerator, denominator):
    return round(100 * numerator / denominator, 1) if denominator else None


class PerformanceTotals:
    def __init__(self):
        self.funnel = {k: 0 for k in ("total_leads", "eligible_leads", "leads_attempted")}
        self.calling = {k: 0 for k in ("calls_attempted", "connected", "no_answer", "busy", "failed", "completed_conversations")}
        self.qualification = {k: 0 for k in ("qualified", "disqualified", "follow_up_required", "completed", "ai_results")}
        self.reviews = {k: 0 for k in ("reviewed", "correct", "incorrect", "not_reviewed")}
        self.duration_sum = 0
        self.duration_count = 0

    def add(self, lead, start, end, profile_id=None):
        q = lead.get("qualification_call") or {}
        calls = [call for call in canonical_calls(lead) if in_period(call.get("created_at"), start, end)]
        current_profile = q.get("qualification_profile_id") or lead.get("qualification_profile_id")
        if profile_id and current_profile != profile_id and not any(c.get("profile_id") == profile_id for c in calls):
            return
        calls = [c for c in calls if not profile_id or c.get("profile_id") == profile_id]
        self.funnel["total_leads"] += 1
        if lead_phone_from_doc(lead) and not lead.get("do_not_call") and lead.get("lead_status") != "JUNK" and not is_junk_lead(lead):
            self.funnel["eligible_leads"] += 1
        self.funnel["leads_attempted"] += bool(calls)
        for call in calls:
            self.calling["calls_attempted"] += 1
            outcome = (call.get("result") or {}).get("call_outcome", "")
            status = str(call.get("status") or "").lower().replace("_", "-")
            connected = outcome in {"CONNECTED", "CALLBACK_REQUESTED", "DND_REQUESTED", "DROPPED_CALL", "WRONG_NUMBER"} if outcome else bool(call.get("answered_at")) or status in {"answered", "in-progress", "completed"}
            self.calling["connected"] += connected
            self.calling["no_answer"] += outcome in {"NO_ANSWER", "SWITCHED_OFF", "UNREACHABLE"} if outcome else status in {"no-answer", "unanswered", "timeout"}
            self.calling["busy"] += outcome == "BUSY" if outcome else status == "busy"
            self.calling["failed"] += outcome in {"TECHNICAL_ISSUE", "INVALID_NUMBER"} if outcome else status in {"failed", "error", "cancelled", "canceled"}
            completed = connected and outcome != "DROPPED_CALL" and call.get("terminal", True) and (status == "completed" or outcome in {"CONNECTED", "CALLBACK_REQUESTED", "DND_REQUESTED"})
            self.calling["completed_conversations"] += completed
            try:
                duration = float(call.get("duration"))
                if completed and 0 <= duration < float("inf"):
                    self.duration_sum += duration
                    self.duration_count += 1
            except (TypeError, ValueError):
                pass
        # Qualification/review describe the latest saved result, not old results from another profile.
        if profile_id and current_profile != profile_id:
            return
        source = qualification_source(lead)
        if not has_qualification(source):
            return
        self.qualification["ai_results"] += 1
        result = source["engine_result"]
        status = result.get("lead_status")
        qualified = status in {"QUALIFIED", "SALES_READY"} or not status and q.get("qualification_status") == "qualified"
        disqualified = status in {"UNQUALIFIED", "JUNK"} or not status and q.get("qualification_status") == "not_qualified"
        self.qualification["qualified"] += qualified
        self.qualification["disqualified"] += disqualified
        self.qualification["completed"] += qualified or disqualified
        follow_up = result.get("next_action") in {"FOLLOW_UP", "CALLBACK", "RETRY_CALL"} or status == "PARTIALLY_QUALIFIED" or any(t.get("action_type") in {"FOLLOW_UP", "CALLBACK", "RETRY_CALL"} for t in lead.get("tasks", []))
        self.qualification["follow_up_required"] += follow_up
        review = review_state(lead)["review"]["status"]
        self.reviews[review if review in {"correct", "incorrect"} else "not_reviewed"] += 1

    def output(self):
        self.reviews["reviewed"] = self.reviews["correct"] + self.reviews["incorrect"]
        self.reviews["accuracy"] = rate(self.reviews["correct"], self.reviews["reviewed"])
        self.calling["connection_rate"] = rate(self.calling["connected"], self.calling["calls_attempted"])
        self.calling["average_duration_seconds"] = round(self.duration_sum / self.duration_count, 1) if self.duration_count else None
        self.qualification["completion_rate"] = rate(self.qualification["completed"], self.qualification["ai_results"])
        return {"funnel": self.funnel, "calling": self.calling, "qualification": self.qualification, "reviews": self.reviews}


@router.get("/performance")
async def performance(ws_id: str, request: Request, start: date | None = None, end: date | None = None,
                      profile_id: str | None = None, status: str | None = Query(default=None, max_length=100)):
    oid(ws_id)
    await require_workspace_access(request, ws_id)
    db = db_from(request)
    if profile_id and not await db.qualification_profiles.find_one({"workspace_id": ws_id, "_id": oid(profile_id)}):
        raise HTTPException(404, "Qualification profile not found")
    lower, upper = date_bounds(start, end)
    totals = PerformanceTotals()
    async for lead in db.crm_leads.aggregate(performance_pipeline(ws_id, lower, upper, status)):
        totals.add(lead, lower, upper, profile_id)
    return {**totals.output(), "filters": {"start": lower.date().isoformat(), "end": (upper - timedelta(days=1)).date().isoformat(),
            "profile_id": profile_id, "status": status}, "date_basis": "lead_cohort_utc"}
