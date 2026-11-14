"""Inbound calls for a dedicated Sarvam agent: setup through MCP, caller recognition and call-end processing.

Uses the isolated real-Mongo helper, a fake Sarvam MCP server and an in-process ASGI app. No live calls.
"""
import asyncio
import json

import httpx
import pytest
from bson import ObjectId
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException

import llm_service  # noqa: F401  loads backend/.env with override at import; must happen before fixtures set test keys
import qualification_service
import sarvam_agent_builder as builder
import sarvam_inbound as inbound
from qualification_engine import validated_facts
from tests.test_qualification_integration import isolated, seed
from tests.test_sarvam_agent_builder import FakeSarvam, USER, connected_account, request_body
from voice_config import load_config

NUMBER = "+917971413693"
CALLER = "+14155550123"


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("VOICE_CREDENTIAL_KEYS", Fernet.generate_key().decode())
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://crm.example")
    monkeypatch.delenv("SARVAM_OAUTH_REDIRECT_URI", raising=False)
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    builder._metadata_cache.update(value=None, at=0.0)

    async def extract(call, *args):
        return validated_facts(call.extracted_data), 100, "Inbound summary"
    monkeypatch.setattr(qualification_service, "extract_facts", extract)


class FakeInboundSarvam(FakeSarvam):
    def __init__(self):
        super().__init__()
        self.deployments = []
        self.committed = 1
        self.refuse_tools = 0

    def tool_result(self, name, arguments):
        if name == "configure_agent" and "agent_id" in arguments:
            return {"id": "App-1", "changed": ["ok"]}
        if name == "create_api_tool":
            return {"tool_id": "tool-1", "call_reference": "call tool:arevei_caller_lookup"}
        if name == "agents" and arguments["operation"] == "commit" and self.deployments is not None and any(c["name"] == "create_api_tool" for c in self.tool_calls):
            self.committed += 1
            return {"app_id": "App-1", "app_version": self.committed, "org_id": "org-sarvam", "workspace_id": "ws-sarvam"}
        if name == "agents" and arguments["operation"] == "get" and "versions" in arguments["params"]["include"]:
            return {"versions": [{"app_version": v, "status": "committed"} for v in range(1, self.committed + 1)], "id": "App-1"}
        if name == "telephony" and arguments["operation"] == "list_deployments":
            return {"items": self.deployments}
        if name == "telephony" and arguments["operation"] in ("pause_deployment", "resume_deployment", "delete_deployment"):
            return {"ok": True}
        if name == "configure_deployment":
            return {"deployment_id": arguments.get("deployment_id") or "dep-1", "status": "active"}
        return super().tool_result(name, arguments)

    def mcp(self, request):
        message = json.loads(request.content)
        if message.get("method") == "tools/call" and message["params"]["name"] == "create_api_tool" and self.refuse_tools:
            self.tool_calls.append({"name": "create_api_tool", "arguments": message["params"]["arguments"]})
            self.refuse_tools -= 1
            return self.reply(message, "variable user_identifier is not defined", error=True)
        return super().mcp(request)


@pytest.fixture
def sarvam(monkeypatch):
    fake = FakeInboundSarvam()
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(fake.handle), **kw))
    return fake, real


async def dedicated_workspace(db):
    ws = str(ObjectId())
    await db.workspaces.insert_one({"_id": ObjectId(ws), "name": "Ayurooms"})
    await connected_account(db, ws)
    await builder.create_agent(db, ws, USER, request_body(api_key="rest-key"))
    return ws


def calls(fake, name):
    return [c["arguments"] for c in fake.tool_calls if c["name"] == name]


