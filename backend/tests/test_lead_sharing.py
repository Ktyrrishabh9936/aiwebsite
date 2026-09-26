import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bson import ObjectId
import pytest
from fastapi import HTTPException
import sales_team


def test_share_reassign_and_revoke_invalidate_links_preserving_credit(monkeypatch):
    agent_a, agent_b, lead_id = ObjectId(), ObjectId(), ObjectId()
    people = {str(agent_a): {"_id": agent_a, "name": "Agent A", "active": True, "role": "sales_agent", "user_id": "account"}, str(agent_b): {"_id": agent_b, "name": "Agent B", "active": True, "role": "sales_agent", "user_id": "account"}}
    lead = {"_id": lead_id, "workspace_id": "workspace", "status": "won", "deleted_at": None,
            "sales_assignment": {"sales_agent_id": str(agent_a), "sales_agent_name": "Agent A", "introduced_by_id": str(agent_a), "acquisition_channel": "referral"}}
    async def find(query):
        if "lead_share.token_hash" in query:
            return lead if (lead.get("lead_share") or {}).get("token_hash") == query["lead_share.token_hash"] else None
        return lead
    async def update(query, patch):
        lead.update(patch.get("$set", {}))
        for key in patch.get("$unset", {}):
            lead.pop(key, None)
    async def person(query):
        return people.get(str(query["_id"]))
    db = SimpleNamespace(workspace_memberships=SimpleNamespace(find_one=AsyncMock(return_value={"active": True})), crm_leads=SimpleNamespace(find_one=AsyncMock(side_effect=find), update_one=AsyncMock(side_effect=update)), crm_sales_people=SimpleNamespace(find_one=AsyncMock(side_effect=person)))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))
    monkeypatch.setattr(sales_team, "ensure_crm_settings", AsyncMock(return_value={"fields": [], "states": []}))
    monkeypatch.setattr(sales_team, "decorate_lead", lambda doc, settings: dict(doc))
    async def run():
        first = await sales_team.share_lead("workspace", str(lead_id), request, {"sales_agent_id": str(agent_a)})
        assert first["share_path"] == f"/app/w/workspace/crm?lead={lead_id}"
        assert lead["lead_share"]["authenticated"] is True
        assert "token_hash" not in lead["lead_share"]
        with pytest.raises(HTTPException) as retired:
            await sales_team.view_shared_lead("legacy-token", request)
        assert retired.value.status_code == 410
        second = await sales_team.share_lead("workspace", str(lead_id), request, {"sales_agent_id": str(agent_b)})
        assert lead["sales_assignment"]["sales_agent_id"] == str(agent_b)
        assert lead["sales_credit"]["sales_agent_id"] == str(agent_a)
        assert lead["sales_assignment"]["introduced_by_id"] == str(agent_a)
        await sales_team.revoke_share("workspace", str(lead_id), request)
        assert lead["sales_assignment"]["sales_agent_id"] == ""
        assert lead["sales_credit"]["sales_agent_id"] == str(agent_a)
        with pytest.raises(HTTPException):
            await sales_team.view_shared_lead("legacy-token", request)
    asyncio.run(run())
