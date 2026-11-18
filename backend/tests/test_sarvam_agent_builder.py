"""Automated Sarvam agent creation: OAuth, MCP sequencing, idempotency and persistence.

Uses the isolated real-Mongo helper and a fake Sarvam MCP/OAuth server over httpx MockTransport.
No live Sarvam requests are made.
"""
import asyncio
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from bson import ObjectId
from cryptography.fernet import Fernet
from fastapi import HTTPException

import sarvam_agent_builder as builder
from tests.test_qualification_integration import isolated
from voice_config import decrypt, load_config, save_config

USER = {"_id": ObjectId(), "email": "owner@example.com"}
ALL_VARIABLES = ["lead_name", "lead_phone", "lead_context", "requirement", "product_fit", "budget", "eligibility",
                 "purchase_timeline", "buying_intent", "decision_maker_status", "location", "preferences", "objections",
                 "not_interested", "dnd_requested"]


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("VOICE_CREDENTIAL_KEYS", Fernet.generate_key().decode())
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://crm.example")
    monkeypatch.delenv("SARVAM_OAUTH_REDIRECT_URI", raising=False)
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    builder._metadata_cache.update(value=None, at=0.0)


class FakeSarvam:
    """Minimal stand-in for Sarvam's OAuth server, MCP server and REST analytics probe."""

    def __init__(self):
        self.tool_calls = []
        self.token_requests = []
        self.refresh_counter = 0
        self.tool_error = None
        self.commit_result = {"app_id": "App-1", "app_version": 2, "status": "draft", "org_id": "org-sarvam", "workspace_id": "ws-sarvam", "id": "App-1"}

    def creates(self):
        return [c for c in self.tool_calls if c["name"] == "configure_agent" and "agent_id" not in c["arguments"]]

    def handle(self, request):
        url = str(request.url)
        if url == builder.OAUTH_METADATA_URL:
            return httpx.Response(200, json={"issuer": builder.MCP_URL, "authorization_endpoint": builder.MCP_URL + "/authorize",
                                             "token_endpoint": builder.MCP_URL + "/token", "registration_endpoint": builder.MCP_URL + "/register"})
        if url == builder.MCP_URL + "/register":
            body = json.loads(request.content)
            assert body["token_endpoint_auth_method"] == "none" and body["redirect_uris"] == ["https://crm.example/api/sarvam/oauth/callback"]
            return httpx.Response(201, json={"client_id": "client-1", **body})
        if url == builder.MCP_URL + "/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            if form["grant_type"] == "authorization_code":
                assert form["code_verifier"] and form["client_id"] == "client-1"
                return httpx.Response(200, json={"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 86400, "token_type": "bearer"})
            self.refresh_counter += 1
            return httpx.Response(200, json={"access_token": f"access-{self.refresh_counter + 1}", "refresh_token": f"refresh-{self.refresh_counter + 1}", "expires_in": 86400})
        if url == builder.MCP_URL:
            return self.mcp(request)
        if "apps.sarvam.ai/api/analytics" in url:
            assert request.headers["X-API-Key"] == "rest-key"
            return httpx.Response(200, json={"items": []})
        raise AssertionError("unexpected request " + url)

    def mcp(self, request):
        assert request.headers["Authorization"].startswith("Bearer ")
        if request.headers["Authorization"] == "Bearer stale":
            return httpx.Response(401, json={"error": "invalid_token"})
        message = json.loads(request.content)
        if message["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": "2025-06-18", "capabilities": {}}}, headers={"mcp-session-id": "session-1"})
        if message["method"] == "notifications/initialized":
            return httpx.Response(202)
        assert message["method"] == "tools/call" and request.headers["Mcp-Session-Id"] == "session-1"
        name, arguments = message["params"]["name"], message["params"]["arguments"]
        self.tool_calls.append({"name": name, "arguments": arguments})
        if self.tool_error and name == self.tool_error[0]:
            return self.reply(message, self.tool_error[1], error=True)
        return self.reply(message, self.tool_result(name, arguments))

    def tool_result(self, name, arguments):
        if name == "configure_agent":
            if "agent_id" not in arguments:
                assert "prompt_append" not in arguments and "states" not in json.dumps(arguments["config"])
                return {"id": "App-1", "changed": ["created"], "details": {"app_id": "App-1", "app_version": 1, "status": "draft"}}
            return {"id": "App-1", "changed": ["llm_config.agent_config.states.start.instructions"], "prompt_sha": "abc"}
        if name == "agents":
            operation = arguments["operation"]
            if operation == "get" and "versions" in arguments["params"]["include"]:
                return {"versions": [{"app_version": 1, "status": "committed"}, {"app_version": 2, "status": "draft"}], "id": "App-1"}
            if operation == "get":
                variables = {v: {"name": v, "update_post_interaction": v not in ("lead_name", "lead_phone", "lead_context")} for v in ALL_VARIABLES}
                prompt = {"initial_state_name": "start", "states": {"start": {"instructions": "# ROLE ... lead_context ..."}}}
                return {"variables": variables, "prompt_text": prompt, "id": "App-1"}
            if operation == "commit":
                return self.commit_result
            if operation == "list_voices":
                return {"items": [{"internal_id": "01a0cf16-5db4-7924-a37d-8f3bb1234d7c", "display_name": "Ishita", "gender": "female", "preferred_languages": ["English"]}]}
        if name == "telephony":
            if arguments["operation"] == "list_connections":
                return {"items": [{"connection_id": "conn-1", "name": "Vobiz", "channel_provider": "vobiz", "status": "connection_successful"}]}
            if arguments["operation"] == "get_connection":
                return {"connection": {"connection_id": arguments["id"]}, "endpoints": [{"phone_number": "+917971413693"}]}
        raise AssertionError(f"unexpected tool {name} {arguments}")

    @staticmethod
    def reply(message, payload, error=False):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": {"content": [{"type": "text", "text": text}], "isError": error}})


