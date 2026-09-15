"""Real Mongo and ASGI tests; synthetic records only, no voice or AI requests."""
import asyncio
import uuid
from pathlib import Path

import httpx
import pytest
from bson import ObjectId
from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

import qualification_service as service
from qualification_api import router
from qualification_engine import QualificationData, QualificationProfile
from tests.test_qualification_engine import full_data


async def isolated(run):
    config = dotenv_values(Path(__file__).parents[1] / ".env")
    client = AsyncIOMotorClient(config.get("MONGO_URL", "mongodb://127.0.0.1:27017"), serverSelectionTimeoutMS=5000)
    name = "qual_test_" + uuid.uuid4().hex[:24]
    try:
        await run(client[name])
    finally:
        assert name.startswith("qual_test_")
        await client.drop_database(name)
        client.close()


async def seed(db):
    from crm import ensure_crm_settings, build_manual_lead
    ws, profile = ObjectId(), ObjectId()
    await db.qualification_profiles.insert_one({"_id": profile, "workspace_id": str(ws), **QualificationProfile().model_dump(mode="json")})
    await db.workspaces.insert_one({"_id": ws, "qualification_profile_id": str(profile)})
    lead = build_manual_lead(str(ws), {"field_values": {"phone": "+14155550123"}}, await ensure_crm_settings(db, str(ws)))
    await db.crm_leads.insert_one(lead)
    return str(ws), str(lead["_id"]), str(profile)


@pytest.fixture
def facts_only(monkeypatch):
    async def extract(call, profile, model):
        return QualificationData.model_validate(call.extracted_data), 100, call.summary
    monkeypatch.setattr(service, "extract_facts", extract)


def test_replay_after_partial_write_has_one_note_and_action(facts_only, monkeypatch):
    async def run(db):
        ws, lead_id, profile_id = await seed(db)
        controller = service.PlivoWebhookController(db)
        payload = {"CallUUID": "replay-call", "CallStatus": "completed", "qualification_data": full_data()}
        original = service.CRMLeadUpdateService.apply
        async def interrupted(self, *args, **kwargs):
            await original(self, *args, **kwargs)
            raise RuntimeError("Simulated interruption after CRM write")
        monkeypatch.setattr(service.CRMLeadUpdateService, "apply", interrupted)
        with pytest.raises(RuntimeError):
            await controller.process(ws, lead_id, payload)
        monkeypatch.setattr(service.CRMLeadUpdateService, "apply", original)
        await db.qualification_profiles.update_one({"_id": ObjectId(profile_id)}, {"$set": {"mandatory_qualification_criteria": [{"field": "product_fit", "operator": "eq", "value": False}]}})
        result = await controller.process(ws, lead_id, payload)
        assert result["qualification_result"]["lead_status"] == "SALES_READY"  # Frozen decision and profile.
        lead = await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
        assert len(lead["lead_notes"]) == 1
        assert await db.tasks.count_documents({"action_type": "SALES_CALL"}) == 1
        assert "qualification_lock" not in lead
    asyncio.run(isolated(run))


def test_concurrent_callbacks_are_serialized(facts_only, monkeypatch):
    async def run(db):
        ws, lead_id, _ = await seed(db)
        entered, release = asyncio.Event(), asyncio.Event()
        async def blocked(call, *args):
            entered.set()
            await release.wait()
            return QualificationData.model_validate(call.extracted_data), 100, call.summary
        monkeypatch.setattr(service, "extract_facts", blocked)
        controller = service.PlivoWebhookController(db)
        payload = {"CallUUID": "concurrent-call", "CallStatus": "completed", "qualification_data": full_data()}
        first = asyncio.create_task(controller.process(ws, lead_id, payload))
        await asyncio.wait_for(entered.wait(), 10)
        try:
            with pytest.raises(HTTPException) as exc:
                await controller.process(ws, lead_id, {**payload, "event_id": "second"})
            assert exc.value.status_code == 503
        finally:
            release.set()
            await first
        assert (await controller.process(ws, lead_id, payload))["duplicate"]
        await controller.process(ws, lead_id, {**payload, "event_id": "second"})
        assert await db.tasks.count_documents({}) == 1
        assert await db.crm_call_logs.count_documents({}) == 1
    asyncio.run(isolated(run))


