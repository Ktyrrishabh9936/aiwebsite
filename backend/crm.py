import html
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse

from models import now_iso

router = APIRouter(prefix="/workspaces/{ws_id}/crm")

VALID_FIELD_TYPES = {
    "text",
    "long_text",
    "email",
    "phone",
    "number",
    "currency",
    "date",
    "datetime",
    "boolean",
    "select",
    "multi_select",
    "url",
    "json",
}
VALID_STAGE_STATUSES = {"pending", "partially_paid", "paid"}
VALID_PLAN_STATUSES = {"draft", "active", "completed", "cancelled"}
SYSTEM_FIELD_KEYS = {"phone"}
TRASH_RETENTION_DAYS = 30

DEFAULT_FIELDS = [
    {"key": "phone", "label": "Phone", "type": "phone", "required": True, "system": True, "active": True, "options": []},
    {"key": "full_name", "label": "Name", "type": "text", "required": False, "system": True, "active": True, "options": []},
    {"key": "email", "label": "Email", "type": "email", "required": False, "system": True, "active": True, "options": []},
    {"key": "address", "label": "Address", "type": "long_text", "required": False, "system": False, "active": True, "options": []},
    {"key": "source", "label": "Lead Source", "type": "text", "required": False, "system": True, "active": True, "options": []},
    {"key": "assigned_salesperson", "label": "Assigned Salesperson", "type": "text", "required": False, "system": False, "active": True, "options": []},
]
DEFAULT_STATES = [
    {"key": "new", "label": "New", "color": "blue", "order": 1},
    {"key": "contacted", "label": "Contacted", "color": "amber", "order": 2},
    {"key": "won", "label": "Won", "color": "emerald", "order": 3},
    {"key": "lost", "label": "Lost", "color": "red", "order": 4},
]
DEFAULT_PAYMENT_STAGES = []
DEFAULT_TEMPLATE = {
    "id": "receipt-default",
    "name": "Receipt",
    "type": "receipt",
    "button_label": "Download Receipt",
    "active": True,
    "html": (
        "<h1>Receipt</h1>"
        "<p><strong>Customer:</strong> {{full_name}}</p>"
        "<p><strong>Email:</strong> {{email}}</p>"
        "<p><strong>Phone:</strong> {{phone}}</p>"
        "<p><strong>Address:</strong> {{address}}</p>"
    ),
}
DEFAULT_ORGANIZATION = {
    "company_name": "Arevei Realty",
    "logo_url": "",
    "address": "Add your company address",
    "phone": "",
    "email": "",
    "website": "",
    "tax_number": "",
    "bank_details": "",
    "authorized_signatory": "Authorized Signatory",
    "receipt_prefix": "REC",
    "invoice_prefix": "INV",
    "document_accent_color": "#000000",
    "document_text_color": "#000000",
    "document_muted_color": "#000000",
    "document_table_header_color": "#000000",
}


def oid(v):
    return ObjectId(v)


def db_from(request):
    return request.app.state.db if hasattr(request.app.state, "db") else request.app.extra.get("db")


def doc_out(doc):
    if not doc:
        return None
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


