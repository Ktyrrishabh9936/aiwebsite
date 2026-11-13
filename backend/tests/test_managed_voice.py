"""Unified AI Voice Agent: master-agent trial and dedicated Sarvam agents on one calling path."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from bson import ObjectId
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException

import managed_voice as mv
import sarvam_agent_builder as builder
from tests.test_qualification_integration import isolated, seed
from tests.test_sarvam_agent_builder import FakeSarvam, connected_account
from voice_config import decrypt, load_config, save_config
from voice_providers import SarvamVoiceProvider, callback_proof, get_provider

PLATFORM = {"SARVAM_API_KEY": "platform-key", "SARVAM_ORG_ID": "org-master", "SARVAM_WORKSPACE_ID": "sws-master",
            "SARVAM_APP_ID": "Master-1", "SARVAM_APP_VERSION": "3", "SARVAM_CONNECTION_ID": "conn-master",
            "SARVAM_AGENT_PHONE_NUMBER": "+917971413693"}
OWN = {"organization_id": "org-own", "workspace_id": "sws-own", "app_id": "Own-1", "app_version": 5,
       "connection_id": "conn-own", "agent_phone_number": "+14155550123", "payload_mode": "lead_context_v1"}
USER = {"_id": ObjectId(), "email": "owner@example.com"}
PROFILE = {"agent_name": "Priya", "business_name": "Acme Homes", "business_details": "Villas in Pune.", "behaviour": "Ask budget first."}


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("VOICE_CREDENTIAL_KEYS", Fernet.generate_key().decode())
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://crm.example")
    monkeypatch.delenv("SARVAM_OAUTH_REDIRECT_URI", raising=False)
    for key, value in PLATFORM.items():
        monkeypatch.setenv(key, value)
    builder._metadata_cache.update(value=None, at=0.0)


async def new_workspace(db):
    ws = str(ObjectId())
    await db.workspaces.insert_one({"_id": ObjectId(ws), "name": "Acme", "user_id": USER["_id"]})
    return ws


async def expire_trial(db, ws):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    await db.workspace_voice_agents.update_one({"workspace_id": ws}, {"$set": {"trial_expires_at": past.isoformat()}})


def test_managed_config_requires_every_platform_value(monkeypatch):
    assert mv.managed_config()["app_version"] == 3
    monkeypatch.delenv("SARVAM_APP_ID")
    assert mv.managed_config() is None
    monkeypatch.setenv("SARVAM_APP_ID", "Master-1")
    monkeypatch.setenv("SARVAM_APP_VERSION", "latest")
    assert mv.managed_config() is None


def test_trial_activates_once_and_editing_never_extends_it():
    async def run(db):
        await mv.ensure_indexes(db)  # created by migrate_runtime.py in deployments
        ws = await new_workspace(db)
        state = await mv.voice_agent_state(db, ws)
        assert state["active_type"] is None and state["trial"]["status"] == "available" and state["trial"]["days"] == 14
        await mv.activate_trial(db, ws, USER, PROFILE)
        doc = await mv.workspace_agent(db, ws)
        started, expires = doc["trial_started_at"], doc["trial_expires_at"]
        assert datetime.fromisoformat(expires) - datetime.fromisoformat(started) == timedelta(days=14)
        state = await mv.voice_agent_state(db, ws)
        assert state["active_type"] == "master" and state["calling_enabled"] and state["trial"]["status"] == "active"
        assert state["trial"]["days_left"] == 14 and state["profile"]["agent_name"] == "Priya"
        with pytest.raises(HTTPException) as again:
            await mv.activate_trial(db, ws, USER, PROFILE)
        assert again.value.status_code == 409
        await mv.upsert_agent(db, ws, {**PROFILE, "behaviour": "Be brief."}, USER)
        doc = await mv.workspace_agent(db, ws)
        assert (doc["trial_started_at"], doc["trial_expires_at"]) == (started, expires) and doc["behaviour"] == "Be brief."
        # No secret or provider identifier reaches the browser.
        assert "platform-key" not in json.dumps(state) and "Master-1" not in json.dumps(state)
        # Concurrent activation of a fresh workspace starts exactly one trial.
        other = await new_workspace(db)
        results = await asyncio.gather(*[mv.activate_trial(db, other, USER, PROFILE) for _ in range(3)], return_exceptions=True)
        assert sum(r is None for r in results) == 1
    asyncio.run(isolated(run))


def test_trial_is_unavailable_without_master_configuration(monkeypatch):
    async def run(db):
        monkeypatch.delenv("SARVAM_APP_ID")
        ws = await new_workspace(db)
        assert (await mv.voice_agent_state(db, ws))["trial"]["status"] == "unavailable"
        with pytest.raises(HTTPException):
            await mv.activate_trial(db, ws, USER, PROFILE)
        assert await mv.workspace_agent(db, ws) is None
    asyncio.run(isolated(run))


def test_master_trial_call_end_to_end_uses_platform_account_and_workspace_context(monkeypatch):
    from tests.test_qualification_engine import full_data
    from voice_api import router
    import qualification_service
    from qualification_engine import validated_facts

    async def extract(call, *args):
        return validated_facts(call.extracted_data), 100, "Qualified"
    monkeypatch.setattr(qualification_service, "extract_facts", extract)

    async def run(db):
        ws, lead_id, profile_id = await seed(db)
        await db.crm_leads.update_one({"_id": ObjectId(lead_id)}, {"$set": {"field_values.full_name": "Asha", "field_values.requirements": "3BHK villa"}})
        await mv.activate_trial(db, ws, USER, PROFILE)
        from plivo_calls import start_qualification_call
        initiate = AsyncMock(return_value=httpx.Response(200, json={"attempt_id": "attempt-1"}))
        monkeypatch.setattr(SarvamVoiceProvider, "initiate_call", initiate)
        recording = AsyncMock(return_value="https://media.example/call.wav")
        monkeypatch.setattr(SarvamVoiceProvider, "recording", recording)
        result = await start_qualification_call(db, ws, lead_id, None)
        assert result["provider"] == "sarvam" and result.get("agent_display_name", "Priya") == "Priya"
        _, sent_config, payload = initiate.await_args.args
        assert sent_config["credentials"]["api_key"] == "platform-key" and sent_config["organization_id"] == "org-master"
        assert payload["app_config"]["app_id"] == "Master-1" and payload["app_config"]["app_version"] == 3
        assert payload["app_config"]["connection_config"] == {"connection_id": "conn-master", "agent_phone_number": "+917971413693"}
        variables = payload["app_config"]["agent_variables"]
        assert variables["agent_name"] == "Priya" and variables["business_name"] == "Acme Homes"
        assert "Villas in Pune." in variables["agent_brief"] and "Ask budget first." in variables["agent_brief"]
        assert variables["lead_name"] == "Asha" and "3BHK villa" in variables["lead_context"]
        session = await db.plivo_call_sessions.find_one({"_id": ObjectId(result["session_id"])})
        assert session["agent_snapshot"]["voice_agent_type"] == "master"
        assert "platform-key" not in json.dumps(session, default=str)
        # The existing callback, qualification and recording path completes the call.
        _, secrets = await load_config(db, ws, "sarvam", enabled=False)
        proof = callback_proof(secrets["callback_token"], ws, result["session_id"])
        app = FastAPI(); app.state.db = db; app.include_router(router, prefix="/api")
        body = {"attempt_id": "attempt-1", "status": "connected", "final_agent_variables": full_data(), "interaction_id": "interaction-1",
                "channel_info": {"channel_type": "telephony", "channel_provider": "sarvam", "agent_phone_number": "+917971413693"},
                "webhook_config": {"metadata": {"callback_proof": proof, "arevei_workspace_id": ws, "lead_id": lead_id,
                                                "qualification_session_id": result["session_id"]}}}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://crm.example") as client:
            response = await client.post(f"/api/sarvam/workspaces/{ws}/calls/{result['session_id']}/result", json=body)
        assert response.status_code == 200, response.text
        account, account_secrets = recording.await_args.args[0], recording.await_args.args[1]
        assert account["organization_id"] == "org-master" and account_secrets == {"api_key": "platform-key"}
        lead = await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
        assert lead["qualification_call"]["recording_url"] == "https://media.example/call.wav"
        assert await db.crm_call_logs.count_documents({"kind": "qualification_engine"}) == 1
    asyncio.run(isolated(run))


def test_paused_or_expired_trial_never_places_calls():
    async def run(db):
        ws = await new_workspace(db)
        await mv.activate_trial(db, ws, USER, PROFILE)
        assert (await get_provider("sarvam").configuration(db, ws))["voice_agent_type"] == "master"
        await mv.upsert_agent(db, ws, {"enabled": False})
        with pytest.raises(HTTPException, match="paused"):
            await get_provider("sarvam").configuration(db, ws)
        await mv.upsert_agent(db, ws, {"enabled": True})
        await expire_trial(db, ws)
        with pytest.raises(HTTPException, match="trial has ended"):
            await get_provider("sarvam").configuration(db, ws)
        assert (await mv.voice_agent_state(db, ws))["trial"]["status"] == "expired"
        with pytest.raises(HTTPException):
            await mv.switch_agent(db, ws, USER, "master")
        # Configuration and profile are preserved after expiry.
        assert (await mv.workspace_agent(db, ws))["business_details"] == "Villas in Pune."
    asyncio.run(isolated(run))


def test_switching_preserves_both_configurations_and_only_selected_agent_calls():
    async def run(db):
        ws = await new_workspace(db)
        await mv.activate_trial(db, ws, USER, PROFILE)
        with pytest.raises(HTTPException, match="own agent first"):
            await mv.switch_agent(db, ws, USER, "dedicated")
        # A dedicated agent connected while the trial is active does not take over silently.
        await save_config(db, ws, "sarvam", True, OWN, {"api_key": "own-key"})
        await mv.on_dedicated_connected(db, ws)
        assert (await mv.voice_agent_state(db, ws))["active_type"] == "master"
        assert (await get_provider("sarvam").configuration(db, ws))["app_id"] == "Master-1"
        await mv.switch_agent(db, ws, USER, "dedicated")
        config = await get_provider("sarvam").configuration(db, ws)
        assert config["app_id"] == "Own-1" and config["credentials"]["api_key"] == "own-key" and config["voice_agent_type"] == "dedicated"
        await mv.switch_agent(db, ws, USER, "master")
        assert (await get_provider("sarvam").configuration(db, ws))["credentials"]["api_key"] == "platform-key"
        doc, secrets = await load_config(db, ws, "sarvam", enabled=False)
        assert doc["config"]["app_id"] == "Own-1" and secrets["api_key"] == "own-key"
        assert (await mv.workspace_agent(db, ws))["agent_name"] == "Priya"
        # Trial expiry never affects a dedicated agent.
        await mv.switch_agent(db, ws, USER, "dedicated")
        await expire_trial(db, ws)
        assert (await get_provider("sarvam").configuration(db, ws))["app_id"] == "Own-1"
    asyncio.run(isolated(run))


def test_existing_dedicated_workspace_is_unchanged_and_selected_after_creation():
    async def run(db):
        legacy = await new_workspace(db)
        await save_config(db, legacy, "sarvam", True, OWN, {"api_key": "own-key"})
        assert await mv.workspace_calling_agent(db, legacy) is None  # legacy routing untouched
        state = await mv.voice_agent_state(db, legacy)
        assert state["active_type"] == "dedicated" and state["dedicated"]["configured"] and state["calling_enabled"]
        assert "own-key" not in json.dumps(state)
        fresh = await new_workspace(db)
        await save_config(db, fresh, "sarvam", True, OWN, {"api_key": "own-key"})
        await mv.on_dedicated_connected(db, fresh)
        assert (await mv.workspace_agent(db, fresh))["agent_type"] == "dedicated"
        await mv.upsert_agent(db, fresh, {"enabled": False})
        with pytest.raises(HTTPException, match="paused"):
            await get_provider("sarvam").configuration(db, fresh)
    asyncio.run(isolated(run))


def test_recording_account_follows_the_agent_that_placed_the_call():
    async def run(db):
        ws = await new_workspace(db)
        await save_config(db, ws, "sarvam", True, OWN, {"api_key": "own-key"})
        account, secrets = await mv.call_account(db, ws, {"agent_snapshot": {"voice_agent_type": "master"}})
        assert account["organization_id"] == "org-master" and secrets == {"api_key": "platform-key"}
        account, secrets = await mv.call_account(db, ws, {"agent_snapshot": {}})
        assert account["organization_id"] == "org-own" and secrets["api_key"] == "own-key"
    asyncio.run(isolated(run))


def test_master_agent_is_created_with_profile_inputs(monkeypatch):
    fake = FakeSarvam()
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(fake.handle), **kw))
    original = fake.tool_result

    def tool_result(name, arguments):
        result = original(name, arguments)
        if name == "agents" and arguments["operation"] == "get" and "variables" in result:
            for item in mv.PROFILE_VARIABLES:
                result["variables"][item["name"]] = {"name": item["name"], "update_post_interaction": False}
        return result
    fake.tool_result = tool_result

    async def run(db):
        await connected_account(db, builder.PLATFORM_ACCOUNT)
        ids = await builder.create_master_agent(db, "AREVEI Voice Agent", "Hindi")
        assert ids == {"SARVAM_ORG_ID": "org-sarvam", "SARVAM_WORKSPACE_ID": "ws-sarvam", "SARVAM_APP_ID": "App-1", "SARVAM_APP_VERSION": 1}
        create = fake.creates()[0]["arguments"]
        variables = create["config"]["llm_config"]["agent_config"]["agent_variables"]
        assert {"agent_name", "business_name", "agent_brief", "lead_context"} <= set(variables)
        assert create["config"]["intro_message_config"]["audio"] == mv.MASTER_INTRO
        prompt = next(c for c in fake.tool_calls if "prompt_append" in c["arguments"])["arguments"]["prompt_append"]
        assert "agent_brief" in prompt and "Never mention Sarvam" in prompt
        # The platform sign-in is separate from every workspace's own Sarvam account.
        assert await db.sarvam_agent_creations.count_documents({}) == 0
    asyncio.run(isolated(run))


def test_dedicated_creation_through_builder_selects_it_for_a_new_workspace(monkeypatch):
    fake = FakeSarvam()
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(fake.handle), **kw))

    async def run(db):
        ws = await new_workspace(db)
        await connected_account(db, ws)
        body = builder.AgentCreateRequest(creation_key="key-" + str(ObjectId()), agent_name="Acme Qualifier", connection_id="conn-1",
                                          agent_phone_number="+917971413693", api_key="rest-key")
        await builder.create_agent(db, ws, USER, body)
        state = await mv.voice_agent_state(db, ws)
        assert state["active_type"] == "dedicated" and state["dedicated"]["agent_name"] == "Acme Qualifier"
        assert state["dedicated"]["status"] == "connected"
        doc, _ = await load_config(db, ws, "sarvam")
        assert "api_key" in decrypt(ws, "sarvam", doc["encrypted_credentials"])
    asyncio.run(isolated(run))


def test_env_key_applies_only_to_agents_in_arevei_sarvam_workspace(monkeypatch):
    async def run(db):
        own_ws = await new_workspace(db)
        await save_config(db, own_ws, "sarvam", True, OWN, {"api_key": "customer-key"})
        arevei_ws = await new_workspace(db)
        in_arevei = {**OWN, "organization_id": "org-master", "workspace_id": "sws-master"}
        await save_config(db, arevei_ws, "sarvam", True, in_arevei, {"api_key": "stale-or-wrong"})
        # A customer's own Sarvam account never receives AREVEI's key.
        assert (await load_config(db, own_ws, "sarvam"))[1]["api_key"] == "customer-key"
        # An agent in AREVEI's workspace always uses the .env key, even over a saved one.
        assert (await load_config(db, arevei_ws, "sarvam"))[1]["api_key"] == "platform-key"
        keyless = await new_workspace(db)
        await save_config(db, keyless, "sarvam", True, in_arevei, {})
        assert (await mv.dedicated_state(db, keyless))["configured"]
        assert (await get_provider("sarvam").configuration(db, keyless))["credentials"]["api_key"] == "platform-key"
        monkeypatch.delenv("SARVAM_WORKSPACE_ID")
        assert (await load_config(db, arevei_ws, "sarvam"))[1]["api_key"] == "stale-or-wrong"
    asyncio.run(isolated(run))
