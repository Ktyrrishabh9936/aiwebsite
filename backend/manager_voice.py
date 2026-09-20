"""Inbound-only Sarvam API-tool adapter. No telephony or qualification imports.

The JSON names below belong to AREVEI's configurable HTTP tool contract, not
an assumed Sarvam webhook schema. See SARVAM_AI_MANAGER.md for picker mappings.
"""
import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger("ai_manager.voice")
MAX_BODY_BYTES = 32768
MANAGER_TIMEOUT = 20
REQUEST_TIMEOUT = 25
MAX_TURNS = 100
PHONE = re.compile(r"^\+[1-9]\d{7,14}$")


class VoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    caller_phone: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    # Map Call Transcript with the picker; preserve its actual JSON type.
    transcript: JsonValue = None
    # Optional AREVEI per-turn key. NEVER use Interaction ID here (it is per-call).
    request_id: str | None = Field(default=None, min_length=1, max_length=160)


def configuration():
    prefix = "SARVAM_AI_MANAGER_"
    return {
        "enabled": os.getenv(prefix + "ENABLED", "false").lower() == "true",
        "key": os.getenv(prefix + "API_KEY", ""),
    }


def configured(config):
    return len(config["key"]) >= 32


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def event(name, **fields):
    # Never pass message text, phone numbers, tokens or exception strings here.
    logger.info(json.dumps({"event": name, **fields}, separators=(",", ":")))


def speech_text(text, *, allow_urls=False):
    """Conservative transport-only cleanup; never emit raw structured answers."""
    text = str(text or "").strip()
    if not text or "[error:" in text.lower():
        raise ValueError("Empty or failed manager response")
    if text.startswith(("{", "[")):
        try:
            json.loads(text)
            return "I couldn't turn that result into a spoken answer. Please ask a more specific question."
        except (ValueError, TypeError):
            pass
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"!?\[([^\]]+)\]\(([^)]+)\)", lambda m: f"{m[1]} {m[2]}" if allow_urls else m[1], text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    if not allow_urls:
        text = re.sub(r"(?:https?://|www\.)\S+", "", text, flags=re.I)
    text = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b[0-9a-f]{24}\b", "", text, flags=re.I)
    text = re.sub(r"(?im)^.*\b(?:api[_ -]?key|authorization|password|secret|access[_ -]?token|system prompt)\s*[:=].*$", "", text)
    lines = []
    for line in text.splitlines():
        if re.fullmatch(r"[\s|:\-]+", line):
            continue
        line = re.sub(r"^\s*(?:#{1,6}\s*|[-*+>]\s+|\d+[.)]\s+)", "", line)
        line = re.sub(r"[*_`~]", "", line).replace("|", ", ").strip(" ,")
        line = re.sub(r"\b(?:ID|UUID)\s*:\s*(?=[,.;]|$)", "", line, flags=re.I)
        if line:
            lines.append(line)
    result = re.sub(r"\s+", " ", ". ".join(lines)).strip()
    # Keep phone replies short even if the model ignores the style instruction.
    sentences = re.split(r"(?<=[.!?])\s+", result)
    result = " ".join(sentences[:5])
    if len(result) > 1200:
        result = result[:1100].rsplit(" ", 1)[0] + ". Ask me for more detail."
    return result or "I couldn't turn that result into a spoken answer. Please rephrase your question."


async def initialize_voice_storage(db):
    # Separate collections from Plivo and qualification. Connections can be
    # prepared while the shared Sarvam service is disabled.
    await db.ai_manager_voice_sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.ai_manager_voice_sessions.create_index([("workspace_id", 1), ("started_at", -1)])
    await db.ai_manager_voice_sessions.create_index([("caller_phone", 1), ("session_id", 1)])
    await db.ai_manager_voice_connections.create_index("caller_phone", unique=True)