def iso_after_days(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


async def purge_expired_trashed_leads(db, ws_id):
    await db.crm_leads.delete_many({
        "workspace_id": ws_id,
        "deleted_at": {"$ne": None},
        "delete_after": {"$lte": now_iso()},
    })


def keyify(value):
    key = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    key = re.sub(r"_+", "_", key)
    return key


def normalize_field(field, existing=None):
    field = field or {}
    existing = existing or {}
    key = keyify(field.get("key") or field.get("label") or existing.get("key"))
    if not key:
        raise HTTPException(status_code=400, detail="Field key or label required")
    field_type = field.get("type") or existing.get("type") or "text"
    if field_type not in VALID_FIELD_TYPES:
        raise HTTPException(status_code=400, detail="Invalid field type")
    system = bool(existing.get("system") or field.get("system") or key in SYSTEM_FIELD_KEYS)
    required = bool(field.get("required", existing.get("required", False)))
    active = bool(field.get("active", existing.get("active", True)))
    if key == "phone":
        required = True
        system = True
        active = True
        field_type = "phone"
    return {
        "key": key,
        "label": str(field.get("label") or existing.get("label") or key.replace("_", " ").title()).strip(),
        "type": field_type,
        "required": required,
        "system": system,
        "active": active,
        "options": field.get("options", existing.get("options", [])) if isinstance(field.get("options", existing.get("options", [])), list) else [],
        "updated_at": now_iso(),
        "created_at": existing.get("created_at") or now_iso(),
    }


def normalize_states(states):
    clean = []
    seen = set()
    for index, state in enumerate(states or []):
        key = keyify(state.get("key") or state.get("label"))
        if not key or key in seen:
            continue
        seen.add(key)
        clean.append({
            "key": key,
            "label": str(state.get("label") or key.replace("_", " ").title()).strip(),
            "color": str(state.get("color") or "blue").strip(),
            "order": int(state.get("order") or index + 1),
        })
    if not clean:
        clean = deepcopy(DEFAULT_STATES)
    if not any(s["key"] == "new" for s in clean):
        clean.insert(0, deepcopy(DEFAULT_STATES[0]))
    return sorted(clean, key=lambda s: s.get("order", 0))


def normalize_template(template, existing=None):
    template = template or {}
    existing = existing or {}
    name = str(template.get("name") or existing.get("name") or "CRM Template").strip()
    template_id = str(template.get("id") or existing.get("id") or ObjectId())
    return {
        "id": template_id,
        "name": name,
        "type": str(template.get("type") or existing.get("type") or "document").strip(),
        "button_label": str(template.get("button_label") or existing.get("button_label") or name).strip(),
        "active": bool(template.get("active", existing.get("active", True))),
        "html": str(template.get("html") or existing.get("html") or "").strip(),
        "updated_at": now_iso(),
        "created_at": existing.get("created_at") or now_iso(),
    }


def phone_first_fields(fields):
    current = {f.get("key"): f for f in fields or []}
    normalized = []
    seen = set()
    for default_field in DEFAULT_FIELDS:
        source = current.get(default_field["key"]) or default_field
        patch = {**source}
        if default_field["key"] == "email":
            patch["required"] = False
        item = normalize_field(patch, source)
        item["updated_at"] = source.get("updated_at", item["updated_at"])
        normalized.append(item)
        seen.add(default_field["key"])
    for field in fields or []:
        key = field.get("key")
        if key not in seen:
            item = normalize_field(field, field)
            item["updated_at"] = field.get("updated_at", item["updated_at"])
            normalized.append(item)
            seen.add(key)
    return normalized


async def ensure_crm_settings(db, ws_id):
    settings = await db.crm_settings.find_one({"workspace_id": ws_id})
    if settings:
        fields = phone_first_fields(settings.get("fields") or [])
        if fields != (settings.get("fields") or []):
            await db.crm_settings.update_one({"workspace_id": ws_id}, {"$set": {"fields": fields, "updated_at": now_iso()}})
            settings["fields"] = fields
        return settings
    settings = {
        "workspace_id": ws_id,
        "fields": deepcopy(DEFAULT_FIELDS),
        "states": deepcopy(DEFAULT_STATES),
        "templates": [deepcopy(DEFAULT_TEMPLATE)],
        "organization": deepcopy(DEFAULT_ORGANIZATION),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    res = await db.crm_settings.insert_one(settings)
    settings["_id"] = res.inserted_id
    return settings


def active_fields(settings):
    return [f for f in settings.get("fields", []) if f.get("active", True)]


def default_field_values(doc, settings):
    values = dict(doc.get("field_values") or {})
    for field in active_fields(settings):
        key = field["key"]
        if key not in values and doc.get(key) is not None:
            values[key] = doc.get(key)
    return values


def decorate_lead(doc, settings):
    out = doc_out(doc)
    if not out:
        return None
    values = default_field_values(doc, settings)
    out["field_values"] = values
    for key in ("email", "full_name", "phone", "address", "source", "assigned_salesperson"):
        out[key] = values.get(key, out.get(key))
    receipts = out.get("receipts") or []
    if out.get("conversion_type") == "payment_plan":
        out["payment_plan"] = recalculate_payment_plan(out.get("payment_plan") or {}, receipts)
    elif out.get("conversion_type") == "single_payment":
        out["payment_summary"] = single_payment_summary(out, receipts)
    return out


def validate_field_values(values, settings):
    values = values or {}
    if not isinstance(values, dict):
        raise HTTPException(status_code=400, detail="field_values must be an object")
    allowed = {f["key"]: f for f in active_fields(settings)}
    clean = {}
    for key, value in values.items():
        if key not in allowed:
            continue
        clean[key] = value
    for key, field in allowed.items():
        if field.get("required") and not str(clean.get(key, "")).strip():
            raise HTTPException(status_code=400, detail=f"{field['label']} is required")
    return clean


def lead_query(ws_id, include_trashed=False, only_trashed=False):
    q = {"workspace_id": ws_id}
    if only_trashed:
        q["deleted_at"] = {"$ne": None}
    elif not include_trashed:
        q["$or"] = [{"deleted_at": {"$exists": False}}, {"deleted_at": None}]
    return q


def build_manual_lead(ws_id, body, settings):
    body = body or {}
    states = {s["key"] for s in settings.get("states", [])}
    status = body.get("status") or "new"
    if status not in states:
        raise HTTPException(status_code=400, detail="Invalid status value")
    incoming_values = body.get("field_values")
    if incoming_values is None:
        incoming_values = {f["key"]: body[f["key"]] for f in active_fields(settings) if f["key"] in body}
    values = validate_field_values(incoming_values or {}, settings)
    lead_id = ObjectId()
    now = now_iso()
    return {
        "_id": lead_id,
        "workspace_id": ws_id,
        "workflow_kind": "ads_to_crm",
        "source": values.get("source") or "manual",
        "sheet_row_key": f"manual:{lead_id}",
        "email": values.get("email"),
        "full_name": values.get("full_name"),
        "phone": values.get("phone"),
        "address": values.get("address"),
        "assigned_salesperson": values.get("assigned_salesperson"),
        "notes": "",
        "lead_notes": [],
        "fields": {},
        "field_values": values,
        "status": status,
        "customer_status": "lead",
        "conversion_type": None,
        "converted_at": None,
        "payment_plan": {},
        "timeline": [{"type": "created", "label": "Lead created manually", "created_at": now}],
        "receipts": [],
        "final_invoice": {},
        "deleted_at": None,
        "delete_after": None,
        "created_at": now,
        "updated_at": now,
    }


def normalize_payment_stage(stage):
    status = stage.get("status") or "pending"
    if status not in VALID_STAGE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid payment stage status")
    source = stage.get("source") or "system"
    if source not in {"system", "manual"}:
        source = "system"
    return {
        "id": str(stage.get("id") or ObjectId()),
        "name": str(stage.get("name") or "").strip(),
        "amount": str(stage.get("amount") or "").strip(),
        "paid_amount": str(stage.get("paid_amount") or "").strip(),
        "due_timing": str(stage.get("due_timing") or "").strip(),
        "status": status,
        "receipt_note": str(stage.get("receipt_note") or "").strip(),
        "transaction_id": str(stage.get("transaction_id") or "").strip(),
        "payment_date": str(stage.get("payment_date") or "").strip(),
        "payment_method": str(stage.get("payment_method") or "").strip(),
        "due_amount": str(stage.get("due_amount") or "").strip(),
        "description": str(stage.get("description") or "").strip(),
        "source": source,
    }


def normalize_payment_plan(body):
    body = body or {}
    stages = body.get("stages") if isinstance(body.get("stages"), list) else []
    normalized = [normalize_payment_stage(stage or {}) for stage in stages]
    if normalized and any(not stage["name"] for stage in normalized):
        raise HTTPException(status_code=400, detail="Every payment stage needs a name")
    plan_status = body.get("status") or ("completed" if normalized and all(s["status"] == "paid" for s in normalized) else "active")
    if plan_status not in VALID_PLAN_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid payment plan status")
    if normalized and all(s["status"] == "paid" for s in normalized):
        plan_status = "completed"
    return ensure_first_stage({
        "status": plan_status,
        "total_amount": str(body.get("total_amount") or "").strip(),
        "stages": normalized,
        "final_invoice_note": str(body.get("final_invoice_note") or "").strip(),
        "updated_at": now_iso(),
    })


def render_template_html(template, lead, settings):
    values = default_field_values(lead, settings)
    plan = lead.get("payment_plan") or {}

    def lookup(path):
        if path == "payment_plan.stages":
            return "\n".join(
                f"<tr><td>{html.escape(s.get('name', ''))}</td><td>{html.escape(s.get('amount', ''))}</td>"
                f"<td>{html.escape(s.get('due_timing', ''))}</td><td>{html.escape(s.get('status', ''))}</td></tr>"
                for s in plan.get("stages", [])
            )
        return html.escape(str(values.get(path, lead.get(path, "")) or ""))

    body = re.sub(r"{{\s*([a-zA-Z0-9_.]+)\s*}}", lambda m: lookup(m.group(1)), template.get("html", ""))
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>"
        f"{html.escape(template.get('name', 'CRM Template'))}</title>"
        "<style>body{font-family:Arial,sans-serif;margin:40px;color:#111}"
        "table{border-collapse:collapse;width:100%;margin-top:16px}td,th{border:1px solid #ddd;padding:8px;text-align:left}"
        "@media print{button{display:none}}</style></head><body>"
        "<button onclick='window.print()'>Print / Save PDF</button>"
        f"{body}</body></html>"
    )


def sequence_number(items, prefix):
    return f"{prefix}-{len(items or []) + 1:04d}"


def money_value(value):
    try:
        return float(str(value or "0").replace(",", ""))
    except ValueError:
        return 0.0


def money_text(value):
    value = max(0, float(value or 0))
    return str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")


def status_from_due(amount, paid):
    if paid <= 0:
        return "pending"
    if amount > 0 and paid < amount:
        return "partially_paid"
    return "paid"


def payment_plan_ready_for_final_invoice(plan):
    stages = plan.get("stages") if isinstance(plan.get("stages"), list) else []
    return bool(stages) and all(stage.get("status") == "paid" for stage in stages)


def payments_total(receipts, stage_id=None):
    total = 0.0
    for receipt in receipts or []:
        if stage_id is not None and receipt.get("stage_id") != stage_id:
            continue
        total += money_value(receipt.get("amount"))
    return total


def payment_stage_remaining_amount(stage, receipts):
    stage_amount = money_value(stage.get("amount"))
    if stage_amount <= 0:
        return money_value(stage.get("due_amount"))
    return max(stage_amount - payments_total(receipts, stage.get("id")), 0)


def ensure_first_stage(plan):
    total = money_value(plan.get("total_amount"))
    stages = plan.get("stages") if isinstance(plan.get("stages"), list) else []
    if total > 0 and not stages:
        stages = [{
            "id": str(ObjectId()),
            "name": "Payment 1",
            "amount": "",
            "paid_amount": "",
            "due_timing": "",
            "status": "pending",
            "receipt_note": "",
            "transaction_id": "",
            "payment_date": "",
            "payment_method": "",
            "due_amount": money_text(total),
            "description": "",
            "source": "system",
        }]
    return {**plan, "stages": stages}


def recalculate_payment_plan(plan, receipts):
    plan = ensure_first_stage(plan or {})
    stages = [normalize_payment_stage(stage) for stage in plan.get("stages", [])]
    total_amount = money_value(plan.get("total_amount"))
    total_paid = payments_total(receipts)
    recalculated = []
    running_paid = 0.0

    for index, stage in enumerate(stages):
        stage_paid = payments_total(receipts, stage.get("id"))
        stage_amount = money_value(stage.get("amount"))
        running_paid += stage_paid
        stage_status = status_from_due(stage_amount, stage_paid)
        stage_due = 0 if stage_status == "paid" else max(total_amount - running_paid, 0)
        stage_receipts = [r for r in receipts or [] if r.get("stage_id") == stage.get("id")]
        latest_receipt = stage_receipts[-1] if stage_receipts else {}
        recalculated.append({
            **stage,
            "name": stage.get("name") or f"Payment {index + 1}",
            "paid_amount": money_text(stage_paid) if stage_paid else "",
            "due_amount": money_text(stage_due),
            "status": stage_status,
            "transaction_id": latest_receipt.get("transaction_id", stage.get("transaction_id", "")),
            "payment_date": latest_receipt.get("payment_date", stage.get("payment_date", "")),
            "payment_method": latest_receipt.get("payment_method", stage.get("payment_method", "")),
            "description": latest_receipt.get("description", stage.get("description", "")),
            "receipt_note": latest_receipt.get("description", stage.get("receipt_note", "")),
        })

    plan_due = max(total_amount - total_paid, 0)
    if recalculated and recalculated[-1]["status"] == "paid" and plan_due > 0:
        recalculated.append({
            "id": str(ObjectId()),
            "name": f"Payment {len(recalculated) + 1}",
            "amount": money_text(plan_due),
            "paid_amount": "",
            "due_timing": "",
            "status": "pending",
            "receipt_note": "",
            "transaction_id": "",
            "payment_date": "",
            "payment_method": "",
            "due_amount": money_text(plan_due),
            "description": "",
            "source": "system",
        })

    completed = bool(recalculated) and plan_due == 0
    return {
        **plan,
        "stages": recalculated,
        "total_paid": money_text(total_paid),
        "due_amount": money_text(plan_due),
        "status": "completed" if completed else "active",
        "updated_at": now_iso(),
    }


def single_payment_summary(lead, receipts, incoming_total=None):
    previous = lead.get("payment_summary") or {}
    total_paid = payments_total(receipts)
    total_amount = money_value(incoming_total or previous.get("total_amount"))
    if total_amount <= 0:
        latest_due = money_value((receipts or [{}])[-1].get("due_amount")) if receipts else 0
        total_amount = total_paid + latest_due
    due_amount = max(total_amount - total_paid, 0)
    return {
        "total_amount": money_text(total_amount),
        "total_paid": money_text(total_paid),
        "due_amount": money_text(due_amount),
        "status": "completed" if receipts and due_amount == 0 else "active",
        "updated_at": now_iso(),
    }


def customer_snapshot(lead, settings):
    values = default_field_values(lead, settings)
    return {
        "name": values.get("full_name", ""),
        "email": values.get("email", ""),
        "phone": values.get("phone", ""),
        "address": values.get("address", ""),
        "field_values": values,
    }


def clean_organization_values(values):
    values = values or {}
    allowed = set(DEFAULT_ORGANIZATION.keys())
    clean = {}
    for key in allowed:
        value = str(values.get(key) or "").strip()
        if value:
            clean[key] = value
    return clean


def effective_organization(settings, workspace=None):
    brain = (workspace or {}).get("brain") or {}
    business_profile = brain.get("business_profile") or {}
    crm_org = clean_organization_values((settings or {}).get("organization") or {})
    brain_org = clean_organization_values({
        "company_name": business_profile.get("company_name", ""),
        "website": brain.get("_source_url") or (workspace or {}).get("website_url", ""),
        **(brain.get("organization") or {}),
    })
    return {**deepcopy(DEFAULT_ORGANIZATION), **crm_org, **brain_org}


async def current_document_organization(db, ws_id):
    settings = await ensure_crm_settings(db, ws_id)
    workspace = await db.workspaces.find_one({"_id": oid(ws_id)})
    return settings, effective_organization(settings, workspace)


def with_document_organization(doc, organization):
    out = {**(doc or {}), "organization": organization}
    if isinstance(out.get("receipts"), list):
        out["receipts"] = [{**receipt, "organization": organization} for receipt in out["receipts"]]
    return out


def brand_initials(name):
    words = [part for part in re.split(r"\s+", str(name or "").strip()) if part]
    initials = "".join(word[0].upper() for word in words[:2])
    return initials or "A"


def logo_html(org):
    logo_url = html.escape(org.get("logo_url", ""))
    if logo_url:
        return f'<img class="logo" src="{logo_url}" alt="{html.escape(org.get("company_name", "Company"))} logo">'
    return f'<div class="logo logo-fallback">{html.escape(brand_initials(org.get("company_name")))}</div>'


def css_color(value, fallback):
    value = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?", value):
        return value
    if re.fullmatch(r"rgba?\([0-9\s,%.]+\)", value):
        return value
    return fallback


def pdf_rgb(value, fallback="#111827"):
    value = css_color(value, fallback)
    if not value.startswith("#"):
        value = fallback
    raw = value[1:]
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    try:
        return tuple(int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except Exception:
        return pdf_rgb(fallback, "#111827") if fallback != "#111827" else (0.067, 0.094, 0.153)


def pdf_contrast(rgb):
    r, g, b = rgb
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return (0, 0, 0) if luminance > 0.55 else (1, 1, 1)


def css_contrast(value):
    r, g, b = pdf_rgb(value, "#000000")
    return "#000000" if (0.2126 * r + 0.7152 * g + 0.0722 * b) > 0.55 else "#ffffff"


def pdf_escape(value):
    text = str(value or "")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def wrap_pdf_text(text, max_chars):
    words = str(text or "").split()
    lines = []
    current = ""
    for word in words:
        next_line = f"{current} {word}".strip()
        if len(next_line) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = next_line
    if current:
        lines.append(current)
    return lines or [""]


class SimplePdf:
    def __init__(self):
        self.ops = []

    def color(self, rgb):
        r, g, b = rgb
        self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg {r:.3f} {g:.3f} {b:.3f} RG")

    def rect(self, x, y, w, h, fill):
        self.color(fill)
        self.ops.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")

    def stroke_rect(self, x, y, w, h, stroke=(0.898, 0.906, 0.922)):
        self.color(stroke)
        self.ops.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re S")

    def line(self, x1, y1, x2, y2, stroke=(0.612, 0.639, 0.686), width=1):
        self.color(stroke)
        self.ops.append(f"{width:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def text(self, x, y, text, size=10, bold=False, fill=(0.067, 0.094, 0.153)):
        self.color(fill)
        font = "F2" if bold else "F1"
        self.ops.append(f"BT /{font} {size:.2f} Tf {x:.2f} {y:.2f} Td ({pdf_escape(text)}) Tj ET")

    def right_text(self, x, y, text, size=10, bold=False, fill=(0.067, 0.094, 0.153)):
        approx_width = len(str(text or "")) * size * 0.52
        self.text(x - approx_width, y, text, size, bold, fill)

    def build(self):
        stream = "\n".join(self.ops).encode("latin-1", errors="replace")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        ]
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for index, obj in enumerate(objects, 1):
            offsets.append(len(out))
            out.extend(f"{index} 0 obj\n".encode())
            out.extend(obj)
            out.extend(b"\nendobj\n")
        xref = len(out)
        out.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
        for offset in offsets[1:]:
            out.extend(f"{offset:010d} 00000 n \n".encode())
        out.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
        return bytes(out)


def receipt_pdf(receipt):
    org = receipt.get("organization", {})
    customer = receipt.get("customer", {})
    accent = pdf_rgb(org.get("document_accent_color"), "#000000")
    ink = pdf_rgb(org.get("document_text_color"), "#000000")
    muted = pdf_rgb(org.get("document_muted_color"), "#000000")
    table_head = pdf_rgb(org.get("document_table_header_color"), "#000000")
    accent_text = pdf_contrast(accent)
    line = pdf_rgb("#e5e7eb")
    pdf = SimplePdf()
    pdf.rect(0, 0, 595, 842, (0.953, 0.957, 0.965))
    pdf.rect(42, 0, 511, 842, (1, 1, 1))
    pdf.rect(42, 833, 511, 9, accent)
    left, right = 64, 531
    content_w = right - left
    top = 760

    pdf.rect(left, top - 8, 44, 44, ink)
    pdf.text(left + 10, top + 8, brand_initials(org.get("company_name")), 17, True, (1, 1, 1))
    pdf.text(left + 58, top + 30, org.get("company_name", ""), 13, True, ink)
    org_lines = [org.get("address", ""), f"{org.get('phone', '')} {org.get('email', '')}".strip(), org.get("tax_number", "")]
    for i, line_text in enumerate([x for x in org_lines if x]):
        pdf.text(left + 58, top + 13 - i * 13, line_text, 9.5, False, muted)

    pdf.rect(332, top + 16, 26, 13, accent)
    pdf.text(370, top + 11, "RECEIPT", 29, True, ink)
    pdf.rect(507, top + 16, 26, 13, accent)
    pdf.text(332, top - 28, "Receipt#", 9.5, True, ink)
    pdf.text(390, top - 28, receipt.get("receipt_number", ""), 9.5, False, ink)
    pdf.text(332, top - 45, "Date", 9.5, True, ink)
    pdf.text(390, top - 45, receipt.get("payment_date", ""), 9.5, False, ink)
    pdf.rect(left, 666, content_w, 8, accent)

    pdf.text(left, 624, "RECEIPT TO", 12, True, ink)
    for i, line_text in enumerate([customer.get("name", ""), customer.get("email", ""), customer.get("phone", ""), customer.get("address", "")]):
        if line_text:
            pdf.text(left, 602 - i * 14, line_text, 10.5, False, muted)

    payment_x = left + 260
    pdf.text(payment_x, 624, "PAYMENT INFO", 12, True, ink)
    payment_lines = [
        f"Stage: {receipt.get('payment_stage', '')}",
        f"Transaction ID: {receipt.get('transaction_id', '')}",
        f"Method: {receipt.get('payment_method', '')}",
        f"Status: {receipt.get('status', '')}",
    ]
    for i, line_text in enumerate(payment_lines):
        pdf.text(payment_x, 602 - i * 14, line_text, 10.5, False, muted)

    table_y = 500
    widths = [38, 168, 136, 60, 65]
    headers = ["Sl.", "Description", "Transaction ID", "Amount", "Due Amount"]
    x = left
    pdf.rect(left, table_y, sum(widths), 32, table_head)
    for i, header in enumerate(headers):
        pdf.text(x + 8, table_y + 13, header, 8.5, True, (1, 1, 1))
        pdf.stroke_rect(x, table_y - 32, widths[i], 64, line)
        x += widths[i]
    pdf.text(left + 8, table_y - 20, "1", 9, False, ink)
    desc = " ".join(wrap_pdf_text(receipt.get("description", "") or receipt.get("payment_stage", ""), 34)[:1])
    pdf.text(left + widths[0] + 8, table_y - 20, desc, 9, False, ink)
    pdf.text(left + widths[0] + widths[1] + 8, table_y - 20, receipt.get("transaction_id", ""), 9, False, ink)
    pdf.right_text(left + sum(widths[:4]) - 8, table_y - 20, receipt.get("amount", ""), 9, False, ink)
    pdf.right_text(left + sum(widths) - 8, table_y - 20, receipt.get("due_amount", ""), 9, False, ink)

    total_x, total_y, total_w = right - 190, 390, 190
    pdf.stroke_rect(total_x, total_y, total_w, 66, line)
    pdf.text(total_x + 12, total_y + 43, "Paid Amount", 10, False, ink)
    pdf.right_text(total_x + total_w - 12, total_y + 43, receipt.get("amount", ""), 10, True, ink)
    pdf.rect(total_x, total_y, total_w, 33, accent)
    pdf.text(total_x + 12, total_y + 12, "Balance Due", 11, True, accent_text)
    pdf.right_text(total_x + total_w - 12, total_y + 12, receipt.get("due_amount", ""), 11, True, accent_text)

    for i, line_text in enumerate(wrap_pdf_text(org.get("bank_details", ""), 42)[:3]):
        pdf.text(left, 330 - i * 13, line_text, 9, False, muted)
    pdf.line(right - 150, 260, right, 260)
    pdf.text(right - 111, 244, org.get("authorized_signatory", "Authorized Signatory"), 9, True, ink)
    pdf.line(left, 34, right, 34, accent, 3)
    pdf.text(left, 18, org.get("phone", ""), 8, False, ink)
    pdf.text(left + 160, 18, org.get("address", ""), 8, False, ink)
    pdf.text(right - 120, 18, org.get("website", ""), 8, False, ink)
    return pdf.build()


def document_styles(org=None):
    org = org or {}
    accent = css_color(org.get("document_accent_color"), "#000000")
    ink = css_color(org.get("document_text_color"), "#000000")
    muted = css_color(org.get("document_muted_color"), "#000000")
    table_header = css_color(org.get("document_table_header_color"), "#000000")
    accent_text = css_contrast(accent)
    return f"""
    :root{{--ink:{ink};--muted:{muted};--line:#e5e7eb;--soft:#f8fafc;--accent:{accent};--accent-text:{accent_text};--table-head:{table_header}}}
    *{{box-sizing:border-box}}body{{font-family:Inter,Arial,sans-serif;margin:0;background:#f3f4f6;color:var(--ink)}}
    .page{{width:794px;min-height:1123px;margin:24px auto;background:#fff;padding:42px 48px;box-shadow:0 20px 55px rgba(15,23,42,.14);position:relative;overflow:hidden}}
    .page:before{{content:"";position:absolute;left:0;right:0;top:0;height:10px;background:var(--accent)}}
    .top{{display:grid;grid-template-columns:1.2fr .8fr;gap:32px;align-items:start;margin-top:18px}}
    .brand{{display:flex;gap:14px;align-items:center}}.logo{{width:54px;height:54px;object-fit:contain;border:1px solid var(--line);background:#fff}}.logo-fallback{{display:grid;place-items:center;background:var(--ink);color:#fff;font-weight:900;font-size:18px}}
    h1{{font-size:38px;line-height:1;margin:0;text-transform:uppercase;font-weight:800;letter-spacing:0}}h2{{font-size:13px;text-transform:uppercase;margin:0 0 10px;font-weight:800;letter-spacing:0;color:var(--ink)}}
    .doc-title{{display:flex;align-items:center;justify-content:flex-end;gap:12px}}.bar{{height:18px;width:74px;background:var(--accent);display:inline-block}}.bar.small{{width:34px}}
    .muted{{color:var(--muted);font-size:12px;line-height:1.55}}.meta{{display:grid;grid-template-columns:auto 1fr;gap:7px 16px;margin-top:28px;font-size:12px}}.meta b{{font-size:12px}}
    .grid{{display:grid;grid-template-columns:1fr 1fr;gap:28px;margin-top:34px}}.box{{min-height:112px}}.section-line{{height:8px;background:var(--accent);width:100%;margin:18px 0 20px}}
    table{{width:100%;border-collapse:collapse;margin-top:24px;font-size:12px}}th{{background:var(--table-head);color:#fff;text-align:left;text-transform:uppercase;font-size:11px;font-weight:800}}td,th{{border:1px solid var(--line);padding:12px}}tbody tr:nth-child(even){{background:var(--soft)}}
    .right{{text-align:right}}.receipt-link{{color:var(--ink);font-weight:800;text-decoration:underline;text-underline-offset:2px}}.total{{margin-left:auto;margin-top:22px;width:315px;border:1px solid var(--line)}}.row{{display:flex;justify-content:space-between;gap:16px;padding:12px 14px;border-bottom:1px solid var(--line);font-size:13px}}.row:last-child{{border-bottom:0;background:var(--accent);color:var(--accent-text);font-weight:900}}
    .footer{{display:grid;grid-template-columns:1fr 220px;gap:32px;margin-top:44px;align-items:end}}.sign{{border-top:1px solid #9ca3af;padding-top:10px;text-align:center;font-size:12px;font-weight:700}}.footbar{{position:absolute;left:48px;right:48px;bottom:28px;border-top:3px solid var(--accent);padding-top:12px;display:flex;gap:18px;font-size:11px;color:var(--ink)}}
    button,.download-btn{{position:fixed;right:24px;top:24px;padding:10px 14px;border:0;border-radius:6px;background:var(--ink);color:white;font-weight:800;text-decoration:none}}@media print{{body{{background:white}}.page{{box-shadow:none;margin:0;width:auto;min-height:1123px}}button,.download-btn{{display:none}}}}
    """


def normalize_lead_note(body):
    body = body or {}
    note = str(body.get("body") or body.get("note") or body.get("content") or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="Note cannot be empty")
    return {
        "id": str(ObjectId()),
        "body": note,
        "author": str(body.get("author") or "Internal").strip() or "Internal",
        "created_at": now_iso(),
    }


def receipt_html(receipt):
    org = receipt.get("organization", {})
    customer = receipt.get("customer", {})
    pdf_url = f"./pdf"
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(receipt.get("receipt_number", "Receipt"))}</title>
  <style>{document_styles(org)}</style>
</head>
<body><a class="download-btn" href="{pdf_url}">Download PDF</a><main class="page">
  <section class="top"><div class="brand">{logo_html(org)}<div><h2>{html.escape(org.get("company_name", ""))}</h2><div class="muted">{html.escape(org.get("address", ""))}<br>{html.escape(org.get("phone", ""))} {html.escape(org.get("email", ""))}<br>{html.escape(org.get("tax_number", ""))}</div></div></div><div><div class="doc-title"><span class="bar small"></span><h1>Receipt</h1><span class="bar small"></span></div><div class="meta"><b>Receipt#</b><span>{html.escape(receipt.get("receipt_number", ""))}</span><b>Date</b><span>{html.escape(receipt.get("payment_date", ""))}</span></div></div></section>
  <div class="section-line"></div>
  <section class="grid"><div class="box"><h2>Receipt To</h2><div class="muted">{html.escape(customer.get("name", ""))}<br>{html.escape(customer.get("email", ""))}<br>{html.escape(customer.get("phone", ""))}<br>{html.escape(customer.get("address", ""))}</div></div><div class="box"><h2>Payment Info</h2><div class="muted">Stage: {html.escape(receipt.get("payment_stage", ""))}<br>Transaction ID: {html.escape(receipt.get("transaction_id", ""))}<br>Method: {html.escape(receipt.get("payment_method", ""))}<br>Status: {html.escape(receipt.get("status", ""))}</div></div></section>
  <table><thead><tr><th>Sl.</th><th>Description</th><th>Transaction ID</th><th class="right">Amount</th><th class="right">Due Amount</th></tr></thead><tbody><tr><td>1</td><td>{html.escape(receipt.get("description", "") or receipt.get("payment_stage", ""))}</td><td>{html.escape(receipt.get("transaction_id", ""))}</td><td class="right">{html.escape(str(receipt.get("amount", "")))}</td><td class="right">{html.escape(str(receipt.get("due_amount", "")))}</td></tr></tbody></table>
  <section class="total"><div class="row"><span>Paid Amount</span><strong>{html.escape(str(receipt.get("amount", "")))}</strong></div><div class="row"><span>Balance Due</span><strong>{html.escape(str(receipt.get("due_amount", "")))}</strong></div></section>
  <section class="footer"><div class="muted">{html.escape(org.get("bank_details", ""))}</div><div class="sign">{html.escape(org.get("authorized_signatory", "Authorized Signatory"))}</div></section>
  <section class="footbar"><span>{html.escape(org.get("phone", ""))}</span><span>{html.escape(org.get("address", ""))}</span><span>{html.escape(org.get("website", ""))}</span></section>
</main></body></html>"""


def receipt_download_link(receipt):
    receipt_id = str(receipt.get("id") or "").strip()
    if not receipt_id:
        return ""
    return f'<a class="receipt-link" href="../receipts/{html.escape(receipt_id)}/pdf">Download Receipt</a>'


def invoice_html(invoice):
    org = invoice.get("organization", {})
    customer = invoice.get("customer", {})
    receipts = invoice.get("receipts", [])
    rows = "".join(
        f"<tr><td>{i}</td><td>{html.escape(r.get('receipt_number',''))}</td><td>{html.escape(r.get('payment_stage',''))}</td><td>{html.escape(r.get('payment_date',''))}</td><td>{html.escape(r.get('transaction_id',''))}</td><td class='right'>{html.escape(str(r.get('amount','')))}</td><td>{receipt_download_link(r)}</td></tr>"
        for i, r in enumerate(receipts, 1)
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(invoice.get("invoice_number", "Final Invoice"))}</title><style>{document_styles(org)}</style></head><body><a class="download-btn" href="./pdf">Download PDF</a><main class="page">
<section class="top"><div class="brand">{logo_html(org)}<div><h2>{html.escape(org.get("company_name",""))}</h2><div class="muted">{html.escape(org.get("address",""))}<br>{html.escape(org.get("phone",""))} {html.escape(org.get("email",""))}<br>{html.escape(org.get("tax_number",""))}</div></div></div><div><div class="doc-title"><span class="bar"></span><h1>Invoice</h1><span class="bar small"></span></div><div class="meta"><b>Invoice#</b><span>{html.escape(invoice.get("invoice_number",""))}</span><b>Date</b><span>{html.escape(invoice.get("generated_at",""))}</span></div></div></section>
<div class="section-line"></div>
<section class="grid"><div class="box"><h2>Invoice To</h2><div class="muted">{html.escape(customer.get("name",""))}<br>{html.escape(customer.get("email",""))}<br>{html.escape(customer.get("phone",""))}<br>{html.escape(customer.get("address",""))}</div></div><div class="box"><h2>Payment Info</h2><div class="muted">Status: Completed<br>Receipts: {len(receipts)}<br>Tax Number: {html.escape(org.get("tax_number",""))}</div></div></section>
<table><thead><tr><th>Sl.</th><th>Receipt</th><th>Stage</th><th>Date</th><th>Transaction ID</th><th class="right">Amount</th><th>Download</th></tr></thead><tbody>{rows}</tbody></table>
<section class="total"><div class="row"><span>Total Paid</span><strong>{html.escape(str(invoice.get("total_paid","")))}</strong></div><div class="row"><span>Final Due</span><strong>{html.escape(str(invoice.get("due_amount","")))}</strong></div></section>
<section class="footer"><div class="muted">{html.escape(invoice.get("description",""))}<br><br>{html.escape(org.get("bank_details",""))}</div><div class="sign">{html.escape(org.get("authorized_signatory","Authorized Signatory"))}</div></section>
<section class="footbar"><span>{html.escape(org.get("phone",""))}</span><span>{html.escape(org.get("address",""))}</span><span>{html.escape(org.get("website",""))}</span></section>
</main></body></html>"""


def invoice_pdf(invoice):
    org = invoice.get("organization", {})
    customer = invoice.get("customer", {})
    receipts = invoice.get("receipts", [])
    accent = pdf_rgb(org.get("document_accent_color"), "#000000")
    ink = pdf_rgb(org.get("document_text_color"), "#000000")
    muted = pdf_rgb(org.get("document_muted_color"), "#000000")
    table_head = pdf_rgb(org.get("document_table_header_color"), "#000000")
    accent_text = pdf_contrast(accent)
    line = pdf_rgb("#e5e7eb")
    pdf = SimplePdf()
    pdf.rect(0, 0, 595, 842, (0.953, 0.957, 0.965))
    pdf.rect(42, 0, 511, 842, (1, 1, 1))
    pdf.rect(42, 833, 511, 9, accent)
    left, right = 64, 531
    content_w = right - left
    top = 760

    pdf.rect(left, top - 8, 44, 44, ink)
    pdf.text(left + 10, top + 8, brand_initials(org.get("company_name")), 17, True, (1, 1, 1))
    pdf.text(left + 58, top + 30, org.get("company_name", ""), 13, True, ink)
    org_lines = [org.get("address", ""), f"{org.get('phone', '')} {org.get('email', '')}".strip(), org.get("tax_number", "")]
    for i, line_text in enumerate([x for x in org_lines if x]):
        pdf.text(left + 58, top + 13 - i * 13, line_text, 9.5, False, muted)

    pdf.rect(332, top + 16, 26, 13, accent)
    pdf.text(370, top + 11, "INVOICE", 29, True, ink)
    pdf.rect(507, top + 16, 26, 13, accent)
    pdf.text(332, top - 28, "Invoice#", 9.5, True, ink)
    pdf.text(390, top - 28, invoice.get("invoice_number", ""), 9.5, False, ink)
    pdf.text(332, top - 45, "Date", 9.5, True, ink)
    pdf.text(390, top - 45, invoice.get("generated_at", ""), 9.5, False, ink)
    pdf.rect(left, 666, content_w, 8, accent)

    pdf.text(left, 624, "INVOICE TO", 12, True, ink)
    for i, line_text in enumerate([customer.get("name", ""), customer.get("email", ""), customer.get("phone", ""), customer.get("address", "")]):
        if line_text:
            pdf.text(left, 602 - i * 14, line_text, 10.5, False, muted)

    payment_x = left + 260
    pdf.text(payment_x, 624, "PAYMENT INFO", 12, True, ink)
    for i, line_text in enumerate(["Status: Completed", f"Receipts: {len(receipts)}", f"Tax Number: {org.get('tax_number', '')}"]):
        pdf.text(payment_x, 602 - i * 14, line_text, 10.5, False, muted)

    table_y = 500
    widths = [28, 72, 76, 66, 112, 76]
    headers = ["Sl.", "Receipt", "Stage", "Date", "Transaction ID", "Amount"]
    pdf.rect(left, table_y, sum(widths), 32, table_head)
    x = left
    for i, header in enumerate(headers):
        pdf.text(x + 6, table_y + 13, header, 7.5, True, (1, 1, 1))
        pdf.stroke_rect(x, table_y - 28 * max(len(receipts), 1), widths[i], 32 + 28 * max(len(receipts), 1), line)
        x += widths[i]
    for row_index, receipt in enumerate(receipts[:10], 1):
        y = table_y - 20 - ((row_index - 1) * 28)
        x = left
        values = [
            str(row_index),
            receipt.get("receipt_number", ""),
            receipt.get("payment_stage", ""),
            receipt.get("payment_date", ""),
            receipt.get("transaction_id", ""),
            str(receipt.get("amount", "")),
        ]
        for col_index, value in enumerate(values):
            text = " ".join(wrap_pdf_text(value, 16)[:1])
            if col_index == 5:
                pdf.right_text(x + widths[col_index] - 6, y, text, 8.2, False, ink)
            else:
                pdf.text(x + 6, y, text, 8.2, False, ink)
            x += widths[col_index]

    total_x, total_y, total_w = right - 235, 210, 235
    pdf.stroke_rect(total_x, total_y, total_w, 66, line)
    pdf.text(total_x + 12, total_y + 43, "Total Paid", 10, False, ink)
    pdf.right_text(total_x + total_w - 12, total_y + 43, invoice.get("total_paid", ""), 10, True, ink)
    pdf.rect(total_x, total_y, total_w, 33, accent)
    pdf.text(total_x + 12, total_y + 12, "Final Due", 11, True, accent_text)
    pdf.right_text(total_x + total_w - 12, total_y + 12, invoice.get("due_amount", ""), 11, True, accent_text)

    for i, line_text in enumerate(wrap_pdf_text(invoice.get("description", "") or org.get("bank_details", ""), 46)[:3]):
        pdf.text(left, 160 - i * 13, line_text, 9, False, muted)
    pdf.line(right - 150, 110, right, 110)
    pdf.text(right - 111, 94, org.get("authorized_signatory", "Authorized Signatory"), 9, True, ink)
    pdf.line(left, 34, right, 34, accent, 3)
    pdf.text(left, 18, org.get("phone", ""), 8, False, ink)
    pdf.text(left + 160, 18, org.get("address", ""), 8, False, ink)
    pdf.text(right - 120, 18, org.get("website", ""), 8, False, ink)
    return pdf.build()


@router.get("/settings")
async def get_settings(ws_id: str, request: Request):
    settings = await ensure_crm_settings(db_from(request), ws_id)
    return doc_out(settings)


@router.put("/settings/fields")
async def replace_fields(ws_id: str, request: Request, body: dict = Body(...)):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    current = {f["key"]: f for f in settings.get("fields", [])}
    fields = [normalize_field(field, current.get(keyify(field.get("key") or field.get("label")))) for field in body.get("fields", [])]
    if not any(f["key"] == "phone" for f in fields):
        fields.insert(0, normalize_field({"key": "phone"}, current.get("phone")))
    await db.crm_settings.update_one({"workspace_id": ws_id}, {"$set": {"fields": fields, "updated_at": now_iso()}})
    return doc_out(await db.crm_settings.find_one({"workspace_id": ws_id}))


@router.post("/settings/fields")
async def add_field(ws_id: str, request: Request, body: dict = Body(...)):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    field = normalize_field(body)
    if any(existing.get("key") == field["key"] for existing in settings.get("fields", [])):
        raise HTTPException(status_code=400, detail="Field key already exists")
    await db.crm_settings.update_one({"workspace_id": ws_id}, {"$push": {"fields": field}, "$set": {"updated_at": now_iso()}})
    return doc_out(await db.crm_settings.find_one({"workspace_id": ws_id}))


@router.patch("/settings/fields/{field_key}")
async def update_field(ws_id: str, field_key: str, request: Request, body: dict = Body(...)):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    fields = settings.get("fields", [])
    key = keyify(field_key)
    updated = []
    found = False
    for field in fields:
        if field.get("key") == key:
            found = True
            updated.append(normalize_field({**field, **body, "key": key}, field))
        else:
            updated.append(field)
    if not found:
        raise HTTPException(status_code=404, detail="Field not found")
    await db.crm_settings.update_one({"workspace_id": ws_id}, {"$set": {"fields": updated, "updated_at": now_iso()}})
    return doc_out(await db.crm_settings.find_one({"workspace_id": ws_id}))


@router.delete("/settings/fields/{field_key}")
async def deactivate_field(ws_id: str, field_key: str, request: Request):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    key = keyify(field_key)
    if key == "phone":
        raise HTTPException(status_code=400, detail="Phone is required and cannot be removed")
    fields = [{**f, "active": False, "updated_at": now_iso()} if f.get("key") == key else f for f in settings.get("fields", [])]
    await db.crm_settings.update_one({"workspace_id": ws_id}, {"$set": {"fields": fields, "updated_at": now_iso()}})
    return doc_out(await db.crm_settings.find_one({"workspace_id": ws_id}))


@router.put("/settings/states")
async def replace_states(ws_id: str, request: Request, body: dict = Body(...)):
    db = db_from(request)
    await ensure_crm_settings(db, ws_id)
    states = normalize_states(body.get("states", []))
    await db.crm_settings.update_one({"workspace_id": ws_id}, {"$set": {"states": states, "updated_at": now_iso()}})
    return doc_out(await db.crm_settings.find_one({"workspace_id": ws_id}))


@router.post("/settings/templates")
async def upsert_template(ws_id: str, request: Request, body: dict = Body(...)):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    template = normalize_template(body)
    templates = [t for t in settings.get("templates", []) if t.get("id") != template["id"]]
    templates.append(template)
    await db.crm_settings.update_one({"workspace_id": ws_id}, {"$set": {"templates": templates, "updated_at": now_iso()}})
    return doc_out(await db.crm_settings.find_one({"workspace_id": ws_id}))


@router.patch("/settings/organization")
async def update_organization(ws_id: str, request: Request, body: dict = Body(...)):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    org = {**deepcopy(DEFAULT_ORGANIZATION), **(settings.get("organization") or {})}
    allowed = set(DEFAULT_ORGANIZATION.keys())
    org.update({k: str(v or "") for k, v in body.items() if k in allowed})
    await db.crm_settings.update_one({"workspace_id": ws_id}, {"$set": {"organization": org, "updated_at": now_iso()}})
    return doc_out(await db.crm_settings.find_one({"workspace_id": ws_id}))


@router.get("/leads")
async def list_leads(
    ws_id: str,
    request: Request,
    status: str = Query(None),
    page: int = Query(None),
    limit: int = Query(20),
    search: str = Query(""),
    trashed: bool = Query(False),
):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    await purge_expired_trashed_leads(db, ws_id)
    q = lead_query(ws_id, only_trashed=trashed)
    if status:
        q["status"] = status
    all_docs = await db.crm_leads.find(q).sort("created_at", -1).to_list(1000)
    decorated = [decorate_lead(d, settings) for d in all_docs]
    if search:
        term = search.lower()
        decorated = [
            lead for lead in decorated
            if any(term in str(v or "").lower() for v in (lead.get("field_values") or {}).values())
        ]
    if page is None:
        return decorated
    safe_limit = max(1, min(int(limit or 20), 100))
    safe_page = max(1, int(page or 1))
    start = (safe_page - 1) * safe_limit
    return {
        "items": decorated[start:start + safe_limit],
        "total": len(decorated),
        "page": safe_page,
        "limit": safe_limit,
    }


@router.post("/leads")
async def create_lead(ws_id: str, request: Request, body: dict = Body(...)):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    await purge_expired_trashed_leads(db, ws_id)
    lead_doc = build_manual_lead(ws_id, body, settings)
    await db.crm_leads.insert_one(lead_doc)
    return decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": lead_doc["_id"]}), settings)


@router.get("/leads/{lead_id}")
async def get_lead(ws_id: str, lead_id: str, request: Request):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    await purge_expired_trashed_leads(db, ws_id)
    doc = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Lead not found")
    return decorate_lead(doc, settings)


@router.delete("/leads/{lead_id}")
async def trash_lead(ws_id: str, lead_id: str, request: Request):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    await purge_expired_trashed_leads(db, ws_id)
    now = now_iso()
    result = await db.crm_leads.update_one(
        {
            "workspace_id": ws_id,
            "_id": oid(lead_id),
            "$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}],
        },
        {"$set": {"deleted_at": now, "delete_after": iso_after_days(TRASH_RETENTION_DAYS), "updated_at": now}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    return decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)}), settings)


