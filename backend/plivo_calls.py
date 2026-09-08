import base64
import hashlib
import hmac
import html
import json
import logging
import os
from datetime import datetime, timedelta, timezone

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
logger = logging.getLogger("plivo_calls")
QUALIFICATION_CATEGORIES = {"hot", "warm", "cold", "junk"}
JUNK_DISCONNECTION_REASONS = {"invalid_number", "number_unreachable", "unreachable", "wrong_contact", "fake_lead", "do_not_call", "not_interested"}
JUNK_RESULT_VALUES = {"declined", "not_interested", "do_not_call", "wrong_contact", "invalid_number", "number_unreachable", "fake_lead", "junk"}
TERMINAL_CALL_STATUSES = {"completed", "failed", "busy", "no_answer", "rejected", "cancelled", "canceled", "hangup"}
SUMMARY_KEYS = {
    "summary",
    "call_summary",
    "callSummary",
    "conversation_summary",
    "conversationSummary",
    "qualification_summary",
    "qualificationSummary",
    "final_summary",
    "finalSummary",
    "lead_summary",
    "leadSummary",
    "message",
    "text",
    "content",
    "notes",
    "transcript",
}


def normalize_phone(value):
    raw = str(value or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.startswith("+"):
        return f"+{digits}"
    return digits


def normalize_lead_phone(value):
    phone = normalize_phone(value)
    digits = phone[1:] if phone.startswith("+") else phone
    default_country = os.environ.get("PLIVO_DEFAULT_COUNTRY_CODE", "+91").strip() or "+91"
    default_digits = "".join(ch for ch in default_country if ch.isdigit())
    if phone.startswith("+"):
        return phone
    if default_digits == "91" and len(digits) == 10:
        return f"+91{digits}"
    if default_digits and digits.startswith(default_digits) and len(digits) > len(default_digits):
        return f"+{digits}"
    return phone


def require_e164_phone(phone):
    if not phone.startswith("+"):
        raise HTTPException(status_code=400, detail=f"Lead phone must be in E.164 format before calling, got {phone or 'empty'}")
    digits = phone[1:]
    if not digits.isdigit() or len(digits) < 8 or len(digits) > 15:
        raise HTTPException(status_code=400, detail=f"Lead phone must be a valid E.164 number, got {phone}")
    return phone


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


def plivo_agent_config():
    cfg = {
        "trigger_url": os.environ.get("PLIVO_AGENT_TRIGGER_URL", "").strip(),
        "trigger_token": os.environ.get("PLIVO_AGENT_TRIGGER_TOKEN", "").strip(),
        "from_number": normalize_phone(os.environ.get("PLIVO_FROM_NUMBER", "")),
    }
    missing = [key for key in ("trigger_url", "from_number") if not cfg.get(key)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Plivo AI qualification is not configured: missing {', '.join(missing)}")
    return cfg


def plivo_config_debug(base=None, ws_id=None, lead_id=None):
    raw = {
        "auth_id": os.environ.get("PLIVO_AUTH_ID", "").strip(),
        "auth_token": os.environ.get("PLIVO_AUTH_TOKEN", "").strip(),
        "from_number": normalize_phone(os.environ.get("PLIVO_FROM_NUMBER", "")),
        "staff_number": normalize_phone(os.environ.get("PLIVO_STAFF_NUMBER", "")),
        "agent_trigger_url": os.environ.get("PLIVO_AGENT_TRIGGER_URL", "").strip(),
        "agent_trigger_token": os.environ.get("PLIVO_AGENT_TRIGGER_TOKEN", "").strip(),
        "public_base_url": (base or os.environ.get("PUBLIC_BASE_URL", "")).strip().rstrip("/"),
        "signature_validation": os.environ.get("PLIVO_VALIDATE_SIGNATURE", "true").lower() not in {"0", "false", "no"},
    }
    required = ("auth_id", "auth_token", "from_number", "public_base_url")
    missing = [key for key in required if not raw.get(key)]
    urls = callback_urls(raw["public_base_url"], ws_id, lead_id) if raw["public_base_url"] and ws_id else {}
    callbacks = {
        "status_url": urls["outbound_status"],
        "recording_url": urls["recording"],
        "result_url": urls["qualification_result"],
    }
    return {
        "configured": not missing,
        "missing": missing,
        "from_number": raw["from_number"],
        "staff_number": raw["staff_number"],
        "public_base_url": raw["public_base_url"],
        "public_base_url_https": raw["public_base_url"].startswith("https://"),
        "signature_validation": raw["signature_validation"],
        "auth_id_configured": bool(raw["auth_id"]),
        "auth_token_configured": bool(raw["auth_token"]),
        "agent_trigger_url_configured": bool(raw["agent_trigger_url"]),
        "agent_trigger_token_configured": bool(raw["agent_trigger_token"]),
        "dial_sequence": "agent_direct_to_lead",
        "required_trigger_payload_fields": ["to_number", "from_number", "customer_name", "lead_source", "callbacks.result_url"],
        "urls": urls,
    }


def callback_urls(base, ws_id, lead_id=None):
    root = f"{base}/api/plivo/workspaces/{ws_id}/calls"
    lead_query = f"?lead_id={lead_id}" if lead_id else ""
    return {
        "outbound_answer": f"{root}/{lead_id}/outbound/answer" if lead_id else "",
        "outbound_status": f"{root}/outbound/status{lead_query}",
        "inbound_answer": f"{root}/inbound/answer",
        "recording": f"{root}/recording{lead_query}",
        "qualification_result": f"{root}/{lead_id}/qualification/result" if lead_id else "",
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


def outbound_bridge_xml(lead_phone, recording_url, caller_id=None, timeout=45):
    attrs = []
    if caller_id:
        attrs.append(f'callerId="{html.escape(caller_id)}"')
    if timeout:
        attrs.append(f'timeout="{int(timeout)}"')
    dial_tag = f"<Dial{' ' + ' '.join(attrs) if attrs else ''}>"
    return plivo_xml(
        f'<Record startOnDialAnswer="true" redirect="false" callbackUrl="{html.escape(recording_url)}" callbackMethod="POST" />'
        f"{dial_tag}<Number>{html.escape(lead_phone)}</Number></Dial>"
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
    call_status = str(payload.get("CallStatus") or payload.get("status") or body.get("status") or "").strip()
    hangup_cause = str(payload.get("HangupCause") or payload.get("HangupCauseCode") or "").strip()
    status = call_status or hangup_cause
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
    note_body = body.get("body") or f"{direction.title()} Plivo call {status or 'updated'}"
    if hangup_cause and hangup_cause not in note_body:
        note_body = f"{note_body} (hangup: {hangup_cause})"
    note = normalize_lead_note({
        "body": note_body,
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
        "call_status": call_status,
        "hangup_cause": hangup_cause,
        "recording_url": payload.get("RecordUrl") or payload.get("RecordingUrl") or "",
    })
    set_updates = {"updated_at": now_iso()}
    recording_url = payload.get("RecordUrl") or payload.get("RecordingUrl") or payload.get("recording_url") or ""
    duration = payload.get("Duration") or payload.get("RecordingDuration") or payload.get("duration") or ""
    normalized_status = qualification_status_from_plivo(payload)
    disconnection_reason = normalize_disconnection_reason(payload)
    terminal_status = normalized_status in TERMINAL_CALL_STATUSES or str(status).strip().lower() in TERMINAL_CALL_STATUSES
    if body.get("event") == "recording" and recording_url:
        set_updates.update({
            "qualification_call.recording_url": recording_url,
            "communication_summary.last_recording_url": recording_url,
        })
    if body.get("event") == "outbound_status":
        previous = lead.get("communication_summary") or {}
        latest_summary = note_body
        if disconnection_reason:
            latest_summary = f"{latest_summary} ({disconnection_reason})"
        set_updates.update({
            "communication_summary.latest_summary": latest_summary,
            "communication_summary.last_call_status": normalized_status,
            "communication_summary.last_call_uuid": call_uuid,
            "communication_summary.disconnection_reason": disconnection_reason,
            "qualification_call.disconnection_reason": disconnection_reason,
        })
        if terminal_status and not (previous.get("last_call_uuid") == call_uuid and previous.get("last_call_status") in TERMINAL_CALL_STATUSES):
            set_updates["communication_summary.total_call_count"] = int(previous.get("total_call_count") or 0) + 1
    if duration:
        set_updates.setdefault("qualification_call.duration", str(duration))
        set_updates.setdefault("communication_summary.last_duration", str(duration))
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": ObjectId(lead_id)},
        {"$push": {"lead_notes": note}, "$set": set_updates},
    )
    await db[COLLECTION].update_one(
        {"workspace_id": ws_id, "lead_id": str(lead_id), "call_key": note_key},
        {"$setOnInsert": {"created_at": now_iso()}, "$set": {"payload": dict(payload), "note": note, "updated_at": now_iso()}},
        upsert=True,
    )
    settings = await ensure_crm_settings(db, ws_id)
    return decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings)


def plivo_error_detail(response):
    text = response.text or ""
    try:
        data = response.json()
        if isinstance(data, dict):
            text = data.get("error") or data.get("message") or data.get("detail") or text
    except Exception:
        pass
    text = " ".join(str(text).split())
    if len(text) > 300:
        text = text[:300] + "..."
    return f"Plivo could not start the call: HTTP {response.status_code}" + (f" - {text}" if text else "")


def lead_phone_from_doc(lead):
    values = lead.get("field_values") or {}
    return normalize_lead_phone(values.get("phone") or lead.get("phone"))


def scheduled_for_iso(minutes=5, base=None):
    base = base or datetime.now(timezone.utc)
    return (base + timedelta(minutes=minutes)).isoformat()


def parse_iso_datetime(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_junk_lead(lead):
    qualification = lead.get("qualification_call") or {}
    return qualification.get("qualification_category") == "junk"


def normalize_qualification_score(payload):
    for key in ("qualification_score", "score", "lead_score", "percentage", "qualification_percentage"):
        raw = payload.get(key)
        if raw is None or raw == "":
            continue
        try:
            score = float(str(raw).strip().rstrip("%"))
        except (TypeError, ValueError):
            continue
        return int(max(0, min(100, round(score))))
    return None


def parse_jsonish_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def parse_jsonish_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
    return []


def first_nested_value(payload, keys, depth=0):
    if depth > 5:
        return ""
    payload = parse_jsonish_dict(payload) if isinstance(payload, str) else payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if value not in (None, "", [], {}):
                if isinstance(value, (dict, list)):
                    nested = first_nested_value(value, keys, depth + 1)
                    if nested:
                        return nested
                return value
        for value in payload.values():
            nested = first_nested_value(value, keys, depth + 1)
            if nested:
                return nested
    elif isinstance(payload, list):
        for value in payload:
            nested = first_nested_value(value, keys, depth + 1)
            if nested:
                return nested
    return ""


def unwrap_qualification_payload(payload):
    payload = dict(payload or {})
    merged = dict(payload)
    for key in ("data", "result", "output", "payload", "variables", "callback", "response", "body", "arguments"):
        nested = parse_jsonish_dict(payload.get(key))
        if nested:
            merged.update(unwrap_qualification_payload(nested))
    return merged


def category_from_score(score):
    if score is None:
        return ""
    if score >= 80:
        return "hot"
    if score >= 50:
        return "warm"
    if score >= 20:
        return "cold"
    return "junk"


def normalize_qualification_category(payload, score=None):
    raw = str(
        payload.get("qualification_category")
        or payload.get("category")
        or payload.get("lead_category")
        or payload.get("qualification")
        or ""
    ).strip().lower().replace(" lead", "").replace("invalid", "junk")
    if raw in QUALIFICATION_CATEGORIES:
        return raw
    return category_from_score(score) or ""


def normalize_disconnection_reason(payload):
    raw = str(
        payload.get("disconnection_reason")
        or payload.get("disconnect_reason")
        or payload.get("HangupCause")
        or payload.get("HangupCauseCode")
        or payload.get("hangup_cause")
        or payload.get("reason")
        or ""
    ).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "user_busy": "busy",
        "no_answer": "no_answer",
        "noanswer": "no_answer",
        "unreachable": "number_unreachable",
        "not_reachable": "number_unreachable",
        "invalid": "invalid_number",
        "wrong_number": "wrong_contact",
        "dnc": "do_not_call",
    }
    return aliases.get(raw, raw)


def raw_qualification_result_value(payload):
    return str(
        payload.get("qualification_status")
        or payload.get("result")
        or payload.get("outcome")
        or payload.get("status")
        or ""
    ).strip().lower().replace("-", "_").replace(" ", "_")


def is_mandatory_junk_result(payload):
    return (
        raw_qualification_result_value(payload) in JUNK_RESULT_VALUES
        or normalize_disconnection_reason(payload) in JUNK_DISCONNECTION_REASONS
    )


async def mark_lead_junk(db, ws_id, lead_id, reason, payload=None):
    now = now_iso()
    payload = payload or {}
    note = normalize_lead_note({
        "body": f"Lead marked junk by AI qualification: {reason}",
        "author": "Plivo",
        "source": "call_agent",
        "call_provider": "plivo",
        "direction": "outbound",
        "outcome": "junk",
        "summary": reason,
    })
    note.update({
        "call_key": f"qualification_junk:{lead_id}:{now}",
        "status": "junk",
        "call_status": "junk",
        "disconnection_reason": reason,
    })
    qualification = {
        "status": "failed",
        "provider": "plivo",
        "mode": "agent_direct_to_lead",
        "phone": lead_phone_from_doc(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}) or {}),
        "qualification_category": "junk",
        "qualification_score": 0,
        "summary": reason,
        "last_error": reason,
        "disconnection_reason": reason,
        "result": payload,
        "updated_at": now,
    }
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": ObjectId(lead_id)},
        {"$set": {"status": "lost", "qualification_call": qualification, "updated_at": now}, "$push": {"lead_notes": note}},
    )
    await db[COLLECTION].insert_one({
        "workspace_id": ws_id,
        "lead_id": str(lead_id),
        "call_key": note["call_key"],
        "kind": "ai_qualification_junk",
        "status": "junk",
        "payload": payload,
        "error": reason,
        "created_at": now,
        "updated_at": now,
    })
    return qualification