@pytest.fixture
def sarvam(monkeypatch):
    fake = FakeSarvam()
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(fake.handle), **kw))
    return fake


async def connected_account(db, ws, expires_in=86400, access="access-1"):
    tokens = {"access_token": access, "refresh_token": "refresh-1", "expires_in": expires_in}
    await db.sarvam_account_connections.insert_one({"workspace_id": ws, "status": "connected", "client_id": "client-1", "token_revision": 1,
                                                    "encrypted_tokens": builder.token_envelope(ws, tokens), "connected_at": "2026-11-07T00:00:00+00:00"})


def request_body(**overrides):
    data = {"creation_key": "key-" + ObjectId().__str__(), "agent_name": "Acme Lead Qualifier", "business_name": "Acme", "offer": "Villas",
            "objective": "Book a site visit", "instructions": "Never quote prices.", "connection_id": "conn-1",
            "agent_phone_number": "+917971413693", "initial_language": "English", "supported_languages": ["English", "Hindi"], **overrides}
    return builder.AgentCreateRequest(**data)


def test_create_agent_end_to_end_connects_calling_configuration(sarvam):
    async def run(db):
        ws = str(ObjectId())
        await db.workspaces.insert_one({"_id": ObjectId(ws), "name": "Acme"})
        await connected_account(db, ws)
        body = request_body(api_key="rest-key")
        result = await builder.create_agent(db, ws, USER, body)
        assert result["creation"]["status"] == "connected" and result["creation"]["app_id"] == "App-1" and result["creation"]["app_version"] == 1
        doc, secrets = await load_config(db, ws, "sarvam")
        assert doc["config"] == {"organization_id": "org-sarvam", "workspace_id": "ws-sarvam", "app_id": "App-1", "app_version": 1,
                                 "connection_id": "conn-1", "agent_phone_number": "+917971413693", "payload_mode": "lead_context_v1"}
        assert secrets["api_key"] == "rest-key" and len(secrets["callback_token"]) >= 32
        assert doc["enabled"] and doc["status"] == "connected"
        assert (await db.workspaces.find_one({"_id": ObjectId(ws)}))["qualification_voice_provider"] == "sarvam"
        names = [c["name"] + ":" + (c["arguments"].get("operation") or ("prompt" if "prompt_append" in c["arguments"] else "config")) for c in sarvam.tool_calls]
        assert names.index("configure_agent:config") < names.index("configure_agent:prompt") < names.index("agents:get") < names.index("agents:commit")
        create = sarvam.creates()[0]["arguments"]
        variables = create["config"]["llm_config"]["agent_config"]["agent_variables"]
        assert set(variables) == set(ALL_VARIABLES)
        assert all(not variables[v]["update_post_interaction"] for v in ("lead_name", "lead_phone", "lead_context"))
        assert all(variables[v]["update_post_interaction"] and variables[v]["post_interaction_prompt"] for v in ALL_VARIABLES[3:])
        assert create["config"]["language_config"] == {"initial_language_name": "English", "supported_languages": ["English", "Hindi"]}
        prompt = next(c for c in sarvam.tool_calls if "prompt_append" in c["arguments"])["arguments"]
        assert prompt["prompt_scope"] == "state" and "Never quote prices." in prompt["prompt_append"] and "Acme" in prompt["prompt_append"]
        assert "Configure this Sarvam voice agent" not in prompt["prompt_append"]
        # Secrets never appear in persisted public projections.
        public = json.dumps(result["provider"]) + json.dumps(result["creation"])
        assert "rest-key" not in public and "access-1" not in public and "refresh-1" not in public
    asyncio.run(isolated(run))