@router.post("/leads/{lead_id}/restore")
async def restore_lead(ws_id: str, lead_id: str, request: Request):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    await purge_expired_trashed_leads(db, ws_id)
    result = await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": oid(lead_id), "deleted_at": {"$ne": None}},
        {"$set": {"updated_at": now_iso()}, "$unset": {"deleted_at": "", "delete_after": ""}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found in trash")
    return decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)}), settings)


@router.get("/leads/{lead_id}/notes")
async def list_lead_notes(ws_id: str, lead_id: str, request: Request):
    db = db_from(request)
    doc = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Lead not found")
    return doc.get("lead_notes") or []


@router.post("/leads/{lead_id}/notes")
async def add_lead_note(ws_id: str, lead_id: str, request: Request, body: dict = Body(...)):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    doc = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Lead not found")
    note = normalize_lead_note(body)
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": oid(lead_id)},
        {"$push": {"lead_notes": note}, "$set": {"updated_at": now_iso()}},
    )
    return decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)}), settings)


@router.delete("/leads/{lead_id}/notes/{note_id}")
async def delete_lead_note(ws_id: str, lead_id: str, note_id: str, request: Request):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    doc = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Lead not found")
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": oid(lead_id)},
        {"$pull": {"lead_notes": {"id": note_id}}, "$set": {"updated_at": now_iso()}},
    )
    return decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)}), settings)


