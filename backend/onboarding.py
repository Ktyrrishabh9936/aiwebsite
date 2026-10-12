"""Guided onboarding: user profile, AI-guided sales setup interview and setup checklist.

User-level state lives on ``users.onboarding``; the interview transcript and answers
live on ``workspaces.onboarding_interview``. The interview fills the existing
``SalesProfile`` so the sales strategy engine needs no changes.
"""
import asyncio
import html
import logging
import os
import re
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from auth import get_current_user, get_current_user_and_workspace, new_onboarding_state, onboarding_out
from mailer import _base_email, admin_notify_email, send_email_background

logger = logging.getLogger("onboarding")
router = APIRouter(tags=["Onboarding"])

ASSIST_EMAIL = os.environ.get("ONBOARDING_ASSIST_EMAIL", "admin@arevei.com")
CONTACT = {"name": "arevei", "email": "admin@arevei.com"}
ROLES = {"founder", "marketer", "real_estate_broker", "sales_leader", "agency", "other"}
HEARD_FROM = {"social_media", "chatgpt_ai", "whatsapp", "google_search", "referral", "event", "other"}
STEPS = {"about", "setup", "interview", "channels", "done"}
SECONDS_PER_QUESTION = 40


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- user profile
class ProfileInput(BaseModel):
    role: str
    role_other: str = Field(default="", max_length=120)
    heard_from: str
    heard_from_other: str = Field(default="", max_length=200)


class StepInput(BaseModel):
    step: str
    workspace_id: str | None = None


class CompleteInput(BaseModel):
    skipped: bool = False


class AssistInput(BaseModel):
    workspace_id: str | None = None
    phone: str = Field(default="", max_length=40)
    preferred_time: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=2000)


def _db(request):
    return request.app.state.db


async def _set_user_onboarding(db, user, updates):
    current = user.get("onboarding") or new_onboarding_state()
    merged = {**current, **updates, "updated_at": now_iso()}
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"onboarding": merged}})
    return {**merged, "completed": bool(merged.get("completed_at"))}


@router.get("/onboarding")
async def get_onboarding(request: Request):
    user = await get_current_user(request, _db(request))
    return {**onboarding_out(user), "contact": CONTACT}


@router.put("/onboarding/profile")
async def save_profile(request: Request, body: ProfileInput):
    db = _db(request)
    user = await get_current_user(request, db)
    if body.role not in ROLES:
        raise HTTPException(422, "Choose your role")
    if body.heard_from not in HEARD_FROM:
        raise HTTPException(422, "Tell us how you heard about Arevei")
    if body.role == "other" and not body.role_other.strip():
        raise HTTPException(422, "Tell us your role")
    current = user.get("onboarding") or {}
    step = current.get("step") if current.get("step") not in (None, "about") else "setup"
    return await _set_user_onboarding(db, user, {**body.model_dump(), "step": step})


@router.put("/onboarding/step")
async def save_step(request: Request, body: StepInput):
    db = _db(request)
    user = await get_current_user(request, db)
    if body.step not in STEPS:
        raise HTTPException(422, "Unknown onboarding step")
    updates = {"step": body.step}
    if body.workspace_id:
        updates["workspace_id"] = body.workspace_id
    return await _set_user_onboarding(db, user, updates)


@router.post("/onboarding/complete")
async def complete(request: Request, body: CompleteInput = Body(default=CompleteInput())):
    db = _db(request)
    user = await get_current_user(request, db)
    return await _set_user_onboarding(db, user, {"step": "done", "completed_at": now_iso(), "skipped": body.skipped})


