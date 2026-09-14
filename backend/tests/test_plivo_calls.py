import base64
import hashlib
import hmac
import json

import anyio
import pytest
import httpx
from fastapi import HTTPException

from plivo_calls import (
    DEFAULT_AGENT_INPUT_MAPPINGS,
    agent_flow_xml,
    callback_urls,
    cancel_scheduled_qualification_call,
    build_agent_trigger_payload,
    assign_plivo_call_uuid,
    inbound_bridge_xml,
    lead_phone_from_doc,
    is_junk_lead,
    log_call_note,
    normalize_phone,
    normalize_lead_phone,
    normalize_qualification_category,
    normalize_qualification_score,
    normalize_agent_config,
    normalize_budget_inr,
    is_mandatory_junk_result,
    outbound_bridge_xml,
    plivo_config_debug,
    plivo_error_detail,
    plivo_config,
    plivo_agent_config,
    sanitize_agent_config,
    communication_summary_from_result,
    normalized_answers,
    normalized_text_list,
    qualification_payload,
    recommended_next_action,
    qualification_result_status,
    qualification_status_from_plivo,
    run_ai_qualification,
    save_qualification_result,
    score_structured_qualification,
    schedule_first_qualification_call,
    start_qualification_call,
    store_plivo_event,
    trigger_auth_for_agent,
    structured_qualification_from_payload,
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
        if doc is None:
            if not upsert:
                return FakeUpdateResult(0)
            doc = {**query, **update.get("$setOnInsert", {})}
            self.docs.append(doc)
        for key, value in (update.get("$addToSet") or {}).items():
            items = doc.setdefault(key, [])
            if value not in items:
                items.append(value)
        for key, value in (update.get("$set") or {}).items():
            self._set_path(doc, key, value)
        for key, value in (update.get("$unset") or {}).items():
            self._unset_path(doc, key)
        for key, value in (update.get("$push") or {}).items():
            doc.setdefault(key, []).append(value)
        return FakeUpdateResult(1)

    async def find_one_and_update(self, query, update, **kwargs):
        doc = await self.find_one(query)
        if doc is None:
            return None
        await self.update_one(query, update)
        return doc

    async def count_documents(self, query):
        return sum(self._matches(doc, query) for doc in self.docs)

    async def update_many(self, query, update):
        matched = 0
        for doc in self.docs:
            if self._matches(doc, query):
                matched += 1
                for key, value in (update.get("$set") or {}).items():
                    self._set_path(doc, key, value)
                for key, value in (update.get("$unset") or {}).items():
                    self._unset_path(doc, key)
        return FakeUpdateResult(matched)

    async def insert_one(self, doc):
        self.inserted.append(doc)
        self.docs.append(doc)
        return type("InsertResult", (), {"inserted_id": doc.get("_id")})()

    def _matches(self, doc, query):
        for key, value in query.items():
            if key == "$or":
                if not any(self._matches(doc, item) for item in value):
                    return False
                continue
            if isinstance(value, dict):
                current = self._get_path(doc, key) if "." in key else doc.get(key)
                if "$exists" in value and (current is not None) != value["$exists"]:
                    return False
                if "$lt" in value and (current is None or current >= value["$lt"]):
                    return False
                if "$in" in value and current not in value["$in"]:
                    return False
                if "$ne" in value and current == value["$ne"]:
                    return False
                continue
            if key == "_id" and doc.get("_id") != value:
                return False
            if key == "workspace_id" and doc.get("workspace_id") != value:
                return False
            if "." in key and self._get_path(doc, key) != value:
                return False
            if key not in {"_id", "workspace_id"} and "." not in key and doc.get(key) != value:
                return False
        return True

    def _get_path(self, doc, key):
        cur = doc
        for part in key.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        return cur

    def _set_path(self, doc, key, value):
        cur = doc
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def _unset_path(self, doc, key):
        parts = key.split(".")
        if len(parts) == 1:
            doc.pop(parts[0], None)
            return
        cur = doc
        for part in parts[:-1]:
            if not isinstance(cur, dict):
                return
            cur = cur.get(part)
            if cur is None:
                return
        if isinstance(cur, dict):
            cur.pop(parts[-1], None)


class FakeDb:
    def __init__(self, lead, agents=None):
        self.crm_leads = FakeCollection([lead])
        self.crm_settings = FakeCollection([{"workspace_id": lead["workspace_id"], "fields": [], "states": [], "templates": [], "organization": {}}])
        self.crm_call_logs = FakeCollection([])
        self.workspaces = FakeCollection([])
        self.plivo_agent_configs = FakeCollection(agents or [])
        self.plivo_call_sessions = FakeCollection([])
        self.plivo_call_events = FakeCollection([])
        self.qualification_profiles = FakeCollection([])
        self.plivo_workflow_configs = FakeCollection([])
        self.tasks = FakeCollection([])

    def __getitem__(self, name):
        return getattr(self, name)


@pytest.fixture(autouse=True)
def default_fact_extraction(monkeypatch):
    import llm_service
    async def unavailable(*args, **kwargs):
        raise RuntimeError("No live AI in unit tests")
    monkeypatch.setattr(llm_service, "generate_json", unavailable)


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


def test_normalize_agent_config_keeps_trigger_secret_server_side():
    config = normalize_agent_config({
        "display_name": "DLF Sales Agent",
        "flow_id": "flow-123",
        "trigger_url": "https://agentflow.plivo.com/v1/account/auth/flow/flow-123",
        "auth_type": "basic",
        "auth_username": "api-user",
        "auth_password": "api-secret",
        "from_number": "+918031703100",
        "input_variable_mappings": {
            "mobile": "lead.phone",
            "name": "lead.full_name",
            "result_callback": "callbacks.result_url",
        },
    })
    public = sanitize_agent_config({**config, "_id": "agent-1"})

    assert config["credentials"] == {"username": "api-user", "password": "api-secret"}
    assert public["credential_configured"] is True
    assert "credentials" not in public
    assert "api-secret" not in str(public)
    assert public["input_variable_mappings"]["mobile"] == "lead.phone"


def test_legacy_agent_uses_plivo_basic_auth_from_env(monkeypatch):
    from plivo_calls import legacy_agent_config_from_env

    monkeypatch.setenv("PLIVO_AGENT_TRIGGER_URL", "https://agentflow.plivo.com/v1/account/auth/flow/flow-123")
    monkeypatch.delenv("PLIVO_AGENT_TRIGGER_TOKEN", raising=False)
    monkeypatch.setenv("PLIVO_AUTH_ID", "auth-id")
    monkeypatch.setenv("PLIVO_AUTH_TOKEN", "auth-token")
    monkeypatch.setenv("PLIVO_FROM_NUMBER", "+918031703100")

    agent = legacy_agent_config_from_env()
    headers, auth = trigger_auth_for_agent(agent)

    assert agent["auth_type"] == "basic"
    assert sanitize_agent_config(agent)["credential_configured"] is True
    assert "Authorization" not in headers
    assert auth == ("auth-id", "auth-token")


def test_basic_agent_without_saved_credentials_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("PLIVO_AUTH_ID", "auth-id")
    monkeypatch.setenv("PLIVO_AUTH_TOKEN", "auth-token")

    config = normalize_agent_config({
        "display_name": "Env Auth Agent",
        "trigger_url": "https://agentflow.plivo.com/v1/account/auth/flow/flow-123",
        "auth_type": "basic",
        "from_number": "+918031703100",
    })
    headers, auth = trigger_auth_for_agent(config)

    assert config["credentials"] == {}
    assert sanitize_agent_config(config)["credential_configured"] is True
    assert "Authorization" not in headers
    assert auth == ("auth-id", "auth-token")


def test_build_agent_trigger_payload_uses_configured_input_mappings(monkeypatch):
    monkeypatch.setenv("PLIVO_FROM_NUMBER", "+918031703100")
    agent = normalize_agent_config({
        "display_name": "Inventory Agent",
        "trigger_url": "https://agentflow.plivo.com/v1/account/auth/flow/flow-abc",
        "auth_type": "bearer",
        "bearer_token": "secret",
        "from_number": "+918031703100",
        "input_variable_mappings": {
            "customer_mobile": "lead.phone",
            "customer_name": "lead.full_name",
            "callback": "callbacks.result_url",
            "fixed_campaign": "literal:AREVEI Demo",
            "session": "session.id",
        },
    })
    base = qualification_payload(
        "https://public.example",
        "111111111111111111111111",
        "lead-1",
        {"field_values": {"phone": "+919876543210", "full_name": "Riya", "source": "Meta Ads"}},
        "+919876543210",
        agent,
        "session-1",
    )
    payload = build_agent_trigger_payload(base, agent, "session-1")

    assert payload == {
        "customer_mobile": "+919876543210",
        "customer_name": "Riya",
        "callback": "https://public.example/api/plivo/workspaces/111111111111111111111111/calls/lead-1/qualification/result",
        "fixed_campaign": "AREVEI Demo",
        "session": "session-1",
    }
    assert "lead" not in payload


def test_start_qualification_call_creates_session_and_uses_selected_agent(monkeypatch):
    from bson import ObjectId

    class FakeAsyncClient:
        last_request = {}

        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None, auth=None):
            FakeAsyncClient.last_request = {"url": url, "json": json, "headers": headers, "auth": auth}
            return httpx.Response(200, json={"execution_id": "exec-1", "request_uuid": "call-1"})

    async def run():
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://public.example")
        import plivo_calls

        monkeypatch.setattr(plivo_calls.httpx, "AsyncClient", FakeAsyncClient)
        lead_id = ObjectId()
        agent_id = ObjectId()
        agent = normalize_agent_config({
            "display_name": "Sales Qualifier",
            "flow_id": "flow-1",
            "trigger_url": "https://agentflow.plivo.com/v1/account/auth/flow/flow-1",
            "auth_type": "basic",
            "auth_username": "trigger-user",
            "auth_password": "trigger-password",
            "from_number": "+918031703100",
            "input_variable_mappings": {
                "phone": "lead.phone",
                "name": "lead.full_name",
                "session_id": "session.id",
            },
        })
        agent.update({"_id": agent_id, "workspace_id": "111111111111111111111111", "enabled": True, "is_default": True})
        lead = {
            "_id": lead_id,
            "workspace_id": "111111111111111111111111",
            "field_values": {"phone": "8299752170", "full_name": "Aarav"},
            "qualification_call": {},
            "lead_notes": [],
        }
        db = FakeDb(lead, [agent])
        request = type("RequestContext", (), {
            "headers": {},
            "url": type("UrlContext", (), {"scheme": "https", "netloc": "public.example", "path": "", "query": ""})(),
        })()

        result = await start_qualification_call(db, "111111111111111111111111", str(lead_id), request, agent_config_id=str(agent_id))

        session = db.plivo_call_sessions.docs[0]
        sent = FakeAsyncClient.last_request
        assert result["status"] == "started"
        assert result["session_id"] == str(session["_id"])
        assert result["agent_display_name"] == "Sales Qualifier"
        assert sent["url"] == agent["trigger_url"]
        assert sent["auth"] == ("trigger-user", "trigger-password")
        assert sent["json"] == {"phone": "+918299752170", "name": "Aarav", "session_id": str(session["_id"])}
        assert session["agent_snapshot"]["display_name"] == "Sales Qualifier"
        assert session["provider_identifiers"]["execution_id"] == "exec-1"
        assert lead["qualification_call"]["agent_config_id"] == str(agent_id)
        assert lead["qualification_call"]["session_id"] == str(session["_id"])

    anyio.run(run)