@router.patch("/leads/{lead_id}")
async def update_lead(ws_id: str, lead_id: str, request: Request, body: dict = Body(...)):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    doc = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Lead not found")
    states = {s["key"] for s in settings.get("states", [])}
    status = body.get("status", doc.get("status", "new"))
    if status not in states:
        raise HTTPException(status_code=400, detail="Invalid status value")

    incoming_values = body.get("field_values")
    if incoming_values is None:
        incoming_values = {f["key"]: body[f["key"]] for f in active_fields(settings) if f["key"] in body}
    values = default_field_values(doc, settings)
    allowed = {f["key"] for f in active_fields(settings)}
    values.update({k: v for k, v in (incoming_values or {}).items() if k in allowed})
    values = validate_field_values(values, settings)
    updates = {
        "status": status,
        "field_values": values,
        "email": values.get("email"),
        "full_name": values.get("full_name"),
        "phone": values.get("phone"),
        "address": values.get("address"),
        "source": values.get("source", doc.get("source", "google_sheet")),
        "assigned_salesperson": values.get("assigned_salesperson"),
        "updated_at": now_iso(),
    }
    await db.crm_leads.update_one({"workspace_id": ws_id, "_id": oid(lead_id)}, {"$set": updates})
    return decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)}), settings)


@router.post("/leads/{lead_id}/convert")
async def convert_lead(ws_id: str, lead_id: str, request: Request, body: dict = Body(default=None)):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    body = body or {}
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    conversion_type = body.get("conversion_type") or "payment_plan"
    if conversion_type not in {"single_payment", "payment_plan"}:
        raise HTTPException(status_code=400, detail="Invalid conversion type")
    plan = {} if conversion_type == "single_payment" else recalculate_payment_plan(normalize_payment_plan(body.get("payment_plan") or lead.get("payment_plan") or {}), lead.get("receipts") or [])
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": oid(lead_id)},
        {"$set": {
            "status": "won",
            "customer_status": "customer",
            "conversion_type": conversion_type,
            "converted_at": lead.get("converted_at") or now_iso(),
            "payment_plan": plan,
            "updated_at": now_iso(),
        }},
    )
    return decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)}), settings)


