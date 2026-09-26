import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from crm import db_from, require_workspace_access
from models import now_iso
from workspace_access import MEMBER_ROLES, member_context, permitted_leads

owner_router = APIRouter(prefix="/workspaces/{ws_id}/members", dependencies=[Depends(require_workspace_access)])
invite_router = APIRouter(prefix="/membership-invitations")
portal_router = APIRouter(prefix="/workspaces/{ws_id}/sales-portal")


class InvitationInput(BaseModel):
    sales_person_id: str
    email: EmailStr


@owner_router.get("")
async def list_members(ws_id: str, request: Request):
    db = db_from(request)
    rows = []
    async for doc in db.workspace_memberships.find({"workspace_id": ws_id, "role": {"$in": list(MEMBER_ROLES)}}):
        person = await db.crm_sales_people.find_one({"workspace_id": ws_id, "_id": ObjectId(doc["sales_person_id"])})
        rows.append({"id": str(doc["_id"]), "name": (person or {}).get("name", "Member"), "email": doc.get("email"), "role": doc["role"], "active": doc.get("active", False), "sales_person_id": doc["sales_person_id"]})
    invitations = [{"id": str(doc["_id"]), "sales_person_id": doc["sales_person_id"], "email": doc["email"], "role": doc["role"], "expires_at": doc["expires_at"]} async for doc in db.workspace_invitations.find({"workspace_id": ws_id, "status": "pending", "expires_at": {"$gt": now_iso()}})]
    return {"items": rows, "invitations": invitations}