def test_default_agent_input_mappings_include_correlation_fields():
    assert DEFAULT_AGENT_INPUT_MAPPINGS["lead_id"] == "lead_id"
    assert DEFAULT_AGENT_INPUT_MAPPINGS["session_id"] == "session.id"
    assert DEFAULT_AGENT_INPUT_MAPPINGS["result_url"] == "callbacks.result_url"


def test_real_estate_qualification_normalizes_budget_score_and_action():
    payload = {
        "qualification_status": "completed",
        "summary": "Lead wants a 3 BHK in Gurgaon and asked for a site visit.",
        "answers": {
            "budget": "1.2 Cr",
            "location": "Gurgaon",
            "property_type": "3 BHK",
            "purpose": "End use",
            "timeline": "30-45 days",
            "intent": "High intent",
            "site_visit_interest": "yes",
        },
    }
    structured = structured_qualification_from_payload(payload)
    score = score_structured_qualification(structured)
    action = recommended_next_action(structured, score, "completed")

    assert normalize_budget_inr("1.2 Cr")["normalized_inr_min"] == 12000000
    assert structured["budget"]["normalized_inr_max"] == 12000000
    assert structured["preferred_location"] == "Gurgaon"
    assert score["score"] == 100
    assert score["category"] == "hot"
    assert action["type"] == "schedule_site_visit"