@router.post("/leads/{lead_id}/receipts")
async def create_receipt(ws_id: str, lead_id: str, request: Request, body: dict = Body(...)):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    workspace = await db.workspaces.find_one({"_id": oid(ws_id)})
    org = effective_organization(settings, workspace)
    receipts = lead.get("receipts") or []
    receipt_number = str(body.get("receipt_number") or sequence_number(receipts, org.get("receipt_prefix", "REC"))).strip()
    if any(r.get("receipt_number") == receipt_number for r in receipts):
        raise HTTPException(status_code=400, detail="Receipt number already exists for this customer")
    amount = str(body.get("amount") or "").strip()
    if not amount:
        raise HTTPException(status_code=400, detail="Payment amount is required")
    amount_value = money_value(amount)
    if amount_value <= 0:
        raise HTTPException(status_code=400, detail="Payment amount must be greater than zero")
    stage_id = str(body.get("stage_id") or "").strip()
    has_payment_plan_payload = isinstance(body.get("payment_plan"), dict)
    conversion_type = lead.get("conversion_type") or ("payment_plan" if stage_id or has_payment_plan_payload else "single_payment")
    plan = normalize_payment_plan(body.get("payment_plan")) if isinstance(body.get("payment_plan"), dict) else lead.get("payment_plan") or {}
    if conversion_type == "single_payment":
        current_summary = single_payment_summary(lead, receipts, body.get("total_amount"))
        current_due = money_value(current_summary.get("due_amount"))
        if money_value(current_summary.get("total_amount")) <= 0:
            raise HTTPException(status_code=400, detail="Total amount is required")
        if current_due <= 0:
            raise HTTPException(status_code=400, detail="Payment is already complete")
        if amount_value > current_due:
            raise HTTPException(status_code=400, detail="Payment amount cannot exceed due amount")
        next_receipts = receipts + [{"stage_id": "", "amount": amount}]
        summary = single_payment_summary(lead, next_receipts, body.get("total_amount"))
        due_amount = summary["due_amount"]
    else:
        current_plan = recalculate_payment_plan(plan, receipts)
        stages = current_plan.get("stages") or []
        if not stage_id or not any(s.get("id") == stage_id for s in stages):
            raise HTTPException(status_code=400, detail="Valid payment stage is required")
        target_index = next(i for i, s in enumerate(stages) if s.get("id") == stage_id)
        if target_index > 0 and stages[target_index - 1].get("status") != "paid":
            raise HTTPException(status_code=400, detail="Complete the previous payment stage first")
        stage_due = payment_stage_remaining_amount(stages[target_index], receipts)
        if stage_due <= 0:
            raise HTTPException(status_code=400, detail="Payment stage is already complete")
        if amount_value > stage_due:
            raise HTTPException(status_code=400, detail="Payment amount cannot exceed this payment stage amount")
        plan = current_plan
        due_amount = str(body.get("due_amount") or "0").strip()
    receipt = {
        "id": str(ObjectId()),
        "stage_id": stage_id,
        "receipt_number": receipt_number,
        "transaction_id": str(body.get("transaction_id") or body.get("payment_id") or ObjectId()).strip(),
        "payment_stage": str(body.get("payment_stage") or "Single Payment").strip(),
        "amount": amount,
        "payment_date": str(body.get("payment_date") or now_iso()[:10]).strip(),
        "payment_method": str(body.get("payment_method") or "").strip(),
        "status": str(body.get("status") or "Paid").strip(),
        "due_amount": due_amount,
        "description": str(body.get("description") or "").strip(),
        "organization": org,
        "customer": customer_snapshot(lead, settings),
        "created_at": now_iso(),
    }
    set_updates = {"updated_at": now_iso()}
    plan = plan if conversion_type == "payment_plan" else lead.get("payment_plan") or {}
    if conversion_type == "single_payment":
        set_updates["payment_summary"] = summary
        receipt["due_amount"] = summary["due_amount"]
    elif receipt["stage_id"] and plan.get("stages"):
        recalculated = recalculate_payment_plan(plan, receipts + [receipt])
        receipt["due_amount"] = recalculated["due_amount"]
        set_updates["payment_plan"] = recalculated
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": oid(lead_id)},
        {"$push": {"receipts": receipt}, "$set": set_updates},
    )
    return decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)}), settings)


