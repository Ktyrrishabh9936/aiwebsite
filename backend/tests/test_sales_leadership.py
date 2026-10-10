import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError
import pytest
import sales_leadership as sales

NOW = datetime(2026, 10, 9, 9, tzinfo=timezone.utc)
WS, LEAD = ObjectId(), ObjectId()
PROFILE = {"organisation": "Studio", "offerings": "Consulting", "ideal_customer": "Agencies",
           "team_capacity": "Two salespeople", "monthly_revenue_target": 200000,
           "business_stage": "existing", "offer_confidence": "validated", "timezone": "UTC"}


def lead(**updates):
    return {"_id": LEAD, "workspace_id": str(WS), "field_values": {"full_name": "Sarah"}, "status": "proposal",
            "updated_at": (NOW-timedelta(days=9)).isoformat(), "sales_assignment": {"sales_agent_id": "owner", "sales_agent_name": "Priya"}, **updates}


def matches(row, query):
    for key, expected in query.items():
        value = row.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]: return False
            if "$ne" in expected and value == expected["$ne"]: return False
            if "$exists" in expected and (key in row) != expected["$exists"]: return False
        elif value != expected: return False
    return True


class Cursor:
    def __init__(self, rows): self.rows = rows
    def sort(self, *args): return self
    async def to_list(self, limit): return deepcopy(self.rows[:limit])


class Collection:
    def __init__(self, rows=()): self.rows = deepcopy(list(rows)); self.writes = 0
    def find(self, query): return Cursor([row for row in self.rows if matches(row, query)])
    async def count_documents(self, query): return len([row for row in self.rows if matches(row, query)])
    async def find_one(self, query): return next((deepcopy(row) for row in self.rows if matches(row, query)), None)
    async def update_one(self, query, update, upsert=False):
        self.writes += 1
        row = next((r for r in self.rows if matches(r, query)), None)
        if row is None and upsert:
            self.rows.append({**query, **update.get("$setOnInsert", {})}); return SimpleNamespace(matched_count=0)
        if row is not None: row.update(update.get("$set", {}))
        return SimpleNamespace(matched_count=int(row is not None))


def database(leads=(), tasks=()):
    return SimpleNamespace(crm_leads=Collection(leads), tasks=Collection(tasks), crm_sales_people=Collection(),
                           catalog_items=Collection(), workspaces=Collection([{"_id": WS}]), notifications=Collection())


def test_stage_thresholds_and_future_commitments():
    row = lead()
    assert any(s["code"] == "stale" for s in sales.lead_insight(row, [], {}, NOW)["signals"])
    profile = {"stage_stale_days": {"proposal": 12}}
    assert not sales.lead_insight(row, [], profile, NOW)["signals"]
    task = {"_id": ObjectId(), "lead_id": str(LEAD), "status": "pending", "scheduled_time": (NOW+timedelta(days=2)).isoformat(), "source": "crm_reminder"}
    assert not sales.lead_insight(row, [task], {}, NOW)["signals"]


def test_overdue_work_is_surfaced_without_duplicate_qualification():
    row = lead(qualification_call={"status": "scheduled"})
    task = {"_id": ObjectId(), "lead_id": str(LEAD), "status": "pending", "scheduled_time": (NOW-timedelta(days=1)).isoformat()}
    codes = [s["code"] for s in sales.lead_insight(row, [task], {}, NOW)["signals"]]
    assert codes == ["overdue_followup", "qualification_pending"]


@pytest.mark.parametrize("updates", [{"status": "won"}, {"customer_status": "customer"}, {"deleted_at": NOW.isoformat()}, {"qualification_call": {"qualification_category": "junk"}}])
def test_closed_and_junk_leads_are_not_sales_risks(updates):
    insight = sales.lead_insight(lead(**updates), [], {}, NOW)
    assert insight["closed"] and not insight["signals"]


def test_snapshot_does_not_invent_pipeline_value_or_modify_crm():
    async def run():
        db = database([lead(field_values={"full_name": "Sarah", "budget": 500000})])
        ws = {"_id": WS, "sales_profile": PROFILE}
        report = await sales.snapshot(db, ws, NOW)
        assert report["known_pipeline_value"] is None
        assert report["unpriced_opportunities"] == 1
        ws["sales_profile"] = {**PROFILE, "opportunity_value_field": "deal_value"}
        db.crm_leads.rows[0]["field_values"]["deal_value"] = "150000"
        report = await sales.snapshot(db, ws, NOW)
        assert report["known_pipeline_value"] == "150000"
        assert db.crm_leads.writes == 0
    asyncio.run(run())