async def schedule_first_qualification_call(db, ws_id, lead_id, delay_minutes=5):
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if is_junk_lead(lead):
        settings = await ensure_crm_settings(db, ws_id)
        return {"status": "skipped", "reason": "lead is marked junk", "lead": decorate_lead(lead, settings)}
    lead_phone = lead_phone_from_doc(lead)
    try:
        require_e164_phone(lead_phone)
    except HTTPException as exc:
        await mark_lead_junk(db, ws_id, lead_id, str(exc.detail))
        settings = await ensure_crm_settings(db, ws_id)
        return {"status": "junk", "reason": str(exc.detail), "lead": decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings)}
    qualification = lead.get("qualification_call") or {}
    if qualification.get("status") in {"scheduled", "queued", "started", "answered", "completed"}:
        settings = await ensure_crm_settings(db, ws_id)
        return {"status": "skipped", "reason": "qualification call already scheduled or triggered", "lead": decorate_lead(lead, settings)}
    now = now_iso()
    scheduled = {
        **qualification,
        "status": "scheduled",
        "provider": "plivo",
        "mode": "agent_direct_to_lead",
        "phone": lead_phone,
        "scheduled_for": scheduled_for_iso(delay_minutes, parse_iso_datetime(lead.get("created_at"))),
        "auto_triggered": False,
        "updated_at": now,
    }
    note = normalize_lead_note({
        "body": f"AI qualification call scheduled for {scheduled['scheduled_for']}.",
        "author": "System",
        "source": "call_agent",
        "call_provider": "plivo",
        "direction": "outbound",
        "outcome": "scheduled",
        "summary": "AI qualification call scheduled",
    })
    note.update({"call_key": f"qualification_scheduled:{lead_id}:{scheduled['scheduled_for']}", "status": "scheduled", "call_status": "scheduled"})
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": ObjectId(lead_id)},
        {"$set": {"qualification_call": scheduled, "updated_at": now}, "$push": {"lead_notes": note}},
    )
    settings = await ensure_crm_settings(db, ws_id)
    return {"status": "scheduled", "scheduled_for": scheduled["scheduled_for"], "lead": decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings)}


