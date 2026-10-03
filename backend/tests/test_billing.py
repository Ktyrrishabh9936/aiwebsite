from datetime import datetime, timezone
from decimal import Decimal

import asyncio
import pytest
from bson import ObjectId
from fastapi import HTTPException

import billing
from billing import billing_summary, price_event, rate_card


def test_monthly_credit_combines_workspaces_and_flags_unpriced_calls():
    rates = {"bedrock::model-a": (Decimal("2"), Decimal("8"))}
    events = [
        {"workspace_id": "one", "provider": "bedrock", "model": "model-a", "metered": True, "input_tokens": 1_000_000, "output_tokens": 500_000},
        {"workspace_id": "two", "provider": "bedrock", "model": "model-a", "metered": True, "input_tokens": 500_000, "output_tokens": 0},
        {"workspace_id": "two", "provider": "bedrock", "model": "unknown", "metered": True, "input_tokens": 100, "output_tokens": 20},
    ]
    summary = billing_summary(events, 2, datetime(2026, 10, 2, tzinfo=timezone.utc), rates, Decimal("100"))
    assert summary["period_start"] == "2026-10-01"
    assert summary["period_end_exclusive"] == "2026-11-01"
    assert summary["estimated_usage_usd"] == "7.00"
    assert summary["estimated_remaining_usd"] is None
    assert summary["priced_calls"] == 2
    assert summary["unpriced_calls"] == 1
    assert summary["workspace_count"] == 2


def test_complete_estimate_reports_remaining_and_overage():
    event = {"provider": "bedrock_mantle", "model": "model-b", "metered": True, "input_tokens": 2_000_000, "output_tokens": 0}
    rates = {"bedrock_mantle::model-b": (Decimal("60"), Decimal("1"))}
    summary = billing_summary([event], 1, datetime(2026, 10, 2, tzinfo=timezone.utc), rates, Decimal("100"))
    assert summary["estimate_complete"] is True
    assert summary["estimated_remaining_usd"] == "0.00"
    assert summary["estimated_overage_usd"] == "20.00"


def test_missing_or_non_bedrock_rates_are_never_silently_zero(monkeypatch):
    monkeypatch.setenv("AI_BILLING_RATES_JSON", '{"bedrock::model-a":{"input_per_million_usd":"3","output_per_million_usd":"15"}}')
    rates = rate_card()
    assert price_event({"provider": "bedrock", "model": "model-a", "metered": True, "input_tokens": 1_000_000}, rates) == Decimal("3")
    assert price_event({"provider": "openrouter", "model": "model-a", "metered": True, "input_tokens": 1_000_000}, rates) is None
    assert price_event({"provider": "bedrock", "model": "unknown", "metered": True, "input_tokens": 1_000_000}, rates) is None


def test_cached_tokens_need_separate_rates():
    event = {"provider": "bedrock", "model": "model-a", "metered": True,
             "input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 1000}
    assert price_event(event, {"bedrock::model-a": (Decimal("1"), Decimal("2"))}) is None
    rates = {"bedrock::model-a": (Decimal("1"), Decimal("2"), Decimal("0.1"), Decimal("1.25"))}
    assert price_event(event, rates) == Decimal("0.0003")


def test_billing_endpoint_rejects_team_member(monkeypatch):
    async def context(request, db, ws_id):
        return {}, {"user_id": "owner"}, {"role": "sales_agent"}

    monkeypatch.setattr(billing, "db_from", lambda request: object())
    monkeypatch.setattr(billing, "member_context", context)
    with pytest.raises(HTTPException) as error:
        asyncio.run(billing.get_billing_summary("workspace", object()))
    assert error.value.status_code == 403


def test_billing_endpoint_uses_all_workspaces_of_owner(monkeypatch):
    first, second = ObjectId(), ObjectId()

    class WorkspaceCursor:
        async def to_list(self, length):
            return [{"_id": first}, {"_id": second}]

    class WorkspaceCollection:
        def find(self, query, projection):
            assert query == {"user_id": "owner"}
            return WorkspaceCursor()

    class EventCursor:
        def __aiter__(self):
            self.events = iter([{"provider": "bedrock", "model": "model-a", "metered": True,
                                 "input_tokens": 1_000_000, "output_tokens": 0}])
            return self

        async def __anext__(self):
            try:
                return next(self.events)
            except StopIteration:
                raise StopAsyncIteration

    class EventCollection:
        def find(self, query, projection):
            assert query["workspace_id"] == {"$in": [str(first), str(second)]}
            return EventCursor()

    class Db:
        workspaces = WorkspaceCollection()
        ai_usage_events = EventCollection()

    async def context(request, db, ws_id):
        return {}, {"user_id": "owner"}, {"role": "owner"}

    monkeypatch.setenv("AI_BILLING_RATES_JSON", '{"bedrock::model-a":{"input_per_million_usd":"2","output_per_million_usd":"8"}}')
    monkeypatch.setattr(billing, "db_from", lambda request: Db())
    monkeypatch.setattr(billing, "member_context", context)
    summary = asyncio.run(billing.get_billing_summary("workspace", object()))
    assert summary["workspace_count"] == 2
    assert summary["estimated_usage_usd"] == "2.00"
