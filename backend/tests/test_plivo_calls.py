import base64
import hashlib
import hmac

from fastapi import HTTPException

from plivo_calls import (
    callback_urls,
    inbound_bridge_xml,
    normalize_phone,
    outbound_bridge_xml,
    plivo_config,
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


def test_normalize_phone_preserves_plus_when_present():
    assert normalize_phone("+91 98765-43210") == "+919876543210"
    assert normalize_phone("(987) 654-3210") == "9876543210"


def test_callback_urls_include_lead_id_for_status_and_recording():
    urls = callback_urls("https://example.com", "workspace-1", "lead-1")

    assert urls["outbound_answer"] == "https://example.com/api/plivo/workspaces/workspace-1/calls/lead-1/outbound/answer"
    assert urls["outbound_status"].endswith("/calls/outbound/status?lead_id=lead-1")
    assert urls["recording"].endswith("/calls/recording?lead_id=lead-1")


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
    outbound = outbound_bridge_xml("+919876543210", "https://example.com/recording?lead_id=a&call_direction=outbound")
    inbound = inbound_bridge_xml("+919999999999", "https://example.com/recording?lead_id=b&call_direction=inbound")

    assert "<Dial><Number>+919876543210</Number></Dial>" in outbound.body.decode()
    assert "&amp;call_direction=outbound" in outbound.body.decode()
    assert "<Dial><Number>+919999999999</Number></Dial>" in inbound.body.decode()
    assert "&amp;call_direction=inbound" in inbound.body.decode()
