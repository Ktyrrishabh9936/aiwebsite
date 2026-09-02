import sys
from pathlib import Path

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crm import (  # noqa: E402
    DEFAULT_FIELDS,
    DEFAULT_ORGANIZATION,
    DEFAULT_STATES,
    TRASH_RETENTION_DAYS,
    build_manual_lead,
    effective_organization,
    invoice_html,
    lead_query,
    invoice_pdf,
    normalize_field,
    normalize_lead_note,
    normalize_payment_plan,
    payment_stage_remaining_amount,
    payment_plan_ready_for_final_invoice,
    recalculate_payment_plan,
    receipt_html,
    receipt_pdf,
    render_template_html,
    single_payment_summary,
    validate_field_values,
)


def test_phone_field_is_locked_required():
    default_fields = {field["key"]: field for field in DEFAULT_FIELDS}
    assert default_fields["phone"]["required"] is True
    assert default_fields["email"]["required"] is False

    field = normalize_field({"key": "phone", "type": "text", "required": False, "active": False})

    assert field["key"] == "phone"
    assert field["type"] == "phone"
    assert field["required"] is True
    assert field["active"] is True


def test_required_phone_validation_uses_crm_field_values():
    settings = {"fields": DEFAULT_FIELDS, "states": DEFAULT_STATES}

    try:
        validate_field_values({"full_name": "Diya Sharma"}, settings)
        assert False, "missing required phone should fail"
    except HTTPException:
        pass

    try:
        validate_field_values({"email": "diya@example.com"}, settings)
        assert False, "email-only values should fail"
    except HTTPException:
        pass

    values = validate_field_values({"phone": "999", "email": "diya@example.com", "unknown": "ignored"}, settings)
    assert values == {"phone": "999", "email": "diya@example.com"}


def test_manual_lead_uses_active_fields_and_required_phone():
    settings = {"fields": DEFAULT_FIELDS, "states": DEFAULT_STATES}

    lead = build_manual_lead("workspace-1", {"field_values": {"phone": "999", "full_name": "Diya Sharma"}}, settings)

    assert str(lead["_id"]) in lead["sheet_row_key"]
    assert lead["source"] == "manual"
    assert lead["status"] == "new"
    assert lead["customer_status"] == "lead"
    assert lead["phone"] == "999"
    assert lead["field_values"] == {"phone": "999", "full_name": "Diya Sharma"}
    assert lead["deleted_at"] is None
    assert lead["delete_after"] is None


def test_manual_lead_rejects_invalid_status():
    settings = {"fields": DEFAULT_FIELDS, "states": DEFAULT_STATES}

    try:
        build_manual_lead("workspace-1", {"status": "archived", "field_values": {"phone": "999"}}, settings)
        assert False, "invalid status should fail"
    except HTTPException as exc:
        assert exc.status_code == 400


def test_lead_query_separates_active_and_trash():
    active = lead_query("workspace-1")
    trash = lead_query("workspace-1", only_trashed=True)

    assert active["workspace_id"] == "workspace-1"
    assert active["$or"] == [{"deleted_at": {"$exists": False}}, {"deleted_at": None}]
    assert trash == {"workspace_id": "workspace-1", "deleted_at": {"$ne": None}}
    assert TRASH_RETENTION_DAYS == 30


def test_payment_plan_stays_embedded_and_completes_by_stage_status():
    plan = normalize_payment_plan({
        "final_invoice_note": "Invoice INV-001 ready",
        "stages": [
            {"name": "Token Amount", "amount": "100000", "due_timing": "On booking", "status": "paid"},
            {"name": "Final Payment", "amount": "900000", "due_timing": "Registry", "status": "paid"},
        ],
    })

    assert plan["status"] == "completed"
    assert len(plan["stages"]) == 2
    assert plan["final_invoice_note"] == "Invoice INV-001 ready"
    assert plan["stages"][0]["source"] == "system"


def test_payment_stage_manual_source_is_preserved():
    plan = normalize_payment_plan({
        "total_amount": "10000",
        "stages": [{"name": "Custom Milestone", "amount": "10000", "source": "manual"}],
    })

    assert plan["stages"][0]["source"] == "manual"


