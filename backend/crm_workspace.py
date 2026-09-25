"""CRM pipeline and manual lead reminders, backed by existing leads and tasks."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from bson import ObjectId

from crm import apply_lead_filters, db_from, require_workspace_access, lead_query, doc_out
from models import now_iso
from workspace_modules import workspace_currency

router = APIRouter(prefix="/workspaces/{ws_id}/crm", tags=["CRM workspace"])


class StageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(min_length=1, max_length=100)


@router.patch("/pipeline/leads/{lead_id}")
async def move_lead(ws_id: str, lead_id: str, request: Request, body: StageInput):
    await access(request, ws_id)
    if not await db_from(request).crm_leads.find_one({**lead_query(ws_id), "_id": oid(lead_id)}):
        raise HTTPException(404, "Active lead not found")
    from crm import update_lead
    return await update_lead(ws_id, lead_id, request, {"status": body.status})


def oid(value):
    if not ObjectId.is_valid(value):
        raise HTTPException(422, "Invalid identifier")
    return ObjectId(value)


async def access(request, ws_id):
    oid(ws_id)
    return await require_workspace_access(request, ws_id)


@router.get("/pipeline")
async def pipeline(ws_id: str, request: Request, status: str = Query(max_length=100), search: str = Query(default="", max_length=200), campaign: str = Query(default="", max_length=200), created_from: datetime = Query(None), created_before: datetime = Query(None), offset: int = Query(default=0, ge=0), limit: int = Query(default=30, ge=1, le=100)):
    _, workspace = await access(request, ws_id)
    query = apply_lead_filters(lead_query(ws_id), search, campaign, created_from, created_before)
    query["status"] = status
    db = db_from(request)
    total = await db.crm_leads.count_documents(query)
    docs = await db.crm_leads.find(query, {"field_values.full_name": 1, "field_values.phone": 1, "field_values.email": 1, "full_name": 1, "phone": 1, "email": 1, "status": 1, "created_at": 1, "lead_status": 1, "opportunity": 1}).sort([("created_at", -1), ("_id", -1)]).skip(offset).limit(limit).to_list(limit)
    value = await db.crm_leads.aggregate([{"$match": query}, {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$opportunity.total_minor", 0]}}}}]).to_list(1)
    return {"items": [doc_out(doc) for doc in docs], "total": total,
            "value_minor": value[0]["total"] if value else 0, "currency": workspace_currency(workspace)}


@router.get("/pipeline-value")
async def pipeline_value(ws_id: str, request: Request, search: str = Query(default="", max_length=200), campaign: str = Query(default="", max_length=200), created_from: datetime = Query(None), created_before: datetime = Query(None), status: str = Query(default="all", max_length=100)):
    _, workspace = await access(request, ws_id)
    query = apply_lead_filters(lead_query(ws_id), search, campaign, created_from, created_before)
    if status != "all":
        query["status"] = status
    values = await db_from(request).crm_leads.aggregate([{"$match": query}, {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$opportunity.total_minor", 0]}}}}]).to_list(1)
    return {"value_minor": values[0]["total"] if values else 0, "currency": workspace_currency(workspace)}


class ReminderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=4000)
    due_at: datetime

    @field_validator("title")
    @classmethod
    def title_required(cls, value):
        if not value.strip():
            raise ValueError("Enter a reminder title")
        return value.strip()

    @field_validator("due_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Due time must include a timezone")
        return value.astimezone(timezone.utc)


class ReminderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "done", "cancelled"]


@router.post("/leads/{lead_id}/reminders")
async def create_reminder(ws_id: str, lead_id: str, request: Request, body: ReminderInput):
    user, _ = await access(request, ws_id)
    db = db_from(request)
    lead = await db.crm_leads.find_one({**lead_query(ws_id), "_id": oid(lead_id)})
    if not lead:
        raise HTTPException(404, "Active lead not found")
    now = now_iso()
    task = {"_id": ObjectId(), "workspace_id": ws_id, "lead_id": lead_id, "source": "crm_reminder",
            "title": body.title, "objective": body.note.strip(), "scheduled_time": body.due_at.isoformat(),
            "agent": "sales", "deliverable_type": "crm_follow_up", "requires_approval": True,
            "status": "pending", "created_by": str(user["_id"]), "created_at": now, "updated_at": now,
            "logs": [], "timeline": [{"status": "pending", "by": str(user["_id"]), "at": now}]}
    await db.tasks.insert_one(task)
    return doc_out(task)


@router.get("/reminders")
async def reminders(ws_id: str, request: Request, lead_id: str | None = None, start: datetime | None = None,
                    end: datetime | None = None, status: Literal["pending", "done", "cancelled", "all"] = "pending",
                    overdue: bool = False, offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100)):
    await access(request, ws_id)
    query = {"workspace_id": ws_id, "source": "crm_reminder"}
    if lead_id:
        oid(lead_id)
        query["lead_id"] = lead_id
    if status != "all":
        query["status"] = status
    for value in (start, end):
        if value and value.tzinfo is None:
            raise HTTPException(422, "Date filters must include a timezone")
    if start and end and start >= end:
        raise HTTPException(422, "End must be after start")
    if overdue:
        query["scheduled_time"] = {"$lt": now_iso()}
    elif start or end:
        query["scheduled_time"] = {**({"$gte": start.astimezone(timezone.utc).isoformat()} if start else {}), **({"$lt": end.astimezone(timezone.utc).isoformat()} if end else {})}
    db = db_from(request)
    total = await db.tasks.count_documents(query)
    docs = await db.tasks.find(query).sort([("scheduled_time", 1), ("_id", 1)]).skip(offset).limit(limit).to_list(limit)
    ids = [oid(doc["lead_id"]) for doc in docs]
    leads = await db.crm_leads.find({"workspace_id": ws_id, "_id": {"$in": ids}}, {"full_name": 1, "phone": 1, "field_values.full_name": 1, "field_values.phone": 1, "deleted_at": 1}).to_list(limit)
    by_id = {str(lead["_id"]): lead for lead in leads}
    items = []
    for doc in docs:
        lead = by_id.get(doc["lead_id"], {})
        values = lead.get("field_values") or {}
        items.append({**doc_out(doc), "lead_name": values.get("full_name") or lead.get("full_name") or values.get("phone") or lead.get("phone") or "Unavailable lead",
                      "lead_phone": values.get("phone") or lead.get("phone") or "", "lead_available": bool(lead) and not lead.get("deleted_at")})
    return {"items": items, "total": total}


@router.patch("/reminders/{reminder_id}")
async def update_reminder(ws_id: str, reminder_id: str, request: Request, body: ReminderInput | ReminderStatus):
    user, _ = await access(request, ws_id)
    db = db_from(request)
    query = {"workspace_id": ws_id, "source": "crm_reminder", "_id": oid(reminder_id)}
    patch = {"status": body.status} if isinstance(body, ReminderStatus) else {"title": body.title, "objective": body.note.strip(), "scheduled_time": body.due_at.isoformat()}
    now = now_iso()
    result = await db.tasks.update_one(query, {"$set": {**patch, "updated_at": now}, "$push": {"timeline": {**patch, "by": str(user["_id"]), "at": now}}})
    if not result.matched_count:
        raise HTTPException(404, "Reminder not found")
    return doc_out(await db.tasks.find_one(query))
