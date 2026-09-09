import base64
import hashlib
import hmac
import html
import json
import logging
import os
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

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
AGENT_CONFIGS_COLLECTION = "plivo_agent_configs"
CALL_SESSIONS_COLLECTION = "plivo_call_sessions"
CALL_EVENTS_COLLECTION = "plivo_call_events"
WORKFLOW_CONFIGS_COLLECTION = "plivo_workflow_configs"
logger = logging.getLogger("plivo_calls")
QUALIFICATION_CATEGORIES = {"hot", "warm", "cold", "junk"}
JUNK_DISCONNECTION_REASONS = {"invalid_number", "number_unreachable", "unreachable", "wrong_contact", "fake_lead", "do_not_call", "not_interested"}
JUNK_RESULT_VALUES = {"declined", "not_interested", "do_not_call", "wrong_contact", "invalid_number", "number_unreachable", "fake_lead", "junk"}
TERMINAL_CALL_STATUSES = {"completed", "failed", "busy", "no_answer", "rejected", "cancelled", "canceled", "hangup"}
ACTIVE_CALL_SESSION_STATUSES = {"queued", "started", "accepted", "answered", "reconcile_required"}
PLIVO_AGENT_AUTH_TYPES = {"none", "bearer", "basic"}
DEFAULT_AGENT_INPUT_MAPPINGS = {
    "workspace_id": "workspace_id",
    "lead_id": "lead_id",
    "session_id": "session.id",
    "call_session_id": "session.id",
    "to_number": "lead.phone",
    "phone_number": "lead.phone",
    "to": "lead.phone",
    "from_number": "agent.from_number",
    "customer_name": "lead.full_name",
    "contact_name": "lead.full_name",
    "email": "lead.email",
    "lead_source": "lead.source",
    "status_url": "callbacks.status_url",
    "recording_url": "callbacks.recording_url",
    "result_url": "callbacks.result_url",
}
DEFAULT_QUALIFICATION_SCHEMA_VERSION = "indian_real_estate_v1"
DEFAULT_SCORING_CONFIG = {
    "version": "indian_real_estate_v1_score_v1",
    "thresholds": {"hot": 80, "warm": 50, "cold": 20},
    "weights": {
        "budget_known": 15,
        "location_known": 15,
        "property_type_known": 10,
        "purpose_known": 5,
        "timeline_under_90_days": 20,
        "high_intent": 20,
        "site_visit_requested": 15,
    },
}
DEFAULT_CALLING_WORKFLOW_CONFIG = {
    "enabled": True,
    "lead_created_trigger_enabled": True,
    "selected_agent_config_id": "",
    "qualification_config_id": "indian_real_estate_v1",
    "timezone": "Asia/Kolkata",
    "calling_window": {"start": "09:30", "end": "19:00"},
    "initial_delay_minutes": 5,
    "retry_delay_minutes": 30,
    "max_attempts": 3,
    "concurrency_limit": 1,
    "hot_followup_task": True,
    "warm_followup_task": True,
    "cold_nurture": True,
}
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


def require_e164_number(phone, label="Phone number"):
    phone = normalize_phone(phone)
    if not phone.startswith("+"):
        raise HTTPException(status_code=400, detail=f"{label} must be in E.164 format")
    digits = phone[1:]
    if not digits.isdigit() or len(digits) < 8 or len(digits) > 15:
        raise HTTPException(status_code=400, detail=f"{label} must be a valid E.164 number")
    return phone


def normalize_trigger_url(value):
    url = str(value or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Plivo agent trigger URL is required")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Plivo agent trigger URL must be an absolute http(s) URL")
    return url


def normalize_json_object(value, field_name):
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail=f"{field_name} must be valid JSON")
        if isinstance(parsed, dict):
            return parsed
    raise HTTPException(status_code=400, detail=f"{field_name} must be a JSON object")


def normalize_input_mappings(value):
    mappings = normalize_json_object(value, "input_variable_mappings") if value not in (None, "") else deepcopy(DEFAULT_AGENT_INPUT_MAPPINGS)
    clean = {}
    for key, source in mappings.items():
        target = str(key or "").strip()
        if not target:
            continue
        clean[target] = deepcopy(source)
    return clean or deepcopy(DEFAULT_AGENT_INPUT_MAPPINGS)


def agent_id(agent_config):
    raw = (agent_config or {}).get("_id") or (agent_config or {}).get("id") or ""
    return str(raw) if raw else ""


def plivo_basic_credentials_from_env():
    username = os.environ.get("PLIVO_AUTH_ID", "").strip()
    password = os.environ.get("PLIVO_AUTH_TOKEN", "").strip()
    return username, password


def agent_credentials_configured(agent_config):
    agent_config = agent_config or {}
    auth_type = str(agent_config.get("auth_type") or "basic").strip().lower()
    credentials = agent_config.get("credentials") or {}
    if auth_type == "none":
        return True
    if auth_type == "bearer":
        return bool(str(credentials.get("bearer_token") or credentials.get("trigger_token") or "").strip())
    if auth_type == "basic":
        username = str(credentials.get("username") or "").strip()
        password = str(credentials.get("password") or "").strip()
        if username and password:
            return True
        env_username, env_password = plivo_basic_credentials_from_env()
        return bool(env_username and env_password)
    return False


def agent_readiness(agent_config):
    agent_config = agent_config or {}
    missing = []
    if not str(agent_config.get("display_name") or "").strip():
        missing.append("display_name")
    if not str(agent_config.get("trigger_url") or "").strip():
        missing.append("trigger_url")
    if not str(agent_config.get("from_number") or "").strip():
        missing.append("from_number")
    if str(agent_config.get("auth_type") or "basic").strip().lower() not in PLIVO_AGENT_AUTH_TYPES:
        missing.append("auth_type")
    if not agent_credentials_configured(agent_config):
        missing.append("credentials")
    warnings = []
    if str(agent_config.get("trigger_url") or "").strip().lower().startswith("http://"):
        warnings.append("trigger_url is not HTTPS")
    return {
        "ready": not missing and bool(agent_config.get("enabled", True)),
        "missing": missing,
        "warnings": warnings,
    }


def sanitize_agent_config(agent_config):
    if not agent_config:
        return None
    config_id = agent_id(agent_config)
    out = deepcopy(agent_config)
    out.pop("_id", None)
    out.pop("credentials", None)
    out["id"] = config_id
    out["credential_ref"] = agent_config.get("credential_ref") or (f"plivo_agent_config:{config_id}:trigger_auth" if config_id else "")
    out["credential_configured"] = agent_credentials_configured(agent_config)
    out["readiness"] = agent_readiness(agent_config)
    return out


