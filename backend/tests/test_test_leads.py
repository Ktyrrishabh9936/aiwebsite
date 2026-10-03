import asyncio
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from fastapi import HTTPException

import crm
import google_sheets
import httpx
from fastapi import FastAPI
from auth import create_access_token
from crm_performance import router as performance_router
from tests.test_qualification_integration import isolated
from crm_performance import PerformanceTotals, date_bounds, performance_pipeline
from sales_team import performance_rows


def test_metrics_filter_keeps_legacy_leads_and_record_queries_keep_test_leads():
    query = crm.lead_query("workspace", exclude_test=True)
    assert query["is_test_lead"] == {"$ne": True}
    assert query["deleted_at"] is None
    assert "is_test_lead" not in crm.lead_query("workspace")
    start, end = date_bounds(date(2026, 9, 1), date(2026, 9, 30))
    assert performance_pipeline("workspace", start, end)[0]["$match"]["is_test_lead"] == {"$ne": True}


def test_test_lead_changes_no_report_totals_including_calls_and_revenue():
    start, end = date_bounds(date(2026, 9, 1), date(2026, 9, 30))
    real = {"status": "new", "created_at": start.isoformat()}
    test = {"is_test_lead": True, "status": "won", "customer_status": "customer", "created_at": start.isoformat(),
            "receipts": [{"amount": "1000", "status": "Paid", "created_at": start.isoformat()}],
            "crm_call_logs": [{"created_at": start.isoformat(), "provider_call_id": "test-call", "call_result": {"duration_seconds": 60, "call_status": "completed"}}]}
    totals = PerformanceTotals()
    totals.add(real, start, end)
    expected = deepcopy(totals.output())
    totals.add(test, start, end)
    assert totals.output() == expected
    assert crm.build_crm_analytics([real, test], now=start) == crm.build_crm_analytics([real], now=start)


def test_sales_attribution_excludes_test_leads():
    person_id = ObjectId()
    people = [{"_id": person_id, "name": "Sales", "role": "sales_agent"}]
    test = {"is_test_lead": True, "status": "won", "sales_assignment": {"sales_agent_id": str(person_id)},
            "opportunity": {"sale_status": "sold", "total_minor": 100000}}
    assert performance_rows(people, [test]) == performance_rows(people, [])


def test_flag_saves_unmarks_and_survives_other_edits(monkeypatch):
    async def run():
        lead_id = ObjectId()
        stored = {"_id": lead_id, "workspace_id": "workspace", "status": "new", "field_values": {"phone": "+14155550123"}}
        collection = SimpleNamespace(find_one=AsyncMock(side_effect=lambda query: deepcopy(stored)))
        async def update(query, changes):
            assert query == {"workspace_id": "workspace", "_id": lead_id}
            stored.update(changes["$set"])
        collection.update_one = AsyncMock(side_effect=update)
        db = SimpleNamespace(crm_leads=collection)
        monkeypatch.setattr(crm, "db_from", lambda request: db)
        monkeypatch.setattr(google_sheets, "sync_lead_status", AsyncMock())
        monkeypatch.setattr(crm, "ensure_crm_settings", AsyncMock(return_value={"states": deepcopy(crm.DEFAULT_STATES), "fields": deepcopy(crm.DEFAULT_FIELDS)}))
        for body, expected in [({"is_test_lead": True}, True), ({"status": "contacted"}, True), ({"is_test_lead": False}, False)]:
            result = await crm.update_lead("workspace", str(lead_id), None, body)
            assert result["is_test_lead"] is expected
        writes = collection.update_one.call_count
        for invalid in ["false", 1, None]:
            with pytest.raises(HTTPException) as error:
                await crm.update_lead("workspace", str(lead_id), None, {"is_test_lead": invalid})
            assert error.value.status_code == 422
        assert collection.update_one.call_count == writes
    asyncio.run(run())


def test_selecting_test_lead_persists_and_changes_real_reports(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-lead-autosave-only-signing-secret-long-enough")
    async def run(db):
        user, workspace = ObjectId(), ObjectId()
        ws_id = str(workspace)
        await db.users.insert_one({"_id": user, "email": "test-lead@example.test"})
        await db.workspaces.insert_one({"_id": workspace, "user_id": str(user)})
        settings = await crm.ensure_crm_settings(db, ws_id)
        lead = crm.build_manual_lead(ws_id, {"field_values": {"phone": "+14155550123"}}, settings)
        lead["created_at"] = "2026-09-20T10:00:00+00:00"
        await db.crm_leads.insert_one(lead)
        app = FastAPI(); app.state.db = db
        app.include_router(crm.router); app.include_router(performance_router)
        base = f"/workspaces/{ws_id}/crm"
        path = base + f"/leads/{lead['_id']}/test-lead"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.patch(path, json={"is_test_lead": True})).status_code == 401
            client.headers["Authorization"] = "Bearer " + create_access_token(str(user), "test-lead@example.test")
            for flag, count in [(True, 0), (False, 1)]:
                saved = await client.patch(path, json={"is_test_lead": flag})
                assert saved.status_code == 200, saved.text
                assert saved.json()["is_test_lead"] is flag
                stored = await db.crm_leads.find_one({"_id": lead["_id"]})
                assert stored["is_test_lead"] is flag
                assert stored["field_values"] == lead["field_values"]
                assert stored["status"] == lead["status"]
                result = await client.get(base + "/performance", params={"start": "2026-09-01", "end": "2026-09-30"})
                assert result.status_code == 200, result.text
                assert result.json()["funnel"]["total_leads"] == count
                overview = (await client.get(base + "/analytics/overview")).json()
                assert overview["totals"]["leads"] == count
                records = (await client.get(base + "/leads", params={"page": 1})).json()
                assert records["total"] == 1
                assert records["items"][0]["is_test_lead"] is flag
    asyncio.run(isolated(run))