def test_real_estate_qualification_keeps_no_answer_separate_from_cold():
    structured = structured_qualification_from_payload({"status": "no_answer", "summary": "No answer."})
    score = score_structured_qualification(structured)

    assert score["score"] is None
    assert score["category"] == "insufficient_data"
    assert score["qualification_processing_status"] == "no_answer"


def test_store_plivo_event_deduplicates_by_kind_and_event_identity():
    from bson import ObjectId

    async def run():
        lead = {"_id": ObjectId(), "workspace_id": "111111111111111111111111", "field_values": {"phone": "8299752170"}}
        db = FakeDb(lead)

        first, duplicate_first = await store_plivo_event(db, "111111111111111111111111", str(lead["_id"]), "outbound_status", {"CallUUID": "call-1", "Event": "Ring", "CallStatus": "ringing"})
        second, duplicate_second = await store_plivo_event(db, "111111111111111111111111", str(lead["_id"]), "outbound_status", {"CallUUID": "call-1", "Event": "Ring", "CallStatus": "ringing"})
        result, duplicate_result = await store_plivo_event(db, "111111111111111111111111", str(lead["_id"]), "qualification_result", {"call_uuid": "call-1", "qualification_status": "completed"})

        assert duplicate_first is False
        assert duplicate_second is True
        assert duplicate_result is False
        assert first["_id"] == second["_id"]
        assert first["_id"] != result["_id"]
        assert len(db.plivo_call_events.docs) == 2

    anyio.run(run)


