"""Landing Page Form connector: capture leads from any website into the CRM.

Owners configure forms (fields, lead defaults, appearance, allowed domains) and
install them via an embed script, by connecting an existing form, or by posting
to the public submit endpoint. Submissions carry hidden UTM attribution.
"""
import asyncio
import hashlib
import json
import logging
import re
import secrets
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import parse_qs, urlparse

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pymongo.errors import DuplicateKeyError

from countries import BY_ISO, COUNTRIES, dial_code
from crm import build_manual_lead, db_from, doc_out, ensure_crm_settings, require_workspace_access
from models import now_iso

logger = logging.getLogger("lead_forms")
router = APIRouter(prefix="/workspaces/{ws_id}/lead-forms", dependencies=[Depends(require_workspace_access)], tags=["Landing page forms"])
public_router = APIRouter(tags=["Landing page forms (public)"])

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")
CLICK_KEYS = ("gclid", "fbclid")
FIELD_KEYS = ("full_name", "email", "phone", "requirement")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RATE_PER_IP_PER_MINUTE = 8
RATE_PER_FORM_PER_MINUTE = 120
SUBMISSION_LOG_DAYS = 90
MAX_BODY_BYTES = 16_000

DEFAULT_FORM_FIELDS = {
    "full_name": {"enabled": True, "required": True, "label": "Full name", "placeholder": "Your name"},
    "email": {"enabled": True, "required": False, "label": "Email", "placeholder": "you@example.com"},
    "phone": {"enabled": True, "required": True, "label": "Phone number", "placeholder": "98765 43210", "default_country": "IN"},
    "requirement": {"enabled": True, "required": False, "label": "Your requirement", "placeholder": "Tell us what you're looking for"},
}
DEFAULT_LEAD_DEFAULTS = {"source_label": "Landing page", "status": "new", "tags": [], "assign_to": "", "trigger_ai_call": True, "dedupe_days": 30}
DEFAULT_APPEARANCE = {"title": "Get in touch", "subtitle": "Share your details and our team will reach out shortly.",
                      "button_label": "Submit", "accent_color": "#4f46e5", "theme": "light", "rounded": True}
DEFAULT_AFTER_SUBMIT = {"mode": "message", "message": "Thank you! We've received your details and will contact you shortly.", "redirect_url": ""}
REQUIREMENT_FIELD = {"key": "requirement", "label": "Requirement / Query", "type": "long_text", "required": False, "system": False, "active": True, "options": []}


def new_form_key():
    return "lf_" + secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:24]


def form_out(doc):
    out = doc_out(doc)
    out.pop("rr_index", None)
    return out


async def ensure_requirement_field(db, ws_id):
    settings = await ensure_crm_settings(db, ws_id)
    if any(f.get("key") == "requirement" for f in settings.get("fields", [])):
        return settings
    field = {**REQUIREMENT_FIELD, "created_at": now_iso(), "updated_at": now_iso()}
    await db.crm_settings.update_one({"workspace_id": ws_id}, {"$push": {"fields": field}, "$set": {"updated_at": now_iso()}})
    settings["fields"] = [*settings.get("fields", []), field]
    return settings


# ---------------------------------------------------------------- validation of owner settings
def clean_origins(values):
    if not isinstance(values, list):
        raise HTTPException(422, "Allowed domains must be a list")
    clean = []
    for value in values[:20]:
        value = str(value or "").strip().rstrip("/")
        if not value:
            continue
        if "://" not in value:
            value = "https://" + value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(422, f"Enter a valid domain, for example example.com (got {value})")
        host = parsed.netloc.lower()
        if host not in clean:
            clean.append(host)
    return clean


def clean_fields(values, current):
    merged = deepcopy(current or DEFAULT_FORM_FIELDS)
    if not isinstance(values, dict):
        raise HTTPException(422, "fields must be an object")
    for key, cfg in values.items():
        if key not in FIELD_KEYS or not isinstance(cfg, dict):
            continue
        target = merged.setdefault(key, deepcopy(DEFAULT_FORM_FIELDS[key]))
        for attr in ("enabled", "required"):
            if attr in cfg:
                target[attr] = bool(cfg[attr])
        for attr in ("label", "placeholder"):
            if attr in cfg:
                target[attr] = str(cfg[attr] or "").strip()[:120] or DEFAULT_FORM_FIELDS[key][attr]
        if key == "phone" and "default_country" in cfg:
            iso = str(cfg["default_country"] or "").upper()
            if iso not in BY_ISO:
                raise HTTPException(422, "Choose a supported default country")
            target["default_country"] = iso
    # Phone is the CRM identity and is required for AI qualification calls.
    merged["phone"]["enabled"] = True
    merged["phone"]["required"] = True
    for key in FIELD_KEYS:
        if not merged[key]["enabled"]:
            merged[key]["required"] = False
    return merged


def clean_defaults(values, current, settings):
    merged = {**DEFAULT_LEAD_DEFAULTS, **(current or {})}
    if not isinstance(values, dict):
        raise HTTPException(422, "defaults must be an object")
    if "source_label" in values:
        merged["source_label"] = str(values["source_label"] or "").strip()[:80] or "Landing page"
    if "status" in values:
        states = {s["key"] for s in settings.get("states", [])}
        if values["status"] not in states:
            raise HTTPException(422, "Choose a valid pipeline stage")
        merged["status"] = values["status"]
    if "tags" in values:
        from crm import normalize_lead_tags
        merged["tags"] = normalize_lead_tags(values["tags"] or [])
    if "assign_to" in values:
        value = str(values["assign_to"] or "")
        if value not in {"", "round_robin"} and not ObjectId.is_valid(value):
            raise HTTPException(422, "Choose a valid salesperson")
        merged["assign_to"] = value
    if "trigger_ai_call" in values:
        merged["trigger_ai_call"] = bool(values["trigger_ai_call"])
    if "dedupe_days" in values:
        try:
            merged["dedupe_days"] = max(0, min(int(values["dedupe_days"]), 365))
        except (TypeError, ValueError):
            raise HTTPException(422, "Duplicate window must be a number of days")
    return merged