@router.post("/onboarding/assist")
async def request_assist(request: Request, body: AssistInput):
    """'Contact Arevei for setup': notify the Arevei team and record the request."""
    db = _db(request)
    user = await get_current_user(request, db)
    state = user.get("onboarding") or {}
    workspace = None
    if body.workspace_id and ObjectId.is_valid(body.workspace_id):
        workspace = await db.workspaces.find_one({"_id": ObjectId(body.workspace_id), "user_id": str(user["_id"])})
    rows = [
        ("Name", user.get("name") or ""), ("Email", user.get("email") or ""), ("Phone", body.phone),
        ("Role", state.get("role_other") or state.get("role") or ""),
        ("Heard about us", state.get("heard_from_other") or state.get("heard_from") or ""),
        ("Website", (workspace or {}).get("website_url") or ""), ("Preferred time", body.preferred_time), ("Note", body.note),
    ]
    table = "".join(
        f'<tr><td style="padding:10px;border-bottom:1px solid #e2e8f0;color:#64748b">{html.escape(k)}</td>'
        f'<td style="padding:10px;border-bottom:1px solid #e2e8f0;font-weight:700">{html.escape(str(v) or "—")}</td></tr>'
        for k, v in rows
    )
    email_html = _base_email("Setup help requested", "Onboarding", f'<p style="margin:0 0 14px">A customer asked the Arevei team to set up their AI Manager.</p><table role="presentation" style="width:100%;border-collapse:collapse;font-size:14px">{table}</table>')
    for recipient in {ASSIST_EMAIL, admin_notify_email()}:
        if recipient:
            try:
                send_email_background(recipient, "Arevei setup help requested", email_html)
            except Exception:
                logger.exception("Failed to queue assist email")
    await db.onboarding_assist_requests.insert_one({
        "user_id": str(user["_id"]), "workspace_id": body.workspace_id, "phone": body.phone,
        "preferred_time": body.preferred_time, "note": body.note, "created_at": now_iso(), "status": "new",
    })
    result = await _set_user_onboarding(db, user, {"assisted_requested_at": now_iso()})
    return {**result, "contact": CONTACT}


# ---------------------------------------------------------------- interview
def _money(ws):
    return (ws.get("currency") or "INR").upper()


def questions_for(ws, role):
    broker = role == "real_estate_broker"
    currency = _money(ws)
    name = ws.get("name") if ws.get("name") and not str(ws.get("name")).startswith("http") else "your business"
    return [
        {"key": "organisation", "label": "Business", "type": "text", "required": True,
         "text": f"Let's start simple. In a sentence or two, what does {name} do?",
         "placeholder": "e.g. We sell premium 3 & 4 BHK apartments in Pune" if broker else "e.g. We help D2C brands grow with performance marketing"},
        {"key": "offerings", "label": "Offers", "type": "text", "required": True,
         "text": "Which projects or properties are you selling right now, and at what price ranges?" if broker else "What products or services do you sell, and roughly what do they cost?",
         "placeholder": "e.g. Green Valley 2BHK ₹65L–80L, 3BHK ₹1.1Cr" if broker else "e.g. Monthly retainer ₹50k–1.5L, one-time audit ₹25k"},
        {"key": "ideal_customer", "label": "Ideal customer", "type": "text", "required": True,
         "text": "Who is your ideal buyer? Think budget, location and what they care about most." if broker else "Who is your ideal customer? Describe who buys from you and why.",
         "placeholder": "e.g. IT professionals, 30–45, upgrading from rented homes"},
        {"key": "lead_sources", "label": "Lead sources", "type": "multi", "required": False,
         "text": "Where do your leads come from today? Pick all that apply.",
         "chips": (["Meta / Instagram ads", "Google ads", "Property portals", "Website", "Referrals", "Walk-ins / site visits", "Channel partners"] if broker
                   else ["Meta / Instagram ads", "Google ads", "Website", "Referrals", "LinkedIn", "WhatsApp", "Events"])},
        {"key": "team_capacity", "label": "Team", "type": "choice", "required": True,
         "text": "How big is your sales team?",
         "chips": ["Just me", "2–5 people", "6–20 people", "20+ people"], "allow_text": True},
        {"key": "monthly_revenue_target", "label": "Revenue target", "type": "number", "required": True,
         "text": f"What monthly revenue are you aiming for (in {currency})? A rough number is fine.",
         "chips": (["10 lakh", "25 lakh", "50 lakh", "1 crore"] if currency == "INR" else ["10k", "50k", "100k", "500k"]),
         "placeholder": "e.g. 50 lakh"},
        {"key": "monthly_sales_budget", "label": "Budget", "type": "number", "required": False,
         "text": f"How much do you spend on sales and marketing each month (in {currency})?",
         "chips": (["Under 1 lakh", "1–3 lakh", "3–10 lakh", "10 lakh+"] if currency == "INR" else ["Under 5k", "5k–20k", "20k–50k", "50k+"])},
        {"key": "business_stage", "label": "Stage", "type": "choice", "required": True,
         "text": "Are you just getting started, or already selling regularly?",
         "chips": ["Just getting started", "Already selling"]},
        {"key": "offer_confidence", "label": "Offer fit", "type": "choice", "required": False,
         "text": "How confident are you that your offer sells?",
         "chips": ["Not sure yet", "Still testing", "Proven — customers buy regularly"]},
        {"key": "customer_feedback", "label": "Feedback", "type": "text", "required": False,
         "text": "What do customers usually say — why they buy, or why they don't?",
         "placeholder": "e.g. Love the location, but worry about possession dates"},
        {"key": "constraints", "label": "Constraints", "type": "text", "required": False,
         "text": "Last one: anything the AI should respect? Calling hours, regions, compliance, languages…",
         "placeholder": "e.g. Call only 10am–7pm IST, Hindi and English"},
    ]


