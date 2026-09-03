import base64
import hashlib
import hmac
import html
import os
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from bson import ObjectId
from fastapi import HTTPException, Request, Response

from crm import (
    build_manual_lead,
    decorate_lead,
    ensure_crm_settings,
    lead_query,
    normalize_lead_note,
)
from models import now_iso


COLLECTION = "crm_call_logs"


def normalize_phone(value):
    raw = str(value or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.startswith("+"):
        return f"+{digits}"
    return digits


def public_base_url(request: Request):
    configured = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


def public_request_url(request: Request):
    base = public_base_url(request)
    path = request.url.path
    query = request.url.query
    return f"{base}{path}{('?' + query) if query else ''}"


def plivo_config():
    cfg = {
        "auth_id": os.environ.get("PLIVO_AUTH_ID", "").strip(),
        "auth_token": os.environ.get("PLIVO_AUTH_TOKEN", "").strip(),
        "from_number": normalize_phone(os.environ.get("PLIVO_FROM_NUMBER", "")),
        "staff_number": normalize_phone(os.environ.get("PLIVO_STAFF_NUMBER", "")),
    }
    missing = [key for key, value in cfg.items() if not value]
    if missing:
        raise HTTPException(status_code=400, detail=f"Plivo is not configured: missing {', '.join(missing)}")
    return cfg


def callback_urls(base, ws_id, lead_id=None):
    root = f"{base}/api/plivo/workspaces/{ws_id}/calls"
    lead_query = f"?lead_id={lead_id}" if lead_id else ""
    return {
        "outbound_answer": f"{root}/{lead_id}/outbound/answer" if lead_id else "",
        "outbound_status": f"{root}/outbound/status{lead_query}",
        "inbound_answer": f"{root}/inbound/answer",
        "recording": f"{root}/recording{lead_query}",
    }


def _signature_payload(method, url, nonce, params):
    if method.upper() == "GET":
        return f"{url}.{nonce}"
    pairs = []
    for key in sorted((params or {}).keys()):
        value = params.get(key)
        if isinstance(value, list):
            value = value[0] if value else ""
        pairs.append(f"{key}{value}")
    return f"{url}{''.join(pairs)}.{nonce}"


def validate_signature(method, url, nonce, signature, auth_token, params=None):
    if not nonce or not signature or not auth_token:
        return False
    payload = _signature_payload(method, url, nonce, params)
    digest = hmac.new(auth_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return any(hmac.compare_digest(expected, item.strip()) for item in str(signature).split(","))


async def require_plivo_signature(request: Request, params):
    if os.environ.get("PLIVO_VALIDATE_SIGNATURE", "true").lower() in {"0", "false", "no"}:
        return
    auth_token = os.environ.get("PLIVO_AUTH_TOKEN", "").strip()
    if not auth_token:
        raise HTTPException(status_code=400, detail="Plivo auth token is not configured")
    signature = request.headers.get("X-Plivo-Signature-V3") or request.headers.get("X-Plivo-Signature-Ma-V3")
    nonce = request.headers.get("X-Plivo-Signature-V3-Nonce")
    if not validate_signature(request.method, public_request_url(request), nonce, signature, auth_token, params):
        raise HTTPException(status_code=403, detail="Invalid Plivo signature")


def plivo_xml(body):
    return Response(content=f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>', media_type="text/xml")


def outbound_bridge_xml(lead_phone, recording_url):
    return plivo_xml(
        f'<Record startOnDialAnswer="true" redirect="false" callbackUrl="{html.escape(recording_url)}" callbackMethod="POST" />'
        f"<Dial><Number>{html.escape(lead_phone)}</Number></Dial>"
    )


def inbound_bridge_xml(staff_phone, recording_url):
    return plivo_xml(
        f'<Record startOnDialAnswer="true" redirect="false" callbackUrl="{html.escape(recording_url)}" callbackMethod="POST" />'
        f"<Dial><Number>{html.escape(staff_phone)}</Number></Dial>"
    )


async def log_call_note(db, ws_id, lead_id, payload, body):
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)})
    if not lead:
        return None
    call_uuid = str(payload.get("CallUUID") or payload.get("CallUuid") or payload.get("call_uuid") or "")
    status = str(payload.get("CallStatus") or payload.get("HangupCause") or payload.get("status") or body.get("status") or "").strip()
    direction = str(body.get("call_direction") or payload.get("Direction") or "").strip() or "outbound"
    note_key = f"{call_uuid}:{status}:{body.get('event', 'call')}"
    if call_uuid:
        existing = await db.crm_leads.find_one({
            "workspace_id": ws_id,
            "_id": ObjectId(lead_id),
            "lead_notes.call_key": note_key,
        })
        if existing:
            return decorate_lead(lead, await ensure_crm_settings(db, ws_id))
    note = normalize_lead_note({
        "body": body.get("body") or f"{direction.title()} Plivo call {status or 'updated'}",
        "author": "Plivo",
        "source": "call_agent",
        "call_provider": "plivo",
        "call_id": call_uuid,
        "direction": direction,
        "duration": payload.get("Duration") or payload.get("RecordingDuration") or "",
        "outcome": body.get("outcome") or status,
        "transcript": payload.get("Transcription") or payload.get("transcript") or "",
        "summary": body.get("summary") or status,
    })
    note.update({
        "call_key": note_key,
        "call_direction": direction,
        "call_uuid": call_uuid,
        "from_number": normalize_phone(payload.get("From") or payload.get("CallerName") or body.get("from_number")),
        "to_number": normalize_phone(payload.get("To") or body.get("to_number")),
        "status": status,
        "recording_url": payload.get("RecordUrl") or payload.get("RecordingUrl") or "",
    })
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": ObjectId(lead_id)},
        {"$push": {"lead_notes": note}, "$set": {"updated_at": now_iso()}},
    )
    await db[COLLECTION].update_one(
        {"workspace_id": ws_id, "lead_id": str(lead_id), "call_key": note_key},
        {"$setOnInsert": {"created_at": now_iso()}, "$set": {"payload": dict(payload), "note": note, "updated_at": now_iso()}},
        upsert=True,
    )
    settings = await ensure_crm_settings(db, ws_id)
    return decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings)


