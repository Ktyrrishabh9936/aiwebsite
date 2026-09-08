import base64
import hashlib
import hmac
import json

import anyio
import httpx
from fastapi import HTTPException

from plivo_calls import (
    callback_urls,
    cancel_scheduled_qualification_call,
    inbound_bridge_xml,
    lead_phone_from_doc,
    is_junk_lead,
    log_call_note,
    normalize_phone,
    normalize_lead_phone,
    normalize_qualification_category,
    normalize_qualification_score,
    is_mandatory_junk_result,
    outbound_bridge_xml,
    plivo_config_debug,
    plivo_error_detail,
    plivo_config,
    plivo_agent_config,
    communication_summary_from_result,
    normalized_answers,
    normalized_text_list,
    qualification_payload,
    qualification_result_status,
    qualification_status_from_plivo,
    save_qualification_result,
    schedule_first_qualification_call,
    unwrap_qualification_payload,
    validate_signature,
)


class FakeUpdateResult:
    def __init__(self, matched_count=1):
        self.matched_count = matched_count


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.inserted = []

    async def find_one(self, query):
        for doc in self.docs:
            if self._matches(doc, query):
                return doc
        return None

    async def update_one(self, query, update, upsert=False):
        doc = await self.find_one(query)
        if not doc:
            return FakeUpdateResult(0)
        for key, value in (update.get("$set") or {}).items():
            self._set_path(doc, key, value)
        for key, value in (update.get("$push") or {}).items():
            doc.setdefault(key, []).append(value)
        return FakeUpdateResult(1)

    async def insert_one(self, doc):
        self.inserted.append(doc)
        return type("InsertResult", (), {"inserted_id": doc.get("_id")})()

    def _matches(self, doc, query):
        for key, value in query.items():
            if key == "_id" and doc.get("_id") != value:
                return False
            if key == "workspace_id" and doc.get("workspace_id") != value:
                return False
            if "." in key and self._get_path(doc, key) != value:
                return False
        return True

    def _get_path(self, doc, key):
        cur = doc
        for part in key.split("."):
            cur = cur.get(part, {}) if isinstance(cur, dict) else {}
        return cur

    def _set_path(self, doc, key, value):
        cur = doc
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value


class FakeDb:
    def __init__(self, lead):
        self.crm_leads = FakeCollection([lead])
        self.crm_settings = FakeCollection([{"workspace_id": lead["workspace_id"], "fields": [], "states": [], "templates": [], "organization": {}}])
        self.crm_call_logs = FakeCollection([])

    def __getitem__(self, name):
        return getattr(self, name)


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


def test_qualification_payload_includes_previous_context(monkeypatch):
    monkeypatch.setenv("PLIVO_FROM_NUMBER", "+91 80 3170 3100")
    payload = qualification_payload(
        "https://public.example",
        "ws-1",
        "lead-1",
        {
            "field_values": {"phone": "+91 98765 43210", "full_name": "Lead One"},
            "status": "new",
            "communication_summary": {
                "answers": {"budget": "50 lakh"},
                "collected_information": ["Budget confirmed"],
                "pending_discussion": ["Decision maker"],
                "recommended_next_steps": ["Send pricing"],
            },
            "lead_notes": [{"body": "Asked about budget", "source": "call_agent", "summary": "Budget captured"}],
        },
        "+919876543210",
    )

    assert payload["previous_answers"] == {"budget": "50 lakh"}
    assert payload["pending_discussion"] == ["Decision maker"]
    assert payload["previous_lead_notes"][0]["body"] == "Asked about budget"
    assert "Do not repeat questions" in payload["agent_instructions"]


def test_qualification_score_and_category_normalize():
    assert normalize_qualification_score({"qualification_score": "87%"}) == 87
    assert normalize_qualification_score({"score": 105}) == 100
    assert normalize_qualification_category({"qualification_category": "Hot Lead"}) == "hot"
    assert normalize_qualification_category({}, 18) == "junk"


