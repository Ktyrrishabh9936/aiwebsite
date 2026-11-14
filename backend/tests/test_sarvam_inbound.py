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
        self.refuse_binding = False

    def tool_result(self, name, arguments):
        if name == "configure_agent" and "agent_id" in arguments:
            return {"id": "App-1", "changed": ["ok"]}
        if name == "create_api_tool":
            if arguments.get("tool_id"):
                return {"tool_id": arguments["tool_id"], "changed": ["saved"]}
            tool_id = "tool-find" if arguments["name"] == inbound.FIND_TOOL_NAME else "tool-1"
            return {"tool_id": tool_id, "call_reference": f"call tool:{arguments['name']}"}
        if name == "configure_app_tool":
            return {"id": arguments["tool_id"], "changed": ["saved"], "not_applied": []}
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
        if message.get("method") == "tools/call" and message["params"]["name"] == "configure_app_tool" and self.refuse_binding \
                and "system_variable" in json.dumps(message["params"]["arguments"]):
            self.tool_calls.append({"name": "configure_app_tool", "arguments": message["params"]["arguments"]})
            return self.reply(message, "system variables are not available on this plan", error=True)
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
        assert tool["body"]["existing_context"]["value"]["variable_name"] == "lead_context"
        token = tool["headers"][inbound.TOKEN_HEADER]
        # The caller's number is bound from the call runtime, with the opening line echoed for outbound calls.
        binding = calls(fake, "configure_app_tool")[0]
        assert binding["tool_id"] == "tool-1" and binding["tool_type"] == "webhook_on_start"
        body = {item["name"]: item for item in binding["connector_config"]["body"]}
        assert body["caller_phone"] == {"name": "caller_phone", "type": "system_variable", "value": {"variable_name": "user_identifier"}}
        assert body["existing_opening"]["value"]["variable_name"] == "opening_line"
        assert {"response_path": "opening_line", "variable_name": "opening_line"} in binding["connector_config"]["save_to_variables"]
        # The in-call search tool is real, so the prompt may name it.
        search = calls(fake, "create_api_tool")[1]
        assert search["name"] == inbound.FIND_TOOL_NAME and search["lifecycle"] == "run" and search["headers"][inbound.TOKEN_HEADER] == token
        assert search["url"] == f"https://crm.example/api/sarvam/inbound/{ws}/find" and search["resp_template"] == "{{reply}}"
        configured = calls(fake, "configure_agent")
        assert any((c.get("config") or {}).get("intro_message_config") == {"audio": "{{opening_line}}"} for c in configured)
        variables = {name for c in configured for name in ((c.get("config") or {}).get("llm_config", {}).get("agent_config", {}).get("agent_variables") or {})}
        assert {"caller_name", "caller_email", "opening_line"} <= variables
        opening = next(c for c in configured if "opening_line" in json.dumps(c.get("config") or {}) and "agent_variables" in json.dumps(c.get("config") or {}))
        assert "thank you for calling" in json.dumps(opening).lower()
        deployment = calls(fake, "configure_deployment")[0]
        assert "inbound_config" not in deployment  # 24/7
        assert deployment["connection_configs"] == [{"connection_id": "conn-1", "phone_numbers": [NUMBER]}]
        assert deployment["webhook_config"] == {"url": f"https://crm.example/api/sarvam/inbound/{ws}/result",
                                                "metadata": {"arevei_workspace_id": ws, "inbound_token": token}}
        assert deployment["app_version"] == 2 and deployment["app_id"] == "App-1"
        appended = [c["prompt_append"] for c in calls(fake, "configure_agent") if c.get("prompt_append")]
        assert appended[-1] == inbound.INBOUND_PROMPT and f"tool:{inbound.FIND_TOOL_NAME}" in appended[-1]
        doc, _ = await load_config(db, ws, "sarvam")
        assert doc["config"]["app_version"] == 2 and doc["config"]["opening_line_ready"] is True  # outbound uses the same version
        # Enabling again patches the same deployment instead of creating a second one.
        fake.deployments = [{"id": "dep-1", "app_id": "App-1", "connection_configs": [{"connection_id": "conn-1", "phone_numbers": [NUMBER]}]}]
        await inbound.enable_inbound(db, ws, USER)
        assert calls(fake, "configure_deployment")[-1]["deployment_id"] == "dep-1"
        assert calls(fake, "telephony")[-2]["operation"] == "pause_deployment"  # Sarvam edits only paused deployments
        assert len(calls(fake, "create_api_tool")) == 2 and len(calls(fake, "configure_app_tool")) == 1
    asyncio.run(isolated(run))