def agent_config_snapshot(agent_config):
    snapshot = sanitize_agent_config(agent_config) or {}
    snapshot.pop("readiness", None)
    return snapshot


def normalize_agent_config(body, existing=None):
    body = body or {}
    existing = existing or {}
    display_name = str(body.get("display_name", existing.get("display_name") or "") or "").strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="Display name is required")
    auth_type = str(body.get("auth_type", existing.get("auth_type") or "basic") or "basic").strip().lower()
    if auth_type not in PLIVO_AGENT_AUTH_TYPES:
        raise HTTPException(status_code=400, detail="auth_type must be one of none, bearer, or basic")
    trigger_url = normalize_trigger_url(body.get("trigger_url", existing.get("trigger_url") or ""))
    from_number = require_e164_number(body.get("from_number", existing.get("from_number") or ""), "Authorized calling number")
    credentials = deepcopy(existing.get("credentials") or {})
    if body.get("clear_credentials") or auth_type == "none":
        credentials = {}
    elif auth_type == "bearer":
        token = str(body.get("bearer_token") or body.get("trigger_token") or body.get("credential_value") or "").strip()
        if token:
            credentials = {"bearer_token": token}
        elif existing.get("auth_type") != "bearer":
            credentials = {}
    elif auth_type == "basic":
        username = str(body.get("auth_username", credentials.get("username") or "") or "").strip()
        password = str(body.get("auth_password") or credentials.get("password") or "").strip()
        credentials = {"username": username, "password": password} if username or password else {}
    enabled = bool(body.get("enabled", existing.get("enabled", True)))
    config = {
        **deepcopy(existing),
        "provider": "plivo",
        "display_name": display_name,
        "flow_id": str(body.get("flow_id", existing.get("flow_id") or "") or "").strip(),
        "provider_agent_id": str(body.get("provider_agent_id", existing.get("provider_agent_id") or body.get("flow_id", existing.get("flow_id") or "")) or "").strip(),
        "trigger_url": trigger_url,
        "auth_type": auth_type,
        "credentials": credentials,
        "credential_ref": existing.get("credential_ref") or "",
        "from_number": from_number,
        "authorized_calling_number": from_number,
        "input_variable_mappings": normalize_input_mappings(body.get("input_variable_mappings", existing.get("input_variable_mappings") or None)),
        "extra_payload": normalize_json_object(body.get("extra_payload", existing.get("extra_payload") or {}), "extra_payload"),
        "qualification_config_id": str(body.get("qualification_config_id", existing.get("qualification_config_id") or "indian_real_estate_v1") or "").strip(),
        "enabled": enabled,
        "is_default": bool(body.get("is_default", existing.get("is_default", False))) and enabled,
        "updated_at": now_iso(),
        "created_at": existing.get("created_at") or now_iso(),
    }
    if enabled and not agent_credentials_configured(config):
        raise HTTPException(status_code=400, detail="Trigger credentials are required before enabling this Plivo agent")
    return config


def legacy_agent_config_from_env():
    trigger_url = os.environ.get("PLIVO_AGENT_TRIGGER_URL", "").strip()
    from_number = normalize_phone(os.environ.get("PLIVO_FROM_NUMBER", ""))
    if not trigger_url or not from_number:
        return None
    token = os.environ.get("PLIVO_AGENT_TRIGGER_TOKEN", "").strip()
    auth_id, auth_token = plivo_basic_credentials_from_env()
    flow_id = ""
    parts = [part for part in trigger_url.rstrip("/").split("/") if part]
    if "flow" in parts:
        idx = parts.index("flow")
        if idx + 1 < len(parts):
            flow_id = parts[idx + 1]
    return {
        "_id": "environment",
        "id": "environment",
        "workspace_id": "*",
        "provider": "plivo",
        "display_name": "Environment Plivo agent",
        "flow_id": flow_id,
        "provider_agent_id": flow_id,
        "trigger_url": trigger_url,
        "auth_type": "bearer" if token else "basic" if auth_id and auth_token else "none",
        "credentials": {"bearer_token": token} if token else {},
        "credential_ref": "environment:PLIVO_AGENT_TRIGGER_TOKEN",
        "from_number": from_number,
        "authorized_calling_number": from_number,
        "input_variable_mappings": deepcopy(DEFAULT_AGENT_INPUT_MAPPINGS),
        "extra_payload": {},
        "qualification_config_id": "indian_real_estate_v1",
        "enabled": True,
        "is_default": True,
        "legacy_environment": True,
    }


async def resolve_plivo_agent_config(db, ws_id, agent_config_id=None):
    config_id = str(agent_config_id or "").strip()
    if config_id == "environment":
        legacy = legacy_agent_config_from_env()
        if legacy:
            return legacy
        raise HTTPException(status_code=400, detail="Environment Plivo agent is not configured")
    if config_id:
        try:
            oid = ObjectId(config_id)
        except Exception:
            raise HTTPException(status_code=404, detail="Plivo agent configuration not found")
        agent = await db[AGENT_CONFIGS_COLLECTION].find_one({"workspace_id": ws_id, "_id": oid})
        if not agent:
            raise HTTPException(status_code=404, detail="Plivo agent configuration not found")
    else:
        agent = await db[AGENT_CONFIGS_COLLECTION].find_one({"workspace_id": ws_id, "enabled": True, "is_default": True})
        if not agent:
            agent = await db[AGENT_CONFIGS_COLLECTION].find_one({"workspace_id": ws_id, "enabled": True})
    if agent:
        if not agent.get("enabled", True):
            raise HTTPException(status_code=400, detail="Selected Plivo agent is disabled")
        readiness = agent_readiness(agent)
        if not readiness["ready"]:
            raise HTTPException(status_code=400, detail=f"Selected Plivo agent is not ready: missing {', '.join(readiness['missing'])}")
        return agent
    legacy = legacy_agent_config_from_env()
    if legacy:
        return legacy
    raise HTTPException(status_code=400, detail="No enabled Plivo AI agent is configured for this workspace")


def _path_value(source, data):
    current = data
    for part in str(source or "").split("."):
        if part == "":
            continue
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def resolve_mapping_value(source, context):
    if isinstance(source, str):
        if source.startswith("literal:"):
            return source[len("literal:"):]
        value = _path_value(source, context)
        if value is not None:
            return deepcopy(value)
        return source
    if isinstance(source, dict):
        return {str(key): resolve_mapping_value(value, context) for key, value in source.items()}
    if isinstance(source, list):
        return [resolve_mapping_value(item, context) for item in source]
    return deepcopy(source)