def clean_appearance(values, current):
    merged = {**DEFAULT_APPEARANCE, **(current or {})}
    if not isinstance(values, dict):
        raise HTTPException(422, "appearance must be an object")
    for key, limit in (("title", 120), ("subtitle", 300), ("button_label", 40)):
        if key in values:
            merged[key] = str(values[key] or "").strip()[:limit]
    if "accent_color" in values:
        color = str(values["accent_color"] or "")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise HTTPException(422, "Accent colour must be a hex value like #4f46e5")
        merged["accent_color"] = color
    if "theme" in values:
        merged["theme"] = "dark" if values["theme"] == "dark" else "light"
    if "rounded" in values:
        merged["rounded"] = bool(values["rounded"])
    return merged


def clean_after_submit(values, current):
    merged = {**DEFAULT_AFTER_SUBMIT, **(current or {})}
    if not isinstance(values, dict):
        raise HTTPException(422, "after_submit must be an object")
    if "mode" in values:
        merged["mode"] = "redirect" if values["mode"] == "redirect" else "message"
    if "message" in values:
        merged["message"] = str(values["message"] or "").strip()[:500] or DEFAULT_AFTER_SUBMIT["message"]
    if "redirect_url" in values:
        url = str(values["redirect_url"] or "").strip()
        if url and urlparse(url).scheme not in {"http", "https"}:
            raise HTTPException(422, "Redirect URL must start with https://")
        merged["redirect_url"] = url[:500]
    if merged["mode"] == "redirect" and not merged["redirect_url"]:
        raise HTTPException(422, "Add the page to redirect to after submit")
    return merged


# ---------------------------------------------------------------- owner API
@router.get("")
async def list_forms(ws_id: str, request: Request):
    db = db_from(request)
    docs = await db.lead_forms.find({"workspace_id": ws_id}).sort("created_at", -1).to_list(100)
    return {"items": [form_out(d) for d in docs], "countries": [BY_ISO[iso] for iso, _, _ in COUNTRIES]}


