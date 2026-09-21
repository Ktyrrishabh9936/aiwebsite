import asyncio
from datetime import datetime, timezone

import httpx
import pytest
from bson import ObjectId
from fastapi import FastAPI
from pydantic import ValidationError

from auth import create_access_token
from crm import build_manual_lead, ensure_crm_settings
from crm_workspace import ReminderInput, router
from tests.test_qualification_integration import isolated


def test_reminder_requires_timezone_and_nonempty_title():
    for data in [{"title": " ", "due_at": "2026-09-20T10:00:00Z"}, {"title": "Call", "due_at": "2026-09-20T10:00:00"}]:
        with pytest.raises(ValidationError):
            ReminderInput(**data)
    assert ReminderInput(title="Call", due_at="2026-09-20T10:00:00+05:30").due_at.hour == 4


def test_reminders_and_pipeline_persist_with_workspace_isolation(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "crm-workspace-test-only-long-signing-secret")
    async def run(db):
        user, ws, other = ObjectId(), ObjectId(), ObjectId()
        await db.users.insert_one({"_id": user, "email": "planner@example.test"})
        await db.workspaces.insert_many([{"_id": ws, "user_id": str(user)}, {"_id": other, "user_id": str(ObjectId())}])
        settings = await ensure_crm_settings(db, str(ws))
        doc = build_manual_lead(str(ws), {"field_values": {"phone": "+14155550123", "full_name": "Planner lead"}}, settings)
        await db.crm_leads.insert_one(doc)
        foreign = {**doc, "_id": ObjectId(), "workspace_id": str(other)}
        await db.crm_leads.insert_one(foreign)
        app = FastAPI(); app.state.db = db; app.include_router(router)
        base = f"/workspaces/{ws}/crm"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get(base + "/reminders")).status_code == 401
            client.headers["Authorization"] = "Bearer " + create_access_token(str(user), "planner@example.test")
            assert (await client.get(base.replace(str(ws), str(other)) + "/reminders")).status_code == 403
            payload = {"title": "Share brochure", "note": "Discuss 3 BHK pricing", "due_at": "2026-09-20T10:00:00+05:30"}
            assert (await client.post(base + f"/leads/{foreign['_id']}/reminders", json=payload)).status_code == 404
            response = await client.post(base + f"/leads/{doc['_id']}/reminders", json=payload)
            assert response.status_code == 200, response.text
            task = response.json(); task_id = task["id"]
            assert task["requires_approval"] is True and task["source"] == "crm_reminder"
            assert task["created_by"] == str(user)
            params = {"start": "2026-09-20T00:00:00+05:30", "end": "2026-09-21T00:00:00+05:30"}
            data = (await client.get(base + "/reminders", params=params)).json()
            assert data["total"] == 1 and data["items"][0]["lead_name"] == "Planner lead"
            assert data["items"][0]["objective"] == "Discuss 3 BHK pricing"
            assert (await client.get(base + "/reminders", params={"start": "2026-09-21T00:00:00Z"})).json()["total"] == 0
            assert (await client.patch(base + f"/reminders/{task_id}", json={"status": "done"})).status_code == 200
            assert (await client.get(base + "/reminders")).json()["total"] == 0
            assert (await client.get(base + "/reminders", params={"status": "done"})).json()["total"] == 1
            assert (await client.patch(base + f"/reminders/{task_id}", json={**payload, "due_at": "2026-09-22T12:00:00Z"})).status_code == 200
            persisted = await db.tasks.find_one({"_id": ObjectId(task_id)})
            assert len(persisted["timeline"]) == 3
            assert persisted["scheduled_time"] == "2026-09-22T12:00:00+00:00"
            assert (await client.patch(base.replace(str(ws), str(other)) + f"/reminders/{task_id}", json={"status": "pending"})).status_code == 403
            board = await client.get(base + "/pipeline", params={"status": doc["status"]})
            assert board.status_code == 200, board.text
            assert board.json()["total"] == 1
            assert "qualification_call" not in board.json()["items"][0]
            assert (await client.get(base + "/pipeline", params={"status": doc["status"], "offset": 1})).json()["items"] == []
            assert (await client.get(base + "/pipeline", params={"status": doc["status"], "search": "missing"})).json()["total"] == 0
            next_status = next(s["key"] for s in settings["states"] if s["key"] != doc["status"])
            moved = await client.patch(base + f"/pipeline/leads/{doc['_id']}", json={"status": next_status})
            assert moved.status_code == 200, moved.text
            assert moved.json()["status"] == next_status
            assert (await client.patch(base + f"/pipeline/leads/{foreign['_id']}", json={"status": next_status})).status_code == 404
    asyncio.run(isolated(run))