async def cancel_scheduled_qualification_call(db, ws_id, lead_id, cancelled_by="admin"):
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    qualification = lead.get("qualification_call") or {}
    if qualification.get("status") != "scheduled":
        raise HTTPException(status_code=400, detail="Only scheduled qualification calls can be cancelled")
    now = now_iso()
    qualification.update({"status": "cancelled", "cancelled_at": now, "cancelled_by": str(cancelled_by or "admin"), "updated_at": now})
    note = normalize_lead_note({
        "body": "Scheduled AI qualification call cancelled by admin.",
        "author": "System",
        "source": "call_agent",
        "call_provider": "plivo",
        "direction": "outbound",
        "outcome": "cancelled",
        "summary": "Scheduled call cancelled",
    })
    note.update({"call_key": f"qualification_cancelled:{lead_id}:{now}", "status": "cancelled", "call_status": "cancelled"})
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": ObjectId(lead_id)},
        {"$set": {"qualification_call": qualification, "updated_at": now}, "$push": {"lead_notes": note}},
    )
    settings = await ensure_crm_settings(db, ws_id)
    return {"ok": True, "status": "cancelled", "lead": decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings)}


def qualification_payload(base, ws_id, lead_id, lead, lead_phone):
    values = lead.get("field_values") or {}
    communication = lead.get("communication_summary") or {}
    notes = lead.get("lead_notes") or []
    previous_notes = [
        {
            "body": _clean_text(note.get("body"), 700),
            "source": note.get("source", "internal"),
            "summary": _clean_text(note.get("summary"), 700),
            "outcome": note.get("outcome", ""),
            "created_at": note.get("created_at", ""),
        }
        for note in notes[-20:]
    ]
    urls = callback_urls(base, ws_id, lead_id)
    full_name = values.get("full_name") or lead.get("full_name") or ""
    source = values.get("source") or lead.get("source") or ""
    email = values.get("email") or lead.get("email") or ""
    callbacks = {
        "status_url": urls["outbound_status"],
        "recording_url": urls["recording"],
        "result_url": urls["qualification_result"],
    }
    return {
        "workspace_id": str(ws_id),
        "lead_id": str(lead_id),
        "to_number": lead_phone,
        "phone_number": lead_phone,
        "lead_phone": lead_phone,
        "to": lead_phone,
        "from_number": normalize_phone(os.environ.get("PLIVO_FROM_NUMBER", "")),
        "customer_name": full_name,
        "contact_name": full_name,
        "lead_source": source,
        "email": email,
        "lead": {
            "id": str(lead_id),
            "phone": lead_phone,
            "full_name": full_name,
            "email": email,
            "source": source,
            "status": lead.get("status") or "",
            "field_values": values,
            "qualification_call": lead.get("qualification_call") or {},
            "communication_summary": communication,
            "lead_notes": previous_notes,
        },
        "communication_summary": communication,
        "previous_answers": communication.get("answers") or {},
        "collected_information": communication.get("collected_information") or [],
        "pending_discussion": communication.get("pending_discussion") or [],
        "recommended_next_steps": communication.get("recommended_next_steps") or [],
        "previous_lead_notes": previous_notes,
        "agent_instructions": (
            "Review all previous communication before speaking. Do not repeat questions already answered. "
            "Continue from pending_discussion and collect only missing qualification details."
        ),
        "callbacks": callbacks,
        "callbacks_json": json.dumps(callbacks),
    }


