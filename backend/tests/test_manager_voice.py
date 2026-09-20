"""Offline ASGI tests: synthetic state, no Mongo server, provider, or phone calls."""
import asyncio
import copy
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from bson import ObjectId
from fastapi import FastAPI, HTTPException
from pymongo.errors import DuplicateKeyError

import manager_voice as voice

USER = ObjectId("111111111111111111111111")
WORKSPACE = ObjectId("222222222222222222222222")
PHONE = "+14155550123"
KEY = "offline-test-credential-" + "x" * 32
BODY = {"message": "How many hot leads?", "session_id": "test-call", "caller_phone": PHONE, "transcript": "User: How many hot leads?"}
HEADERS = {"Authorization": "Bearer " + KEY}


class Collection:
    def __init__(self):
        self.docs = {}

    @staticmethod
    def matches(doc, query):
        for key, expected in query.items():
            current = doc
            for part in key.split("."):
                current = current.get(part) if isinstance(current, dict) else None
            if isinstance(expected, dict) and "$exists" in expected:
                if (current is not None) != expected["$exists"]:
                    return False
            elif current != expected:
                return False
        return True

    async def insert_one(self, doc):
        if doc["_id"] in self.docs:
            raise DuplicateKeyError("duplicate")
        self.docs[doc["_id"]] = copy.deepcopy(doc)

    async def find_one(self, query):
        return next((copy.deepcopy(d) for d in self.docs.values() if self.matches(d, query)), None)

    async def update_one(self, query, update, upsert=False):
        doc = next((d for d in self.docs.values() if self.matches(d, query)), None)
        if doc is None:
            if not upsert:
                return SimpleNamespace(matched_count=0)
            doc = {**{k: v for k, v in query.items() if not isinstance(v, dict)}, **copy.deepcopy(update.get("$setOnInsert", {}))}
            doc.setdefault("_id", ObjectId())
            self.docs[doc["_id"]] = doc
        for key, value in update.get("$set", {}).items():
            target = doc
            parts = key.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = copy.deepcopy(value)
        for key, value in update.get("$push", {}).items():
            doc.setdefault(key, []).append(copy.deepcopy(value))
        for key in update.get("$unset", {}):
            doc.pop(key, None)
        return SimpleNamespace(matched_count=1)

    async def delete_many(self, query):
        keys = [key for key, doc in self.docs.items() if self.matches(doc, query)]
        for key in keys:
            del self.docs[key]
        return SimpleNamespace(deleted_count=len(keys))

    async def find_one_and_update(self, query, update, **kwargs):
        result = await self.update_one(query, update)
        return await self.find_one({"_id": query["_id"]}) if result.matched_count else None


@pytest.fixture
def setup(monkeypatch):
    for name, value in {"ENABLED": "true", "API_KEY": KEY}.items():
        monkeypatch.setenv("SARVAM_AI_MANAGER_" + name, value)
    db = SimpleNamespace(users=Collection(), ai_manager_voice_sessions=Collection(), ai_manager_voice_connections=Collection())
    db.users.docs[USER] = {"_id": USER, "role": "user"}
    db.ai_manager_voice_connections.docs[str(USER)] = {"_id": str(USER), "caller_phone": PHONE, "workspace_id": str(WORKSPACE), "user_id": str(USER), "enabled": True}
    ws = {"_id": WORKSPACE, "user_id": str(USER), "brain": {"business_profile": {"name": "Test"}}}
    owner = AsyncMock(return_value=ws)
    auth = AsyncMock(return_value={"_id": USER, "role": "user"})
    calls = []

    async def stream(workspace, message, history, **kwargs):
        calls.append((workspace, message, copy.deepcopy(history)))
        kwargs["audit"].append({"tool": "crm_context", "status": "completed"})
        yield "You have four hot leads. Rahul is first."

    manager = SimpleNamespace(stream=stream)
    app = FastAPI()
    app.include_router(voice.build_voice_router(db, manager, owner, auth), prefix="/api")
    return SimpleNamespace(app=app, db=db, manager=manager, owner=owner, auth=auth, calls=calls)


def client(setup):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=setup.app), base_url="http://test")


def test_auth_before_validation_and_safe_health(setup):
    async def run():
        async with client(setup) as c:
            r = await c.post("/api/ai-manager/voice", content="invalid")
            assert r.status_code == 401
            assert not setup.owner.called
            health = await c.get("/api/ai-manager/voice/health")
            assert health.json() == {"enabled": True, "configured": True}
            assert KEY not in health.text
    asyncio.run(run())