CHOICE_VALUES = {
    "business_stage": {"just getting started": "starting", "starting": "starting", "already selling": "existing", "existing": "existing"},
    "offer_confidence": {"not sure yet": "unknown", "still testing": "testing", "proven — customers buy regularly": "validated", "proven": "validated"},
}
ACKS = ["Got it.", "Great, thanks.", "Perfect.", "Noted.", "Thanks — that helps.", "Nice.", "Understood."]
MULTIPLIERS = {"k": 1e3, "thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "l": 1e5,
               "cr": 1e7, "crore": 1e7, "crores": 1e7, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}


def parse_amount(text):
    """Parse '50 lakh', '1.2 Cr', '₹2,50,000', '50k', '3–10 lakh' (midpoint), 'under 1 lakh'."""
    s = str(text or "").lower().replace(",", "")
    nums = re.findall(r"(\d+(?:\.\d+)?)\s*([a-z]+)?", s)
    if not nums:
        return None
    unit_word = None
    for _, unit in reversed(nums):
        if unit and unit in MULTIPLIERS:
            unit_word = unit
            break
    values = []
    for number, unit in nums[:2]:
        mult = MULTIPLIERS.get(unit or "", None) or (MULTIPLIERS[unit_word] if unit_word else 1)
        values.append(float(number) * mult)
    if "under" in s or "below" in s or "less than" in s:
        return values[0] / 2
    return sum(values) / len(values)


def interpret(question, message):
    """Deterministically turn a reply into a SalesProfile value; None if not understood."""
    msg = (message or "").strip()
    if not msg:
        return None
    key, kind = question["key"], question["type"]
    if kind == "number":
        value = parse_amount(msg)
        return round(value, 2) if value is not None and value >= 0 else None
    if key in CHOICE_VALUES:
        low = msg.lower()
        for phrase, value in CHOICE_VALUES[key].items():
            if low == phrase or low.startswith(phrase):
                return value
        if any(w in low for w in ("start", "new", "launch", "early")):
            return "starting"
        if any(w in low for w in ("already", "existing", "established", "selling", "years")):
            return "existing"
        if key == "offer_confidence":
            if "test" in low: return "testing"
            if any(w in low for w in ("proven", "validated", "regular", "confident")): return "validated"
            return "unknown"
        return None
    return msg[:5000]


