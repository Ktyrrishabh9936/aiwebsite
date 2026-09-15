import asyncio
import uuid
from pathlib import Path

import pytest
from bson import ObjectId
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from qualification_engine import *
from plivo_response_adapter import PlivoResponseAdapter


def process(payload=None, profile=None, **kw):
    return LeadQualificationEngine().process(PlivoResponseAdapter().adapt(payload or {}, "lead"), profile or QualificationProfile(), **kw)


@pytest.mark.parametrize("raw,outcome,status,retry", [
    ("invalid_number", "INVALID_NUMBER", "JUNK", False),
    ("wrong_number", "WRONG_NUMBER", "JUNK", False),
    ("spam", "DUPLICATE_OR_SPAM", "JUNK", False),
    ("no-answer", "NO_ANSWER", "PENDING", True),
    ("busy", "BUSY", "PENDING", True),
    ("switched_off", "SWITCHED_OFF", "PENDING", True),
    ("unreachable", "UNREACHABLE", "PENDING", True),
    ("failed", "TECHNICAL_ISSUE", "PENDING", True),
    ("dropped", "DROPPED_CALL", "PENDING", True),
    ("callback_requested", "CALLBACK_REQUESTED", "PENDING", False),
    ("do_not_call", "DND_REQUESTED", "UNQUALIFIED", False),
])
def test_call_outcomes(raw, outcome, status, retry):
    result = process({"CallStatus": raw})
    assert result.call_outcome == outcome
    assert result.lead_status == status
    assert result.retry_eligible is retry
    assert result.qualification_score is None
    assert result.lead_temperature is None


def full_data(**kw):
    return {"product_fit": True, "eligibility": True, "budget": {"value": 9000000, "currency": "INR"}, "buying_intent": "high", "purchase_timeline": "immediate", "decision_maker_status": "decision_maker", **kw}


def connected(data, profile=None):
    return process({"CallStatus": "completed", "qualification_data": data}, profile)


def test_not_interested_is_unqualified_not_junk():
    result = connected(full_data(not_interested=True))
    assert result.lead_status == "UNQUALIFIED"
    assert result.lead_temperature is None


def test_mandatory_budget_overrides_high_ai_score():
    profile = QualificationProfile(price_range={"min": 8000000, "currency": "INR"})
    result = process({"CallStatus": "completed", "qualification_score": 100, "qualification_category": "hot", "qualification_data": full_data(budget={"value": 5000000, "currency": "INR"})}, profile)
    assert result.qualification_score == 100
    assert result.lead_status == "UNQUALIFIED"
    assert result.lead_temperature is None
    assert result.next_action == "NO_ACTION"


def test_partial_retains_nulls():
    result = connected({"requirement": "A subscription", "budget": {"min": 80, "max": 90}})
    assert result.lead_status == "PARTIALLY_QUALIFIED"
    assert result.qualification_data.purchase_timeline is None
    assert result.confidence_score < 100


@pytest.mark.parametrize("data,score,temperature,status", [
    (full_data(buying_intent="medium", purchase_timeline="later", decision_maker_status="not_decision_maker"), 65, "WARM", "QUALIFIED"),
    (full_data(buying_intent="medium", purchase_timeline="soon", decision_maker_status="shared"), 80, "HOT", "QUALIFIED"),
    (full_data(), 100, "VERY_HOT", "SALES_READY"),
])
def test_qualified_levels(data, score, temperature, status):
    result = connected(data)
    assert result.qualification_score == score
    assert result.lead_temperature == temperature
    assert result.lead_status == status


def test_missing_transcript_and_fields_never_invents_score():
    result = process({"CallStatus": "completed", "qualification_score": 99, "summary": "Great call"})
    assert result.lead_status == "PARTIALLY_QUALIFIED"
    assert result.qualification_score is None


def test_missing_required_field_is_unknown_not_failed():
    result = connected(full_data(), QualificationProfile(mandatory_qualification_criteria=[Rule(field="location", value="Anywhere")]))
    assert result.lead_status == "PARTIALLY_QUALIFIED"
    assert "location" in result.missing_information


def test_dnd_has_priority_over_junk_and_high_score():
    result = process({"CallStatus": "invalid_number", "qualification_data": full_data(dnd_requested=True)})
    assert result.call_outcome == "DND_REQUESTED"
    assert result.next_action == "DND"


