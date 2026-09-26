import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from fastapi import HTTPException
from crm import apply_lead_filters
from sales_team import attribution, performance_rows, assign_lead


def test_property_sales_and_referral_credit_are_separate():
    agent, partner = ObjectId(), ObjectId()
    people = [{"_id": agent, "name": "Agent", "role": "sales_agent"}, {"_id": partner, "name": "Partner", "role": "channel_partner"}]
    leads = [
        {"status": "won", "opportunity": {"project_id": "project-a", "sale_status": "sold", "total_minor": 500000}, "sales_assignment": {"sales_agent_id": str(agent), "channel_partner_id": str(partner), "introduced_by_id": str(partner), "acquisition_channel": "referral"}},
        {"status": "new", "opportunity": {"project_id": "project-a"}, "sales_assignment": {"sales_agent_id": str(agent), "introduced_by_id": str(agent), "acquisition_channel": "marketing"}},
        {"status": "won", "opportunity": {"project_id": "project-b", "sale_status": "sold", "total_minor": 900000}, "sales_assignment": {"sales_agent_id": str(agent)}},
    ]
    rows = {row["id"]: row for row in performance_rows(people, leads, "project-a")}
    assert rows[str(agent)]["assigned_leads"] == 2
    assert rows[str(agent)]["sales_minor"] == 500000
    assert rows[str(agent)]["marketing_leads"] == 1
    assert rows[str(partner)]["referral_leads"] == 1
    assert rows[str(partner)]["introduced_sales"] == 1


def test_attribution_rejects_foreign_or_wrong_role_people():
    person_id = ObjectId()
    db = SimpleNamespace(crm_sales_people=SimpleNamespace(find_one=AsyncMock(return_value=None)))
    async def run():
        with pytest.raises(HTTPException):
            await attribution(db, "workspace-a", {"sales_agent_id": str(person_id)})
        db.crm_sales_people.find_one.assert_awaited_with({"workspace_id": "workspace-a", "_id": person_id})
        db.crm_sales_people.find_one.return_value = {"name": "Partner", "role": "channel_partner"}
        with pytest.raises(HTTPException):
            await attribution(db, "workspace-a", {"sales_agent_id": str(person_id)})
    asyncio.run(run())


def test_sales_filters_compose_with_existing_search():
    query = apply_lead_filters({"workspace_id": "workspace-a"}, search="Vinay", sales_agent_id="agent", channel_partner_id="partner")
    assert query["sales_assignment.sales_agent_id"] == "agent"
    assert query["sales_assignment.channel_partner_id"] == "partner"
    assert query["$and"]


def test_converted_sales_credit_cannot_be_reassigned():
    db = SimpleNamespace(crm_leads=SimpleNamespace(find_one=AsyncMock(return_value={"status": "won"})))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))
    async def run():
        with pytest.raises(HTTPException) as error:
            await assign_lead("workspace-a", str(ObjectId()), request, {})
        assert error.value.status_code == 409
    asyncio.run(run())