def test_caller_binding_falls_back_to_manual_mapping(sarvam):
    fake, _ = sarvam
    fake.refuse_binding = True
    async def run(db):
        ws = await dedicated_workspace(db)
        result = await inbound.enable_inbound(db, ws, USER)
        assert result["caller_lookup"] == "manual"
        names = [item["name"] for item in calls(fake, "configure_app_tool")[-1]["connector_config"]["body"]]
        assert "caller_phone" not in names and "existing_context" in names
    asyncio.run(isolated(run))


def test_retry_reuses_tools_left_by_a_failed_attempt(sarvam):
    fake, _ = sarvam
    async def run(db):
        ws = await dedicated_workspace(db)
        original = fake.tool_result
        def leftovers(name, arguments):
            if name == "agents" and arguments["operation"] == "get" and "tools" in arguments["params"]["include"]:
                return {"id": "App-1", "intro": {"audio": "Hi, am I speaking with {{lead_name}}?"},
                        "prompt_text": {"initial_state_name": "start", "states": {"start": {"instructions": "# ROLE\nSeller.\n\n" + inbound.INBOUND_PROMPT_BASIC + "\n\n# RESULT\nCapture."}}},
                        "tools": [{"id": "old-lookup", "name": inbound.TOOL_NAME, "connector_config": {"headers": [{"name": inbound.TOKEN_HEADER, "type": "static", "value": "old-token"}]}},
                                  {"id": "old-find", "name": inbound.FIND_TOOL_NAME, "connector_config": {}}]}
            return original(name, arguments)
        fake.tool_result = leftovers
        await inbound.enable_inbound(db, ws, USER)
        creates = calls(fake, "create_api_tool")
        assert len(creates) == 1 and creates[0]["tool_id"] == "old-find" and creates[0]["headers"][inbound.TOKEN_HEADER] == "old-token"
        assert calls(fake, "configure_app_tool")[0]["tool_id"] == "old-lookup"
        edit = next(c for c in calls(fake, "configure_agent") if c.get("prompt_edits"))
        assert edit["prompt_edits"] == [{"old_text": inbound.INBOUND_PROMPT_BASIC, "new_text": inbound.INBOUND_PROMPT}]
        assert calls(fake, "configure_deployment")[0]["webhook_config"]["metadata"]["inbound_token"] == "old-token"
        route = await inbound.route_for(db, ws)
        assert route["token_hash"] == inbound.token_hash("old-token") and route["setup_version"] == inbound.SETUP_VERSION
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
            assert known["known"] and known["lead_name"] == "Ravi" and known["opening_line"].startswith("Hello Ravi, thank you for calling")
            assert known["lead_context"].startswith("INBOUND CALL") and "Goa" in known["lead_context"] and "not to be called" in known["lead_context"]
            outbound = (await client.post(url, json={"caller_phone": CALLER, "existing_name": "Ravi", "existing_context": "LEAD CONTEXT: prepared",
                                                     "existing_opening": "Hi, am I speaking with Ravi?"}, headers=headers)).json()
            assert outbound == {"lead_name": "Ravi", "lead_context": "LEAD CONTEXT: prepared", "opening_line": "Hi, am I speaking with Ravi?", "direction": "outbound"}
            new = (await client.post(url, json={"caller_phone": "+919111111111"}, headers=headers)).json()
            assert not new["known"] and new["lead_context"] == inbound.UNKNOWN_CALLER and new["opening_line"].startswith("Hello, thank you for calling")
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


def test_context_remembers_calls_across_duplicate_leads():
    async def run(db):
        ws, lead_id, _ = await seed(db)
        await active_route(db, ws)
        await db.crm_leads.update_one({"_id": ObjectId(lead_id)}, {"$set": {"field_values.full_name": "Ravi"}})
        older = await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
        older.update({"_id": ObjectId(), "created_at": "2020-01-01T00:00:00+00:00", "updated_at": "2020-01-01T00:00:00+00:00"})
        await db.crm_leads.insert_one(older)
        await db.plivo_call_sessions.insert_many([
            {"workspace_id": ws, "lead_id": str(older["_id"]), "status": "completed", "summary": "Wanted a 2 BHK in Kanpur for investment.", "created_at": "2026-09-10T03:44:00+00:00"},
            {"workspace_id": ws, "lead_id": lead_id, "status": "completed", "direction": "outbound", "summary": "Asked for a December yoga retreat.", "created_at": "2026-11-14T08:21:00+00:00"},
        ])
        async with asgi(db) as client:
            known = (await client.post(f"/api/sarvam/inbound/{ws}/context", json={"caller_phone": CALLER}, headers={inbound.TOKEN_HEADER: TOKEN})).json()
        assert known["known"] and "December yoga retreat" in known["lead_context"] and "2 BHK in Kanpur" in known["lead_context"]
        assert known["lead_context"].index("December yoga") < known["lead_context"].index("2 BHK")  # newest first
    asyncio.run(isolated(run))