def test_unwrap_qualification_payload_accepts_vibe_envelopes():
    payload = unwrap_qualification_payload({
        "result": json.dumps({
            "qualification_score": "74",
            "qualification_category": "warm",
            "call_summary": "Lead asked for pricing.",
        }),
        "callbacks": {"result_url": "https://example.test/callback"},
    })

    assert payload["qualification_score"] == "74"
    assert payload["qualification_category"] == "warm"
    assert payload["call_summary"] == "Lead asked for pricing."


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
    assert qualification_result_status({"status": "rejected"}) == "failed"
    assert qualification_result_status({}) == "completed"


def test_mandatory_junk_result_detects_policy_outcomes():
    assert is_mandatory_junk_result({"outcome": "not_interested"})
    assert is_mandatory_junk_result({"qualification_status": "wrong_contact"})
    assert is_mandatory_junk_result({"disconnection_reason": "do_not_call"})
    assert is_mandatory_junk_result({"reason": "invalid"})
    assert not is_mandatory_junk_result({"qualification_status": "completed", "qualification_category": "cold"})


def test_qualification_result_normalizes_communication_summary():
    payload = {
        "qualification_status": "qualified",
        "summary": "Budget confirmed and follow-up needed.",
        "recording_url": "https://recordings.example/call.mp3",
        "call_uuid": "call-1",
        "answers": {"budget": "50 lakh", "timeline": "This month", "empty": ""},
        "collected_information": ["Budget confirmed", "Budget confirmed", "Timeline is this month"],
        "pending_discussion": "Decision maker confirmation\nSite visit availability",
        "recommended_next_steps": ["Call back within 24 hours", "Send pricing details"],
        "qualification_score": 82,
        "qualification_category": "hot",
        "duration": "54",
        "objections": ["Needs director approval"],
    }
    lead = {
        "field_values": {"phone": "8299752170"},
        "communication_summary": {"total_call_count": 1, "collected_information": ["Name confirmed"]},
    }

    summary = communication_summary_from_result(lead, payload, "completed", payload["summary"], payload["recording_url"])

    assert normalized_answers(payload) == {"budget": "50 lakh", "timeline": "This month"}
    assert normalized_text_list(payload["pending_discussion"]) == ["Decision maker confirmation", "Site visit availability"]
    assert summary["total_call_count"] == 2
    assert summary["last_recording_url"] == "https://recordings.example/call.mp3"
    assert summary["collected_information"] == ["Name confirmed", "Budget confirmed", "Timeline is this month"]
    assert summary["pending_discussion"] == ["Decision maker confirmation", "Site visit availability"]
    assert summary["recommended_next_steps"] == ["Call back within 24 hours", "Send pricing details"]
    assert summary["qualification_score"] == 82
    assert summary["qualification_category"] == "hot"
    assert summary["last_duration"] == "54"
    assert summary["objections"] == ["Needs director approval"]


def test_qualification_result_summary_accepts_call_summary_alias():
    from plivo_calls import qualification_result_summary

    assert qualification_result_summary({"call_summary": "Lead wants pricing."}) == "Lead wants pricing."


def test_qualification_result_summary_accepts_nested_vibe_alias():
    from plivo_calls import qualification_result_summary

    assert qualification_result_summary({"output": {"finalSummary": "Lead wants a site visit."}}) == "Lead wants a site visit."


def test_qualification_result_summary_fallback_names_missing_fields():
    from plivo_calls import qualification_result_summary

    summary = qualification_result_summary({"qualification_status": "completed"})

    assert "no summary was included" in summary
    assert "qualification_status" in summary


def test_normalizers_parse_json_string_answers_and_lists():
    assert normalized_answers({"answers": "{\"budget\":\"50 lakh\"}"}) == {"budget": "50 lakh"}
    assert normalized_text_list("[\"Budget confirmed\", \"Timeline next week\"]") == ["Budget confirmed", "Timeline next week"]


def test_schedule_first_qualification_call_sets_five_minute_state():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {"_id": lead_id, "workspace_id": "ws-1", "field_values": {"phone": "8299752170"}, "qualification_call": {}, "lead_notes": []}
        db = FakeDb(lead)

        result = await schedule_first_qualification_call(db, "ws-1", str(lead_id))

        assert result["status"] == "scheduled"
        assert lead["qualification_call"]["status"] == "scheduled"
        assert lead["qualification_call"]["phone"] == "+918299752170"
        assert lead["lead_notes"][-1]["status"] == "scheduled"

    anyio.run(run)


