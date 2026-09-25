"""Authorization and pagination regression tests for the CRM hot paths."""

import asyncio
from datetime import datetime, timezone

import httpx
from bson import ObjectId
from fastapi import FastAPI

from auth import create_access_token
from crm import build_manual_lead, ensure_crm_settings, router
from tests.test_qualification_integration import isolated


def test_crm_router_authorization_bootstrap_and_database_pagination(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "crm-fast-path-test-signing-secret-long-enough")

    async def run(db):
        user_id, workspace_id, foreign_workspace_id = ObjectId(), ObjectId(), ObjectId()
        await db.users.insert_one({"_id": user_id, "email": "crm@example.test", "role": "user"})
        await db.workspaces.insert_many([
            {"_id": workspace_id, "user_id": str(user_id)},
            {"_id": foreign_workspace_id, "user_id": str(ObjectId())},
        ])
        await db.crm_leads.create_index([("workspace_id", 1), ("deleted_at", 1), ("created_at", -1)])
        settings = await ensure_crm_settings(db, str(workspace_id))
        for index in range(25):
            lead = build_manual_lead(
                str(workspace_id),
                {"field_values": {"phone": f"+91999999{index:04d}", "full_name": f"Lead {index}"}},
                settings,
            )
            lead["field_values"]["custom_interest"] = "Seaside villa" if index == 17 else "Apartment"
            lead["created_at"] = datetime(2026, 9, index % 20 + 1, tzinfo=timezone.utc).isoformat()
            lead["timeline"] = [{"large": "must not be included in a list response"}]
            lead["receipts"] = [{"large": "must not be included in a list response"}]
            await db.crm_leads.insert_one(lead)

        app = FastAPI()
        app.state.db = db
        app.include_router(router)
        base = f"/workspaces/{workspace_id}/crm"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get(base + "/settings")).status_code == 401
            client.headers["Authorization"] = "Bearer " + create_access_token(str(user_id), "crm@example.test")
            assert (await client.get(base.replace(str(workspace_id), str(foreign_workspace_id)) + "/leads", params={"page": 1})).status_code == 403

            response = await client.get(base + "/leads", params={"page": 2, "limit": 10})
            assert response.status_code == 200, response.text
            page = response.json()
            assert page["total"] == 25 and page["page"] == 2 and len(page["items"]) == 10
            assert "timeline" not in page["items"][0]
            assert "receipts" not in page["items"][0]

            explained = await db.command({
                "explain": {"find": "crm_leads", "filter": {"workspace_id": str(workspace_id), "deleted_at": None},
                            "sort": {"created_at": -1}, "limit": 10},
                "verbosity": "executionStats",
            })
            plan_text = str(explained["queryPlanner"]["winningPlan"])
            assert "'stage': 'SORT'" not in plan_text
            assert explained["executionStats"]["totalDocsExamined"] <= 10

            searched = (await client.get(base + "/leads", params={"page": 1, "search": "seaside"})).json()
            assert searched["total"] == 1
            detail = (await client.get(base + f"/leads/{searched['items'][0]['id']}")).json()
            assert detail["timeline"] and detail["receipts"]

            bootstrap = await client.get(base + "/bootstrap", params={"page": 1, "limit": 10})
            assert bootstrap.status_code == 200, bootstrap.text
            payload = bootstrap.json()
            assert payload["leads"]["total"] == 25
            assert payload["settings"]["workspace_id"] == str(workspace_id)
            assert payload["agents"]["agents"] == []

    asyncio.run(isolated(run))
