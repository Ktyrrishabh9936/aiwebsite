"""Agency products and services; activated per workspace."""
from bson import ObjectId
from fastapi import APIRouter, Body, HTTPException, Query, Request

from crm import db_from, require_workspace_access
from models import now_iso
from workspace_modules import money_minor, minor_to_price, require_module, workspace_currency

router = APIRouter(prefix="/workspaces/{ws_id}/catalog", tags=["agency catalog"])
KINDS = {"product", "service"}
STATUSES = {"active", "inactive", "sold_out"}


def output(doc):
    result = dict(doc)
    result["id"] = str(result.pop("_id"))
    return result


def clean_item(body, existing=None):
    existing, body = existing or {}, body or {}
    name = str(body.get("name", existing.get("name", ""))).strip()
    if not name:
        raise HTTPException(400, "Product or service name is required")
    kind = str(body.get("kind", existing.get("kind", "product"))).lower().strip()
    if kind not in KINDS:
        raise HTTPException(400, "Kind must be product or service")
    status = str(body.get("status", existing.get("status", "active"))).lower().strip()
    if status not in STATUSES or kind == "service" and status == "sold_out":
        raise HTTPException(400, "Invalid catalog status")
    price_minor = money_minor(body.get("price", existing.get("price", "0")))
    try:
        stock = max(0, int(body.get("stock_quantity", existing.get("stock_quantity", 0)) or 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "Stock quantity must be a whole number") from None
    if kind == "service":
        stock = 0
    elif stock == 0 and status == "active":
        status = "sold_out"
    return {"name": name, "kind": kind, "description": str(body.get("description", existing.get("description", ""))).strip(),
            "sku": str(body.get("sku", existing.get("sku", ""))).strip(), "price": minor_to_price(price_minor),
            "price_minor": price_minor, "stock_quantity": stock, "status": status,
            "details": body.get("details", existing.get("details", {})) if isinstance(body.get("details", existing.get("details", {})), dict) else {},
            "updated_at": now_iso()}


async def module_context(request, ws_id):
    _, workspace = await require_workspace_access(request, ws_id)
    require_module(workspace, "agency")
    return db_from(request), workspace


@router.get("")
async def list_items(ws_id: str, request: Request, search: str = Query(""), kind: str = Query(""), status: str = Query("")):
    db, workspace = await module_context(request, ws_id)
    query = {"workspace_id": ws_id}
    if kind in KINDS:
        query["kind"] = kind
    if status in STATUSES:
        query["status"] = status
    if search.strip():
        query["$or"] = [{"name": {"$regex": search.strip(), "$options": "i"}}, {"sku": {"$regex": search.strip(), "$options": "i"}}]
    docs = await db.catalog_items.find(query).sort("created_at", -1).to_list(500)
    return {"items": [output(doc) for doc in docs], "currency": workspace_currency(workspace)}


@router.post("")
async def create_item(ws_id: str, request: Request, body: dict = Body(...)):
    db, _ = await module_context(request, ws_id)
    doc = {"_id": ObjectId(), "workspace_id": ws_id, **clean_item(body), "created_at": now_iso()}
    await db.catalog_items.insert_one(doc)
    return output(doc)


@router.patch("/{item_id}")
async def update_item(ws_id: str, item_id: str, request: Request, body: dict = Body(...)):
    db, _ = await module_context(request, ws_id)
    if not ObjectId.is_valid(item_id):
        raise HTTPException(422, "Invalid catalog item")
    query = {"_id": ObjectId(item_id), "workspace_id": ws_id}
    current = await db.catalog_items.find_one(query)
    if not current:
        raise HTTPException(404, "Catalog item not found")
    await db.catalog_items.update_one(query, {"$set": clean_item(body, current)})
    return output(await db.catalog_items.find_one(query))


@router.delete("/{item_id}")
async def delete_item(ws_id: str, item_id: str, request: Request):
    db, _ = await module_context(request, ws_id)
    if not ObjectId.is_valid(item_id):
        raise HTTPException(422, "Invalid catalog item")
    if await db.crm_leads.find_one({"workspace_id": ws_id, "opportunity.item_id": item_id}):
        raise HTTPException(409, "This item is linked to a CRM lead and cannot be deleted; mark it inactive instead")
    result = await db.catalog_items.delete_one({"_id": ObjectId(item_id), "workspace_id": ws_id})
    if not result.deleted_count:
        raise HTTPException(404, "Catalog item not found")
    return {"ok": True}
