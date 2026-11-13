"""Automated Sarvam voice-agent creation through Sarvam's official Voice Agents MCP server.

Sarvam's public REST API (X-API-Key) places calls and reads analytics but cannot create,
configure or commit agents. Those operations are exposed only by the official MCP server at
https://mcp.sarvam.ai/voice-agents, which authenticates with OAuth 2.1 (PKCE, dynamic client
registration, refresh tokens). This module:

- connects a workspace owner's Sarvam account once (browser consent), storing tokens encrypted
  with the existing voice credential key ring, bound to the AREVEI workspace;
- creates, prompts, verifies and commits an agent with AREVEI's fixed lead-context contract;
- saves the resulting app id / version / connection into the existing Sarvam provider
  configuration through ``voice_config.save_config`` so calling needs no further setup.

Nothing here touches call initiation, callbacks, the qualification engine or Plivo.
"""
import base64
import hashlib
import json
import logging
import os
import re
import secrets as secure_random
import time
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Literal
from urllib.parse import urlencode, urlsplit

import httpx
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from crm import db_from, require_workspace_access
from models import now_iso
from voice_config import decrypt, encrypt, load_config, platform_sarvam_configured, platform_sarvam_key, public_base, public_config, save_config
from voice_providers import get_provider

router = APIRouter(tags=["sarvam agent builder"])
logger = logging.getLogger("voice.sarvam_builder")

MCP_URL = "https://mcp.sarvam.ai/voice-agents"
OAUTH_METADATA_URL = MCP_URL + "/.well-known/oauth-authorization-server"
MCP_PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "AREVEI AI Manager"
TOKEN_ENVELOPE = "sarvam_account"  # encrypt()/decrypt() binding for account tokens
STATE_TTL = timedelta(minutes=10)
CREATION_LEASE = timedelta(minutes=10)
TOOL_TIMEOUT = 45
Language = Literal["English", "Hindi", "Bengali", "Gujarati", "Kannada", "Konkani", "Malayalam", "Tamil", "Telugu",
                   "Punjabi", "Odia", "Marathi", "Assamese"]
SUPPORTED_LANGUAGES = Language.__args__
# AREVEI's own Sarvam sign-in, used only by scripts/setup_sarvam_master_agent.py to create the
# master agent. Stored under this pseudo workspace id, separate from every workspace's own account.
PLATFORM_ACCOUNT = "__platform__"
INPUT_VARIABLES = [
    {"name": "lead_name", "description": "Lead name"},
    {"name": "lead_phone", "description": "Lead phone number"},
    {"name": "lead_context", "description": "Dynamic campaign form and CRM context"},
]


class SarvamBuilderError(HTTPException):
    """HTTP error with a stable machine-readable code for the frontend."""

    def __init__(self, status_code, code, message):
        super().__init__(status_code, {"code": code, "message": message})
        self.code = code


# --------------------------------------------------------------------------- OAuth

_metadata_cache = {"value": None, "at": 0.0}


