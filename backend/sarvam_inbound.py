"""Inbound calls answered by a workspace's own (dedicated) Sarvam agent.

How a call flows:
  1. A Sarvam *deployment* routes the workspace's number to its agent, 24/7. AREVEI creates and keeps it in
     sync through the Sarvam MCP server (``enable_inbound`` / ``sync_after_agent_change``).
  2. When the call starts, an ``on_start`` API tool on the agent asks AREVEI who is calling
     (``POST /api/sarvam/inbound/{ws}/context``) and fills ``lead_name`` / ``lead_context``.
     Outbound calls already carry ``lead_context``; the endpoint echoes it unchanged for them.
  3. When the call ends, the deployment posts a call-end webhook (``POST /api/sarvam/inbound/{ws}/result``).
     It is acknowledged immediately and processed in the background through the same qualification
     pipeline as outbound results.
  4. A sweep re-processes stuck events and reads Sarvam analytics for inbound calls whose webhook never
     arrived (Sarvam does not retry inbound deliveries automatically).

Free-trial (shared master) agents never take inbound calls: one shared number cannot route to many workspaces.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets as secure_random
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from crm import db_from, require_workspace_access
from models import now_iso

router = APIRouter(tags=["sarvam inbound"])
logger = logging.getLogger("voice.sarvam_inbound")

TOKEN_ENVELOPE = "sarvam_inbound"
TOKEN_HEADER = "X-Arevei-Inbound-Token"
TOOL_NAME = "arevei_caller_lookup"
INBOUND_MARKER = "# INBOUND CALLS"
INBOUND_PROMPT = f"""{INBOUND_MARKER}
Outbound calls always supply lead_context. When lead_context starts with "INBOUND CALL" or is empty, the person rang the business:
- Welcome them and thank them for calling. Never say you are calling them, and never offer to call back to start the conversation.
- If lead_name is set, greet them by name and use lead_context; do not ask again for facts it already contains.
- If lead_name is empty, ask for their name early, then ask how you can help, then qualify as usual.
- If they say they enquired before from another number, ask for that number or their email.
- If the call is a wrong number, spam, or someone selling to the business, end it politely without qualifying.
- If lead_context says the person asked not to be called, still help them politely because they called; never push."""
CALLER_NAME_VARIABLE = {
    "name": "caller_name", "value": "", "type": "string", "needs_initial_value": False, "update_post_interaction": True,
    "description": "The caller's name as they stated it",
    "post_interaction_prompt": "From the conversation, determine the caller's name exactly as they stated it. Leave empty when unknown.",
}
MIN_DURATION_SECONDS = 10
MIN_USER_WORDS = 3
MAX_ATTEMPTS = 6
LEASE = timedelta(minutes=5)
SWEEP_EVERY = timedelta(minutes=15)
SWEEP_WINDOW = timedelta(hours=6)
CONTEXT_LIMIT = 4500
UNKNOWN_CALLER = ("INBOUND CALL: a new caller who is not in the CRM rang the business. Welcome them, ask their name, "
                  "ask how you can help, then qualify them.")
NO_NUMBER = ("INBOUND CALL: the caller's number is not available. Welcome them, ask their name and a callback number, "
             "then qualify them.")


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def phone_e164(value):
    from plivo_calls import normalize_lead_phone
    raw = str(value or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.startswith("00") and len(digits) > 10:
        raw = "+" + digits[2:]  # international dialling prefix
    elif not raw.startswith("+") and digits.startswith("0") and len(digits) == 11:
        raw = digits[1:]  # national trunk prefix: 09876543210 -> 9876543210
    phone = normalize_lead_phone(raw)
    return phone if phone.startswith("+") and 8 <= len(phone) <= 16 else ""


def same_phone(a, b):
    a, b = phone_e164(a), phone_e164(b)
    return bool(a) and a == b


# --------------------------------------------------------------------------- Routing table


async def route_for(db, ws_id):
    return await db.sarvam_inbound_routes.find_one({"_id": ws_id})


def route_public(route):
    if not route:
        return {"enabled": False, "status": "off"}
    keys = ("enabled", "status", "agent_phone_number", "deployment_id", "app_version", "caller_lookup", "last_context_at",
            "last_context_caller_seen", "last_call_at", "error", "updated_at")
    return {key: route.get(key) for key in keys}


async def route_token(db, ws_id, route):
    from voice_config import decrypt
    if route and route.get("encrypted_token"):
        try:
            return decrypt(ws_id, TOKEN_ENVELOPE, route["encrypted_token"])["token"]
        except HTTPException:
            pass
    return secure_random.token_urlsafe(32)


async def authenticate(db, ws_id, token):
    if not ObjectId.is_valid(ws_id) or not isinstance(token, str) or not token:
        raise HTTPException(403, "Invalid inbound authentication")
    route = await route_for(db, ws_id)
    if not route or not route.get("token_hash") or not hmac.compare_digest(token_hash(token), route["token_hash"]):
        raise HTTPException(403, "Invalid inbound authentication")
    return route


# --------------------------------------------------------------------------- Sarvam setup (MCP)


def items_of(payload):
    """Sarvam list responses name their list differently; take the first list of objects."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "deployments", "data", "results", "_value"):
        if isinstance(payload.get(key), list):
            return [item for item in payload[key] if isinstance(item, dict)]
    for value in payload.values():
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            return value
    return []