def test_session_snapshot_old_calls_and_callback_task(facts_only):
    async def run(db):
        ws, lead_id, profile_id = await seed(db)
        snapshot = QualificationProfile().model_dump(mode="json")
        await db.plivo_call_sessions.insert_one({"_id": ObjectId(), "workspace_id": ws, "lead_id": lead_id, "provider_identifiers": {"request_uuid": "request-1", "call_uuid": "call-1"}, "profile_snapshot": snapshot, "profile_id": profile_id})
        await db.qualification_profiles.update_one({"_id": ObjectId(profile_id)}, {"$set": {"mandatory_qualification_criteria": [{"field": "product_fit", "operator": "eq", "value": False}]}})
        controller = service.PlivoWebhookController(db)
        first = await controller.process(ws, lead_id, {"CallUUID": "request-1", "CallStatus": "completed", "ended_at": "2030-01-01T10:00:00Z", "qualification_data": full_data()})
        assert first["qualification_result"]["lead_status"] == "SALES_READY"
        await controller.process(ws, lead_id, {"CallUUID": "call-1", "CallStatus": "completed", "recording_url": "https://example.test/recording"})
        assert await db.crm_call_logs.count_documents({}) == 1  # Request/call aliases are one attempt.
        updated = await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
        assert updated["qualification_call"]["recording_url"] == "https://example.test/recording"
        assert updated["qualification_call"]["call_uuid"] == "call-1"
        assert updated["call_attempt_count"] == 1
        assert await db.tasks.count_documents({"action_type": "SALES_CALL"}) == 1
        await controller.process(ws, lead_id, {"CallUUID": "call-2", "CallStatus": "completed", "callback_requested": True, "ended_at": "2030-01-02T10:00:00Z"})
        assert await db.tasks.count_documents({"action_type": "CALLBACK"}) == 1  # Missing time goes to a person.
        await controller.process(ws, lead_id, {"CallUUID": "call-1", "CallStatus": "completed", "ended_at": "2030-01-01T10:00:00Z", "event_id": "late"})
        lead = await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
        assert lead["call_outcome"] == "CALLBACK_REQUESTED"
        assert lead["qualification_call"]["call_uuid"] == "call-2"
        await controller.process(ws, lead_id, {"CallUUID": "call-2", "CallStatus": "do_not_call"})
        assert await db.tasks.count_documents({"status": "pending"}) == 0
    asyncio.run(isolated(run))