@router.get("/leads/{lead_id}/receipts/{receipt_id}/html")
async def render_receipt(ws_id: str, lead_id: str, receipt_id: str, request: Request):
    db = db_from(request)
    _, org = await current_document_organization(db, ws_id)
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    receipt = next((r for r in lead.get("receipts", []) if r.get("id") == receipt_id), None)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return HTMLResponse(receipt_html(with_document_organization(receipt, org)))


@router.get("/leads/{lead_id}/receipts/{receipt_id}/pdf")
async def render_receipt_pdf(ws_id: str, lead_id: str, receipt_id: str, request: Request):
    db = db_from(request)
    _, org = await current_document_organization(db, ws_id)
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    receipt = next((r for r in lead.get("receipts", []) if r.get("id") == receipt_id), None)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    filename = re.sub(r"[^A-Za-z0-9_.-]+", "-", receipt.get("receipt_number") or "receipt").strip("-") or "receipt"
    return Response(
        content=receipt_pdf(with_document_organization(receipt, org)),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )


@router.get("/leads/{lead_id}/receipts/{receipt_id}/download")
async def download_receipt(ws_id: str, lead_id: str, receipt_id: str, request: Request):
    db = db_from(request)
    _, org = await current_document_organization(db, ws_id)
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    receipt = next((r for r in lead.get("receipts", []) if r.get("id") == receipt_id), None)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    filename = re.sub(r"[^A-Za-z0-9_.-]+", "-", receipt.get("receipt_number") or "receipt").strip("-") or "receipt"
    return Response(
        content=receipt_html(with_document_organization(receipt, org)),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.html"'},
    )