def test_lead_note_requires_body_and_gets_timestamp():
    note = normalize_lead_note({"body": "Called customer about payment documents", "author": "Sales"})

    assert note["body"] == "Called customer about payment documents"
    assert note["author"] == "Sales"
    assert note["id"]
    assert note["created_at"]

    try:
        normalize_lead_note({"body": "  "})
        assert False, "empty note should fail"
    except HTTPException as exc:
        assert exc.status_code == 400


def test_single_payment_summary_tracks_partial_and_full_due():
    lead = {}
    partial = single_payment_summary(lead, [{"amount": "4000"}], "10000")
    full = single_payment_summary({"payment_summary": partial}, [{"amount": "4000"}, {"amount": "6000"}])

    assert partial["total_paid"] == "4000"
    assert partial["due_amount"] == "6000"
    assert partial["status"] == "active"
    assert full["total_paid"] == "10000"
    assert full["due_amount"] == "0"
    assert full["status"] == "completed"


def test_multistep_partial_receipt_keeps_next_stage_absent_until_due_clears():
    plan = normalize_payment_plan({
        "total_amount": "20000",
        "stages": [{"id": "stage-1", "name": "Payment 1", "amount": "5000"}],
    })

    partial = recalculate_payment_plan(plan, [{"stage_id": "stage-1", "amount": "2000"}])
    completed_first = recalculate_payment_plan(plan, [{"stage_id": "stage-1", "amount": "5000"}])

    assert len(partial["stages"]) == 1
    assert partial["stages"][0]["paid_amount"] == "2000"
    assert partial["stages"][0]["due_amount"] == "18000"
    assert partial["stages"][0]["status"] == "partially_paid"
    assert len(completed_first["stages"]) == 2
    assert completed_first["stages"][0]["status"] == "paid"
    assert completed_first["stages"][1]["amount"] == "15000"
    assert completed_first["due_amount"] == "15000"


def test_multistep_multiple_receipts_sum_by_stage_and_complete_plan():
    plan = normalize_payment_plan({
        "total_amount": "10000",
        "stages": [
            {"id": "stage-1", "name": "Payment 1", "amount": "4000"},
            {"id": "stage-2", "name": "Payment 2", "amount": "6000"},
        ],
    })
    receipts = [
        {"stage_id": "stage-1", "amount": "1000"},
        {"stage_id": "stage-1", "amount": "3000"},
        {"stage_id": "stage-2", "amount": "6000"},
    ]

    recalculated = recalculate_payment_plan(plan, receipts)

    assert recalculated["total_paid"] == "10000"
    assert recalculated["due_amount"] == "0"
    assert recalculated["status"] == "completed"
    assert recalculated["stages"][0]["paid_amount"] == "4000"
    assert recalculated["stages"][0]["due_amount"] == "0"


def test_final_invoice_requires_every_payment_stage_paid_even_when_due_is_zero():
    plan = normalize_payment_plan({
        "total_amount": "10000",
        "stages": [
            {"id": "stage-1", "name": "Payment 1", "amount": "4000"},
            {"id": "stage-2", "name": "Payment 2", "amount": "6000"},
        ],
    })

    recalculated = recalculate_payment_plan(plan, [{"stage_id": "stage-1", "amount": "10000"}])

    assert recalculated["due_amount"] == "0"
    assert recalculated["stages"][0]["status"] == "paid"
    assert recalculated["stages"][1]["status"] == "pending"
    assert payment_plan_ready_for_final_invoice(recalculated) is False


def test_payment_stage_remaining_amount_is_limited_to_stage_total():
    plan = normalize_payment_plan({
        "total_amount": "10000",
        "stages": [
            {"id": "stage-1", "name": "Payment 1", "amount": "4000"},
            {"id": "stage-2", "name": "Payment 2", "amount": "6000"},
        ],
    })
    stage = plan["stages"][0]

    assert payment_stage_remaining_amount(stage, []) == 4000
    assert payment_stage_remaining_amount(stage, [{"stage_id": "stage-1", "amount": "1500"}]) == 2500


def test_template_render_uses_configured_field_values_and_payment_plan():
    settings = {"fields": DEFAULT_FIELDS, "states": DEFAULT_STATES}
    lead = {
        "field_values": {"full_name": "Diya Sharma", "email": "diya@example.com", "phone": "999"},
        "payment_plan": {"stages": [{"name": "Token Amount", "amount": "100000", "due_timing": "Today", "status": "paid"}]},
    }
    template = {"name": "Receipt", "html": "<h1>{{full_name}}</h1><p>{{email}}</p><table>{{payment_plan.stages}}</table>"}

    html = render_template_html(template, lead, settings)

    assert "Diya Sharma" in html
    assert "diya@example.com" in html
    assert "Token Amount" in html