def test_assign_plivo_call_uuid_clears_duplicate_values_from_other_leads():
    from bson import ObjectId

    async def run():
        old_lead = {"_id": ObjectId(), "workspace_id": "111111111111111111111111", "plivo_call_uuid": "call-duplicate", "qualification_call": {"call_uuid": "call-duplicate"}}
        new_lead = {"_id": ObjectId(), "workspace_id": "111111111111111111111111", "field_values": {"phone": "+919999999999"}}
        db = FakeDb(old_lead)
        db.crm_leads.docs.append(new_lead)

        await assign_plivo_call_uuid(db, "111111111111111111111111", str(new_lead["_id"]), "call-duplicate")

        old_doc = await db.crm_leads.find_one({"_id": old_lead["_id"]})
        new_doc = await db.crm_leads.find_one({"_id": new_lead["_id"]})

        assert old_doc.get("plivo_call_uuid") is None
        assert old_doc.get("qualification_call", {}).get("call_uuid") is None
        assert new_doc["plivo_call_uuid"] == "call-duplicate"
        assert new_doc["qualification_call"]["call_uuid"] == "call-duplicate"

    anyio.run(run)


def test_save_qualification_result_flattens_nested_data_object_and_preserves_call_uuid():
    from bson import ObjectId

    async def run():
        lead = {"_id": ObjectId(), "workspace_id": "111111111111111111111111", "field_values": {"phone": "+919999999999"}}
        db = FakeDb(lead)

        payload = {
            "data": {
                "object": {
                    "call_uuid": "call-xyz",
                    "CallStatus": "answered",
                    "qualification_status": "completed",
                    "conversation_summary": "Buyer wants a 2 BHK in Gurgaon",
                    "transcript": "Detailed call transcript",
                    "recording_url": "https://example.com/recording.mp3",
                }
            }
        }

        result = await save_qualification_result(db, "111111111111111111111111", str(lead["_id"]), payload)
        updated = await db.crm_leads.find_one({"_id": lead["_id"]})

        assert result["ok"] is True
        assert updated["qualification_call"]["call_uuid"] == "call-xyz"
        assert updated["lead_status"] == "PARTIALLY_QUALIFIED"
        assert updated["communication_summary"]["latest_summary"] == "Buyer wants a 2 BHK in Gurgaon"

    anyio.run(run)


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

    debug = plivo_config_debug("https://public.example", "111111111111111111111111", "lead-1")

    assert debug["configured"] is True
    assert debug["public_base_url_https"] is True
    assert debug["auth_id_configured"] is True
    assert debug["auth_token_configured"] is True
    assert debug["dial_sequence"] == "agent_direct_to_lead"
    assert "real-auth-token" not in str(debug)
    assert debug["urls"]["inbound_answer"] == "https://public.example/api/plivo/workspaces/111111111111111111111111/calls/inbound/answer"
    assert debug["urls"]["outbound_answer"].endswith("/calls/lead-1/outbound/answer")