@router.post("/leads/{lead_id}/final-invoice")
async def create_final_invoice(ws_id: str, lead_id: str, request: Request, body: dict = Body(default=None)):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    body = body or {}
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    conversion_type = lead.get("conversion_type") or "payment_plan"
    workspace = await db.workspaces.find_one({"_id": oid(ws_id)})
    org = effective_organization(settings, workspace)
    receipts = lead.get("receipts") or []
    if not receipts:
        raise HTTPException(status_code=400, detail="Add at least one payment transaction before generating final invoice")
    if conversion_type == "payment_plan":
        plan = recalculate_payment_plan(lead.get("payment_plan") or {}, receipts)
        total_paid = plan.get("total_paid", "0")
        due_amount = plan.get("due_amount", "0")
        if (
            money_value(due_amount) > 0
            or any(money_value(s.get("due_amount")) > 0 for s in plan.get("stages", []))
            or not payment_plan_ready_for_final_invoice(plan)
        ):
            raise HTTPException(status_code=400, detail="All payment stages must be paid before final invoice")
    else:
        summary = single_payment_summary(lead, receipts)
        total_paid = summary.get("total_paid", "0")
        due_amount = summary.get("due_amount", "0")
        if money_value(due_amount) > 0:
            raise HTTPException(status_code=400, detail="Clear due amount before generating final invoice")
    invoice = {
        "id": str(ObjectId()),
        "invoice_number": str(body.get("invoice_number") or org.get("invoice_prefix", "INV") + "-0001").strip(),
        "generated_at": now_iso()[:10],
        "organization": org,
        "customer": customer_snapshot(lead, settings),
        "receipts": receipts,
        "total_paid": total_paid,
        "due_amount": due_amount,
        "description": str(body.get("description") or "").strip(),
        "created_at": now_iso(),
    }
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": oid(lead_id)},
        {"$set": {"final_invoice": invoice, "updated_at": now_iso()}},
    )
    return invoice