def looks_like_question(message):
    msg = (message or "").strip().lower()
    return msg.endswith("?") and len(msg.split()) > 2 or msg.startswith(("what is", "what's", "how do", "how does", "why ", "can you", "what can"))


def interview_state(ws):
    return ws.get("onboarding_interview") or {"answers": {}, "skipped": [], "index": 0, "transcript": []}


def prefill(ws, key):
    profile = (ws.get("brain") or {}).get("business_profile") or {}
    if key == "organisation":
        return profile.get("one_liner") or profile.get("summary") or profile.get("description") or ""
    if key == "offerings":
        offers = profile.get("offerings") or profile.get("products") or profile.get("services") or ""
        if isinstance(offers, list):
            offers = ", ".join(str(o.get("name") if isinstance(o, dict) else o) for o in offers[:8])
        return str(offers or "")
    if key == "ideal_customer":
        audience = (ws.get("brain") or {}).get("audience") or {}
        if isinstance(audience, dict):
            return str(audience.get("primary") or audience.get("summary") or audience.get("segments") or "")[:600]
    return ""


def public_question(ws, q):
    out = {k: v for k, v in q.items()}
    suggestion = prefill(ws, q["key"])
    if suggestion and ws.get("brain_status") == "ready":
        out["suggestion"] = str(suggestion)[:600]
    return out


def state_out(ws, role, replies=None):
    questions = questions_for(ws, role)
    state = interview_state(ws)
    index = min(state.get("index", 0), len(questions))
    remaining = max(len(questions) - index, 0)
    current = public_question(ws, questions[index]) if index < len(questions) else None
    return {
        "questions": [{"key": q["key"], "label": q["label"], "required": q["required"]} for q in questions],
        "current": current,
        "index": index,
        "total": len(questions),
        "answers": state.get("answers", {}),
        "skipped": state.get("skipped", []),
        "transcript": state.get("transcript", [])[-60:],
        "eta_seconds": remaining * SECONDS_PER_QUESTION,
        "done": current is None,
        "brain_status": ws.get("brain_status"),
        "strategy_status": ws.get("strategy_status") or ("ready" if ws.get("sales_strategy") else None),
        "replies": replies or [],
        "contact": CONTACT,
    }


async def answer_product_question(ws, message):
    import product_knowledge
    docs = product_knowledge.search(message, limit=2)
    context = product_knowledge.as_text(docs, 2200) if docs else ""
    try:
        import llm_service
        from ai_usage import usage_scope
        with usage_scope(str(ws["_id"]), "onboarding_interview"):
            text = await llm_service.generate_text(
                ws.get("model_id"),
                "You are Arevei's friendly onboarding guide. Answer the user's question in 2-4 short sentences using ONLY "
                "the product guide. Mention where in the app to find it. If the guide doesn't cover it, say the Arevei team "
                "can help at admin@arevei.com. No markdown headings.",
                f"Product guide:\n{context or '(no matching section)'}\n\nQuestion: {message}",
                temperature=0.3, max_tokens=300,
            )
        if text and text.strip():
            return text.strip()
    except Exception:
        logger.warning("Onboarding product answer failed", exc_info=True)
    if docs:
        return docs[0]["sections"].get("What it does", "") + " " + docs[0]["sections"].get("Why it matters", "")
    return "Good question — the Arevei team can walk you through it at admin@arevei.com."


async def interview_access(request, ws_id):
    db = _db(request)
    user, ws = await get_current_user_and_workspace(request, db, ws_id)
    return db, user, ws


