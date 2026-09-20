"""Workspace settings and authenticated Sarvam qualification callbacks."""
import hashlib
import hmac
import json
import logging
import time
from typing import Literal

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from crm import db_from, require_workspace_access
from models import now_iso
from voice_config import PROVIDERS, load_config, public_base, public_config, regenerate_sarvam_callback_secret, save_config
from voice_providers import callback_proof, get_provider

router = APIRouter(tags=["voice providers"])
logger = logging.getLogger("voice")
Provider = Literal["plivo", "sarvam"]


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    config: dict = Field(default_factory=dict)
    credentials: dict[str, SecretStr] = Field(default_factory=dict)
    revision: int | None = None


class SecretRegeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int | None = None


def webhooks(ws_id, provider):
    try:
        base = public_base()
    except HTTPException:
        return {"status": "configuration_error", "message": "Configure PUBLIC_BASE_URL", "endpoints": []}
    if provider == "plivo":
        from plivo_calls import callback_urls
        urls = callback_urls(base, ws_id, "{lead_id}", include_auth=False)
        endpoints = [{"event": k, "url": v, "method": "POST"} for k, v in urls.items()]
    else:
        endpoints = [{"event": "connected, no_answer, busy, failed (includes transcript and final variables)",
                      "url": f"{base}/api/sarvam/workspaces/{ws_id}/calls/{{session_id}}/result", "method": "POST"}]
    return {"status": "configured", "endpoints": endpoints}


@router.get("/workspaces/{ws_id}/voice-providers")
async def list_configs(ws_id: str, request: Request):
    await require_workspace_access(request, ws_id)
    db = db_from(request)
    result = []
    for provider in PROVIDERS:
        doc = await db.workspace_voice_provider_configs.find_one({"workspace_id": ws_id, "provider": provider})
        result.append({**(public_config(doc) if doc else {"provider": provider, "enabled": False, "config": {}, "status": "missing_configuration", "configured_secrets": [],
            **({"callback_security_configured": False} if provider == "sarvam" else {})}), "webhooks": webhooks(ws_id, provider)})
    return result


@router.put("/workspaces/{ws_id}/voice-providers/{provider}")
async def put_config(ws_id: str, provider: Provider, request: Request, body: ConfigUpdate):
    await require_workspace_access(request, ws_id)
    # SecretStr ensures validation diagnostics never reflect supplied secrets.
    return await save_config(db_from(request), ws_id, provider, body.enabled, body.config,
                             {k: v.get_secret_value() for k, v in body.credentials.items()}, body.revision)


@router.post("/workspaces/{ws_id}/voice-providers/{provider}/test")
async def test_config(ws_id: str, provider: Provider, request: Request):
    await require_workspace_access(request, ws_id)
    db = db_from(request)
    doc, secrets = await load_config(db, ws_id, provider, enabled=False)
    status = await get_provider(provider).test_connection(doc["config"], secrets)
    patch = {"status": status, "last_verified_at": now_iso(), "error_code": None if status == "connected" else status}
    updated = await db.workspace_voice_provider_configs.update_one({"workspace_id": ws_id, "provider": provider, "revision": doc["revision"]}, {"$set": patch})
    if not updated.matched_count:
        raise HTTPException(409, "Configuration changed during verification; test again")
    return patch


@router.post("/workspaces/{ws_id}/voice-providers/sarvam/callback-secret/regenerate")
async def regenerate_sarvam_secret(ws_id: str, request: Request, body: SecretRegeneration):
    await require_workspace_access(request, ws_id)
    return await regenerate_sarvam_callback_secret(db_from(request), ws_id, body.revision)