async def oauth_metadata(client):
    if _metadata_cache["value"] and time.monotonic() - _metadata_cache["at"] < 3600:
        return _metadata_cache["value"]
    try:
        response = await client.get(OAUTH_METADATA_URL, timeout=15)
        data = response.json() if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        data = None
    if not data or not all(data.get(k) for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint")):
        raise SarvamBuilderError(503, "provider_unavailable", "Sarvam account sign-in is unavailable right now")
    _metadata_cache.update(value=data, at=time.monotonic())
    return data


def redirect_uri():
    configured = os.getenv("SARVAM_OAUTH_REDIRECT_URI", "").strip()
    if configured:
        parsed = urlsplit(configured)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.query or parsed.fragment:
            raise SarvamBuilderError(503, "configuration_error", "SARVAM_OAUTH_REDIRECT_URI is invalid")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise SarvamBuilderError(503, "configuration_error", "SARVAM_OAUTH_REDIRECT_URI must use HTTPS")
        return configured
    return f"{public_base()}/api/sarvam/oauth/callback"


async def oauth_client_id(db, client, metadata, uri):
    """One dynamically registered public client per callback URL, shared by all workspaces."""
    doc = await db.sarvam_oauth_clients.find_one({"redirect_uri": uri})
    if doc and doc.get("client_id"):
        return doc["client_id"]
    try:
        response = await client.post(metadata["registration_endpoint"], json={
            "client_name": CLIENT_NAME, "redirect_uris": [uri], "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": "none"}, timeout=20)
        data = response.json() if response.status_code in (200, 201) else {}
    except (httpx.HTTPError, ValueError):
        data = {}
    if not data.get("client_id"):
        raise SarvamBuilderError(503, "provider_unavailable", "Could not register AREVEI with Sarvam sign-in")
    await db.sarvam_oauth_clients.update_one({"redirect_uri": uri}, {"$set": {
        "client_id": data["client_id"], "registered_at": now_iso(), "updated_at": now_iso()}}, upsert=True)
    return data["client_id"]


def pkce_pair():
    verifier = base64.urlsafe_b64encode(secure_random.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def account_public(doc):
    if not doc or doc.get("status") in (None, "pending", "disconnected"):
        return {"status": "disconnected", "connected_at": None, "sarvam_org_id": None, "sarvam_workspace_id": None, "error": None}
    return {"status": doc.get("status", "disconnected"), "connected_at": doc.get("connected_at"),
            "sarvam_org_id": doc.get("sarvam_org_id"), "sarvam_workspace_id": doc.get("sarvam_workspace_id"),
            "error": doc.get("error"), "connected_by": doc.get("connected_by_email")}


async def begin_connect(db, ws_id, user):
    async with httpx.AsyncClient() as client:
        metadata = await oauth_metadata(client)
        uri = redirect_uri()
        client_id = await oauth_client_id(db, client, metadata, uri)
    verifier, challenge = pkce_pair()
    state = secure_random.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    owner = ws_id
    existing = await db.sarvam_account_connections.find_one({"workspace_id": owner}) or {}
    # A new consent never discards a working connection until the exchange succeeds.
    await db.sarvam_account_connections.update_one({"workspace_id": owner}, {"$set": {
        "workspace_id": owner,
        "pending": {"state": state, "encrypted_verifier": encrypt(owner, TOKEN_ENVELOPE, {"verifier": verifier}),
                    "client_id": client_id, "redirect_uri": uri, "expires_at": (now + STATE_TTL).isoformat(),
                    "user_id": str(user["_id"]), "user_email": user.get("email")},
        "status": existing.get("status") or "pending", "updated_at": now.isoformat()},
        "$setOnInsert": {"created_at": now.isoformat()}}, upsert=True)
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": uri, "code_challenge": challenge,
              "code_challenge_method": "S256", "state": state, "resource": MCP_URL}
    return metadata["authorization_endpoint"] + "?" + urlencode(params)


async def finish_connect(db, state, code):
    doc = await db.sarvam_account_connections.find_one({"pending.state": state})
    pending = (doc or {}).get("pending") or {}
    if not doc or pending.get("state") != state:
        raise SarvamBuilderError(400, "invalid_state", "This sign-in link is not valid. Start the connection again from AREVEI.")
    ws_id = doc["workspace_id"]
    if datetime.fromisoformat(pending["expires_at"]) < datetime.now(timezone.utc):
        await db.sarvam_account_connections.update_one({"_id": doc["_id"]}, {"$unset": {"pending": ""}})
        raise SarvamBuilderError(400, "expired_state", "This sign-in link expired. Start the connection again from AREVEI.")
    verifier = decrypt(ws_id, TOKEN_ENVELOPE, pending["encrypted_verifier"])["verifier"]
    async with httpx.AsyncClient() as client:
        metadata = await oauth_metadata(client)
        tokens = await exchange_token(client, metadata, {
            "grant_type": "authorization_code", "code": code, "redirect_uri": pending["redirect_uri"],
            "client_id": pending["client_id"], "code_verifier": verifier, "resource": MCP_URL})
    now = now_iso()
    await db.sarvam_account_connections.update_one({"_id": doc["_id"], "pending.state": state}, {
        "$set": {"status": "connected", "encrypted_tokens": token_envelope(ws_id, tokens), "client_id": pending["client_id"],
                 "token_revision": int(doc.get("token_revision") or 0) + 1, "connected_at": now, "updated_at": now,
                 "connected_by_user_id": pending.get("user_id"), "connected_by_email": pending.get("user_email"),
                 "error": None, "sarvam_org_id": doc.get("sarvam_org_id"), "sarvam_workspace_id": doc.get("sarvam_workspace_id")},
        "$unset": {"pending": ""}})
    return ws_id


def token_envelope(ws_id, tokens):
    return encrypt(ws_id, TOKEN_ENVELOPE, {
        "access_token": tokens["access_token"], "refresh_token": tokens.get("refresh_token"),
        "expires_at": time.time() + float(tokens.get("expires_in") or 0)})


async def exchange_token(client, metadata, form):
    last_error = None
    for attempt in range(3):
        try:
            response = await client.post(metadata["token_endpoint"], data=form, timeout=20)
        except httpx.HTTPError as exc:
            last_error = exc
            continue
        if response.status_code == 200:
            try:
                data = response.json()
                if data.get("access_token"):
                    return data
            except ValueError:
                pass
            raise SarvamBuilderError(502, "provider_unavailable", "Sarvam returned an unexpected sign-in response")
        if response.status_code == 400:
            # "authorization code does not exist" was observed transiently; retry once more.
            last_error = response.status_code
            continue
        raise SarvamBuilderError(502, "provider_unavailable", "Sarvam rejected the sign-in exchange")
    raise SarvamBuilderError(502, "provider_unavailable", "Sarvam sign-in could not be completed; try connecting again")


async def disconnect(db, ws_id):
    await db.sarvam_account_connections.update_one({"workspace_id": ws_id}, {
        "$set": {"status": "disconnected", "updated_at": now_iso()},
        "$unset": {"encrypted_tokens": "", "pending": ""}})


# --------------------------------------------------------------------------- MCP client


class SarvamMcpClient:
    """Minimal streamable-HTTP JSON-RPC client for the Sarvam Voice Agents MCP server."""

    def __init__(self, db, ws_id, connection):
        self.db, self.ws_id, self.connection = db, ws_id, connection
        self.session_id = None
        self.counter = 0
        self.client = httpx.AsyncClient(timeout=TOOL_TIMEOUT)
        self.initialized = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.client.aclose()

    async def access_token(self, force_refresh=False):
        doc = self.connection
        if doc.get("status") != "connected" or not doc.get("encrypted_tokens"):
            raise SarvamBuilderError(409, "account_not_connected", "Connect the Sarvam account before creating agents")
        tokens = decrypt(doc["workspace_id"], TOKEN_ENVELOPE, doc["encrypted_tokens"])
        if not force_refresh and tokens.get("expires_at", 0) - 120 > time.time():
            return tokens["access_token"]
        if not tokens.get("refresh_token"):
            await self.mark_expired()
            raise SarvamBuilderError(409, "account_reconnect_required", "The Sarvam connection expired. Reconnect the account.")
        metadata = await oauth_metadata(self.client)
        try:
            response = await self.client.post(metadata["token_endpoint"], data={
                "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                "client_id": doc.get("client_id"), "resource": MCP_URL}, timeout=20)
        except httpx.HTTPError:
            raise SarvamBuilderError(503, "provider_unavailable", "Sarvam sign-in is unavailable right now") from None
        if response.status_code != 200:
            await self.mark_expired()
            raise SarvamBuilderError(409, "account_reconnect_required", "The Sarvam connection expired. Reconnect the account.")
        new = response.json()
        new.setdefault("refresh_token", tokens["refresh_token"])
        revision = int(doc.get("token_revision") or 0)
        updated = await self.db.sarvam_account_connections.update_one(
            {"_id": doc["_id"], "token_revision": revision},
            {"$set": {"encrypted_tokens": (envelope := token_envelope(doc["workspace_id"], new)), "token_revision": revision + 1, "updated_at": now_iso()}})
        if updated.matched_count:
            self.connection = {**doc, "encrypted_tokens": envelope, "token_revision": revision + 1}
        else:
            # Another worker refreshed concurrently; its rotated token is the valid one.
            self.connection = await self.db.sarvam_account_connections.find_one({"_id": doc["_id"]}) or doc
            return await self.access_token()
        return new["access_token"]

    async def mark_expired(self):
        await self.db.sarvam_account_connections.update_one({"_id": self.connection["_id"]}, {"$set": {
            "status": "expired", "error": "account_reconnect_required", "updated_at": now_iso()}})
        self.connection["status"] = "expired"

    async def rpc(self, method, params=None, *, notify=False, _retry=True):
        self.counter += 1
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            body["id"] = self.counter
        headers = {"Authorization": "Bearer " + await self.access_token(), "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": MCP_PROTOCOL_VERSION}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        try:
            response = await self.client.post(MCP_URL, headers=headers, content=json.dumps(body))
        except httpx.TimeoutException:
            raise SarvamBuilderError(504, "provider_timeout", "Sarvam did not respond in time") from None
        except httpx.HTTPError:
            raise SarvamBuilderError(503, "provider_unavailable", "Sarvam is unreachable right now") from None
        if response.headers.get("mcp-session-id"):
            self.session_id = response.headers["mcp-session-id"]
        if response.status_code == 401 and _retry:
            await self.access_token(force_refresh=True)
            return await self.rpc(method, params, notify=notify, _retry=False)
        if response.status_code == 401:
            await self.mark_expired()
            raise SarvamBuilderError(409, "account_reconnect_required", "The Sarvam connection expired. Reconnect the account.")
        if response.status_code == 429:
            raise SarvamBuilderError(503, "provider_unavailable", "Sarvam rate limit reached; try again in a minute")
        if response.status_code >= 400:
            raise SarvamBuilderError(502, "provider_unavailable", f"Sarvam agent service returned HTTP {response.status_code}")
        if notify:
            return None
        return parse_rpc_response(response)

    async def ensure_initialized(self):
        if self.initialized:
            return
        result = await self.rpc("initialize", {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {},
                                               "clientInfo": {"name": "arevei-ai-manager", "version": "1.0"}})
        if not isinstance(result, dict) or "result" not in result:
            raise SarvamBuilderError(502, "provider_unavailable", "Sarvam agent service handshake failed")
        await self.rpc("notifications/initialized", {}, notify=True)
        self.initialized = True

    async def tool(self, name, arguments):
        """Call a tool; returns the parsed JSON payload. Tool-level errors raise with Sarvam's message."""
        await self.ensure_initialized()
        message = await self.rpc("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(message, dict):
            raise SarvamBuilderError(502, "provider_unavailable", "Sarvam agent service returned no result")
        if "error" in message:
            raise SarvamBuilderError(502, "provider_unavailable", "Sarvam agent service rejected the request")
        result = message.get("result") or {}
        text = "\n".join(part.get("text", "") for part in result.get("content", []) if isinstance(part, dict))
        if result.get("isError"):
            raise SarvamBuilderError(422, "configuration_error", safe_tool_message(text))
        try:
            data = json.loads(text) if text else {}
        except ValueError:
            data = {"_text": text}
        return data if isinstance(data, dict) else {"_value": data}


def parse_rpc_response(response):
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        last = None
        for line in response.text.splitlines():
            if line.startswith("data:"):
                try:
                    message = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if isinstance(message, dict) and "id" in message:
                    last = message
        return last
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def safe_tool_message(text):
    """Surface Sarvam's validation message without URLs, tokens or oversized bodies."""
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"(?i)(api[_-]?key|token|secret|authorization)\s*[:=]\s*\S+", r"\1=[redacted]", text)
    text = " ".join(text.split())
    return text[:600] or "Sarvam rejected the agent configuration"


# --------------------------------------------------------------------------- Agent creation


class AgentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    creation_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    agent_name: str = Field(min_length=1, max_length=50, pattern=r"^[\w\- ()]{1,50}$")
    business_name: str = Field(default="", max_length=300)
    offer: str = Field(default="", max_length=8000)
    objective: str = Field(default="", max_length=4000)
    instructions: str = Field(default="", max_length=16000)
    connection_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")
    agent_phone_number: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    initial_language: Language = "English"
    supported_languages: list[Language] = Field(default_factory=lambda: ["English", "Hindi"], max_length=13)
    voice_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")
    intro_message: str = Field(default="Hi, am I speaking with {{lead_name}}?", min_length=1, max_length=300)
    api_key: SecretStr | None = None
    revision: int | None = None


def creation_public(doc):
    if not doc:
        return None
    keys = ("creation_key", "status", "agent_name", "app_id", "app_version", "connection_id", "agent_phone_number",
            "error_code", "error", "created_at", "updated_at", "steps")
    return {key: doc.get(key) for key in keys}


def agent_variables(inputs=None):
    from voice_api import SARVAM_QUALIFICATION_OUTPUTS
    variables = {}
    for item in inputs or INPUT_VARIABLES:
        variables[item["name"]] = {"name": item["name"], "value": "", "description": item["description"], "type": "string",
                                   "needs_initial_value": True, "update_post_interaction": False}
    for item in SARVAM_QUALIFICATION_OUTPUTS:
        variables[item["name"]] = {
            "name": item["name"], "value": "", "description": item["description"], "type": "string",
            "needs_initial_value": False, "update_post_interaction": True,
            "post_interaction_prompt": (f"From the conversation, determine {item['name']}: {item['description']}. "
                                        "Use only facts the lead explicitly stated or reliably confirmed. Leave empty when unknown.")}
    return variables


def build_agent_config(body: AgentCreateRequest, inputs=None):
    languages = list(dict.fromkeys([body.initial_language, *body.supported_languages]))
    config = {
        "channel_type": "v2v",
        "llm_config": {"agent_config": {"agent_variables": agent_variables(inputs)}},
        "language_config": {"initial_language_name": body.initial_language, "supported_languages": languages},
        "intro_message_config": {"audio": body.intro_message},
    }
    if body.voice_id:
        config["text_to_speech_config"] = {"config_version": "2.0", "internal_id": body.voice_id.lower()}
    return config


async def sarvam_connection(db, ws_id):
    doc = await db.sarvam_account_connections.find_one({"workspace_id": ws_id})
    if not doc or doc.get("status") != "connected":
        code = "account_reconnect_required" if (doc or {}).get("status") == "expired" else "account_not_connected"
        raise SarvamBuilderError(409, code, "Connect the Sarvam account before creating agents")
    return doc


async def list_connections(db, ws_id):
    """Telephony connections with the numbers onboarded to each; the only numbers a call may dial from."""
    async with SarvamMcpClient(db, ws_id, await sarvam_connection(db, ws_id)) as mcp:
        listing = await mcp.tool("telephony", {"operation": "list_connections"})
        result = []
        for item in (listing.get("items") or [])[:10]:
            connection_id = item.get("connection_id")
            if not connection_id:
                continue
            numbers = []
            try:
                detail = await mcp.tool("telephony", {"operation": "get_connection", "id": connection_id, "params": {"include": ["endpoints"]}})
                numbers = [e.get("phone_number") for e in detail.get("endpoints") or [] if e.get("phone_number")]
            except SarvamBuilderError:
                numbers = []
            result.append({"connection_id": connection_id, "name": item.get("name") or connection_id,
                           "provider": item.get("channel_provider"), "status": item.get("status"), "phone_numbers": numbers})
        return result


async def list_voices(db, ws_id, language):
    async with SarvamMcpClient(db, ws_id, await sarvam_connection(db, ws_id)) as mcp:
        params = {"limit": 50}
        if language:
            params["language"] = language
        listing = await mcp.tool("agents", {"operation": "list_voices", "params": params})
    return [{"voice_id": v.get("internal_id"), "name": v.get("display_name"), "gender": v.get("gender"),
             "description": v.get("description"), "languages": v.get("preferred_languages") or []}
            for v in listing.get("items") or [] if v.get("internal_id")]


async def create_agent(db, ws_id, user, body: AgentCreateRequest):
    from voice_api import sarvam_runtime_prompt
    connection = await sarvam_connection(db, ws_id)
    # Calls still use the REST API key, so require it before anything is created in Sarvam.
    supplied_key = body.api_key.get_secret_value().strip() if body.api_key else ""
    stored_secrets = {}
    try:
        _, stored_secrets = await load_config(db, ws_id, "sarvam", enabled=False)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
    in_platform_workspace = platform_sarvam_key({"organization_id": connection.get("sarvam_org_id"), "workspace_id": connection.get("sarvam_workspace_id")})
    # Sarvam names the account's org/workspace only in the first commit. Until then the account may be
    # AREVEI's own, so proceed; connect_created_agent asks for a key if it turns out not to be.
    ids_unknown = not (connection.get("sarvam_org_id") and connection.get("sarvam_workspace_id"))
    platform_possible = ids_unknown and platform_sarvam_configured()
    if not supplied_key and not stored_secrets.get("api_key") and not in_platform_workspace and not platform_possible:
        raise SarvamBuilderError(422, "api_key_required", "Enter the Sarvam Voice Agents API key; calls are placed with it")
    now = now_iso()
    query = {"workspace_id": ws_id, "creation_key": body.creation_key}
    record = await db.sarvam_agent_creations.find_one(query)
    if record:
        if record.get("status") in ("connected",):
            return {"creation": creation_public(record), "provider": await current_provider(db, ws_id), "idempotent": True}
        if record.get("status") == "created_unsaved":
            return await connect_created_agent(db, ws_id, record, supplied_key, body.revision)
        if record.get("status") == "creating":
            started = datetime.fromisoformat(record.get("updated_at") or record.get("created_at"))
            if started + CREATION_LEASE > datetime.now(timezone.utc):
                raise SarvamBuilderError(409, "creation_in_progress", "This agent is still being created; wait for it to finish")
        if record.get("app_id"):
            # An agent exists in Sarvam for this key; never create a second one.
            return await connect_created_agent(db, ws_id, record, supplied_key, body.revision)
    base = {**query, "status": "creating", "agent_name": body.agent_name, "connection_id": body.connection_id,
            "agent_phone_number": body.agent_phone_number, "requested_by": str(user["_id"]), "updated_at": now,
            "error": None, "error_code": None, "steps": []}
    if record:
        claimed = await db.sarvam_agent_creations.update_one({**query, "status": record.get("status"), "updated_at": record.get("updated_at")}, {"$set": base})
        if not claimed.matched_count:
            raise SarvamBuilderError(409, "creation_in_progress", "This agent is already being created")
    else:
        from pymongo.errors import DuplicateKeyError
        try:
            await db.sarvam_agent_creations.insert_one({**base, "created_at": now})
        except DuplicateKeyError:
            raise SarvamBuilderError(409, "creation_in_progress", "This agent is already being created") from None

    async def progress(step, **fields):
        await db.sarvam_agent_creations.update_one(query, {"$set": {"updated_at": now_iso(), **fields}, "$push": {"steps": step}})

    async def fail(exc):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "failed", "message": str(exc.detail)}
        current = await db.sarvam_agent_creations.find_one(query) or {}
        status = "created_unsaved" if current.get("app_id") else "failed"
        await db.sarvam_agent_creations.update_one(query, {"$set": {"status": status, "error_code": detail.get("code"),
                                                                     "error": detail.get("message"), "updated_at": now_iso()}})
        logger.warning(json.dumps({"event": "sarvam_agent_creation_failed", "workspace_id": ws_id, "creation_key": body.creation_key,
                                   "status": status, "error_code": detail.get("code")}))

    runtime_prompt = sarvam_runtime_prompt(body.business_name or await workspace_business_name(db, ws_id), body.offer, body.objective, body.instructions)
    try:
        async with SarvamMcpClient(db, ws_id, connection) as mcp:
            created = await mcp.tool("configure_agent", {"name": body.agent_name, "config": build_agent_config(body)})
            app_id = created.get("id") or (created.get("details") or {}).get("app_id")
            if not app_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", str(app_id)):
                raise SarvamBuilderError(502, "provider_unavailable", "Sarvam did not return an agent id")
            await progress("created", app_id=app_id)
            await mcp.tool("configure_agent", {"agent_id": app_id, "prompt_append": runtime_prompt, "prompt_scope": "state"})
            await progress("prompt_written")
            # The template seeds a sample input; remove it so calls need only AREVEI's three inputs.
            try:
                await mcp.tool("configure_agent", {"agent_id": app_id, "config": {"llm_config": {"agent_config": {"agent_variables": {"user_name": None}}}}})
            except SarvamBuilderError:
                pass
            check = await mcp.tool("agents", {"operation": "get", "id": app_id, "params": {"include": ["variables", "prompt_text"]}})
            verify_agent(check)
            await progress("verified")
            commit = await mcp.tool("agents", {"operation": "commit", "id": app_id, "params": {"app_version_description": "Created by AREVEI AI Manager"}})
            versions = await mcp.tool("agents", {"operation": "get", "id": app_id, "params": {"include": ["versions"]}})
            committed = [int(v["app_version"]) for v in versions.get("versions") or [] if v.get("status") == "committed" and isinstance(v.get("app_version"), int)]
            if not committed:
                raise SarvamBuilderError(502, "provider_unavailable", "Sarvam did not report a committed version")
            app_version = max(committed)
            await progress("committed", app_version=app_version)
            # The commit record names the Sarvam org and workspace the agent lives in.
            org_id = commit.get("org_id") or connection.get("sarvam_org_id")
            sarvam_ws = commit.get("workspace_id") or connection.get("sarvam_workspace_id")
    except HTTPException as exc:
        await fail(exc)
        raise
    await db.sarvam_account_connections.update_one({"_id": connection["_id"]}, {"$set": {"sarvam_org_id": org_id, "sarvam_workspace_id": sarvam_ws}})
    record = await db.sarvam_agent_creations.find_one(query)
    record.update({"sarvam_org_id": org_id, "sarvam_workspace_id": sarvam_ws})
    await db.sarvam_agent_creations.update_one(query, {"$set": {"sarvam_org_id": org_id, "sarvam_workspace_id": sarvam_ws}})
    return await connect_created_agent(db, ws_id, record, supplied_key, body.revision)


async def create_master_agent(db, agent_name, initial_language="English", voice_id=None):
    """Create and commit AREVEI's single master agent in the platform Sarvam account.

    Used once by scripts/setup_sarvam_master_agent.py. Returns the values for backend/.env.
    """
    from managed_voice import MASTER_INTRO, PROFILE_VARIABLES, master_prompt
    inputs = INPUT_VARIABLES + PROFILE_VARIABLES
    body = AgentCreateRequest(creation_key="master-agent", agent_name=agent_name, connection_id="unused",
                              agent_phone_number="+10000000000", initial_language=initial_language,
                              supported_languages=list(SUPPORTED_LANGUAGES), voice_id=voice_id, intro_message=MASTER_INTRO)
    connection = await sarvam_connection(db, PLATFORM_ACCOUNT)
    async with SarvamMcpClient(db, PLATFORM_ACCOUNT, connection) as mcp:
        created = await mcp.tool("configure_agent", {"name": body.agent_name, "config": build_agent_config(body, inputs)})
        app_id = created.get("id") or (created.get("details") or {}).get("app_id")
        if not app_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", str(app_id)):
            raise SarvamBuilderError(502, "provider_unavailable", "Sarvam did not return an agent id")
        await mcp.tool("configure_agent", {"agent_id": app_id, "prompt_append": master_prompt(), "prompt_scope": "state"})
        try:
            await mcp.tool("configure_agent", {"agent_id": app_id, "config": {"llm_config": {"agent_config": {"agent_variables": {"user_name": None}}}}})
        except SarvamBuilderError:
            pass
        check = await mcp.tool("agents", {"operation": "get", "id": app_id, "params": {"include": ["variables", "prompt_text"]}})
        verify_agent(check, inputs)
        commit = await mcp.tool("agents", {"operation": "commit", "id": app_id, "params": {"app_version_description": "AREVEI master voice agent"}})
        versions = await mcp.tool("agents", {"operation": "get", "id": app_id, "params": {"include": ["versions"]}})
    committed = [int(v["app_version"]) for v in versions.get("versions") or [] if v.get("status") == "committed" and isinstance(v.get("app_version"), int)]
    if not committed:
        raise SarvamBuilderError(502, "provider_unavailable", "Sarvam did not report a committed version")
    return {"SARVAM_ORG_ID": commit.get("org_id") or connection.get("sarvam_org_id"),
            "SARVAM_WORKSPACE_ID": commit.get("workspace_id") or connection.get("sarvam_workspace_id"),
            "SARVAM_APP_ID": app_id, "SARVAM_APP_VERSION": max(committed)}


async def workspace_business_name(db, ws_id):
    workspace = await db.workspaces.find_one({"_id": ObjectId(ws_id)}) if ObjectId.is_valid(ws_id) else None
    brain = (workspace or {}).get("brain") or {}
    return (brain.get("business_profile") or {}).get("company_name") or (workspace or {}).get("name") or ""


def verify_agent(check, inputs=None):
    inputs = inputs or INPUT_VARIABLES
    variables = check.get("variables") or {}
    required = [v["name"] for v in inputs]
    from voice_api import SARVAM_QUALIFICATION_OUTPUTS
    required += [item["name"] for item in SARVAM_QUALIFICATION_OUTPUTS]
    missing = [name for name in required if name not in variables]
    if missing:
        raise SarvamBuilderError(502, "configuration_error", "Sarvam agent is missing variables: " + ", ".join(missing))
    for name in (v["name"] for v in inputs):
        if variables[name].get("update_post_interaction"):
            raise SarvamBuilderError(502, "configuration_error", f"{name} must be a call-start input")
    states = ((check.get("prompt_text") or {}).get("states") or {})
    instructions = " ".join(str((state or {}).get("instructions") or "") for state in states.values())
    if "lead_context" not in instructions:
        raise SarvamBuilderError(502, "configuration_error", "Sarvam agent prompt was not written")


async def current_provider(db, ws_id):
    doc = await db.workspace_voice_provider_configs.find_one({"workspace_id": ws_id, "provider": "sarvam"})
    return public_config(doc) if doc else None


async def connect_created_agent(db, ws_id, record, supplied_key="", revision=None):
    """Persist a Sarvam agent that already exists into the workspace's calling configuration."""
    query = {"workspace_id": ws_id, "creation_key": record["creation_key"]}
    if not record.get("app_id") or not record.get("app_version"):
        raise SarvamBuilderError(409, "creation_incomplete", "The agent was not fully created in Sarvam; create it again")
    org_id, sarvam_ws = record.get("sarvam_org_id"), record.get("sarvam_workspace_id")
    existing = await db.workspace_voice_provider_configs.find_one({"workspace_id": ws_id, "provider": "sarvam"})
    old_config = (existing or {}).get("config") or {}
    org_id = org_id or old_config.get("organization_id") or old_config.get("org_id")
    sarvam_ws = sarvam_ws or old_config.get("workspace_id") or old_config.get("sarvam_workspace_id")
    if not org_id or not sarvam_ws:
        await db.sarvam_agent_creations.update_one(query, {"$set": {"status": "created_unsaved", "error_code": "missing_sarvam_ids",
                                                                     "error": "Enter the Sarvam organization and workspace IDs once, then finish connecting", "updated_at": now_iso()}})
        raise SarvamBuilderError(409, "missing_sarvam_ids", "Enter the Sarvam organization and workspace IDs once, then finish connecting")
    has_key = (supplied_key or "api_key" in ((existing or {}).get("configured_secrets") or [])
               or platform_sarvam_key({"organization_id": org_id, "workspace_id": sarvam_ws}))
    if not has_key:
        message = "The agent was created, but this Sarvam account is not AREVEI's. Enter its Voice Agents API key, then use Finish connecting"
        await db.sarvam_agent_creations.update_one(query, {"$set": {"status": "created_unsaved", "error_code": "api_key_required",
                                                                     "error": message, "updated_at": now_iso()}})
        raise SarvamBuilderError(422, "created_unsaved", message)
    config ={"organization_id": org_id, "workspace_id": sarvam_ws, "app_id": record["app_id"], "app_version": int(record["app_version"]),
              "connection_id": record["connection_id"], "agent_phone_number": record["agent_phone_number"], "payload_mode": "lead_context_v1"}
    credentials = {"api_key": supplied_key} if supplied_key else {}
    try:
        saved = await save_config(db, ws_id, "sarvam", True, config, credentials, revision)
        status = await get_provider("sarvam").test_connection(saved["config"], (await load_config(db, ws_id, "sarvam", enabled=False))[1])
        patch = {"status": status, "last_verified_at": now_iso(), "error_code": None if status == "connected" else status}
        await db.workspace_voice_provider_configs.update_one({"workspace_id": ws_id, "provider": "sarvam", "revision": saved["revision"]}, {"$set": patch})
        saved = {**saved, **patch}
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "save_failed", "message": str(exc.detail)}
        await db.sarvam_agent_creations.update_one(query, {"$set": {"status": "created_unsaved", "error_code": detail.get("code"),
                                                                     "error": detail.get("message"), "updated_at": now_iso()}})
        raise SarvamBuilderError(exc.status_code if exc.status_code in (409, 422, 503) else 502, "created_unsaved",
                                 f"The agent exists in Sarvam but could not be connected: {detail.get('message')}. Use Finish connecting.") from None
    await db.workspaces.update_one({"_id": ObjectId(ws_id)}, {"$set": {"qualification_voice_provider": "sarvam", "updated_at": now_iso()}})
    await db.sarvam_agent_creations.update_one(query, {"$set": {"status": "connected", "error": None, "error_code": None, "updated_at": now_iso()}})
    from managed_voice import on_dedicated_connected
    await on_dedicated_connected(db, ws_id)
    logger.info(json.dumps({"event": "sarvam_agent_connected", "workspace_id": ws_id, "creation_key": record["creation_key"],
                            "app_id": record["app_id"], "app_version": int(record["app_version"]), "verification": saved.get("status")}))
    record = await db.sarvam_agent_creations.find_one(query)
    return {"creation": creation_public(record), "provider": {**saved, "is_default": True}, "idempotent": False}


# --------------------------------------------------------------------------- Routes


class SarvamIdsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,160}$")
    workspace_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,160}$")


