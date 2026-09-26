import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import crm
import plivo_calls


def test_manual_lead_can_skip_automatic_call_without_blocking_manual_call(monkeypatch):
    async def settings(*args):
        return {"fields": crm.DEFAULT_FIELDS, "states": crm.DEFAULT_STATES}
    monkeypatch.setattr(crm, "ensure_crm_settings", settings)
    real_schedule = plivo_calls.schedule_first_qualification_call
    schedule = AsyncMock()
    monkeypatch.setattr(plivo_calls, "schedule_first_qualification_call", schedule)
    saved = {}

    async def insert(doc):
        saved.update(doc)

    async def find(query):
        return saved

    db = SimpleNamespace(crm_leads=SimpleNamespace(insert_one=AsyncMock(side_effect=insert), find_one=AsyncMock(side_effect=find)))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))

    async def run():
        lead = await crm.create_lead("workspace-a", request, {
            "field_values": {"phone": "+919876543210", "full_name": "Already contacted"},
            "trigger_ai_call": False,
        })
        assert lead["auto_qualification_enabled"] is False
        assert lead["qualification_call"] == {}
        assert any(item["type"] == "ai_call_skipped" for item in lead["timeline"])
        schedule.assert_not_awaited()
        assert "do_not_call" not in lead

        result = await real_schedule(db, "workspace-a", str(saved["_id"]))
        assert result["status"] == "skipped"
        assert db.crm_leads.find_one.await_args.args[0]["_id"] == saved["_id"]
    asyncio.run(run())


def test_manual_lead_keeps_existing_call_behavior_by_default(monkeypatch):
    async def settings(*args):
        return {"fields": crm.DEFAULT_FIELDS, "states": crm.DEFAULT_STATES}
    monkeypatch.setattr(crm, "ensure_crm_settings", settings)
    schedule = AsyncMock()
    monkeypatch.setattr(plivo_calls, "schedule_first_qualification_call", schedule)
    saved = {}

    async def insert(doc):
        saved.update(doc)

    db = SimpleNamespace(crm_leads=SimpleNamespace(insert_one=AsyncMock(side_effect=insert), find_one=AsyncMock(side_effect=lambda query: saved)))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))

    async def run():
        lead = await crm.create_lead("workspace-a", request, {"field_values": {"phone": "+919876543211"}})
        assert lead["auto_qualification_enabled"] is True
        schedule.assert_awaited_once_with(db, "workspace-a", str(saved["_id"]))
    asyncio.run(run())