def test_qualification_payload_targets_lead_phone(monkeypatch):
    monkeypatch.setenv("PLIVO_FROM_NUMBER", "+91 80 3170 3100")
    payload = qualification_payload(
        "https://public.example",
        "111111111111111111111111",
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
        "111111111111111111111111",
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
    assert qualification_result_status({"outcome": "not_interested"}) == "not_interested"
    assert qualification_result_status({"status": "busy"}) == "busy"
    assert qualification_result_status({"status": "rejected"}) == "failed"
    assert qualification_result_status({}) == "completed"


def test_mandatory_junk_result_detects_policy_outcomes():
    assert not is_mandatory_junk_result({"outcome": "not_interested"})
    assert is_mandatory_junk_result({"qualification_status": "wrong_contact"})
    assert not is_mandatory_junk_result({"disconnection_reason": "do_not_call"})
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


def test_normalize_contacto_qualification_payload_maps_event_data_fields():
    from plivo_calls import normalize_contacto_qualification_payload

    payload = {
        "call_uuid": "b1930339-455d-4e50-aecc-6dc02fcac598",
        "conversation_id": "9522-1845327839",
        "event_data": {
            "Property Qualification.budget": "2000000",
            "Property Qualification.preferred_location": "Noida",
            "Property Qualification.property_type": "2 BHK",
            "Property Qualification.qualification_category": "Warm",
            "Property Qualification.qualification_status": "completed",
            "Property Qualification.recommended_next_steps": "requested salesperson callback",
        },
    }

    normalized = normalize_contacto_qualification_payload(payload)

    assert normalized["qualification_status"] == "completed"
    assert normalized["qualification_category"] == "warm"
    assert normalized["budget"] == "2000000"
    assert normalized["preferred_location"] == "Noida"
    assert normalized["property_type"] == "2 BHK"
    assert normalized["recommended_next_steps"] == "requested salesperson callback"
    assert normalized["call_uuid"] == "b1930339-455d-4e50-aecc-6dc02fcac598"
    assert normalized["conversation_id"] == "9522-1845327839"
    assert normalized["event_data"]["Property Qualification.qualification_category"] == "Warm"


def test_save_qualification_result_accepts_contacto_event_data_payload():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {
            "_id": lead_id,
            "workspace_id": "111111111111111111111111",
            "field_values": {"phone": "8299752170"},
            "qualification_call": {"status": "started"},
            "communication_summary": {},
            "lead_notes": [],
        }
        db = FakeDb(lead)

        result = await save_qualification_result(db, "111111111111111111111111", str(lead_id), {
            "call_uuid": "b1930339-455d-4e50-aecc-6dc02fcac598",
            "conversation_id": "9522-1845327839",
            "event_data": {
                "Property Qualification.budget": "2000000",
                "Property Qualification.preferred_location": "Noida",
                "Property Qualification.property_type": "2 BHK",
                "Property Qualification.qualification_category": "Warm",
                "Property Qualification.qualification_status": "completed",
                "Property Qualification.recommended_next_steps": "requested salesperson callback",
            },
        })

        assert result["status"] == "completed"
        assert lead["lead_status"] == "PARTIALLY_QUALIFIED"
        assert lead["qualification_status"] == "manual_review"
        assert lead["qualification_call"]["qualification_category"] == ""
        assert db.crm_call_logs.docs[0]["call_result"]["raw_provider_data"]["event_data"]["Property Qualification.budget"] == "2000000"
        assert db.crm_call_logs.docs[0]["call_result"]["raw_provider_data"]["event_data"]["Property Qualification.preferred_location"] == "Noida"
        assert db.crm_call_logs.docs[0]["call_result"]["raw_provider_data"]["event_data"]["Property Qualification.property_type"] == "2 BHK"
        assert lead["next_action"] == "FOLLOW_UP"

    anyio.run(run)


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
        lead = {"_id": lead_id, "workspace_id": "111111111111111111111111", "field_values": {"phone": "8299752170"}, "qualification_call": {}, "lead_notes": []}
        db = FakeDb(lead)

        result = await schedule_first_qualification_call(db, "111111111111111111111111", str(lead_id))

        assert result["status"] == "scheduled"
        assert lead["qualification_call"]["status"] == "scheduled"
        assert lead["qualification_call"]["phone"] == "+918299752170"
        assert lead["lead_notes"][-1]["status"] == "scheduled"

    anyio.run(run)


def test_schedule_invalid_phone_marks_junk_and_blocks_call():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {"_id": lead_id, "workspace_id": "111111111111111111111111", "field_values": {"phone": "123"}, "qualification_call": {}, "lead_notes": []}
        db = FakeDb(lead)

        result = await schedule_first_qualification_call(db, "111111111111111111111111", str(lead_id))

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
            "workspace_id": "111111111111111111111111",
            "field_values": {"phone": "8299752170"},
            "qualification_call": {"status": "scheduled", "scheduled_for": "2030-01-01T00:00:00+00:00"},
            "lead_notes": [],
        }
        db = FakeDb(lead)

        result = await cancel_scheduled_qualification_call(db, "111111111111111111111111", str(lead_id), "admin@example.com")

        assert result["status"] == "cancelled"
        assert lead["qualification_call"]["status"] == "cancelled"
        assert lead["qualification_call"]["cancelled_by"] == "admin@example.com"

    anyio.run(run)


