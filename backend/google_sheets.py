import os
import asyncio
import hmac
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
import urllib.parse
from fastapi import APIRouter, Request, HTTPException, Query, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from bson import ObjectId
from models import GoogleSheetConnection, Workflow, now_iso
import httpx
from crm import active_fields, ensure_crm_settings
from meta_fields import META_FIELDS, header_index, map_sheet_row, strip_meta_phone_prefix

router = APIRouter(prefix="/google")

GOOGLE_READ_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
SHEET_POLL_LOOKBACK_ROWS = 50
SHEET_POLL_BATCH_ROWS = 250
DRIVE_WATCH_RENEW_BEFORE_MS = 6 * 60 * 60 * 1000
DRIVE_WATCH_LIFETIME_MS = 23 * 60 * 60 * 1000

FIELD_ALIASES = {
    "full_name": ["name", "full name", "lead name", "customer name"],
    "phone": ["phone", "phone number", "mobile", "mobile number", "contact number"],
    "email": ["email", "email address", "e-mail"],
    "address": ["address", "location", "full address"],
    "assigned_salesperson": ["assigned salesperson", "salesperson", "owner", "assignee"],
    "source": ["source", "lead source"],
    "status": ["status", "lead status", "crm status"],
}


def normalized_mapping_name(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def mapping_targets(settings):
    targets = [{"key": key, "label": label, "type": "source"} for key, (_, label) in META_FIELDS.items()]
    targets.append({"key": "status", "label": "CRM Status", "type": "status"})
    seen = {target["key"] for target in targets}
    for field in active_fields(settings):
        if field["key"] not in seen:
            targets.append({"key": field["key"], "label": field["label"], "type": field.get("type", "text")})
            seen.add(field["key"])
    return targets


def deterministic_column_map(headers, targets):
    """Create high-confidence exact/alias matches for the AI agent to review and extend."""
    indexed = {}
    for header in headers:
        indexed.setdefault(normalized_mapping_name(header), []).append(header)
    result, used = {}, set()
    for target in targets:
        key = target["key"]
        candidates = [key, target.get("label", "")]
        if key in META_FIELDS:
            candidates.insert(0, META_FIELDS[key][0])
        candidates.extend(FIELD_ALIASES.get(key, []))
        for candidate in candidates:
            matches = indexed.get(normalized_mapping_name(candidate), [])
            if len(matches) == 1 and matches[0] not in used:
                result[key] = matches[0]
                used.add(matches[0])
                break
    return result


def validate_ai_column_map(headers, targets, proposed, baseline=None):
    allowed_keys = {target["key"] for target in targets}
    exact_headers = {str(header): header for header in headers}
    normalized_headers = {}
    for header in headers:
        normalized_headers.setdefault(normalized_mapping_name(header), []).append(header)
    clean, used = {}, set()
    # Exact/alias matches are higher-confidence than model guesses; AI fills gaps.
    for candidate_map in (baseline or {}, proposed or {}):
        if not isinstance(candidate_map, dict):
            continue
        for key, value in candidate_map.items():
            if key not in allowed_keys or not value or key in clean:
                continue
            header = exact_headers.get(str(value))
            if header is None:
                matches = normalized_headers.get(normalized_mapping_name(value), [])
                header = matches[0] if len(matches) == 1 else None
            if header is not None and header not in used:
                clean[key] = header
                used.add(header)
    return clean


async def generate_ai_column_map(model_id, headers, targets, workspace_id=None):
    from llm_service import generate_json
    from ai_usage import usage_scope
    baseline = deterministic_column_map(headers, targets)
    system = (
        "You are a CRM data-mapping agent. Match Google Sheet headers to CRM target fields. "
        "Use only headers and target keys supplied by the user. Never invent a header, never map one header twice, "
        "and omit uncertain mappings. Meta form questions belong in matching configurable CRM fields."
    )
    prompt = json.dumps({
        "sheet_headers": headers,
        "crm_targets": targets,
        "high_confidence_matches": baseline,
        "response_schema": {"column_map": {"target_key": "exact Sheet header"}},
    }, ensure_ascii=False)
    with usage_scope(workspace_id, "sheet_column_mapping"):
        response = await asyncio.wait_for(
            generate_json(model_id, system, prompt, temperature=0.1, max_tokens=1800), timeout=60
        )
    proposed = response.get("column_map", response) if isinstance(response, dict) else {}
    return validate_ai_column_map(headers, targets, proposed, baseline)


async def google_get_with_retry(url, token, attempts=2):
    """Retry transient Google reads, including read timeouts and 5xx responses."""
    last_error = None
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=GOOGLE_READ_TIMEOUT) as client:
                response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if response.status_code != 429 and response.status_code < 500:
                return response
            last_error = response
        except (httpx.TimeoutException, httpx.RequestError) as error:
            last_error = error
        if attempt + 1 < attempts:
            await asyncio.sleep(0.5 * (attempt + 1))
    if isinstance(last_error, httpx.Response):
        return last_error
    raise last_error or httpx.ReadTimeout("Google request timed out")

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