def build_agent_trigger_payload(base_payload, agent_config, session_id):
    agent = {
        "id": agent_id(agent_config),
        "display_name": agent_config.get("display_name") or "",
        "flow_id": agent_config.get("flow_id") or "",
        "from_number": agent_config.get("from_number") or "",
        "qualification_config_id": agent_config.get("qualification_config_id") or "",
    }
    context = deepcopy(base_payload or {})
    context["agent"] = agent
    context["session"] = {"id": str(session_id)}
    context["session_id"] = str(session_id)
    context["call_session_id"] = str(session_id)
    mappings = agent_config.get("input_variable_mappings") or DEFAULT_AGENT_INPUT_MAPPINGS
    payload = {}
    for target, source in mappings.items():
        if source == "__omit__":
            continue
        payload[str(target)] = resolve_mapping_value(source, context)
    payload.update(deepcopy(agent_config.get("extra_payload") or {}))
    return payload


def trigger_auth_for_agent(agent_config):
    auth_type = str((agent_config or {}).get("auth_type") or "basic").strip().lower()
    credentials = (agent_config or {}).get("credentials") or {}
    headers = {"Content-Type": "application/json"}
    auth = None
    if auth_type == "bearer":
        token = str(credentials.get("bearer_token") or credentials.get("trigger_token") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "basic":
        username = str(credentials.get("username") or "").strip()
        password = str(credentials.get("password") or "").strip()
        if not (username and password):
            username, password = plivo_basic_credentials_from_env()
        auth = (username, password)
    return headers, auth


def extract_provider_identifiers(response_data):
    response_data = response_data or {}
    keys = {
        "request_uuid": ("request_uuid", "requestUuid", "RequestUUID"),
        "call_uuid": ("call_uuid", "callUuid", "CallUUID"),
        "conversation_id": ("conversation_id", "conversationId", "conversation_uuid", "conversationUuid"),
        "execution_id": ("execution_id", "executionId", "flow_execution_id", "flowExecutionId", "run_id", "id"),
    }
    identifiers = {}
    for target, aliases in keys.items():
        for key in aliases:
            value = response_data.get(key)
            if value not in (None, ""):
                identifiers[target] = str(value)
                break
    if "call_uuid" not in identifiers and identifiers.get("request_uuid"):
        identifiers["call_uuid"] = identifiers["request_uuid"]
    return identifiers


async def find_active_call_session(db, ws_id, lead_id):
    return await db[CALL_SESSIONS_COLLECTION].find_one({
        "workspace_id": ws_id,
        "lead_id": str(lead_id),
        "status": {"$in": sorted(ACTIVE_CALL_SESSION_STATUSES)},
    })


async def create_call_session(db, ws_id, lead_id, lead_phone, agent_config, auto=False):
    now = now_iso()
    session = {
        "_id": ObjectId(),
        "workspace_id": ws_id,
        "lead_id": str(lead_id),
        "provider": "plivo",
        "provider_mode": "ai_studio_api_trigger",
        "status": "queued",
        "call_status": "queued",
        "result_status": "pending",
        "crm_sync_status": "pending",
        "auto_triggered": bool(auto),
        "agent_config_id": agent_id(agent_config),
        "agent_snapshot": agent_config_snapshot(agent_config),
        "qualification_config_id": agent_config.get("qualification_config_id") or "indian_real_estate_v1",
        "lead_phone": lead_phone,
        "provider_identifiers": {},
        "request_payload": {},
        "trigger_response": {},
        "last_error": "",
        "created_at": now,
        "updated_at": now,
    }
    await db[CALL_SESSIONS_COLLECTION].insert_one(session)
    return session


async def update_call_session(db, ws_id, session_id, patch):
    if not session_id:
        return
    try:
        oid = ObjectId(str(session_id))
    except Exception:
        return
    update = {**(patch or {}), "updated_at": now_iso()}
    await db[CALL_SESSIONS_COLLECTION].update_one({"workspace_id": ws_id, "_id": oid}, {"$set": update})


async def update_call_session_from_payload(db, ws_id, lead_id, payload, status=None):
    payload = payload or {}
    session_id = str(payload.get("session_id") or payload.get("call_session_id") or "").strip()
    call_uuid = str(payload.get("CallUUID") or payload.get("CallUuid") or payload.get("call_uuid") or "").strip()
    query = None
    if session_id:
        try:
            query = {"workspace_id": ws_id, "_id": ObjectId(session_id)}
        except Exception:
            query = None
    if query is None and call_uuid:
        query = {
            "workspace_id": ws_id,
            "lead_id": str(lead_id),
            "$or": [
                {"provider_identifiers.call_uuid": call_uuid},
                {"provider_identifiers.request_uuid": call_uuid},
            ],
        }
    if query is None:
        return
    update = {
        "updated_at": now_iso(),
        "last_callback_payload": dict(payload),
    }
    if status:
        update["status"] = status
        update["call_status"] = status
    if call_uuid:
        update["provider_identifiers.call_uuid"] = call_uuid
    await db[CALL_SESSIONS_COLLECTION].update_one(query, {"$set": update})


def stable_json(value):
    return json.dumps(value or {}, sort_keys=True, default=str, separators=(",", ":"))


def event_provider_id(payload):
    payload = payload or {}
    for key in ("event_id", "eventId", "callback_id", "callbackId", "webhook_id", "webhookId", "id"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    recording_id = payload.get("RecordingID") or payload.get("recording_id") or payload.get("recordingId")
    call_uuid = payload.get("CallUUID") or payload.get("call_uuid") or payload.get("request_uuid")
    event = payload.get("Event") or payload.get("event")
    status = payload.get("CallStatus") or payload.get("status") or payload.get("qualification_status")
    if recording_id:
        return f"recording:{recording_id}"
    if call_uuid and (event or status):
        return f"call:{call_uuid}:{event or ''}:{status or ''}"
    return ""


def event_idempotency_key(kind, ws_id, lead_id, payload):
    provider_id = event_provider_id(payload)
    if provider_id:
        return f"{kind}:{provider_id}"
    fingerprint = hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()
    return f"{kind}:fingerprint:{ws_id}:{lead_id}:{fingerprint}"


async def store_plivo_event(db, ws_id, lead_id, kind, payload):
    payload = unwrap_qualification_payload(payload) if kind == "qualification_result" else dict(payload or {})
    session_id = str(payload.get("session_id") or payload.get("call_session_id") or "").strip()
    key = event_idempotency_key(kind, ws_id, lead_id, payload)
    existing = await db[CALL_EVENTS_COLLECTION].find_one({"workspace_id": ws_id, "idempotency_key": key})
    if existing:
        return existing, True
    now = now_iso()
    event = {
        "_id": ObjectId(),
        "workspace_id": ws_id,
        "lead_id": str(lead_id or ""),
        "session_id": session_id,
        "provider": "plivo",
        "kind": kind,
        "idempotency_key": key,
        "provider_event_id": event_provider_id(payload),
        "provider_identifiers": extract_provider_identifiers(payload),
        "payload": payload,
        "processing_status": "received",
        "received_at": now,
        "created_at": now,
        "updated_at": now,
    }
    await db[CALL_EVENTS_COLLECTION].insert_one(event)
    return event, False


async def mark_plivo_event(db, ws_id, event_id, status, error=""):
    if not event_id:
        return
    update = {"processing_status": status, "updated_at": now_iso()}
    if status in {"processed", "failed"}:
        update["processed_at"] = now_iso()
    if error:
        update["error"] = _clean_text(error, 1000)
    await db[CALL_EVENTS_COLLECTION].update_one({"workspace_id": ws_id, "_id": ObjectId(str(event_id))}, {"$set": update})


REAL_ESTATE_ALIASES = {
    "budget": ("budget", "lead_budget", "property_budget", "budget_range", "max_budget", "buyer_budget"),
    "preferred_location": ("preferred_location", "location", "preferredLocation", "area", "city", "locality"),
    "property_type": ("property_type", "propertyType", "property", "configuration", "unit_type", "bhk"),
    "purchase_purpose": ("purchase_purpose", "purpose", "buying_purpose", "investment_or_end_use"),
    "purchase_timeline": ("purchase_timeline", "timeline", "buying_timeline", "purchaseTimeline", "when_to_buy"),
    "interest_intent": ("interest_intent", "intent", "interest", "lead_intent", "customer_intent"),
    "site_visit_interest": ("site_visit_interest", "site_visit", "siteVisitInterest", "wants_site_visit", "visit_interest"),
    "requested_callback_datetime": ("requested_callback_datetime", "callback_datetime", "callback_time", "preferred_callback_time"),
    "timezone": ("timezone", "time_zone", "tz"),
    "site_visit_booked": ("site_visit_booked", "site_visit_confirmed", "visit_booked", "visit_confirmed"),
}


def _boolish(value):
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"yes", "y", "true", "1", "interested", "requested", "confirmed", "booked"}:
        return True
    if text in {"no", "n", "false", "0", "not_interested", "declined", "not requested"}:
        return False
    return None


def normalize_budget_inr(value):
    text = _clean_text(value, 200)
    if not text:
        return {"original": "", "normalized_inr_min": None, "normalized_inr_max": None}
    lower = text.lower().replace(",", "")
    multiplier = 1
    if any(term in lower for term in ("crore", "cr")):
        multiplier = 10000000
    elif any(term in lower for term in ("lakh", "lac", "lakhs")):
        multiplier = 100000
    numbers = []
    for match in re.findall(r"\d+(?:\.\d+)?", lower):
        try:
            numbers.append(float(match) * multiplier)
        except ValueError:
            continue
    if not numbers:
        return {"original": text, "normalized_inr_min": None, "normalized_inr_max": None}
    values = [int(round(num)) for num in numbers]
    return {"original": text, "normalized_inr_min": min(values), "normalized_inr_max": max(values)}


def field_value(payload, answers, field):
    merged = {**(payload or {}), **(answers or {})}
    return first_nested_value(merged, REAL_ESTATE_ALIASES[field])


def timeline_under_90_days(value):
    text = str(value or "").strip().lower()
    if not text:
        return False
    if any(term in text for term in ("immediate", "asap", "now", "this week", "this month", "ready")):
        return True
    numbers = [int(float(n)) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if not numbers:
        return False
    max_num = max(numbers)
    if any(term in text for term in ("day", "days")):
        return max_num <= 90
    if any(term in text for term in ("week", "weeks")):
        return max_num <= 13
    if any(term in text for term in ("month", "months")):
        return max_num <= 3
    return False


def high_intent(value):
    text = str(value or "").strip().lower()
    if not text:
        return False
    return any(term in text for term in ("high", "strong", "very interested", "serious", "ready", "urgent", "site visit", "visit"))


def structured_qualification_from_payload(payload):
    payload = unwrap_qualification_payload(payload)
    answers = normalized_answers(payload)
    budget_raw = field_value(payload, answers, "budget")
    callback_tz = field_value(payload, answers, "timezone") or payload.get("timezone") or "Asia/Kolkata"
    site_visit_raw = field_value(payload, answers, "site_visit_interest")
    site_visit_booked_raw = field_value(payload, answers, "site_visit_booked")
    disconnection_reason = normalize_disconnection_reason(payload)
    raw_result = raw_qualification_result_value(payload)
    structured = {
        "schema_version": DEFAULT_QUALIFICATION_SCHEMA_VERSION,
        "budget": normalize_budget_inr(budget_raw),
        "preferred_location": _clean_text(field_value(payload, answers, "preferred_location"), 300) or None,
        "property_type": _clean_text(field_value(payload, answers, "property_type"), 200) or None,
        "purchase_purpose": _clean_text(field_value(payload, answers, "purchase_purpose"), 200) or None,
        "purchase_timeline": _clean_text(field_value(payload, answers, "purchase_timeline"), 200) or None,
        "interest_intent": _clean_text(field_value(payload, answers, "interest_intent"), 200) or None,
        "site_visit": {
            "requested": bool(_boolish(site_visit_raw)),
            "booked": bool(_boolish(site_visit_booked_raw)),
            "status": "booked" if _boolish(site_visit_booked_raw) else "requested" if _boolish(site_visit_raw) else "not_requested",
        },
        "requested_callback": {
            "datetime": _clean_text(field_value(payload, answers, "requested_callback_datetime"), 200) or None,
            "timezone": _clean_text(callback_tz, 80) or "Asia/Kolkata",
        },
        "outcomes": {
            "wrong_number": raw_result == "wrong_contact" or disconnection_reason == "wrong_contact",
            "not_interested": raw_result == "not_interested" or disconnection_reason == "not_interested",
            "do_not_call": raw_result == "do_not_call" or disconnection_reason == "do_not_call",
            "no_answer": raw_result == "no_answer" or qualification_status_from_plivo(payload) == "no_answer",
            "busy": raw_result == "busy" or qualification_status_from_plivo(payload) == "busy",
        },
        "additional_answers": answers,
        "evidence": {
            "summary": qualification_result_summary(payload),
            "transcript": _clean_text(payload.get("transcript") or payload.get("Transcription") or "", 5000),
        },
    }
    return structured


def score_structured_qualification(structured, scoring_config=None):
    scoring_config = scoring_config or DEFAULT_SCORING_CONFIG
    weights = scoring_config.get("weights") or {}
    outcomes = structured.get("outcomes") or {}
    if outcomes.get("wrong_number") or outcomes.get("not_interested") or outcomes.get("do_not_call"):
        return {
            "score": 0,
            "category": "junk",
            "qualification_processing_status": "processed",
            "score_version": scoring_config.get("version"),
            "breakdown": [{"rule": "mandatory_junk_outcome", "points": 0, "matched": True}],
        }
    if outcomes.get("no_answer") or outcomes.get("busy"):
        return {
            "score": None,
            "category": "insufficient_data",
            "qualification_processing_status": "no_answer" if outcomes.get("no_answer") else "busy",
            "score_version": scoring_config.get("version"),
            "breakdown": [],
        }
    checks = [
        ("budget_known", bool((structured.get("budget") or {}).get("original"))),
        ("location_known", bool(structured.get("preferred_location"))),
        ("property_type_known", bool(structured.get("property_type"))),
        ("purpose_known", bool(structured.get("purchase_purpose"))),
        ("timeline_under_90_days", timeline_under_90_days(structured.get("purchase_timeline"))),
        ("high_intent", high_intent(structured.get("interest_intent"))),
        ("site_visit_requested", bool((structured.get("site_visit") or {}).get("requested"))),
    ]
    score = 0
    breakdown = []
    for rule, matched in checks:
        points = int(weights.get(rule) or 0) if matched else 0
        score += points
        breakdown.append({"rule": rule, "points": points, "matched": bool(matched)})
    known_count = sum(1 for _, matched in checks[:4] if matched)
    if known_count == 0 and not high_intent(structured.get("interest_intent")):
        return {
            "score": None,
            "category": "insufficient_data",
            "qualification_processing_status": "insufficient_data",
            "score_version": scoring_config.get("version"),
            "breakdown": breakdown,
        }
    thresholds = scoring_config.get("thresholds") or {}
    if score >= int(thresholds.get("hot", 80)):
        category = "hot"
    elif score >= int(thresholds.get("warm", 50)):
        category = "warm"
    elif score >= int(thresholds.get("cold", 20)):
        category = "cold"
    else:
        category = "cold"
    return {
        "score": int(max(0, min(100, score))),
        "category": category,
        "qualification_processing_status": "processed",
        "score_version": scoring_config.get("version"),
        "breakdown": breakdown,
    }


def normalized_agent_actions(payload):
    return normalized_text_list(
        payload.get("agent_actions")
        or payload.get("agent_action")
        or payload.get("observed_agent_actions")
        or payload.get("actions")
    )


def recommended_next_action(structured, score_result, status):
    outcomes = structured.get("outcomes") or {}
    site_visit = structured.get("site_visit") or {}
    if outcomes.get("do_not_call"):
        return {"type": "stop_auto_calls", "priority": "high", "reason": "Lead requested do-not-call"}
    if outcomes.get("wrong_number"):
        return {"type": "verify_phone", "priority": "high", "reason": "Wrong number outcome"}
    if outcomes.get("not_interested"):
        return {"type": "nurture_or_close", "priority": "low", "reason": "Lead is not interested"}
    if status in {"busy", "no_answer"} or score_result.get("qualification_processing_status") in {"busy", "no_answer"}:
        return {"type": "retry_call", "priority": "medium", "reason": "No complete conversation yet"}
    if score_result.get("category") == "insufficient_data":
        return {"type": "review_call", "priority": "medium", "reason": "Insufficient qualification data"}
    if site_visit.get("booked"):
        return {"type": "confirm_site_visit", "priority": "high", "reason": "Site visit booking confirmation received"}
    if site_visit.get("requested"):
        return {"type": "schedule_site_visit", "priority": "high", "reason": "Lead requested a site visit"}
    category = score_result.get("category")
    if category == "hot":
        return {"type": "sales_follow_up", "priority": "high", "reason": "Hot lead score"}
    if category == "warm":
        return {"type": "follow_up", "priority": "medium", "reason": "Warm lead score"}
    return {"type": "nurture", "priority": "low", "reason": "Cold lead score"}


def _int_between(value, default, low, high):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


def normalize_time_text(value, fallback):
    text = str(value or fallback).strip()
    if not re.match(r"^\d{2}:\d{2}$", text):
        return fallback
    hours, minutes = [int(part) for part in text.split(":")]
    if hours > 23 or minutes > 59:
        return fallback
    return text


def normalize_workflow_config(body, existing=None):
    body = body or {}
    existing = {**deepcopy(DEFAULT_CALLING_WORKFLOW_CONFIG), **(existing or {})}
    window = {**(existing.get("calling_window") or {}), **(body.get("calling_window") or {})}
    return {
        "enabled": bool(body.get("enabled", existing.get("enabled", True))),
        "lead_created_trigger_enabled": bool(body.get("lead_created_trigger_enabled", existing.get("lead_created_trigger_enabled", True))),
        "selected_agent_config_id": str(body.get("selected_agent_config_id", existing.get("selected_agent_config_id") or "") or "").strip(),
        "qualification_config_id": str(body.get("qualification_config_id", existing.get("qualification_config_id") or "indian_real_estate_v1") or "").strip(),
        "timezone": str(body.get("timezone", existing.get("timezone") or "Asia/Kolkata") or "Asia/Kolkata").strip(),
        "calling_window": {
            "start": normalize_time_text(window.get("start"), "09:30"),
            "end": normalize_time_text(window.get("end"), "19:00"),
        },
        "initial_delay_minutes": _int_between(body.get("initial_delay_minutes", existing.get("initial_delay_minutes")), 5, 0, 1440),
        "retry_delay_minutes": _int_between(body.get("retry_delay_minutes", existing.get("retry_delay_minutes")), 30, 1, 1440),
        "max_attempts": _int_between(body.get("max_attempts", existing.get("max_attempts")), 3, 1, 10),
        "concurrency_limit": _int_between(body.get("concurrency_limit", existing.get("concurrency_limit")), 1, 1, 20),
        "hot_followup_task": bool(body.get("hot_followup_task", existing.get("hot_followup_task", True))),
        "warm_followup_task": bool(body.get("warm_followup_task", existing.get("warm_followup_task", True))),
        "cold_nurture": bool(body.get("cold_nurture", existing.get("cold_nurture", True))),
    }


async def ensure_calling_workflow_config(db, ws_id):
    doc = await db[WORKFLOW_CONFIGS_COLLECTION].find_one({"workspace_id": ws_id})
    if doc:
        normalized = normalize_workflow_config({}, doc)
        if any(doc.get(key) != value for key, value in normalized.items()):
            await db[WORKFLOW_CONFIGS_COLLECTION].update_one({"workspace_id": ws_id}, {"$set": {**normalized, "updated_at": now_iso()}})
            doc.update(normalized)
        return doc
    now = now_iso()
    doc = {
        "_id": ObjectId(),
        "workspace_id": ws_id,
        **deepcopy(DEFAULT_CALLING_WORKFLOW_CONFIG),
        "created_at": now,
        "updated_at": now,
    }
    await db[WORKFLOW_CONFIGS_COLLECTION].insert_one(doc)
    return doc


def public_workflow_config(doc):
    if not doc:
        return None
    out = {**deepcopy(DEFAULT_CALLING_WORKFLOW_CONFIG), **deepcopy(doc)}
    out.pop("_id", None)
    out["id"] = str(doc.get("_id") or "")
    return out


def _workflow_zone(config):
    try:
        return ZoneInfo(config.get("timezone") or "Asia/Kolkata")
    except Exception:
        return ZoneInfo("Asia/Kolkata")


def _time_minutes(text):
    hours, minutes = [int(part) for part in normalize_time_text(text, "09:30").split(":")]
    return hours * 60 + minutes


def within_calling_window(config, now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    local = now_utc.astimezone(_workflow_zone(config))
    start = _time_minutes((config.get("calling_window") or {}).get("start") or "09:30")
    end = _time_minutes((config.get("calling_window") or {}).get("end") or "19:00")
    current = local.hour * 60 + local.minute
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def next_calling_window_start(config, now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    zone = _workflow_zone(config)
    local = now_utc.astimezone(zone)
    start = _time_minutes((config.get("calling_window") or {}).get("start") or "09:30")
    start_hour, start_minute = divmod(start, 60)
    candidate = local.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    if within_calling_window(config, now_utc):
        return now_utc
    if local > candidate:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(timezone.utc)


async def count_active_workspace_sessions(db, ws_id):
    sessions = await db[CALL_SESSIONS_COLLECTION].find({
        "workspace_id": ws_id,
        "status": {"$in": sorted(ACTIVE_CALL_SESSION_STATUSES)},
    }).to_list(1000)
    return len(sessions)


async def count_lead_call_attempts(db, ws_id, lead_id):
    sessions = await db[CALL_SESSIONS_COLLECTION].find({"workspace_id": ws_id, "lead_id": str(lead_id)}).to_list(1000)
    return len(sessions)


async def schedule_retry_if_allowed(db, ws_id, lead_id, status):
    if status not in {"busy", "no_answer", "failed"}:
        return False
    workflow = await ensure_calling_workflow_config(db, ws_id)
    if not workflow.get("enabled", True) or not workflow.get("lead_created_trigger_enabled", True):
        return False
    attempts = await count_lead_call_attempts(db, ws_id, lead_id)
    if attempts >= int(workflow.get("max_attempts") or 3):
        return False
    scheduled_for = (datetime.now(timezone.utc) + timedelta(minutes=int(workflow.get("retry_delay_minutes") or 30))).isoformat()
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)})
    qualification = {**(lead.get("qualification_call") or {})} if lead else {}
    qualification.update({
        "status": "scheduled",
        "scheduled_for": scheduled_for,
        "retry_after_status": status,
        "auto_retry_count": int(qualification.get("auto_retry_count") or 0) + 1,
        "updated_at": now_iso(),
    })
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": ObjectId(lead_id)},
        {"$set": {"qualification_call": qualification, "updated_at": now_iso()}},
    )
    return True