def build_voice_router(db, manager, owned_workspace, require_user):
    router = APIRouter(prefix="/ai-manager/voice", tags=["AI Manager voice test"])
    recent = deque()

    @router.get("/health")
    async def health():
        config = configuration()
        # Configuration syntax only, not a DB, LLM or telephone connectivity test.
        return {"enabled": config["enabled"], "configured": configured(config)}

    @router.get("/workspaces/{ws_id}/connection")
    async def get_connection(ws_id: str, request: Request):
        user = await require_user(request)
        await owned_workspace(ws_id, user)
        connection = await db.ai_manager_voice_connections.find_one({
            "workspace_id": ws_id, "user_id": str(user["_id"]), "enabled": True,
        })
        return {"connected": bool(connection), "caller_phone": connection.get("caller_phone", "") if connection else "",
                "service_enabled": configuration()["enabled"]}

    @router.put("/workspaces/{ws_id}/connection")
    async def connect_workspace(ws_id: str, request: Request):
        user = await require_user(request)
        await owned_workspace(ws_id, user)
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(422, "Invalid connection request") from None
        if not isinstance(payload, dict) or set(payload) != {"caller_phone"}:
            raise HTTPException(422, "caller_phone is required")
        caller_phone = str(payload.get("caller_phone") or "").strip()
        if not PHONE.fullmatch(caller_phone):
            raise HTTPException(422, "Use an E.164 phone number, such as +919876543210")
        user_id = str(user["_id"])
        existing = await db.ai_manager_voice_connections.find_one({"caller_phone": caller_phone})
        if existing and existing.get("user_id") != user_id:
            raise HTTPException(409, "This phone number is already connected to another account")
        now = datetime.now(timezone.utc)
        try:
            await db.ai_manager_voice_connections.update_one(
                {"_id": user_id},
                {"$set": {"caller_phone": caller_phone, "workspace_id": ws_id, "user_id": user_id,
                          "enabled": True, "updated_at": now}, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
        except DuplicateKeyError:
            raise HTTPException(409, "This phone number is already connected") from None
        event("voice_connection_updated", workspace=ws_id)
        return {"connected": True, "caller_phone": caller_phone, "service_enabled": configuration()["enabled"]}

    @router.delete("/workspaces/{ws_id}/connection")
    async def disconnect_workspace(ws_id: str, request: Request):
        user = await require_user(request)
        await owned_workspace(ws_id, user)
        await db.ai_manager_voice_connections.delete_many({"workspace_id": ws_id, "user_id": str(user["_id"])})
        event("voice_connection_removed", workspace=ws_id)
        return {"connected": False, "caller_phone": "", "service_enabled": configuration()["enabled"]}

    async def process(body, config):
        connection = await db.ai_manager_voice_connections.find_one({"caller_phone": body.caller_phone, "enabled": True})
        if not connection:
            raise HTTPException(403, "Caller is not connected to an AREVEI workspace")
        # A workspace change affects new calls. An existing call stays with the
        # workspace it started in, as long as the same user's phone remains connected.
        existing_session = await db.ai_manager_voice_sessions.find_one({
            "caller_phone": body.caller_phone, "session_id": body.session_id,
        })
        user_id = connection.get("user_id", "")
        workspace_id = connection.get("workspace_id", "")
        if existing_session and existing_session.get("user_id") == user_id:
            workspace_id = existing_session.get("workspace_id", "")
        if not ObjectId.is_valid(user_id) or not ObjectId.is_valid(workspace_id):
            raise HTTPException(403, "Voice access is not authorized")
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(403, "Voice access is not authorized")
        try:
            ws = await owned_workspace(workspace_id, user)
        except HTTPException:
            raise HTTPException(403, "Voice access is not authorized") from None
        identity = f"{workspace_id}:{user_id}:{body.session_id}"
        session_key = digest(identity)
        event("voice_workspace_resolved", session=session_key, workspace=workspace_id)
        fingerprint = digest(json.dumps([body.message, body.transcript], ensure_ascii=False, sort_keys=True))
        turn_key = digest(body.request_id) if body.request_id else fingerprint
        sessions = db.ai_manager_voice_sessions
        now = datetime.now(timezone.utc)
        try:
            await sessions.insert_one({
                "_id": session_key, "kind": "ai_manager_inbound_test", "provider": "sarvam",
                "session_id": body.session_id, "caller_phone": body.caller_phone,
                "workspace_id": workspace_id, "user_id": user_id,
                "started_at": now, "updated_at": now, "expires_at": now + timedelta(days=7),
                "history": [], "turns": [], "results": {},
            })
        except DuplicateKeyError:
            pass
        session = await sessions.find_one({"_id": session_key})
        if session["caller_phone"] != body.caller_phone:
            raise HTTPException(403, "Voice session does not belong to this caller")
        # Mongo may return naive UTC datetimes; never revive old call IDs.
        if (now - session["started_at"].replace(tzinfo=timezone.utc)).total_seconds() > 14400:
            raise HTTPException(409, "Voice session expired; start a new call")
        previous = session["results"].get(turn_key)
        if previous:
            if previous["fingerprint"] != fingerprint:
                raise HTTPException(409, "Request identifier was already used")
            event("voice_turn_replayed", session=session_key)
            return previous["response"]
        if len(session["turns"]) >= MAX_TURNS:
            raise HTTPException(409, "Voice session limit reached; start a new call")
        token = secrets.token_hex(16)
        locked = await sessions.find_one_and_update(
            {"_id": session_key, "busy_token": {"$exists": False}, f"results.{turn_key}": {"$exists": False}},
            {"$set": {"busy_token": token, "pending": {"turn_key": turn_key, "message": body.message, "started_at": now}}},
            return_document=ReturnDocument.AFTER,
        )
        if not locked:
            raise HTTPException(409, "A voice turn is already processing; retry shortly")
        if len(locked["turns"]) >= MAX_TURNS:
            await sessions.update_one({"_id": session_key, "busy_token": token}, {"$unset": {"busy_token": "", "pending": ""}})
            raise HTTPException(409, "Voice session limit reached; start a new call")
        # No expiring lock: a crashed or uncertain write MUST NOT replay actions.
        # A normal failure records an answer; a crash needs operator reconciliation.
        audit = []
        start = time.monotonic()
        event("voice_manager_started", session=session_key)

        async def collect():
            chunks = []
            size = 0
            async for chunk in manager.stream(ws, body.message, locked["history"], voice=True, audit=audit):
                chunks.append(chunk)
                size += len(chunk)
                if size > 24000:
                    raise ValueError("Manager response too large")
            return "".join(chunks)

        error = None
        try:
            text = await asyncio.wait_for(collect(), timeout=MANAGER_TIMEOUT)
            reply = speech_text(text, allow_urls=bool(re.search(r"\b(url|link|website address)\b", body.message, re.I)))
        except asyncio.TimeoutError:
            error = "manager_timeout"
            reply = "The manager took too long to respond. If you requested a change, check the workspace before trying it again."
        except Exception:
            error = "manager_failed"
            reply = "I couldn't complete that request. If you requested a change, check the workspace before trying it again."
        response = {"reply": reply, "session_id": body.session_id, "ok": error is None}
        duration = round((time.monotonic() - start) * 1000)
        finished = datetime.now(timezone.utc)
        history = (locked["history"] + [{"role": "user", "content": body.message}, {"role": "assistant", "content": reply}])[-12:]
        turn = {"request_key": turn_key, "message": body.message, "reply": reply, "tools": audit,
                "started_at": now, "finished_at": finished, "duration_ms": duration, "error": error}
        result = await sessions.update_one({"_id": session_key, "busy_token": token}, {
            "$set": {"history": history, "updated_at": finished, "latest_transcript": body.transcript,
                     f"results.{turn_key}": {"fingerprint": fingerprint, "response": response}},
            "$push": {"turns": turn}, "$unset": {"busy_token": "", "pending": ""},
        })
        if result.matched_count != 1:
            raise RuntimeError("Voice session ownership lost")
        event("voice_manager_finished", session=session_key, duration_ms=duration, outcome=error or "success", tools=audit)
        return response

    @router.post("")
    async def voice(request: Request):
        config = configuration()
        if not config["enabled"]:
            raise HTTPException(404, "Voice test is disabled")
        if not configured(config):
            raise HTTPException(503, "Voice test is not configured")
        authorization = request.headers.get("authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.encode(), config["key"].encode()):
            event("voice_auth_rejected")
            raise HTTPException(401, "Invalid voice credential", headers={"WWW-Authenticate": "Bearer"})
        if not getattr(request.app.state, "voice_storage_ready", True):
            raise HTTPException(503, "Voice storage is not ready")
        now = time.monotonic()
        while recent and now - recent[0] >= 60:
            recent.popleft()
        if len(recent) >= 30:
            raise HTTPException(429, "Voice request limit reached", headers={"Retry-After": "60"})
        recent.append(now)
        if request.headers.get("content-type", "").split(";")[0].lower() != "application/json":
            raise HTTPException(415, "Use application/json")

        async def parse_body():
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > MAX_BODY_BYTES:
                    raise HTTPException(413, "Voice request is too large")
            try:
                return VoiceRequest.model_validate_json(raw)
            except (ValidationError, ValueError):
                # Pydantic's default errors include input values. Do not echo transcripts.
                raise HTTPException(422, "Invalid voice request; check the documented contract") from None

        try:
            body = await asyncio.wait_for(parse_body(), timeout=5)
            event("voice_request_authenticated")
            payload = await asyncio.wait_for(process(body, config), timeout=REQUEST_TIMEOUT)
            return JSONResponse(payload, headers={"Cache-Control": "no-store"})
        except HTTPException:
            raise
        except asyncio.TimeoutError:
            event("voice_request_failed", reason="deadline")
            raise HTTPException(504, "Voice request timed out; verify any requested change in the workspace") from None
        except Exception:
            event("voice_request_failed", reason="internal")
            raise HTTPException(503, "Voice manager is temporarily unavailable; verify any requested change in the workspace") from None

    return router
