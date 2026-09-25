import asyncio
import time
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest
from bson import ObjectId

import auth


class FakeInsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class FakeUpdateResult:
    def __init__(self, matched_count):
        self.matched_count = matched_count


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def find_one(self, query, sort=None, projection=None):
        docs = list(self.docs)
        if sort:
            for key, direction in reversed(sort):
                docs.sort(key=lambda item: item.get(key, ""), reverse=direction < 0)
        for doc in docs:
            if all(doc.get(key) == value for key, value in query.items()):
                result = dict(doc)
                if projection:
                    result = {key: value for key, value in result.items() if projection.get(key) or key == "_id"}
                return result
        return None

    async def insert_one(self, doc):
        doc = dict(doc)
        doc["_id"] = doc.get("_id") or ObjectId()
        self.docs.append(doc)
        return FakeInsertResult(doc["_id"])

    async def update_one(self, query, update):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                doc.update(update.get("$set", {}))
                return FakeUpdateResult(1)
        return FakeUpdateResult(0)


class FakeDb:
    def __init__(self):
        self.users = FakeCollection()
        self.password_reset_tokens = FakeCollection()
        self.workspaces = FakeCollection()


def run(coro):
    return asyncio.run(coro)


def route(router, path):
    return next(r.endpoint for r in router.routes if getattr(r, "path", "") == path)


def test_forgot_password_is_generic_and_creates_hashed_token(monkeypatch):
    db = FakeDb()
    user_id = ObjectId()
    db.users.docs.append({"_id": user_id, "name": "Riya", "email": "riya@example.com", "password_hash": "old"})
    sent = []
    monkeypatch.setattr(auth, "send_email_background", lambda *args: sent.append(args))
    router = auth.build_auth_router(db)

    body = SimpleNamespace(email="riya@example.com")
    response = run(route(router, "/api/auth/forgot-password")(body))

    assert response["ok"] is True
    assert len(db.password_reset_tokens.docs) == 1
    token_doc = db.password_reset_tokens.docs[0]
    assert token_doc["email"] == "riya@example.com"
    assert "token" not in token_doc
    assert len(token_doc["token_hash"]) == 64
    assert sent and sent[0][0] == "riya@example.com"


def test_forgot_password_unknown_email_does_not_send(monkeypatch):
    db = FakeDb()
    sent = []
    monkeypatch.setattr(auth, "send_email_background", lambda *args: sent.append(args))
    router = auth.build_auth_router(db)

    body = SimpleNamespace(email="missing@example.com")
    response = run(route(router, "/api/auth/forgot-password")(body))

    assert response["ok"] is True
    assert db.password_reset_tokens.docs == []
    assert sent == []


def test_reset_password_updates_password_and_rejects_reuse():
    db = FakeDb()
    user_id = ObjectId()
    db.users.docs.append({"_id": user_id, "email": "riya@example.com", "password_hash": auth.hash_password("oldpass")})
    raw_token = "reset-token-value-that-is-long-enough"
    db.password_reset_tokens.docs.append({
        "_id": ObjectId(),
        "user_id": str(user_id),
        "email": "riya@example.com",
        "token_hash": auth.hash_reset_token(raw_token),
        "used_at": None,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=20),
    })
    router = auth.build_auth_router(db)

    body = SimpleNamespace(token=raw_token, password="newpass")
    response = run(route(router, "/api/auth/reset-password")(body))

    assert response["ok"] is True
    assert auth.verify_password("newpass", db.users.docs[0]["password_hash"])
    assert db.password_reset_tokens.docs[0]["used_at"] is not None
    with pytest.raises(Exception):
        run(route(router, "/api/auth/reset-password")(body))


def test_register_does_not_block_when_email_fails(monkeypatch):
    db = FakeDb()
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    def fail_email(*args):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(auth, "send_email_background", fail_email)
    router = auth.build_auth_router(db)
    body = SimpleNamespace(name="Riya", email="riya@example.com", password="secret1")
    response = SimpleNamespace(set_cookie=lambda *args, **kwargs: None)

    result = run(route(router, "/api/auth/register")(body, response))

    assert result["user"]["email"] == "riya@example.com"
    assert len(db.users.docs) == 1


def test_login_returns_default_workspace_and_bcrypt_does_not_block_loop(monkeypatch):
    db = FakeDb()
    monkeypatch.setenv("JWT_SECRET", "test-login-signing-secret-long-enough")
    user_id = ObjectId()
    db.users.docs.append({
        "_id": user_id,
        "name": "Riya",
        "email": "riya@example.com",
        "password_hash": auth.hash_password("secret1"),
    })
    older, newer = ObjectId(), ObjectId()
    db.workspaces.docs.extend([
        {"_id": older, "user_id": str(user_id), "created_at": "2026-01-01"},
        {"_id": newer, "user_id": str(user_id), "created_at": "2026-02-01"},
    ])
    router = auth.build_auth_router(db)
    response = SimpleNamespace(set_cookie=lambda *args, **kwargs: None)

    async def scenario():
        body = SimpleNamespace(email="riya@example.com", password="secret1")
        login_task = asyncio.create_task(route(router, "/api/auth/login")(body, response))
        started = time.perf_counter()
        await asyncio.sleep(0.01)
        tick_elapsed = time.perf_counter() - started
        result = await login_task
        return tick_elapsed, result

    tick_elapsed, result = run(scenario())
    assert tick_elapsed < 0.1
    assert result["default_workspace_id"] == str(newer)
