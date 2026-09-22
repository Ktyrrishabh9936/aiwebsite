"""Workspace-bound encrypted voice credentials. No customer environment fallback."""
import json
import os
import re
import secrets as secure_random
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from fastapi import HTTPException
from models import now_iso

PROVIDERS = ("plivo", "sarvam")
SECRET_FIELDS = {"auth_token", "api_key", "callback_token", "bearer_token", "password"}
SARVAM_CONFIG_ALIASES = {
    "org_id": "organization_id",
    "sarvam_workspace_id": "workspace_id",
    "from_number": "agent_phone_number",
}


def cipher():
    try:
        keys = [Fernet(k.strip().encode()) for k in os.getenv("VOICE_CREDENTIAL_KEYS", "").split(",") if k.strip()]
        if not keys:
            raise ValueError()
        return MultiFernet(keys)
    except ValueError:
        raise HTTPException(503, "Voice credential encryption is not configured") from None


def encrypt(ws_id, provider, credentials):
    return cipher().encrypt(json.dumps({"workspace_id": str(ws_id), "provider": provider, "credentials": credentials}).encode()).decode()


def decrypt(ws_id, provider, value):
    try:
        data = json.loads(cipher().decrypt(value.encode()))
        if data["workspace_id"] != str(ws_id) or data["provider"] != provider:
            raise ValueError()
        return data["credentials"]
    except (InvalidToken, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Voice credentials cannot be decrypted for this workspace") from None


def public_base():
    base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(503, "PUBLIC_BASE_URL must be the application's public HTTPS URL")
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(503, "PUBLIC_BASE_URL must be publicly reachable")
    return base


def validate_provider(provider):
    if provider not in PROVIDERS:
        raise HTTPException(422, "Unsupported voice provider")


def safe_config(provider, config):
    allowed = {"plivo": {"auth_id", "from_number", "staff_number", "trigger_url", "auth_type", "flow_id", "input_variable_mappings", "extra_payload"},
               "sarvam": {"organization_id", "workspace_id", "app_id", "app_version", "connection_id", "agent_phone_number", "payload_mode", *SARVAM_CONFIG_ALIASES}}[provider]
    if set(config) - allowed:
        raise HTTPException(422, "Unknown provider configuration fields")
    def check_fields(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if any(word in str(key).lower() for word in ("secret", "token", "password", "credential", "authorization", "api_key")):
                    raise HTTPException(422, "Store secrets in credential fields only")
                check_fields(child)
        elif isinstance(value, list):
            for child in value:
                check_fields(child)
    check_fields(config)
    result = dict(config)
    if provider == "sarvam":
        for old_key, canonical_key in SARVAM_CONFIG_ALIASES.items():
            old_value = result.pop(old_key, None)
            if old_value is not None:
                if canonical_key in result and str(result[canonical_key]) != str(old_value):
                    raise HTTPException(422, f"Conflicting {canonical_key} values")
                result.setdefault(canonical_key, old_value)
    for key in ("organization_id", "workspace_id", "app_id", "connection_id", "auth_id"):
        if result.get(key) and not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", str(result[key])):
            raise HTTPException(422, f"Invalid {key}")
    for key in ("agent_phone_number", "from_number", "staff_number"):
        if result.get(key) and not re.fullmatch(r"\+[1-9]\d{7,14}", str(result[key])):
            raise HTTPException(422, f"{key} must use E.164 format")
    if result.get("trigger_url"):
        url = urlsplit(result["trigger_url"])
        if url.scheme != "https" or url.hostname != "agentflow.plivo.com" or url.username or url.password or url.query or url.fragment:
            raise HTTPException(422, "Use an HTTPS agentflow.plivo.com trigger URL without credentials or query parameters")
    if "app_version" in result:
        try:
            result["app_version"] = int(result["app_version"])
            if result["app_version"] < 1:
                raise ValueError()
        except (TypeError, ValueError):
            raise HTTPException(422, "App version must be a positive integer") from None
    if result.get("auth_type", "basic") not in {"basic", "bearer"}:
        raise HTTPException(422, "Authentication must be basic or bearer")
    if provider == "sarvam" and result.get("payload_mode", "legacy") not in {"legacy", "lead_context_v1"}:
        raise HTTPException(422, "Sarvam agent input mode is invalid")
    return result


async def load_config(db, ws_id, provider, *, enabled=True):
    validate_provider(provider)
    doc = await db.workspace_voice_provider_configs.find_one({"workspace_id": str(ws_id), "provider": provider})
    if not doc:
        raise HTTPException(409, "Missing workspace voice provider configuration")
    if enabled and not doc.get("enabled"):
        raise HTTPException(409, "Voice provider is disabled")
    doc = dict(doc)
    doc["config"] = safe_config(provider, doc.get("config") or {})
    return doc, decrypt(ws_id, provider, doc["encrypted_credentials"])


def public_config(doc):
    result = {key: doc.get(key) for key in ("workspace_id", "provider", "enabled", "config", "status", "created_at", "updated_at", "last_verified_at", "last_callback_at", "error_code", "configured_secrets", "revision")}
    result["config"] = safe_config(doc["provider"], doc.get("config") or {})
    if doc["provider"] == "sarvam":
        configured = set(doc.get("configured_secrets") or [])
        result["callback_security_configured"] = "callback_token" in configured
        result["configured_secrets"] = sorted(configured - {"callback_token"})
    return result


async def save_config(db, ws_id, provider, enabled, config, credentials, revision=None):
    validate_provider(provider)
    config = safe_config(provider, config)
    if set(credentials) - SECRET_FIELDS:
        raise HTTPException(422, "Unknown credential fields")
    if provider == "sarvam" and "callback_token" in credentials:
        raise HTTPException(422, "Sarvam callback security is managed automatically")
    query = {"workspace_id": str(ws_id), "provider": provider}
    old = await db.workspace_voice_provider_configs.find_one(query)
    secrets = decrypt(ws_id, provider, old["encrypted_credentials"]) if old else {}
    secrets.update({k: v for k, v in credentials.items() if v})
    if provider == "sarvam" and not secrets.get("callback_token"):
        secrets["callback_token"] = secure_random.token_urlsafe(48)
    if secrets.get("callback_token") and len(secrets["callback_token"]) < 32:
        raise HTTPException(422, "Callback token must contain at least 32 characters")
    now = now_iso()
    doc = {**query, "enabled": enabled, "config": config, "encrypted_credentials": encrypt(ws_id, provider, secrets),
           "configured_secrets": sorted(k for k, v in secrets.items() if v), "status": "unverified", "error_code": None,
           "last_verified_at": None, "last_callback_at": None, "updated_at": now, "revision": (old or {}).get("revision", 0) + 1}
    if old:
        query["revision"] = revision if revision is not None else old.get("revision", 0)
        updated = await db.workspace_voice_provider_configs.update_one(query, {"$set": doc})
        if not updated.matched_count:
            raise HTTPException(409, "Configuration changed; reload before saving")
    else:
        from pymongo.errors import DuplicateKeyError
        try:
            await db.workspace_voice_provider_configs.insert_one({**doc, "created_at": now})
        except DuplicateKeyError:
            raise HTTPException(409, "Configuration changed; reload before saving") from None
    return public_config(await db.workspace_voice_provider_configs.find_one({"workspace_id": str(ws_id), "provider": provider}))


async def regenerate_sarvam_callback_secret(db, ws_id, revision=None):
    query = {"workspace_id": str(ws_id), "provider": "sarvam"}
    old = await db.workspace_voice_provider_configs.find_one(query)
    if not old:
        raise HTTPException(409, "Save the Sarvam configuration before regenerating callback security")
    credentials = decrypt(ws_id, "sarvam", old["encrypted_credentials"])
    credentials["callback_token"] = secure_random.token_urlsafe(48)
    now = now_iso()
    match = {**query, "revision": revision if revision is not None else old.get("revision", 0)}
    updated = await db.workspace_voice_provider_configs.update_one(match, {"$set": {
        "encrypted_credentials": encrypt(ws_id, "sarvam", credentials),
        "configured_secrets": sorted(k for k, value in credentials.items() if value),
        "callback_secret_rotated_at": now,
        "updated_at": now,
        "revision": old.get("revision", 0) + 1,
    }})
    if not updated.matched_count:
        raise HTTPException(409, "Configuration changed; reload before regenerating callback security")
    return public_config(await db.workspace_voice_provider_configs.find_one(query))
