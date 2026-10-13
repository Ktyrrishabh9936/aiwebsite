import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from bson import ObjectId
from fastapi import HTTPException

import lead_forms
import onboarding
import product_knowledge


def _get(doc, path):
    for part in path.split("."):
        if not isinstance(doc, dict):
            return None
        doc = doc.get(part)
    return doc


def _matches(doc, query):
    for key, cond in query.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
            continue
        value = _get(doc, key)
        if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
            for op, arg in cond.items():
                if op == "$ne" and value == arg: return False
                if op == "$gte" and (value is None or value < arg): return False
                if op == "$in" and value not in arg: return False
        elif value != cond:
            return False
    return True


def _set(doc, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        doc = doc.setdefault(part, {})
    doc[parts[-1]] = value


class Cursor:
    def __init__(self, rows): self.rows = rows
    def sort(self, *a, **k): return self
    def skip(self, *a): return self
    def limit(self, *a): return self
    async def to_list(self, n): return self.rows[:n]


class Collection:
    def __init__(self): self.rows = []

    async def find_one(self, query, projection=None, **kwargs):
        return next((r for r in self.rows if _matches(r, query)), None)

    def find(self, query=None, projection=None):
        return Cursor([r for r in self.rows if _matches(r, query or {})])

    async def insert_one(self, doc):
        if "_id" not in doc: doc["_id"] = ObjectId()
        self.rows.append(doc)
        return SimpleNamespace(inserted_id=doc["_id"])

    def _apply(self, row, update):
        for path, value in update.get("$set", {}).items(): _set(row, path, value)
        for path, value in update.get("$inc", {}).items(): _set(row, path, (_get(row, path) or 0) + value)
        for path, value in update.get("$push", {}).items(): _set(row, path, [*(_get(row, path) or []), value])
        for path, value in update.get("$addToSet", {}).items():
            current = _get(row, path) or []
            _set(row, path, current if value in current else [*current, value])

    async def update_one(self, query, update, upsert=False):
        row = await self.find_one(query)
        if row: self._apply(row, update)
        return SimpleNamespace(matched_count=int(bool(row)))

    async def find_one_and_update(self, query, update, upsert=False, return_document=False):
        row = await self.find_one(query)
        if not row and upsert:
            row = {**{k: v for k, v in query.items() if not k.startswith("$")}}
            for path, value in update.get("$setOnInsert", {}).items(): _set(row, path, value)
            self.rows.append(row)
        if row: self._apply(row, update)
        return row


class Db:
    def __getattr__(self, name):
        coll = Collection()
        setattr(self, name, coll)
        return coll


def request(origin=None, host="forms.arevei.com"):
    headers = {"host": host, **({"origin": origin} if origin else {})}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host="1.2.3.4"), url=SimpleNamespace(scheme="https", netloc=host))


def make_form(**overrides):
    form = {"_id": ObjectId(), "workspace_id": "ws1", "name": "Launch page", "form_key": "lf_test", "status": "active",
            "allowed_origins": [], "fields": deepcopy(lead_forms.DEFAULT_FORM_FIELDS),
            "defaults": {**lead_forms.DEFAULT_LEAD_DEFAULTS, "trigger_ai_call": False}, "stats": {}}
    form.update(overrides)
    return form


def run(coro):
    return asyncio.run(coro)


def test_phone_normalisation_uses_country_code():
    assert lead_forms.to_e164("98765 43210", "IN") == "+919876543210"
    assert lead_forms.to_e164("098765 43210", "+91") == "+919876543210"
    assert lead_forms.to_e164("+1 (555) 123-4567", "IN") == "+15551234567"
    assert lead_forms.to_e164("5551234567", "US") == "+15551234567"
    assert lead_forms.to_e164("123", "IN") == ""


def test_validation_reports_field_errors():
    form = make_form()
    with pytest.raises(HTTPException) as exc:
        lead_forms.validate_payload(form, {"full_name": "", "phone": "12", "email": "nope"})
    assert set(exc.value.detail["errors"]) == {"full_name", "phone", "email"}


