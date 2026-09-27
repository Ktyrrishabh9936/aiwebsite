import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from bson import ObjectId
from fastapi import FastAPI, HTTPException

import manager_agent as agent
from manager_tools import ManagerTools
from manager_model import bedrock_messages

WS, LEAD = ObjectId(), ObjectId()


def call(name, arguments=None, call_id="call-one"):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments or {})}}]}


def body(text="Find pending work"):
    return agent.AgentInput(message=text, conversation_id="conversation-test", request_id="request-test", timezone="Asia/Kolkata")


def run(responses, *, history=(), fail=False):
    model = AsyncMock(side_effect=responses)
    tools = SimpleNamespace(execute=AsyncMock(side_effect=ValueError("Choose an unambiguous lead") if fail else None, return_value={"id": str(LEAD)}))
    events, saves = [], []
    async def emit(event): events.append(deepcopy(event))
    async def save(messages): saves.append(deepcopy(messages))
    asyncio.run(agent.run_loop({"_id": WS, "model_id": "test", "name": "Studio"}, body(), list(history), tools, emit, save, model=model))
    return tools, events, saves, model


def test_model_selects_tools_and_receives_results_without_a_fixed_sequence():
    tools, events, saves, model = run([call("list_followups"), call("get_business_context", call_id="call-two"), {"role": "assistant", "content": "Two follow-ups need attention."}])
    assert [args.args[0] for args in tools.execute.call_args_list] == ["list_followups", "get_business_context"]
    assert any(message.get("role") == "tool" and json.loads(message["content"])["id"] == str(LEAD)
               for message in model.call_args_list[1].args[2])
    assert [event["type"] for event in events].count("tool_finished") == 2
    assert events[-1]["status"] == "completed"
    assert saves[-1][-1]["content"] == "Two follow-ups need attention."


def test_prior_tool_results_are_available_for_pronoun_resolution():
    history = [{"role": "user", "content": "Which lead?"}, call("search_leads"),
               {"role": "tool", "tool_call_id": "call-one", "content": json.dumps({"id": str(LEAD), "name": "Rahul"})},
               {"role": "assistant", "content": "Rahul needs a follow-up."}]
    _, _, _, model = run([{"role": "assistant", "content": "What time should I schedule it?"}], history=history)
    assert any("Rahul" in message.get("content", "") for message in model.call_args.args[2])
    assert "Asia/Kolkata" in model.call_args.args[1]


def test_duplicate_writes_execute_once_but_reads_refresh():
    tools, events, _, _ = run([call("add_lead_note", {"lead_id": str(LEAD), "body": "Called"}),
        call("add_lead_note", {"lead_id": str(LEAD), "body": "Called"}, "duplicate"),
        call("get_lead", {"lead_id": str(LEAD)}, "read-one"), call("get_lead", {"lead_id": str(LEAD)}, "read-two"),
        {"role": "assistant", "content": "Note saved."}])
    assert tools.execute.await_count == 3
    assert any(event.get("reused") for event in events)


def test_tool_failure_is_returned_to_model_and_visibly_failed():
    _, events, _, model = run([call("get_lead", {"lead_id": str(LEAD)}), {"role": "assistant", "content": "Please identify the lead."}], fail=True)
    assert any(event["status"] == "failed" for event in events)
    result = json.loads(model.call_args.args[2][-2]["content"])
    assert result["saved"] is False and "error" in result


def test_interrupted_history_removes_unanswered_tool_calls():
    messages = [{"role": "user", "content": "Hello"}, call("get_lead")]
    assert agent.valid_history(messages) == [{"role": "user", "content": "Hello"}]


def test_bedrock_translation_preserves_tool_use_and_result():
    converted = bedrock_messages([{"role": "user", "content": "Get a lead"}, call("get_lead", {"lead_id": str(LEAD)}),
                                  {"role": "tool", "tool_call_id": "call-one", "content": '{"name":"Rahul"}'}])
    assert converted[1]["content"][0]["toolUse"]["name"] == "get_lead"
    assert converted[2]["content"][0]["toolResult"]["toolUseId"] == "call-one"


def test_agent_loop_has_an_execution_budget():
    async def scenario():
        with pytest.raises(ValueError, match="limit"):
            await agent.run_loop({"_id": WS}, body(), [], SimpleNamespace(execute=AsyncMock(return_value={})),
                AsyncMock(), AsyncMock(), model=AsyncMock(return_value=call("get_business_context")))
    asyncio.run(scenario())


def test_tools_reject_unknown_tool_and_foreign_lead(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "get_current_user_and_workspace", AsyncMock(return_value=({}, {})))
    db = SimpleNamespace(crm_leads=SimpleNamespace(find_one=AsyncMock(return_value=None)))
    tools = ManagerTools(db, {"_id": WS}, object())
    async def scenario():
        with pytest.raises(ValueError, match="Unknown"): await tools.execute("run_arbitrary_code", {})
        with pytest.raises(HTTPException) as error: await tools.execute("get_lead", {"lead_id": str(LEAD)})
        assert error.value.status_code == 404
        assert db.crm_leads.find_one.call_args.args[0]["workspace_id"] == str(WS)
    asyncio.run(scenario())


