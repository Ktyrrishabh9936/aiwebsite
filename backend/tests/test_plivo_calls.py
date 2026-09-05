import base64
import hashlib
import hmac
import json

import httpx
from fastapi import HTTPException

from plivo_calls import (
    callback_urls,
    inbound_bridge_xml,
    lead_phone_from_doc,
    normalize_phone,
    normalize_lead_phone,
    outbound_bridge_xml,
    plivo_config_debug,
    plivo_error_detail,
    plivo_config,
    plivo_agent_config,
    qualification_payload,
    qualification_result_status,
    qualification_status_from_plivo,
    validate_signature,
)


def test_plivo_config_requires_all_runtime_values(monkeypatch):
    for key in ("PLIVO_AUTH_ID", "PLIVO_AUTH_TOKEN", "PLIVO_FROM_NUMBER", "PLIVO_STAFF_NUMBER"):
        monkeypatch.delenv(key, raising=False)

    try:
        plivo_config()
        assert False, "missing config should fail"
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "Plivo is not configured" in exc.detail


def test_plivo_agent_config_requires_trigger_url_and_from_number(monkeypatch):
    monkeypatch.delenv("PLIVO_AGENT_TRIGGER_URL", raising=False)
    monkeypatch.delenv("PLIVO_FROM_NUMBER", raising=False)

    try:
        plivo_agent_config()
        assert False, "missing agent trigger config should fail"
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "Plivo AI qualification is not configured" in exc.detail


def test_normalize_phone_preserves_plus_when_present():
    assert normalize_phone("+91 98765-43210") == "+919876543210"
    assert normalize_phone("(987) 654-3210") == "9876543210"


def test_normalize_lead_phone_defaults_indian_mobile_to_e164():
    assert normalize_lead_phone("8299752170") == "+918299752170"
    assert lead_phone_from_doc({"field_values": {"phone": "8299752170"}}) == "+918299752170"
    assert normalize_lead_phone("+91 82997 52170") == "+918299752170"


def test_callback_urls_include_lead_id_for_status_and_recording():
    urls = callback_urls("https://example.com", "workspace-1", "lead-1")

    assert urls["outbound_answer"] == "https://example.com/api/plivo/workspaces/workspace-1/calls/lead-1/outbound/answer"
    assert urls["outbound_status"].endswith("/calls/outbound/status?lead_id=lead-1")
    assert urls["inbound_answer"] == "https://example.com/api/plivo/workspaces/workspace-1/calls/inbound/answer"
    assert urls["recording"].endswith("/calls/recording?lead_id=lead-1")
    assert urls["qualification_result"] == "https://example.com/api/plivo/workspaces/workspace-1/calls/lead-1/qualification/result"


def test_plivo_config_debug_masks_secrets_and_generates_urls(monkeypatch):
    monkeypatch.setenv("PLIVO_AUTH_ID", "real-auth-id")
    monkeypatch.setenv("PLIVO_AUTH_TOKEN", "real-auth-token")
    monkeypatch.setenv("PLIVO_FROM_NUMBER", "+91 80 3170 3100")
    monkeypatch.setenv("PLIVO_STAFF_NUMBER", "+91 63948 32742")

    debug = plivo_config_debug("https://public.example", "ws-1", "lead-1")

    assert debug["configured"] is True
    assert debug["public_base_url_https"] is True
    assert debug["auth_id_configured"] is True
    assert debug["auth_token_configured"] is True
    assert debug["dial_sequence"] == "agent_direct_to_lead"
    assert "real-auth-token" not in str(debug)
    assert debug["urls"]["inbound_answer"] == "https://public.example/api/plivo/workspaces/ws-1/calls/inbound/answer"
    assert debug["urls"]["outbound_answer"].endswith("/calls/lead-1/outbound/answer")