def drive_webhook_url():
    base = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("PUBLIC_BASE_URL must be a public HTTPS URL before activating the Sheet webhook.")
    return f"{base}/api/google/webhooks/drive"


def drive_watch_is_fresh(conn, now_ms=None):
    now_ms = now_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    try:
        expiration = int(conn.get("drive_watch_expiration") or 0)
    except (TypeError, ValueError):
        return False
    return bool(conn.get("drive_watch_channel_id") and expiration > now_ms + DRIVE_WATCH_RENEW_BEFORE_MS)


async def stop_drive_watch(db, conn):
    channel_id = conn.get("drive_watch_channel_id")
    resource_id = conn.get("drive_watch_resource_id")
    if not channel_id or not resource_id:
        return
    token = conn.get("tokens", {}).get("access_token")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://www.googleapis.com/drive/v3/channels/stop",
            headers={"Authorization": f"Bearer {token}"},
            json={"id": channel_id, "resourceId": resource_id},
        )
        if response.status_code == 401:
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))
            token = await refresh_access_token(conn, request)
            response = await client.post(
                "https://www.googleapis.com/drive/v3/channels/stop",
                headers={"Authorization": f"Bearer {token}"},
                json={"id": channel_id, "resourceId": resource_id},
            )
    if response.status_code not in {200, 204, 404, 410}:
        logging.getLogger(__name__).warning(
            "Could not stop Drive watch workspace=%s status=%s", conn.get("workspace_id"), response.status_code
        )