def test_same_creation_key_never_creates_a_second_agent(sarvam):
    async def run(db):
        ws = str(ObjectId())
        await db.workspaces.insert_one({"_id": ObjectId(ws), "name": "Acme"})
        await connected_account(db, ws)
        body = request_body(api_key="rest-key")
        first = await builder.create_agent(db, ws, USER, body)
        second = await builder.create_agent(db, ws, USER, body)
        assert second["idempotent"] and second["creation"]["app_id"] == first["creation"]["app_id"]
        assert len(sarvam.creates()) == 1
    asyncio.run(isolated(run))


def test_database_failure_after_sarvam_creation_is_recoverable_without_duplicates(sarvam, monkeypatch):
    async def run(db):
        ws = str(ObjectId())
        await db.workspaces.insert_one({"_id": ObjectId(ws), "name": "Acme"})
        await connected_account(db, ws)
        await save_config(db, ws, "sarvam", False, {}, {"api_key": "rest-key"})
        body = request_body()
        real_save = builder.save_config
        async def broken(*args, **kwargs):
            raise HTTPException(503, "Voice credential encryption is not configured")
        monkeypatch.setattr(builder, "save_config", broken)
        with pytest.raises(HTTPException) as failure:
            await builder.create_agent(db, ws, USER, body)
        assert failure.value.detail["code"] == "created_unsaved"
        record = await db.sarvam_agent_creations.find_one({"workspace_id": ws, "creation_key": body.creation_key})
        assert record["status"] == "created_unsaved" and record["app_id"] == "App-1" and record["app_version"] == 1
        monkeypatch.setattr(builder, "save_config", real_save)
        result = await builder.create_agent(db, ws, USER, body)
        assert result["creation"]["status"] == "connected"
        assert len(sarvam.creates()) == 1
        doc, _ = await load_config(db, ws, "sarvam")
        assert doc["config"]["app_id"] == "App-1" and doc["enabled"]
    asyncio.run(isolated(run))


def test_rest_api_key_is_required_before_anything_is_created(sarvam):
    async def run(db):
        ws = str(ObjectId())
        await connected_account(db, ws)
        with pytest.raises(HTTPException) as failure:
            await builder.create_agent(db, ws, USER, request_body())
        assert failure.value.detail["code"] == "api_key_required"
        assert sarvam.tool_calls == []
        assert await db.sarvam_agent_creations.count_documents({}) == 0
    asyncio.run(isolated(run))


def test_unconnected_account_is_refused_before_any_provider_call(sarvam):
    async def run(db):
        ws = str(ObjectId())
        with pytest.raises(HTTPException) as failure:
            await builder.create_agent(db, ws, USER, request_body(api_key="rest-key"))
        assert failure.value.detail["code"] == "account_not_connected"
        assert sarvam.tool_calls == []
    asyncio.run(isolated(run))


def test_sarvam_validation_error_is_reported_safely_and_allows_retry(sarvam):
    sarvam.tool_error = ("configure_agent", "voice 01a0 is not available see https://agents.sarvam.ai/x?api_key=private-value")
    async def run(db):
        ws = str(ObjectId())
        await connected_account(db, ws)
        body = request_body(api_key="rest-key")
        with pytest.raises(HTTPException) as failure:
            await builder.create_agent(db, ws, USER, body)
        detail = failure.value.detail
        assert detail["code"] == "configuration_error" and "https://" not in detail["message"] and "private-value" not in detail["message"]
        record = await db.sarvam_agent_creations.find_one({"workspace_id": ws, "creation_key": body.creation_key})
        assert record["status"] == "failed" and not record.get("app_id")
        sarvam.tool_error = None
        result = await builder.create_agent(db, ws, USER, body)
        assert result["creation"]["status"] == "connected"
        assert await db.workspace_voice_provider_configs.count_documents({"workspace_id": ws}) == 1
    asyncio.run(isolated(run))


def test_expired_access_token_is_refreshed_and_rotated_token_persisted(sarvam):
    async def run(db):
        ws = str(ObjectId())
        await connected_account(db, ws, expires_in=-10)
        connections = await builder.list_connections(db, ws)
        assert connections == [{"connection_id": "conn-1", "name": "Vobiz", "provider": "vobiz", "status": "connection_successful", "phone_numbers": ["+917971413693"]}]
        assert sarvam.token_requests[-1]["grant_type"] == "refresh_token" and sarvam.token_requests[-1]["refresh_token"] == "refresh-1"
        stored = await db.sarvam_account_connections.find_one({"workspace_id": ws})
        tokens = decrypt(ws, builder.TOKEN_ENVELOPE, stored["encrypted_tokens"])
        assert tokens["refresh_token"] == "refresh-2" and stored["token_revision"] == 2
    asyncio.run(isolated(run))


