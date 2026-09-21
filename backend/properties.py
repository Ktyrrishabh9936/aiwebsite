from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Body, HTTPException, Query, Request

from crm import db_from, require_workspace_access
from workspace_modules import require_module, workspace_currency

router = APIRouter(prefix="/workspaces/{ws_id}/properties", tags=["properties"])

CONTAINER_KINDS = {"project", "individual", "land"}
STATUSES = {"available", "reserved", "sold", "inactive"}
CATEGORIES = {"residential", "commercial", "land", "industrial", "other"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def output(doc):
    if not doc:
        return None
    result = dict(doc)
    result["id"] = str(result.pop("_id"))
    return result


async def module_context(request, ws_id):
    _, workspace = await require_workspace_access(request, ws_id)
    require_module(workspace, "real_estate")
    return db_from(request), workspace


def clean_property(body, existing=None):
    existing = existing or {}
    body = body or {}
    name = str(body.get("name", existing.get("name", ""))).strip()
    if not name:
        raise HTTPException(400, "Property name is required")
    kind = str(body.get("container_kind", existing.get("container_kind", "individual"))).strip().lower()
    category = str(body.get("category", existing.get("category", "other"))).strip().lower()
    status = str(body.get("status", existing.get("status", "available"))).strip().lower()
    if kind not in CONTAINER_KINDS:
        raise HTTPException(400, "Invalid property container type")
    if category not in CATEGORIES:
        raise HTTPException(400, "Invalid property category")
    if status not in STATUSES:
        raise HTTPException(400, "Invalid property status")
    attributes = body.get("attributes", existing.get("attributes", {}))
    if not isinstance(attributes, dict):
        raise HTTPException(400, "Property attributes must be an object")
    now = now_iso()
    return {
        "name": name,
        "container_kind": kind,
        "user_role": str(body.get("user_role", existing.get("user_role", ""))).strip(),
        "inventory_source": str(body.get("inventory_source", existing.get("inventory_source", ""))).strip(),
        "category": category,
        "subtype": str(body.get("subtype", existing.get("subtype", ""))).strip(),
        "location": str(body.get("location", existing.get("location", ""))).strip(),
        "price": str(body.get("price", existing.get("price", ""))).strip(),
        "status": status,
        "inventory_owner": str(body.get("inventory_owner", existing.get("inventory_owner", ""))).strip(),
        "selling_organization": str(body.get("selling_organization", existing.get("selling_organization", ""))).strip(),
        "assigned_agent": str(body.get("assigned_agent", existing.get("assigned_agent", ""))).strip(),
        "project_id": str(body.get("project_id", existing.get("project_id", ""))).strip(),
        "tower_id": str(body.get("tower_id", existing.get("tower_id", ""))).strip(),
        "unit_number": str(body.get("unit_number", existing.get("unit_number", ""))).strip(),
        "structure": str(body.get("structure", existing.get("structure", "single"))).strip(),
        "inventory_setup": body.get("inventory_setup", existing.get("inventory_setup", {})) if isinstance(body.get("inventory_setup", existing.get("inventory_setup", {})), dict) else {},
        "attributes": attributes,
        "updated_at": now,
    }


@router.get("")
async def list_properties(ws_id: str, request: Request, search: str = Query(""), category: str = Query(""), status: str = Query("")):
    db, workspace = await module_context(request, ws_id)
    query = {"workspace_id": ws_id}
    if category in CATEGORIES:
        query["category"] = category
    if status in STATUSES:
        query["status"] = status
    if search.strip():
        query["$or"] = [{"name": {"$regex": search.strip(), "$options": "i"}}, {"location": {"$regex": search.strip(), "$options": "i"}}]
    docs = await db.properties.find(query).sort("created_at", -1).to_list(500)
    return {"items": [output(doc) for doc in docs], "currency": workspace_currency(workspace)}


@router.post("")
async def create_property(ws_id: str, request: Request, body: dict = Body(...)):
    db, _ = await module_context(request, ws_id)
    now = now_iso()
    doc = {
        "_id": ObjectId(),
        "workspace_id": ws_id,
        **clean_property(body),
        "created_at": now,
    }
    await db.properties.insert_one(doc)
    return output(doc)


@router.patch("/{property_id}")
async def update_property(ws_id: str, property_id: str, request: Request, body: dict = Body(...)):
    db, _ = await module_context(request, ws_id)
    try:
        oid = ObjectId(property_id)
    except Exception:
        raise HTTPException(400, "Invalid property id")
    current = await db.properties.find_one({"_id": oid, "workspace_id": ws_id})
    if not current:
        raise HTTPException(404, "Property not found")
    updates = clean_property(body, current)
    await db.properties.update_one({"_id": oid}, {"$set": updates})
    return output(await db.properties.find_one({"_id": oid}))


@router.delete("/{property_id}")
async def delete_property(ws_id: str, property_id: str, request: Request):
    db, _ = await module_context(request, ws_id)
    if await db.crm_leads.find_one({"workspace_id": ws_id, "opportunity.item_id": property_id}):
        raise HTTPException(409, "This property is linked to a CRM lead and cannot be deleted")
    try:
        oid = ObjectId(property_id)
    except Exception:
        raise HTTPException(400, "Invalid property id")
    result = await db.properties.delete_one({"_id": oid, "workspace_id": ws_id})
    if not result.deleted_count:
        raise HTTPException(404, "Property not found")
    return {"ok": True}
