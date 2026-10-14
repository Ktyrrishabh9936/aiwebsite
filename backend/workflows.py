from fastapi import APIRouter, Request, HTTPException, Depends
from crm import require_workspace_access
from models import Workflow, now_iso
from bson import ObjectId

router = APIRouter(prefix="/workspaces/{ws_id}/workflows", dependencies=[Depends(require_workspace_access)])

def doc_out(doc):
    if not doc:
        return None
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc

@router.get("")
async def list_workflows(ws_id: str, request: Request):
    db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")
    docs = await db.workflows.find({"workspace_id": ws_id}).to_list(100)
    
    # Check if ads_to_crm workflow exists. If not, return a default draft template.
    has_ads = any(d.get("kind") == "ads_to_crm" for d in docs)
    if not has_ads:
        conn = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
        default_wf = {
            "workspace_id": ws_id,
            "kind": "ads_to_crm",
            "status": "draft",
            "sheet_connection_id": str(conn["_id"]) if conn else None,
            "published_at": None
        }
        # Save it to DB
        res = await db.workflows.insert_one(default_wf)
        default_wf["_id"] = res.inserted_id
        docs.append(default_wf)

    return [doc_out(d) for d in docs]

@router.post("/ads-to-crm/publish")
async def publish_workflow(ws_id: str, request: Request):
    db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")
    
    # Verify google sheet is connected and bound
    conn = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
    if not conn or not conn.get("spreadsheet_id"):
        raise HTTPException(status_code=400, detail="You must connect and bind a Google Sheet before publishing.")
    
    # Phone is the required CRM identity field.
    col_map = conn.get("column_map", {})
    if not col_map or not col_map.get("phone"):
        raise HTTPException(status_code=400, detail="Please map the spreadsheet Phone column before publishing.")

    from google_sheets import (
        drain_with_lease, ensure_drive_watch, establish_live_import_boundary,
        sheet_live_tail_row,
    )
    try:
        # Activation is intentionally forward-only: rows already present in the
        # Sheet are the baseline and are not imported into CRM.
        tail_row = await sheet_live_tail_row(db, conn)
        await ensure_drive_watch(db, conn, force=True)
        conn = await establish_live_import_boundary(db, conn, tail_row)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
        
    await db.workflows.update_one(
        {"workspace_id": ws_id, "kind": "ads_to_crm"},
        {"$set": {
            "status": "published",
            "published_at": now_iso(),
            "sheet_connection_id": str(conn["_id"])
        }},
        upsert=True
    )

    # Close the small race between taking the baseline and registering the
    # Drive watch. Any row appended during activation is imported here.
    try:
        await drain_with_lease(db, ws_id, conn)
    except Exception:
        # The active webhook and scheduled recovery will retry without making a
        # successfully registered workflow appear inactive.
        pass
    
    doc = await db.workflows.find_one({"workspace_id": ws_id, "kind": "ads_to_crm"})
    return doc_out(doc)

@router.post("/ads-to-crm/unpublish")
async def unpublish_workflow(ws_id: str, request: Request):
    db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")

    conn = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
    if conn:
        from google_sheets import stop_drive_watch
        try:
            await stop_drive_watch(db, conn)
        except Exception:
            # Pausing locally must still succeed if Google is temporarily unavailable.
            pass
        await db.google_sheet_connections.update_one(
            {"_id": conn["_id"]},
            {"$set": {"drive_watch_status": "paused", "updated_at": now_iso()},
             "$unset": {"drive_watch_channel_id": "", "drive_watch_token": "", "drive_watch_resource_id": "", "drive_watch_expiration": "",
                        "pending_drive_watch_channel_id": "", "pending_drive_watch_token": ""}},
        )
    
    await db.workflows.update_one(
        {"workspace_id": ws_id, "kind": "ads_to_crm"},
        {"$set": {
            "status": "draft",
            "published_at": None
        }}
    )
    
    doc = await db.workflows.find_one({"workspace_id": ws_id, "kind": "ads_to_crm"})
    return doc_out(doc)