def test_disqualification_rules_outrank_score():
    profile = QualificationProfile(disqualification_criteria=[Rule(field="attributes.existing_customer", value=True)])
    result = connected(full_data(attributes={"existing_customer": True}), profile)
    assert result.lead_status == "UNQUALIFIED"


def test_retry_cap_and_configurable_interval():
    profile = QualificationProfile(retry={"max_attempts": 4, "retry_rules": [{"outcome": "BUSY", "delay_minutes": 127}]})
    assert process({"CallStatus": "busy"}, profile, attempts=4).retry_eligible is False
    assert RetryPolicyEngine.delay(Outcome.BUSY, profile.retry) == 127


def test_callback_time_and_no_score():
    result = process({"CallStatus": "completed", "callback_requested": True, "callback_at": "2030-01-01T10:00:00Z"})
    assert result.next_action == "CALLBACK"
    assert result.callback_at.year == 2030
    assert result.qualification_score is None


@pytest.mark.parametrize("score,temp", [(0,"LOW"),(29,"LOW"),(30,"COLD"),(49,"COLD"),(50,"WARM"),(69,"WARM"),(70,"HOT"),(84,"HOT"),(85,"VERY_HOT"),(100,"VERY_HOT")])
def test_temperature_boundaries(score, temp):
    assert LeadTemperatureEngine.temperature(score) == temp


def test_profile_validation():
    with pytest.raises(ValueError):
        QualificationProfile(weights={"product_fit": 100})
    with pytest.raises(ValueError):
        QualificationProfile(mandatory_qualification_criteria=[{"field": "budget.value", "operator": "gte", "value": "eighty lakh"}])


def test_adapter_plivo_codes_and_bool_strings():
    assert process({"CallStatus": "completed", "HangupCauseCode": "3000"}).call_outcome == "NO_ANSWER"
    assert process({"CallStatus": "completed", "HangupCauseCode": "2000"}).call_outcome == "INVALID_NUMBER"
    assert process({"CallStatus": "completed", "qualification_data": {"dnd_requested": "false"}}).call_outcome != "DND_REQUESTED"


def test_llm_extraction_cannot_rewrite_numeric_provider_facts(monkeypatch):
    import llm_service
    from qualification_service import extract_facts
    async def generate(*args, **kw):
        return {"qualification_data": {"budget": {"value": 9000000, "currency": "INR"}, "product_fit": True}, "evidence": {"budget": "I have fifty lakh", "product_fit": "fabricated quote"}, "confidence_score": 99}
    monkeypatch.setattr(llm_service, "generate_json", generate)
    call = PlivoResponseAdapter().adapt({"transcript": "I have fifty lakh for a home", "qualification_data": {"budget": {"value": 5000000, "currency": "INR"}}}, "lead")
    data, _, _ = asyncio.run(extract_facts(call, QualificationProfile(), None))
    assert data.budget.value == 5000000
    assert data.product_fit is None


def test_unknown_and_malformed_facts_remain_unknown():
    call = PlivoResponseAdapter().adapt({"CallStatus": "completed", "qualification_data": {"product_fit": "unknown", "eligibility": "maybe", "budget": {"value": "not a number", "currency": "INR"}, "preferences": [None], "attributes": "invalid"}}, "lead")
    data = validated_facts(call.extracted_data)
    assert data.product_fit is None and data.eligibility is None
    assert data.budget.value is None
    assert data.attributes == {}
    assert LeadQualificationEngine().process(call, QualificationProfile()).qualification_score is None
    assert connected({}, QualificationProfile(required_information=["budget"])).lead_status == "PARTIALLY_QUALIFIED"


def test_budget_can_supply_eligibility_points():
    result = connected(full_data(eligibility=None), QualificationProfile(price_range={"min": 8000000, "currency": "INR"}))
    assert result.score_breakdown["budget_eligibility"] == 20


def test_structured_budget_range_without_transcript_preserves_known_information():
    result = process({"CallStatus": "completed", "answers": {"budget": "₹80–90 lakh", "preferred_location": "Noida"}})
    assert result.qualification_data.budget.min == 8000000
    assert result.qualification_data.budget.max == 9000000
    assert result.qualification_data.budget.currency == "INR"
    assert result.qualification_data.location == "Noida"
    assert result.qualification_data.purchase_timeline is None
    assert result.lead_status == "PARTIALLY_QUALIFIED"


