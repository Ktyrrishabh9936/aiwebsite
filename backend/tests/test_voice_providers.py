import asyncio
import hashlib
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from bson import ObjectId
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException

from qualification_engine import QualificationProfile
from voice_config import encrypt, decrypt, load_config, public_config, public_base, regenerate_sarvam_callback_secret, safe_config, save_config
from voice_providers import get_provider, SarvamVoiceProvider, PlivoVoiceProvider, callback_proof


def sarvam_channel():
    return {"channel_type": "telephony", "channel_provider": "sarvam", "agent_phone_number": "+14155550123"}


@pytest.fixture(autouse=True)
def encryption(monkeypatch):
    monkeypatch.setenv("VOICE_CREDENTIAL_KEYS", Fernet.generate_key().decode())
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://crm.example")


@pytest.mark.parametrize("provider", ["plivo", "sarvam"])
def test_cipher_binds_workspace_and_provider(provider):
    token = encrypt("A", provider, {"api_key": "private-value"})
    assert "private-value" not in token
    assert decrypt("A", provider, token)["api_key"] == "private-value"
    with pytest.raises(HTTPException):
        decrypt("B", provider, token)
    with pytest.raises(HTTPException):
        decrypt("A", "sarvam" if provider == "plivo" else "plivo", token)


def test_key_rotation(monkeypatch):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv("VOICE_CREDENTIAL_KEYS", old)
    token = encrypt("A", "plivo", {"auth_token": "private"})
    monkeypatch.setenv("VOICE_CREDENTIAL_KEYS", f"{new},{old}")
    rotated = encrypt("A", "plivo", decrypt("A", "plivo", token))
    monkeypatch.setenv("VOICE_CREDENTIAL_KEYS", new)
    assert decrypt("A", "plivo", rotated)["auth_token"] == "private"


@pytest.mark.parametrize("provider", ["plivo", "sarvam"])
def test_resolution_is_scoped_and_disabled_fails(provider):
    async def run():
        db = AsyncMock()
        db.workspace_voice_provider_configs.find_one.return_value = None
        with pytest.raises(HTTPException):
            await load_config(db, "B", provider)
        db.workspace_voice_provider_configs.find_one.assert_awaited_with({"workspace_id": "B", "provider": provider})
        db.workspace_voice_provider_configs.find_one.return_value = {"enabled": False}
        with pytest.raises(HTTPException, match="disabled"):
            await load_config(db, "B", provider)
    asyncio.run(run())


@pytest.mark.parametrize("status,expected", [("connected", "completed"), ("no_answer", "no_answer"), ("busy", "busy"), ("failed", "failed")])
def test_sarvam_normalization(status, expected):
    call = SarvamVoiceProvider().normalize({"attempt_id": "attempt-1", "status": status, "duration": None,
        "channel_info": sarvam_channel(), "final_agent_variables": {"qualification_score": 100, "buying_intent": "high"},
        "interaction_transcript": None}, "lead")
    assert call.provider == "sarvam"
    assert call.call_status == expected
    assert "qualification_score" not in call.extracted_data
    assert call.terminal


@pytest.mark.parametrize("payload", [{}, {"attempt_id": "a", "status": "surprise", "channel_info": {}},
    {"attempt_id": "a", "status": "connected", "channel_info": {}, "interaction_transcript": "wrong"}])
def test_malformed_callback(payload):
    with pytest.raises(HTTPException):
        SarvamVoiceProvider().normalize(payload, "lead")


def test_provider_choice_is_separate_from_model():
    assert QualificationProfile().voice_provider == "plivo"
    assert isinstance(get_provider(QualificationProfile(voice_provider="sarvam").voice_provider), SarvamVoiceProvider)
    assert isinstance(get_provider("plivo"), PlivoVoiceProvider)


@pytest.mark.parametrize("code,state", [(200, "connected"), (401, "invalid_credentials"), (403, "invalid_credentials"), (422, "configuration_error"), (503, "provider_unavailable")])
def test_connection_calls_provider(code, state, monkeypatch):
    provider = SarvamVoiceProvider()
    provider.probe = AsyncMock(return_value=httpx.Response(code))
    config = dict.fromkeys(provider.required_config, "value")
    result = asyncio.run(provider.test_connection(config, {"api_key": "private", "callback_token": "private"}))
    assert result == state
    provider.probe.assert_awaited_once()


