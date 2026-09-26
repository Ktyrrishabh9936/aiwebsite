import asyncio
import base64
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError

import push_notifications as push


def matches(row, query):
    for key, expected in query.items():
        value = row.get(key)
        if isinstance(expected, dict):
            for op, operand in expected.items():
                if op == "$in" and value not in operand: return False
                if op == "$lt" and not value < operand: return False
                if op == "$lte" and not value <= operand: return False
                if op == "$gte" and not value >= operand: return False
        elif isinstance(value, list):
            if expected not in value: return False
        elif value != expected: return False
    return True


class Cursor:
    def __init__(self, rows): self.rows = copy.deepcopy(rows)
    def sort(self, key, direction):
        self.rows.sort(key=lambda row: row[key], reverse=direction < 0)
        return self
    def __aiter__(self):
        async def iterate():
            for row in self.rows: yield row
        return iterate()


class Collection:
    def __init__(self, rows=()): self.rows = copy.deepcopy(list(rows))
    def find(self, query): return Cursor([row for row in self.rows if matches(row, query)])
    async def find_one(self, query): return copy.deepcopy(next((row for row in self.rows if matches(row, query)), None))
    async def update_one(self, query, update, upsert=False):
        row = next((row for row in self.rows if matches(row, query)), None)
        if row is None:
            if not upsert: return
            row = {**query, **update.get("$setOnInsert", {})}
            self.rows.append(row)
        row.update(update.get("$set", {}))
        for key, value in update.get("$inc", {}).items(): row[key] = row.get(key, 0) + value
    async def find_one_and_update(self, query, update, **kwargs):
        row = await self.find_one(query)
        if row is None: return None
        await self.update_one(query, update)
        return await self.find_one({"_id": row["_id"]})
    async def delete_one(self, query): self.rows = [row for row in self.rows if not matches(row, query)]


@pytest.fixture
def fixture(monkeypatch):
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "public")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "private")
    now = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
    user, workspace, lead, task = [ObjectId() for _ in range(4)]
    db = SimpleNamespace(
        users=Collection([{"_id": user}]), workspaces=Collection([{"_id": workspace, "user_id": str(user)}]),
        crm_leads=Collection([{"_id": lead, "workspace_id": str(workspace), "full_name": "Asha"}]),
        tasks=Collection([{"_id": task, "workspace_id": str(workspace), "lead_id": str(lead), "created_by": str(user),
                           "title": "Call Asha", "status": "pending", "source": "crm_reminder",
                           "scheduled_time": (now - timedelta(minutes=1)).isoformat()}]),
        push_subscriptions=Collection([{"_id": "device", "user_id": str(user), "workspace_ids": [str(workspace)],
                                        "active": True, "subscription": {"endpoint": "https://fcm.googleapis.com/test"}}]),
        push_deliveries=Collection())
    return db, now


def test_due_reminder_sent_once_and_rescheduled_reminder_sent_again(fixture):
    db, now = fixture
    sender = AsyncMock()
    async def run():
        assert (await push.dispatch_due(db, now=now, sender=sender))["sent"] == 1
        assert (await push.dispatch_due(db, now=now, sender=sender))["sent"] == 0
        db.tasks.rows[0]["scheduled_time"] = (now - timedelta(seconds=10)).isoformat()
        assert (await push.dispatch_due(db, now=now, sender=sender))["sent"] == 1
    asyncio.run(run())
    assert sender.await_count == 2
    payload = sender.call_args.args[1]
    assert "Asha" in payload["body"]
    assert payload["url"].endswith("?lead=" + db.tasks.rows[0]["lead_id"])


@pytest.mark.parametrize("change", ["completed", "future", "old", "revoked", "deleted", "disabled", "other_user"])
def test_unavailable_or_ineligible_reminders_are_not_sent(fixture, change):
    db, now = fixture
    if change == "completed": db.tasks.rows[0]["status"] = "done"
    if change == "future": db.tasks.rows[0]["scheduled_time"] = (now + timedelta(minutes=5)).isoformat()
    if change == "old": db.tasks.rows[0]["scheduled_time"] = (now - timedelta(days=2)).isoformat()
    if change == "revoked": db.workspaces.rows[0]["user_id"] = str(ObjectId())
    if change == "deleted": db.crm_leads.rows[0]["deleted_at"] = now.isoformat()
    if change == "disabled": db.push_subscriptions.rows[0]["active"] = False
    if change == "other_user": db.push_subscriptions.rows[0]["user_id"] = str(ObjectId())
    sender = AsyncMock()
    assert asyncio.run(push.dispatch_due(db, now=now, sender=sender))["sent"] == 0
    sender.assert_not_awaited()


def test_transient_failures_retry_after_lease_and_expired_devices_disable(fixture):
    db, now = fixture
    sender = AsyncMock(side_effect=RuntimeError("temporary"))
    async def run():
        assert (await push.dispatch_due(db, now=now, sender=sender))["failed"] == 1
        await push.dispatch_due(db, now=now, sender=sender)
        assert sender.await_count == 1
        error = RuntimeError("gone")
        error.response = SimpleNamespace(status_code=410)
        sender.side_effect = error
        assert (await push.dispatch_due(db, now=now + timedelta(minutes=3), sender=sender))["failed"] == 1
    asyncio.run(run())
    assert db.push_subscriptions.rows[0]["active"] is False


def test_dispatch_requires_cron_secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "secret")
    request = SimpleNamespace(headers={"authorization": "Bearer wrong"})
    with pytest.raises(HTTPException) as error:
        asyncio.run(push.dispatch(request))
    assert error.value.status_code == 401


def test_subscription_rejects_arbitrary_endpoints():
    keys = {"auth": base64.urlsafe_b64encode(bytes(16)).decode(), "p256dh": base64.urlsafe_b64encode(bytes(65)).decode()}
    with pytest.raises(ValidationError):
        push.DeviceInput(endpoint="https://localhost/internal", keys=keys)
    assert push.DeviceInput(endpoint="https://fcm.googleapis.com/push/test", keys=keys).keys == keys
