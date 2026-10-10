"""Customer identity is the original converted lead; repeat deals never reset it."""
from decimal import Decimal, InvalidOperation
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from crm import (require_workspace_access, db_from, oid, ensure_crm_settings,
                 build_manual_lead, decorate_lead, receipt_is_collected,
                 single_payment_summary, recalculate_payment_plan)

router = APIRouter(prefix="/workspaces/{ws_id}/crm/customers", dependencies=[Depends(require_workspace_access)])


def amount(value):
    try:
        result = Decimal(str(value or 0).replace(",", ""))
        return result if result.is_finite() and result >= 0 else Decimal(0)
    except InvalidOperation:
        return Decimal(0)


def payment_state(lead):
    receipts = [r for r in lead.get("receipts", []) if receipt_is_collected(r)]
    paid = sum((amount(r.get("amount")) for r in receipts), Decimal(0))
    if lead.get("conversion_type") == "payment_plan":
        summary = recalculate_payment_plan(lead.get("payment_plan") or {}, receipts)
    else:
        summary = single_payment_summary(lead, receipts)
    total = amount(summary.get("total_amount"))
    due = amount(summary.get("due_amount"))
    return paid, due, total > 0 and paid >= total and due == 0


def customer_summary(root, deals, currency):
    values = root.get("field_values") or {}
    ltv = Decimal(0)
    due_total = Decimal(0)
    history = []
    for lead in deals:
        paid, due, complete = payment_state(lead)
        ltv += paid
        due_total += due
        closed = lead.get("status") in {"won", "lost"} or lead.get("customer_status") == "customer"
        history.append({"id": str(lead["_id"]), "status": lead.get("status", "new"),
                        "request": lead.get("repeat_request") or "Initial purchase",
                        "kind": lead.get("opportunity_kind") or "initial", "paid": str(paid),
                        "due": str(due), "payment_complete": complete, "open": not closed,
                        "created_at": lead.get("created_at"), "archived": bool(lead.get("deleted_at"))})
    _, _, root_complete = payment_state(root)
    return {"id": str(root["_id"]), "name": values.get("full_name") or root.get("full_name") or "Unnamed customer",
            "phone": values.get("phone") or root.get("phone") or "", "email": values.get("email") or root.get("email") or "",
            "currency": currency, "ltv": str(ltv), "outstanding": str(due_total),
            "lifecycle": "customer" if root_complete else "won_payment_pending",
            "deals": history, "open_opportunities": sum(d["open"] and not d["archived"] for d in history),
            "converted_at": root.get("converted_at"), "archived": bool(root.get("deleted_at"))}


async def customer_history(db, ws_id, customer_id, currency="INR"):
    root = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(customer_id)})
    if not root or root.get("customer_id") or (root.get("customer_status") != "customer" and root.get("status") != "won") or root.get("is_test_lead"):
        raise HTTPException(404, "Customer not found")
    # Include archived deals so trash does not silently erase collected LTV.
    repeats = await db.crm_leads.find({"workspace_id": ws_id, "customer_id": customer_id, "is_test_lead": {"$ne": True}}).to_list(5001)
    result = customer_summary(root, [root, *repeats[:5000]], currency)
    result["capped"] = len(repeats) > 5000
    return result


@router.get("")
async def customers(ws_id: str, request: Request, page: int = 1, limit: int = 25, search: str = ""):
    import re
    db = db_from(request)
    page, limit = max(1, page), max(1, min(100, limit))
    query = {"workspace_id": ws_id, "customer_id": None, "customer_deleted_at": None, "is_test_lead": {"$ne": True},
             "$or": [{"customer_status": "customer"}, {"status": "won"}]}
    if search.strip():
        query["$and"] = [{"$or": [{key: {"$regex": re.escape(search.strip()[:200]), "$options": "i"}} for key in
                                 ["field_values.full_name", "field_values.phone", "field_values.email"]]}]
    total = await db.crm_leads.count_documents(query)
    roots = await db.crm_leads.find(query).sort("converted_at", -1).skip((page - 1) * limit).limit(limit).to_list(limit)
    ws = await db.workspaces.find_one({"_id": oid(ws_id)}) or {}
    rows = [await customer_history(db, ws_id, str(root["_id"]), ws.get("currency") or "INR") for root in roots]
    return {"items": rows, "total": total, "page": page, "limit": limit}


@router.get("/{customer_id}")
async def customer(ws_id: str, customer_id: str, request: Request):
    db = db_from(request)
    ws = await db.workspaces.find_one({"_id": oid(ws_id)}) or {}
    return await customer_history(db, ws_id, customer_id, ws.get("currency") or "INR")


@router.post("/{customer_id}/opportunities")
async def repeat_opportunity(ws_id: str, customer_id: str, request: Request, body: dict = Body(...)):
    db = db_from(request)
    await customer_history(db, ws_id, customer_id)
    root = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(customer_id)})
    if root.get("deleted_at") or root.get("customer_deleted_at"):
        raise HTTPException(409, "Restore the customer record before adding an opportunity")
    description = str(body.get("request") or "").strip()
    if not description or len(description) > 2000:
        raise HTTPException(422, "Describe the requested product or service (up to 2000 characters)")
    kind = body.get("kind") or "upsell"
    if kind not in {"upsell", "repeat_purchase", "cross_sell"}:
        raise HTTPException(422, "Invalid opportunity kind")
    settings = await ensure_crm_settings(db, ws_id)
    fields = {f["key"] for f in settings.get("fields", []) if f.get("active", True)}
    contact = root.get("field_values") or {}
    values = {key: contact.get(key) or root.get(key) for key in ["full_name", "phone", "email", "address", "assigned_salesperson"] if key in fields and (contact.get(key) or root.get(key))}
    values.update({key: value for key, value in (body.get("field_values") or {}).items() if key in fields})
    # Repeat customers are already qualified. Never schedule an unsolicited initial call.
    lead = build_manual_lead(ws_id, {"field_values": values, "trigger_ai_call": False}, settings)
    lead.update({"customer_id": customer_id, "opportunity_kind": kind, "repeat_request": description,
                 "notes": description, "sales_assignment": root.get("sales_assignment") or {}})
    if body.get("sales_assignment"):
        from sales_team import attribution
        lead["sales_assignment"] = await attribution(db, ws_id, body["sales_assignment"])
    await db.crm_leads.insert_one(lead)
    return decorate_lead(lead, settings)


@router.delete("/{customer_id}")
async def delete_customer(ws_id: str, customer_id: str, request: Request):
    from models import now_iso
    db = db_from(request)
    await customer_history(db, ws_id, customer_id)
    await db.crm_leads.update_one({"workspace_id": ws_id, "_id": oid(customer_id)}, {"$set": {"customer_deleted_at": now_iso()}})
    return {"ok": True, "payment_history_preserved": True}