async def create_followup_task_for_result(db, ws_id, lead_id, qualification):
    next_action = qualification.get("next_action") or {}
    action_type = next_action.get("type")
    if action_type not in {"sales_follow_up", "follow_up", "schedule_site_visit", "confirm_site_visit"}:
        return None
    existing = await db.tasks.find_one({
        "workspace_id": ws_id,
        "source": "plivo_qualification",
        "lead_id": str(lead_id),
        "action_type": action_type,
    })
    if existing:
        return existing
    priority = next_action.get("priority") or "medium"
    title = {
        "schedule_site_visit": "Schedule requested site visit",
        "confirm_site_visit": "Confirm booked site visit",
        "sales_follow_up": "Follow up hot qualified lead",
        "follow_up": "Follow up warm qualified lead",
    }.get(action_type, "Follow up qualified lead")
    task = {
        "_id": ObjectId(),
        "workspace_id": ws_id,
        "title": title,
        "objective": f"Lead {lead_id}: {next_action.get('reason') or 'AI qualification next action'}",
        "agent": "sales",
        "deliverable_type": "crm_follow_up",
        "success_criteria": "Sales team reviews the AI qualification and records the outcome.",
        "month_number": 1,
        "requires_approval": True,
        "scheduled_time": now_iso(),
        "status": "pending",
        "output_ref": str(lead_id),
        "output_summary": "",
        "output_payload": {"qualification_call": qualification, "priority": priority},
        "logs": [],
        "source": "plivo_qualification",
        "lead_id": str(lead_id),
        "action_type": action_type,
        "priority": priority,
        "created_at": now_iso(),
    }
    await db.tasks.insert_one(task)
    return task