async def record_qualification_attempt(db, ws_id, lead_id, status, payload=None, response=None, error=""):
    now = now_iso()
    payload = payload or {}
    response = response or {}
    call_uuid = str(
        response.get("request_uuid")
        or response.get("requestUuid")
        or response.get("message_uuid")
        or response.get("call_uuid")
        or response.get("callUuid")
        or ""
    )
    note = normalize_lead_note({
        "body": f"AI qualification call {status}" + (f": {error}" if error else ""),
        "author": "Plivo",
        "source": "call_agent",
        "call_provider": "plivo",
        "call_id": call_uuid,
        "direction": "outbound",
        "outcome": status,
        "summary": error or status,
    })
    note.update({
        "call_key": f"qualification:{call_uuid or now}:{status}",
        "call_direction": "outbound",
        "call_uuid": call_uuid,
        "from_number": normalize_phone(payload.get("from_number")),
        "to_number": normalize_phone(payload.get("to_number") or payload.get("phone_number") or payload.get("to")),
        "status": status,
        "call_status": status,
        "hangup_cause": response.get("HangupCause") or response.get("hangup_cause") or "",
    })
    qualification = {
        "status": status,
        "provider": "plivo",
        "mode": "agent_direct_to_lead",
        "call_uuid": call_uuid,
        "phone": normalize_phone(payload.get("to_number") or payload.get("phone_number") or payload.get("to")),
        "last_error": error,
        "trigger_http_status": response.get("_http_status", ""),
        "trigger_response": response,
        "updated_at": now,
    }
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": ObjectId(lead_id)},
        {
            "$set": {"qualification_call": qualification, "updated_at": now},
            "$push": {"lead_notes": note},
        },
    )
    await db[COLLECTION].insert_one({
        "workspace_id": ws_id,
        "lead_id": str(lead_id),
        "call_key": note["call_key"],
        "kind": "ai_qualification",
        "status": status,
        "payload": payload,
        "response": response,
        "error": error,
        "created_at": now,
        "updated_at": now,
    })
    return qualification


