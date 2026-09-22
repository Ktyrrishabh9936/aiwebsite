import asyncio

from lead_context import deterministic_lead_context, prepare_lead_context
from qualification_engine import QualificationProfile


def settings():
    return {"fields": [
        {"key": "phone", "label": "Phone", "active": True},
        {"key": "full_name", "label": "Full Name", "active": True},
        {"key": "requirements", "label": "What do you need?", "active": True},
        {"key": "budget_note", "label": "Expected Budget", "active": True},
        {"key": "hidden", "label": "Hidden", "active": False},
    ]}


def test_dynamic_form_values_use_crm_labels_and_skip_separate_variables():
    lead = {"field_values": {"full_name": "Asha", "phone": "+919999999999", "requirements": "Website design",
             "budget_note": "2 lakh", "hidden": "private"}, "meta_campaign_name": "September launch",
            "communication_summary": {"answers": {"timeline": "This month"}, "pending_discussion": ["decision maker"]}}
    context = deterministic_lead_context(lead, QualificationProfile(product_name="Design services"), settings())
    assert "What do you need?: Website design" in context
    assert "Expected Budget: 2 lakh" in context
    assert "Campaign: September launch" in context
    assert "Timeline: This month" in context
    assert "Still to discuss: decision maker" in context
    assert "+919999999999" not in context
    assert "Hidden" not in context


def test_context_ai_result_and_failure_fallback(monkeypatch):
    import llm_service
    lead = {"field_values": {"requirements": "Website design"}}
    profile = QualificationProfile(product_name="Design services")

    async def generated(*args, **kwargs):
        return {"lead_context": "The lead requested a website."}

    monkeypatch.setattr(llm_service, "generate_json", generated)
    context, source = asyncio.run(prepare_lead_context(lead, profile, settings(), "workspace", "model"))
    assert source == "ai"
    assert context.endswith("The lead requested a website.")

    async def failed(*args, **kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(llm_service, "generate_json", failed)
    context, source = asyncio.run(prepare_lead_context(lead, profile, settings(), "workspace", "model"))
    assert source == "deterministic_fallback"
    assert "What do you need?: Website design" in context