def test_default_receipt_and_invoice_html_include_snapshots():
    receipt = {
        "receipt_number": "REC-0001",
        "transaction_id": "TXN-001",
        "payment_stage": "Single Payment",
        "amount": "100000",
        "payment_date": "2026-08-29",
        "payment_method": "Bank Transfer",
        "status": "Paid",
        "due_amount": "0",
        "description": "Booking payment",
        "salesperson": "Riya",
        "organization": {**DEFAULT_ORGANIZATION, "company_name": "Arevei Realty", "logo_url": "https://example.com/logo.png", "bank_details": "Bank XYZ", "authorized_signatory": "Riya Sen"},
        "customer": {"name": "Diya Sharma", "email": "diya@example.com", "phone": "999", "address": "Unit 101"},
    }
    invoice = {
        "invoice_number": "INV-0001",
        "generated_at": "2026-08-29",
        "organization": receipt["organization"],
        "customer": receipt["customer"],
        "receipts": [{**receipt, "id": "receipt-1"}],
        "total_paid": "100000",
        "due_amount": "0",
        "salesperson": "Riya",
        "description": "Final settlement",
    }

    assert "REC-0001" in receipt_html(receipt)
    assert "TXN-001" in receipt_html(receipt)
    assert "Diya Sharma" in receipt_html(receipt)
    assert "https://example.com/logo.png" in receipt_html(receipt)
    assert "Bank XYZ" in receipt_html(receipt)
    assert "Riya Sen" in receipt_html(receipt)
    assert "Download PDF" in receipt_html(receipt)
    assert 'href="./pdf"' in receipt_html(receipt)
    assert receipt_pdf(receipt).startswith(b"%PDF-1.4")
    assert DEFAULT_ORGANIZATION["document_accent_color"] == "#000000"
    assert "--accent:#000000" in receipt_html({"organization": DEFAULT_ORGANIZATION, "customer": {}})
    assert "--accent-text:#ffffff" in receipt_html({"organization": DEFAULT_ORGANIZATION, "customer": {}})
    assert "INV-0001" in invoice_html(invoice)
    assert "REC-0001" in invoice_html(invoice)
    assert "TXN-001" in invoice_html(invoice)
    assert "Arevei Realty" in invoice_html(invoice)
    assert "Download PDF" in invoice_html(invoice)
    assert 'href="./pdf"' in invoice_html(invoice)
    assert "Download Receipt" in invoice_html(invoice)
    assert 'href="../receipts/receipt-1/pdf"' in invoice_html(invoice)
    assert invoice_pdf(invoice).startswith(b"%PDF-1.4")


def test_brain_organization_overrides_crm_settings_for_documents():
    settings = {"organization": {"company_name": "CRM Co", "logo_url": "https://example.com/crm.png", "receipt_prefix": "CRM", "document_accent_color": "#000000"}}
    workspace = {"brain": {"organization": {"company_name": "Brain Co", "logo_url": "https://example.com/brain.png", "invoice_prefix": "BINV", "document_accent_color": "#ffcc00"}}}

    org = effective_organization(settings, workspace)

    assert org["company_name"] == "Brain Co"
    assert org["logo_url"] == "https://example.com/brain.png"
    assert org["receipt_prefix"] == "CRM"
    assert org["invoice_prefix"] == "BINV"
    assert org["document_accent_color"] == "#ffcc00"
    assert "--accent:#ffcc00" in receipt_html({"organization": org, "customer": {}})


def test_brain_business_profile_fills_legacy_organization_fields():
    settings = {"organization": {"company_name": "CRM Co", "website": "https://crm.example", "receipt_prefix": "CRM"}}
    workspace = {
        "website_url": "https://workspace.example",
        "brain": {
            "_source_url": "https://brain.example",
            "business_profile": {"company_name": "Brain Profile Co"},
        },
    }

    org = effective_organization(settings, workspace)

    assert org["company_name"] == "Brain Profile Co"
    assert org["website"] == "https://brain.example"
    assert org["receipt_prefix"] == "CRM"