def deployment_numbers(deployment):
    numbers = [n for n in deployment.get("phone_numbers") or [] if isinstance(n, str)]  # list_deployments shape
    for config in deployment.get("connection_configs") or []:  # get_deployment shape
        if isinstance(config, dict):
            numbers += [n for n in config.get("phone_numbers") or [] if isinstance(n, str)]
            if isinstance(config.get("agent_phone_number"), str):
                numbers.append(config["agent_phone_number"])
    return numbers


def entity_id(payload, *keys):
    for source in (payload, payload.get("details") if isinstance(payload, dict) else None, payload.get("deployment") if isinstance(payload, dict) else None):
        if isinstance(source, dict):
            for key in keys:
                if isinstance(source.get(key), str) and source[key]:
                    return source[key]
    return None


async def latest_committed(mcp, app_id):
    versions = await mcp.tool("agents", {"operation": "get", "id": app_id, "params": {"include": ["versions"]}})
    committed = [int(v["app_version"]) for v in versions.get("versions") or [] if v.get("status") == "committed" and isinstance(v.get("app_version"), int)]
    if not committed:
        from sarvam_agent_builder import SarvamBuilderError
        raise SarvamBuilderError(502, "provider_unavailable", "Sarvam did not report a committed version")
    return max(committed)


def lookup_tool_arguments(app_id, ws_id, token, with_caller=True, with_existing=True):
    from voice_config import public_base
    body = {}
    if with_caller:
        body["caller_phone"] = "{{user_identifier}}"
    if with_existing:
        body["existing_name"] = {"type": "agent_variable", "value": {"variable_name": "lead_name"}}
        body["existing_context"] = {"type": "agent_variable", "value": {"variable_name": "lead_context"}}
    return {"agent_id": app_id, "name": TOOL_NAME, "description": "Looks up the caller in AREVEI's CRM before the agent speaks.",
            "url": f"{public_base()}/api/sarvam/inbound/{ws_id}/context", "method": "POST", "lifecycle": "on_start",
            "headers": {TOKEN_HEADER: token}, "body": body, "timeout_seconds": 5,
            "save_to_variables": [{"response_path": "lead_name", "variable_name": "lead_name"},
                                  {"response_path": "lead_context", "variable_name": "lead_context"}]}


async def prepare_agent(mcp, route, app_id, ws_id, token):
    """Add the inbound prompt section, caller-name output and caller lookup once per agent.

    Returns (changed, tool_id, caller_lookup, token). caller_lookup is "auto" when the caller number is bound
    automatically, "manual" when it must be mapped once in the Sarvam console, "off" when no tool exists.
    token is the header token the agent's lookup tool sends; an existing tool keeps its own.
    """
    from sarvam_agent_builder import SarvamBuilderError
    same_agent = route and route.get("app_id") == app_id
    changed = False
    agent = await mcp.tool("agents", {"operation": "get", "id": app_id, "params": {"include": ["variables", "prompt_text", "tools"]}})
    if INBOUND_MARKER not in json.dumps(agent):
        await mcp.tool("configure_agent", {"agent_id": app_id, "prompt_append": INBOUND_PROMPT, "prompt_scope": "state"})
        changed = True
    if "caller_name" not in json.dumps(agent.get("variables") or agent):
        try:
            await mcp.tool("configure_agent", {"agent_id": app_id, "config": {"llm_config": {"agent_config": {"agent_variables": {"caller_name": CALLER_NAME_VARIABLE}}}}})
            changed = True
        except SarvamBuilderError:
            pass  # the name is then read from the transcript summary only
    if same_agent and route.get("context_tool_id") and route.get("caller_lookup") in ("auto", "manual"):
        return changed, route["context_tool_id"], route["caller_lookup"], token
    existing = existing_lookup_tool(agent)
    if existing:  # left behind by an earlier attempt that failed later on: reuse it, never add a second hook
        return changed, *existing
    # Outbound calls also fire on_start hooks. Without the echo of the outbound context the hook would
    # overwrite it, so the tool is only created when that echo can be bound.
    for with_caller, lookup in ((True, "auto"), (False, "manual")):
        try:
            created = await mcp.tool("create_api_tool", lookup_tool_arguments(app_id, ws_id, token, with_caller=with_caller))
        except SarvamBuilderError as exc:
            logger.info(json.dumps({"event": "sarvam_inbound_tool_refused", "workspace_id": ws_id, "caller_binding": with_caller, "code": exc.code}))
            continue
        return True, entity_id(created, "tool_id", "id"), lookup, token
    return changed, None, "off", token


def existing_lookup_tool(agent):
    """(tool_id, caller_lookup, token) of the agent's AREVEI lookup tool, or None."""
    for tool in agent.get("tools") or []:
        if not isinstance(tool, dict) or TOOL_NAME not in (tool.get("name"), tool.get("name_override")):
            continue
        config = tool.get("connector_config") or {}
        token = next((h.get("value") for h in config.get("headers") or [] if isinstance(h, dict) and h.get("name") == TOKEN_HEADER), None)
        if not tool.get("id") or not isinstance(token, str) or not token:
            continue
        fields = {b.get("name") for b in config.get("body") or [] if isinstance(b, dict)}
        return tool["id"], "auto" if "caller_phone" in fields else "manual", token
    return None