def test_enable_sets_up_lookup_tool_and_24x7_deployment(sarvam):
    fake, _ = sarvam
    async def run(db):
        ws = await dedicated_workspace(db)
        result = await inbound.enable_inbound(db, ws, USER)
        assert result["enabled"] and result["status"] == "active" and result["agent_phone_number"] == NUMBER
        assert result["caller_lookup"] == "auto" and result["deployment_id"] == "dep-1"
        tool = calls(fake, "create_api_tool")[0]
        assert tool["lifecycle"] == "on_start" and tool["url"] == f"https://crm.example/api/sarvam/inbound/{ws}/context"
        assert tool["body"]["caller_phone"] == "{{user_identifier}}" and tool["body"]["existing_context"]["value"]["variable_name"] == "lead_context"
        token = tool["headers"][inbound.TOKEN_HEADER]
        deployment = calls(fake, "configure_deployment")[0]
        assert "inbound_config" not in deployment  # 24/7
        assert deployment["connection_configs"] == [{"connection_id": "conn-1", "phone_numbers": [NUMBER]}]
        assert deployment["webhook_config"] == {"url": f"https://crm.example/api/sarvam/inbound/{ws}/result",
                                                "metadata": {"arevei_workspace_id": ws, "inbound_token": token}}
        assert deployment["app_version"] == 2 and deployment["app_id"] == "App-1"
        assert any(inbound.INBOUND_MARKER in (c.get("prompt_append") or "") for c in calls(fake, "configure_agent"))
        doc, _ = await load_config(db, ws, "sarvam")
        assert doc["config"]["app_version"] == 2  # outbound uses the same version
        # Enabling again patches the same deployment instead of creating a second one.
        fake.deployments = [{"id": "dep-1", "app_id": "App-1", "connection_configs": [{"connection_id": "conn-1", "phone_numbers": [NUMBER]}]}]
        await inbound.enable_inbound(db, ws, USER)
        assert calls(fake, "configure_deployment")[-1]["deployment_id"] == "dep-1"
        assert len(calls(fake, "create_api_tool")) == 1
    asyncio.run(isolated(run))


def test_caller_binding_falls_back_to_manual_mapping(sarvam):
    fake, _ = sarvam
    fake.refuse_tools = 1
    async def run(db):
        ws = await dedicated_workspace(db)
        result = await inbound.enable_inbound(db, ws, USER)
        assert result["caller_lookup"] == "manual"
        assert "caller_phone" not in calls(fake, "create_api_tool")[-1]["body"]
    asyncio.run(isolated(run))


def test_number_answered_by_another_agent_is_refused(sarvam):
    fake, _ = sarvam
    fake.deployments = [{"id": "dep-x", "name": "AI Manager line", "app_id": "Other-App", "connection_configs": [{"connection_id": "conn-1", "phone_numbers": ["917971413693"]}]}]
    async def run(db):
        ws = await dedicated_workspace(db)
        with pytest.raises(HTTPException) as failure:
            await inbound.enable_inbound(db, ws, USER)
        assert failure.value.detail["code"] == "number_in_use" and "AI Manager line" in failure.value.detail["message"]
        assert calls(fake, "configure_deployment") == []
        assert (await inbound.route_for(db, ws))["status"] == "needs_attention"
    asyncio.run(isolated(run))


def test_free_trial_agent_cannot_take_inbound_calls(sarvam):
    async def run(db):
        ws = str(ObjectId())
        await db.workspace_voice_agents.insert_one({"workspace_id": ws, "agent_type": "master", "enabled": True})
        with pytest.raises(HTTPException) as failure:
            await inbound.enable_inbound(db, ws, USER)
        assert failure.value.detail["code"] == "dedicated_agent_required"
    asyncio.run(isolated(run))


def test_same_number_cannot_serve_two_workspaces(sarvam):
    async def run(db):
        ws = await dedicated_workspace(db)
        await db.sarvam_inbound_routes.insert_one({"_id": str(ObjectId()), "agent_phone_number": NUMBER, "enabled": True})
        with pytest.raises(HTTPException) as failure:
            await inbound.enable_inbound(db, ws, USER)
        assert failure.value.detail["code"] == "number_in_use"
    asyncio.run(isolated(run))


# --------------------------------------------------------------------------- calls


TOKEN = "inbound-secret-token-value"


async def active_route(db, ws):
    await db.sarvam_inbound_routes.insert_one({"_id": ws, "workspace_id": ws, "enabled": True, "status": "active", "app_id": "App-1",
                                               "agent_phone_number": NUMBER, "token_hash": inbound.token_hash(TOKEN)})


def payload(interaction="int-1", caller=CALLER, duration=95, user_text="I want a five day wellness retreat next month", variables=None, **extra):
    data = {"app_id": "App-1", "app_version": 2, "deployment_id": "dep-1", "interaction_id": interaction,
            "user_phone_number": caller, "agent_phone_number": NUMBER, "duration": duration,
            "recording_url": "https://media.example/in.wav", "final_agent_variables": variables if variables is not None else {"requirement": "Five day wellness retreat"},
            "interaction_transcript": [{"role": "agent", "en_text": "Thanks for calling."}, {"role": "user", "en_text": user_text}],
            "metadata": {"inbound_token": TOKEN}}
    data.update(extra)
    return data