@router.get("/workspaces/{ws_id}/voice-providers/sarvam/account")
async def get_account(ws_id: str, request: Request):
    await require_workspace_access(request, ws_id)
    doc = await db_from(request).sarvam_account_connections.find_one({"workspace_id": ws_id})
    covered = platform_sarvam_key({"organization_id": (doc or {}).get("sarvam_org_id"), "workspace_id": (doc or {}).get("sarvam_workspace_id")})
    ids_unknown = not ((doc or {}).get("sarvam_org_id") and (doc or {}).get("sarvam_workspace_id"))
    return {**account_public(doc), "platform_key": bool(covered), "platform_key_possible": bool(ids_unknown and platform_sarvam_configured())}


@router.post("/workspaces/{ws_id}/voice-providers/sarvam/account/connect")
async def connect_account(ws_id: str, request: Request):
    user, _ = await require_workspace_access(request, ws_id)
    return {"authorization_url": await begin_connect(db_from(request), ws_id, user)}


@router.delete("/workspaces/{ws_id}/voice-providers/sarvam/account")
async def disconnect_account(ws_id: str, request: Request):
    await require_workspace_access(request, ws_id)
    await disconnect(db_from(request), ws_id)
    return {"status": "disconnected"}


@router.get("/sarvam/oauth/callback")
async def oauth_callback(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = ""):
    """Browser redirect target after Sarvam consent. Authenticated by the single-use state only."""
    origin = os.getenv("FRONTEND_URL", "").strip().rstrip("/") or "*"
    if error or not code or not state:
        message = "Sarvam sign-in was cancelled" if error == "access_denied" else "Sarvam sign-in did not complete"
        return result_page(origin, "SARVAM_CONNECT_FAILED", message, status_code=400)
    try:
        await finish_connect(db_from(request), state, code)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return result_page(origin, "SARVAM_CONNECT_FAILED", detail.get("message", "Sarvam sign-in failed"), status_code=exc.status_code)
    return result_page(origin, "SARVAM_CONNECTED", "Sarvam account connected. You can close this window.")