@router.get("/leads/{lead_id}/final-invoice/html")
async def render_final_invoice(ws_id: str, lead_id: str, request: Request):
    db = db_from(request)
    _, org = await current_document_organization(db, ws_id)
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    invoice = lead.get("final_invoice")
    if not invoice:
        raise HTTPException(status_code=404, detail="Final invoice not found")
    return HTMLResponse(invoice_html(with_document_organization(invoice, org)))


@router.get("/leads/{lead_id}/final-invoice/pdf")
async def render_final_invoice_pdf(ws_id: str, lead_id: str, request: Request):
    db = db_from(request)
    _, org = await current_document_organization(db, ws_id)
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    invoice = lead.get("final_invoice")
    if not invoice:
        raise HTTPException(status_code=404, detail="Final invoice not found")
    filename = re.sub(r"[^A-Za-z0-9_.-]+", "-", invoice.get("invoice_number") or "final-invoice").strip("-") or "final-invoice"
    return Response(
        content=invoice_pdf(with_document_organization(invoice, org)),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )


@router.patch("/leads/{lead_id}/payment-plan")
async def update_payment_plan(ws_id: str, lead_id: str, request: Request, body: dict = Body(...)):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.get("customer_status") != "customer":
        raise HTTPException(status_code=400, detail="Convert the lead before adding a payment plan")
    plan = recalculate_payment_plan(normalize_payment_plan(body), lead.get("receipts") or [])
    await db.crm_leads.update_one(
        {"workspace_id": ws_id, "_id": oid(lead_id)},
        {"$set": {"payment_plan": plan, "updated_at": now_iso()}},
    )
    return decorate_lead(await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)}), settings)


@router.get("/leads/{lead_id}/templates/{template_id}/render")
async def render_lead_template(ws_id: str, lead_id: str, template_id: str, request: Request):
    db = db_from(request)
    settings = await ensure_crm_settings(db, ws_id)
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    template = next((t for t in settings.get("templates", []) if t.get("id") == template_id and t.get("active", True)), None)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return HTMLResponse(render_template_html(template, lead, settings))