def asgi(db):
    app = FastAPI()
    app.state.db = db
    app.include_router(inbound.router, prefix="/api")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def wait_processed(db, ws, interaction):
    for _ in range(100):
        event = await db.sarvam_inbound_events.find_one({"_id": inbound.event_key(ws, interaction)})
        if event and event["status"] not in ("received", "processing"):
            return event
        await asyncio.sleep(0.1)
    raise AssertionError("event not processed")


def test_known_lead_call_is_authenticated_processed_merged_and_deduplicated():
    async def run(db):
        ws, lead_id, _ = await seed(db)
        await active_route(db, ws)
        await db.crm_leads.update_one({"_id": ObjectId(lead_id)}, {"$set": {"qualification_data": {"location": "Pune", "budget": {"value": 275.0, "currency": "USD"}},
                                                                             "qualification_call": {"status": "scheduled", "scheduled_for": "2030-01-01T00:00:00+00:00", "call_uuid": "old"}}})
        async with asgi(db) as client:
            assert (await client.post(f"/api/sarvam/inbound/{ws}/result", json={**payload(), "metadata": {"inbound_token": "wrong"}})).status_code == 403
            assert (await client.post(f"/api/sarvam/inbound/{ws}/result", json={**payload(), "app_id": "Other"})).status_code == 403
            response = await client.post(f"/api/sarvam/inbound/{ws}/result", json=payload())
            assert response.status_code == 200 and response.json() == {"ok": True}
            event = await wait_processed(db, ws, "int-1")
            assert event["status"] == "processed" and event["lead_id"] == lead_id and not event["created_lead"]
            again = await client.post(f"/api/sarvam/inbound/{ws}/result", json=payload())
            assert again.json()["duplicate"] is True
        lead = await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
        data = lead["qualification_data"]
        assert "wellness" in data["requirement"].lower() and data["location"] == "Pune" and data["budget"]["value"] == 275.0
        assert lead["qualification_call"]["status"] != "scheduled" and lead["qualification_call"]["call_uuid"] == "int-1"
        assert lead["qualification_call"]["recording_url"] == "https://media.example/in.wav"
        notes = " ".join(n["body"] for n in lead["lead_notes"])
        assert "Inbound call answered" in notes and "called back" in notes
        assert await db.crm_leads.count_documents({"workspace_id": ws}) == 1
        session = await db.plivo_call_sessions.find_one({"provider_identifiers.call_uuid": "int-1"})
        assert session["direction"] == "inbound" and session["lead_id"] == lead_id
    asyncio.run(isolated(run))


def test_unknown_caller_becomes_one_lead_even_for_simultaneous_calls():
    async def run(db):
        ws, _, _ = await seed(db)
        await active_route(db, ws)
        first = payload("int-a", caller="+919876543210", variables={"requirement": "Detox retreat", "caller_name": "Asha"})
        second = payload("int-b", caller="09876543210", variables={"requirement": "Detox retreat for two"})
        for item in (first, second):
            await inbound.record_event(db, ws, inbound.InboundPayload.model_validate(item).model_dump(mode="json"), "webhook")
        results = await asyncio.gather(inbound.process_event(db, inbound.event_key(ws, "int-a")),
                                       inbound.process_event(db, inbound.event_key(ws, "int-b")), return_exceptions=True)
        for _ in range(3):  # a call blocked by the other call's lock is retried, as the sweep would
            for key in ("int-a", "int-b"):
                event = await db.sarvam_inbound_events.find_one({"_id": inbound.event_key(ws, key)})
                if event["status"] == "failed":
                    await db.sarvam_inbound_events.update_one({"_id": event["_id"]}, {"$unset": {"lease_until": ""}})
                    try:
                        await inbound.process_event(db, event["_id"])
                    except HTTPException:
                        pass
        leads = await db.crm_leads.find({"workspace_id": ws, "source": "sarvam_inbound"}).to_list(10)
        assert len(leads) == 1, results
        assert leads[0]["field_values"]["phone"] == "+919876543210" and leads[0]["field_values"].get("full_name") == "Asha"
        statuses = {e["_id"]: e["status"] for e in await db.sarvam_inbound_events.find({"workspace_id": ws}).to_list(10)}
        assert set(statuses.values()) == {"processed"}
    asyncio.run(isolated(run))