def qualification_already_auto_triggered(lead):
    qualification = lead.get("qualification_call") or {}
    return qualification.get("auto_triggered") is True or qualification.get("status") in {"queued", "started", "answered", "completed"}


def qualification_status_from_plivo(payload):
    raw = str(payload.get("CallStatus") or payload.get("status") or payload.get("HangupCause") or "").strip().lower()
    if raw in {"answered", "in-progress", "in_progress"}:
        return "answered"
    if raw in {"completed", "hangup"}:
        return "completed"
    if raw in {"busy", "user_busy"}:
        return "busy"
    if raw in {"no-answer", "no_answer", "timeout"}:
        return "no_answer"
    if raw in {"failed", "rejected", "cancelled", "canceled", "unreachable", "invalid_number"}:
        return "failed"
    return raw or "updated"


async def sync_qualification_status_from_payload(db, ws_id, lead_id, payload):
    status = qualification_status_from_plivo(payload)
    call_uuid = str(payload.get("CallUUID") or payload.get("CallUuid") or payload.get("call_uuid") or "")
    hangup_cause = str(payload.get("HangupCause") or payload.get("HangupCauseCode") or "").strip()
    disconnection_reason = normalize_disconnection_reason(payload)
    if disconnection_reason in JUNK_DISCONNECTION_REASONS:
        await mark_lead_junk(db, ws_id, lead_id, disconnection_reason, payload)
        return "failed"
    update = {
        "qualification_call.status": status,
        "qualification_call.provider": "plivo",
        "qualification_call.mode": "agent_direct_to_lead",
        "qualification_call.updated_at": now_iso(),
        "qualification_call.hangup_cause": hangup_cause,
        "qualification_call.disconnection_reason": disconnection_reason,
        "updated_at": now_iso(),
    }
    if call_uuid:
        update["qualification_call.call_uuid"] = call_uuid
    if status in {"failed", "busy", "no_answer"} and hangup_cause:
        update["qualification_call.last_error"] = hangup_cause
    await db.crm_leads.update_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}, {"$set": update})
    return status


