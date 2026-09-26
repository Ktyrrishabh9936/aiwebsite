"""Role boundaries tested against synthetic Mongo records and real ASGI routes."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from bson import ObjectId
from fastapi import FastAPI

import auth
from crm import router as crm_router
from memberships import owner_router, invite_router, portal_router
from sales_team import router as team_router, shared_router
from workflows import router as workflow_router
from workspace_access import accessible_workspaces
from migrate_workspace_access import migrate
from tests.test_qualification_integration import isolated


def test_workspace_membership_lifecycle(monkeypatch):
    async def run(db):
        owner, agent, partner, other = [ObjectId() for _ in range(4)]
        ws, foreign = ObjectId(), ObjectId()
        agent_person, partner_person = ObjectId(), ObjectId()
        for uid, email in ((owner, "owner@example.com"), (agent, "agent@example.com"), (partner, "partner@example.com"), (other, "other@example.com")):
            await db.users.insert_one({"_id": uid, "email": email, "name": email.split("@")[0], "role": "user"})
        await db.workspaces.insert_many([{"_id": ws, "user_id": str(owner), "name": "Private workspace", "currency": "INR"}, {"_id": foreign, "user_id": str(other), "name": "Other workspace"}])
        for pid, name, role in ((agent_person, "Agent", "sales_agent"), (partner_person, "Partner", "channel_partner")):
            await db.crm_sales_people.insert_one({"_id": pid, "workspace_id": str(ws), "name": name, "role": role, "active": True})
        await migrate(db)
        current = {"id": owner}
        monkeypatch.setattr(auth, "access_token_payload", lambda request: {"sub": str(current["id"])})
        app = FastAPI()
        app.state.db = db
        for router in (owner_router, invite_router, portal_router, team_router, shared_router, crm_router, workflow_router):
            app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            base = f"/workspaces/{ws}"
            async def invite(pid, email):
                response = await client.post(base + "/members/invite", json={"sales_person_id": str(pid), "email": email})
                assert response.status_code == 200, response.text
                return response.json()["invite_path"].split("/")[-1]
            token = await invite(agent_person, "agent@example.com")
            invitation = await db.workspace_invitations.find_one({"sales_person_id": str(agent_person)})
            assert token not in repr(invitation)
            current["id"] = other
            assert (await client.post(f"/membership-invitations/{token}/accept")).status_code == 403
            current["id"] = agent
            accepted = await client.post(f"/membership-invitations/{token}/accept")
            assert accepted.status_code == 200, accepted.text
            assert (await client.post(f"/membership-invitations/{token}/accept")).status_code == 410
            visible = await accessible_workspaces(db, await db.users.find_one({"_id": agent}))
            assert visible == [{"id": str(ws), "name": "Private workspace", "access_role": "sales_agent"}]
            lead, hidden, introduced = ObjectId(), ObjectId(), ObjectId()
            await db.crm_leads.insert_many([
                {"_id": lead, "workspace_id": str(ws), "status": "new", "deleted_at": None, "phone": "+14155550123", "sales_assignment": {"sales_agent_id": str(agent_person)}, "payments": [{"secret": "private"}], "lead_notes": [{"id": "a", "source": "sales_member", "body": "Visible note"}, {"id": "b", "source": "private", "body": "Owner secret"}]},
                {"_id": hidden, "workspace_id": str(ws), "deleted_at": None},
                {"_id": introduced, "workspace_id": str(ws), "deleted_at": None, "sales_assignment": {"introduced_by_id": str(partner_person)}}])
            portal = base + "/sales-portal"
            response = await client.get(portal + "/leads")
            assert response.status_code == 200, response.text
            assert [row["id"] for row in response.json()["items"]] == [str(lead)]
            assert "private" not in response.text and "Owner secret" not in response.text
            await db.crm_leads.update_one({"_id": lead}, {"$set": {"qualification_call": {"summary": "Interested in a visit", "engine_result": {"qualification_score": 85}, "auth_token": "credential"}}, "$push": {"lead_notes": {"id": "call", "source": "call_agent", "body": "Call response", "transcript": "Customer requested a visit"}}})
            mirrored = (await client.get(portal + f"/leads/{lead}")).json()["lead"]
            assert mirrored["qualification_call"]["summary"] == "Interested in a visit"
            assert mirrored["qualification_call"]["auth_token"] == "[redacted]"
            assert mirrored["lead_notes"] == mirrored["notes"]
            assert mirrored["lead_notes"][-1]["transcript"] == "Customer requested a visit"
            whatsapp = await client.post(portal + f"/leads/{lead}/notes", json={"body": "To +14155550123: Brochure shared", "source": "manual_whatsapp", "direction": "outbound"})
            assert whatsapp.status_code == 200
            recorded = await db.crm_leads.find_one({"_id": lead})
            assert recorded["lead_notes"][-1]["source"] == "manual_whatsapp"
            assert recorded["lead_notes"][-1]["author"] == "agent"
            await db.workspace_sms_configs.insert_one({"workspace_id": str(ws), "enabled": True, "encrypted_auth_token": "secret-token", "account_sid": "secret-account"})
            config = (await client.get(portal + "/sms/config")).json()
            assert config == {"configured": True, "enabled": True}
            await db.crm_sms_messages.insert_one({"workspace_id": str(ws), "lead_id": str(lead), "body": "SMS response", "status": "delivered"})
            assert (await client.get(portal + f"/sms/leads/{lead}")).json()[0]["body"] == "SMS response"
            assert (await client.get(portal + f"/sms/leads/{hidden}")).status_code == 404
            import sms
            from unittest.mock import AsyncMock
            delivery = AsyncMock(return_value={"status": "queued"})
            monkeypatch.setattr(sms, "send_message", delivery)
            assert (await client.post(portal + f"/sms/leads/{hidden}", json={"text": "Denied"})).status_code == 404
            delivery.assert_not_awaited()
            assert (await client.post(portal + f"/sms/leads/{lead}", json={"text": "Permitted"})).status_code == 200
            delivery.assert_awaited_once()
            await db.crm_call_logs.insert_one({"workspace_id": str(ws), "lead_id": str(lead), "kind": "qualification_engine", "result": {"qualification_score": 85}, "profile_snapshot": {"product_name": "Land project", "internal_config": "hidden"}, "raw_provider_data": {"secret": "hidden"}})
            history = await client.get(portal + f"/qualification/leads/{lead}/history")
            assert history.json()[0]["result"]["qualification_score"] == 85
            assert "hidden" not in history.text
            assert (await client.get(portal + f"/qualification/leads/{hidden}/history")).status_code == 404
            assert (await client.get(portal + f"/leads/{hidden}")).status_code == 404
            assert (await client.get(f"/workspaces/{foreign}/sales-portal/leads")).status_code == 403
            assert (await client.get(base + "/members")).status_code == 403
            assert (await client.get(base + "/crm/leads")).status_code == 403
            assert (await client.get(base + "/workflows")).status_code == 403
            assert (await client.post(portal + f"/leads/{lead}/notes", json={"body": "Contacted"})).status_code == 200
            due = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
            assert (await client.post(portal + f"/leads/{lead}/reminders", json={"title": "Call again", "due_at": due})).status_code == 200
            task = await db.tasks.find_one({"lead_id": str(lead)})
            assert task["requires_approval"] is True
            assert task["created_by"] == str(agent)
            assert (await client.patch(portal + f"/leads/{hidden}/reminders/{task['_id']}", json={"status": "done"})).status_code == 404
            assert (await client.patch(portal + f"/leads/{lead}/reminders/{task['_id']}", json={"status": "done", "outcome": "Spoke to lead"})).status_code == 200
            assert (await client.post(portal + f"/leads/{hidden}/notes", json={"body": "Forbidden"})).status_code == 404
            assert (await client.post(portal + "/leads", json={"phone": "+14155550124", "sales_assignment": {"sales_agent_id": "other"}})).status_code == 422
            assert (await client.get("/crm/shared-leads/old-token")).status_code == 410
            snapshot = (await client.get(portal + f"/leads/{lead}")).json()["lead"]["follow_up"]
            assert snapshot["last_response"] == "Spoke to lead"
            assert snapshot["last_response_at"]
            current["id"] = owner
            await client.delete(base + f"/crm/sales-team/leads/{lead}/share")
            current["id"] = agent
            assert (await client.get(portal + f"/leads/{lead}")).status_code == 404
            current["id"] = owner
            member = await db.workspace_memberships.find_one({"user_id": str(agent), "workspace_id": str(ws)})
            assert (await client.patch(base + f"/members/{member['_id']}", json={"active": False})).status_code == 200
            current["id"] = agent
            assert (await client.get(portal + "/leads")).status_code == 403
            assert await accessible_workspaces(db, await db.users.find_one({"_id": agent})) == []
            current["id"] = owner
            partner_token = await invite(partner_person, "partner@example.com")
            current["id"] = partner
            assert (await client.post(f"/membership-invitations/{partner_token}/accept")).status_code == 200
            assert [row["id"] for row in (await client.get(portal + "/leads")).json()["items"]] == [str(introduced)]
            created = await client.post(portal + "/leads", json={"full_name": "Referral", "phone": "+14155550125", "acquisition_channel": "marketing"})
            assert created.status_code == 200, created.text
            doc = await db.crm_leads.find_one({"_id": ObjectId(created.json()["id"])})
            assert doc["sales_assignment"]["introduced_by_id"] == str(partner_person)
            assert doc["sales_assignment"]["acquisition_channel"] == "marketing"
            assert doc["auto_qualification_enabled"] is False
            stats = await client.get(portal + "/performance")
            assert stats.status_code == 200
            assert stats.json()["item"]["id"] == str(partner_person)
            assert stats.json()["item"]["marketing_leads"] == 1
            await db.crm_sales_people.update_one({"_id": partner_person}, {"$set": {"active": False}})
            assert (await client.get(portal + "/leads")).status_code == 403
            current["id"] = owner
            revoked = await invite(agent_person, "agent@example.com")
            doc = await db.workspace_invitations.find_one({"sales_person_id": str(agent_person)})
            assert (await client.delete(base + f"/members/invitations/{doc['_id']}")).status_code == 200
            assert (await client.get(f"/membership-invitations/{revoked}")).status_code == 410
            expired = await invite(agent_person, "agent@example.com")
            await db.workspace_invitations.update_one({"sales_person_id": str(agent_person)}, {"$set": {"expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}})
            assert (await client.get(f"/membership-invitations/{expired}")).status_code == 410
    asyncio.run(isolated(run))


def test_assigned_salesperson_uses_current_assignment_instead_of_stale_text():
    from crm import decorate_lead
    settings = {"fields": [{"key": "assigned_salesperson", "active": True}]}
    lead = {"_id": ObjectId(), "assigned_salesperson": "Previous agent", "field_values": {"assigned_salesperson": "Previous agent"}, "sales_assignment": {"sales_agent_id": "current", "sales_agent_name": "Current agent"}}
    decorated = decorate_lead(lead, settings)
    assert decorated["assigned_salesperson"] == "Current agent"
    assert decorated["field_values"]["assigned_salesperson"] == "Current agent"
    lead["sales_assignment"] = {"sales_agent_id": "", "sales_agent_name": ""}
    assert decorate_lead(lead, settings)["assigned_salesperson"] == ""
    lead.pop("sales_assignment")
    assert decorate_lead(lead, settings)["assigned_salesperson"] == "Previous agent"