@pytest.mark.parametrize("change", [{"workspace_id": "other"}, {"user_id": "other"}, {"message": " "}, {"message": "x" * 2001}, {"session_id": ""}, {"history": []}, {"caller_phone": "123"}])
def test_invalid_and_tenant_injection_rejected(setup, change):
    async def run():
        async with client(setup) as c:
            r = await c.post("/api/ai-manager/voice", json={**BODY, **change}, headers=HEADERS)
            assert r.status_code == 422
            assert not setup.owner.called
            assert not setup.calls
    asyncio.run(run())


def test_caller_and_workspace_authorization(setup):
    async def run():
        async with client(setup) as c:
            assert (await c.post("/api/ai-manager/voice", json={**BODY, "caller_phone": "+14155550999"}, headers=HEADERS)).status_code == 403
            setup.owner.side_effect = HTTPException(403, "private details")
            r = await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)
            assert r.status_code == 403
            assert "private details" not in r.text
            assert not setup.calls
    asyncio.run(run())


def test_continuity_replay_and_mapping(setup):
    async def run():
        async with client(setup) as c:
            first = await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)
            assert first.json() == {"reply": "You have four hot leads. Rahul is first.", "session_id": "test-call", "ok": True}
            setup.owner.assert_called_with(str(WORKSPACE), {"_id": USER, "role": "user"})
            duplicate = await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)
            assert duplicate.json() == first.json()
            assert len(setup.calls) == 1
            followup = {**BODY, "message": "Tell me about the first one.", "transcript": "longer transcript"}
            assert (await c.post("/api/ai-manager/voice", json=followup, headers=HEADERS)).status_code == 200
            assert setup.calls[1][2][-1]["content"].endswith("Rahul is first.")
            session = next(iter(setup.db.ai_manager_voice_sessions.docs.values()))
            assert len(session["turns"]) == 2
            assert session["turns"][0]["tools"][0]["tool"] == "crm_context"
            assert "busy_token" not in session
    asyncio.run(run())


def test_failed_tool_is_safe_cached_and_logged_without_secrets(setup, caplog):
    async def broken(*args, **kwargs):
        raise RuntimeError("secret=" + KEY)
        yield  # async generator
    setup.manager.stream = broken
    async def run():
        async with client(setup) as c:
            r = await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)
            assert r.json()["ok"] is False
            assert "Done" not in r.json()["reply"]
            assert KEY not in r.text
            assert (await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)).json() == r.json()
    with caplog.at_level(logging.INFO, logger="ai_manager.voice"):
        asyncio.run(run())
    assert KEY not in caplog.text
    assert PHONE not in caplog.text
    assert "How many" not in caplog.text


def test_timeout_and_overlap_do_not_repeat_actions(setup, monkeypatch):
    monkeypatch.setattr(voice, "MANAGER_TIMEOUT", .03)
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
        yield "Done"
    setup.manager.stream = slow
    async def run():
        async with client(setup) as c:
            first, second = await asyncio.gather(*[c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS) for _ in range(2)])
            assert sorted([first.status_code, second.status_code]) == [200, 409]
            result = first if first.status_code == 200 else second
            assert result.json()["ok"] is False
            assert "too long" in result.json()["reply"]
            assert (await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)).json() == result.json()
    asyncio.run(run())


def test_session_cannot_change_caller_and_request_id_cannot_change_message(setup, monkeypatch):
    setup.db.ai_manager_voice_connections.docs[ObjectId()] = {"caller_phone": "+14155550999", "workspace_id": str(WORKSPACE), "user_id": str(USER), "enabled": True}
    async def run():
        async with client(setup) as c:
            body = {**BODY, "request_id": "turn-one"}
            assert (await c.post("/api/ai-manager/voice", json=body, headers=HEADERS)).status_code == 200
            assert (await c.post("/api/ai-manager/voice", json={**body, "message": "Changed"}, headers=HEADERS)).status_code == 409
            assert (await c.post("/api/ai-manager/voice", json={**body, "caller_phone": "+14155550999"}, headers=HEADERS)).status_code == 403
    asyncio.run(run())


def test_limits_disabled_config_and_body_size(setup, monkeypatch):
    async def run():
        async with client(setup) as c:
            r = await c.post("/api/ai-manager/voice", json={**BODY, "transcript": "x" * 33000}, headers=HEADERS)
            assert r.status_code == 413
            for _ in range(29):
                await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)
            assert (await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)).status_code == 429
            monkeypatch.setenv("SARVAM_AI_MANAGER_API_KEY", "short")
            assert (await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)).status_code == 503
            monkeypatch.setenv("SARVAM_AI_MANAGER_ENABLED", "false")
            assert (await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)).status_code == 404
    asyncio.run(run())


