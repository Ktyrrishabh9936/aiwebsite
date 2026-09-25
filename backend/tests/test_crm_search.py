import asyncio

import httpx
from bson import ObjectId
from fastapi import FastAPI

from auth import create_access_token
from crm import build_manual_lead, ensure_crm_settings, router as crm_router
from crm_workspace import router as workspace_router
from tests.test_qualification_integration import isolated


def test_crm_search_filters_records_and_pipeline(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "crm-search-test-only-long-signing-secret")

    async def run(db):
        user, ws = ObjectId(), ObjectId()
        await db.users.insert_one({"_id": user, "email": "search@example.test"})
        await db.workspaces.insert_one({"_id": ws, "user_id": str(user)})
        settings = await ensure_crm_settings(db, str(ws))
        rows = [
            ("Asha Sharma", "+14155550123", "Summer Homes", "2026-09-20T09:30:00+00:00"),
            ("Ravi Kumar", "+14155550124", "Winter Homes", "2026-09-22T10:30:00+00:00"),
            ("Neha Shah", "+14155550125", "Summer Homes", "2026-09-23T11:30:00+00:00"),
        ]
        for name, phone, campaign, created_at in rows:
            lead = build_manual_lead(str(ws), {"field_values": {"full_name": name, "phone": phone}}, settings)
            lead.update(meta_campaign_name=campaign, created_at=created_at)
            await db.crm_leads.insert_one(lead)

        app = FastAPI()
        app.state.db = db
        app.include_router(crm_router)
        app.include_router(workspace_router)
        base = f"/workspaces/{ws}/crm"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            client.headers["Authorization"] = "Bearer " + create_access_token(str(user), "search@example.test")
            async def records(**params):
                response = await client.get(base + "/leads", params={"page": 1, "limit": 1, **params})
                assert response.status_code == 200, response.text
                return response.json()

            assert (await records(search="asha"))["total"] == 1
            assert (await records(search="4155550124"))["total"] == 1
            assert (await records(search="winter"))["total"] == 1
            assert (await records(campaign="summer"))["total"] == 2
            filtered = await records(campaign="summer", created_from="2026-09-22T00:00:00+05:30")
            assert filtered["total"] == 1 and filtered["items"][0]["field_values"]["full_name"] == "Neha Shah"
            assert (await records(created_before="2026-09-21T00:00:00Z"))["total"] == 1
            assert (await records())["total"] == 3
            assert len((await records())["items"]) == 1

            board = await client.get(base + "/pipeline", params={"status": "new", "campaign": "summer", "created_before": "2026-09-22T00:00:00Z"})
            assert board.status_code == 200, board.text
            assert board.json()["total"] == 1
            value = await client.get(base + "/pipeline-value", params={"campaign": "winter", "search": "Ravi"})
            assert value.status_code == 200, value.text
            assert (await client.get(base + "/leads", params={"page": 1, "created_from": "2026-09-23T10:00:00Z", "created_before": "2026-09-22T10:00:00Z"})).status_code == 422

    asyncio.run(isolated(run))