def test_rejected_bearer_token_triggers_one_refresh_then_retry(sarvam):
    async def run(db):
        ws = str(ObjectId())
        await connected_account(db, ws, access="stale")
        voices = await builder.list_voices(db, ws, "English")
        assert voices[0]["voice_id"] == "01a0cf16-5db4-7924-a37d-8f3bb1234d7c"
        assert sum(1 for r in sarvam.token_requests if r["grant_type"] == "refresh_token") == 1
    asyncio.run(isolated(run))


def test_oauth_connect_round_trip_binds_state_and_stores_tokens_encrypted(sarvam):
    async def run(db):
        ws = str(ObjectId())
        url, mode = await builder.begin_connect(db, ws, USER)
        assert mode == "popup"
        params = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert url.startswith(builder.MCP_URL + "/authorize?") and params["code_challenge_method"] == "S256"
        assert params["redirect_uri"] == "https://crm.example/api/sarvam/oauth/callback" and params["client_id"] == "client-1"
        pending = (await db.sarvam_account_connections.find_one({"workspace_id": ws}))["pending"]
        assert pending["encrypted_verifier"].startswith("gAAAA") and "code_verifier" not in pending
        assert decrypt(ws, builder.TOKEN_ENVELOPE, pending["encrypted_verifier"])["verifier"] not in json.dumps(pending)
        with pytest.raises(HTTPException):
            await builder.finish_connect(db, "wrong-state", "code")
        assert await builder.finish_connect(db, params["state"], "code-1") == ws
        doc = await db.sarvam_account_connections.find_one({"workspace_id": ws})
        assert doc["status"] == "connected" and "pending" not in doc and doc["connected_by_email"] == "owner@example.com"
        assert decrypt(ws, builder.TOKEN_ENVELOPE, doc["encrypted_tokens"])["refresh_token"] == "refresh-1"
        assert "refresh-1" not in json.dumps(builder.account_public(doc))
        with pytest.raises(HTTPException):  # single use
            await builder.finish_connect(db, params["state"], "code-1")
        # Registration is reused, not repeated, for the same callback URL.
        await builder.begin_connect(db, ws, USER)
        assert await db.sarvam_oauth_clients.count_documents({}) == 1
    asyncio.run(isolated(run))


def test_concurrent_creation_with_same_key_is_refused_while_in_progress(sarvam):
    async def run(db):
        ws = str(ObjectId())
        await connected_account(db, ws)
        body = request_body(api_key="rest-key")
        await db.sarvam_agent_creations.insert_one({"workspace_id": ws, "creation_key": body.creation_key, "status": "creating",
                                                    "created_at": builder.now_iso(), "updated_at": builder.now_iso()})
        with pytest.raises(HTTPException) as failure:
            await builder.create_agent(db, ws, USER, body)
        assert failure.value.detail["code"] == "creation_in_progress"
        assert sarvam.tool_calls == []
    asyncio.run(isolated(run))


def test_runtime_prompt_is_shared_with_manual_guide():
    from voice_api import sarvam_runtime_prompt, sarvam_setup_prompt
    runtime = sarvam_runtime_prompt("Acme", "Villas", "Book a visit", "Be brief.")
    assert runtime.startswith("# ROLE") and "Be brief." in runtime
    assert runtime in sarvam_setup_prompt("Acme", "Villas", "Book a visit", "Be brief.")


def test_safe_tool_message_redacts_urls_and_secrets():
    text = builder.safe_tool_message("bad field voice see https://x.example/a?b=c token: abc123 api_key=zzz\n\n more")
    assert "https://" not in text and "abc123" not in text and "zzz" not in text and "bad field voice" in text


def test_env_key_lets_creation_start_before_account_ids_are_known(sarvam, monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "rest-key")
    monkeypatch.setenv("SARVAM_ORG_ID", "org-sarvam")
    monkeypatch.setenv("SARVAM_WORKSPACE_ID", "ws-sarvam")
    async def run(db):
        ws = str(ObjectId())
        await db.workspaces.insert_one({"_id": ObjectId(ws), "name": "Acme"})
        await connected_account(db, ws)
        result = await builder.create_agent(db, ws, USER, request_body())
        assert result["creation"]["status"] == "connected"
        _, secrets = await load_config(db, ws, "sarvam")
        assert secrets["api_key"] == "rest-key"
    asyncio.run(isolated(run))