@router.post("/sarvam/workspaces/{ws_id}/calls/{session_id}/result")
async def sarvam_callback(ws_id: str, session_id: str, request: Request):
    start = time.monotonic()
    if not ObjectId.is_valid(ws_id) or not ObjectId.is_valid(session_id):
        raise HTTPException(404, "Call not found")
    db = db_from(request)
    session = await db.plivo_call_sessions.find_one({"_id": ObjectId(session_id), "workspace_id": ws_id, "provider": "sarvam"})
    if not session:
        raise HTTPException(404, "Call not found")
    # Bound request bodies; never log the raw callback or validation diagnostics.
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 1_000_000:
            raise HTTPException(413, "Callback too large")
        chunks.append(chunk)
    try:
        raw = json.loads(b"".join(chunks))
        metadata = raw["webhook_config"]["metadata"]
        proof = metadata["callback_proof"]
        if not isinstance(proof, str):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(403, "Invalid callback authentication") from None
    # Store only a digest per session. Rotation/disable does not strand in-flight calls.
    expected = session.get("callback_proof_hash", "")
    if not expected or not hmac.compare_digest(hashlib.sha256(proof.encode()).hexdigest(), expected):
        raise HTTPException(403, "Invalid callback authentication")
    # Sarvam echoes webhook metadata. New calls include these identifiers so a
    # valid capability cannot be replayed against another lead or session URL.
    correlation = {
        "arevei_workspace_id": ws_id,
        "lead_id": str(session["lead_id"]),
        "qualification_session_id": session_id,
    }
    if any(key in metadata and str(metadata[key]) != value for key, value in correlation.items()):
        raise HTTPException(403, "Callback does not match qualification session")
    # Authentication metadata has served its purpose and must not enter event or
    # qualification payloads.
    raw.pop("webhook_config", None)
    raw.pop("_arevei_recording_url", None)
    call = get_provider("sarvam").normalize(raw, session["lead_id"])
    call_id = (session.get("provider_identifiers") or {}).get("call_uuid")
    if not call_id:
        raise HTTPException(503, "Call initiation is still being reconciled", headers={"Retry-After": "5"})
    if call.provider_call_id != call_id:
        raise HTTPException(403, "Callback does not match call")
    # Discard caller-supplied internal enrichment. Media URLs come only from the
    # authenticated provider API, and an unavailable recording never blocks a result.
    raw.pop("_arevei_recording_url", None)
    recording = session.get("recording_url")
    if raw.get("interaction_id") and not recording:
        try:
            doc, secrets = await load_config(db, ws_id, "sarvam", enabled=False)
            recording = await get_provider("sarvam").recording(doc["config"], secrets, call_id, session.get("started_at") or session.get("created_at"))
        except HTTPException:
            recording = None
    if recording:
        raw["_arevei_recording_url"] = recording
    from qualification_service import QualificationWebhookController
    result = await QualificationWebhookController(db).process(ws_id, session["lead_id"], raw, provider="sarvam")
    await db.plivo_call_sessions.update_one({"_id": session["_id"], "workspace_id": ws_id}, {"$set": {"provider_session_id": raw.get("interaction_id"), "provider_identifiers.interaction_id": raw.get("interaction_id"), "recording_reference": {"provider": "sarvam", "interaction_id": raw.get("interaction_id"), "availability": "provider_managed" if raw.get("interaction_id") else "unavailable"}, "transcript_status": "received" if call.transcript else "unavailable"}})
    await db.workspace_voice_provider_configs.update_one({"workspace_id": ws_id, "provider": "sarvam"}, {"$set": {"last_callback_at": now_iso()}})
    logger.info(json.dumps({"event": "qualification_callback", "workspace_id": ws_id, "lead_id": session["lead_id"], "qualification_profile_id": session.get("profile_id"), "provider": "sarvam", "provider_call_id": call_id, "session_id": session_id, "normalized_status": call.call_status, "qualification_status": result.get("status"), "processing_duration_ms": round((time.monotonic() - start) * 1000)}))
    return {k: v for k, v in result.items() if k != "lead"}


@router.post("/workspaces/{ws_id}/voice-providers/sarvam/calls/{session_id}/recording/refresh")
async def refresh_recording(ws_id: str, session_id: str, request: Request):
    """Explicit retry for media published after the final call callback."""
    await require_workspace_access(request, ws_id)
    if not ObjectId.is_valid(session_id):
        raise HTTPException(404, "Call not found")
    db = db_from(request)
    session = await db.plivo_call_sessions.find_one({"_id": ObjectId(session_id), "workspace_id": ws_id, "provider": "sarvam"})
    if not session:
        raise HTTPException(404, "Call not found")
    doc, secrets = await load_config(db, ws_id, "sarvam", enabled=False)
    call_id = (session.get("provider_identifiers") or {}).get("call_uuid")
    if not call_id:
        raise HTTPException(409, "Call requires reconciliation")
    recording = await get_provider("sarvam").recording(doc["config"], secrets, call_id, session.get("started_at") or session.get("created_at"))
    if not recording:
        return {"status": "recording_unavailable"}
    await db.plivo_call_sessions.update_one({"_id": session["_id"], "workspace_id": ws_id}, {"$set": {"recording_url": recording}})
    await db.crm_leads.update_one({"_id": ObjectId(session["lead_id"]), "workspace_id": ws_id, "qualification_call.session_id": session_id},
        {"$set": {"qualification_call.recording_url": recording, "communication_summary.last_recording_url": recording}})
    await db.crm_call_logs.update_many({"workspace_id": ws_id, "lead_id": session["lead_id"], "provider": "sarvam", "provider_call_id": call_id, "kind": "qualification_engine"},
        {"$set": {"call_result.recording_url": recording}})
    return {"status": "available", "recording_url": recording}
