"""Owner-managed sales people, lead attribution, and property performance."""
from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from crm import db_from, require_workspace_access, doc_out, lead_query, decorate_lead, ensure_crm_settings
from models import now_iso
from workspace_modules import workspace_currency

router = APIRouter(prefix="/workspaces/{ws_id}/crm/sales-team", dependencies=[Depends(require_workspace_access)])
ROLES = {"sales_agent", "channel_partner"}
shared_router = APIRouter()


@router.post("/leads/{lead_id}/share")
async def share_lead(ws_id: str, lead_id: str, request: Request, body: dict = Body(...)):
    db = db_from(request)
    if not ObjectId.is_valid(lead_id):
        raise HTTPException(404, "Lead not found")
    query = {**lead_query(ws_id), "_id": ObjectId(lead_id)}
    lead = await db.crm_leads.find_one(query)
    if not lead:
        raise HTTPException(404, "Active lead not found")
    person_id = str(body.get("sales_agent_id") or "")
    if not ObjectId.is_valid(person_id):
        raise HTTPException(422, "Choose an available sales agent")
    person = await db.crm_sales_people.find_one({"workspace_id": ws_id, "_id": ObjectId(person_id), "role": "sales_agent", "active": True})
    if not person:
        raise HTTPException(422, "Sales agent is unavailable")
    assignment = {**(lead.get("sales_assignment") or {}), "sales_agent_id": person_id, "sales_agent_name": person["name"]}
    membership = await db.workspace_memberships.find_one({"workspace_id": ws_id, "sales_person_id": person_id, "active": True})
    if not membership or not person.get("user_id"):
        raise HTTPException(409, "Invite this agent to the workspace and have them accept before sharing")
    previous = lead.get("lead_share") or {}
    updates = {"sales_assignment": assignment, "lead_share": {"agent_id": person_id, "agent_name": person["name"], "created_at": now_iso(), "authenticated": True}, "updated_at": now_iso()}
    if lead.get("status") == "won" or lead.get("customer_status") == "customer":
        updates["sales_credit"] = lead.get("sales_credit") or lead.get("sales_assignment") or {}
    await db.crm_leads.update_one(query, {"$set": updates, "$push": {"timeline": {"type": "lead_shared", "label": f"Lead shared with {person['name']}", "previous_agent_id": previous.get("agent_id"), "agent_id": person_id, "created_at": now_iso()}}})
    return {"share_path": f"/app/w/{ws_id}/crm?lead={lead_id}", "agent_name": person["name"], "lead": decorate_lead(await db.crm_leads.find_one(query), await ensure_crm_settings(db, ws_id))}


@router.delete("/leads/{lead_id}/share")
async def revoke_share(ws_id: str, lead_id: str, request: Request):
    db = db_from(request)
    if not ObjectId.is_valid(lead_id):
        raise HTTPException(404, "Lead not found")
    query = {**lead_query(ws_id), "_id": ObjectId(lead_id)}
    lead = await db.crm_leads.find_one(query)
    if not lead:
        raise HTTPException(404, "Active lead not found")
    assignment = {**(lead.get("sales_assignment") or {}), "sales_agent_id": "", "sales_agent_name": ""}
    updates = {"sales_assignment": assignment, "updated_at": now_iso()}
    if lead.get("status") == "won" or lead.get("customer_status") == "customer":
        updates["sales_credit"] = lead.get("sales_credit") or lead.get("sales_assignment") or {}
    await db.crm_leads.update_one(query, {"$set": updates, "$unset": {"lead_share": ""}, "$push": {"timeline": {"type": "lead_share_revoked", "label": "Lead sharing revoked and sales agent unassigned", "created_at": now_iso()}}})
    return decorate_lead(await db.crm_leads.find_one(query), await ensure_crm_settings(db, ws_id))


@shared_router.get("/crm/shared-leads/{token}")
async def view_shared_lead(token: str, request: Request):
    raise HTTPException(410, "Private lead links have been retired. Sign in to your workspace to view assigned leads")


async def attribution(db, ws_id, body, previous=None):
    if not isinstance(body, dict):
        raise HTTPException(422, "Sales assignment must be an object")
    result = {}
    for key, role in (("sales_agent_id", "sales_agent"), ("channel_partner_id", "channel_partner"), ("introduced_by_id", None)):
        value = str(body.get(key) or "")
        if value:
            if not ObjectId.is_valid(value):
                raise HTTPException(422, "Select a valid sales person")
            person = await db.crm_sales_people.find_one({"workspace_id": ws_id, "_id": ObjectId(value)})
            if not person or (not person.get("active", True) and (previous or {}).get(key) != value) or role and person["role"] != role:
                raise HTTPException(422, "Selected sales person is unavailable or has a different role")
            result[key.replace("_id", "_name")] = person["name"]
        else:
            result[key.replace("_id", "_name")] = ""
        result[key] = value
    channel = body.get("acquisition_channel") or "direct"
    if channel not in {"direct", "marketing", "referral"}:
        raise HTTPException(422, "Choose direct, marketing, or referral")
    result["acquisition_channel"] = channel
    return result