def deployment_name(number):
    """Sarvam deployment names allow only letters, digits, underscore, hyphen and spaces (max 50)."""
    return re.sub(r"[^\w\- ]", "", f"AREVEI inbound {number}")[:50].strip()


async def find_conflicts(mcp, number, app_id, own_deployment_id):
    """Deployments in the Sarvam workspace that already answer this number."""
    listed = await mcp.tool("telephony", {"operation": "list_deployments", "fetch_all": True})
    own, others = None, []
    for deployment in items_of(listed):
        if not any(same_phone(n, number) for n in deployment_numbers(deployment)):
            continue
        dep_id = entity_id(deployment, "id", "deployment_id")
        if dep_id == own_deployment_id or (not own and deployment.get("app_id") == app_id):
            own = dep_id
        else:
            others.append(deployment)
    return own, others


async def enable_inbound(db, ws_id, user=None):
    from managed_voice import MASTER, workspace_agent
    from sarvam_agent_builder import SarvamBuilderError, SarvamMcpClient, sarvam_connection
    from voice_config import encrypt, load_config, public_base
    await ensure_indexes(db)  # idempotent; the unique number index must exist before any route is saved
    agent = await workspace_agent(db, ws_id)
    if agent and agent.get("agent_type") == MASTER:
        raise SarvamBuilderError(409, "dedicated_agent_required", "Inbound calls need your own agent. The free-trial agent cannot answer inbound calls.")
    try:
        provider_doc, _ = await load_config(db, ws_id, "sarvam", enabled=False)
    except HTTPException:
        raise SarvamBuilderError(409, "dedicated_agent_required", "Create your own agent first, then turn on inbound calls") from None
    config = provider_doc["config"]
    if not all(config.get(key) for key in ("app_id", "app_version", "connection_id", "agent_phone_number")):
        raise SarvamBuilderError(409, "dedicated_agent_required", "Create your own agent first, then turn on inbound calls")
    number, app_id = config["agent_phone_number"], config["app_id"]
    taken = await db.sarvam_inbound_routes.find_one({"agent_phone_number": number, "_id": {"$ne": ws_id}})
    if taken:
        raise SarvamBuilderError(409, "number_in_use", f"{number} already receives inbound calls for another workspace")
    connection = await sarvam_connection(db, ws_id)
    route = await route_for(db, ws_id) or {}
    token = await route_token(db, ws_id, route)
    now = now_iso()
    await db.sarvam_inbound_routes.update_one({"_id": ws_id}, {"$set": {"workspace_id": ws_id, "status": "setting_up", "error": None, "updated_at": now,
                                                               "encrypted_token": encrypt(ws_id, TOKEN_ENVELOPE, {"token": token})},
                                                               "$setOnInsert": {"created_at": now, "agent_phone_number": number}}, upsert=True)
    try:
        async with SarvamMcpClient(db, ws_id, connection) as mcp:
            own_deployment, others = await find_conflicts(mcp, number, app_id, route.get("deployment_id"))
            if others:
                name = others[0].get("name") or entity_id(others[0], "id", "deployment_id") or "another deployment"
                raise SarvamBuilderError(409, "number_in_use", f"{number} already answers calls for another Sarvam agent ({name}). "
                                         "Remove that deployment in Sarvam or use a different number.")
            old_deployment = route.get("deployment_id")
            if old_deployment and route.get("app_id") and route["app_id"] != app_id:
                # A deployment's agent is fixed: the number moves by deleting the old binding first.
                try:
                    await mcp.tool("telephony", {"operation": "delete_deployment", "id": old_deployment})
                except SarvamBuilderError:
                    pass
                own_deployment = None
            changed, tool_id, lookup, token = await prepare_agent(mcp, route, app_id, ws_id, token)
            if changed:
                await mcp.tool("agents", {"operation": "commit", "id": app_id, "params": {"app_version_description": "Inbound calls set up by AREVEI"}})
            # Always the newest committed version: an earlier attempt may have committed the inbound setup
            # before failing, leaving the saved config on an older version without it.
            version = max(int(config["app_version"]), await latest_committed(mcp, app_id))
            deployment = {"app_version": version, "connection_configs": [{"connection_id": config["connection_id"], "phone_numbers": [number]}],
                          "webhook_config": {"url": f"{public_base()}/api/sarvam/inbound/{ws_id}/result",
                                             "metadata": {"arevei_workspace_id": ws_id, "inbound_token": token}}}
            if own_deployment:
                try:  # Sarvam edits only paused deployments; the resume below follows within a second or two
                    await mcp.tool("telephony", {"operation": "pause_deployment", "id": own_deployment})
                except SarvamBuilderError:
                    pass  # already paused
                await mcp.tool("configure_deployment", {**deployment, "deployment_id": own_deployment})
                try:
                    await mcp.tool("telephony", {"operation": "resume_deployment", "id": own_deployment})
                except SarvamBuilderError:
                    pass  # already active
                deployment_id = own_deployment
            else:  # inbound_config omitted: Sarvam answers 24/7
                created = await mcp.tool("configure_deployment", {**deployment, "name": deployment_name(number), "app_id": app_id})
                deployment_id = entity_id(created, "deployment_id", "id")
                if not deployment_id:
                    raise SarvamBuilderError(502, "provider_unavailable", "Sarvam did not return a deployment id")
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "failed", "message": str(exc.detail)}
        await db.sarvam_inbound_routes.update_one({"_id": ws_id}, {"$set": {"status": "needs_attention", "error": detail.get("message"), "updated_at": now_iso()}})
        raise
    if version != int(config["app_version"]):
        # Outbound calls use the same agent version, which now includes the inbound instructions.
        await db.workspace_voice_provider_configs.update_one({"_id": provider_doc["_id"]}, {"$set": {"config.app_version": version, "updated_at": now_iso()}, "$inc": {"revision": 1}})
    try:
        await db.sarvam_inbound_routes.update_one({"_id": ws_id}, {"$set": {
            "enabled": True, "status": "active", "error": None, "agent_phone_number": number, "connection_id": config["connection_id"],
            "app_id": app_id, "app_version": version, "deployment_id": deployment_id, "organization_id": config.get("organization_id"),
            "sarvam_workspace_id": config.get("workspace_id"), "context_tool_id": tool_id, "caller_lookup": lookup,
            "token_hash": token_hash(token), "encrypted_token": encrypt(ws_id, TOKEN_ENVELOPE, {"token": token}),
            "enabled_by": str(user["_id"]) if user else route.get("enabled_by"), "updated_at": now_iso()}})
    except DuplicateKeyError:
        raise SarvamBuilderError(409, "number_in_use", f"{number} already receives inbound calls for another workspace") from None
    logger.info(json.dumps({"event": "sarvam_inbound_enabled", "workspace_id": ws_id, "app_id": app_id, "app_version": version,
                            "deployment_id": deployment_id, "caller_lookup": lookup}))
    return route_public(await route_for(db, ws_id))


