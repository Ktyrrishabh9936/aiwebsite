import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from bson import ObjectId
from fastapi import HTTPException
import pytest
import customer_lifecycle as lifecycle

WS, ROOT = str(ObjectId()), ObjectId()


def purchase(**extra):
    return {"_id": ROOT, "workspace_id": WS, "status": "won", "customer_status": "customer",
            "field_values": {"full_name": "Sarah", "phone": "+919999999999"},
            "conversion_type": "single_payment", "payment_summary": {"total_amount": "100"},
            "receipts": [{"amount": "100", "status": "Paid"}], **extra}


def test_ltv_is_collected_revenue_and_repeat_is_an_open_separate_deal():
    root = purchase()
    repeat = purchase(_id=ObjectId(), customer_id=str(ROOT), status="new", customer_status="lead",
                      repeat_request="Premium service", opportunity_kind="upsell", receipts=[], payment_summary={})
    archived = purchase(_id=ObjectId(), customer_id=str(ROOT), deleted_at="2026-10-10", receipts=[{"amount": "40"}, {"amount": "60", "status": "failed"}])
    result = lifecycle.customer_summary(root, [root, repeat, archived], "INR")
    assert result["ltv"] == "140"
    assert result["lifecycle"] == "customer"
    assert result["open_opportunities"] == 1
    assert root["status"] == "won" and len(root["receipts"]) == 1


def test_partial_and_unknown_payments_are_not_fully_paid_customers():
    root = purchase(receipts=[{"amount": "25", "status": "Paid"}])
    result = lifecycle.customer_summary(root, [root], "INR")
    assert result["lifecycle"] == "won_payment_pending"
    assert result["outstanding"] == "75"
    assert not lifecycle.payment_state(purchase(receipts=[], payment_summary={}))[2]


def test_repeat_creation_preserves_customer_payments_and_skips_initial_qualification(monkeypatch):
    async def run():
        root = purchase()
        db = SimpleNamespace(crm_leads=SimpleNamespace(find_one=AsyncMock(return_value=deepcopy(root)), insert_one=AsyncMock()))
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))
        monkeypatch.setattr(lifecycle, "customer_history", AsyncMock(return_value={}))
        from crm import DEFAULT_FIELDS, DEFAULT_STATES
        monkeypatch.setattr(lifecycle, "ensure_crm_settings", AsyncMock(return_value={"fields": DEFAULT_FIELDS, "states": DEFAULT_STATES}))
        result = await lifecycle.repeat_opportunity(WS, str(ROOT), request, {"request": "New service", "kind": "upsell"})
        created = db.crm_leads.insert_one.call_args.args[0]
        assert created["customer_id"] == str(ROOT)
        assert created["customer_status"] == "lead" and created["status"] == "new"
        assert created["receipts"] == [] and not created["auto_qualification_enabled"]
        assert result["id"] != str(ROOT)
        assert root["receipts"] == [{"amount": "100", "status": "Paid"}]
    asyncio.run(run())


def test_customer_history_is_workspace_scoped():
    async def run():
        db = SimpleNamespace(crm_leads=SimpleNamespace(find_one=AsyncMock(return_value=None)))
        with pytest.raises(HTTPException) as error:
            await lifecycle.customer_history(db, WS, str(ROOT))
        assert error.value.status_code == 404
        assert db.crm_leads.find_one.call_args.args[0]["workspace_id"] == WS
    asyncio.run(run())


def test_customer_deletion_preserves_deals_and_receipts(monkeypatch):
    async def run():
        db = SimpleNamespace(crm_leads=SimpleNamespace(update_one=AsyncMock()))
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))
        monkeypatch.setattr(lifecycle, "customer_history", AsyncMock(return_value={}))
        result = await lifecycle.delete_customer(WS, str(ROOT), request)
        query, update = db.crm_leads.update_one.call_args.args
        assert query == {"workspace_id": WS, "_id": ROOT}
        assert list(update["$set"]) == ["customer_deleted_at"]
        assert result["payment_history_preserved"]
    asyncio.run(run())