def test_env_key_for_another_account_keeps_agent_and_asks_for_key(sarvam, monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "platform-key")
    monkeypatch.setenv("SARVAM_ORG_ID", "org-arevei")
    monkeypatch.setenv("SARVAM_WORKSPACE_ID", "ws-arevei")
    async def run(db):
        ws = str(ObjectId())
        await db.workspaces.insert_one({"_id": ObjectId(ws), "name": "Acme"})
        await connected_account(db, ws)
        body = request_body()
        with pytest.raises(HTTPException) as failure:
            await builder.create_agent(db, ws, USER, body)
        assert failure.value.detail["code"] == "created_unsaved"
        record = await db.sarvam_agent_creations.find_one({"workspace_id": ws, "creation_key": body.creation_key})
        assert record["status"] == "created_unsaved" and record["error_code"] == "api_key_required"
        # Now that the account is known not to be AREVEI's, the key is required up front.
        with pytest.raises(HTTPException) as again:
            await builder.create_agent(db, ws, USER, request_body())
        assert again.value.detail["code"] == "api_key_required"
        result = await builder.connect_created_agent(db, ws, record, "rest-key")
        assert result["creation"]["status"] == "connected" and len(sarvam.creates()) == 1
        _, secrets = await load_config(db, ws, "sarvam")
        assert secrets["api_key"] == "rest-key"
    asyncio.run(isolated(run))


def test_paste_sign_in_when_sarvam_refuses_the_https_callback(sarvam):
    """Sarvam registers https callbacks only once allow-listed; loopback always works, and the user pastes the address back."""
    original = sarvam.handle
    registered = []
    def handle(request):
        if str(request.url) == builder.MCP_URL + "/register":
            uri = json.loads(request.content)["redirect_uris"][0]
            registered.append(uri)
            if uri.startswith("https://"):
                return httpx.Response(400, json={"error": "invalid_redirect_uri", "error_description": "not allow-listed"})
            return httpx.Response(201, json={"client_id": "client-1"})
        return original(request)
    sarvam.handle = handle
    async def run(db):
        ws = str(ObjectId())
        url, mode = await builder.begin_connect(db, ws, USER)
        params = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert mode == "paste" and params["redirect_uri"] == builder.PASTE_REDIRECT_URI and params["client_id"] == "client-1"
        # The refusal is remembered: the next click neither re-registers https nor fails.
        url2, mode2 = await builder.begin_connect(db, ws, USER)
        assert mode2 == "paste" and registered.count("https://crm.example/api/sarvam/oauth/callback") == 1
        state = {k: v[0] for k, v in parse_qs(urlsplit(url2).query).items()}["state"]
        with pytest.raises(HTTPException) as junk:
            builder.pasted_callback("https://example.com/not-it")
        assert junk.value.detail["code"] == "invalid_paste"
        code, got_state, error = builder.pasted_callback(f"{builder.PASTE_REDIRECT_URI}?code=code-1&state={state}")
        assert (code, got_state, error) == ("code-1", state, "")
        with pytest.raises(HTTPException):  # another workspace cannot finish this sign-in
            await builder.finish_connect(db, state, code, ws_id=str(ObjectId()))
        assert await builder.finish_connect(db, state, code, ws_id=ws) == ws
        doc = await db.sarvam_account_connections.find_one({"workspace_id": ws})
        assert doc["status"] == "connected" and doc["client_id"] == "client-1"
        # After REDIRECT_RECHECK the https callback is tried again, so allow-listing switches back to the popup flow.
        await db.sarvam_oauth_clients.update_one({"redirect_uri": "https://crm.example/api/sarvam/oauth/callback"},
                                                 {"$set": {"rejected_at": "2020-01-01T00:00:00+00:00"}})
        await builder.begin_connect(db, ws, USER)
        assert registered.count("https://crm.example/api/sarvam/oauth/callback") == 2
    asyncio.run(isolated(run))


def test_account_status_says_when_the_day_long_sign_in_has_ended():
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    fresh = builder.account_public({"status": "connected", "connected_at": now.isoformat(), "session_expires_at": (now + timedelta(hours=23)).isoformat()})
    assert fresh["status"] == "connected" and fresh["expires_at"]
    legacy = builder.account_public({"status": "connected", "connected_at": (now - timedelta(hours=30)).isoformat()})
    assert legacy["status"] == "expired" and legacy["expires_at"] is None
    assert builder.account_public({"status": "connected"})["status"] == "connected"  # nothing to judge by