async def disable_inbound(db, ws_id):
    from sarvam_agent_builder import SarvamMcpClient, sarvam_connection
    route = await route_for(db, ws_id)
    if not route:
        return route_public(None)
    if route.get("deployment_id"):
        connection = await sarvam_connection(db, ws_id)
        async with SarvamMcpClient(db, ws_id, connection) as mcp:
            await mcp.tool("telephony", {"operation": "pause_deployment", "id": route["deployment_id"]})
    await db.sarvam_inbound_routes.update_one({"_id": ws_id}, {"$set": {"enabled": False, "status": "paused", "error": None, "updated_at": now_iso()}})
    return route_public(await route_for(db, ws_id))


async def sync_after_agent_change(db, ws_id):
    """Keep the deployment on the workspace's current agent and version. Never raises."""
    route = await route_for(db, ws_id)
    if not route or not route.get("enabled"):
        return
    try:
        doc = await db.workspace_voice_provider_configs.find_one({"workspace_id": ws_id, "provider": "sarvam"})
        config = (doc or {}).get("config") or {}
        if config.get("app_id") == route.get("app_id") and int(config.get("app_version") or 0) == int(route.get("app_version") or 0) \
                and config.get("agent_phone_number") == route.get("agent_phone_number"):
            return
        await enable_inbound(db, ws_id)
    except Exception as exc:  # recorded on the route and shown in Settings
        message = (exc.detail.get("message") if isinstance(getattr(exc, "detail", None), dict) else None) or "Inbound calls could not follow the agent change"
        logger.warning(json.dumps({"event": "sarvam_inbound_sync_failed", "workspace_id": ws_id, "error_type": type(exc).__name__}))
        await db.sarvam_inbound_routes.update_one({"_id": ws_id}, {"$set": {"status": "needs_attention", "error": message, "updated_at": now_iso()}})


# --------------------------------------------------------------------------- Caller recognition


async def leads_for_phone(db, ws_id, phone):
    """Every non-deleted lead in the workspace whose phone matches, most recently active first."""
    from crm import lead_query
    if not phone:
        return []
    last10 = phone[-10:]
    fields = {"field_values": 1, "phone": 1, "status": 1, "customer_status": 1, "updated_at": 1, "created_at": 1}
    matches = []
    async for doc in db.crm_leads.find(lead_query(ws_id), {"field_values.phone": 1, "phone": 1}):
        raw = (doc.get("field_values") or {}).get("phone") or doc.get("phone")
        digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
        if digits.endswith(last10) and same_phone(raw, phone):
            matches.append(doc["_id"])
    if not matches:
        return []
    docs = await db.crm_leads.find({"_id": {"$in": matches}, "workspace_id": ws_id}).to_list(len(matches))
    return sorted(docs, key=lambda d: str(d.get("updated_at") or d.get("created_at") or ""), reverse=True)


def pick_primary(leads):
    """Open leads first, then customers, then anything; each group most recent first."""
    def rank(lead):
        customer = lead.get("customer_status") == "customer" or lead.get("status") == "won"
        closed = lead.get("status") == "lost"
        return 2 if closed else 1 if customer else 0
    return sorted(leads, key=rank)[0] if leads else None


def lead_name(lead):
    values = lead.get("field_values") or {}
    return str(values.get("full_name") or values.get("name") or lead.get("full_name") or "").strip()


