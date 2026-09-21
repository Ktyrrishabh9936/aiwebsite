"""Shared CRM opportunity layer for optional vertical inventory modules."""
from bson import ObjectId
from fastapi import APIRouter, Body, HTTPException, Request
from pymongo import ReturnDocument

from crm import db_from, decorate_lead, ensure_crm_settings, lead_query, require_workspace_access
from models import now_iso
from workspace_modules import money_minor, require_module, workspace_currency, workspace_modules

router = APIRouter(prefix="/workspaces/{ws_id}/crm", tags=["CRM opportunities"])


def safe_money_minor(value):
    try:
        return money_minor(value)
    except HTTPException:
        return 0


async def offerings_for(db, ws_id, workspace):
    modules = workspace_modules(workspace)
    items = []
    if modules["real_estate"]:
        async for row in db.properties.find({"workspace_id": ws_id, "status": {"$in": ["available", "reserved"]}}).sort("name", 1):
            items.append({"id": str(row["_id"]), "module": "real_estate", "kind": "property", "name": row.get("name", "Property"),
                          "description": row.get("location", ""), "price": row.get("price", "0"), "price_minor": safe_money_minor(row.get("price", "0")),
                          "available_quantity": 1})
    if modules["agency"]:
        query = {"workspace_id": ws_id, "status": "active", "$or": [{"kind": "service"}, {"kind": "product", "stock_quantity": {"$gt": 0}}]}
        async for row in db.catalog_items.find(query).sort("name", 1):
            items.append({"id": str(row["_id"]), "module": "agency", "kind": row["kind"], "name": row["name"],
                          "description": row.get("description", ""), "price": row.get("price", "0"), "price_minor": int(row.get("price_minor") or 0),
                          "available_quantity": row.get("stock_quantity") if row["kind"] == "product" else None})
    return items


@router.get("/offerings")
async def list_offerings(ws_id: str, request: Request):
    _, workspace = await require_workspace_access(request, ws_id)
    items = await offerings_for(db_from(request), ws_id, workspace)
    return {"items": items, "currency": workspace_currency(workspace), "modules": workspace_modules(workspace)}


@router.patch("/leads/{lead_id}/opportunity")
async def set_opportunity(ws_id: str, lead_id: str, request: Request, body: dict = Body(...)):
    _, workspace = await require_workspace_access(request, ws_id)
    db = db_from(request)
    if not ObjectId.is_valid(lead_id):
        raise HTTPException(422, "Invalid lead")
    lead = await db.crm_leads.find_one({**lead_query(ws_id), "_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(404, "Lead not found")
    if lead.get("customer_status") == "customer" or (lead.get("opportunity") or {}).get("sale_status") == "sold":
        raise HTTPException(409, "Sold opportunities cannot be changed")
    item_id = str(body.get("item_id") or "")
    module = str(body.get("module") or "")
    if not item_id or not ObjectId.is_valid(item_id):
        raise HTTPException(400, "Select an inventory item, product, or service")
    require_module(workspace, module)
    offerings = await offerings_for(db, ws_id, workspace)
    item = next((row for row in offerings if row["id"] == item_id and row["module"] == module), None)
    if not item:
        raise HTTPException(409, "The selected item is no longer available")
    try:
        quantity = max(1, int(body.get("quantity") or 1))
    except (TypeError, ValueError):
        raise HTTPException(400, "Quantity must be a whole number") from None
    if item["kind"] == "property":
        quantity = 1
    if item["available_quantity"] is not None and quantity > item["available_quantity"]:
        raise HTTPException(409, "Requested quantity exceeds available stock")
    unit_price_minor = item["price_minor"]
    if str(body.get("amount") or "").strip():
        unit_price_minor = money_minor(body["amount"])
    opportunity = {"module": module, "kind": item["kind"], "item_id": item_id, "name": item["name"],
                   "quantity": quantity, "unit_price_minor": unit_price_minor, "total_minor": unit_price_minor * quantity,
                   "currency": workspace_currency(workspace), "sale_status": "selected", "selected_at": now_iso()}
    await db.crm_leads.update_one({"_id": lead["_id"], "workspace_id": ws_id}, {"$set": {"opportunity": opportunity, "updated_at": now_iso()}})
    return decorate_lead(await db.crm_leads.find_one({"_id": lead["_id"]}), await ensure_crm_settings(db, ws_id))


async def finalize_opportunity(db, ws_id, lead, workspace):
    opportunity = dict(lead.get("opportunity") or {})
    if not opportunity or opportunity.get("sale_status") == "sold":
        return opportunity
    item_id = opportunity.get("item_id", "")
    if not ObjectId.is_valid(item_id):
        raise HTTPException(409, "The selected opportunity is invalid")
    module, kind = opportunity.get("module"), opportunity.get("kind")
    require_module(workspace, module)
    lead_id = str(lead["_id"])
    if module == "real_estate":
        result = await db.properties.find_one_and_update(
            {"_id": ObjectId(item_id), "workspace_id": ws_id, "status": {"$in": ["available", "reserved"]}},
            {"$set": {"status": "sold", "sold_to_lead_id": lead_id, "sold_at": now_iso(), "updated_at": now_iso()}},
            return_document=ReturnDocument.AFTER)
        if not result:
            raise HTTPException(409, "The selected property is no longer available")
    elif kind == "product":
        quantity = int(opportunity.get("quantity") or 1)
        result = await db.catalog_items.find_one_and_update(
            {"_id": ObjectId(item_id), "workspace_id": ws_id, "kind": "product", "status": "active", "stock_quantity": {"$gte": quantity}},
            {"$inc": {"stock_quantity": -quantity}, "$set": {"last_sold_to_lead_id": lead_id, "last_sold_at": now_iso(), "updated_at": now_iso()}},
            return_document=ReturnDocument.AFTER)
        if not result:
            raise HTTPException(409, "The selected product no longer has enough stock")
        if result.get("stock_quantity", 0) == 0:
            await db.catalog_items.update_one({"_id": result["_id"], "stock_quantity": 0}, {"$set": {"status": "sold_out"}})
    elif kind == "service":
        if not await db.catalog_items.find_one({"_id": ObjectId(item_id), "workspace_id": ws_id, "kind": "service", "status": "active"}):
            raise HTTPException(409, "The selected service is no longer active")
    else:
        raise HTTPException(409, "The selected opportunity type is invalid")
    opportunity.update({"sale_status": "sold", "sold_at": now_iso(), "currency": workspace_currency(workspace)})
    return opportunity