@router.get("")
async def list_people(ws_id: str, request: Request):
    return {"items": [doc_out(doc) async for doc in db_from(request).crm_sales_people.find({"workspace_id": ws_id}).sort("name", 1)]}


@router.post("")
async def add_person(ws_id: str, request: Request, body: dict = Body(...)):
    name = str(body.get("name") or "").strip()
    role = body.get("role")
    if not name or len(name) > 120 or role not in ROLES:
        raise HTTPException(422, "Enter a name and choose Sales agent or Channel partner")
    doc = {"workspace_id": ws_id, "name": name, "role": role, "phone": str(body.get("phone") or "").strip()[:40],
           "email": str(body.get("email") or "").strip()[:200], "active": True, "created_at": now_iso()}
    await db_from(request).crm_sales_people.insert_one(doc)
    return doc_out(doc)


@router.patch("/{person_id}")
async def update_person(ws_id: str, person_id: str, request: Request, body: dict = Body(...)):
    if not ObjectId.is_valid(person_id) or set(body) != {"active"} or not isinstance(body["active"], bool):
        raise HTTPException(422, "Supply a valid person and active flag")
    result = await db_from(request).crm_sales_people.update_one({"workspace_id": ws_id, "_id": ObjectId(person_id)}, {"$set": {"active": body["active"]}})
    if not result.matched_count:
        raise HTTPException(404, "Sales person not found")
    return {"ok": True}


@router.put("/leads/{lead_id}")
async def assign_lead(ws_id: str, lead_id: str, request: Request, body: dict = Body(...)):
    if not ObjectId.is_valid(lead_id):
        raise HTTPException(404, "Lead not found")
    db = db_from(request)
    lead = await db.crm_leads.find_one({**lead_query(ws_id), "_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(404, "Active lead not found")
    if lead.get("customer_status") == "customer" or lead.get("status") == "won":
        raise HTTPException(409, "Sales credit is locked after conversion")
    assignment = await attribution(db, ws_id, body, lead.get("sales_assignment"))
    if assignment.get("sales_agent_id") != (lead.get("sales_assignment") or {}).get("sales_agent_id"):
        await db.crm_leads.update_one({"workspace_id": ws_id, "_id": lead["_id"]}, {"$unset": {"lead_share": ""}})
    await db.crm_leads.update_one({"workspace_id": ws_id, "_id": lead["_id"]}, {"$set": {"sales_assignment": assignment, "updated_at": now_iso()}, "$push": {"timeline": {"type": "sales_assignment", "label": "Sales assignment and lead attribution updated", "created_at": now_iso()}}})
    return decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": lead["_id"]}), await ensure_crm_settings(db, ws_id))


def performance_rows(people, leads, property_id=""):
    rows = {str(person["_id"]): {"id": str(person["_id"]), "name": person["name"], "role": person["role"], "active": person.get("active", True),
            "assigned_leads": 0, "sales": 0, "sales_minor": 0, "introduced_leads": 0, "marketing_leads": 0, "referral_leads": 0, "introduced_sales": 0} for person in people}
    for lead in leads:
        opportunity = lead.get("opportunity") or {}
        if property_id and property_id not in {opportunity.get("project_id"), opportunity.get("item_id"), (lead.get("referral_property") or {}).get("id")}:
            continue
        assignment = lead.get("sales_assignment") or {}
        sold = opportunity.get("sale_status") == "sold" or lead.get("status") == "won" and opportunity.get("sale_status") != "rented"
        credit = lead.get("sales_credit", assignment) if sold else assignment
        for key in ("sales_agent_id", "channel_partner_id"):
            row = rows.get(assignment.get(key))
            if row:
                row["assigned_leads"] += 1
            credited = rows.get(credit.get(key))
            if sold and credited:
                credited["sales"] += 1
                credited["sales_minor"] += int(opportunity.get("sold_value_minor") or opportunity.get("total_minor") or 0)
        row = rows.get(assignment.get("introduced_by_id"))
        if row:
            row["introduced_leads"] += 1
            channel = assignment.get("acquisition_channel")
            if channel in {"marketing", "referral"}:
                row[f"{channel}_leads"] += 1
            row["introduced_sales"] += int(sold)
    return list(rows.values())


@router.get("/performance/summary")
async def performance(ws_id: str, request: Request, property_id: str = ""):
    _, workspace = await require_workspace_access(request, ws_id)
    db = db_from(request)
    people = await db.crm_sales_people.find({"workspace_id": ws_id}).to_list(None)
    leads = await db.crm_leads.find(lead_query(ws_id), {"sales_assignment": 1, "sales_credit": 1, "opportunity": 1, "referral_property": 1, "status": 1}).to_list(None)
    properties = [{"id": str(doc["_id"]), "name": doc.get("name", "Property")} async for doc in db.properties.find({"workspace_id": ws_id}, {"name": 1}).sort("name", 1)]
    return {"items": performance_rows(people, leads, property_id), "properties": properties, "currency": workspace_currency(workspace)}