async def caller_context(db, ws_id, lead):
    from crm import ensure_crm_settings
    from lead_context import deterministic_lead_context
    from qualification_service import resolve_profile
    workspace = await db.workspaces.find_one({"_id": ObjectId(ws_id)}) or {}
    settings = await ensure_crm_settings(db, ws_id)
    try:
        profile, _ = await resolve_profile(db, ws_id, lead, workspace)
    except HTTPException:
        profile = {}
    customer = lead.get("customer_status") == "customer" or lead.get("status") == "won"
    lines = [f"INBOUND CALL: this person rang the business. They are an existing {'customer' if customer else 'lead'} in the CRM."]
    if lead.get("do_not_call"):
        lines.append("They previously asked not to be called. Help them politely because they called; do not push.")
    summary = (lead.get("communication_summary") or {}).get("latest_summary") or lead.get("conversation_summary")
    if summary:
        lines.append(f"Last conversation: {str(summary)[:600]}")
    facts = {k: v for k, v in (lead.get("qualification_data") or {}).items() if v not in (None, "", [], {}, [""])}
    if facts:
        lines.append("Already known from earlier calls (do not ask again): " + json.dumps(facts, ensure_ascii=False, default=str)[:900])
    text = "\n".join(lines) + "\n" + deterministic_lead_context(lead, profile, settings)
    return text[:CONTEXT_LIMIT]


class ContextRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    caller_phone: str | None = Field(default=None, max_length=64)
    existing_name: str | None = Field(default=None, max_length=500)
    existing_context: str | None = Field(default=None, max_length=20000)


def bound(value):
    """A value Sarvam could not bind arrives as the literal template; treat it as empty."""
    value = (value or "").strip()
    return "" if "{{" in value else value


@router.post("/sarvam/inbound/{ws_id}/context")
async def inbound_context(ws_id: str, request: Request):
    db = db_from(request)
    route = await authenticate(db, ws_id, request.headers.get(TOKEN_HEADER, ""))
    if not route.get("enabled"):
        raise HTTPException(409, "Inbound calls are turned off")
    try:
        body = ContextRequest.model_validate(json.loads((await request.body())[:64_000] or b"{}"))
    except (ValueError, ValidationError):
        body = ContextRequest()
    existing = bound(body.existing_context)
    if existing:  # outbound call: AREVEI already supplied the context, leave it unchanged
        return {"lead_name": bound(body.existing_name), "lead_context": existing, "direction": "outbound"}
    phone = phone_e164(bound(body.caller_phone))
    reply = {"lead_name": "", "lead_context": NO_NUMBER if not phone else UNKNOWN_CALLER, "direction": "inbound", "known": False}
    if phone:
        try:
            lead = pick_primary(await asyncio.wait_for(leads_for_phone(db, ws_id, phone), timeout=3))
            if lead:
                reply.update({"lead_name": lead_name(lead), "lead_context": await asyncio.wait_for(caller_context(db, ws_id, lead), timeout=1.5), "known": True})
        except asyncio.TimeoutError:
            logger.warning(json.dumps({"event": "sarvam_inbound_context_slow", "workspace_id": ws_id}))
    await db.sarvam_inbound_routes.update_one({"_id": ws_id}, {"$set": {"last_context_at": now_iso(), "last_context_caller_seen": bool(phone),
                                                                       "last_context_matched": reply["known"]}})
    return reply


# --------------------------------------------------------------------------- Call-end webhook


class InboundTurn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: str = ""
    en_text: str | None = ""


class InboundPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    app_id: str = Field(min_length=1, max_length=200)
    app_version: int | None = None
    deployment_id: str | None = None
    interaction_id: str = Field(min_length=1, max_length=200)
    user_phone_number: str | None = Field(default=None, max_length=64)
    agent_phone_number: str = Field(min_length=1, max_length=64)
    duration: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    recording_url: str | None = None
    start_datetime: str | None = None
    end_datetime: str | None = None
    final_agent_variables: dict | None = None
    output_agent_variables: dict | None = None
    interaction_transcript: list[InboundTurn] | None = None


def event_key(ws_id, interaction_id):
    return f"{ws_id}:{interaction_id}"


async def record_event(db, ws_id, payload, source):
    """Store an inbound call once per interaction. Returns the event id, or None for a duplicate."""
    key = event_key(ws_id, payload["interaction_id"])
    try:
        await db.sarvam_inbound_events.insert_one({"_id": key, "workspace_id": ws_id, "interaction_id": payload["interaction_id"],
                                                   "payload": payload, "status": "received", "attempts": 0, "source": source,
                                                   "received_at": now_iso()})
    except DuplicateKeyError:
        return None
    await db.sarvam_inbound_routes.update_one({"_id": ws_id}, {"$set": {"last_call_at": now_iso()}})
    return key


@router.post("/sarvam/inbound/{ws_id}/result")
async def inbound_result(ws_id: str, request: Request):
    db = db_from(request)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 1_000_000:
            raise HTTPException(413, "Callback too large")
        chunks.append(chunk)
    try:
        raw = json.loads(b"".join(chunks))
        token = (raw.get("metadata") or {}).get("inbound_token")
    except (ValueError, AttributeError):
        raise HTTPException(403, "Invalid inbound authentication") from None
    route = await authenticate(db, ws_id, token)
    try:
        payload = InboundPayload.model_validate(raw)
    except ValidationError:
        raise HTTPException(422, "Malformed inbound callback") from None
    if payload.app_id != route.get("app_id") or not same_phone(payload.agent_phone_number, route.get("agent_phone_number")):
        raise HTTPException(403, "Callback does not match this workspace's inbound number")
    key = await record_event(db, ws_id, payload.model_dump(mode="json"), "webhook")
    if not key:
        return {"ok": True, "duplicate": True}
    # Acknowledge now: qualification can take longer than Sarvam waits. The sweep retries failures.
    asyncio.create_task(process_event_safely(db, key))
    return {"ok": True}