def qualification_result_status(payload):
    raw = raw_qualification_result_value(payload)
    if raw in {"qualified", "qualification_completed", "completed", "success", "interested"}:
        return "completed"
    if raw in JUNK_RESULT_VALUES or raw in {"rejected", "cancelled", "canceled", "disconnected", "unreachable"}:
        return "failed"
    if raw in {"busy", "no_answer", "failed"}:
        return raw
    return raw or "completed"


def qualification_result_summary(payload):
    value = first_nested_value(payload, SUMMARY_KEYS)
    if value:
        return _clean_text(value, 2000)
    answers = parse_jsonish_dict(payload.get("answers")) or parse_jsonish_dict(payload.get("qualification_answers")) or payload.get("answers") or payload.get("qualification_answers")
    if isinstance(answers, dict) and answers:
        return "; ".join(f"{key}: {value}" for key, value in answers.items())[:2000]
    keys = ", ".join(sorted(str(key) for key in payload.keys())[:12])
    return f"AI qualification result received, but no summary was included in the callback{f' (fields: {keys})' if keys else ''}."


def _clean_text(value, limit=500):
    return " ".join(str(value or "").split())[:limit]


def normalized_text_list(value):
    if value is None:
        return []
    parsed_list = parse_jsonish_list(value)
    if parsed_list:
        items = parsed_list
    elif isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = [f"{key}: {val}" for key, val in value.items() if str(val or "").strip()]
    else:
        items = [part.strip() for part in str(value).replace("\r", "\n").split("\n")]
    cleaned = []
    seen = set()
    for item in items:
        text = _clean_text(item)
        key = text.lower()
        if text and key not in seen:
            cleaned.append(text)
            seen.add(key)
    return cleaned[:25]


def normalized_answers(payload):
    answers = (
        parse_jsonish_dict(payload.get("answers"))
        or parse_jsonish_dict(payload.get("qualification_answers"))
        or payload.get("answers")
        or payload.get("qualification_answers")
        or {}
    )
    if not isinstance(answers, dict):
        return {}
    clean = {}
    for key, value in answers.items():
        if value is None:
            continue
        text = _clean_text(value, 1000)
        if text:
            clean[str(key).strip()] = text
    return clean


def merge_text_lists(*lists):
    merged = []
    seen = set()
    for items in lists:
        for item in normalized_text_list(items):
            key = item.lower()
            if key not in seen:
                merged.append(item)
                seen.add(key)
    return merged[:50]


def communication_summary_from_result(lead, payload, status, summary, recording_url):
    previous = lead.get("communication_summary") or {}
    answers = normalized_answers(payload)
    collected = normalized_text_list(
        payload.get("collected_information")
        or payload.get("collected_info")
        or payload.get("important_information")
    )
    if not collected:
        collected = normalized_text_list(answers)
    objections = normalized_text_list(payload.get("objections") or payload.get("key_objections"))
    pending = normalized_text_list(payload.get("pending_discussion") or payload.get("missing_information") or payload.get("open_questions"))
    next_steps = normalized_text_list(payload.get("recommended_next_steps") or payload.get("next_steps") or payload.get("strategy"))
    score = normalize_qualification_score(payload)
    category = normalize_qualification_category(payload, score)
    disconnection_reason = normalize_disconnection_reason(payload)
    return {
        "latest_summary": summary,
        "last_call_status": status,
        "last_recording_url": recording_url,
        "last_call_uuid": str(payload.get("call_uuid") or payload.get("CallUUID") or ""),
        "last_duration": str(payload.get("duration") or payload.get("Duration") or payload.get("RecordingDuration") or ""),
        "qualification_score": score,
        "qualification_category": category,
        "disconnection_reason": disconnection_reason,
        "total_call_count": int(previous.get("total_call_count") or 0) + 1,
        "collected_information": merge_text_lists(previous.get("collected_information"), collected),
        "objections": merge_text_lists(previous.get("objections"), objections),
        "pending_discussion": pending or normalized_text_list(previous.get("pending_discussion")),
        "recommended_next_steps": next_steps or normalized_text_list(previous.get("recommended_next_steps")),
        "answers": {**(previous.get("answers") or {}), **answers},
        "updated_at": now_iso(),
    }


