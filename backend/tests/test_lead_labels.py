import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from fastapi import HTTPException
import crm

def test_tags_are_custom_multiple_and_deduplicated():
    assert crm.normalize_lead_tags([" VIP ", "vip", "Repeat enquiry", "3 BHK"]) == ["VIP", "Repeat enquiry", "3 BHK"]
    for tags in [None, "VIP", [""], [1], ["x" * 51], ["x"] * 51]:
        with pytest.raises(HTTPException):
            crm.normalize_lead_tags(tags)

def test_customer_and_tags_are_independent_of_stage_and_qualification(monkeypatch):
    async def run():
        lead_id = ObjectId()
        stored = {"_id": lead_id, "workspace_id": "workspace", "status": "new", "lead_status": "PENDING", "customer_status": "lead", "field_values": {"phone": "+14155550123"}, "tags": []}
        async def update(query, changes):
            assert query == {"workspace_id": "workspace", "_id": lead_id, "deleted_at": None}
            stored.update(changes["$set"])
        collection = SimpleNamespace(find_one=AsyncMock(side_effect=lambda query: deepcopy(stored)), update_one=AsyncMock(side_effect=update))
        monkeypatch.setattr(crm, "db_from", lambda request: SimpleNamespace(crm_leads=collection))
        monkeypatch.setattr(crm, "ensure_crm_settings", AsyncMock(return_value={"fields": deepcopy(crm.DEFAULT_FIELDS)}))
        result = await crm.set_lead_labels("workspace", str(lead_id), None, {"tags": ["VIP", "Repeat enquiry"], "customer_status": "customer"})
        assert result["tags"] == ["VIP", "Repeat enquiry"]
        assert result["customer_status"] == "customer"
        assert result["status"] == "new" and result["lead_status"] == "PENDING"
        assert result["conversion_type"] == "single_payment"
        result = await crm.set_lead_labels("workspace", str(lead_id), None, {"tags": ["VIP"]})
        assert result["customer_status"] == "customer" and result["status"] == "new"
        result = await crm.set_lead_labels("workspace", str(lead_id), None, {"customer_status": "lead"})
        assert result["tags"] == ["VIP"] and result["status"] == "new"
    asyncio.run(run())

def test_workspace_tag_library_reuses_names_and_saves_colors(monkeypatch):
    async def run():
        library = deepcopy(crm.DEFAULT_TAG_LIBRARY)
        settings = {"tag_library": library}
        collection = SimpleNamespace(update_one=AsyncMock())
        monkeypatch.setattr(crm, "db_from", lambda request: SimpleNamespace(crm_settings=collection))
        monkeypatch.setattr(crm, "ensure_crm_settings", AsyncMock(return_value=settings))
        result = await crm.save_tag_library("workspace", None, {"names": ["vip", "Interested in 3 BHK"], "color": "rose"})
        assert len([tag for tag in result["tags"] if tag["label"].casefold() == "vip"]) == 1
        assert next(tag for tag in result["tags"] if tag["label"] == "VIP")["color"] == "rose"
        assert {"label": "Interested in 3 BHK", "color": "rose"} in result["tags"]
        query, update = collection.update_one.call_args.args
        assert query == {"workspace_id": "workspace"}
        assert update["$set"]["tag_library"] == result["tags"]
        with pytest.raises(HTTPException):
            await crm.save_tag_library("workspace", None, {"names": ["VIP"], "color": "invalid"})
    asyncio.run(run())