def result_page(origin, event, message, status_code=200):
    body = f"""<!doctype html><html><head><meta charset="utf-8"><title>Sarvam connection</title></head>
<body style="font-family:sans-serif;padding:24px"><p>{escape(message)}</p>
<script>
try {{ if (window.opener) {{ window.opener.postMessage({{ type: {json.dumps(event)} }}, {json.dumps(origin)}); }} }} catch (e) {{}}
setTimeout(function () {{ window.close(); }}, 800);
</script></body></html>"""
    return HTMLResponse(body, status_code=status_code)


@router.get("/workspaces/{ws_id}/voice-providers/sarvam/account/connections")
async def account_connections(ws_id: str, request: Request):
    await require_workspace_access(request, ws_id)
    return {"connections": await list_connections(db_from(request), ws_id)}


@router.get("/workspaces/{ws_id}/voice-providers/sarvam/account/voices")
async def account_voices(ws_id: str, request: Request, language: str = "English"):
    await require_workspace_access(request, ws_id)
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(422, "Unsupported language")
    return {"voices": await list_voices(db_from(request), ws_id, language)}


@router.post("/workspaces/{ws_id}/voice-providers/sarvam/agents")
async def create_agent_route(ws_id: str, request: Request, body: AgentCreateRequest):
    user, _ = await require_workspace_access(request, ws_id)
    return await create_agent(db_from(request), ws_id, user, body)


