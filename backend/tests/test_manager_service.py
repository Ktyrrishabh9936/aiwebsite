"""Exercise the shared manager and actual CRM helpers with synthetic data only."""
import ast
import asyncio
import copy
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

import agents
from manager_service import ManagerService, VOICE_STYLE
from tests.test_manager_voice import Collection, USER, WORKSPACE


class ReadCollection:
    def __init__(self, docs):
        self.docs = docs
        self.queries = []

    def find(self, query, projection=None):
        self.queries.append(query)
        return self

    def sort(self, *args):
        return self

    async def to_list(self, limit):
        return self.docs[:limit]


def test_same_context_and_provider_for_web_and_voice(monkeypatch):
    seen = []
    async def llm(model, brain, roadmap, history, prompt, **kwargs):
        seen.append((model, brain, roadmap, history, prompt, kwargs))
        yield "Four hot leads."
    monkeypatch.setattr(agents, "manager_chat_stream", llm)
    db = SimpleNamespace(tasks=ReadCollection([{"title": "Follow up"}]), properties=ReadCollection([{"name": "Test property"}]))
    context = AsyncMock(return_value=({}, [], {"total_leads": 4}, [{"name": "Rahul", "status": "hot"}]))
    action = AsyncMock(return_value=None)
    service = ManagerService(db, context, action)
    ws = {"_id": WORKSPACE, "model_id": "saved-model", "brain": {"business_profile": {"company_name": "Test Realty"}}}
    async def run():
        for voice in (False, True):
            result = [x async for x in service.stream(ws, "How many?", [], voice=voice)]
            assert result == ["Four hot leads."]
    asyncio.run(run())
    assert seen[0][:5] == seen[1][:5]
    assert seen[1][5]["reply_instructions"] == VOICE_STYLE
    assert seen[0][0] == "saved-model"
    assert seen[0][1] == ws["brain"]
    assert "Rahul" in seen[0][4] and "Test property" in seen[0][4] and "Follow up" in seen[0][4]
    assert db.tasks.queries == [{"workspace_id": str(WORKSPACE)}] * 2
    assert db.properties.queries == db.tasks.queries


def server_functions(*names, **globals_):
    # Loading just these real functions avoids server startup, .env connections,
    # schedulers, admin seeding, and external callbacks during offline testing.
    tree = ast.parse((Path(__file__).parents[1] / "server.py").read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    for node in functions:
        node.decorator_list = []
    from ai_usage import usage_scope
    scope = {"re": re, "oid": ObjectId, "HTTPException": HTTPException, "usage_scope": usage_scope, **globals_}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "server.py", "exec"), scope)
    return scope


def test_actual_crm_action_success_and_missing_lead_failure():
    from crm import DEFAULT_FIELDS, DEFAULT_STATES
    lead_id = ObjectId()
    leads = [{"id": str(lead_id), "full_name": "Rahul", "field_values": {"full_name": "Rahul"}}]
    collection = Collection()
    collection.docs[lead_id] = {"_id": lead_id, "workspace_id": str(WORKSPACE), "status": "new"}
    db = SimpleNamespace(crm_leads=collection)
    functions = server_functions("_find_crm_lead", "_extract_note_body", "try_manager_crm_action", db=db, now_iso=lambda: "test-time")
    action = functions["try_manager_crm_action"]
    settings = {"fields": copy.deepcopy(DEFAULT_FIELDS), "states": copy.deepcopy(DEFAULT_STATES)}
    async def run():
        result = await action(str(WORKSPACE), "Add a call note for Rahul: Please follow up tomorrow", settings, leads, source="voice")
        assert result.startswith("Done.")
        assert len(collection.docs[lead_id]["lead_notes"]) == 1
        assert collection.docs[lead_id]["lead_notes"][0]["source"] == "ai_manager_voice"
        assert "call_provider" not in collection.docs[lead_id]["lead_notes"][0]
        collection.docs.clear()
        with pytest.raises(HTTPException) as error:
            await action(str(WORKSPACE), "Add a note for Rahul: Please follow up tomorrow", settings, leads)
        assert error.value.status_code == 409
    asyncio.run(run())