def test_short_silent_and_no_enquiry_calls_create_no_lead():
    async def run(db):
        ws, lead_id, _ = await seed(db)
        await active_route(db, ws)
        cases = [payload("short", caller="+919000000001", duration=4, user_text="hello"),
                 payload("silent", caller="+919000000002", user_text=""),
                 payload("spam", caller="+919000000003", user_text="I am calling to sell you advertising space", variables={}),
                 payload("known-short", caller=CALLER, duration=3, user_text="hi")]
        for item in cases:
            key = await inbound.record_event(db, ws, inbound.InboundPayload.model_validate(item).model_dump(mode="json"), "webhook")
            await inbound.process_event(db, key)
        events = {e["interaction_id"]: e for e in await db.sarvam_inbound_events.find({"workspace_id": ws}).to_list(10)}
        assert events["short"]["reason"] == "short_or_silent" and events["silent"]["reason"] == "short_or_silent"
        assert events["spam"]["reason"] == "no_enquiry"
        assert events["known-short"]["lead_id"] == lead_id
        assert await db.crm_leads.count_documents({"workspace_id": ws}) == 1
        lead = await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
        assert any("Short inbound call" in n["body"] for n in lead["lead_notes"])
    asyncio.run(isolated(run))


def test_caller_lookup_recognises_known_leads_and_leaves_outbound_context_alone():
    async def run(db):
        ws, lead_id, _ = await seed(db)
        await active_route(db, ws)
        await db.crm_leads.update_one({"_id": ObjectId(lead_id)}, {"$set": {"field_values.full_name": "Ravi", "do_not_call": True,
                                                                             "qualification_data": {"location": "Goa"}}})
        headers = {inbound.TOKEN_HEADER: TOKEN}
        url = f"/api/sarvam/inbound/{ws}/context"
        async with asgi(db) as client:
            assert (await client.post(url, json={"caller_phone": CALLER}, headers={inbound.TOKEN_HEADER: "wrong"})).status_code == 403
            known = (await client.post(url, json={"caller_phone": CALLER, "existing_context": ""}, headers=headers)).json()
            assert known["known"] and known["lead_name"] == "Ravi"
            assert known["lead_context"].startswith("INBOUND CALL") and "Goa" in known["lead_context"] and "not to be called" in known["lead_context"]
            outbound = (await client.post(url, json={"caller_phone": CALLER, "existing_name": "Ravi", "existing_context": "LEAD CONTEXT: prepared"}, headers=headers)).json()
            assert outbound == {"lead_name": "Ravi", "lead_context": "LEAD CONTEXT: prepared", "direction": "outbound"}
            new = (await client.post(url, json={"caller_phone": "+919111111111"}, headers=headers)).json()
            assert not new["known"] and new["lead_context"] == inbound.UNKNOWN_CALLER
            unbound = (await client.post(url, json={"caller_phone": "{{user_identifier}}", "existing_context": "{{lead_context}}"}, headers=headers)).json()
            assert unbound["lead_context"] == inbound.NO_NUMBER
        route = await inbound.route_for(db, ws)
        assert route["last_context_caller_seen"] is False and route["last_context_at"]
    asyncio.run(isolated(run))


def test_missed_webhook_is_recovered_from_sarvam_analytics(sarvam, monkeypatch):
    fake, _ = sarvam
    async def run(db):
        ws = await dedicated_workspace(db)
        await db.crm_leads.delete_many({"workspace_id": ws})
        route = {"_id": ws, "workspace_id": ws, "enabled": True, "status": "active", "app_id": "App-1", "app_version": 1,
                 "agent_phone_number": NUMBER, "deployment_id": "dep-1", "token_hash": inbound.token_hash(TOKEN)}
        await db.sarvam_inbound_routes.insert_one(route)
        item = {"interaction_id": "int-missed", "channel_direction": "inbound", "deployment_id": "dep-1", "user_contact": "+919222222222",
                "bot_contact_identifier": NUMBER, "duration_in_seconds": 80, "audio_url": "https://media.example/m.wav",
                "agent_variables": {"requirement": "Yoga retreat"},
                "original_transcript": [{"role": "user", "en_text": "I am looking for a yoga retreat in December"}]}
        original = fake.handle
        def handle(request):
            if "/interactions" in str(request.url):
                assert request.headers["X-API-Key"] == "rest-key"
                return httpx.Response(200, json={"items": [item]})
            return original(request)
        fake.handle = handle
        assert await inbound.fetch_missed(db, await inbound.route_for(db, ws)) == 1
        assert await inbound.fetch_missed(db, await inbound.route_for(db, ws)) == 0  # never twice
        await inbound.process_event(db, inbound.event_key(ws, "int-missed"))
        lead = await db.crm_leads.find_one({"workspace_id": ws, "source": "sarvam_inbound"})
        assert lead and "yoga" in lead["qualification_data"]["requirement"].lower()
    asyncio.run(isolated(run))