@router.get("/workspaces/{ws_id}/onboarding/interview")
async def get_interview(ws_id: str, request: Request):
    _, user, ws = await interview_access(request, ws_id)
    db = _db(request)
    role = (user.get("onboarding") or {}).get("role")
    state = interview_state(ws)
    if not state.get("transcript"):
        questions = questions_for(ws, role)
        first = (user.get("name") or "").split(" ")[0]
        intro = (f"Hi{(' ' + first) if first else ''}! I'm your AI Manager. I'll ask {len(questions)} quick questions about your "
                 "business and sales goals so I can build your sales strategy. Skip anything you're not sure about — "
                 "and feel free to ask me what Arevei can do at any point.")
        state = {"answers": {}, "skipped": [], "index": 0, "started_at": now_iso(), "updated_at": now_iso(), "transcript": [
            {"role": "assistant", "text": intro, "at": now_iso()},
            {"role": "assistant", "text": questions[0]["text"], "at": now_iso(), "key": questions[0]["key"]},
        ]}
        await db.workspaces.update_one({"_id": ws["_id"]}, {"$set": {"onboarding_interview": state}})
        ws["onboarding_interview"] = state
    return state_out(ws, role)


class AnswerInput(BaseModel):
    message: str = Field(default="", max_length=5000)
    skip: bool = False
    skip_all: bool = False


@router.post("/workspaces/{ws_id}/onboarding/interview/answer")
async def answer(ws_id: str, request: Request, body: AnswerInput):
    db, user, ws = await interview_access(request, ws_id)
    role = (user.get("onboarding") or {}).get("role")
    questions = questions_for(ws, role)
    state = interview_state(ws)
    state.setdefault("answers", {}); state.setdefault("skipped", []); state.setdefault("transcript", [])
    index = state.get("index", 0)
    replies = []

    def say(text, key=None):
        item = {"role": "assistant", "text": text, "at": now_iso()}
        if key: item["key"] = key
        state["transcript"].append(item); replies.append(item)

    def ask_current():
        if state["index"] < len(questions):
            q = questions[state["index"]]
            say(q["text"], q["key"])
        else:
            say("That's everything I need! Review your answers below, edit anything, then build your strategy.")

    if index >= len(questions):
        return state_out(ws, role)
    q = questions[index]
    if body.skip_all:
        state["transcript"].append({"role": "user", "text": "Skip the rest", "at": now_iso()})
        for rest in questions[index:]:
            if rest["key"] not in state["answers"] and rest["key"] not in state["skipped"]:
                state["skipped"].append(rest["key"])
        state["index"] = len(questions)
        say("No problem — you can fill in the rest anytime from Brain → Sales strategy.")
        ask_current()
    elif body.skip:
        state["transcript"].append({"role": "user", "text": "Skip", "at": now_iso()})
        if q["key"] not in state["skipped"]:
            state["skipped"].append(q["key"])
        state["index"] = index + 1
        say("Skipped — we can come back to it later.")
        ask_current()
    else:
        message = body.message.strip()
        if not message:
            raise HTTPException(422, "Type an answer, pick an option, or skip")
        state["transcript"].append({"role": "user", "text": message, "at": now_iso()})
        if looks_like_question(message) and q["type"] in {"text", "choice", "multi"} and message not in q.get("chips", []):
            say(await answer_product_question(ws, message))
            say(f"Back to setup — {q['text'][0].lower() + q['text'][1:]}", q["key"])
        else:
            value = interpret(q, message)
            if value is None:
                hint = "a number like 50 lakh or 2 crore" if q["type"] == "number" else "one of the options"
                say(f"Sorry, I didn't catch that. Could you give me {hint}? You can also skip this one.", q["key"])
            else:
                state["answers"][q["key"]] = value
                if q["key"] in state["skipped"]:
                    state["skipped"].remove(q["key"])
                state["index"] = index + 1
                say(ACKS[index % len(ACKS)])
                ask_current()
    state["updated_at"] = now_iso()
    state.setdefault("started_at", now_iso())
    state["transcript"] = state["transcript"][-120:]
    await db.workspaces.update_one({"_id": ws["_id"]}, {"$set": {"onboarding_interview": state}})
    ws["onboarding_interview"] = state
    return state_out(ws, role, replies)


