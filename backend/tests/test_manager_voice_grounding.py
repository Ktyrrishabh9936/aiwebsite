import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from bson import ObjectId
import pytest
import manager_voice_grounding as grounding


def call(name, args):
    return {"role": "assistant", "content": "", "tool_calls": [{"id": "call", "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_no_matching_lead_cannot_turn_into_invented_details(monkeypatch):
    model = AsyncMock(return_value=call("search_voice_leads", {"search": "Other account lead"}))
    monkeypatch.setattr(grounding, "tool_turn", model)
    monkeypatch.setattr(grounding.VoiceLookup, "execute", AsyncMock(return_value={"total": 0, "items": []}))
    reply = asyncio.run(grounding.grounded_voice_answer(None, {"_id": ObjectId()}, "What do they want?", [{"role": "assistant", "content": "They want a property."}], []))
    assert "No matching lead" in reply
    assert model.await_count == 1
    assert not any(m.get("content") == "They want a property." for m in model.call_args.args[2])


def test_unverified_model_answer_is_not_spoken(monkeypatch):
    monkeypatch.setattr(grounding, "tool_turn", AsyncMock(return_value={"content": "They want a property."}))
    reply = asyncio.run(grounding.grounded_voice_answer(None, {"_id": ObjectId()}, "What does this lead want?", [], []))
    assert "couldn't verify" in reply and "property" not in reply


def test_read_is_workspace_scoped_and_preserves_actual_requirements():
    lead, ws = ObjectId(), ObjectId()
    find = AsyncMock(return_value={"_id": lead, "field_values": {"requirements": "Accounting software"}, "qualification_data": {"product": "SaaS"}})
    lookup = grounding.VoiceLookup(SimpleNamespace(crm_leads=SimpleNamespace(find_one=find)), str(ws))
    lookup.matched.add(str(lead))
    result = asyncio.run(lookup.execute("read_voice_lead", {"lead_id": str(lead)}))
    assert find.call_args.args[0]["workspace_id"] == str(ws)
    assert result["details"]["field_values"]["requirements"] == "Accounting software"
    assert result["details"]["qualification_data"] == {"product": "SaaS"}
    with pytest.raises(ValueError): asyncio.run(lookup.execute("read_voice_lead", {"lead_id": str(ObjectId())}))


def test_spoken_name_can_use_alternate_spelling_without_searching_another_workspace(monkeypatch):
    import crm
    ws, lead = ObjectId(), ObjectId()
    search = AsyncMock(side_effect=[{"total": 0, "items": []}, {"total": 1, "items": [{"id": str(lead), "field_values": {"full_name": "Manish Tiwari"}}]}])
    monkeypatch.setattr(crm, "paginated_leads", search)
    monkeypatch.setattr(crm, "ensure_crm_settings", AsyncMock(return_value={}))
    result = asyncio.run(grounding.VoiceLookup(None, str(ws)).execute("search_voice_leads", {"search": "spoken-name", "alternate_searches": ["Manish Tiwari"]}))
    assert result["total"] == 1
    assert [c.kwargs["search"] for c in search.call_args_list] == ["spoken-name", "Manish Tiwari"]
    assert all(c.args[1] == str(ws) for c in search.call_args_list)