def test_profiles_api_auth_isolation_assignment_and_preview(monkeypatch):
    from auth import create_access_token
    monkeypatch.setenv("JWT_SECRET", "synthetic-qualification-test-secret-only")
    async def run(db):
        ws, lead_id, _ = await seed(db)
        user_id, foreign_ws = ObjectId(), ObjectId()
        await db.users.insert_one({"_id": user_id, "email": "qualification@example.test", "role": "user"})
        await db.workspaces.update_one({"_id": ObjectId(ws)}, {"$set": {"user_id": str(user_id)}})
        await db.workspaces.insert_one({"_id": foreign_ws, "user_id": str(ObjectId())})
        await db.qualification_profiles.create_index([("workspace_id", 1), ("campaign_id", 1)], unique=True, partialFilterExpression={"campaign_id": {"$type": "string"}})
        app = FastAPI()
        app.state.db = db
        app.include_router(router)
        base = f"/workspaces/{ws}/crm/qualification"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get(base + "/profiles")).status_code == 401
            client.headers["Authorization"] = "Bearer " + create_access_token(str(user_id), "qualification@example.test")
            assert (await client.get(f"/workspaces/{foreign_ws}/crm/qualification/profiles")).status_code == 403
            template = (await client.get(base + "/profiles")).json()["template"]
            profile = {**template, "product_name": "Test software", "campaign_id": "software-launch"}
            created = await client.post(base + "/profiles", json=profile)
            assert created.status_code == 200
            profile_id = created.json()["id"]
            assert (await client.post(base + "/profiles", json=profile)).status_code == 409
            assert (await client.put(base + f"/profiles/{profile_id}", json={**profile, "product_name": "Updated software"})).status_code == 200
            assert (await client.post(base + f"/profiles/{profile_id}/default")).status_code == 200
            assert (await client.put(base + f"/leads/{lead_id}/profile", json={"profile_id": profile_id})).status_code == 200
            foreign_profile = ObjectId()
            await db.qualification_profiles.insert_one({"_id": foreign_profile, "workspace_id": str(foreign_ws)})
            assert (await client.put(base + f"/leads/{lead_id}/profile", json={"profile_id": str(foreign_profile)})).status_code == 404
            assert (await client.put(base + "/leads/bad/profile", json={"profile_id": None})).status_code == 422
            preview = await client.post(base + "/preview", json={"profile": profile, "call": {"provider": "test", "provider_call_id": "preview", "lead_id": lead_id, "outcome_hint": "CONNECTED", "extracted_data": full_data()}})
            assert preview.status_code == 200 and preview.json()["lead_status"] == "SALES_READY"
            assert await db.tasks.count_documents({}) == 0
            assert await db.crm_call_logs.count_documents({}) == 0
            assert (await db.crm_leads.find_one({"_id": ObjectId(lead_id)}))["lead_status"] == "NEW"
            assert (await client.get(base + f"/leads/{lead_id}/history")).json() == []
            selected, selected_id = await service.resolve_profile(db, ws, {"campaign_id": "software-launch"}, {})
            assert selected_id == profile_id and selected.product_name == "Updated software"
            await db.workspaces.update_one({"_id": ObjectId(ws)}, {"$unset": {"qualification_profile_id": ""}})
            fallback, _ = await service.resolve_profile(db, ws, {}, {})
            from qualification_engine import CallResult, LeadQualificationEngine
            decision = LeadQualificationEngine().process(CallResult(provider="test", provider_call_id="unconfigured", lead_id=lead_id, extracted_data=full_data()), fallback)
            assert decision.lead_status == "PARTIALLY_QUALIFIED"
    asyncio.run(isolated(run))


def test_webhook_requires_auth_and_redacts_token(monkeypatch, facts_only):
    import base64
    import hashlib
    import hmac
    import server
    from plivo_calls import _signature_payload
    monkeypatch.setenv("PLIVO_AGENT_CALLBACK_TOKEN", "synthetic-callback-token")
    monkeypatch.setenv("PLIVO_AUTH_TOKEN", "synthetic-plivo-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://test")
    async def run(db):
        ws, lead_id, _ = await seed(db)
        monkeypatch.setattr(server, "db", db)
        app = FastAPI()
        app.add_api_route("/workspaces/{ws_id}/leads/{lead_id}/result", server.plivo_qualification_result, methods=["POST"])
        url = f"/workspaces/{ws}/leads/{lead_id}/result"
        payload = {"CallUUID": "auth-call", "CallStatus": "busy"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.post(url, json=payload)).status_code == 403
            assert await db.plivo_call_events.count_documents({}) == 0
            assert (await client.post(url + "?token=synthetic-callback-token", json=payload)).status_code == 200
            event = await db.plivo_call_events.find_one({})
            assert event["payload"]["token"] == "[redacted]"
            monkeypatch.delenv("PLIVO_AGENT_CALLBACK_TOKEN")
            assert (await client.post(url, json=payload)).status_code == 403
            nonce = "synthetic-nonce"
            signature = base64.b64encode(hmac.new(b"synthetic-plivo-secret", _signature_payload("POST", "http://test" + url, nonce, payload).encode(), hashlib.sha256).digest()).decode()
            response = await client.post(url, data=payload, headers={"X-Plivo-Signature-V3": signature, "X-Plivo-Signature-V3-Nonce": nonce})
            assert response.status_code == 200
            assert response.json()["qualification_result"]["lead_status"] == "PENDING"
    asyncio.run(isolated(run))