async def find_or_create_inbound_lead(db, ws_id, caller_phone):
    settings = await ensure_crm_settings(db, ws_id)
    normalized = normalize_phone(caller_phone)
    docs = await db.crm_leads.find(lead_query(ws_id)).sort("updated_at", -1).to_list(5000)
    for doc in docs:
        values = doc.get("field_values") or {}
        phone = normalize_phone(values.get("phone") or doc.get("phone"))
        if phone and phone == normalized:
            return decorate_lead(doc, settings), False
    lead_doc = build_manual_lead(ws_id, {
        "field_values": {
            "phone": normalized,
            "source": "plivo_inbound",
        },
    }, settings)
    lead_doc["source"] = "plivo_inbound"
    lead_doc["timeline"] = [{"type": "created", "label": "Lead created from inbound Plivo call", "created_at": now_iso()}]
    await db.crm_leads.insert_one(lead_doc)
    return decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": lead_doc["_id"]}), settings), True


async def start_outbound_call(db, ws_id, lead_id, request: Request):
    cfg = plivo_config()
    settings = await ensure_crm_settings(db, ws_id)
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    values = lead.get("field_values") or {}
    lead_phone = normalize_phone(values.get("phone") or lead.get("phone"))
    if not lead_phone:
        raise HTTPException(status_code=400, detail="Lead phone number is required before calling")
    urls = callback_urls(public_base_url(request), ws_id, lead_id)
    payload = {
        "from": cfg["from_number"],
        "to": cfg["staff_number"],
        "answer_url": urls["outbound_answer"],
        "answer_method": "POST",
        "hangup_url": urls["outbound_status"],
        "hangup_method": "POST",
        "ring_url": urls["outbound_status"],
        "ring_method": "POST",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"https://api.plivo.com/v1/Account/{cfg['auth_id']}/Call/",
            data=payload,
            auth=(cfg["auth_id"], cfg["auth_token"]),
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Plivo could not start the call")
    data = response.json()
    call_uuid = data.get("request_uuid") or data.get("requestUuid") or data.get("message_uuid") or ""
    updated = await log_call_note(db, ws_id, lead_id, {
        "CallUUID": call_uuid,
        "From": cfg["staff_number"],
        "To": lead_phone,
        "CallStatus": "started",
    }, {
        "event": "outbound_started",
        "body": f"Outbound Plivo call started. Staff will be bridged to {lead_phone}.",
        "call_direction": "outbound",
        "outcome": "started",
    })
    return {
        "status": "started",
        "provider": "plivo",
        "call_uuid": call_uuid,
        "lead": updated or decorate_lead(lead, settings),
    }