@router.get("/workspaces/{ws_id}/voice-providers/sarvam/agents/{creation_key}")
async def creation_status(ws_id: str, creation_key: str, request: Request):
    await require_workspace_access(request, ws_id)
    record = await db_from(request).sarvam_agent_creations.find_one({"workspace_id": ws_id, "creation_key": creation_key})
    if not record:
        raise HTTPException(404, "Agent creation not found")
    return {"creation": creation_public(record)}


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr | None = None
    revision: int | None = None
    organization_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,160}$")
    workspace_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,160}$")


@router.post("/workspaces/{ws_id}/voice-providers/sarvam/agents/{creation_key}/connect")
async def finish_connecting(ws_id: str, creation_key: str, request: Request, body: ConnectRequest):
    """Retry only the AREVEI-side persistence for an agent Sarvam already created."""
    await require_workspace_access(request, ws_id)
    db = db_from(request)
    query = {"workspace_id": ws_id, "creation_key": creation_key}
    record = await db.sarvam_agent_creations.find_one(query)
    if not record:
        raise HTTPException(404, "Agent creation not found")
    if body.organization_id and body.workspace_id:
        await db.sarvam_agent_creations.update_one(query, {"$set": {"sarvam_org_id": body.organization_id, "sarvam_workspace_id": body.workspace_id}})
        record.update({"sarvam_org_id": body.organization_id, "sarvam_workspace_id": body.workspace_id})
    key = body.api_key.get_secret_value().strip() if body.api_key else ""
    return await connect_created_agent(db, ws_id, record, key, body.revision)


async def ensure_indexes(db):
    await db.sarvam_account_connections.create_index("workspace_id", unique=True)
    await db.sarvam_agent_creations.create_index([("workspace_id", 1), ("creation_key", 1)], unique=True)
    await db.sarvam_oauth_clients.create_index("redirect_uri", unique=True)