def test_run_ai_qualification_returns_structured_score_and_tags():
    async def run():
        transcript = "I need a 2 BHK in Gurgaon for my family and budget is around 90 lakh. I am ready to visit this week."
        config = {
            "is_enabled": True,
            "passing_score": 70,
            "criteria": [
                {"field": "budget", "condition": "contains", "value": "90 lakh", "weight": 30},
                {"field": "location", "condition": "contains", "value": "gurgaon", "weight": 25},
                {"field": "timeline", "condition": "contains", "value": "this week", "weight": 20},
            ],
        }

        async def fake_generate_json(*args, **kwargs):
            return {"score": 88, "status": "qualified", "tags": ["High intent", "Ready to visit"], "summary": "Strong fit for a premium family home in Gurgaon."}

        import plivo_calls
        monkeypatch = globals()["monkeypatch"] if "monkeypatch" in globals() else None
        if monkeypatch is None:
            from pytest import MonkeyPatch
            monkeypatch = MonkeyPatch()
        monkeypatch.setattr(plivo_calls, "generate_json", fake_generate_json)
        result = await run_ai_qualification(transcript, config)
        assert result["status"] == "qualified"
        assert result["score"] >= 70
        assert "High intent" in result["tags"]
        assert "Gurgaon" in result["summary"]

    anyio.run(run)


def test_recording_callback_payload_is_processed_as_application_qualification():
    from bson import ObjectId
    from server import maybe_process_recording_as_qualification

    async def run():
        lead_id = ObjectId()
        lead = {
            "_id": lead_id,
            "workspace_id": "111111111111111111111111",
            "field_values": {"phone": "8299752170"},
            "qualification_call": {"status": "started"},
            "communication_summary": {},
            "lead_notes": [],
        }
        db = FakeDb(lead)
        db.workspaces = FakeCollection([{
            "_id": ObjectId(),
            "workspace_id": "111111111111111111111111",
            "user_id": "u-1",
            "ai_qualification_config": {"is_enabled": True, "passing_score": 70, "criteria": []},
        }])

        import plivo_calls
        from pytest import MonkeyPatch
        monkeypatch = MonkeyPatch()

        async def fake_generate_json(*args, **kwargs):
            return {"score": 82, "status": "qualified", "tags": ["Strong fit", "Wants site visit"], "summary": "Interested in a 2 BHK in Noida with immediate move-in."}

        monkeypatch.setattr(plivo_calls, "generate_json", fake_generate_json)

        payload = {
            "data": {
                "object": {
                    "call_uuid": "394c780f-d158-40d9-bdf2-2bcc489242a7",
                    "conversation_id": "9522-1772654112",
                    "event_data": {
                        "conversation_summary": "Customer is interested in a 2 BHK in Noida for personal use and wants an immediate move-in and a site visit.",
                        "transcription": "I want a 2 BHK in Noida for personal use. I can move in immediately and I want a site visit on 14 September at 6 PM.",
                        "recording_url": "https://example.test/recording.wav",
                    },
                }
            }
        }

        result = await maybe_process_recording_as_qualification(db, "111111111111111111111111", str(lead_id), payload)

        assert result["status"] == "completed"
        assert lead["lead_status"] == "PARTIALLY_QUALIFIED"
        assert lead["qualification_status"] == "manual_review"
        assert lead["communication_summary"]["latest_summary"]
        monkeypatch.undo()

    anyio.run(run)