async def ensure_drive_watch(db, conn, force=False):
    """Create or renew the Google Drive push channel used as the Sheet change trigger."""
    if not force and drive_watch_is_fresh(conn):
        return conn
    if not conn.get("spreadsheet_id"):
        raise ValueError("Bind a Google Sheet before activating its webhook.")

    previous = dict(conn)
    channel_id = str(uuid4())
    channel_token = secrets.token_urlsafe(32)
    expiration = int(datetime.now(timezone.utc).timestamp() * 1000) + DRIVE_WATCH_LIFETIME_MS
    pending = {
        "pending_drive_watch_channel_id": channel_id,
        "pending_drive_watch_token": channel_token,
        "drive_watch_status": "creating",
        "drive_watch_error": None,
        "updated_at": now_iso(),
    }
    # Google can deliver its initial sync call before files.watch returns.
    await db.google_sheet_connections.update_one({"_id": conn["_id"]}, {"$set": pending})
    token = conn.get("tokens", {}).get("access_token")
    url = f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(conn['spreadsheet_id'], safe='')}/watch"
    payload = {
        "id": channel_id,
        "type": "web_hook",
        "address": drive_webhook_url(),
        "token": channel_token,
        "expiration": expiration,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, headers={"Authorization": f"Bearer {token}"}, json=payload)
        if response.status_code == 401:
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))
            token = await refresh_access_token(conn, request)
            response = await client.post(url, headers={"Authorization": f"Bearer {token}"}, json=payload)
    if response.status_code >= 400:
        safe = f"Google Drive could not activate the Sheet webhook (HTTP {response.status_code})."
        await db.google_sheet_connections.update_one(
            {"_id": conn["_id"], "pending_drive_watch_channel_id": channel_id},
            {"$set": {"drive_watch_status": "failed", "drive_watch_error": safe, "updated_at": now_iso()},
             "$unset": {"pending_drive_watch_channel_id": "", "pending_drive_watch_token": ""}},
        )
        raise ValueError(safe)

    channel = response.json()
    updates = {
        "drive_watch_channel_id": channel_id,
        "drive_watch_token": channel_token,
        "drive_watch_resource_id": channel.get("resourceId"),
        "drive_watch_expiration": int(channel.get("expiration") or expiration),
        "drive_watch_status": "active",
        "drive_watch_error": None,
        "drive_watch_updated_at": now_iso(),
    }
    await db.google_sheet_connections.update_one(
        {"_id": conn["_id"], "pending_drive_watch_channel_id": channel_id},
        {"$set": updates, "$unset": {"pending_drive_watch_channel_id": "", "pending_drive_watch_token": ""}},
    )
    if previous.get("drive_watch_channel_id") and previous.get("drive_watch_resource_id"):
        try:
            await stop_drive_watch(db, previous)
        except Exception:
            logging.getLogger(__name__).warning(
                "Old Drive watch cleanup failed workspace=%s", conn.get("workspace_id"), exc_info=True
            )
    return {**conn, **updates}

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
        "webhook_status": conn.get("drive_watch_status", "inactive"),
        "webhook_error": conn.get("drive_watch_error"),
        "webhook_expires_at": conn.get("drive_watch_expiration"),
    }