def test_action_completion_bypasses_llm_and_failures_propagate(monkeypatch):
    action = AsyncMock(return_value="Done. I added a lead note for Rahul.")
    context = AsyncMock(return_value=({}, [], {}, []))
    service = ManagerService(None, context, action)
    async def unexpected(*args, **kwargs):
        pytest.fail("Do not ask LLM to invent a tool completion")
        yield
    monkeypatch.setattr(agents, "manager_chat_stream", unexpected)
    async def run():
        audit = []
        result = [x async for x in service.stream({"_id": WORKSPACE}, "Add a note", [], audit=audit)]
        assert result[0].startswith("Done.")
        assert audit[-1] == {"tool": "crm_action", "status": "completed"}
        action.side_effect = RuntimeError("database unavailable")
        audit = []
        with pytest.raises(RuntimeError):
            async for _ in service.stream({"_id": WORKSPACE}, "Add a note", [], audit=audit):
                pass
        assert audit[-1]["status"] == "failed"
    asyncio.run(run())


def test_web_endpoint_still_streams_shared_manager():
    calls = []
    async def stream(*args, **kwargs):
        calls.append((args, kwargs))
        yield "Hello "
        yield "manager."
    user = {"_id": USER}
    ws = {"_id": WORKSPACE, "model_id": "saved-model"}
    scope = server_functions("manager_chat", Request=object, Body=lambda *args: None,
                             require_user=AsyncMock(return_value=user), owned_workspace=AsyncMock(return_value=ws),
                             manager_service=SimpleNamespace(stream=stream), StreamingResponse=StreamingResponse,
                             logger=logging.getLogger("test"))
    async def run():
        response = await scope["manager_chat"](str(WORKSPACE), object(), {"message": "Hi", "history": []})
        assert "".join([chunk async for chunk in response.body_iterator]) == "Hello manager."
        assert calls == [((ws, "Hi", []), {"model_id": "saved-model"})]
    asyncio.run(run())


def test_actual_owner_check_denies_other_tenant():
    db = SimpleNamespace(workspaces=Collection())
    db.workspaces.docs[WORKSPACE] = {"_id": WORKSPACE, "user_id": str(USER)}
    owned = server_functions("owned_workspace", db=db)["owned_workspace"]
    async def run():
        assert (await owned(str(WORKSPACE), {"_id": USER}))["_id"] == WORKSPACE
        with pytest.raises(HTTPException) as error:
            await owned(str(WORKSPACE), {"_id": ObjectId()})
        assert error.value.status_code == 403
    asyncio.run(run())


def test_existing_crm_reader_preserves_workspace_scope_and_real_analytics(monkeypatch):
    import crm
    settings = {"fields": copy.deepcopy(crm.DEFAULT_FIELDS), "states": copy.deepcopy(crm.DEFAULT_STATES)}
    lead = crm.build_manual_lead(str(WORKSPACE), {"field_values": {"phone": "+14155550123", "full_name": "Rahul"}}, settings)
    db = SimpleNamespace(crm_leads=ReadCollection([lead]))
    monkeypatch.setattr(crm, "ensure_crm_settings", AsyncMock(return_value=settings))
    monkeypatch.setattr(crm, "purge_expired_trashed_leads", AsyncMock())
    reader = server_functions("crm_manager_context", db=db)["crm_manager_context"]
    async def run():
        actual_settings, leads, analytics, summaries = await reader(str(WORKSPACE))
        assert actual_settings == settings
        assert leads[0]["full_name"] == "Rahul"
        assert summaries[0]["name"] == "Rahul"
        assert analytics == crm.build_crm_analytics(leads)
        assert db.crm_leads.queries[0]["workspace_id"] == str(WORKSPACE)
        assert db.crm_leads.queries[0]["deleted_at"] is None  # Excludes trash and includes legacy missing fields.
    asyncio.run(run())


def test_task_creation_is_not_presented_as_an_executable_tool(monkeypatch):
    seen = []
    async def stream(model, system, prompt):
        seen.append(system)
        yield "Task creation is unavailable."
    monkeypatch.setattr(agents, "_stream", stream)
    async def run():
        async for _ in agents.manager_chat_stream("test", {}, {}, [], "Create a task for Rishabh tomorrow"):
            pass
    asyncio.run(run())
    assert "Task creation, task execution" in seen[0]
    assert "Never claim you created" in seen[0]
    assert "no more than 80 words" in seen[0]
    assert "at most three short bullets" in seen[0]


def test_task_request_does_not_accidentally_assign_a_crm_lead():
    context, action = AsyncMock(), AsyncMock()
    service = ManagerService(None, context, action)
    async def run():
        result = [x async for x in service.stream({"_id": WORKSPACE}, "Create a task assigned to Rishabh to follow up with Rahul", [], voice=True)]
        assert "has not been saved" in result[0]
        context.assert_not_called()
        action.assert_not_called()
    asyncio.run(run())