def test_test_leads_do_not_inflate_the_sales_briefing():
    async def run():
        db = database([lead(is_test_lead=True)])
        report = await sales.snapshot(db, {"_id": WS, "sales_profile": PROFILE}, NOW)
        assert report["total_leads"] == 0
        assert not report["priorities"]
    asyncio.run(run())


def test_sales_task_creation_is_idempotent_and_preserves_existing_followups():
    async def run():
        db = database([lead()])
        ws = {"_id": WS, "sales_profile": PROFILE}
        report = await sales.snapshot(db, ws, NOW)
        await sales.synchronise_tasks(db, ws, report)
        await sales.synchronise_tasks(db, ws, report)
        assert len(db.tasks.rows) == 1
        task = db.tasks.rows[0]
        assert task["source"] == "sales_manager" and task["requires_approval"]
        assert db.crm_leads.writes == 0
        reminder = {"_id": ObjectId(), "workspace_id": str(WS), "lead_id": str(LEAD), "status": "pending", "source": "qualification_engine"}
        db = database([lead()], [reminder])
        await sales.synchronise_tasks(db, ws, report)
        assert db.tasks.rows == [reminder]
    asyncio.run(run())


def test_completed_evidence_is_not_recreated_and_closed_lead_tasks_are_cancelled():
    async def run():
        db = database([lead()]); ws = {"_id": WS, "sales_profile": PROFILE}
        report = await sales.snapshot(db, ws, NOW)
        await sales.synchronise_tasks(db, ws, report)
        db.tasks.rows[0]["status"] = "done"
        await sales.synchronise_tasks(db, ws, report)
        assert len(db.tasks.rows) == 1 and db.tasks.rows[0]["status"] == "done"
        db.tasks.rows[0]["status"] = "pending"; db.crm_leads.rows[0]["status"] = "won"
        await sales.synchronise_tasks(db, ws, await sales.snapshot(db, ws, NOW))
        assert db.tasks.rows[0]["status"] == "cancelled"
    asyncio.run(run())


def test_morning_review_is_once_per_local_day():
    async def run():
        db = database([lead()]); ws = {"_id": WS, "sales_profile": {**PROFILE, "timezone": "Asia/Kolkata", "morning_hour": 8}}
        await sales.morning_review(db, ws, datetime(2026,10,9,1,tzinfo=timezone.utc))
        assert not db.notifications.rows
        await sales.morning_review(db, ws, NOW)
        await sales.morning_review(db, ws, NOW)
        assert len(db.notifications.rows) == 1
        assert len(db.tasks.rows) == 1
    asyncio.run(run())


def test_profile_and_outcome_validation():
    assert sales.SalesProfile(**PROFILE).voice_setup == "skipped"
    with pytest.raises(ValidationError): sales.SalesProfile(**{**PROFILE, "timezone": "invalid"})
    with pytest.raises(ValidationError): sales.SalesProfile(**{**PROFILE, "stage_stale_days": {"proposal": 0}})
    with pytest.raises(ValidationError): sales.Outcome(outcome="   ")


def test_strategy_requires_setup_and_never_deletes_tasks(monkeypatch):
    import agents
    model = AsyncMock(return_value={"strategy_summary": "Improve proposal conversion", "months": [{"month_number": 1, "goal": "Recover stalled proposals"}]})
    monkeypatch.setattr(agents, "build_roadmap", model)
    async def run():
        db = database([lead()]); ws = {"_id": WS, "brain_status": "ready", "model_id": "test"}
        with pytest.raises(HTTPException): await sales.sales_strategy(db, ws)
        ws["sales_profile"] = PROFILE
        await sales.sales_strategy(db, ws)
        context = model.call_args.args[1]["sales_context"]
        assert context["organisation"]["monthly_revenue_target"] == 200000
        assert context["live_sales"]["total_leads"] == 1
        assert not hasattr(db.tasks, "delete_many")
    asyncio.run(run())


def test_endpoints_reject_non_owner_before_reading_sales_data(monkeypatch):
    async def denied(*args): raise HTTPException(403, "Forbidden")
    monkeypatch.setattr(sales, "get_current_user_and_workspace", denied)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=database())))
    with pytest.raises(HTTPException) as exc: asyncio.run(sales.briefing(str(WS), request))
    assert exc.value.status_code == 403