@router.post("/workspaces/{ws_id}/onboarding/interview/restart")
async def restart(ws_id: str, request: Request):
    db, user, ws = await interview_access(request, ws_id)
    await db.workspaces.update_one({"_id": ws["_id"]}, {"$unset": {"onboarding_interview": ""}})
    ws.pop("onboarding_interview", None)
    return await get_interview(ws_id, request)


class FinishInput(BaseModel):
    answers: dict = Field(default_factory=dict)
    timezone: str = "UTC"
    morning_hour: int = Field(default=8, ge=0, le=23)


def starter_brain(ws, profile):
    """A minimal Brain built from interview answers for workspaces without a website."""
    return {
        "business_profile": {"company_name": ws.get("name") or profile.get("organisation", "")[:80],
                             "summary": profile.get("organisation", ""), "offerings": profile.get("offerings", ""),
                             "source": "onboarding_interview"},
        "audience": {"primary": profile.get("ideal_customer", "")},
        "goals_constraints": {"monthly_revenue_target": profile.get("monthly_revenue_target"), "constraints": profile.get("constraints", "")},
        "organization": {}, "brand_identity": {}, "evidence": [], "decision_memory": [],
    }


async def run_strategy_background(db, ws_id):
    from sales_leadership import sales_strategy
    try:
        ws = await db.workspaces.find_one({"_id": ObjectId(ws_id)})
        await db.workspaces.update_one({"_id": ws["_id"]}, {"$set": {"strategy_status": "building"}, "$unset": {"strategy_pending": ""}})
        await sales_strategy(db, ws)
        await db.workspaces.update_one({"_id": ws["_id"]}, {"$set": {"strategy_status": "ready"}})
        await db.notifications.insert_one({"workspace_id": ws_id, "kind": "success", "title": "Sales strategy ready",
                                           "body": "Your AI Manager prepared your month-by-month sales plan.", "read": False, "created_at": now_iso()})
    except Exception as exc:
        logger.exception("Onboarding strategy build failed workspace=%s", ws_id)
        await db.workspaces.update_one({"_id": ObjectId(ws_id)}, {"$set": {"strategy_status": "error", "strategy_error": str(getattr(exc, "detail", exc))[:300]}})


async def run_pending_strategy(db, ws_id):
    """Called after Brain training finishes; builds a strategy queued during onboarding."""
    ws = await db.workspaces.find_one({"_id": ObjectId(ws_id)}, {"strategy_pending": 1})
    if ws and ws.get("strategy_pending"):
        await run_strategy_background(db, ws_id)


@router.post("/workspaces/{ws_id}/onboarding/interview/complete")
async def finish(ws_id: str, request: Request, body: FinishInput):
    from sales_leadership import SalesProfile
    db, user, ws = await interview_access(request, ws_id)
    state = interview_state(ws)
    answers = {**state.get("answers", {}), **{k: v for k, v in body.answers.items() if v not in (None, "")}}
    for key in ("monthly_revenue_target", "monthly_sales_budget"):
        if key in answers and not isinstance(answers[key], (int, float)):
            answers[key] = parse_amount(answers[key])
    for key in ("business_stage", "offer_confidence"):
        if key in answers and answers[key] not in {"starting", "existing", "unknown", "testing", "validated"}:
            answers[key] = interpret({"key": key, "type": "choice"}, str(answers[key]))
    if isinstance(answers.get("lead_sources"), list):
        answers["lead_sources"] = ", ".join(answers["lead_sources"])
    existing = ws.get("sales_profile") or {}
    candidate = {**existing, **{k: v for k, v in answers.items() if v is not None},
                 "timezone": body.timezone, "morning_hour": body.morning_hour}
    candidate.setdefault("monthly_sales_budget", 0)
    try:
        profile = SalesProfile(**candidate).model_dump()
    except ValidationError as exc:
        labels = {q["key"]: q["label"] for q in questions_for(ws, (user.get("onboarding") or {}).get("role"))}
        missing = sorted({str(err["loc"][0]) for err in exc.errors() if err.get("loc")})
        raise HTTPException(422, {"message": "A few answers are needed to build your strategy.",
                                  "missing": missing, "labels": [labels.get(k, k) for k in missing]})
    updates = {"sales_profile": profile, "onboarding_interview.completed_at": now_iso()}
    if ws.get("brain_status") in (None, "pending", "error") and not ws.get("brain"):
        updates.update({"brain": starter_brain(ws, profile), "brain_status": "ready"})
        ws["brain_status"] = "ready"
    await db.workspaces.update_one({"_id": ws["_id"]}, {"$set": updates, "$unset": {"sales_review_day": ""}})
    if ws.get("brain_status") == "ready":
        await db.workspaces.update_one({"_id": ws["_id"]}, {"$set": {"strategy_status": "building"}})
        asyncio.create_task(run_strategy_background(db, ws_id))
        status = "building"
    else:
        await db.workspaces.update_one({"_id": ws["_id"]}, {"$set": {"strategy_pending": True, "strategy_status": "waiting_for_brain"}})
        status = "waiting_for_brain"
    return {"sales_profile": profile, "strategy_status": status}