def test_save_qualification_result_uses_manual_review_when_llm_fails():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {
            "_id": lead_id,
            "workspace_id": "111111111111111111111111",
            "field_values": {"phone": "8299752170"},
            "qualification_call": {"status": "started"},
            "communication_summary": {},
            "lead_notes": [],
        }
        db = FakeDb(lead)
        db.workspaces = FakeCollection([{
            "_id": ObjectId(),
            "workspace_id": "111111111111111111111111",
            "user_id": "u-1",
            "ai_qualification_config": {"is_enabled": True, "passing_score": 70, "criteria": []},
        }])

        import plivo_calls
        from pytest import MonkeyPatch
        monkeypatch = MonkeyPatch()

        async def fake_fail(*args, **kwargs):
            raise RuntimeError("LLM down")

        monkeypatch.setattr(plivo_calls, "generate_json", fake_fail)

        result = await save_qualification_result(db, "111111111111111111111111", str(lead_id), {
            "qualification_status": "completed",
            "summary": "Lead wants a 2 BHK in Gurgaon and is very interested.",
            "transcript": "I need a 2 BHK in Gurgaon, my budget is 90 lakh and I want to visit this week.",
        })

        assert result["status"] == "completed"
        assert lead["qualification_status"] == "manual_review"
        assert lead["qualification_call"]["engine_result"]["confidence_score"] == 0
        monkeypatch.undo()

    anyio.run(run)


def test_save_qualification_result_marks_not_interested_as_unqualified_without_category():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {
            "_id": lead_id,
            "workspace_id": "111111111111111111111111",
            "field_values": {"phone": "8299752170"},
            "qualification_call": {"status": "started"},
            "communication_summary": {},
            "lead_notes": [],
        }
        db = FakeDb(lead)

        result = await save_qualification_result(db, "111111111111111111111111", str(lead_id), {
            "qualification_status": "not_interested",
            "summary": "Lead declined future contact.",
        })

        assert result["status"] == "completed"
        assert lead["status"] == "lost"
        assert lead["qualification_call"]["qualification_category"] == ""
        assert lead["qualification_call"]["qualification_score"] == 0
        assert lead["communication_summary"]["qualification_category"] == ""
        assert lead["lead_status"] == "UNQUALIFIED"

    anyio.run(run)