# --------------------------------------------------------------------------- Processing


def user_words(payload):
    return sum(len((turn.get("en_text") or "").split()) for turn in payload.get("interaction_transcript") or [] if turn.get("role") == "user")


def captured_facts(variables):
    from voice_api import SARVAM_QUALIFICATION_OUTPUTS
    names = [item["name"] for item in SARVAM_QUALIFICATION_OUTPUTS if item["name"] not in ("not_interested", "dnd_requested")]
    return any(str(variables.get(name) or "").strip() not in ("", "false", "False", "null", "None") for name in names)


def fact_text(value):
    if isinstance(value, dict):
        if value.get("value") is not None:
            return " ".join(str(part) for part in (value.get("value"), value.get("currency")) if part)
        bounds = [str(value[k]) for k in ("min", "max") if value.get(k) is not None]
        return (" to ".join(bounds) + (f" {value['currency']}" if value.get("currency") and bounds else "")).strip()
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item not in (None, ""))
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def merged_variables(variables, lead):
    """Newer answers win; earlier answers stay where this call said nothing."""
    from voice_api import SARVAM_QUALIFICATION_OUTPUTS
    merged = dict(variables or {})
    old = lead.get("qualification_data") or {}
    for item in SARVAM_QUALIFICATION_OUTPUTS:
        name = item["name"]
        if name in ("not_interested", "dnd_requested"):
            continue
        if str(merged.get(name) or "").strip() in ("", "null", "None") and old.get(name) not in (None, "", [], {}):
            merged[name] = fact_text(old[name])
    return merged


async def add_note(db, ws_id, lead_id, body, **extra):
    from crm import normalize_lead_note
    note = normalize_lead_note({"body": body, "source": "sarvam_inbound", "author": "Inbound calls"})
    note.update({"created_at": now_iso(), **extra})
    await db.crm_leads.update_one({"_id": ObjectId(lead_id), "workspace_id": ws_id}, {"$addToSet": {"lead_notes": note}, "$set": {"updated_at": now_iso()}})


async def create_caller_lead(db, ws_id, phone, name):
    """One lead per unknown number, even when two calls finish at the same moment."""
    from crm import build_manual_lead, ensure_crm_settings
    claim_id = str(ObjectId())
    claim = await db.sarvam_inbound_callers.find_one_and_update(
        {"_id": f"{ws_id}:{phone}"}, {"$setOnInsert": {"workspace_id": ws_id, "lead_id": claim_id, "created_at": now_iso()}},
        upsert=True, return_document=ReturnDocument.AFTER)
    if claim["lead_id"] != claim_id:
        for _ in range(20):
            if await db.crm_leads.find_one({"_id": ObjectId(claim["lead_id"]), "workspace_id": ws_id}, {"_id": 1}):
                return claim["lead_id"], False
            await asyncio.sleep(0.25)
        raise HTTPException(503, "Lead for this caller is still being created")
    settings = await ensure_crm_settings(db, ws_id)
    values = {"phone": phone, "source": "sarvam_inbound"}
    if name:
        values["full_name"] = name[:120]
    try:
        doc = build_manual_lead(ws_id, {"field_values": values, "trigger_ai_call": False}, settings)
    except HTTPException:
        doc = build_manual_lead(ws_id, {"field_values": {"phone": phone}, "trigger_ai_call": False}, settings)
    doc.update({"_id": ObjectId(claim_id), "sheet_row_key": f"manual:{claim_id}", "source": "sarvam_inbound",
                "timeline": [{"type": "created", "label": "Lead created from an inbound call", "created_at": now_iso()}]})
    await db.crm_leads.insert_one(doc)
    return claim_id, True


def callback_shape(payload, variables):
    """The outbound result shape the shared Sarvam normalizer and qualification pipeline accept."""
    raw = {"attempt_id": payload["interaction_id"], "status": "connected", "interaction_id": payload["interaction_id"],
           "channel_info": {"channel_type": "telephony", "channel_provider": "sarvam", "agent_phone_number": phone_e164(payload["agent_phone_number"])},
           "duration": payload.get("duration") or 0, "final_agent_variables": variables,
           "interaction_transcript": [{"role": t.get("role") or "", "en_text": t.get("en_text") or ""} for t in payload.get("interaction_transcript") or []]}
    url = payload.get("recording_url") or ""
    parsed = urlsplit(url)
    if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
        raw["_arevei_recording_url"] = url
    return raw


