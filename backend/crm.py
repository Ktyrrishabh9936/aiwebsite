from fastapi import APIRouter, Request, HTTPException, Query, Body
from models import CRMLead, now_iso
from bson import ObjectId

router = APIRouter(prefix="/workspaces/{ws_id}/crm")

def oid(v):
    return ObjectId(v)

def doc_out(doc):
    if not doc:
        return None
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc

@router.get("/leads")
async def list_leads(ws_id: str, request: Request, status: str = Query(None)):
    db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")
    q = {"workspace_id": ws_id}
    if status:
        q["status"] = status
    docs = await db.crm_leads.find(q).sort("created_at", -1).to_list(500)
    return [doc_out(d) for d in docs]

@router.get("/leads/{lead_id}")
async def get_lead(ws_id: str, lead_id: str, request: Request):
    db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")
    doc = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Lead not found")
    return doc_out(doc)

@router.patch("/leads/{lead_id}")
async def update_lead_status(ws_id: str, lead_id: str, request: Request, body: dict = Body(...)):
    db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")
    
    new_status = body.get("status")
    if new_status not in ("new", "contacted", "won", "lost"):
        raise HTTPException(status_code=400, detail="Invalid status value")
        
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": oid(lead_id)},
        {"$set": {
            "status": new_status,
            "updated_at": now_iso()
        }}
    )
    
    doc = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    return doc_out(doc)