def test_safe_configuration_and_public_response():
    doc = {"provider": "sarvam", "encrypted_credentials": "private", "credentials": {"api_key": "private"}, "configured_secrets": ["api_key"]}
    assert "private" not in json.dumps(public_config(doc))
    with pytest.raises(HTTPException):
        safe_config("plivo", {"trigger_url": "https://localhost/steal"})
    with pytest.raises(HTTPException):
        safe_config("plivo", {"extra_payload": {"api_key": "private"}})
    assert public_base() == "https://crm.example"


def test_legacy_sarvam_names_are_read_as_canonical_fields():
    assert safe_config("sarvam", {"org_id": "org", "sarvam_workspace_id": "sws", "app_id": "app", "app_version": "1",
        "connection_id": "connection", "from_number": "+14155550123"}) == {
            "organization_id": "org", "workspace_id": "sws", "app_id": "app", "app_version": 1,
            "connection_id": "connection", "agent_phone_number": "+14155550123"}


def test_sarvam_callback_secret_is_generated_encrypted_and_regenerated():
    from tests.test_qualification_integration import isolated, seed
    async def run(db):
        ws, _, _ = await seed(db)
        config = {"organization_id": "org", "workspace_id": "sws", "app_id": "app", "app_version": 1,
            "connection_id": "connection", "agent_phone_number": "+14155550123"}
        public = await save_config(db, ws, "sarvam", True, config, {"api_key": "private"})
        assert public["callback_security_configured"] is True
        assert public["configured_secrets"] == ["api_key"]
        assert "callback_token" not in json.dumps(public)
        doc, credentials = await load_config(db, ws, "sarvam")
        original = credentials["callback_token"]
        assert len(original) >= 32
        assert original not in doc["encrypted_credentials"]
        regenerated = await regenerate_sarvam_callback_secret(db, ws, public["revision"])
        _, credentials = await load_config(db, ws, "sarvam")
        assert credentials["callback_token"] != original
        assert regenerated["callback_security_configured"] is True
        assert "callback_token" not in json.dumps(regenerated)
        with pytest.raises(HTTPException, match="managed automatically"):
            await save_config(db, ws, "sarvam", True, config, {"callback_token": "customer-value"}, regenerated["revision"])
    asyncio.run(isolated(run))


def test_sarvam_transport_contract():
    provider = SarvamVoiceProvider()
    cfg = {"organization_id": "org", "workspace_id": "sws", "app_id": "app", "app_version": 3,
        "connection_id": "connection", "agent_phone_number": "+14155550123",
        "credentials": {"api_key": "private", "callback_token": "callback-private"}}
    base = {"workspace_id": "ws", "lead_id": "lead", "qualification_profile": QualificationProfile(voice_provider="sarvam").model_dump(),
        "customer_name": "Lead", "previous_answers": {}, "pending_discussion": [], "to_number": "+14155550124"}
    payload = provider.build_payload(base, cfg, "session")
    assert payload["app_config"]["app_id"] == "app"
    assert payload["app_config"]["app_version"] == 3
    assert payload["app_config"]["connection_config"] == {"connection_id": "connection", "agent_phone_number": "+14155550123"}
    assert payload["app_config"]["agent_variables"]["qualification_profile"]["voice_provider"] == "sarvam"
    assert payload["user_config"]["user_phone_number"] == base["to_number"]
    assert payload["webhook_config"]["url"] == "https://crm.example/api/sarvam/workspaces/ws/calls/session/result"
    assert payload["webhook_config"]["metadata"] | {"callback_proof": "ignored"} == {
        "callback_proof": "ignored", "arevei_workspace_id": "ws", "lead_id": "lead", "qualification_session_id": "session"}
    assert "private" not in json.dumps(payload)
    assert provider.transport(cfg)[0] == "https://apps.sarvam.ai/api/outbounds/v1/orgs/org/workspaces/sws/outbounds"
    assert provider.transport(cfg)[1] == {"X-API-Key": "private"}