def test_budget_currency_is_not_invented():
    call = PlivoResponseAdapter().adapt({"answers": {"budget": "2000000"}}, "lead")
    assert call.extracted_data["budget"]["value"] == 2000000
    assert call.extracted_data["budget"]["currency"] is None


def test_custom_facts_require_transcript_evidence(monkeypatch):
    import llm_service
    from qualification_service import extract_facts
    async def generate(*args, **kwargs):
        return {"qualification_data": {"attributes": {"seats": 50, "industry": "finance"}}, "evidence": {"attributes.seats": "We need fifty seats", "attributes.industry": "not in transcript"}, "confidence_score": 95}
    monkeypatch.setattr(llm_service, "generate_json", generate)
    call = PlivoResponseAdapter().adapt({"transcript": "We need fifty seats for our team"}, "lead")
    data, _, _ = asyncio.run(extract_facts(call, QualificationProfile(), None))
    assert data.attributes == {"seats": 50}


def test_mongodb_idempotency_history_retry_and_dnd(monkeypatch):
    """Integration test uses an isolated temporary database, never production leads or calls."""
    import qualification_service as service
    from crm import build_manual_lead, ensure_crm_settings
    from plivo_calls import start_qualification_call
    from fastapi import HTTPException

    async def extraction(call, profile, model_id):
        return QualificationData.model_validate(call.extracted_data), 100, call.summary
    monkeypatch.setattr(service, "extract_facts", extraction)

    async def run():
        config = dotenv_values(Path(__file__).parents[1] / ".env")
        client = AsyncIOMotorClient(config.get("MONGO_URL", "mongodb://127.0.0.1:27017"), serverSelectionTimeoutMS=5000)
        name = "qual_test_" + uuid.uuid4().hex[:24]
        db = client[name]
        try:
            ws_id = str(ObjectId())
            profile_id = ObjectId()
            await db.qualification_profiles.insert_one({"_id": profile_id, "workspace_id": ws_id, **QualificationProfile(retry={"max_attempts": 4, "retry_rules": [{"outcome": "NO_ANSWER", "delay_minutes": 30}]}).model_dump(mode="json")})
            await db.workspaces.insert_one({"_id": ObjectId(ws_id), "qualification_profile_id": str(profile_id)})
            lead = build_manual_lead(ws_id, {"field_values": {"phone": "+14155550123", "full_name": "Synthetic Test"}}, await ensure_crm_settings(db, ws_id))
            await db.crm_leads.insert_one(lead)
            controller = service.PlivoWebhookController(db)
            payload = {"CallUUID": "test-call-1", "CallStatus": "no-answer"}
            result = await controller.process(ws_id, str(lead["_id"]), payload)
            assert result["qualification_result"]["lead_status"] == "PENDING"
            assert (await db.crm_leads.find_one({"_id": lead["_id"]}))["status"] != "lost"
            assert (await controller.process(ws_id, str(lead["_id"]), payload))["duplicate"] is True
            assert await db.crm_call_logs.count_documents({"kind": "qualification_engine"}) == 1
            stored = await db.crm_leads.find_one({"_id": lead["_id"]})
            assert stored["call_attempt_count"] == 1
            assert len(stored["lead_notes"]) == 1
            assert stored["qualification_call"]["status"] == "scheduled"
            rich = {"CallUUID": "test-call-1", "CallStatus": "completed", "qualification_data": full_data()}
            await controller.process(ws_id, str(lead["_id"]), rich)
            # Late transport failure cannot overwrite known conversation evidence.
            await controller.process(ws_id, str(lead["_id"]), {**payload, "event_id": "late"})
            stored = await db.crm_leads.find_one({"_id": lead["_id"]})
            assert stored["lead_status"] == "SALES_READY"
            assert stored["call_attempt_count"] == 1
            assert await db.tasks.count_documents({"action_type": "SALES_CALL"}) == 1
            await controller.process(ws_id, str(lead["_id"]), {"CallUUID": "test-call-2", "CallStatus": "do_not_call"})
            stored = await db.crm_leads.find_one({"_id": lead["_id"]})
            assert stored["do_not_call"] is True
            assert stored["call_attempt_count"] == 2
            assert await db.crm_call_logs.count_documents({"kind": "qualification_engine"}) == 2
            with pytest.raises(HTTPException) as exc:
                await start_qualification_call(db, ws_id, str(lead["_id"]), None)
            assert exc.value.status_code == 409
        finally:
            assert name.startswith("qual_test_")
            await client.drop_database(name)
            client.close()
    asyncio.run(run())