@router.delete("/workspaces/{ws_id}")
async def disconnect_google(ws_id: str, request: Request):
    db = request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")
    conn = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
    if conn:
        try:
            await stop_drive_watch(db, conn)
        except Exception:
            logging.getLogger(__name__).warning("Drive watch cleanup failed workspace=%s", ws_id, exc_info=True)
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
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}?fields=sheets.properties.title"
        return await google_get_with_retry(url, token)

    access_token = conn["tokens"].get("access_token")
    try:
        res = await try_fetch(access_token)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Google took too long to return the Sheet tabs. Retry loading tabs.") from None
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Could not reach Google Sheets. Check your connection and retry loading tabs.") from None
    if res.status_code == 401:
        access_token = await refresh_access_token(conn, request)
        try:
            res = await try_fetch(access_token)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Google took too long to return the Sheet tabs. Retry loading tabs.") from None
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail="Could not reach Google Sheets. Check your connection and retry loading tabs.") from None
    if res.status_code != 200:
        raise HTTPException(status_code=res.status_code, detail="Google could not return the Sheet tabs. Retry, or reconnect Google if the problem continues.")
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

    if conn.get("drive_watch_channel_id"):
        try:
            await stop_drive_watch(db, conn)
        except Exception:
            logging.getLogger(__name__).warning("Old Drive watch cleanup failed workspace=%s", ws_id, exc_info=True)
    
    await db.google_sheet_connections.update_one(
        {"workspace_id": ws_id},
        {"$set": {
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_name": spreadsheet_name,
            "sheet_name": sheet_name,
            "header_row": headers_list,
            "cursor": 1,
            "drive_watch_status": "inactive",
            "updated_at": now_iso()
        }, "$unset": {
            "drive_watch_channel_id": "", "drive_watch_token": "",
            "drive_watch_resource_id": "", "drive_watch_expiration": "",
            "pending_drive_watch_channel_id": "", "pending_drive_watch_token": ""
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
            {"$set": {"sheet_connection_id": str(conn_doc["_id"]), "status": "draft", "published_at": None}}
        )

    return {"ok": True, "headers": headers_list}


@router.post("/workspaces/{ws_id}/suggest-column-map")
async def suggest_column_map(ws_id: str, request: Request):
    from crm import require_workspace_access
    await require_workspace_access(request, ws_id)
    db = get_db(request)
    conn = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
    if not conn or not conn.get("spreadsheet_id") or not conn.get("sheet_name"):
        raise HTTPException(400, "Bind a spreadsheet and tab before running AI matching.")
    headers = conn.get("header_row") or []
    if not headers:
        raise HTTPException(400, "The bound Sheet does not contain a header row.")
    settings = await ensure_crm_settings(db, ws_id)
    targets = mapping_targets(settings)
    workspace = await db.workspaces.find_one({"_id": ObjectId(ws_id)})
    baseline = deterministic_column_map(headers, targets)
    try:
        column_map = await generate_ai_column_map(workspace.get("model_id") if workspace else None, headers, targets, ws_id)
        source, warning = "ai", None
    except Exception as error:
        logging.getLogger(__name__).warning(
            "AI Sheet mapping unavailable workspace=%s error_type=%s", ws_id, type(error).__name__
        )
        column_map = baseline
        source = "high_confidence_fallback"
        warning = "The AI agent was unavailable, so only high-confidence matches were applied. Review the remaining fields."
    return {"column_map": column_map, "source": source, "warning": warning,
            "matched": len(column_map), "total": len(targets)}

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
        updates = {**attribution, **source, "fields": raw}
        incoming_phone = values.get("phone")
        if incoming_phone:
            for path, old_phone in (("phone", existing.get("phone")),
                                    ("field_values.phone", (existing.get("field_values") or {}).get("phone"))):
                if (isinstance(old_phone, str) and old_phone != incoming_phone
                        and strip_meta_phone_prefix(old_phone) == incoming_phone):
                    updates[path] = incoming_phone
        await db.crm_leads.update_one({"_id": existing["_id"], "workspace_id": ws_id}, {"$set": updates})
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


async def poll_sheet_connection(db, ws_id, conn):
    """Import one bounded Sheet batch with overlap so late-filled rows are not missed."""
    from plivo_calls import schedule_first_qualification_call

    header_rows = (await sheet_request(db, conn, "GET", "1:1")).get("values") or [[]]
    headers = header_rows[0]
    if not headers:
        raise ValueError("The bound Sheet does not contain a header row.")
    current_cursor = max(1, int(conn.get("cursor") or 1))
    start_row = max(2, current_cursor + 1 - SHEET_POLL_LOOKBACK_ROWS)
    end_row = start_row + SHEET_POLL_BATCH_ROWS - 1
    cells = f"A{start_row}:{column_letter(max(len(headers) - 1, 0))}{end_row}"
    rows = (await sheet_request(db, conn, "GET", cells)).get("values") or []
    if not rows:
        return {"created": 0, "reviewed": 0, "cursor": current_cursor}

    settings = await ensure_crm_settings(db, ws_id)
    field_keys = {field["key"] for field in active_fields(settings)}
    created_count = 0
    reviewed_count = 0
    for offset, row in enumerate(rows):
        row_number = start_row + offset
        if not any(str(value or "").strip() for value in row):
            continue
        lead_id, created = await import_sheet_row(db, ws_id, conn, headers, row, row_number, field_keys)
        reviewed_count += 1
        if created:
            await schedule_first_qualification_call(db, ws_id, lead_id)
            created_count += 1

    new_cursor = max(current_cursor, start_row + len(rows) - 1)
    await db.google_sheet_connections.update_one(
        {"workspace_id": ws_id},
        {"$set": {"cursor": new_cursor, "updated_at": now_iso()}},
    )
    return {"created": created_count, "reviewed": reviewed_count, "cursor": new_cursor}


async def drain_sheet_connection(db, ws_id, conn, max_batches=20):
    """Drain appended rows after one notification, including large bulk appends."""
    total_created = total_reviewed = 0
    cursor = max(1, int(conn.get("cursor") or 1))
    for _ in range(max_batches):
        current = {**conn, "cursor": cursor}
        result = await poll_sheet_connection(db, ws_id, current)
        total_created += result["created"]
        total_reviewed += result["reviewed"]
        if result["cursor"] <= cursor:
            break
        cursor = result["cursor"]
    return {"created": total_created, "reviewed": total_reviewed, "cursor": cursor}


@router.post("/workspaces/{ws_id}/sync")
async def sync_sheet_now(ws_id: str, request: Request):
    """Serverless-safe authenticated poll used by the dashboard and manual recovery."""
    from crm import require_workspace_access

    await require_workspace_access(request, ws_id)
    db = get_db(request)
    workflow = await db.workflows.find_one({"workspace_id": ws_id, "kind": "ads_to_crm"})
    if not workflow or workflow.get("status") != "published":
        return {"status": "paused", "created": 0, "reviewed": 0}
    conn = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
    if not conn or not conn.get("spreadsheet_id") or not conn.get("sheet_name"):
        raise HTTPException(409, "Connect and bind a Google Sheet before syncing.")
    try:
        result = await poll_sheet_connection(db, ws_id, conn)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    return {"status": "synced", **result}


@router.post("/webhooks/drive")
async def google_drive_webhook(request: Request):
    """Receive a Google Drive notification and import newly appended Sheet rows."""
    db = get_db(request)
    channel_id = request.headers.get("x-goog-channel-id", "").strip()
    supplied_token = request.headers.get("x-goog-channel-token", "").strip()
    resource_id = request.headers.get("x-goog-resource-id", "").strip()
    resource_state = request.headers.get("x-goog-resource-state", "").strip().lower()
    if not channel_id or not supplied_token:
        raise HTTPException(401, "Missing Google notification proof")
    conn = await db.google_sheet_connections.find_one({"$or": [
        {"drive_watch_channel_id": channel_id},
        {"pending_drive_watch_channel_id": channel_id},
    ]})
    pending_channel = bool(conn and conn.get("pending_drive_watch_channel_id") == channel_id)
    expected_token = str((conn or {}).get("pending_drive_watch_token" if pending_channel else "drive_watch_token") or "")
    if not conn or not expected_token or not hmac.compare_digest(supplied_token, expected_token):
        raise HTTPException(403, "Invalid Google notification proof")
    expected_resource = "" if pending_channel else str(conn.get("drive_watch_resource_id") or "")
    if expected_resource and (not resource_id or not hmac.compare_digest(resource_id, expected_resource)):
        raise HTTPException(403, "Invalid Google notification resource")
    if resource_state == "sync" or resource_state not in {"update", "add", "change"}:
        return Response(status_code=204)

    ws_id = conn["workspace_id"]
    workflow = await db.workflows.find_one({"workspace_id": ws_id, "kind": "ads_to_crm", "status": "published"})
    if not workflow:
        return Response(status_code=204)
    lock_token = uuid4().hex
    now = datetime.now(timezone.utc)
    lease = await db.google_sheet_connections.update_one(
        {"_id": conn["_id"], "$or": [
            {"webhook_import_lock_until": {"$exists": False}},
            {"webhook_import_lock_until": {"$lt": now.isoformat()}},
        ]},
        {"$set": {
            "webhook_import_lock": lock_token,
            "webhook_import_lock_until": (now + timedelta(minutes=2)).isoformat(),
        }},
    )
    if not lease.modified_count:
        return Response(status_code=204)
    try:
        result = await drain_sheet_connection(db, ws_id, conn)
        if result["created"]:
            from models import Notification
            notification = Notification(
                workspace_id=ws_id,
                kind="success",
                title=f"{result['created']} new leads imported",
                body=f"Imported {result['created']} new lead(s) from your connected Google Sheet webhook.",
            )
            await db.notifications.insert_one(notification.to_mongo())
    except Exception:
        logging.getLogger(__name__).exception("Drive webhook import failed workspace=%s", ws_id)
        raise HTTPException(503, "Sheet import temporarily failed") from None
    finally:
        await db.google_sheet_connections.update_one(
            {"_id": conn["_id"], "webhook_import_lock": lock_token},
            {"$unset": {"webhook_import_lock": "", "webhook_import_lock_until": ""}},
        )
    return Response(status_code=204)


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