def test_sarvam_instant_outbound_http_request_uses_one_lead():
    provider = SarvamVoiceProvider()
    config = {"organization_id": "org-1", "workspace_id": "sarvam-ws", "credentials": {"api_key": "workspace-key"}}
    payload = {"app_config": {"app_id": "app-1", "app_version": 7,
        "connection_config": {"connection_id": "connection-1", "agent_phone_number": "+14155550123"}},
        "user_config": {"user_phone_number": "+14155550124"}}
    def handle(request):
        assert request.method == "POST"
        assert str(request.url) == "https://apps.sarvam.ai/api/outbounds/v1/orgs/org-1/workspaces/sarvam-ws/outbounds"
        assert request.headers["X-API-Key"] == "workspace-key"
        assert json.loads(request.content) == payload
        assert "campaign" not in request.url.path and "bulk" not in request.url.path
        return httpx.Response(200, json={"attempt_id": "attempt-1"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            response = await provider.initiate_call(client, config, payload)
        assert provider.identifiers(response.json())["attempt_id"] == "attempt-1"
    asyncio.run(run())


@pytest.mark.parametrize("returned_id,code,expected", [("call", 200, "https://media.example/recording.wav"), ("other", 200, None), ("call", 503, None)])
def test_recording_fetch_checks_attempt_and_handles_unavailable(monkeypatch, returned_id, code, expected):
    real_client = httpx.AsyncClient
    def handle(request):
        assert request.headers["X-API-Key"] == "tenant-key"
        assert '/org/tenant/app/attempts' in request.url.path
        assert json.loads(request.url.params["filter_conditions"])[0]["value"] == "call"
        return httpx.Response(code, json={"items": [{"attempt_id": returned_id, "audio_url": "https://media.example/recording.wav"}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw))
    result = asyncio.run(SarvamVoiceProvider().recording({"organization_id": "org", "workspace_id": "tenant", "app_id": "app"}, {"api_key": "tenant-key"}, "call", None))
    assert result == expected


def test_workspace_migration_is_idempotent_and_encrypts_legacy_credentials():
    from tests.test_qualification_integration import isolated, seed
    from migrate_voice_providers import migrate
    async def run(db):
        ws, _, _ = await seed(db)
        other = str(ObjectId())
        await db.plivo_agent_configs.insert_one({"workspace_id": ws, "enabled": True, "is_default": True,
            "trigger_url": "https://agentflow.plivo.com/v1/account/account/flow/flow", "from_number": "+14155550123",
            "auth_type": "basic", "credentials": {"username": "account", "password": "private"}})
        await db.plivo_agent_configs.insert_one({"workspace_id": other, "credentials": {"password": "other-private"}})
        await db.plivo_call_sessions.insert_one({"workspace_id": ws, "request_payload": {"result_url": "https://crm.example/result?token=old-private"}})
        await migrate(db, ws)
        await migrate(db, ws)
        historical = await db.plivo_call_sessions.find_one({"workspace_id": ws})
        assert "old-private" not in json.dumps(historical, default=str)
        assert await db.workspace_voice_provider_configs.count_documents({}) == 1
        doc, secrets = await load_config(db, ws, "plivo")
        assert secrets["auth_token"] == "private"
        assert "private" not in json.dumps(doc, default=str)
        agent = await db.plivo_agent_configs.find_one({"workspace_id": ws})
        assert "credentials" not in agent
        assert decrypt(ws, "plivo", agent["encrypted_credentials"])["password"] == "private"
        assert (await db.plivo_agent_configs.find_one({"workspace_id": other}))["credentials"]["password"] == "other-private"
    asyncio.run(isolated(run))


def test_sarvam_end_to_end_workspace_isolation_and_replay(monkeypatch):
    from tests.test_qualification_integration import isolated, seed
    from tests.test_qualification_engine import full_data
    from voice_api import router
    import qualification_service
    from qualification_engine import validated_facts
    async def extract(call, *args):
        return validated_facts(call.extracted_data), 100, "Qualified"
    monkeypatch.setattr(qualification_service, "extract_facts", extract)
    async def run(db):
        ws, lead_id, profile_id = await seed(db)
        await db.qualification_profiles.update_one({"_id": ObjectId(profile_id)}, {"$set": {"voice_provider": "sarvam"}})
        config = {"organization_id": "org", "workspace_id": "sws", "app_id": "app", "app_version": 2,
            "connection_id": "connection", "agent_phone_number": "+14155550123"}
        saved = await save_config(db, ws, "sarvam", True, config, {"api_key": "private"})
        _, generated_credentials = await load_config(db, ws, "sarvam")
        from plivo_calls import start_qualification_call
        adapter = SarvamVoiceProvider
        initiate = AsyncMock(return_value=httpx.Response(200, json={"attempt_id": "attempt-1"}))
        monkeypatch.setattr(adapter, "initiate_call", initiate)
        monkeypatch.setattr(adapter, "recording", AsyncMock(return_value="https://media.example/call.wav"))
        # Local transport failures create audit sessions, but Sarvam never accepted a call.
        # They must not consume qualification attempts.
        for index in range(2):
            await db.plivo_call_sessions.insert_one({"workspace_id": ws, "lead_id": lead_id,
                "provider": "sarvam", "status": "failed", "last_error": "Provider unavailable",
                "created_at": f"2026-09-20T08:2{index}:00+00:00"})
        result = await start_qualification_call(db, ws, lead_id, None)
        assert result["provider"] == "sarvam"
        _, sent_config, sent_payload = initiate.await_args.args
        assert sent_config["credentials"]["api_key"] == "private"
        assert sent_config["workspace_id"] == "sws"
        assert sent_payload["app_config"]["app_id"] == "app"
        assert sent_payload["app_config"]["app_version"] == 2
        assert sent_payload["app_config"]["connection_config"] == {"connection_id": "connection", "agent_phone_number": "+14155550123"}
        assert sent_payload["user_config"]["user_phone_number"] == "+14155550123"
        session_id = result["session_id"]
        session = await db.plivo_call_sessions.find_one({"_id": ObjectId(session_id)})
        assert session["provider_call_id"] == "attempt-1"
        assert session["provider_identifiers"]["attempt_id"] == "attempt-1"
        assert "private" not in json.dumps(session, default=str)
        proof = callback_proof(generated_credentials["callback_token"], ws, session_id)
        # Rotation after initiation must not strand the session's frozen capability.
        await regenerate_sarvam_callback_secret(db, ws, saved["revision"])
        _, saved_secrets = await load_config(db, ws, "sarvam", enabled=False)
        assert saved_secrets["api_key"] == "private"
        assert saved_secrets["callback_token"] != generated_credentials["callback_token"]
        app = FastAPI(); app.state.db = db; app.include_router(router, prefix="/api")
        payload = {"attempt_id": "attempt-1", "status": "connected", "channel_info": sarvam_channel(),
            "final_agent_variables": full_data(), "interaction_id": "interaction-1", "webhook_config": {"metadata": {
                "callback_proof": proof, "arevei_workspace_id": ws, "lead_id": lead_id, "qualification_session_id": session_id}}}
        url = f"/api/sarvam/workspaces/{ws}/calls/{session_id}/result"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://crm.example") as client:
            assert (await client.post(url.replace(ws, str(ObjectId())), json=payload)).status_code == 404
            assert (await client.post(url, json={**payload, "webhook_config": {}})).status_code == 403
            assert (await client.post(url, json={**payload, "attempt_id": "other-call"})).status_code == 403
            wrong_context = {**payload, "webhook_config": {"metadata": {**payload["webhook_config"]["metadata"], "lead_id": str(ObjectId())}}}
            assert (await client.post(url, json=wrong_context)).status_code == 403
            first = await client.post(url, json=payload)
            assert first.status_code == 200, first.text
            second = await client.post(url, json=payload)
            assert second.json()["duplicate"] is True
        assert await db.tasks.count_documents({"action_type": "SALES_CALL"}) == 1
        lead = await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
        assert lead["qualification_call"]["provider"] == "sarvam"
        assert lead["qualification_call"]["recording_url"] == "https://media.example/call.wav"
        assert lead["call_attempt_count"] == 1
        assert len([n for n in lead["lead_notes"] if n["author"] == "Qualification Engine"]) == 1
        assert await db.crm_call_logs.count_documents({"kind": "qualification_engine"}) == 1
        events = await db.plivo_call_events.find({}).to_list(10)
        assert proof not in json.dumps(events, default=str)
    asyncio.run(isolated(run))