@owner_router.post("/invite")
async def invite_member(ws_id: str, request: Request, body: InvitationInput):
    db = db_from(request)
    if not ObjectId.is_valid(body.sales_person_id):
        raise HTTPException(422, "Choose a sales person")
    person = await db.crm_sales_people.find_one({"workspace_id": ws_id, "_id": ObjectId(body.sales_person_id), "active": True})
    if not person or person.get("role") not in MEMBER_ROLES:
        raise HTTPException(422, "Choose an active sales agent or channel partner")
    email = str(body.email).lower()
    if person.get("user_id"):
        linked = await db.users.find_one({"_id": ObjectId(person["user_id"])})
        if linked and linked["email"].lower() != email:
            raise HTTPException(409, "This sales record is already linked to another account")
    workspace = await db.workspaces.find_one({"_id": ObjectId(ws_id)})
    account = await db.users.find_one({"email": email})
    if account and str(account["_id"]) == workspace.get("user_id"):
        raise HTTPException(409, "The workspace owner already has access")
    token = secrets.token_urlsafe(32)
    doc = {"workspace_id": ws_id, "sales_person_id": body.sales_person_id, "email": email, "role": person["role"], "token_hash": hashlib.sha256(token.encode()).hexdigest(), "status": "pending", "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(), "created_at": now_iso()}
    await db.workspace_invitations.update_one({"_id": f"{ws_id}:{body.sales_person_id}"}, {"$set": doc}, upsert=True)
    return {"invite_path": f"/join/{token}", "expires_at": doc["expires_at"], "email": email}


@owner_router.patch("/{membership_id}")
async def set_membership(ws_id: str, membership_id: str, request: Request, body: dict = Body(...)):
    if set(body) != {"active"} or not isinstance(body["active"], bool):
        raise HTTPException(422, "Supply active true or false")
    result = await db_from(request).workspace_memberships.update_one({"_id": membership_id, "workspace_id": ws_id, "role": {"$in": list(MEMBER_ROLES)}}, {"$set": {"active": body["active"], "updated_at": now_iso()}})
    if not result.matched_count:
        raise HTTPException(404, "Member not found")
    if not body["active"]:
        doc = await db_from(request).workspace_memberships.find_one({"_id": membership_id, "workspace_id": ws_id})
        await db_from(request).workspace_invitations.update_many({"workspace_id": ws_id, "sales_person_id": doc["sales_person_id"], "status": "pending"}, {"$set": {"status": "revoked"}})
    return {"ok": True}


@owner_router.delete("/invitations/{invitation_id}")
async def revoke_invitation(ws_id: str, invitation_id: str, request: Request):
    await db_from(request).workspace_invitations.update_one({"_id": invitation_id, "workspace_id": ws_id}, {"$set": {"status": "revoked"}})
    return {"ok": True}


async def pending_invitation(db, token):
    if not 32 <= len(token) <= 100:
        raise HTTPException(404, "Invitation is unavailable")
    doc = await db.workspace_invitations.find_one({"token_hash": hashlib.sha256(token.encode()).hexdigest(), "status": "pending", "expires_at": {"$gt": now_iso()}})
    if not doc:
        raise HTTPException(410, "Invitation has expired, been revoked, or already accepted")
    person = await db.crm_sales_people.find_one({"workspace_id": doc["workspace_id"], "_id": ObjectId(doc["sales_person_id"]), "active": True, "role": doc["role"]})
    if not person:
        raise HTTPException(410, "Invitation is no longer available")
    return doc, person


@invite_router.get("/{token}")
async def invitation_info(token: str, request: Request):
    db = db_from(request)
    doc, person = await pending_invitation(db, token)
    workspace = await db.workspaces.find_one({"_id": ObjectId(doc["workspace_id"])})
    if not workspace:
        raise HTTPException(410, "Workspace is unavailable")
    return {"workspace_name": workspace.get("name", "Workspace"), "email": doc["email"], "role": doc["role"], "name": person["name"]}


@invite_router.post("/{token}/accept")
async def accept_invitation(token: str, request: Request):
    from auth import get_current_user
    db = db_from(request)
    user = await get_current_user(request, db)
    doc, person = await pending_invitation(db, token)
    user_id = str(user["_id"])
    if user["email"].lower() != doc["email"] or person.get("user_id") not in {None, user_id}:
        raise HTTPException(403, "Sign in with the invited email address")
    existing = await db.workspace_memberships.find_one({"workspace_id": doc["workspace_id"], "user_id": user_id})
    if existing and existing.get("sales_person_id") != doc["sales_person_id"]:
        raise HTTPException(409, "This account is already linked to another sales record in this workspace")
    claimed = await db.workspace_invitations.find_one_and_update({"_id": doc["_id"], "token_hash": doc["token_hash"], "status": "pending", "expires_at": {"$gt": now_iso()}}, {"$set": {"status": "accepting", "accepted_by": user_id}}, return_document=ReturnDocument.AFTER)
    if not claimed:
        raise HTTPException(409, "Invitation was already accepted or revoked")
    member_id = f"{doc['workspace_id']}:{user_id}"
    try:
        linked = await db.crm_sales_people.update_one({"workspace_id": doc["workspace_id"], "_id": person["_id"], "active": True, "role": doc["role"], "$or": [{"user_id": None}, {"user_id": user_id}]}, {"$set": {"user_id": user_id}})
        if not linked.matched_count:
            raise HTTPException(409, "Sales record is no longer available")
        await db.workspace_memberships.update_one({"_id": member_id, "sales_person_id": doc["sales_person_id"]}, {"$set": {"workspace_id": doc["workspace_id"], "user_id": user_id, "sales_person_id": doc["sales_person_id"], "email": doc["email"], "role": doc["role"], "active": True, "updated_at": now_iso()}}, upsert=True)
        await db.workspace_invitations.update_one({"_id": doc["_id"], "status": "accepting"}, {"$set": {"status": "accepted", "accepted_at": now_iso()}})
    except DuplicateKeyError:
        await db.workspace_invitations.update_one({"_id": doc["_id"], "token_hash": doc["token_hash"], "status": "accepting"}, {"$set": {"status": "pending"}})
        raise HTTPException(409, "This account or sales record already belongs to a workspace member") from None
    except Exception:
        await db.workspace_invitations.update_one({"_id": doc["_id"], "token_hash": doc["token_hash"], "status": "accepting"}, {"$set": {"status": "pending"}})
        raise
    return {"workspace_id": doc["workspace_id"], "role": doc["role"]}


def safe_lead(lead):
    from qualification_service import audit_payload
    values = lead.get("field_values") or {}
    assignment = lead.get("sales_assignment") or {}
    notes = [audit_payload(note) for note in (lead.get("lead_notes") or []) if isinstance(note, dict) and note.get("source") not in {"private", "internal_private"}]
    out = {key: lead.get(key) for key in ("status", "created_at", "updated_at", "lead_status", "call_outcome", "qualification_score", "lead_temperature", "call_attempt_count", "do_not_call", "auto_qualification_enabled", "qualification_processing")}
    out.update({"id": str(lead["_id"]), "sales_assignment": assignment, "property_name": (lead.get("opportunity") or {}).get("name") or (lead.get("referral_property") or {}).get("name"), "notes": notes, "lead_notes": notes})
    for key in ("full_name", "phone", "email", "address", "source", "assigned_salesperson"):
        out[key] = values.get(key) or lead.get(key)
    if "sales_agent_id" in assignment:
        out["assigned_salesperson"] = assignment.get("sales_agent_name", "") if assignment.get("sales_agent_id") else ""
    for key in ("communication_summary", "qualification_call"):
        out[key] = audit_payload(lead.get(key) or {})
        out[key].pop("raw_provider_data", None)
    return out


def member_snapshot(lead, tasks):
    from crm_workspace import _follow_up_snapshot
    return _follow_up_snapshot({**lead, "lead_notes": safe_lead(lead)["lead_notes"]}, tasks)


async def portal_lead(request, ws_id, lead_id):
    db = db_from(request)
    user, workspace, membership = await member_context(request, db, ws_id)
    if not ObjectId.is_valid(lead_id):
        raise HTTPException(404, "Lead not found")
    lead = await db.crm_leads.find_one({**permitted_leads(ws_id, membership), "_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(404, "Lead is unavailable or has been reassigned")
    return db, user, workspace, membership, lead


@portal_router.get("/leads")
async def portal_leads(ws_id: str, request: Request, search: str = "", page: int = 1):
    from crm import apply_lead_filters
    db = db_from(request)
    _, _, membership = await member_context(request, db, ws_id)
    query = apply_lead_filters(permitted_leads(ws_id, membership), search=search[:200])
    rows = await db.crm_leads.find(query).sort("created_at", -1).skip((max(1, page) - 1) * 20).limit(20).to_list(20)
    ids = [str(doc["_id"]) for doc in rows]
    tasks = await db.tasks.find({"workspace_id": ws_id, "lead_id": {"$in": ids}, "source": "crm_reminder"}).to_list(None)
    grouped = {lead_id: [] for lead_id in ids}
    for task in tasks:
        grouped[task["lead_id"]].append(task)
    return {"items": [{**safe_lead(doc), "follow_up": member_snapshot(doc, grouped[str(doc["_id"])])} for doc in rows], "total": await db.crm_leads.count_documents(query)}


@portal_router.get("/leads/{lead_id}")
async def portal_detail(ws_id: str, lead_id: str, request: Request):
    db, _, _, _, lead = await portal_lead(request, ws_id, lead_id)
    reminders = await db.tasks.find({"workspace_id": ws_id, "lead_id": lead_id, "source": "crm_reminder"}).sort("scheduled_time", 1).limit(100).to_list(100)
    return {"lead": {**safe_lead(lead), "follow_up": member_snapshot(lead, reminders)}, "reminders": [{"id": str(doc["_id"]), **{key: doc.get(key) for key in ("title", "objective", "scheduled_time", "status", "outcome")}} for doc in reminders]}


@portal_router.post("/leads/{lead_id}/notes")
async def member_note(ws_id: str, lead_id: str, request: Request, body: dict = Body(...)):
    db, user, _, _, lead = await portal_lead(request, ws_id, lead_id)
    text = body.get("body")
    if set(body) - {"body", "source", "direction"} or not isinstance(text, str) or not text.strip() or len(text) > 4000 or body.get("source", "sales_member") not in {"sales_member", "manual_whatsapp"}:
        raise HTTPException(422, "Enter a note of 1-4000 characters")
    note = {"id": str(ObjectId()), "source": body.get("source", "sales_member"), "body": text.strip(), "author": user.get("name") or user["email"], "user_id": str(user["_id"]), "created_at": now_iso()}
    if note["source"] == "manual_whatsapp":
        note["direction"] = "outbound"
    await db.crm_leads.update_one({"_id": lead["_id"], "workspace_id": ws_id}, {"$push": {"lead_notes": note}, "$set": {"updated_at": now_iso()}})
    return {"ok": True}


@portal_router.post("/leads/{lead_id}/reminders")
async def member_reminder(ws_id: str, lead_id: str, request: Request, body: dict = Body(...)):
    from crm_workspace import ReminderInput
    db, user, _, _, _ = await portal_lead(request, ws_id, lead_id)
    try:
        reminder = ReminderInput(**body)
    except ValueError:
        raise HTTPException(422, "Enter a title and a due date with timezone") from None
    await db.tasks.insert_one({"workspace_id": ws_id, "lead_id": lead_id, "source": "crm_reminder", "title": reminder.title, "objective": reminder.note, "scheduled_time": reminder.due_at.isoformat(), "status": "pending", "requires_approval": True, "agent": "sales", "created_by": str(user["_id"]), "created_at": now_iso(), "updated_at": now_iso()})
    return {"ok": True}


@portal_router.patch("/leads/{lead_id}/reminders/{reminder_id}")
async def member_reminder_status(ws_id: str, lead_id: str, reminder_id: str, request: Request, body: dict = Body(...)):
    db, _, _, _, _ = await portal_lead(request, ws_id, lead_id)
    if not ObjectId.is_valid(reminder_id) or set(body) - {"status", "outcome"} or body.get("status") not in {"done", "cancelled"} or not isinstance(body.get("outcome", ""), str) or len(body.get("outcome", "")) > 1000:
        raise HTTPException(422, "Choose done or cancelled with an optional outcome")
    patch = {"status": body["status"], "outcome": body.get("outcome", ""), "updated_at": now_iso(), "completed_at": now_iso()}
    result = await db.tasks.update_one({"_id": ObjectId(reminder_id), "workspace_id": ws_id, "lead_id": lead_id, "source": "crm_reminder"}, {"$set": patch})
    if not result.matched_count:
        raise HTTPException(404, "Follow-up not found")
    return {"ok": True}


@portal_router.get("/performance")
async def personal_performance(ws_id: str, request: Request):
    from sales_team import performance_rows
    from workspace_modules import workspace_currency
    db = db_from(request)
    _, workspace, membership = await member_context(request, db, ws_id)
    person_id = membership.get("sales_person_id")
    if not person_id:
        raise HTTPException(403, "Use the owner performance dashboard")
    person = await db.crm_sales_people.find_one({"workspace_id": ws_id, "_id": ObjectId(person_id)})
    query = {"workspace_id": ws_id, "deleted_at": None, "$or": [{f"sales_assignment.{key}": person_id} for key in ("sales_agent_id", "channel_partner_id", "introduced_by_id")] + [{f"sales_credit.{key}": person_id} for key in ("sales_agent_id", "channel_partner_id")]}
    leads = await db.crm_leads.find(query, {"sales_assignment": 1, "sales_credit": 1, "opportunity": 1, "referral_property": 1, "status": 1}).to_list(None)
    return {"item": performance_rows([person], leads)[0], "currency": workspace_currency(workspace)}


@portal_router.get("/properties")
async def referral_properties(ws_id: str, request: Request):
    db = db_from(request)
    await member_context(request, db, ws_id)
    return {"items": [{"id": str(doc["_id"]), "name": doc.get("name", "Property")} async for doc in db.properties.find({"workspace_id": ws_id, "status": {"$in": ["available", "reserved"]}}, {"name": 1})]}


@portal_router.post("/leads")
async def member_referral(ws_id: str, request: Request, body: dict = Body(...)):
    from crm import build_manual_lead, ensure_crm_settings
    db = db_from(request)
    _, _, member = await member_context(request, db, ws_id)
    if member["role"] not in MEMBER_ROLES:
        raise HTTPException(403, "Use owner lead creation")
    if set(body) - {"full_name", "phone", "email", "property_id", "acquisition_channel"}:
        raise HTTPException(422, "Unsupported referral fields")
    channel = body.get("acquisition_channel") or "referral"
    if channel not in {"marketing", "referral"}:
        raise HTTPException(422, "Choose marketing or referral")
    person = await db.crm_sales_people.find_one({"workspace_id": ws_id, "_id": ObjectId(member["sales_person_id"])})
    lead = build_manual_lead(ws_id, {"trigger_ai_call": False, "field_values": {key: body.get(key, "") for key in ("full_name", "phone", "email")}}, await ensure_crm_settings(db, ws_id))
    lead["sales_assignment"] = {"introduced_by_id": member["sales_person_id"], "introduced_by_name": person["name"], "acquisition_channel": channel, f"{member['role']}_id": member["sales_person_id"], f"{member['role']}_name": person["name"]}
    property_id = body.get("property_id")
    if property_id:
        if not ObjectId.is_valid(property_id):
            raise HTTPException(422, "Select a valid property")
        property_doc = await db.properties.find_one({"workspace_id": ws_id, "_id": ObjectId(property_id)})
        if not property_doc:
            raise HTTPException(404, "Property not found")
        lead["referral_property"] = {"id": property_id, "name": property_doc.get("name", "Property")}
    await db.crm_leads.insert_one(lead)
    return safe_lead(lead)


@portal_router.get("/qualification/leads/{lead_id}/history")
async def member_call_history(ws_id: str, lead_id: str, request: Request):
    from qualification_service import audit_payload
    db, _, _, _, _ = await portal_lead(request, ws_id, lead_id)
    docs = await db.crm_call_logs.find({"workspace_id": ws_id, "lead_id": lead_id, "kind": "qualification_engine"}).sort("created_at", -1).to_list(100)
    return [{"id": str(doc["_id"]), "created_at": doc.get("created_at"), "result": audit_payload(doc.get("result")), "profile_snapshot": {"product_name": (doc.get("profile_snapshot") or {}).get("product_name")}} for doc in docs]


@portal_router.get("/sms/config")
async def member_sms_config(ws_id: str, request: Request):
    db = db_from(request)
    await member_context(request, db, ws_id)
    doc = await db.workspace_sms_configs.find_one({"workspace_id": ws_id}) or {}
    return {"configured": bool(doc.get("encrypted_auth_token")), "enabled": bool(doc.get("enabled"))}


@portal_router.get("/sms/leads/{lead_id}")
async def member_sms_history(ws_id: str, lead_id: str, request: Request):
    from sms import list_messages
    await portal_lead(request, ws_id, lead_id)
    return await list_messages(ws_id, lead_id, request)


@portal_router.post("/sms/leads/{lead_id}")
async def member_send_sms(ws_id: str, lead_id: str, request: Request, body: dict = Body(...)):
    from sms import send_message
    await portal_lead(request, ws_id, lead_id)
    return await send_message(ws_id, lead_id, request, body)


@portal_router.post("/sms/leads/{lead_id}/{message_id}/refresh")
async def member_refresh_sms(ws_id: str, lead_id: str, message_id: str, request: Request):
    from sms import refresh_message
    await portal_lead(request, ws_id, lead_id)
    return await refresh_message(ws_id, lead_id, message_id, request)