async def plivo_metrics(db, ws_id):
    leads = await db.crm_leads.find({"workspace_id": ws_id}).to_list(5000)
    sessions = await db[CALL_SESSIONS_COLLECTION].find({"workspace_id": ws_id}).to_list(5000)
    metrics = {
        "leads_received": len(leads),
        "calls_attempted": len(sessions),
        "calls_answered": 0,
        "qualification_completed": 0,
        "hot": 0,
        "warm": 0,
        "cold": 0,
        "insufficient_data": 0,
        "site_visits_requested": 0,
        "site_visits_scheduled": 0,
        "site_visits_completed": 0,
        "bookings": 0,
        "lost": 0,
    }
    for session in sessions:
        if session.get("call_status") in {"answered", "completed"} or session.get("status") in {"answered", "completed"}:
            metrics["calls_answered"] += 1
    for lead in leads:
        qualification = lead.get("qualification_call") or {}
        communication = lead.get("communication_summary") or {}
        category = qualification.get("qualification_category") or communication.get("qualification_category")
        structured = qualification.get("structured_qualification") or communication.get("structured_qualification") or {}
        if qualification.get("status") == "completed":
            metrics["qualification_completed"] += 1
        if category in {"hot", "warm", "cold"}:
            metrics[category] += 1
        elif category == "insufficient_data" or qualification.get("qualification_processing_status") == "insufficient_data":
            metrics["insufficient_data"] += 1
        site_visit = structured.get("site_visit") or {}
        if site_visit.get("requested"):
            metrics["site_visits_requested"] += 1
        if site_visit.get("booked"):
            metrics["site_visits_scheduled"] += 1
        if lead.get("customer_status") == "customer" or lead.get("status") == "won":
            metrics["bookings"] += 1
        if lead.get("status") == "lost":
            metrics["lost"] += 1
    return metrics


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
        "status_url": urls.get("outbound_status", ""),
        "recording_url": urls.get("recording", ""),
        "result_url": urls.get("qualification_result", ""),
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