def test_save_qualification_result_stores_wrapped_vibe_payload_context():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {
            "_id": lead_id,
            "workspace_id": "111111111111111111111111",
            "field_values": {"phone": "8299752170"},
            "qualification_call": {"status": "started"},
            "communication_summary": {},
            "lead_notes": [],
        }
        db = FakeDb(lead)

        result = await save_qualification_result(db, "111111111111111111111111", str(lead_id), {
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
        assert lead["qualification_call"]["qualification_category"] == ""
        assert lead["qualification_call"]["qualification_score"] is None
        assert lead["communication_summary"]["latest_summary"] == "Lead needs a demo and pricing."
        assert lead["communication_summary"]["last_recording_url"] == "https://recordings.example/warm.mp3"
        assert db.crm_call_logs.docs[0]["call_result"]["raw_provider_data"]["output"]["answers"] == {"timeline": "next week"}

    anyio.run(run)


def test_save_qualification_result_sets_ai_qualified_status_for_positive_results():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {
            "_id": lead_id,
            "workspace_id": "111111111111111111111111",
            "field_values": {"phone": "8299752170"},
            "qualification_call": {"status": "started"},
            "communication_summary": {},
            "lead_notes": [],
        }
        db = FakeDb(lead)

        await save_qualification_result(db, "111111111111111111111111", str(lead_id), {
            "qualification_status": "completed",
            "qualification_score": "81",
            "qualification_category": "hot",
            "summary": "Lead is interested and wants a site visit.",
        })

        assert lead["lead_status"] == "PARTIALLY_QUALIFIED"
        assert lead["qualification_status"] == "manual_review"
        assert "PARTIALLY_QUALIFIED" in lead["lead_notes"][-1]["body"]

    anyio.run(run)


def test_save_qualification_result_sets_ai_qualified_when_status_is_positive_without_category():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {
            "_id": lead_id,
            "workspace_id": "111111111111111111111111",
            "field_values": {"phone": "8299752170"},
            "qualification_call": {"status": "started"},
            "communication_summary": {},
            "lead_notes": [],
        }
        db = FakeDb(lead)

        await save_qualification_result(db, "111111111111111111111111", str(lead_id), {
            "qualification_status": "qualified",
            "summary": "Lead wants a site visit and budget is 90 lakh.",
            "transcript": "I am interested in a 2BHK in Gurgaon and budget is around 90 lakh.",
        })

        assert lead["lead_status"] == "PARTIALLY_QUALIFIED"
        assert lead["qualification_status"] == "manual_review"
        assert "PARTIALLY_QUALIFIED" in lead["lead_notes"][-1]["body"]

    anyio.run(run)


def test_save_qualification_result_formats_failed_call_notes_for_disconnected_outcomes():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {
            "_id": lead_id,
            "workspace_id": "111111111111111111111111",
            "field_values": {"phone": "8299752170"},
            "qualification_call": {"status": "started"},
            "communication_summary": {},
            "lead_notes": [],
        }
        db = FakeDb(lead)

        await save_qualification_result(db, "111111111111111111111111", str(lead_id), {
            "CallStatus": "busy",
            "summary": "Call was busy and dropped.",
        })

        assert lead["lead_status"] == "PENDING"
        assert lead["qualification_status"] == "pending"
        assert "BUSY" in lead["lead_notes"][-1]["body"]

    anyio.run(run)


def test_log_call_note_updates_communication_summary_for_status_only_callbacks():
    from bson import ObjectId

    async def run():
        lead_id = ObjectId()
        lead = {
            "_id": lead_id,
            "workspace_id": "111111111111111111111111",
            "field_values": {"phone": "8299752170"},
            "qualification_call": {"status": "started"},
            "communication_summary": {},
            "lead_notes": [],
        }
        db = FakeDb(lead)

        await log_call_note(db, "111111111111111111111111", str(lead_id), {
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

    assert 'action="https://example.com/recording?lead_id=a&amp;call_direction=outbound"' in outbound.body.decode()
    assert "<Number>+919876543210</Number>" in outbound.body.decode()
    assert "<Dial><Number>+919999999999</Number></Dial>" in inbound.body.decode()
    assert "&amp;call_direction=inbound" in inbound.body.decode()


def test_agent_flow_redirect_xml_uses_trigger_url(monkeypatch):
    monkeypatch.setenv("PLIVO_AGENT_TRIGGER_URL", "https://agentflow.plivo.com/v1/account/auth/flow/flow-123")

    xml = agent_flow_xml("https://agentflow.plivo.com/v1/account/auth/flow/flow-123", "https://example.com/result")

    body = xml.body.decode()
    assert "<Redirect>https://agentflow.plivo.com/v1/account/auth/flow/flow-123</Redirect>" in body
    assert "result_url=" not in body


def test_plivo_config_includes_agent_trigger_url(monkeypatch):
    monkeypatch.setenv("PLIVO_AUTH_ID", "auth-id")
    monkeypatch.setenv("PLIVO_AUTH_TOKEN", "auth-token")
    monkeypatch.setenv("PLIVO_FROM_NUMBER", "+918031703100")
    monkeypatch.setenv("PLIVO_STAFF_NUMBER", "+918794856351")
    monkeypatch.setenv("PLIVO_AGENT_TRIGGER_URL", "https://agentflow.plivo.com/v1/account/auth/flow/flow-123")

    cfg = plivo_config()
    assert cfg["agent_trigger_url"] == "https://agentflow.plivo.com/v1/account/auth/flow/flow-123"


def test_plivo_error_detail_includes_response_message():
    response = httpx.Response(400, json={"error": "destination is busy"})

    assert plivo_error_detail(response) == "Plivo could not start the call: HTTP 400 - destination is busy"