def test_session_survives_router_restart_and_rechecks_user(setup):
    async def run():
        async with client(setup) as c:
            assert (await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)).status_code == 200
        setup.app = FastAPI()
        setup.app.include_router(voice.build_voice_router(setup.db, setup.manager, setup.owner, setup.auth), prefix="/api")
        async with client(setup) as c:
            assert (await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)).status_code == 200
            assert len(setup.calls) == 1
            setup.db.users.docs.clear()
            assert (await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)).status_code == 403
    asyncio.run(run())


def test_failed_audit_storage_never_reexecutes_uncertain_action(setup):
    async def run():
        sessions = setup.db.ai_manager_voice_sessions
        update = sessions.update_one
        async def fail_final_write(query, change):
            if "$push" in change:
                raise RuntimeError("storage unavailable")
            return await update(query, change)
        sessions.update_one = fail_final_write
        async with client(setup) as c:
            assert (await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)).status_code == 503
            assert (await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)).status_code == 409
            assert len(setup.calls) == 1
    asyncio.run(run())


def test_voice_storage_failure_does_not_disable_other_routes(setup):
    setup.app.state.voice_storage_ready = False
    async def run():
        async with client(setup) as c:
            assert (await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)).status_code == 503
            assert (await c.get("/api/ai-manager/voice/health")).status_code == 200
            assert not setup.calls
    asyncio.run(run())


def test_signed_in_user_dynamically_connects_and_moves_phone(setup):
    other_workspace = ObjectId("333333333333333333333333")
    async def run():
        async with client(setup) as c:
            first = await c.get(f"/api/ai-manager/voice/workspaces/{WORKSPACE}/connection")
            assert first.json()["caller_phone"] == PHONE
            moved = await c.put(f"/api/ai-manager/voice/workspaces/{other_workspace}/connection", json={"caller_phone": PHONE})
            assert moved.status_code == 200
            connection = await setup.db.ai_manager_voice_connections.find_one({"caller_phone": PHONE})
            assert connection["workspace_id"] == str(other_workspace)
            removed = await c.delete(f"/api/ai-manager/voice/workspaces/{other_workspace}/connection")
            assert removed.json()["connected"] is False
            assert await setup.db.ai_manager_voice_connections.find_one({"caller_phone": PHONE}) is None
    asyncio.run(run())


def test_workspace_move_applies_to_new_calls_not_active_call(setup):
    other_workspace = ObjectId("333333333333333333333333")
    async def run():
        async with client(setup) as c:
            assert (await c.post("/api/ai-manager/voice", json=BODY, headers=HEADERS)).status_code == 200
            await c.put(f"/api/ai-manager/voice/workspaces/{other_workspace}/connection", json={"caller_phone": PHONE})
            followup = {**BODY, "message": "Tell me about the first one", "transcript": "updated"}
            assert (await c.post("/api/ai-manager/voice", json=followup, headers=HEADERS)).status_code == 200
            assert setup.owner.call_args_list[-1].args[0] == str(WORKSPACE)
            new_call = {**BODY, "session_id": "new-call", "message": "Give me an overview"}
            assert (await c.post("/api/ai-manager/voice", json=new_call, headers=HEADERS)).status_code == 200
            assert setup.owner.call_args_list[-1].args[0] == str(other_workspace)
    asyncio.run(run())


def test_phone_cannot_be_claimed_by_another_account(setup):
    other_user = ObjectId("444444444444444444444444")
    setup.db.ai_manager_voice_connections.docs[next(iter(setup.db.ai_manager_voice_connections.docs))]["user_id"] = str(other_user)
    async def run():
        async with client(setup) as c:
            response = await c.put(f"/api/ai-manager/voice/workspaces/{WORKSPACE}/connection", json={"caller_phone": PHONE})
            assert response.status_code == 409
    asyncio.run(run())


def test_speech_formatting():
    text = "### Hot leads\n1. **Rahul** ID: 1234567890abcdef12345678\n| Name | Status |\n|---|---|\n| Rahul | Hot |\n[Site](https://example.com)"
    result = voice.speech_text(text)
    for forbidden in ("###", "**", "|", "1234567890abcdef12345678", "https://", "1."):
        assert forbidden not in result
    assert "Rahul" in result
    assert "spoken answer" in voice.speech_text('{"secret": "hidden"}')
    assert "hidden" not in voice.speech_text("API_KEY: hidden\nHello.")
    assert "https://example.com" in voice.speech_text("https://example.com", allow_urls=True)
    assert len(voice.speech_text("Long answer " * 1000)) <= 1200
