import os
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
import urllib.parse
from fastapi import APIRouter, Request, HTTPException, Query, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from bson import ObjectId
from models import GoogleSheetConnection, Workflow, now_iso
import httpx
from crm import active_fields, ensure_crm_settings
from meta_fields import META_FIELDS, header_index, map_sheet_row

router = APIRouter(prefix="/google")

SCOPES = " ".join([
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/userinfo.email"
])

def get_db(request: Request):
    return request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")

def get_google_creds():
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth credentials not configured on server.")
    return client_id, client_secret

def get_redirect_uri(request: Request):
    env_uri = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
    if env_uri:
        return env_uri
    proto = request.headers.get("x-forwarded-proto", "http")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}/api/google/oauth/callback"

async def refresh_access_token(conn: dict, request: Request) -> str:
    client_id, client_secret = get_google_creds()
    tokens = conn.get("tokens", {})
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token available. Please reconnect your account.")
    
    async with httpx.AsyncClient() as client:
        res = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        })
        if res.status_code != 200:
            raise HTTPException(status_code=401, detail="Failed to refresh Google access token. Please reconnect.")
        
        data = res.json()
        new_access_token = data["access_token"]
        tokens["access_token"] = new_access_token
        
        db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")
        await db.google_sheet_connections.update_one(
            {"_id": conn["_id"]},
            {"$set": {"tokens": tokens, "updated_at": now_iso()}}
        )
        return new_access_token

@router.get("/connect")
async def google_connect(workspace_id: str, request: Request):
    client_id, _ = get_google_creds()
    redirect_uri = get_redirect_uri(request)
    
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": workspace_id,
        "access_type": "offline",
        "prompt": "consent"
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return RedirectResponse(url)

