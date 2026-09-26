import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from bson import ObjectId
from cryptography.fernet import Fernet
from fastapi import HTTPException

import sms
from voice_config import decrypt


def request_for(db):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))


def test_config_encrypts_token_and_does_not_expose_it(monkeypatch):
    monkeypatch.setenv("VOICE_CREDENTIAL_KEYS", Fernet.generate_key().decode())
    db = SimpleNamespace(workspace_sms_configs=SimpleNamespace(find_one=AsyncMock(return_value=None), update_one=AsyncMock()))
    sid = "AC" + "a" * 32
    async def run():
        result = await sms.save_config("workspace-a", request_for(db), {
            "enabled": True, "account_sid": sid, "auth_token": "private-token", "from_number": "+14155550123"
        })
        assert result["configured"] and "auth_token" not in result
        stored = db.workspace_sms_configs.update_one.await_args.args[1]["$set"]
        assert "private-token" not in repr(stored)
        assert decrypt("workspace-a", "twilio_sms", stored["encrypted_auth_token"])["auth_token"] == "private-token"
        with pytest.raises(HTTPException):
            decrypt("workspace-b", "twilio_sms", stored["encrypted_auth_token"])
    asyncio.run(run())


def test_send_uses_saved_lead_phone_and_service_without_real_network(monkeypatch):
    monkeypatch.setenv("VOICE_CREDENTIAL_KEYS", Fernet.generate_key().decode())
    lead_id = ObjectId()
    sid = "AC" + "a" * 32
    message_sid = "SM" + "b" * 32
    config = {"enabled": True, "account_sid": sid, "messaging_service_sid": "MG" + "c" * 32,
              "encrypted_auth_token": sms.encrypt("workspace-a", "twilio_sms", {"auth_token": "private-token"})}
    db = SimpleNamespace(
        crm_leads=SimpleNamespace(find_one=AsyncMock(return_value={"_id": lead_id, "phone": "9876543210"})),
        workspace_sms_configs=SimpleNamespace(find_one=AsyncMock(return_value=config)),
        crm_sms_messages=SimpleNamespace(insert_one=AsyncMock()),
    )
    async def insert(doc):
        doc["_id"] = ObjectId()
    db.crm_sms_messages.insert_one.side_effect = insert
    post = AsyncMock(return_value=httpx.Response(201, json={"sid": message_sid, "status": "queued"}))
    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def post(self, *args, **kwargs):
            return await post(*args, **kwargs)
    monkeypatch.setattr(sms.httpx, "AsyncClient", lambda **kwargs: Client())

    async def run():
        result = await sms.send_message("workspace-a", str(lead_id), request_for(db), {"text": " Hello "})
        assert result["status"] == "queued" and result["to"] == "+919876543210"
        kwargs = post.await_args.kwargs
        assert kwargs["data"] == {"To": "+919876543210", "Body": "Hello", "MessagingServiceSid": config["messaging_service_sid"]}
        assert kwargs["auth"] == (sid, "private-token")
        assert "private-token" not in repr(result)
        db.crm_leads.find_one.assert_awaited_with({"workspace_id": "workspace-a", "_id": lead_id})
    asyncio.run(run())


def test_rejects_invalid_destination_before_network(monkeypatch):
    lead_id = ObjectId()
    db = SimpleNamespace(crm_leads=SimpleNamespace(find_one=AsyncMock(return_value={"phone": "123"})))
    async def run():
        with pytest.raises(HTTPException) as error:
            await sms.send_message("workspace-a", str(lead_id), request_for(db), {"text": "Hello"})
        assert error.value.status_code == 422
    asyncio.run(run())


def test_refresh_returns_delivery_status_without_resending(monkeypatch):
    monkeypatch.setenv("VOICE_CREDENTIAL_KEYS", Fernet.generate_key().decode())
    lead_id, message_id = ObjectId(), ObjectId()
    sid = "AC" + "a" * 32
    message_sid = "SM" + "b" * 32
    doc = {"_id": message_id, "workspace_id": "workspace-a", "lead_id": str(lead_id),
           "twilio_sid": message_sid, "to": "+919876543210", "body": "Hello", "status": "queued"}
    config = {"account_sid": sid, "encrypted_auth_token": sms.encrypt("workspace-a", "twilio_sms", {"auth_token": "private-token"})}
    db = SimpleNamespace(
        crm_sms_messages=SimpleNamespace(find_one=AsyncMock(return_value=doc), update_one=AsyncMock()),
        workspace_sms_configs=SimpleNamespace(find_one=AsyncMock(return_value=config)),
    )
    get = AsyncMock(return_value=httpx.Response(200, json={"status": "delivered", "error_code": None}))
    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def get(self, *args, **kwargs):
            return await get(*args, **kwargs)
    monkeypatch.setattr(sms.httpx, "AsyncClient", lambda **kwargs: Client())
    async def run():
        result = await sms.refresh_message("workspace-a", str(lead_id), str(message_id), request_for(db))
        assert result["status"] == "delivered"
        assert get.await_args.args[0].endswith(f"/Messages/{message_sid}.json")
        db.crm_sms_messages.find_one.assert_awaited_with({"_id": message_id, "workspace_id": "workspace-a", "lead_id": str(lead_id)})
    asyncio.run(run())


def test_connection_failure_reports_no_request_was_sent(monkeypatch):
    monkeypatch.setenv("VOICE_CREDENTIAL_KEYS", Fernet.generate_key().decode())
    lead_id = ObjectId()
    sid = "AC" + "a" * 32
    config = {"enabled": True, "account_sid": sid, "from_number": "+14155550123",
              "encrypted_auth_token": sms.encrypt("workspace-a", "twilio_sms", {"auth_token": "private-token"})}
    db = SimpleNamespace(
        crm_leads=SimpleNamespace(find_one=AsyncMock(return_value={"_id": lead_id, "phone": "+14155550124"})),
        workspace_sms_configs=SimpleNamespace(find_one=AsyncMock(return_value=config)),
        crm_sms_messages=SimpleNamespace(insert_one=AsyncMock()),
    )
    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("proxy unavailable")
    monkeypatch.setattr(sms.httpx, "AsyncClient", lambda **kwargs: Client())
    async def run():
        with pytest.raises(HTTPException, match="request was not sent"):
            await sms.send_message("workspace-a", str(lead_id), request_for(db), {"text": "Hello"})
        db.crm_sms_messages.insert_one.assert_not_awaited()
    asyncio.run(run())
