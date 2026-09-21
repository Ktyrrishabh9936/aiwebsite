"""Exercise the real aggregation pipeline and persisted reviews in an isolated Mongo database."""
import asyncio
from copy import deepcopy

import httpx
from bson import ObjectId
from fastapi import FastAPI

from auth import create_access_token
from crm_performance import router
from tests.test_crm_performance import DAY, lead, log
from tests.test_qualification_integration import isolated


def test_real_aggregation_dates_isolation_profiles_and_persisted_reviews(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "performance-integration-only-signing-secret")

    async def run(db):
        user, ws, foreign_ws, profile = ObjectId(), ObjectId(), ObjectId(), ObjectId()
        await db.users.insert_one({"_id": user, "name": "John", "email": "performance@example.test"})
        await db.workspaces.insert_many([{"_id": ws, "user_id": str(user)}, {"_id": foreign_ws, "user_id": str(ObjectId())}])
        await db.qualification_profiles.insert_one({"_id": profile, "workspace_id": str(ws), "product_name": "Homes"})
        doc = lead()
        doc["workspace_id"] = str(ws)
        doc["qualification_call"]["qualification_profile_id"] = str(profile)
        await db.crm_leads.insert_one(doc)
        for patch in [{"workspace_id": str(foreign_ws)}, {"created_at": "2026-09-19T23:59:59+00:00"},
                      {"created_at": "2026-09-21T00:00:00+00:00"}, {"deleted_at": DAY}]:
            await db.crm_leads.insert_one({**deepcopy(doc), "_id": ObjectId(), **patch})
        call = {**log(), "workspace_id": str(ws), "lead_id": str(doc["_id"]), "kind": "qualification_engine", "profile_id": str(profile)}
        await db.crm_call_logs.insert_one(call)
        await db.plivo_call_sessions.insert_one({"workspace_id": str(ws), "lead_id": str(doc["_id"]), "created_at": DAY,
            "provider_identifiers": {"call_uuid": "call"}, "provider": "plivo", "profile_id": str(profile), "call_status": "completed", "duration": 90})
        # A malformed foreign-workspace link to the same lead must never enter the report.
        await db.crm_call_logs.insert_one({**call, "_id": ObjectId(), "workspace_id": str(foreign_ws), "provider_call_id": "foreign"})
        await db.tasks.insert_one({"workspace_id": str(foreign_ws), "lead_id": str(doc["_id"]), "source": "qualification_engine", "status": "pending", "action_type": "FOLLOW_UP"})
        app = FastAPI(); app.state.db = db; app.include_router(router)
        base = f"/workspaces/{ws}/crm"
        params = {"start": "2026-09-20", "end": "2026-09-20"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get(base + "/performance", params=params)).status_code == 401
            client.headers["Authorization"] = "Bearer " + create_access_token(str(user), "performance@example.test")
            assert (await client.get(base.replace(str(ws), str(foreign_ws)) + "/performance", params=params)).status_code == 403
            response = await client.get(base + "/performance", params=params)
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["funnel"]["total_leads"] == 1
            assert data["calling"]["calls_attempted"] == 1
            assert data["calling"]["average_duration_seconds"] == 60
            assert data["qualification"]["follow_up_required"] == 0
            assert data["reviews"]["accuracy"] is None
            path = base + f"/leads/{doc['_id']}/qualification-review"
            state = (await client.get(path)).json()
            for status, expected in [("correct", 100), ("incorrect", 0)]:
                result = await client.put(path, json={"status": status, "source_version": state["source_version"], "note": "Human verified"})
                assert result.status_code == 200, result.text
                data = (await client.get(base + "/performance", params={**params, "profile_id": str(profile)})).json()
                assert data["reviews"]["accuracy"] == expected
                assert data["reviews"]["reviewed"] == 1
            persisted = await db.crm_leads.find_one({"_id": doc["_id"]})
            assert persisted["qualification_review"]["reviewed_by"] == str(user)
            assert len(persisted["timeline"]) == 2
            assert persisted["timeline"][1]["previous_status"] == "correct"
            assert (await client.get(base + "/performance", params={**params, "status": "won"})).json()["funnel"]["total_leads"] == 0
            assert (await client.get(base + "/performance", params={"start": "2026-09-22", "end": "2026-09-20"})).status_code == 422
            assert (await client.get(base + "/performance", params={**params, "profile_id": str(ObjectId())})).status_code == 404
    asyncio.run(isolated(run))