def qualification_payload(base, ws_id, lead_id, lead, lead_phone, agent_config=None, session_id=""):
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
    from_number = normalize_phone((agent_config or {}).get("from_number") or os.environ.get("PLIVO_FROM_NUMBER", ""))
    callbacks = {
        "status_url": urls.get("outbound_status", ""),
        "recording_url": urls.get("recording", ""),
        "result_url": urls.get("qualification_result", ""),
    }
    return {
        "workspace_id": str(ws_id),
        "lead_id": str(lead_id),
        "to_number": lead_phone,
        "phone_number": lead_phone,
        "lead_phone": lead_phone,
        "to": lead_phone,
        "from_number": from_number,
        "session_id": str(session_id or ""),
        "call_session_id": str(session_id or ""),
        "agent_config_id": agent_id(agent_config),
        "agent_display_name": (agent_config or {}).get("display_name") or "",
        "agent_flow_id": (agent_config or {}).get("flow_id") or "",
        "qualification_config_id": (agent_config or {}).get("qualification_config_id") or "indian_real_estate_v1",
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


async def record_qualification_attempt(db, ws_id, lead_id, status, payload=None, response=None, error="", agent_config=None, session_id=""):
    now = now_iso()
    payload = payload or {}
    response = response or {}
    identifiers = extract_provider_identifiers(response)
    call_uuid = identifiers.get("call_uuid") or identifiers.get("request_uuid") or ""
    agent_snapshot = agent_config_snapshot(agent_config) if agent_config else {}
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
    if agent_snapshot:
        note["agent_config_id"] = agent_snapshot.get("id") or ""
        note["agent_display_name"] = agent_snapshot.get("display_name") or ""
    if session_id:
        note["session_id"] = str(session_id)
    qualification = {
        "status": status,
        "provider": "plivo",
        "mode": "agent_direct_to_lead",
        "session_id": str(session_id or ""),
        "agent_config_id": agent_snapshot.get("id") or "",
        "agent_display_name": agent_snapshot.get("display_name") or "",
        "agent_flow_id": agent_snapshot.get("flow_id") or "",
        "qualification_config_id": agent_snapshot.get("qualification_config_id") or payload.get("qualification_config_id") or "",
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
        "session_id": str(session_id or ""),
        "agent_config_id": agent_snapshot.get("id") or "",
        "agent_snapshot": agent_snapshot,
        "payload": payload,
        "response": response,
        "provider_identifiers": identifiers,
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
        await update_call_session_from_payload(db, ws_id, lead_id, payload, "failed")
        await mark_lead_junk(db, ws_id, lead_id, disconnection_reason, payload)
        return "failed"
    await update_call_session_from_payload(db, ws_id, lead_id, payload, status)
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
    structured = structured_qualification_from_payload(payload)
    score_result = score_structured_qualification(structured)
    score = normalize_qualification_score(payload)
    if score is None:
        score = score_result.get("score")
    category = normalize_qualification_category(payload, score)
    if not category:
        category = score_result.get("category") or ""
    disconnection_reason = normalize_disconnection_reason(payload)
    now = now_iso()
    session_id = str(
        payload.get("session_id")
        or payload.get("call_session_id")
        or (lead.get("qualification_call") or {}).get("session_id")
        or ""
    )
    if category == "junk" or is_mandatory_junk_result(payload):
        status = "failed"
        category = "junk"
        score = 0 if score is None else score
        disconnection_reason = disconnection_reason or raw_qualification_result_value(payload) or "junk"
        payload = {**payload, "qualification_score": score, "qualification_category": category, "disconnection_reason": disconnection_reason}
    elif score is not None or category:
        payload = {**payload, "qualification_score": score, "qualification_category": category}
    next_action = recommended_next_action(structured, {**score_result, "score": score, "category": category}, status)
    agent_actions = normalized_agent_actions(payload)
    communication_summary = communication_summary_from_result(lead, payload, status, summary, recording_url)
    communication_summary.update({
        "structured_qualification": structured,
        "qualification_processing_status": score_result.get("qualification_processing_status") or "processed",
        "score_version": score_result.get("score_version"),
        "score_breakdown": score_result.get("breakdown") or [],
        "agent_actions": agent_actions,
        "next_action": next_action,
    })
    if category:
        communication_summary["qualification_category"] = category
    if score is not None:
        communication_summary["qualification_score"] = score
    qualification = {
        **(lead.get("qualification_call") or {}),
        "status": status,
        "provider": "plivo",
        "mode": "agent_direct_to_lead",
        "session_id": session_id,
        "call_uuid": call_uuid or (lead.get("qualification_call") or {}).get("call_uuid", ""),
        "phone": lead_phone_from_doc(lead),
        "result": payload,
        "summary": summary,
        "transcript": payload.get("transcript") or "",
        "recording_url": recording_url,
        "duration": str(payload.get("duration") or payload.get("Duration") or payload.get("RecordingDuration") or ""),
        "qualification_score": score,
        "qualification_category": category,
        "qualification_processing_status": score_result.get("qualification_processing_status") or "processed",
        "structured_qualification": structured,
        "score_version": score_result.get("score_version"),
        "score_breakdown": score_result.get("breakdown") or [],
        "disconnection_reason": disconnection_reason,
        "answers": answers,
        "collected_information": collected,
        "objections": objections,
        "pending_discussion": pending,
        "recommended_next_steps": next_steps,
        "agent_actions": agent_actions,
        "next_action": next_action,
        "result_status": "received",
        "crm_sync_status": "synced",
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
        "structured_qualification": structured,
        "qualification_processing_status": score_result.get("qualification_processing_status") or "processed",
        "score_breakdown": score_result.get("breakdown") or [],
        "agent_actions": agent_actions,
        "next_action": next_action,
    })
    if session_id:
        note["session_id"] = session_id
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
        "session_id": session_id,
        "payload": payload,
        "created_at": now,
        "updated_at": now,
    })
    if session_id:
        await update_call_session(db, ws_id, session_id, {
            "status": status,
            "result_status": "received",
            "crm_sync_status": "synced",
            "result_payload": payload,
            "summary": summary,
            "qualification_score": score,
            "qualification_category": category,
            "qualification_processing_status": score_result.get("qualification_processing_status") or "processed",
            "score_breakdown": score_result.get("breakdown") or [],
            "structured_qualification": structured,
            "next_action": next_action,
            "agent_actions": agent_actions,
            "provider_identifiers": {
                **((lead.get("qualification_call") or {}).get("provider_identifiers") or {}),
                **extract_provider_identifiers(payload),
            },
        })
    settings = await ensure_crm_settings(db, ws_id)
    return {
        "ok": True,
        "status": status,
        "lead": decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings),
    }


