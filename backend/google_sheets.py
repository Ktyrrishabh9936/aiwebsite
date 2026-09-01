import os
import urllib.parse
from fastapi import APIRouter, Request, HTTPException, Query, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from bson import ObjectId
from models import GoogleSheetConnection, Workflow, now_iso
import httpx
from crm import active_fields, ensure_crm_settings

router = APIRouter(prefix="/google")

SCOPES = " ".join([
    "https://www.googleapis.com/auth/spreadsheets.readonly",
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
        "header_row": conn.get("header_row", [])
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
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{sheet_name}!A1:Z1"
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
    column_map = {k: v for k, v in (body.get("column_map", {}) or {}).items() if k in allowed or k == "meta_lead_id"}
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