def require_agent_callback_token(request: Request):
    expected = os.environ.get("PLIVO_AGENT_CALLBACK_TOKEN", "").strip()
    if not expected:
        return
    auth = request.headers.get("authorization", "")
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    supplied = bearer or request.headers.get("x-arevei-webhook-token", "").strip() or request.query_params.get("token", "").strip()
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Invalid Plivo AI qualification callback token")


async def save_qualification_result(db, ws_id, lead_id, payload):
    payload = unwrap_qualification_payload(payload)
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    status = qualification_result_status(payload)
    summary = qualification_result_summary(payload)
    call_uuid = str(payload.get("call_uuid") or payload.get("CallUUID") or payload.get("request_uuid") or "")
    recording_url = str(
        payload.get("recording_url")
        or payload.get("recordingUrl")
        or payload.get("recording")
        or payload.get("RecordUrl")
        or payload.get("RecordingUrl")
        or ""
    ).strip()
    answers = normalized_answers(payload)
    collected = normalized_text_list(payload.get("collected_information") or payload.get("collected_info") or payload.get("important_information"))
    objections = normalized_text_list(payload.get("objections") or payload.get("key_objections"))
    pending = normalized_text_list(payload.get("pending_discussion") or payload.get("missing_information") or payload.get("open_questions"))
    next_steps = normalized_text_list(payload.get("recommended_next_steps") or payload.get("next_steps") or payload.get("strategy"))
    score = normalize_qualification_score(payload)
    category = normalize_qualification_category(payload, score)
    disconnection_reason = normalize_disconnection_reason(payload)
    now = now_iso()
    if category == "junk" or is_mandatory_junk_result(payload):
        status = "failed"
        category = "junk"
        score = 0 if score is None else score
        disconnection_reason = disconnection_reason or raw_qualification_result_value(payload) or "junk"
        payload = {**payload, "qualification_score": score, "qualification_category": category, "disconnection_reason": disconnection_reason}
    communication_summary = communication_summary_from_result(lead, payload, status, summary, recording_url)
    qualification = {
        **(lead.get("qualification_call") or {}),
        "status": status,
        "provider": "plivo",
        "mode": "agent_direct_to_lead",
        "call_uuid": call_uuid or (lead.get("qualification_call") or {}).get("call_uuid", ""),
        "phone": lead_phone_from_doc(lead),
        "result": payload,
        "summary": summary,
        "transcript": payload.get("transcript") or "",
        "recording_url": recording_url,
        "duration": str(payload.get("duration") or payload.get("Duration") or payload.get("RecordingDuration") or ""),
        "qualification_score": score,
        "qualification_category": category,
        "disconnection_reason": disconnection_reason,
        "answers": answers,
        "collected_information": collected,
        "objections": objections,
        "pending_discussion": pending,
        "recommended_next_steps": next_steps,
        "last_error": "" if status == "completed" else summary,
        "updated_at": now,
    }
    note = normalize_lead_note({
        "body": f"AI qualification result: {summary}",
        "author": "Plivo",
        "source": "call_agent",
        "call_provider": "plivo",
        "call_id": qualification.get("call_uuid", ""),
        "direction": "outbound",
        "outcome": status,
        "summary": summary,
        "transcript": payload.get("transcript") or "",
    })
    note.update({
        "call_key": f"qualification_result:{qualification.get('call_uuid') or now}:{status}",
        "call_direction": "outbound",
        "call_uuid": qualification.get("call_uuid", ""),
        "to_number": qualification.get("phone", ""),
        "status": status,
        "call_status": status,
        "recording_url": recording_url,
        "duration": qualification.get("duration", ""),
        "qualification_score": score,
        "qualification_category": category,
        "disconnection_reason": disconnection_reason,
        "answers": answers,
        "collected_information": collected,
        "objections": objections,
        "pending_discussion": pending,
        "recommended_next_steps": next_steps,
    })
    set_updates = {"qualification_call": qualification, "communication_summary": communication_summary, "updated_at": now}
    if category == "junk":
        set_updates["status"] = "lost"
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": ObjectId(lead_id)},
        {
            "$set": set_updates,
            "$push": {"lead_notes": note},
        },
    )
    await db[COLLECTION].insert_one({
        "workspace_id": ws_id,
        "lead_id": str(lead_id),
        "call_key": note["call_key"],
        "kind": "ai_qualification_result",
        "status": status,
        "payload": payload,
        "created_at": now,
        "updated_at": now,
    })
    settings = await ensure_crm_settings(db, ws_id)
    return {
        "ok": True,
        "status": status,
        "lead": decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings),
    }