def test_qualification_payload_targets_lead_phone(monkeypatch):
    monkeypatch.setenv("PLIVO_FROM_NUMBER", "+91 80 3170 3100")
    payload = qualification_payload(
        "https://public.example",
        "ws-1",
        "lead-1",
        {
            "field_values": {
                "phone": "+91 98765 43210",
                "full_name": "Lead One",
                "email": "lead@example.com",
                "source": "manual",
            },
            "status": "new",
        },
        "+919876543210",
    )

    assert payload["to"] == "+919876543210"
    assert payload["to_number"] == "+919876543210"
    assert payload["phone_number"] == "+919876543210"
    assert payload["from_number"] == "+918031703100"
    assert payload["customer_name"] == "Lead One"
    assert payload["lead_source"] == "manual"
    assert payload["email"] == "lead@example.com"
    assert payload["lead"]["full_name"] == "Lead One"
    assert payload["callbacks"]["status_url"].endswith("/calls/outbound/status?lead_id=lead-1")
    assert payload["callbacks"]["result_url"].endswith("/calls/lead-1/qualification/result")
    assert json.loads(payload["callbacks_json"]) == payload["callbacks"]


def test_qualification_status_maps_plivo_outcomes():
    assert qualification_status_from_plivo({"CallStatus": "answered"}) == "answered"
    assert qualification_status_from_plivo({"CallStatus": "completed"}) == "completed"
    assert qualification_status_from_plivo({"HangupCause": "USER_BUSY"}) == "busy"
    assert qualification_status_from_plivo({"CallStatus": "no-answer"}) == "no_answer"
    assert qualification_status_from_plivo({"CallStatus": "rejected"}) == "failed"


def test_qualification_result_status_maps_agent_outcomes():
    assert qualification_result_status({"qualification_status": "qualified"}) == "completed"
    assert qualification_result_status({"outcome": "not_interested"}) == "failed"
    assert qualification_result_status({"status": "busy"}) == "busy"
    assert qualification_result_status({}) == "completed"


def test_signature_validation_uses_url_nonce_and_sorted_form_params():
    token = "secret"
    url = "https://example.com/api/plivo/workspaces/ws/calls/outbound/status?lead_id=lead-1"
    nonce = "12345"
    payload = f"{url}CallStatusansweredCallUUIDabc.{nonce}"
    signature = base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha256).digest()).decode()

    assert validate_signature("POST", url, nonce, signature, token, {"CallUUID": "abc", "CallStatus": "answered"})
    assert not validate_signature("POST", url, nonce, signature, token, {"CallUUID": "abc", "CallStatus": "failed"})


def test_signature_validation_matches_public_base_url_shape():
    token = "secret"
    url = "https://bookless-triform-lukas.ngrok-free.dev/api/plivo/workspaces/ws/calls/lead-1/outbound/answer"
    nonce = "67890"
    payload = f"{url}CallUUIDabcFrom+916394832742.{nonce}"
    signature = base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha256).digest()).decode()

    assert validate_signature("POST", url, nonce, signature, token, {"From": "+916394832742", "CallUUID": "abc"})


def test_plivo_xml_escapes_phone_and_recording_url():
    outbound = outbound_bridge_xml("+919876543210", "https://example.com/recording?lead_id=a&call_direction=outbound", caller_id="+918031703100")
    inbound = inbound_bridge_xml("+919999999999", "https://example.com/recording?lead_id=b&call_direction=inbound")

    assert '<Dial callerId="+918031703100" timeout="45"><Number>+919876543210</Number></Dial>' in outbound.body.decode()
    assert "&amp;call_direction=outbound" in outbound.body.decode()
    assert "<Dial><Number>+919999999999</Number></Dial>" in inbound.body.decode()
    assert "&amp;call_direction=inbound" in inbound.body.decode()


def test_plivo_error_detail_includes_response_message():
    response = httpx.Response(400, json={"error": "destination is busy"})

    assert plivo_error_detail(response) == "Plivo could not start the call: HTTP 400 - destination is busy"