@pytest.mark.parametrize("skip", [False, True])
def test_chat_lead_creation_preserves_automatic_qualification_unless_explicitly_skipped(monkeypatch, skip):
    import auth, crm
    monkeypatch.setattr(auth, "get_current_user_and_workspace", AsyncMock(return_value=({}, {})))
    create = AsyncMock(return_value={"id": str(LEAD)})
    monkeypatch.setattr(crm, "create_lead", create)
    tools = ManagerTools(SimpleNamespace(), {"_id": WS}, object())
    tools.field_keys = {"phone", "full_name"}
    args = {"field_values": {"phone": "+14155550123"}}
    if skip: args["trigger_ai_call"] = False
    asyncio.run(tools.execute("create_lead", args))
    assert create.call_args.args[2]["trigger_ai_call"] is (not skip)


def test_rejected_provider_call_is_not_reported_as_delegated(monkeypatch):
    import auth, plivo_calls
    monkeypatch.setattr(auth, "get_current_user_and_workspace", AsyncMock(return_value=({}, {})))
    monkeypatch.setattr(plivo_calls, "start_qualification_call", AsyncMock(return_value={"status": "failed", "error": "provider rejected"}))
    tools = ManagerTools(SimpleNamespace(), {"_id": WS}, object())
    tools.lead = AsyncMock(return_value={"_id": LEAD})
    tools.known_leads.add(str(LEAD))
    with pytest.raises(ValueError, match="not accepted"):
        asyncio.run(tools.execute("start_initial_qualification", {"lead_id": str(LEAD)}))


def test_chat_creation_uses_real_crm_creation_and_existing_call_scheduler(monkeypatch):
    import auth, crm, plivo_calls
    monkeypatch.setattr(auth, "get_current_user_and_workspace", AsyncMock(return_value=({}, {})))
    monkeypatch.setattr(crm, "ensure_crm_settings", AsyncMock(return_value={"fields": crm.DEFAULT_FIELDS, "states": crm.DEFAULT_STATES}))
    saved = {}
    async def insert(doc): saved.update(doc)
    async def schedule(db, ws_id, lead_id):
        assert saved["auto_qualification_enabled"] is True
        assert saved["field_values"]["phone"] == "+919876543210"
        saved["qualification_call"] = {"status": "scheduled", "provider": "sarvam"}
    scheduler = AsyncMock(side_effect=schedule)
    monkeypatch.setattr(plivo_calls, "schedule_first_qualification_call", scheduler)
    db = SimpleNamespace(crm_leads=SimpleNamespace(insert_one=AsyncMock(side_effect=insert), find_one=AsyncMock(side_effect=lambda query: saved)))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))
    tools = ManagerTools(db, {"_id": WS}, request)
    tools.field_keys = {"phone", "full_name"}
    result = asyncio.run(tools.execute("create_lead", {"field_values": {"phone": "+919876543210", "full_name": "Test"}}))
    scheduler.assert_awaited_once_with(db, str(WS), str(saved["_id"]))
    assert result["qualification_call"] == {"status": "scheduled", "provider": "sarvam"}
    assert result["auto_qualification_enabled"] is True


def test_real_run_persists_followup_and_replaying_request_does_not_duplicate(monkeypatch):
    from auth import create_access_token
    from tests.test_qualification_integration import isolated
    monkeypatch.setenv("JWT_SECRET", "manager-agent-test-only-long-signing-secret")
    model = AsyncMock(side_effect=[call("get_lead", {"lead_id": str(LEAD)}), call("create_followup", {
        "lead_id": str(LEAD), "title": "Call Rahul", "due_at": "2030-01-01T11:00:00+05:30"}, "write-one"),
        {"role": "assistant", "content": "Rahul's follow-up is saved."}])
    monkeypatch.setattr(agent, "tool_turn", model)
    async def scenario(db):
        user = ObjectId()
        await db.users.insert_one({"_id": user, "email": "manager@example.test"})
        await db.workspaces.insert_one({"_id": WS, "user_id": str(user)})
        await db.crm_leads.insert_one({"_id": LEAD, "workspace_id": str(WS), "field_values": {"full_name": "Rahul", "phone": "+14155550123"}})
        app = FastAPI()
        app.state.db = db
        app.include_router(agent.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            base = f"/workspaces/{WS}/manager"
            assert (await client.post(base + "/runs", json=body().model_dump())).status_code == 401
            client.headers["Authorization"] = "Bearer " + create_access_token(str(user), "manager@example.test")
            response = await client.post(base + "/runs", json=body().model_dump())
            assert response.status_code == 200, response.text
            assert '"type": "answer"' in response.text
            assert await db.tasks.count_documents({"workspace_id": str(WS), "source": "crm_reminder"}) == 1
            replay = await client.post(base + "/runs", json=body().model_dump())
            assert replay.json()["replayed"] is True
            assert model.await_count == 3
            saved = (await client.get(base + "/conversation/conversation-test")).json()
            assert saved["runs"][0]["status"] == "completed"
            assert saved["messages"][-1]["content"] == "Rahul's follow-up is saved."
            # A terminal run left in the conversation lock must not block new work.
            await db.manager_conversations.update_one({"conversation_id": "conversation-test"}, {"$set": {"active_run": "request-test"}})
            model.side_effect = [{"role": "assistant", "content": "Ready for the next request."}]
            next_body = body().model_copy(update={"request_id": "next-request"})
            next_response = await client.post(base + "/runs", json=next_body.model_dump())
            assert next_response.status_code == 200
            assert 'Ready for the next request.' in next_response.text
            thread = await db.manager_conversations.find_one({"conversation_id": "conversation-test"})
            assert thread["active_run"] is None
    asyncio.run(isolated(scenario))