@router.post("")
async def create_form(ws_id: str, request: Request, body: dict = Body(default={})):
    db = db_from(request)
    settings = await ensure_requirement_field(db, ws_id)
    name = str((body or {}).get("name") or "").strip()[:120] or "Website enquiry form"
    fields = deepcopy(DEFAULT_FORM_FIELDS)
    if (body or {}).get("default_country") in BY_ISO:
        fields["phone"]["default_country"] = body["default_country"]
    doc = {
        "workspace_id": ws_id, "name": name, "form_key": new_form_key(), "status": "active",
        "allowed_origins": [], "fields": fields,
        "defaults": clean_defaults({}, None, settings), "appearance": deepcopy(DEFAULT_APPEARANCE),
        "after_submit": deepcopy(DEFAULT_AFTER_SUBMIT),
        "stats": {"submissions": 0, "leads": 0, "duplicates": 0, "last_submission_at": None},
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    res = await db.lead_forms.insert_one(doc)
    doc["_id"] = res.inserted_id
    return form_out(doc)


async def owned_form(db, ws_id, form_id):
    if not ObjectId.is_valid(form_id):
        raise HTTPException(404, "Form not found")
    doc = await db.lead_forms.find_one({"_id": ObjectId(form_id), "workspace_id": ws_id})
    if not doc:
        raise HTTPException(404, "Form not found")
    return doc


@router.get("/{form_id}")
async def get_form(ws_id: str, form_id: str, request: Request):
    return form_out(await owned_form(db_from(request), ws_id, form_id))


@router.patch("/{form_id}")
async def update_form(ws_id: str, form_id: str, request: Request, body: dict = Body(...)):
    db = db_from(request)
    doc = await owned_form(db, ws_id, form_id)
    settings = await ensure_crm_settings(db, ws_id)
    updates = {}
    if "name" in body:
        updates["name"] = str(body["name"] or "").strip()[:120] or doc["name"]
    if "status" in body:
        if body["status"] not in {"active", "paused"}:
            raise HTTPException(422, "Status must be active or paused")
        updates["status"] = body["status"]
    if "allowed_origins" in body:
        updates["allowed_origins"] = clean_origins(body["allowed_origins"])
    if "fields" in body:
        updates["fields"] = clean_fields(body["fields"], doc.get("fields"))
    if "defaults" in body:
        updates["defaults"] = clean_defaults(body["defaults"], doc.get("defaults"), settings)
    if "appearance" in body:
        updates["appearance"] = clean_appearance(body["appearance"], doc.get("appearance"))
    if "after_submit" in body:
        updates["after_submit"] = clean_after_submit(body["after_submit"], doc.get("after_submit"))
    if updates:
        updates["updated_at"] = now_iso()
        await db.lead_forms.update_one({"_id": doc["_id"]}, {"$set": updates})
    return form_out(await db.lead_forms.find_one({"_id": doc["_id"]}))


@router.delete("/{form_id}")
async def delete_form(ws_id: str, form_id: str, request: Request):
    db = db_from(request)
    doc = await owned_form(db, ws_id, form_id)
    await db.lead_forms.delete_one({"_id": doc["_id"]})
    return {"ok": True}


@router.post("/{form_id}/rotate-key")
async def rotate_key(ws_id: str, form_id: str, request: Request):
    db = db_from(request)
    doc = await owned_form(db, ws_id, form_id)
    await db.lead_forms.update_one({"_id": doc["_id"]}, {"$set": {"form_key": new_form_key(), "updated_at": now_iso()}})
    return form_out(await db.lead_forms.find_one({"_id": doc["_id"]}))


@router.post("/{form_id}/test")
async def send_test(ws_id: str, form_id: str, request: Request, body: dict = Body(default={})):
    db = db_from(request)
    doc = await owned_form(db, ws_id, form_id)
    payload = {
        "full_name": (body or {}).get("full_name") or "Test Lead (Arevei)",
        "email": (body or {}).get("email") or "test.lead@example.com",
        "phone": (body or {}).get("phone") or "9876543210",
        "country_code": (body or {}).get("country_code") or doc["fields"]["phone"].get("default_country", "IN"),
        "requirement": (body or {}).get("requirement") or "This is a test submission from the Landing Page Forms setup screen.",
        "utm_source": "arevei", "utm_medium": "test", "utm_campaign": "form_setup",
        "page_url": "https://app.arevei.com/test", "submission_id": secrets.token_hex(8),
    }
    return await process_submission(db, doc, payload, request, test=True)


@router.get("/{form_id}/submissions")
async def submissions(ws_id: str, form_id: str, request: Request):
    db = db_from(request)
    doc = await owned_form(db, ws_id, form_id)
    rows = await db.lead_form_submissions.find({"form_id": str(doc["_id"])}, {"expires_at": 0}).sort("created_at", -1).to_list(50)
    return {"items": [doc_out(r) for r in rows]}


# ---------------------------------------------------------------- submission pipeline
def client_ip(request):
    forwarded = request.headers.get("x-forwarded-for", "")
    return (forwarded.split(",")[0].strip() if forwarded else "") or (request.client.host if request.client else "unknown")


def request_origin_host(request):
    for header in ("origin", "referer"):
        value = request.headers.get(header)
        if value:
            host = urlparse(value).netloc.lower()
            if host:
                return host
    return ""


def assert_origin_allowed(form, request):
    allowed = form.get("allowed_origins") or []
    host = request_origin_host(request)
    if not allowed or not host:
        # No allowlist, or a server-to-server request (Zapier, Make, backend code).
        return
    public_host = urlparse(backend_base(request)).netloc.lower()
    if host == public_host:
        # The hosted/share page submits to its own public API origin.
        return
    if any(host == domain or host.endswith("." + domain) for domain in allowed):
        return
    raise HTTPException(403, "This website is not allowed to submit this form")


async def assert_rate(db, form, request):
    minute = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    form_id = str(form["_id"])
    keys = [(f"ip:{form_id}:{client_ip(request)}:{minute}", RATE_PER_IP_PER_MINUTE), (f"form:{form_id}:{minute}", RATE_PER_FORM_PER_MINUTE)]
    for key, limit in keys:
        row = await db.lead_form_rate.find_one_and_update(
            {"_id": key}, {"$inc": {"count": 1}, "$setOnInsert": {"expires_at": expires}}, upsert=True, return_document=True)
        if (row or {}).get("count", 0) > limit:
            raise HTTPException(429, "Too many submissions. Please wait a minute and try again.")


def to_e164(phone, country):
    raw = str(phone or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if raw.startswith("+") or raw.startswith("00"):
        number = "+" + (digits[2:] if raw.startswith("00") else digits)
    else:
        code = dial_code(country).lstrip("+")
        local = digits.lstrip("0")
        number = "+" + (local if local.startswith(code) and len(local) > 10 else code + local)
    return number if 8 <= len(number) - 1 <= 15 else ""


def text(value, limit):
    if isinstance(value, list):
        value = value[0] if value else ""
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def validate_payload(form, payload):
    fields = form.get("fields") or DEFAULT_FORM_FIELDS
    errors = {}
    name = text(payload.get("full_name") or payload.get("name"), 120)
    email = text(payload.get("email"), 200).lower()
    requirement = str(payload.get("requirement") or payload.get("message") or payload.get("query") or "").strip()[:2000]
    country = text(payload.get("country_code") or payload.get("country"), 8) or fields["phone"].get("default_country", "IN")
    phone = to_e164(payload.get("phone"), country)
    if fields["full_name"]["enabled"] and fields["full_name"]["required"] and not name:
        errors["full_name"] = "Please enter your name"
    if fields["email"]["enabled"]:
        if fields["email"]["required"] and not email:
            errors["email"] = "Please enter your email"
        elif email and not EMAIL_RE.match(email):
            errors["email"] = "Please enter a valid email"
    if not phone:
        errors["phone"] = "Please enter a valid phone number with country code"
    if fields["requirement"]["enabled"] and fields["requirement"]["required"] and not requirement:
        errors["requirement"] = "Please tell us your requirement"
    if errors:
        raise HTTPException(422, {"message": "Please check the highlighted fields.", "errors": errors})
    code = dial_code(country)
    utm = {key: text(payload.get(key), 200) for key in (*UTM_KEYS, *CLICK_KEYS) if text(payload.get(key), 200)}
    first_touch = payload.get("first_touch")
    if isinstance(first_touch, str):
        try:
            first_touch = json.loads(first_touch)
        except ValueError:
            first_touch = None
    if isinstance(first_touch, dict):
        utm["first_touch"] = {k: text(first_touch.get(k), 200) for k in (*UTM_KEYS, *CLICK_KEYS, "landing_page", "captured_at") if first_touch.get(k)}
    page_url = text(payload.get("page_url"), 500)
    referrer = text(payload.get("referrer"), 500)
    if page_url: utm["page_url"] = page_url
    if referrer: utm["referrer"] = referrer
    utm["captured_at"] = now_iso()
    return {"full_name": name, "email": email, "phone": phone, "country_code": code if phone.startswith(code) else "",
            "requirement": requirement, "utm": utm, "page_url": page_url}


async def pick_assignee(db, form):
    target = (form.get("defaults") or {}).get("assign_to") or ""
    ws_id = form["workspace_id"]
    if not target:
        return None
    if target != "round_robin":
        return target
    people = await db.crm_sales_people.find({"workspace_id": ws_id, "active": True, "role": "sales_agent"}, {"_id": 1}).sort("name", 1).to_list(200)
    if not people:
        return None
    row = await db.lead_forms.find_one_and_update({"_id": form["_id"]}, {"$inc": {"rr_index": 1}}, return_document=True)
    return str(people[((row or {}).get("rr_index", 1) - 1) % len(people)]["_id"])


async def find_duplicate(db, form, clean):
    days = (form.get("defaults") or {}).get("dedupe_days", 30)
    if not days:
        return None
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    matches = [{"phone": clean["phone"]}, {"field_values.phone": clean["phone"]}]
    if clean["email"]:
        matches += [{"email": clean["email"]}, {"field_values.email": clean["email"]}]
    return await db.crm_leads.find_one({"workspace_id": form["workspace_id"], "deleted_at": None, "is_test_lead": {"$ne": True},
                                        "created_at": {"$gte": cutoff}, "$or": matches})


async def notify_new_lead(db, form, lead_id, name):
    ws_id = form["workspace_id"]
    await db.notifications.insert_one({"workspace_id": ws_id, "kind": "success", "title": f"New lead from {form['name']}",
                                       "body": f"{name or 'A visitor'} submitted your landing page form.", "read": False, "created_at": now_iso()})
    try:
        from push_notifications import configured, send_push
        if not configured():
            return
        payload = {"title": f"New lead · {form['name']}", "body": f"{name or 'A visitor'} just enquired", "tag": f"lead-form-{lead_id}",
                   "url": f"/app/w/{ws_id}/crm?lead={lead_id}"}
        subs = await db.push_subscriptions.find({"workspace_ids": ws_id, "active": True}).to_list(20)
        await asyncio.wait_for(asyncio.gather(*(send_push(s["subscription"], payload) for s in subs), return_exceptions=True), timeout=8)
    except Exception:
        logger.warning("Lead form push notification failed", exc_info=True)


async def log_submission(db, form, result, clean=None, error=""):
    await db.lead_form_submissions.insert_one({
        "form_id": str(form["_id"]), "workspace_id": form["workspace_id"], "result": result, "error": error[:300],
        "lead_id": (clean or {}).get("lead_id"), "name": (clean or {}).get("full_name", ""), "phone": (clean or {}).get("phone", ""),
        "email": (clean or {}).get("email", ""),
        "utm": {k: v for k, v in ((clean or {}).get("utm") or {}).items() if k in UTM_KEYS},
        "created_at": now_iso(), "expires_at": datetime.now(timezone.utc) + timedelta(days=SUBMISSION_LOG_DAYS),
    })


async def process_submission(db, form, payload, request, test=False):
    ws_id = form["workspace_id"]
    try:
        clean = validate_payload(form, payload)
    except HTTPException as exc:
        await log_submission(db, form, "rejected", {"full_name": text(payload.get("full_name"), 120)}, error=json.dumps(exc.detail)[:300])
        raise
    defaults = {**DEFAULT_LEAD_DEFAULTS, **(form.get("defaults") or {})}
    now = now_iso()
    submission_id = text(payload.get("submission_id"), 80)
    idem = submission_id or hashlib.sha256(f"{clean['phone']}|{clean['email']}|{now[:16]}".encode()).hexdigest()[:24]
    row_key = f"form:{form['_id']}:{idem}"
    existing = await db.crm_leads.find_one({"workspace_id": ws_id, "sheet_row_key": row_key}, {"_id": 1})
    if existing:
        return {"ok": True, "lead_id": str(existing["_id"]), "duplicate": True}

    duplicate = None if test else await find_duplicate(db, form, clean)
    if duplicate:
        detail = clean["requirement"] or "No requirement given"
        set_fields = {"updated_at": now, "utm_last_touch": clean["utm"]}
        if clean["requirement"] and not (duplicate.get("field_values") or {}).get("requirement"):
            set_fields["field_values.requirement"] = clean["requirement"]
        await db.crm_leads.update_one({"_id": duplicate["_id"]}, {
            "$set": set_fields,
            "$addToSet": {"tags": "Repeat Enquiry"},
            "$push": {"timeline": {"type": "form_resubmitted", "label": f"Submitted again via “{form['name']}”", "detail": detail[:500], "created_at": now}},
        })
        clean["lead_id"] = str(duplicate["_id"])
        await db.lead_forms.update_one({"_id": form["_id"]}, {"$inc": {"stats.submissions": 1, "stats.duplicates": 1}, "$set": {"stats.last_submission_at": now}})
        await log_submission(db, form, "duplicate", clean)
        await db.notifications.insert_one({"workspace_id": ws_id, "kind": "info", "title": f"Repeat enquiry from {clean['full_name'] or clean['phone']}",
                                           "body": f"Submitted “{form['name']}” again. The existing lead was updated.", "read": False, "created_at": now})
        return {"ok": True, "lead_id": clean["lead_id"], "duplicate": True}

    settings = await ensure_requirement_field(db, ws_id)
    # Public visitors can't fill workspace-only required custom fields; relax them for form leads.
    relaxed = {**settings, "fields": [{**f, "required": False} for f in settings.get("fields", [])]}
    status = defaults["status"] if defaults["status"] in {s["key"] for s in settings.get("states", [])} else "new"
    trigger = bool(defaults["trigger_ai_call"]) and not test
    values = {"phone": clean["phone"], "full_name": clean["full_name"], "email": clean["email"],
              "requirement": clean["requirement"], "source": defaults["source_label"]}
    lead = build_manual_lead(ws_id, {"field_values": {k: v for k, v in values.items() if v}, "trigger_ai_call": trigger,
                                     "status": status, "tags": defaults.get("tags") or []}, relaxed)
    lead.update({
        "workflow_kind": "landing_form", "source": "landing_form", "sheet_row_key": row_key,
        "form_id": str(form["_id"]), "form_name": form["name"], "utm": clean["utm"],
        "phone_country_code": clean["country_code"], "landing_page_url": clean["page_url"],
        "timeline": [{"type": "created", "label": f"Lead captured from landing page form “{form['name']}”", "created_at": now}],
    })
    if not trigger:
        lead["timeline"].append({"type": "ai_call_skipped", "label": "Automatic AI call skipped for this form" if not test else "Test lead: AI call skipped", "created_at": now})
    if test:
        lead["is_test_lead"] = True
    assignee = await pick_assignee(db, form)
    if assignee:
        try:
            from sales_team import attribution
            lead["sales_assignment"] = await attribution(db, ws_id, {"sales_agent_id": assignee, "acquisition_channel": "marketing"})
            lead["field_values"]["assigned_salesperson"] = lead["sales_assignment"].get("sales_agent_name", "")
        except HTTPException:
            logger.warning("Lead form assignee unavailable form=%s", form["_id"])
    try:
        await db.crm_leads.insert_one(lead)
    except DuplicateKeyError:
        existing = await db.crm_leads.find_one({"workspace_id": ws_id, "sheet_row_key": row_key}, {"_id": 1})
        return {"ok": True, "lead_id": str(existing["_id"]) if existing else None, "duplicate": True}
    lead_id = str(lead["_id"])
    clean["lead_id"] = lead_id
    call_status = None
    if trigger:
        try:
            from plivo_calls import schedule_first_qualification_call
            call_status = (await schedule_first_qualification_call(db, ws_id, lead_id) or {}).get("status")
        except Exception:
            logger.warning("Lead form qualification scheduling failed lead=%s", lead_id, exc_info=True)
            call_status = "failed"
    await db.lead_forms.update_one({"_id": form["_id"]}, {"$inc": {"stats.submissions": 1, "stats.leads": 1}, "$set": {"stats.last_submission_at": now}})
    await log_submission(db, form, "test" if test else "created", clean)
    if not test:
        await notify_new_lead(db, form, lead_id, clean["full_name"])
    return {"ok": True, "lead_id": lead_id, "duplicate": False, "ai_call": call_status if trigger else "skipped", "test": test}


# ---------------------------------------------------------------- public endpoints
async def public_form(db, key):
    if not key or not key.startswith("lf_"):
        raise HTTPException(404, "Form not found")
    form = await db.lead_forms.find_one({"form_key": key})
    if not form:
        raise HTTPException(404, "Form not found")
    return form


def public_config(form):
    return {"name": form["name"], "status": form["status"], "fields": form["fields"], "appearance": form.get("appearance") or DEFAULT_APPEARANCE,
            "after_submit": form.get("after_submit") or DEFAULT_AFTER_SUBMIT,
            "countries": [BY_ISO[iso] for iso, _, _ in COUNTRIES]}


def frame_ancestors(form):
    domains = form.get("allowed_origins") or []
    if not domains:
        return "*"
    sources = []
    for domain in domains:
        scheme = "http" if domain.startswith(("localhost", "127.0.0.1")) else "https"
        sources.append(f"{scheme}://{domain}")
        if ":" not in domain and not domain.startswith(("localhost", "127.0.0.1")):
            sources.append(f"https://*.{domain}")
    return " ".join(dict.fromkeys(sources))


def hosted_form_page(form, request):
    base = backend_base(request)
    script_url = f"{base}/api/embed/form.js"
    script_origin = f"{urlparse(script_url).scheme}://{urlparse(script_url).netloc}"
    title = escape((form.get("appearance") or {}).get("title") or form.get("name") or "Contact form")
    key = escape(form["form_key"], quote=True)
    headers = {
        "Cache-Control": "no-store",
        "Content-Security-Policy": (
            "default-src 'none'; "
            f"script-src 'self' {script_origin}; connect-src 'self' {script_origin}; "
            "style-src 'unsafe-inline'; img-src data:; base-uri 'none'; "
            f"form-action 'self' {script_origin}; frame-ancestors {frame_ancestors(form)}"
        ),
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "X-Content-Type-Options": "nosniff",
    }
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>html,body{{margin:0;min-height:100%;background:transparent}}body{{display:grid;place-items:start center;padding:16px;box-sizing:border-box}}main{{width:min(100%,520px)}}</style></head>
<body><main><div data-arevei-form="{key}"></div></main><script src="{escape(script_url, quote=True)}" async></script></body></html>""", headers=headers)


@public_router.get("/public/forms/{key}")
async def get_public_form(key: str, request: Request):
    db = db_from(request)
    form = await public_form(db, key)
    assert_origin_allowed(form, request)
    return public_config(form)


@public_router.get("/public/forms/{key}/view")
async def view_public_form(key: str, request: Request):
    form = await public_form(db_from(request), key)
    return hosted_form_page(form, request)


async def read_payload(request):
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(413, "Submission is too large")
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype or (body[:1] in (b"{",) and "form" not in ctype):
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            raise HTTPException(400, "Invalid JSON")
        if not isinstance(data, dict):
            raise HTTPException(400, "Send a JSON object")
        return data, False
    if "multipart/form-data" in ctype:
        form = await request.form()
        return {k: form.get(k) for k in form.keys()}, True
    parsed = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
    return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}, True


def thank_you_page(form, message, error=False):
    accent = escape((form.get("appearance") or {}).get("accent_color", "#4f46e5"))
    title = "Something went wrong" if error else "Thank you!"
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f8fafc;font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#0f172a}}
.card{{max-width:420px;margin:24px;padding:36px;border-radius:18px;background:#fff;box-shadow:0 10px 40px rgba(15,23,42,.08);text-align:center}}
.dot{{width:56px;height:56px;border-radius:50%;margin:0 auto 18px;display:grid;place-items:center;background:{accent}1a;color:{accent};font-size:28px}}
h1{{font-size:22px;margin:0 0 8px}}p{{color:#475569;line-height:1.6;margin:0 0 20px}}a{{color:{accent};font-weight:600}}</style></head>
<body><div class="card"><div class="dot">{'!' if error else '✓'}</div><h1>{title}</h1><p>{escape(message)}</p><a href="javascript:history.back()">← Back</a></div></body></html>""",
                        status_code=422 if error else 200)


@public_router.post("/public/forms/{key}/submit")
async def submit_public_form(key: str, request: Request):
    db = db_from(request)
    form = await public_form(db, key)
    payload, html_form = await read_payload(request)
    wants_html = html_form and "application/json" not in request.headers.get("accept", "")
    after = form.get("after_submit") or DEFAULT_AFTER_SUBMIT
    try:
        if form.get("status") != "active":
            raise HTTPException(409, "This form is not accepting submissions right now")
        assert_origin_allowed(form, request)
        await assert_rate(db, form, request)
        if text(payload.get("_hp") or payload.get("_gotcha"), 200):
            # Honeypot filled: pretend success without creating a lead.
            await log_submission(db, form, "spam")
            result = {"ok": True}
        else:
            result = await process_submission(db, form, payload, request)
    except HTTPException as exc:
        if wants_html:
            detail = exc.detail if isinstance(exc.detail, str) else (exc.detail or {}).get("message", "Please check your details.")
            if isinstance(exc.detail, dict) and exc.detail.get("errors"):
                detail = " ".join(exc.detail["errors"].values())
            return thank_you_page(form, detail, error=True)
        raise
    if wants_html:
        if after.get("mode") == "redirect" and after.get("redirect_url"):
            return RedirectResponse(after["redirect_url"], status_code=303)
        return thank_you_page(form, after.get("message") or DEFAULT_AFTER_SUBMIT["message"])
    return {"ok": True, "message": after.get("message"), "redirect_url": after.get("redirect_url") if after.get("mode") == "redirect" else "",
            "duplicate": result.get("duplicate", False)}


def backend_base(request):
    import os
    configured = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if configured:
        return configured
    url = getattr(request, "url", None)
    proto = request.headers.get("x-forwarded-proto") or getattr(url, "scheme", "https")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or getattr(url, "netloc", "")
    return f"{proto}://{host}"


EMBED_JS = r"""
(function(){
  var API = "__API__";
  var STORE = "arevei_utm_v1";
  var KEYS = ["utm_source","utm_medium","utm_campaign","utm_term","utm_content","gclid","fbclid"];
  function params(){ var out={}; try{ var q=new URLSearchParams(location.search); KEYS.forEach(function(k){ var v=q.get(k); if(v) out[k]=v; }); }catch(e){} return out; }
  function attribution(){
    var last = params(), first = null;
    try { first = JSON.parse(localStorage.getItem(STORE) || "null"); } catch(e) {}
    if (first && first.expires < Date.now()) first = null;
    if (!first && Object.keys(last).length) {
      first = Object.assign({landing_page: location.href, captured_at: new Date().toISOString(), expires: Date.now() + 30*864e5}, last);
      try { localStorage.setItem(STORE, JSON.stringify(first)); } catch(e) {}
    }
    var current = Object.keys(last).length ? last : (first || {});
    var out = {}; KEYS.forEach(function(k){ if (current[k]) out[k] = current[k]; });
    var q = null; try { q = new URLSearchParams(location.search); } catch(e) {}
    out.page_url = (q && q.get("arevei_page_url")) || location.href;
    out.referrer = (q && q.get("arevei_referrer")) || document.referrer || "";
    if (first) out.first_touch = first;
    return out;
  }
  window.AreveiAttribution = attribution;
  function uid(){ return (Date.now().toString(36) + Math.random().toString(36).slice(2, 10)); }
  function el(tag, attrs, kids){ var n=document.createElement(tag); for (var k in (attrs||{})) { if (k==="text") n.textContent=attrs[k]; else n.setAttribute(k, attrs[k]); } (kids||[]).forEach(function(c){ if(c) n.appendChild(c); }); return n; }
  function css(id, accent, dark, rounded){
    var r = rounded ? "12px" : "4px", bg = dark ? "#0f172a" : "#ffffff", fg = dark ? "#f8fafc" : "#0f172a", mute = dark ? "#94a3b8" : "#64748b", line = dark ? "#334155" : "#e2e8f0", field = dark ? "#1e293b" : "#ffffff";
    return "#"+id+"{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;max-width:480px;background:"+bg+";color:"+fg+";border:1px solid "+line+";border-radius:"+(rounded?"18px":"6px")+";padding:28px;box-shadow:0 10px 30px rgba(15,23,42,.08);box-sizing:border-box}"+
      "#"+id+" *{box-sizing:border-box}#"+id+" h3{margin:0 0 6px;font-size:22px;line-height:1.25}#"+id+" .sub{margin:0 0 20px;color:"+mute+";font-size:14px;line-height:1.5}"+
      "#"+id+" label{display:block;font-size:13px;font-weight:600;margin:0 0 6px}#"+id+" .f{margin-bottom:14px}"+
      "#"+id+" input,#"+id+" textarea,#"+id+" select{width:100%;font:inherit;font-size:15px;color:"+fg+";background:"+field+";border:1px solid "+line+";border-radius:"+r+";padding:11px 12px;outline:none;transition:border-color .15s,box-shadow .15s}"+
      "#"+id+" input:focus,#"+id+" textarea:focus,#"+id+" select:focus{border-color:"+accent+";box-shadow:0 0 0 3px "+accent+"33}"+
      "#"+id+" textarea{min-height:92px;resize:vertical}#"+id+" .ph{display:flex;gap:8px}#"+id+" .ph select{width:116px;flex:none}"+
      "#"+id+" .err{color:#dc2626;font-size:12px;margin-top:5px;display:none}#"+id+" .f.bad .err{display:block}#"+id+" .f.bad input,#"+id+" .f.bad textarea{border-color:#dc2626}"+
      "#"+id+" button{width:100%;border:0;border-radius:"+r+";padding:13px 16px;font:inherit;font-weight:700;font-size:15px;color:#fff;background:"+accent+";cursor:pointer;transition:filter .15s,transform .05s}"+
      "#"+id+" button:hover{filter:brightness(1.07)}#"+id+" button:active{transform:translateY(1px)}#"+id+" button[disabled]{opacity:.7;cursor:wait}"+
      "#"+id+" .ok{text-align:center;padding:18px 4px}#"+id+" .ok .i{width:56px;height:56px;border-radius:50%;margin:0 auto 14px;display:grid;place-items:center;background:"+accent+"1f;color:"+accent+";font-size:28px}"+
      "#"+id+" .gen{color:#dc2626;font-size:13px;margin:4px 0 12px;display:none}#"+id+" .hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}"+
      "#"+id+" .pw{margin-top:12px;text-align:center;font-size:11px;color:"+mute+"}";
  }
  function render(mount, key, cfg){
    var id = "arevei-form-" + uid(), a = cfg.appearance || {}, F = cfg.fields || {}, accent = a.accent_color || "#4f46e5";
    var style = el("style"); style.textContent = css(id, accent, a.theme === "dark", a.rounded !== false);
    var form = el("form", {id: id, novalidate: "novalidate"});
    if (cfg.status !== "active") { form.appendChild(el("p", {"class": "sub", text: "This form is not accepting submissions right now."})); mount.appendChild(style); mount.appendChild(form); return; }
    if (a.title) form.appendChild(el("h3", {text: a.title}));
    if (a.subtitle) form.appendChild(el("p", {"class": "sub", text: a.subtitle}));
    function field(name, control){
      var c = F[name]; if (!c || !c.enabled) return null;
      var wrap = el("div", {"class": "f", "data-f": name}, [el("label", {"for": id+"-"+name, text: c.label + (c.required ? " *" : "")}), control, el("div", {"class": "err"})]);
      return wrap;
    }
    var nameIn = el("input", {id: id+"-full_name", name: "full_name", autocomplete: "name", placeholder: (F.full_name||{}).placeholder || ""});
    var emailIn = el("input", {id: id+"-email", name: "email", type: "email", autocomplete: "email", placeholder: (F.email||{}).placeholder || ""});
    var cc = el("select", {name: "country_code", "aria-label": "Country code"});
    (cfg.countries || []).forEach(function(c){ var o = el("option", {value: c.iso, text: c.iso + " " + c.dial}); if (c.iso === (F.phone||{}).default_country) o.selected = true; cc.appendChild(o); });
    var phoneIn = el("input", {id: id+"-phone", name: "phone", type: "tel", autocomplete: "tel-national", inputmode: "tel", placeholder: (F.phone||{}).placeholder || ""});
    var reqIn = el("textarea", {id: id+"-requirement", name: "requirement", placeholder: (F.requirement||{}).placeholder || ""});
    [field("full_name", nameIn), field("email", emailIn), field("phone", el("div", {"class": "ph"}, [cc, phoneIn])), field("requirement", reqIn)].forEach(function(n){ if (n) form.appendChild(n); });
    var hp = el("div", {"class": "hp", "aria-hidden": "true"}, [el("input", {name: "_hp", tabindex: "-1", autocomplete: "off"})]);
    form.appendChild(hp);
    var gen = el("div", {"class": "gen", role: "alert"}); form.appendChild(gen);
    var btn = el("button", {type: "submit", text: a.button_label || "Submit"}); form.appendChild(btn);
    form.appendChild(el("div", {"class": "pw", text: "Secured by Arevei"}));
    var sid = uid();
    form.addEventListener("submit", function(e){
      e.preventDefault();
      Array.prototype.forEach.call(form.querySelectorAll(".f"), function(f){ f.classList.remove("bad"); });
      gen.style.display = "none";
      var body = Object.assign(attribution(), {full_name: nameIn.value, email: emailIn.value, phone: phoneIn.value, country_code: cc.value, requirement: reqIn.value, _hp: form.querySelector("[name=_hp]").value, submission_id: sid});
      btn.disabled = true; var label = btn.textContent; btn.textContent = "Sending…";
      fetch(API + "/public/forms/" + encodeURIComponent(key) + "/submit", {method: "POST", headers: {"Content-Type": "text/plain;charset=UTF-8", "Accept": "application/json"}, body: JSON.stringify(body)})
        .then(function(r){ return r.json().then(function(d){ return {ok: r.ok, d: d}; }); })
        .then(function(res){
          if (res.ok) {
            if (res.d.redirect_url) { location.href = res.d.redirect_url; return; }
            form.innerHTML = ""; form.appendChild(el("div", {"class": "ok"}, [el("div", {"class": "i", text: "✓"}), el("h3", {text: "Thank you!"}), el("p", {"class": "sub", text: res.d.message || "We'll be in touch shortly."})]));
            try { mount.dispatchEvent(new CustomEvent("arevei:submitted", {bubbles: true, detail: res.d})); } catch(e) {}
            return;
          }
          var det = res.d && res.d.detail, errs = det && det.errors;
          if (errs) { Object.keys(errs).forEach(function(k){ var f = form.querySelector('[data-f="'+k+'"]'); if (f) { f.classList.add("bad"); f.querySelector(".err").textContent = errs[k]; } }); }
          gen.textContent = (det && (det.message || (typeof det === "string" ? det : ""))) || "Something went wrong. Please try again."; gen.style.display = "block";
        })
        .catch(function(){ gen.textContent = "Network error. Please try again."; gen.style.display = "block"; })
        .then(function(){ btn.disabled = false; btn.textContent = label; });
    });
    mount.appendChild(style); mount.appendChild(form);
    function reportHeight(){ try { if (window.parent !== window) window.parent.postMessage({type:"arevei:resize", key:key, height:Math.ceil(document.documentElement.scrollHeight)}, "*"); } catch(e) {} }
    reportHeight();
    try { new ResizeObserver(reportHeight).observe(document.documentElement); } catch(e) { setTimeout(reportHeight, 250); }
  }
  function boot(){
    var nodes = document.querySelectorAll("[data-arevei-form]");
    Array.prototype.forEach.call(nodes, function(node){
      if (node.__arevei) return; node.__arevei = true;
      var key = node.getAttribute("data-arevei-form");
      var mount = node.tagName === "SCRIPT" ? (function(){ var d = document.createElement("div"); node.parentNode.insertBefore(d, node.nextSibling); return d; })() : node;
      fetch(API + "/public/forms/" + encodeURIComponent(key)).then(function(r){ if (!r.ok) throw r; return r.json(); })
        .then(function(cfg){ render(mount, key, cfg); })
        .catch(function(){ mount.innerHTML = '<p style="font:14px system-ui;color:#dc2626">This form could not be loaded.</p>'; });
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
  attribution();
})();
"""

CONNECT_JS = r"""
(function(){
  var API = "__API__";
  var STORE = "arevei_utm_v1";
  var KEYS = ["utm_source","utm_medium","utm_campaign","utm_term","utm_content","gclid","fbclid"];
  var script = document.currentScript;
  var key = script && script.getAttribute("data-form-key");
  var selector = (script && script.getAttribute("data-selector")) || "form[data-arevei]";
  var map = {}; try { map = JSON.parse((script && script.getAttribute("data-map")) || "{}"); } catch(e) {}
  var defaults = {full_name: ["full_name","name","your-name","fullname","first_name"], email: ["email","your-email","mail"], phone: ["phone","mobile","tel","phone_number","your-phone","whatsapp"], country_code: ["country_code","country","dial_code"], requirement: ["requirement","message","query","your-message","comments","notes"]};
  function params(){ var out={}; try{ var q=new URLSearchParams(location.search); KEYS.forEach(function(k){ var v=q.get(k); if(v) out[k]=v; }); }catch(e){} return out; }
  function attribution(){
    var last = params(), first = null;
    try { first = JSON.parse(localStorage.getItem(STORE) || "null"); } catch(e) {}
    if (first && first.expires < Date.now()) first = null;
    if (!first && Object.keys(last).length) { first = Object.assign({landing_page: location.href, captured_at: new Date().toISOString(), expires: Date.now()+30*864e5}, last); try { localStorage.setItem(STORE, JSON.stringify(first)); } catch(e) {} }
    var cur = Object.keys(last).length ? last : (first || {}), out = {};
    KEYS.forEach(function(k){ if (cur[k]) out[k] = cur[k]; });
    out.page_url = location.href; out.referrer = document.referrer || ""; if (first) out.first_touch = first;
    return out;
  }
  function value(form, names){ for (var i=0;i<names.length;i++){ var n = form.querySelector('[name="'+names[i]+'"]'); if (n && n.value) return n.value; } return ""; }
  function attach(form){
    if (form.__arevei) return; form.__arevei = true;
    var a = attribution();
    KEYS.forEach(function(k){ if (!a[k] || form.querySelector('[name="'+k+'"]')) return; var h = document.createElement("input"); h.type = "hidden"; h.name = k; h.value = a[k]; form.appendChild(h); });
    form.addEventListener("submit", function(){
      var body = attribution();
      Object.keys(defaults).forEach(function(f){ body[f] = value(form, map[f] ? [map[f]] : defaults[f]); });
      body.submission_id = Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
      var url = API + "/public/forms/" + encodeURIComponent(key) + "/submit", data = JSON.stringify(body);
      try { if (navigator.sendBeacon && navigator.sendBeacon(url, new Blob([data], {type: "text/plain"}))) return; } catch(e) {}
      try { fetch(url, {method: "POST", headers: {"Content-Type": "text/plain"}, body: data, keepalive: true}); } catch(e) {}
    }, true);
  }
  function boot(){ Array.prototype.forEach.call(document.querySelectorAll(selector), attach); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
  try { new MutationObserver(boot).observe(document.documentElement, {childList: true, subtree: true}); } catch(e) {}
})();
"""

FRAME_JS = r"""
(function(){
  var KEYS = ["utm_source","utm_medium","utm_campaign","utm_term","utm_content","gclid","fbclid"];
  var frames = [];
  function setup(frame){
    if (frame.__areveiFrame) return; frame.__areveiFrame = true;
    var source = frame.getAttribute("data-src") || frame.getAttribute("src"); if (!source) return;
    try {
      var url = new URL(source, location.href), query = new URLSearchParams(location.search);
      KEYS.forEach(function(key){ var value=query.get(key); if(value) url.searchParams.set(key,value); });
      url.searchParams.set("arevei_page_url", location.href);
      if (document.referrer) url.searchParams.set("arevei_referrer", document.referrer);
      frame.src = url.toString(); frame.__areveiOrigin = url.origin; frames.push(frame);
    } catch(e) { frame.src = source; }
  }
  function boot(){ Array.prototype.forEach.call(document.querySelectorAll("iframe[data-arevei-frame]"), setup); }
  window.addEventListener("message", function(event){
    var data=event.data||{}; if(data.type!=="arevei:resize") return;
    frames.forEach(function(frame){
      if(event.source!==frame.contentWindow || event.origin!==frame.__areveiOrigin) return;
      var height=Math.max(360,Math.min(1600,Number(data.height)||0)); if(height) frame.style.height=height+"px";
    });
  });
  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",boot); else boot();
})();
"""


def js_response(source, request):
    return Response(source.replace("__API__", backend_base(request) + "/api"), media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=300", "Access-Control-Allow-Origin": "*"})


@public_router.get("/embed/form.js")
async def embed_form_js(request: Request):
    return js_response(EMBED_JS, request)


@public_router.get("/embed/form-connect.js")
async def embed_connect_js(request: Request):
    return js_response(CONNECT_JS, request)


@public_router.get("/embed/form-frame.js")
async def embed_frame_js(request: Request):
    return js_response(FRAME_JS, request)
