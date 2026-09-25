from datetime import datetime, timezone
import re

from bson import ObjectId
from fastapi import APIRouter, Body, HTTPException, Query, Request
from pymongo.errors import DuplicateKeyError

from crm import db_from, require_workspace_access
from workspace_modules import money_minor, minor_to_price, require_module, workspace_currency

router = APIRouter(prefix="/workspaces/{ws_id}/properties", tags=["properties"])

CONTAINER_KINDS = {"project", "individual", "land"}
STATUSES = {"available", "reserved", "sold", "inactive"}
CATEGORIES = {"residential", "commercial", "land", "industrial", "other"}
MAX_UNIT_GROUPS = 100
MAX_TOTAL_UNITS = 100000
MAX_GENERATED_UNITS = 5000
UNIT_STATUSES = {"available", "reserved", "sold", "rented", "inactive"}
LISTING_TYPES = {"sale", "rent"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def output(doc):
    if not doc:
        return None
    result = dict(doc)
    result["id"] = str(result.pop("_id"))
    return result


def clean_inventory_setup(value):
    if not isinstance(value, dict):
        raise HTTPException(400, "Inventory setup must be an object")
    if "unit_mix" not in value:
        return value  # Existing properties may use the older manual/count setup.
    groups = value["unit_mix"]
    if not isinstance(groups, list) or len(groups) > MAX_UNIT_GROUPS:
        raise HTTPException(400, "Add at most 100 tower and BHK rows")
    cleaned = []
    seen = set()
    total = 0
    numbered = []
    for group in groups:
        if not isinstance(group, dict):
            raise HTTPException(400, "Each inventory row must be an object")
        tower = str(group.get("tower", "")).strip()
        bhk = str(group.get("bhk", "")).strip()
        count = group.get("count")
        if not tower or len(tower) > 100 or not bhk or len(bhk) > 30:
            raise HTTPException(400, "Each inventory row needs a tower and BHK type")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_TOTAL_UNITS:
            raise HTTPException(400, "Flat count must be a positive whole number")
        key = (tower.casefold(), bhk.casefold(), str(group.get("start_number", "")).strip().casefold())
        if key in seen:
            raise HTTPException(400, "Combine duplicate tower and BHK rows")
        seen.add(key)
        total += count
        if total > MAX_TOTAL_UNITS:
            raise HTTPException(400, "Too many flats in one property")
        row = {"tower": tower, "bhk": bhk, "count": count}
        start = str(group.get("start_number", "")).strip()
        if start and (len(start) > 40 or not re.fullmatch(r"[A-Za-z0-9_-]*\d+", start)):
            raise HTTPException(400, "First flat number must end in digits, such as 101 or A-101")
        numbered.append(bool(start))
        if start:
            row["start_number"] = start
            increment = group.get("number_step", 1)
            if isinstance(increment, bool) or not isinstance(increment, int) or not 1 <= increment <= 1000:
                raise HTTPException(400, "Number increment must be a whole number from 1 to 1000")
            row["number_step"] = increment
        price_min = str(group.get("price_min", "")).strip()
        price_max = str(group.get("price_max", "")).strip()
        if price_min or price_max:
            if not price_min:
                raise HTTPException(400, "Enter a starting price for each flat type")
            low = money_minor(price_min)
            high = money_minor(price_max or price_min)
            if high < low:
                raise HTTPException(400, "Maximum price cannot be below minimum price")
            row.update(price_min=minor_to_price(low), price_max=minor_to_price(high))
        cleaned.append(row)
    if not cleaned:
        raise HTTPException(400, "Add at least one tower and BHK row")
    if any(numbered) and not all(numbered):
        raise HTTPException(400, "Set the first flat number for every tower and BHK row")
    return {"mode": "unit_mix", "unit_mix": cleaned, "total_units": total}


def unit_specs(property_doc):
    rows = (property_doc.get("inventory_setup") or {}).get("unit_mix") or []
    if not rows or not all(row.get("start_number") for row in rows):
        return []  # Older aggregate records need numbering before generation.
    if sum(row["count"] for row in rows) > MAX_GENERATED_UNITS:
        raise HTTPException(400, f"Generate at most {MAX_GENERATED_UNITS} flats per project")
    specs = []
    seen = set()
    for row in rows:
        match = re.fullmatch(r"(.*?)(\d+)", row["start_number"])
        prefix, digits = match.groups()
        low = money_minor(row.get("price_min") or property_doc.get("price") or 0)
        high = money_minor(row.get("price_max") or row.get("price_min") or property_doc.get("price") or 0)
        for offset in range(row["count"]):
            number = f"{prefix}{str(int(digits) + offset * row.get('number_step', 1)).zfill(len(digits))}"
            key = (row["tower"].casefold(), number.casefold())
            if key in seen:
                raise HTTPException(400, f"Flat {number} is repeated in {row['tower']}")
            seen.add(key)
            specs.append({"tower": row["tower"], "unit_number": number, "bhk": row["bhk"],
                          "price_min_minor": low, "price_max_minor": high})
    return specs


async def sync_property_units(db, ws_id, property_doc):
    specs = unit_specs(property_doc)
    property_id = str(property_doc["_id"])
    existing = await db.property_units.find({"workspace_id": ws_id, "property_id": property_id}).to_list(None)
    if not specs and (property_doc.get("inventory_setup") or {}).get("unit_mix") and existing:
        raise HTTPException(409, "Set flat numbers for all rows before changing generated inventory")
    if not specs and not existing:
        return
    old = {(row["tower"].casefold(), row["unit_number"].casefold()): row for row in existing}
    wanted = {(row["tower"].casefold(), row["unit_number"].casefold()): row for row in specs}
    for key, row in old.items():
        if key not in wanted:
            if row["status"] in {"sold", "rented"} or row.get("transactions") or await db.crm_leads.find_one({"workspace_id": ws_id, "opportunity.item_id": str(row["_id"])}):
                raise HTTPException(409, f"Flat {row['tower']} {row['unit_number']} is linked to a lead or has sale history. Mark it inactive instead.")
        elif row["bhk"] != wanted[key]["bhk"]:
            raise HTTPException(409, f"Flat {row['tower']} {row['unit_number']} already has type {row['bhk']}. Use a different number range.")
    now = now_iso()
    for key, spec in wanted.items():
        if key in old:
            patch = {"tower": spec["tower"], "unit_number": spec["unit_number"], "bhk": spec["bhk"], "price_min_minor": spec["price_min_minor"],
                     "price_max_minor": spec["price_max_minor"], "updated_at": now}
            if not old[key].get("price_overridden") and old[key]["status"] == "available":
                patch["asking_price_minor"] = spec["price_min_minor"]
            await db.property_units.update_one({"_id": old[key]["_id"]}, {"$set": patch})
        else:
            try:
                await db.property_units.insert_one({"_id": ObjectId(), "workspace_id": ws_id, "property_id": property_id,
                    **spec, "asking_price_minor": spec["price_min_minor"], "price_overridden": False,
                    "listing_type": "sale", "listing_version": 1, "status": "available", "assigned_to_user_ids": [],
                    "transactions": [], "created_at": now, "updated_at": now})
            except DuplicateKeyError:
                raise HTTPException(409, f"Flat {spec['unit_number']} already exists in {spec['tower']}") from None
    for key, row in old.items():
        if key not in wanted:
            await db.property_units.delete_one({"_id": row["_id"], "workspace_id": ws_id, "property_id": property_id})


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
        "inventory_setup": clean_inventory_setup(body.get("inventory_setup", existing.get("inventory_setup", {}))),
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
    counts = await db.property_units.aggregate([
        {"$match": {"workspace_id": ws_id, "property_id": {"$in": [str(doc["_id"]) for doc in docs]}}},
        {"$group": {"_id": "$property_id", "count": {"$sum": 1}}},
    ]).to_list(500) if docs else []
    count_by_property = {row["_id"]: row["count"] for row in counts}
    items = [output(doc) for doc in docs]
    for item in items:
        item["generated_units"] = count_by_property.get(item["id"], 0)
    return {"items": items, "currency": workspace_currency(workspace)}


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
    unit_specs(doc)  # Validate numbering and collisions before writing the project.
    await db.properties.insert_one(doc)
    try:
        await sync_property_units(db, ws_id, doc)
    except Exception:
        await db.property_units.delete_many({"workspace_id": ws_id, "property_id": str(doc["_id"])})
        await db.properties.delete_one({"_id": doc["_id"], "workspace_id": ws_id})
        raise
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
    next_doc = {**current, **updates}
    await sync_property_units(db, ws_id, next_doc)
    await db.properties.update_one({"_id": oid}, {"$set": updates})
    return output(await db.properties.find_one({"_id": oid}))


@router.post("/{property_id}/generate-units")
async def generate_property_units(ws_id: str, property_id: str, request: Request):
    db, _ = await module_context(request, ws_id)
    if not ObjectId.is_valid(property_id):
        raise HTTPException(400, "Invalid property id")
    property_doc = await db.properties.find_one({"_id": ObjectId(property_id), "workspace_id": ws_id})
    if not property_doc:
        raise HTTPException(404, "Property not found")
    if not unit_specs(property_doc):
        raise HTTPException(409, "Set the first flat number for every tower and BHK row before generating flats")
    await sync_property_units(db, ws_id, property_doc)
    count = await db.property_units.count_documents({"workspace_id": ws_id, "property_id": property_id})
    return {"generated_units": count}


@router.get("/{property_id}/units")
async def list_property_units(ws_id: str, property_id: str, request: Request, tower: str = "", bhk: str = "", status: str = "", offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
    db, workspace = await module_context(request, ws_id)
    if not ObjectId.is_valid(property_id):
        raise HTTPException(400, "Invalid property id")
    property_doc = await db.properties.find_one({"_id": ObjectId(property_id), "workspace_id": ws_id})
    if not property_doc:
        raise HTTPException(404, "Property not found")
    query = {"workspace_id": ws_id, "property_id": property_id}
    if tower:
        query["tower"] = tower
    if bhk:
        query["bhk"] = bhk
    if status in UNIT_STATUSES:
        query["status"] = status
    total = await db.property_units.count_documents(query)
    docs = await db.property_units.find(query).sort([("tower", 1), ("unit_number", 1)]).skip(offset).limit(limit).to_list(limit)
    return {"items": [output(doc) for doc in docs], "total": total, "currency": workspace_currency(workspace)}


@router.patch("/{property_id}/units/{unit_id}")
async def update_property_unit(ws_id: str, property_id: str, unit_id: str, request: Request, body: dict = Body(...)):
    db, _ = await module_context(request, ws_id)
    if not ObjectId.is_valid(property_id) or not ObjectId.is_valid(unit_id):
        raise HTTPException(400, "Invalid property or flat id")
    query = {"_id": ObjectId(unit_id), "workspace_id": ws_id, "property_id": property_id}
    unit = await db.property_units.find_one(query)
    if not unit:
        raise HTTPException(404, "Flat not found")
    if body.get("expected_updated_at") and body["expected_updated_at"] != unit.get("updated_at"):
        raise HTTPException(409, "This flat changed while you were editing. Refresh and try again.")
    query["updated_at"] = unit.get("updated_at")
    if unit["status"] in {"sold", "rented"} and body.get("status") != "available":
        raise HTTPException(409, "Relist this flat before changing it")
    allowed = {"asking_price", "status", "listing_type", "expected_updated_at"}
    if set(body) - allowed:
        raise HTTPException(400, "Unsupported flat update")
    patch = {"updated_at": now_iso()}
    if "asking_price" in body:
        patch["asking_price_minor"] = money_minor(body["asking_price"])
        patch["price_overridden"] = True
    if "listing_type" in body:
        if body["listing_type"] not in LISTING_TYPES:
            raise HTTPException(400, "Listing type must be sale or rent")
        patch["listing_type"] = body["listing_type"]
    if "status" in body:
        if body["status"] not in {"available", "reserved", "inactive"}:
            raise HTTPException(400, "Use lead conversion to mark a flat sold or rented")
        patch["status"] = body["status"]
    if unit["status"] in {"sold", "rented"} and patch.get("status") == "available":
        # Keep transaction history while starting a new listing cycle.
        patch["listing_version"] = unit.get("listing_version", 1) + 1
        result = await db.property_units.update_one(query, {"$set": patch, "$unset": {"sold_to_lead_id": "", "sold_at": "", "sold_value_minor": ""}})
    else:
        if patch.get("listing_type", unit.get("listing_type")) != unit.get("listing_type"):
            patch["listing_version"] = unit.get("listing_version", 1) + 1
        result = await db.property_units.update_one(query, {"$set": patch})
    if not result.matched_count:
        raise HTTPException(409, "This flat changed while you were editing. Refresh and try again.")
    query.pop("updated_at", None)
    return output(await db.property_units.find_one(query))


@router.delete("/{property_id}")
async def delete_property(ws_id: str, property_id: str, request: Request):
    db, _ = await module_context(request, ws_id)
    if not ObjectId.is_valid(property_id):
        raise HTTPException(400, "Invalid property id")
    oid = ObjectId(property_id)
    property_doc = await db.properties.find_one({"_id": oid, "workspace_id": ws_id})
    if not property_doc:
        raise HTTPException(404, "Property not found")
    if property_doc.get("sold_to_lead_id") or property_doc.get("status") == "sold":
        raise HTTPException(409, "This property has sale history and cannot be deleted")
    if await db.crm_leads.find_one({"workspace_id": ws_id, "$or": [
        {"opportunity.item_id": property_id}, {"opportunity.project_id": property_id},
    ]}):
        raise HTTPException(409, "This property or one of its flats is linked to a CRM lead. Unlink it before deleting.")
    units = db.property_units.find({"workspace_id": ws_id, "property_id": property_id})
    async for unit in units:
        if unit["status"] in {"sold", "rented"} or unit.get("transactions") or await db.crm_leads.find_one({"workspace_id": ws_id, "opportunity.item_id": str(unit["_id"])}):
            raise HTTPException(409, "This property has linked flats or sale history and cannot be deleted")
    result = await db.properties.delete_one({"_id": oid, "workspace_id": ws_id})
    if not result.deleted_count:
        raise HTTPException(404, "Property not found")
    await db.property_units.delete_many({"workspace_id": ws_id, "property_id": property_id})
    return {"ok": True}