async def process_event(db, key):
    now = datetime.now(timezone.utc)
    event = await db.sarvam_inbound_events.find_one_and_update(
        {"_id": key, "status": {"$in": ["received", "failed"]}, "attempts": {"$lt": MAX_ATTEMPTS},
         "$or": [{"lease_until": {"$exists": False}}, {"lease_until": {"$lt": now.isoformat()}}]},
        {"$set": {"status": "processing", "lease_until": (now + LEASE).isoformat()}, "$inc": {"attempts": 1}},
        return_document=ReturnDocument.AFTER)
    if not event:
        return None
    ws_id, payload = event["workspace_id"], event["payload"]
    try:
        outcome = await handle_call(db, ws_id, payload)
    except Exception as exc:
        status = "failed" if event["attempts"] < MAX_ATTEMPTS else "gave_up"
        await db.sarvam_inbound_events.update_one({"_id": key}, {"$set": {"status": status, "error_type": type(exc).__name__, "updated_at": now_iso()}, "$unset": {"lease_until": ""}})
        logger.warning(json.dumps({"event": "sarvam_inbound_failed", "workspace_id": ws_id, "status": status, "error_type": type(exc).__name__}))
        raise
    await db.sarvam_inbound_events.update_one({"_id": key}, {"$set": {**outcome, "processed_at": now_iso()}, "$unset": {"lease_until": ""}})
    logger.info(json.dumps({"event": "sarvam_inbound_processed", "workspace_id": ws_id, "status": outcome["status"], "created_lead": outcome.get("created_lead", False)}))
    return outcome


async def process_event_safely(db, key):
    try:
        await process_event(db, key)
    except Exception:
        pass  # recorded on the event; the sweep retries it


async def handle_call(db, ws_id, payload):
    from qualification_service import QualificationWebhookController
    phone = phone_e164(payload.get("user_phone_number"))
    variables = dict(payload.get("final_agent_variables") or {})
    variables.update({k: v for k, v in (payload.get("output_agent_variables") or {}).items() if v not in (None, "")})
    leads = await leads_for_phone(db, ws_id, phone)
    lead = pick_primary(leads)
    words, duration = user_words(payload), float(payload.get("duration") or 0)
    if words == 0 or (duration < MIN_DURATION_SECONDS and words < MIN_USER_WORDS):
        if lead:
            await add_note(db, ws_id, str(lead["_id"]), f"Short inbound call ({int(duration)}s) with no conversation.", call_id=payload["interaction_id"])
        return {"status": "ignored", "reason": "short_or_silent", "lead_id": str(lead["_id"]) if lead else None}
    created = False
    if not lead:
        if not captured_facts(variables) and str(variables.get("not_interested") or "").lower() != "true":
            return {"status": "ignored", "reason": "no_enquiry"}  # wrong number, spam or a pitch: no lead
        lead_id, created = await create_caller_lead(db, ws_id, phone, str(variables.get("caller_name") or "").strip()) if phone else (None, False)
        if not lead_id:
            return {"status": "ignored", "reason": "no_caller_number"}
        lead = await db.crm_leads.find_one({"_id": ObjectId(lead_id), "workspace_id": ws_id})
    lead_id = str(lead["_id"])
    q = lead.get("qualification_call") or {}
    called_back = q.get("status") in ("scheduled", "no_answer", "busy", "failed")
    if q.get("status") == "scheduled":  # they called first: drop the pending retry
        await db.crm_leads.update_one({"_id": lead["_id"]}, {"$set": {"qualification_call.status": "superseded_by_inbound"}, "$unset": {"qualification_call.scheduled_for": ""}})
    await db.plivo_call_sessions.update_one(
        {"workspace_id": ws_id, "provider": "sarvam", "provider_identifiers.call_uuid": payload["interaction_id"]},
        {"$setOnInsert": {"workspace_id": ws_id, "lead_id": lead_id, "provider": "sarvam", "direction": "inbound", "status": "in_progress",
                          "provider_identifiers": {"call_uuid": payload["interaction_id"], "interaction_id": payload["interaction_id"]},
                          "caller_phone": phone, "agent_phone_number": payload.get("agent_phone_number"),
                          "started_at": payload.get("start_datetime") or now_iso(), "created_at": now_iso()}}, upsert=True)
    result = await QualificationWebhookController(db).process(ws_id, lead_id, callback_shape(payload, merged_variables(variables, lead)), provider="sarvam")
    notes = ["Inbound call answered by the AI agent."]
    if created:
        notes.append("New lead created from this call.")
    if called_back:
        notes.append("The lead called back after an earlier outbound call.")
    others = [str(other["_id"]) for other in leads if other["_id"] != lead["_id"]]
    if others:
        notes.append(f"Possible duplicate: {len(others)} other lead(s) have this phone number.")
        await db.crm_leads.update_many({"_id": {"$in": [ObjectId(o) for o in others]}, "workspace_id": ws_id}, {"$set": {"possible_duplicate_of": lead_id}})
    updates = {"last_inbound_call_at": now_iso()}
    if lead.get("customer_status") == "customer" or lead.get("status") == "won":
        updates["last_customer_call_at"] = now_iso()
    await db.crm_leads.update_one({"_id": lead["_id"]}, {"$set": updates})
    await add_note(db, ws_id, lead_id, " ".join(notes), call_id=payload["interaction_id"], call_direction="inbound")
    return {"status": "processed", "lead_id": lead_id, "created_lead": created, "qualification_status": result.get("status")}


# --------------------------------------------------------------------------- Reconciliation sweep