async def start_qualification_call(db, ws_id, lead_id, request: Request, auto=False, raise_on_error=True):
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if is_junk_lead(lead):
        message = "Lead is marked junk and cannot be called until an admin changes its qualification status"
        if raise_on_error:
            raise HTTPException(status_code=400, detail=message)
        settings = await ensure_crm_settings(db, ws_id)
        return {"status": "skipped", "reason": message, "lead": decorate_lead(lead, settings)}
    if auto and qualification_already_auto_triggered(lead):
        settings = await ensure_crm_settings(db, ws_id)
        return {"status": "skipped", "reason": "qualification call already triggered", "lead": decorate_lead(lead, settings)}
    lead_phone = lead_phone_from_doc(lead)
    if not lead_phone:
        message = "Lead phone number is required before starting AI qualification call"
        if raise_on_error:
            raise HTTPException(status_code=400, detail=message)
        await record_qualification_attempt(db, ws_id, lead_id, "failed", error=message)
        settings = await ensure_crm_settings(db, ws_id)
        return {"status": "failed", "error": message, "lead": decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings)}
    try:
        cfg = plivo_agent_config()
    except HTTPException as exc:
        if raise_on_error:
            raise
        await record_qualification_attempt(db, ws_id, lead_id, "failed", {"phone_number": lead_phone, "to": lead_phone}, error=str(exc.detail))
        settings = await ensure_crm_settings(db, ws_id)
        return {"status": "failed", "error": exc.detail, "lead": decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings)}
    try:
        lead_phone = require_e164_phone(lead_phone)
    except HTTPException as exc:
        await mark_lead_junk(db, ws_id, lead_id, str(exc.detail))
        if raise_on_error:
            raise
        settings = await ensure_crm_settings(db, ws_id)
        return {"status": "junk", "error": str(exc.detail), "lead": decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings)}
    payload = qualification_payload(public_base_url(request), ws_id, lead_id, lead, lead_phone)
    headers = {"Content-Type": "application/json"}
    if cfg["trigger_token"]:
        headers["Authorization"] = f"Bearer {cfg['trigger_token']}"
    logger.info(
        "starting Plivo AI qualification workspace=%s lead=%s to=%s trigger_url=%s",
        ws_id,
        lead_id,
        lead_phone,
        cfg["trigger_url"],
    )
    await record_qualification_attempt(db, ws_id, lead_id, "queued", payload)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(cfg["trigger_url"], json=payload, headers=headers)
    except httpx.HTTPError as exc:
        error = f"Plivo AI qualification trigger failed: {exc}"
        await record_qualification_attempt(db, ws_id, lead_id, "failed", payload, error=error)
        if raise_on_error:
            raise HTTPException(status_code=502, detail=error)
        settings = await ensure_crm_settings(db, ws_id)
        return {"status": "failed", "error": error, "lead": decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings)}
    response_data = {}
    try:
        response_data = response.json()
    except Exception:
        response_data = {"text": response.text}
    response_data["_http_status"] = response.status_code
    if response.status_code >= 400:
        error = plivo_error_detail(response)
        await record_qualification_attempt(db, ws_id, lead_id, "failed", payload, response_data, error)
        if raise_on_error:
            raise HTTPException(status_code=502, detail=error)
        settings = await ensure_crm_settings(db, ws_id)
        return {"status": "failed", "error": error, "lead": decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings)}
    qualification = await record_qualification_attempt(db, ws_id, lead_id, "started", payload, response_data)
    if auto:
        qualification["auto_triggered"] = True
        await db.crm_leads.update_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}, {"$set": {"qualification_call": qualification}})
    settings = await ensure_crm_settings(db, ws_id)
    return {
        "status": "started",
        "provider": "plivo",
        "mode": "agent_direct_to_lead",
        "call_uuid": qualification.get("call_uuid", ""),
        "lead_phone": lead_phone,
        "lead": decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings),
    }


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
    if is_junk_lead(lead):
        raise HTTPException(status_code=400, detail="Lead is marked junk and cannot be called until an admin changes its qualification status")
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
    logger.info(
        "starting Plivo outbound call workspace=%s lead=%s from=%s staff_to=%s bridge_to=%s answer_url=%s status_url=%s",
        ws_id,
        lead_id,
        cfg["from_number"],
        cfg["staff_number"],
        lead_phone,
        urls["outbound_answer"],
        urls["outbound_status"],
    )
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"https://api.plivo.com/v1/Account/{cfg['auth_id']}/Call/",
            data=payload,
            auth=(cfg["auth_id"], cfg["auth_token"]),
        )
    if response.status_code >= 400:
        detail = plivo_error_detail(response)
        logger.warning("Plivo outbound call failed workspace=%s lead=%s detail=%s", ws_id, lead_id, detail)
        raise HTTPException(status_code=502, detail=detail)
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
        "dial_sequence": "staff_first_then_lead",
        "staff_number": cfg["staff_number"],
        "lead_phone": lead_phone,
        "lead": updated or decorate_lead(lead, settings),
    }