async def start_qualification_call(db, ws_id, lead_id, request: Request, auto=False, raise_on_error=True, agent_config_id=None):
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
    active_session = await find_active_call_session(db, ws_id, lead_id)
    qualification = lead.get("qualification_call") or {}
    if active_session or qualification.get("status") in ACTIVE_CALL_SESSION_STATUSES:
        settings = await ensure_crm_settings(db, ws_id)
        active = active_session.get("agent_snapshot") if active_session else None
        return {
            "status": "already_active",
            "reason": "An AI qualification call is already in progress for this lead",
            "session_id": str(active_session.get("_id")) if active_session else qualification.get("session_id", ""),
            "agent": active,
            "agent_display_name": (active or {}).get("display_name") or qualification.get("agent_display_name", ""),
            "lead": decorate_lead(lead, settings),
        }
    lead_phone = lead_phone_from_doc(lead)
    if not lead_phone:
        message = "Lead phone number is required before starting AI qualification call"
        if raise_on_error:
            raise HTTPException(status_code=400, detail=message)
        await record_qualification_attempt(db, ws_id, lead_id, "failed", error=message)
        settings = await ensure_crm_settings(db, ws_id)
        return {"status": "failed", "error": message, "lead": decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings)}
    try:
        agent_config = await resolve_plivo_agent_config(db, ws_id, agent_config_id)
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
    session = await create_call_session(db, ws_id, lead_id, lead_phone, agent_config, auto=auto)
    session_id = str(session["_id"])
    base_payload = qualification_payload(public_base_url(request), ws_id, lead_id, lead, lead_phone, agent_config, session_id)
    payload = build_agent_trigger_payload(base_payload, agent_config, session_id)
    headers, auth = trigger_auth_for_agent(agent_config)
    await update_call_session(db, ws_id, session_id, {
        "request_payload": payload,
        "base_payload_snapshot": base_payload,
    })
    logger.info(
        "starting Plivo AI qualification workspace=%s lead=%s session=%s agent_config=%s flow=%s to=%s",
        ws_id,
        lead_id,
        session_id,
        agent_id(agent_config),
        agent_config.get("flow_id") or "",
        lead_phone,
    )
    await record_qualification_attempt(db, ws_id, lead_id, "queued", payload, agent_config=agent_config, session_id=session_id)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(agent_config["trigger_url"], json=payload, headers=headers, auth=auth)
    except httpx.TimeoutException as exc:
        error = f"Plivo AI qualification trigger timed out after the request may have been accepted: {exc}"
        await update_call_session(db, ws_id, session_id, {"status": "reconcile_required", "call_status": "reconcile_required", "last_error": error})
        qualification = await record_qualification_attempt(db, ws_id, lead_id, "reconcile_required", payload, error=error, agent_config=agent_config, session_id=session_id)
        settings = await ensure_crm_settings(db, ws_id)
        return {
            "status": "reconcile_required",
            "provider": "plivo",
            "mode": "agent_direct_to_lead",
            "session_id": session_id,
            "call_uuid": qualification.get("call_uuid", ""),
            "lead_phone": lead_phone,
            "agent": sanitize_agent_config(agent_config),
            "agent_display_name": agent_config.get("display_name") or "",
            "error": error,
            "lead": decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings),
        }
    except httpx.HTTPError as exc:
        error = f"Plivo AI qualification trigger failed: {exc}"
        await update_call_session(db, ws_id, session_id, {"status": "failed", "call_status": "failed", "last_error": error})
        await record_qualification_attempt(db, ws_id, lead_id, "failed", payload, error=error, agent_config=agent_config, session_id=session_id)
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
        await update_call_session(db, ws_id, session_id, {
            "status": "failed",
            "call_status": "failed",
            "trigger_response": response_data,
            "last_error": error,
        })
        await record_qualification_attempt(db, ws_id, lead_id, "failed", payload, response_data, error, agent_config=agent_config, session_id=session_id)
        if raise_on_error:
            raise HTTPException(status_code=502, detail=error)
        settings = await ensure_crm_settings(db, ws_id)
        return {"status": "failed", "error": error, "lead": decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}), settings)}
    identifiers = extract_provider_identifiers(response_data)
    await update_call_session(db, ws_id, session_id, {
        "status": "started",
        "call_status": "started",
        "trigger_response": response_data,
        "provider_identifiers": identifiers,
    })
    qualification = await record_qualification_attempt(db, ws_id, lead_id, "started", payload, response_data, agent_config=agent_config, session_id=session_id)
    if auto:
        qualification["auto_triggered"] = True
        await db.crm_leads.update_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)}, {"$set": {"qualification_call": qualification}})
    settings = await ensure_crm_settings(db, ws_id)
    return {
        "status": "started",
        "provider": "plivo",
        "mode": "agent_direct_to_lead",
        "session_id": session_id,
        "call_uuid": qualification.get("call_uuid", ""),
        "lead_phone": lead_phone,
        "agent": sanitize_agent_config(agent_config),
        "agent_display_name": agent_config.get("display_name") or "",
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