def test_submission_creates_lead_with_utm_and_requirement():
    db, form = Db(), make_form()
    db.lead_forms.rows.append(form)
    payload = {"full_name": "Priya", "email": "PRIYA@example.com", "phone": "9876543210", "country_code": "IN",
               "requirement": "3BHK under 1.2 Cr", "utm_source": "facebook", "utm_campaign": "diwali",
               "page_url": "https://villas.example.com/launch", "submission_id": "abc"}
    result = run(lead_forms.process_submission(db, form, payload, request()))
    lead = db.crm_leads.rows[0]
    assert result["ok"] and not result["duplicate"]
    assert lead["phone"] == "+919876543210" and lead["phone_country_code"] == "+91"
    assert lead["field_values"]["requirement"] == "3BHK under 1.2 Cr"
    assert lead["field_values"]["email"] == "priya@example.com"
    assert lead["utm"]["utm_source"] == "facebook" and lead["utm"]["utm_campaign"] == "diwali"
    assert lead["source"] == "landing_form" and lead["form_id"] == str(form["_id"])
    assert lead["sheet_row_key"] == f"form:{form['_id']}:abc"
    assert form["stats"]["leads"] == 1
    assert db.notifications.rows and db.lead_form_submissions.rows[0]["result"] == "created"


def test_retry_with_same_submission_id_is_idempotent_and_repeat_enquiry_updates_lead():
    db, form = Db(), make_form()
    db.lead_forms.rows.append(form)
    payload = {"full_name": "Priya", "phone": "9876543210", "submission_id": "abc"}
    run(lead_forms.process_submission(db, form, payload, request()))
    again = run(lead_forms.process_submission(db, form, payload, request()))
    assert again["duplicate"] and len(db.crm_leads.rows) == 1
    repeat = run(lead_forms.process_submission(db, form, {**payload, "submission_id": "xyz", "requirement": "Now 4BHK"}, request()))
    lead = db.crm_leads.rows[0]
    assert repeat["duplicate"] and len(db.crm_leads.rows) == 1
    assert "Repeat Enquiry" in lead["tags"]
    assert lead["timeline"][-1]["type"] == "form_resubmitted"
    assert form["stats"]["duplicates"] == 1


def test_origin_allowlist():
    form = make_form(allowed_origins=["example.com"])
    lead_forms.assert_origin_allowed(form, request("https://www.example.com"))
    lead_forms.assert_origin_allowed(form, request("https://forms.arevei.com"))  # hosted form page
    lead_forms.assert_origin_allowed(form, request())  # server-to-server
    with pytest.raises(HTTPException) as exc:
        lead_forms.assert_origin_allowed(form, request("https://evil.test"))
    assert exc.value.status_code == 403


def test_hosted_form_page_is_shareable_and_frame_restricted():
    form = make_form(allowed_origins=["example.com"])
    response = lead_forms.hosted_form_page(form, request())
    body = response.body.decode()
    assert 'data-arevei-form="lf_test"' in body
    assert 'src="https://forms.arevei.com/api/embed/form.js"' in body
    policy = response.headers["content-security-policy"]
    assert "frame-ancestors https://example.com https://*.example.com" in policy
    assert response.headers["x-content-type-options"] == "nosniff"


def test_frame_embed_forwards_attribution_and_validates_resize_origin():
    assert "arevei_page_url" in lead_forms.FRAME_JS
    assert "utm_campaign" in lead_forms.FRAME_JS
    assert "event.origin!==frame.__areveiOrigin" in lead_forms.FRAME_JS
    assert "arevei:resize" in lead_forms.EMBED_JS


def test_rate_limit_per_ip():
    db, form = Db(), make_form()
    for _ in range(lead_forms.RATE_PER_IP_PER_MINUTE):
        run(lead_forms.assert_rate(db, form, request()))
    with pytest.raises(HTTPException) as exc:
        run(lead_forms.assert_rate(db, form, request()))
    assert exc.value.status_code == 429


def test_phone_is_always_required():
    fields = lead_forms.clean_fields({"phone": {"enabled": False, "required": False}, "email": {"enabled": False, "required": True}}, None)
    assert fields["phone"]["enabled"] and fields["phone"]["required"]
    assert not fields["email"]["required"]


def test_interview_amounts_and_choices():
    assert onboarding.parse_amount("50 lakh") == 5_000_000
    assert onboarding.parse_amount("1.2 Cr") == 12_000_000
    assert onboarding.parse_amount("50k") == 50_000
    assert onboarding.interpret({"key": "business_stage", "type": "choice"}, "Already selling") == "existing"
    assert onboarding.interpret({"key": "monthly_revenue_target", "type": "number"}, "no idea") is None


def test_product_knowledge_finds_relevant_feature():
    assert product_knowledge.search("How do I connect my landing page form?")[0]["title"] == "Landing Page Forms"
    assert product_knowledge.is_help_question("What can you do?")
    assert product_knowledge.help_context("Show me hot leads from today") == ""