def test_schedule_invalid_phone_marks_junk_and_blocks_call():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {"_id": lead_id, "workspace_id": "ws-1", "field_values": {"phone": "123"}, "qualification_call": {}, "lead_notes": []}
        db = FakeDb(lead)

        result = await schedule_first_qualification_call(db, "ws-1", str(lead_id))

        assert result["status"] == "junk"
        assert lead["status"] == "lost"
        assert lead["qualification_call"]["qualification_category"] == "junk"
        assert is_junk_lead(lead)

    anyio.run(run)


def test_cancel_scheduled_qualification_call_updates_state():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {
            "_id": lead_id,
            "workspace_id": "ws-1",
            "field_values": {"phone": "8299752170"},
            "qualification_call": {"status": "scheduled", "scheduled_for": "2030-01-01T00:00:00+00:00"},
            "lead_notes": [],
        }
        db = FakeDb(lead)

        result = await cancel_scheduled_qualification_call(db, "ws-1", str(lead_id), "admin@example.com")

        assert result["status"] == "cancelled"
        assert lead["qualification_call"]["status"] == "cancelled"
        assert lead["qualification_call"]["cancelled_by"] == "admin@example.com"

    anyio.run(run)


def test_save_qualification_result_marks_not_interested_as_junk_without_category():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {
            "_id": lead_id,
            "workspace_id": "ws-1",
            "field_values": {"phone": "8299752170"},
            "qualification_call": {"status": "started"},
            "communication_summary": {},
            "lead_notes": [],
        }
        db = FakeDb(lead)

        result = await save_qualification_result(db, "ws-1", str(lead_id), {
            "qualification_status": "not_interested",
            "summary": "Lead declined future contact.",
        })

        assert result["status"] == "failed"
        assert lead["status"] == "lost"
        assert lead["qualification_call"]["qualification_category"] == "junk"
        assert lead["qualification_call"]["qualification_score"] == 0
        assert lead["communication_summary"]["qualification_category"] == "junk"
        assert lead["communication_summary"]["disconnection_reason"] == "not_interested"

    anyio.run(run)


def test_save_qualification_result_stores_wrapped_vibe_payload_context():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {
            "_id": lead_id,
            "workspace_id": "ws-1",
            "field_values": {"phone": "8299752170"},
            "qualification_call": {"status": "started"},
            "communication_summary": {},
            "lead_notes": [],
        }
        db = FakeDb(lead)

        result = await save_qualification_result(db, "ws-1", str(lead_id), {
            "output": {
                "qualification_status": "completed",
                "qualification_score": "74",
                "qualification_category": "warm",
                "call_summary": "Lead needs a demo and pricing.",
                "recordingUrl": "https://recordings.example/warm.mp3",
                "answers": {"timeline": "next week"},
            }
        })

        assert result["status"] == "completed"
        assert lead["qualification_call"]["qualification_category"] == "warm"
        assert lead["qualification_call"]["qualification_score"] == 74
        assert lead["communication_summary"]["latest_summary"] == "Lead needs a demo and pricing."
        assert lead["communication_summary"]["last_recording_url"] == "https://recordings.example/warm.mp3"
        assert lead["communication_summary"]["answers"] == {"timeline": "next week"}

    anyio.run(run)


def test_log_call_note_updates_communication_summary_for_status_only_callbacks():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {
            "_id": lead_id,
            "workspace_id": "ws-1",
            "field_values": {"phone": "8299752170"},
            "qualification_call": {"status": "started"},
            "communication_summary": {},
            "lead_notes": [],
        }
        db = FakeDb(lead)

        await log_call_note(db, "ws-1", str(lead_id), {
            "CallUUID": "call-123",
            "CallStatus": "completed",
            "Duration": "42",
        }, {
            "event": "outbound_status",
            "call_direction": "outbound",
            "body": "Outbound Plivo call status: completed",
            "outcome": "completed",
        })

        assert lead["communication_summary"]["latest_summary"] == "Outbound Plivo call status: completed"
        assert lead["communication_summary"]["last_call_status"] == "completed"
        assert lead["communication_summary"]["last_call_uuid"] == "call-123"
        assert lead["communication_summary"]["last_duration"] == "42"
        assert lead["communication_summary"]["total_call_count"] == 1

    anyio.run(run)


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