# ---------------------------------------------------------------- setup checklist
@router.get("/workspaces/{ws_id}/onboarding/checklist")
async def checklist(ws_id: str, request: Request):
    db, _, ws = await interview_access(request, ws_id)
    voice, sms, form, ads, lead = await asyncio.gather(
        db.workspace_voice_provider_configs.find_one({"workspace_id": ws_id, "enabled": True}, {"_id": 1}),
        db.workspace_sms_configs.find_one({"workspace_id": ws_id, "enabled": True}, {"_id": 1}),
        db.lead_forms.find_one({"workspace_id": ws_id, "status": "active"}, {"_id": 1}),
        db.workflows.find_one({"workspace_id": ws_id, "kind": "ads_to_crm", "status": "published"}, {"_id": 1}),
        db.crm_leads.find_one({"workspace_id": ws_id, "deleted_at": None, "is_test_lead": {"$ne": True}}, {"_id": 1}),
    )
    base = f"/app/w/{ws_id}"
    items = [
        {"key": "brain", "title": "Train your Business Brain", "description": "So every AI answer sounds like your business.",
         "done": ws.get("brain_status") == "ready", "href": f"{base}/brain", "minutes": 2},
        {"key": "strategy", "title": "Build your sales strategy", "description": "A month-by-month plan tied to your revenue target.",
         "done": bool(ws.get("sales_strategy")), "href": f"{base}/setup", "minutes": 6},
        {"key": "voice", "title": "Connect the voice agent", "description": "Call every new lead within minutes, day or night.",
         "done": bool(voice), "href": f"{base}/settings#voice", "minutes": 5},
        {"key": "lead_source", "title": "Connect a lead source", "description": "Landing page forms or Meta lead ads straight into your CRM.",
         "done": bool(form or ads), "href": f"{base}/workflows/landing-forms", "minutes": 3},
        {"key": "sms", "title": "Enable SMS", "description": "Reach leads who don't pick up the phone.",
         "done": bool(sms), "href": f"{base}/settings#sms", "minutes": 3},
        {"key": "first_lead", "title": "Get your first lead", "description": "Send a test from a form or add one in the CRM.",
         "done": bool(lead), "href": f"{base}/crm", "minutes": 1},
    ]
    done = sum(1 for item in items if item["done"])
    next_item = next((item for item in items if not item["done"]), None)
    return {"items": items, "done": done, "total": len(items), "next": next_item, "contact": CONTACT}


@router.get("/product-help")
async def product_help(request: Request, q: str = "", slug: str = ""):
    await get_current_user(request, _db(request))
    import product_knowledge
    if slug:
        doc = product_knowledge.get(slug)
        if not doc:
            raise HTTPException(404, "Guide not found")
        return doc
    if q:
        return {"results": product_knowledge.search(q, limit=3)}
    return {"features": product_knowledge.catalog()}