def test_in_call_search_finds_by_email_and_never_invents_a_match():
    async def run(db):
        ws, lead_id, _ = await seed(db)
        await active_route(db, ws)
        await db.crm_leads.update_one({"_id": ObjectId(lead_id)}, {"$set": {"field_values.full_name": "Ravi Kumar", "field_values.email": "Ravi.K@Example.com",
                                                                             "communication_summary": {"latest_summary": "Asked about a Goa retreat. Budget not shared."}}})
        url, headers = f"/api/sarvam/inbound/{ws}/find", {inbound.TOKEN_HEADER: TOKEN}
        async with asgi(db) as client:
            assert (await client.post(url, json={"email": "ravi.k@example.com"}, headers={inbound.TOKEN_HEADER: "wrong"})).status_code == 403
            found = (await client.post(url, json={"email": "ravi.k at example dot com"}, headers=headers)).json()
            assert found["found"] and found["lead_name"] == "Ravi Kumar" and found["reply"].startswith("Thank you, Ravi. I found your earlier enquiry")
            assert "Goa retreat" in found["reply"] and found["lead_context"].startswith("INBOUND CALL")
            by_phone = (await client.post(url, json={"phone": CALLER}, headers=headers)).json()
            assert by_phone["found"]
            missing = (await client.post(url, json={"email": "nobody@example.com"}, headers=headers)).json()
            assert not missing["found"] and "could not find" in missing["reply"] and missing["lead_name"] == ""
            empty = (await client.post(url, json={"email": "{{email}}", "phone": ""}, headers=headers)).json()
            assert not empty["found"] and "did not catch" in empty["reply"]
    asyncio.run(isolated(run))


def test_call_summary_and_email_are_kept_on_the_lead():
    async def run(db):
        ws, lead_id, _ = await seed(db)
        await active_route(db, ws)
        await db.crm_leads.update_one({"_id": ObjectId(lead_id)}, {"$unset": {"field_values.email": ""}})
        data = payload(interaction="int-summary", variables={"requirement": "Panchakarma retreat", "caller_email": "Asha.Rao@Example.com",
                                                                            "call_summary": "The caller wanted his earlier records and asked about Panchakarma."})
        key = await inbound.record_event(db, ws, data, "webhook")
        outcome = await inbound.process_event(db, key)
        assert outcome["status"] == "processed" and outcome["lead_id"] == lead_id
        lead = await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
        assert lead["communication_summary"]["latest_summary"].startswith("The caller wanted his earlier records")
        assert lead["field_values"]["email"] == "asha.rao@example.com"
        assert lead["lead_notes"][-1]["body"].startswith("Inbound call: The caller wanted his earlier records")
        session = await db.plivo_call_sessions.find_one({"workspace_id": ws, "provider_identifiers.call_uuid": "int-summary"})
        assert session["summary"].startswith("The caller wanted")
    asyncio.run(isolated(run))


def test_outbound_calls_send_the_opening_line_once_the_intro_uses_it():
    from voice_providers import SarvamVoiceProvider
    config = {"app_id": "App-1", "app_version": 3, "connection_id": "conn-1", "agent_phone_number": NUMBER, "payload_mode": "lead_context_v1",
              "credentials": {"callback_token": "x" * 48}}
    base = {"workspace_id": str(ObjectId()), "lead_id": "lead-1", "lead_name": "Asha", "lead_context": "LEAD CONTEXT", "to_number": CALLER}
    assert "opening_line" not in SarvamVoiceProvider().build_payload(base, config, "s-1")["app_config"]["agent_variables"]
    ready = SarvamVoiceProvider().build_payload(base, {**config, "opening_line_ready": True}, "s-1")["app_config"]["agent_variables"]
    assert ready["opening_line"] == "Hi, am I speaking with Asha?"
    nameless = SarvamVoiceProvider().build_payload({**base, "lead_name": ""}, {**config, "opening_line_ready": True}, "s-1")["app_config"]["agent_variables"]
    assert nameless["opening_line"] == "Hello! Do you have a moment to talk?"