@router.get("/oauth/callback")
async def google_oauth_callback(request: Request, code: str = None, state: str = None, error: str = None):
    if error:
        return HTMLResponse(f"<h3>Authentication error: {error}</h3>")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing authorization code or state parameter.")
    
    client_id, client_secret = get_google_creds()
    redirect_uri = get_redirect_uri(request)
    
    async with httpx.AsyncClient() as client:
        res = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        })
        if res.status_code != 200:
            return HTMLResponse(f"<h3>Token exchange failed: {res.text}</h3>")
        
        tokens = res.json()
        
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        user_res = await client.get("https://www.googleapis.com/oauth2/v3/userinfo", headers=headers)
        email = user_res.json().get("email") if user_res.status_code == 200 else None
        
        db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")
        existing = await db.google_sheet_connections.find_one({"workspace_id": state})
        
        if existing:
            if "refresh_token" not in tokens and "refresh_token" in existing.get("tokens", {}):
                tokens["refresh_token"] = existing["tokens"]["refresh_token"]
            
            await db.google_sheet_connections.update_one(
                {"workspace_id": state},
                {"$set": {
                    "google_email": email,
                    "tokens": tokens,
                    "updated_at": now_iso()
                }}
            )
        else:
            conn = GoogleSheetConnection(
                workspace_id=state,
                google_email=email,
                tokens=tokens
            )
            await db.google_sheet_connections.insert_one(conn.to_mongo())
            
    html_content = """
    <html>
        <body>
            <script>
                if (window.opener) {
                    window.opener.postMessage({ type: 'GOOGLE_CONNECTED' }, '*');
                }
                window.close();
            </script>
            <p>Authentication successful. You can close this tab now.</p>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@router.get("/workspaces/{ws_id}")
async def get_connection_status(ws_id: str, request: Request):
    db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")
    conn = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
    if not conn:
        return {"connected": False}
    return {
        "connected": True,
        "google_email": conn.get("google_email"),
        "spreadsheet_id": conn.get("spreadsheet_id"),
        "spreadsheet_name": conn.get("spreadsheet_name"),
        "sheet_name": conn.get("sheet_name"),
        "column_map": conn.get("column_map", {}),
        "header_row": conn.get("header_row", []),
        "mapping_fields": [{"key": key, "label": label} for key, (_, label) in META_FIELDS.items()] + [{"key": "status", "label": "CRM Status (write-back)"}],
        "write_access": "https://www.googleapis.com/auth/spreadsheets" in conn.get("tokens", {}).get("scope", "").split(),
    }

@router.delete("/workspaces/{ws_id}")
async def disconnect_google(ws_id: str, request: Request):
    db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")
    await db.google_sheet_connections.delete_one({"workspace_id": ws_id})
    await db.workflows.update_one({"workspace_id": ws_id, "kind": "ads_to_crm"}, {"$set": {"status": "draft", "sheet_connection_id": None}})
    return {"ok": True}

@router.get("/workspaces/{ws_id}/spreadsheets")
async def list_spreadsheets(ws_id: str, request: Request):
    db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")
    conn = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
    if not conn:
        raise HTTPException(status_code=400, detail="Google sheet connection not found.")
    
    access_token = conn["tokens"].get("access_token")
    
    async def try_fetch(token):
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {token}"}
            r = await client.get(
                "https://www.googleapis.com/drive/v3/files?q=mimeType='application/vnd.google-apps.spreadsheet'&fields=files(id,name)",
                headers=headers
            )
            return r

    res = await try_fetch(access_token)
    if res.status_code == 401:
        new_token = await refresh_access_token(conn, request)
        res = await try_fetch(new_token)
        
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=f"Failed to fetch spreadsheets: {res.text}")
        
    return res.json().get("files", [])

@router.get("/workspaces/{ws_id}/spreadsheets/{spreadsheet_id}/tabs")
async def list_spreadsheet_tabs(ws_id: str, spreadsheet_id: str, request: Request):
    db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")
    conn = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
    if not conn:
        raise HTTPException(status_code=400, detail="Google sheet connection not found.")

    async def try_fetch(token):
        async with httpx.AsyncClient() as client:
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}?fields=sheets.properties.title"
            return await client.get(url, headers={"Authorization": f"Bearer {token}"})

    access_token = conn["tokens"].get("access_token")
    res = await try_fetch(access_token)
    if res.status_code == 401:
        access_token = await refresh_access_token(conn, request)
        res = await try_fetch(access_token)
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=f"Failed to fetch sheet tabs: {res.text}")
    sheets = res.json().get("sheets", [])
    return [{"name": s.get("properties", {}).get("title", "")} for s in sheets if s.get("properties", {}).get("title")]

@router.post("/workspaces/{ws_id}/bind")
async def bind_sheet(ws_id: str, request: Request, body: dict):
    db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")
    conn = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
    if not conn:
        raise HTTPException(status_code=400, detail="Google connection not established.")
    
    spreadsheet_id = body.get("spreadsheet_id")
    spreadsheet_name = body.get("spreadsheet_name")
    sheet_name = body.get("sheet_name") or "Sheet1"
    
    if not spreadsheet_id or not spreadsheet_name:
        raise HTTPException(status_code=400, detail="spreadsheet_id and spreadsheet_name required.")
    
    access_token = conn["tokens"].get("access_token")
    
    async def fetch_headers(token):
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {token}"}
            url = values_url(spreadsheet_id, sheet_name, "1:1")
            return await client.get(url, headers=headers)
            
    res = await fetch_headers(access_token)
    if res.status_code == 401:
        new_token = await refresh_access_token(conn, request)
        res = await fetch_headers(new_token)
        
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail=f"Failed to retrieve sheet structure: {res.text}")
        
    vals = res.json().get("values", [])
    headers_list = vals[0] if vals else []
    
    await db.google_sheet_connections.update_one(
        {"workspace_id": ws_id},
        {"$set": {
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_name": spreadsheet_name,
            "sheet_name": sheet_name,
            "header_row": headers_list,
            "cursor": 1,
            "updated_at": now_iso()
        }}
    )
    
    # Ensure a workflow object exists
    wf = await db.workflows.find_one({"workspace_id": ws_id, "kind": "ads_to_crm"})
    if not wf:
        conn_doc = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
        new_wf = Workflow(
            workspace_id=ws_id,
            kind="ads_to_crm",
            status="draft",
            sheet_connection_id=str(conn_doc["_id"])
        )
        await db.workflows.insert_one(new_wf.to_mongo())
    else:
        conn_doc = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
        await db.workflows.update_one(
            {"workspace_id": ws_id, "kind": "ads_to_crm"},
            {"$set": {"sheet_connection_id": str(conn_doc["_id"])}}
        )

    return {"ok": True, "headers": headers_list}

@router.patch("/workspaces/{ws_id}/column_map")
async def update_column_map(ws_id: str, request: Request, body: dict):
    db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")
    settings = await ensure_crm_settings(db, ws_id)
    allowed = {f["key"] for f in active_fields(settings)}
    column_map = {k: v for k, v in (body.get("column_map", {}) or {}).items() if k in allowed | set(META_FIELDS) | {"status"} and v}
    conn = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
    if not conn:
        raise HTTPException(400, "Google connection not established.")
    try:
        for header in column_map.values():
            header_index(conn.get("header_row", []), header)
        if column_map.get("status") and not column_map.get("meta_lead_id"):
            raise ValueError("Map Meta Lead ID before enabling status write-back.")
        if column_map.get("status") and sum(str(v).strip().casefold() == str(column_map["status"]).strip().casefold() for v in column_map.values()) > 1:
            raise ValueError("The status column must not also map to another field.")
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    if not column_map.get("phone"):
        raise HTTPException(status_code=400, detail="Phone column mapping is required.")
    
    await db.google_sheet_connections.update_one(
        {"workspace_id": ws_id},
        {"$set": {
            "column_map": column_map,
            "updated_at": now_iso()
        }}
    )
    return {"ok": True}


def values_url(spreadsheet_id, sheet_name, cells):
    quoted = "'" + sheet_name.replace("'", "''") + "'!" + cells
    return f"https://sheets.googleapis.com/v4/spreadsheets/{urllib.parse.quote(spreadsheet_id, safe='')}/values/{urllib.parse.quote(quoted, safe='')}"


def column_letter(index):
    result = ""
    while index >= 0:
        result = chr(65 + index % 26) + result
        index = index // 26 - 1
    return result


async def import_sheet_row(db, ws_id, conn, headers, row, row_number, field_keys):
    from models import CRMLead
    values, attribution = map_sheet_row(headers, row, conn.get("column_map", {}), field_keys)
    meta_id = attribution.get("meta_lead_id")
    row_key = meta_id or f"{conn['spreadsheet_id']}_{conn['sheet_name']}_{row_number}"
    alternatives = [{"sheet_row_key": row_key}]
    if meta_id:
        alternatives.insert(0, {"meta_lead_id": meta_id})
    existing = await db.crm_leads.find_one({"workspace_id": ws_id, "$or": alternatives})
    source = {"google_sheet_spreadsheet_id": conn["spreadsheet_id"],
              "google_sheet_name": conn["sheet_name"], "google_sheet_row_number": row_number}
    raw = dict(zip(headers, list(row) + [""] * max(0, len(headers) - len(row))))
    if existing:
        if existing.get("google_sheet_spreadsheet_id") and (existing["google_sheet_spreadsheet_id"], existing.get("google_sheet_name")) != (conn["spreadsheet_id"], conn["sheet_name"]):
            raise ValueError("Meta Lead ID already belongs to another source Sheet in this workspace.")
        # A replay enriches source data but never resets sales status or enqueues write-back.
        await db.crm_leads.update_one({"_id": existing["_id"], "workspace_id": ws_id}, {"$set": {**attribution, **source, "fields": raw}})
        return str(existing["_id"]), False
    status = "new"
    if conn.get("column_map", {}).get("status"):
        index = header_index(headers, conn["column_map"]["status"])
        incoming = str(row[index] if index < len(row) else "").strip().casefold()
        settings = await ensure_crm_settings(db, ws_id)
        status = next((s["key"] for s in settings["states"] if incoming in {s["key"].casefold(), s["label"].casefold()}), "new")
    lead = CRMLead(workspace_id=ws_id, source="google_sheet", sheet_row_key=row_key,
                   **attribution, **source, field_values=values, fields=raw, status=status,
                   **{key: values.get(key) for key in ("email", "full_name", "phone", "address", "assigned_salesperson")}).to_mongo()
    result = await db.crm_leads.update_one({"workspace_id": ws_id, "sheet_row_key": row_key}, {"$setOnInsert": lead}, upsert=True)
    if result.upserted_id:
        return str(result.upserted_id), True
    existing = await db.crm_leads.find_one({"workspace_id": ws_id, "sheet_row_key": row_key})
    return str(existing["_id"]), False


async def sheet_request(db, conn, method, cells, **kwargs):
    async with httpx.AsyncClient(timeout=20) as client:
        url = values_url(conn["spreadsheet_id"], conn["sheet_name"], cells)
        token = conn.get("tokens", {}).get("access_token")
        response = await client.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs)
        if response.status_code == 401:
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))
            token = await refresh_access_token(conn, request)
            response = await client.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs)
        if response.status_code >= 400:
            raise ValueError(f"Google Sheets returned HTTP {response.status_code}. Check access, reconnect Google, and retry.")
        return response.json()


async def sync_lead_status(db, ws_id, lead_id):
    """Write only status; lease across workers and acknowledge only the version sent."""
    query = {"workspace_id": ws_id, "_id": ObjectId(lead_id)}
    now = datetime.now(timezone.utc)
    token = uuid4().hex
    lead = await db.crm_leads.find_one_and_update(
        {**query, "google_sheet_sync_status": {"$in": ["pending", "failed"]},
         "$or": [{"google_sheet_sync_lock_until": {"$exists": False}}, {"google_sheet_sync_lock_until": {"$lt": now.isoformat()}}]},
        {"$set": {"google_sheet_sync_lock": token, "google_sheet_sync_lock_until": (now + timedelta(minutes=5)).isoformat()}})
    if not lead:
        return
    status = lead.get("status", "new")
    outcome = {}
    try:
        conn = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
        if not conn or not conn.get("spreadsheet_id"):
            raise ValueError("Reconnect and bind the original Google Sheet, then retry.")
        if not lead.get("google_sheet_spreadsheet_id") or (lead["google_sheet_spreadsheet_id"], lead.get("google_sheet_name")) != (conn["spreadsheet_id"], conn.get("sheet_name")):
            raise ValueError("Lead source does not match the bound Sheet. Run the migration or restore the original binding.")
        meta_id = str(lead.get("meta_lead_id") or "").strip()
        if not meta_id:
            raise ValueError("Meta Lead ID is missing. Map it and reimport or migrate this lead.")
        mapping = conn.get("column_map", {})
        if not mapping.get("status") or not mapping.get("meta_lead_id"):
            raise ValueError("Map Meta Lead ID and CRM Status in the Google Sheets workflow.")
        headers = (await sheet_request(db, conn, "GET", "1:1")).get("values", [[]])[0]
        id_col = column_letter(header_index(headers, mapping["meta_lead_id"]))
        status_col = column_letter(header_index(headers, mapping["status"]))
        if id_col == status_col:
            raise ValueError("Status and Meta Lead ID must use different columns.")
        ids = (await sheet_request(db, conn, "GET", f"{id_col}2:{id_col}")).get("values", [])
        matches = [i + 2 for i, row in enumerate(ids) if row and str(row[0]).strip() == meta_id]
        if len(matches) != 1:
            raise ValueError("Meta Lead ID is missing or duplicated in the source Sheet; no row was updated.")
        row_number = matches[0]
        settings = await ensure_crm_settings(db, ws_id)
        label = next((s["label"] for s in settings["states"] if s["key"] == status), status)
        cell = f"{status_col}{row_number}"
        current = (await sheet_request(db, conn, "GET", cell)).get("values", [])
        if current != [[label]]:
            await sheet_request(db, conn, "PUT", cell, params={"valueInputOption": "RAW"}, json={"values": [[label]]})
        outcome = {"google_sheet_sync_status": "success", "google_sheet_sync_error": None,
                   "last_google_sheet_sync_at": now_iso(), "google_sheet_row_number": row_number,
                   "google_sheet_synced_status": status, "google_sheet_sync_attempts": 0,
                   "google_sheet_sync_next_attempt_at": None}
    except Exception as error:
        # Do not store provider bodies, tokens, or raw transport exception URLs.
        safe = str(error) if isinstance(error, ValueError) else "Google Sheets sync failed. Check the connection and retry."
        attempts = int(lead.get("google_sheet_sync_attempts") or 0) + 1
        outcome = {"google_sheet_sync_status": "failed", "google_sheet_sync_error": safe,
                   "google_sheet_sync_attempts": attempts,
                   "google_sheet_sync_next_attempt_at": (now + timedelta(seconds=min(3600, 30 * 2 ** min(attempts, 7)))).isoformat()}
        logging.getLogger(__name__).warning("Sheet status sync failed workspace=%s lead=%s: %s", ws_id, lead_id, safe)
    finally:
        await db.crm_leads.update_one({**query, "status": status, "google_sheet_sync_lock": token}, {"$set": outcome})
        await db.crm_leads.update_one({**query, "google_sheet_sync_lock": token}, {"$unset": {"google_sheet_sync_lock": "", "google_sheet_sync_lock_until": ""}})


async def retry_sheet_statuses(db, workspace_ids=None):
    query = {"google_sheet_sync_status": {"$in": ["pending", "failed"]}, "deleted_at": None,
             "$or": [{"google_sheet_sync_next_attempt_at": None}, {"google_sheet_sync_next_attempt_at": {"$lte": now_iso()}}]}
    if workspace_ids:
        query["workspace_id"] = {"$in": workspace_ids}
    async for lead in db.crm_leads.find(query).sort("google_sheet_sync_next_attempt_at", 1).limit(100):
        await sync_lead_status(db, lead["workspace_id"], str(lead["_id"]))


@router.post("/workspaces/{ws_id}/leads/{lead_id}/retry")
async def retry_lead_sync(ws_id: str, lead_id: str, request: Request):
    from crm import require_workspace_access, decorate_lead
    await require_workspace_access(request, ws_id)
    if not ObjectId.is_valid(lead_id):
        raise HTTPException(422, "Invalid lead identifier")
    db = get_db(request)
    query = {"workspace_id": ws_id, "_id": ObjectId(lead_id), "deleted_at": None}
    lead = await db.crm_leads.find_one(query)
    if not lead:
        raise HTTPException(404, "Lead not found")
    if lead.get("google_sheet_sync_status") not in {"pending", "failed"}:
        raise HTTPException(400, "There is no pending or failed sync to retry")
    await sync_lead_status(db, ws_id, lead_id)
    return decorate_lead(await db.crm_leads.find_one(query), await ensure_crm_settings(db, ws_id))