def analytics_payload(item, route):
    """Map an analytics interaction to the webhook payload shape. Returns None when it cannot be used."""
    interaction = item.get("interaction_id") or item.get("id")
    if not isinstance(interaction, str) or not interaction:
        return None
    transcript = []
    for turn in item.get("translate_transcript") or item.get("original_transcript") or item.get("transcript") or []:
        if isinstance(turn, dict):
            role = str(turn.get("role") or turn.get("speaker") or "").lower()
            text = turn.get("en_text") or turn.get("text") or turn.get("content") or ""
            transcript.append({"role": "user" if role in ("user", "customer", "caller") else "agent", "en_text": str(text)})
    return {"app_id": route["app_id"], "app_version": item.get("app_version"), "deployment_id": item.get("deployment_id"),
            "interaction_id": interaction, "user_phone_number": item.get("user_contact") or item.get("user_contact_identifier"),
            "agent_phone_number": item.get("bot_contact_identifier") or route["agent_phone_number"],
            "duration": item.get("duration_in_seconds") or item.get("duration") or 0, "recording_url": item.get("audio_url"),
            "start_datetime": item.get("start_datetime"), "end_datetime": item.get("end_datetime"),
            "final_agent_variables": item.get("agent_variables") or {}, "output_agent_variables": None,
            "interaction_transcript": transcript}


async def fetch_missed(db, route):
    from voice_config import load_config
    ws_id = route["_id"]
    doc, secrets = await load_config(db, ws_id, "sarvam", enabled=False)
    config = doc["config"]
    if not secrets.get("api_key"):
        return 0
    now = datetime.now(timezone.utc)
    url = f"https://apps.sarvam.ai/api/analytics/v1/{config['organization_id']}/{config['workspace_id']}/{route['app_id']}/interactions"
    params = {"start_datetime": (now - SWEEP_WINDOW).isoformat(), "end_datetime": now.isoformat(), "limit": 200, "include_transcript": "true",
              "filter_conditions": json.dumps([{"id": "direction", "field": "channel_direction", "operator": "equals", "value": "inbound"}])}
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        response = await client.get(url, headers={"X-API-Key": secrets["api_key"]}, params=params)
    if response.status_code != 200:
        logger.warning(json.dumps({"event": "sarvam_inbound_sweep_unavailable", "workspace_id": ws_id, "status": response.status_code}))
        return 0
    found = 0
    for item in response.json().get("items") or []:
        if not isinstance(item, dict) or str(item.get("channel_direction") or "inbound").lower() != "inbound":
            continue
        if route.get("deployment_id") and item.get("deployment_id") and item["deployment_id"] != route["deployment_id"]:
            continue
        payload = analytics_payload(item, route)
        if payload and await record_event(db, ws_id, payload, "sweep"):
            found += 1
    return found


async def sweep(db):
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(minutes=2)).isoformat()
    async for event in db.sarvam_inbound_events.find({"status": {"$in": ["received", "failed"]}, "attempts": {"$lt": MAX_ATTEMPTS}, "received_at": {"$lt": stale}}, {"_id": 1}).limit(50):
        await process_event_safely(db, event["_id"])
    async for route in db.sarvam_inbound_routes.find({"enabled": True, "$or": [{"last_sweep_at": {"$exists": False}}, {"last_sweep_at": {"$lt": (now - SWEEP_EVERY).isoformat()}}]}).limit(20):
        await db.sarvam_inbound_routes.update_one({"_id": route["_id"]}, {"$set": {"last_sweep_at": now.isoformat()}})
        try:
            if await fetch_missed(db, route):
                async for event in db.sarvam_inbound_events.find({"workspace_id": route["_id"], "status": "received", "source": "sweep"}, {"_id": 1}).limit(50):
                    await process_event_safely(db, event["_id"])
        except Exception as exc:
            logger.warning(json.dumps({"event": "sarvam_inbound_sweep_failed", "workspace_id": route["_id"], "error_type": type(exc).__name__}))
        await sync_after_agent_change(db, route["_id"])


async def sweep_loop(db):
    await asyncio.sleep(30)
    while True:
        try:
            await sweep(db)
        except Exception:
            logger.exception("sarvam inbound sweep tick failed")
        await asyncio.sleep(300)


# --------------------------------------------------------------------------- Settings API


@router.get("/workspaces/{ws_id}/voice-providers/sarvam/inbound")
async def get_inbound(ws_id: str, request: Request):
    await require_workspace_access(request, ws_id)
    return route_public(await route_for(db_from(request), ws_id))


@router.post("/workspaces/{ws_id}/voice-providers/sarvam/inbound/enable")
async def post_enable(ws_id: str, request: Request):
    user, _ = await require_workspace_access(request, ws_id)
    return await enable_inbound(db_from(request), ws_id, user)


@router.post("/workspaces/{ws_id}/voice-providers/sarvam/inbound/disable")
async def post_disable(ws_id: str, request: Request):
    await require_workspace_access(request, ws_id)
    return await disable_inbound(db_from(request), ws_id)


async def ensure_indexes(db):
    await db.sarvam_inbound_routes.create_index("agent_phone_number", unique=True)
    await db.sarvam_inbound_events.create_index([("status", 1), ("received_at", 1)])
    await db.sarvam_inbound_events.create_index([("workspace_id", 1), ("received_at", -1)])
