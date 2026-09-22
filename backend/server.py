import os
import asyncio
import logging
import random
import importlib.util
import time
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env", override=True)

from fastapi import FastAPI, APIRouter, Request, HTTPException, Response, Body
from fastapi.responses import StreamingResponse, PlainTextResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

from models import Workspace, Task, Blog, Notification, BLOG_IMAGE_POOL, now_iso
from auth import build_auth_router, get_current_user, seed_admin
from coding import build_coding_router
import agents
import llm_service
from ai_usage import configure_usage, usage_scope
from manager_service import ManagerService
from manager_voice import build_voice_router, initialize_voice_storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("server")

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
configure_usage(db)

app = FastAPI(title="Arevei AI Manager")
api = APIRouter(prefix="/api")
PUBLIC_BLOG_RATE = {}
PUBLIC_BLOG_RATE_LIMIT = 120
PUBLIC_BLOG_RATE_WINDOW = 60


def oid(v):
    return ObjectId(v)


def doc_out(doc):
    if not doc:
        return None
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


def workspace_out(doc):
    result = doc_out(doc)
    if result is None:
        return None
    from workspace_modules import workspace_currency, workspace_modules
    result["modules"] = workspace_modules(doc)
    result["currency"] = workspace_currency(doc)
    return result


async def require_user(request: Request):
    return await get_current_user(request, db)


async def owned_workspace(ws_id, user):
    ws = await db.workspaces.find_one({"_id": oid(ws_id)})
    if not ws:
        raise HTTPException(404, "Workspace not found")
    if str(ws["user_id"]) != str(user["_id"]) and user.get("role") != "admin":
        raise HTTPException(403, "Forbidden")
    return ws


async def notify(ws_id, kind, title, body=""):
    n = Notification(workspace_id=str(ws_id), kind=kind, title=title, body=body)
    await db.notifications.insert_one(n.to_mongo())


async def unique_slug(base):
    slug = base
    i = 1
    while await db.blogs.find_one({"slug": slug}):
        i += 1
        slug = f"{base}-{i}"
    return slug


def _normalize_origin(value):
    if not value:
        return ""
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return value.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _request_origin(request):
    return _normalize_origin(request.headers.get("origin") or request.headers.get("referer") or "")


def _clean_origins(origins):
    if not isinstance(origins, list):
        return []
    cleaned = []
    for origin in origins:
        value = _normalize_origin(str(origin).strip())
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned[:25]


def _assert_blog_origin_allowed(ws, request):
    allowed = ws.get("allowed_blog_origins") or []
    seen_origin = _request_origin(request)
    if allowed and seen_origin and seen_origin not in allowed:
        raise HTTPException(403, "This origin is not allowed to read this workspace's published blogs")


def _assert_public_blog_rate(ws, request):
    key = ws.get("public_key") or str(ws.get("_id"))
    host = request.client.host if request.client else "unknown"
    bucket_key = f"{key}:{host}"
    now = time.monotonic()
    bucket = [ts for ts in PUBLIC_BLOG_RATE.get(bucket_key, []) if now - ts < PUBLIC_BLOG_RATE_WINDOW]
    if len(bucket) >= PUBLIC_BLOG_RATE_LIMIT:
        raise HTTPException(429, "Too many public blog requests")
    bucket.append(now)
    PUBLIC_BLOG_RATE[bucket_key] = bucket


def _public_blog_list_item(doc):
    return {
        "title": doc.get("title", ""),
        "slug": doc.get("slug", ""),
        "excerpt": doc.get("excerpt", ""),
        "hero_image": doc.get("hero_image", ""),
        "read_time": doc.get("read_time", ""),
        "tags": doc.get("tags", []),
        "published_at": doc.get("published_at"),
    }


def _public_blog_detail(doc, ws):
    return {
        **_public_blog_list_item(doc),
        "author": doc.get("author", ""),
        "blocks": doc.get("blocks", []),
        "content_html": doc.get("content_html", ""),
        "meta_title": doc.get("meta_title", ""),
        "meta_description": doc.get("meta_description", ""),
        "workspace_name": ws.get("name") if ws else "",
        "workspace_url": ws.get("website_url") if ws else "",
    }


# ---------------- MODELS ----------------
@api.get("/models")
async def list_models():
    def has_python_package(name):
        return importlib.util.find_spec(name) is not None

    def provider_status(provider):
        if provider == "bedrock_mantle":
            ok = bool(llm_service.mantle_config()["key"])
            return {"configured": ok, "reason": "" if ok else "BEDROCK_MANTLE_API_KEY or AWS_BEARER_TOKEN_BEDROCK is missing"}
        if provider == "bedrock":
            has_creds = bool(os.environ.get("AWS_BEARER_TOKEN_BEDROCK") or os.environ.get("AWS_ACCESS_KEY_ID"))
            has_boto3 = has_python_package("boto3")
            reason = ""
            if not has_boto3:
                reason = "boto3 is missing in the backend Python environment"
            elif not has_creds:
                reason = "AWS_BEARER_TOKEN_BEDROCK or AWS_ACCESS_KEY_ID is missing"
            return {"configured": has_boto3 and has_creds, "reason": reason}
        if provider == "openrouter":
            ok = bool(os.environ.get("OPENROUTER_API_KEY"))
            return {"configured": ok, "reason": "" if ok else "OPENROUTER_API_KEY is missing"}
        if provider == "nvidia":
            ok = bool(os.environ.get("NVIDIA_NIM_API_KEY"))
            return {"configured": ok, "reason": "" if ok else "NVIDIA_NIM_API_KEY is missing"}
        return {"configured": False, "reason": "Unknown provider"}

    visible_models = [m for m in llm_service.MODELS if m.get("provider") != "bedrock"]
    statuses = {provider: provider_status(provider) for provider in ("openrouter", "nvidia")}
    models = [{**m, **provider_status(m.get("provider"))} for m in visible_models]
    return {"models": models, "default": llm_service.DEFAULT_MODEL,
            "providers": {
                "bedrock_mantle": {**provider_status("bedrock_mantle"), "env": "BEDROCK_MANTLE_API_KEY (or AWS_BEARER_TOKEN_BEDROCK)"},
                "openrouter": {**statuses["openrouter"], "env": "OPENROUTER_API_KEY"},
                "nvidia": {**statuses["nvidia"], "env": "NVIDIA_NIM_API_KEY"},
            }}


# ---------------- WORKSPACES ----------------
async def _build_brain_bg(ws_id, url, model_id):
    from crawler import crawl_site
    try:
        await db.workspaces.update_one({"_id": oid(ws_id)}, {"$set": {"brain_status": "building"}})
        crawl = await crawl_site(url)
        if crawl.get("page_count", 0) == 0:
            raise ValueError(f"No readable pages found while crawling {url}. The site may block crawlers or return no HTML content.")
        with usage_scope(ws_id, "brain_training"):
            brain = await agents.build_brain(model_id, crawl)
        name = brain.get("business_profile", {}).get("company_name") or url
        await db.workspaces.update_one({"_id": oid(ws_id)},
                                       {"$set": {"brain": brain, "brain_status": "ready", "name": name}})
        await notify(ws_id, "success", "Brain trained", f"Analysed {crawl['page_count']} pages from {url}.")
    except Exception as e:
        logger.exception("brain build failed")
        await db.workspaces.update_one({"_id": oid(ws_id)}, {"$set": {"brain_status": "error"}})
        await notify(ws_id, "error", "Brain training failed", str(e)[:200])


@api.post("/workspaces")
async def create_workspace(request: Request, body: dict = Body(...)):
    user = await require_user(request)
    url = (body.get("website_url") or "").strip()
    if not url:
        raise HTTPException(400, "website_url required")
    model_id = body.get("model_id") or llm_service.DEFAULT_MODEL
    ws = Workspace(user_id=str(user["_id"]), name=body.get("name") or url,
                   website_url=url, public_key=os.urandom(8).hex(), model_id=model_id,
                   brain_status="building")
    res = await db.workspaces.insert_one(ws.to_mongo())
    ws_id = str(res.inserted_id)
    asyncio.create_task(_build_brain_bg(ws_id, url, model_id))
    doc = await db.workspaces.find_one({"_id": res.inserted_id})
    return workspace_out(doc)


@api.get("/workspaces")
async def list_workspaces(request: Request):
    user = await require_user(request)
    docs = await db.workspaces.find({"user_id": str(user["_id"])}).sort("created_at", -1).to_list(100)
    return [workspace_out(d) for d in docs]


@api.get("/workspaces/{ws_id}")
async def get_workspace(ws_id: str, request: Request):
    user = await require_user(request)
    ws = await owned_workspace(ws_id, user)
    return workspace_out(ws)


@api.patch("/workspaces/{ws_id}")
async def update_workspace(ws_id: str, request: Request, body: dict = Body(...)):
    user = await require_user(request)
    await owned_workspace(ws_id, user)
    updates = {k: v for k, v in body.items() if k in ("model_id", "name", "ai_qualification_config")}
    if "modules" in body:
        from workspace_modules import clean_modules
        updates["modules"] = clean_modules(body["modules"])
    if "currency" in body:
        from workspace_modules import clean_currency
        updates["currency"] = clean_currency(body["currency"])
    if "allowed_blog_origins" in body:
        updates["allowed_blog_origins"] = _clean_origins(body.get("allowed_blog_origins"))
    if updates:
        await db.workspaces.update_one({"_id": oid(ws_id)}, {"$set": updates})
    doc = await db.workspaces.find_one({"_id": oid(ws_id)})
    return workspace_out(doc)


@api.post("/workspaces/{ws_id}/public-key/rotate")
async def rotate_public_key(ws_id: str, request: Request):
    user = await require_user(request)
    await owned_workspace(ws_id, user)
    new_key = os.urandom(8).hex()
    await db.workspaces.update_one({"_id": oid(ws_id)}, {"$set": {"public_key": new_key}})
    doc = await db.workspaces.find_one({"_id": oid(ws_id)})
    await notify(ws_id, "info", "Publishable blog key rotated", "Update any external blog integrations with the new key.")
    return workspace_out(doc)


@api.post("/workspaces/{ws_id}/rebrain")
async def rebrain(ws_id: str, request: Request):
    user = await require_user(request)
    ws = await owned_workspace(ws_id, user)
    asyncio.create_task(_build_brain_bg(ws_id, ws["website_url"], ws.get("model_id")))
    return {"ok": True}


@api.put("/workspaces/{ws_id}/brain")
async def edit_brain(ws_id: str, request: Request, body: dict = Body(...)):
    user = await require_user(request)
    await owned_workspace(ws_id, user)
    await db.workspaces.update_one({"_id": oid(ws_id)}, {"$set": {"brain": body.get("brain", {})}})
    doc = await db.workspaces.find_one({"_id": oid(ws_id)})
    return doc_out(doc)


# ---------------- ROADMAP + TASKS ----------------
@api.post("/workspaces/{ws_id}/roadmap")
async def gen_roadmap(ws_id: str, request: Request):
    user = await require_user(request)
    ws = await owned_workspace(ws_id, user)
    if ws.get("brain_status") != "ready":
        raise HTTPException(400, "Brain is not ready yet")
    model_id = ws.get("model_id")
    brain = ws.get("brain", {})
    with usage_scope(ws_id, "roadmap_strategy"):
        roadmap = await agents.build_roadmap(model_id, brain)
    await db.workspaces.update_one({"_id": oid(ws_id)}, {"$set": {"roadmap": roadmap.get("months", []),
                                                                   "strategy_summary": roadmap.get("strategy_summary", "")}})
    # generate + schedule tasks
    with usage_scope(ws_id, "roadmap_tasks"):
        raw_tasks = await agents.generate_tasks(model_id, brain, roadmap, count=8)
    await db.tasks.delete_many({"workspace_id": ws_id, "status": "pending"})
    now = datetime.now(timezone.utc)
    auto_count = 0
    for i, t in enumerate(raw_tasks):
        is_content = t.get("agent") == "content"
        # first few content tasks auto-run soon to showcase automation
        auto = is_content and auto_count < 3
        if auto:
            sched = now + timedelta(seconds=20 + auto_count * 40)
            requires_approval = False
            auto_count += 1
        else:
            sched = now + timedelta(days=i)
            requires_approval = True
        task = Task(workspace_id=ws_id, title=t.get("title", "Untitled task"),
                    objective=t.get("objective", ""), agent=t.get("agent", "content"),
                    deliverable_type=t.get("deliverable_type", "blog_post"),
                    success_criteria=t.get("success_criteria", ""),
                    month_number=int(t.get("month_number", 1) or 1),
                    requires_approval=bool(requires_approval),
                    scheduled_time=sched.isoformat())
        await db.tasks.insert_one(task.to_mongo())
    await notify(ws_id, "info", "Roadmap generated", f"{len(raw_tasks)} tasks scheduled across your 12-month plan.")
    doc = await db.workspaces.find_one({"_id": oid(ws_id)})
    return doc_out(doc)


@api.get("/workspaces/{ws_id}/tasks")
async def list_tasks(ws_id: str, request: Request):
    user = await require_user(request)
    await owned_workspace(ws_id, user)
    docs = await db.tasks.find({"workspace_id": ws_id}).sort("scheduled_time", 1).to_list(200)
    return [doc_out(d) for d in docs]


async def execute_task(task_doc):
    """Run a task through its specialist agent."""
    if task_doc.get("source") in {"qualification_engine", "crm_reminder"}:
        raise HTTPException(409, "This is a human follow-up task. Complete the action in CRM and mark it done.")
    ws = await db.workspaces.find_one({"_id": oid(task_doc["workspace_id"])})
    if not ws:
        return
    model_id = ws.get("model_id")
    brain = ws.get("brain", {})
    ws_id = task_doc["workspace_id"]
    tid = task_doc["_id"]
    await db.tasks.update_one({"_id": tid}, {"$set": {"status": "running"}})
    try:
        process = {"blog_post": "blog_generation", "seo_audit": "seo_audit", "social_post_pack": "creative_content", "image_set": "creative_content"}.get(task_doc.get("deliverable_type"), "analytics_task")
        with usage_scope(ws_id, process, {"task_id": str(tid)}):
            if task_doc.get("agent") == "content" and task_doc.get("deliverable_type") == "blog_post":
                data = await agents.write_blog(model_id, brain, task_doc["title"], task_doc.get("objective", ""))
            elif task_doc.get("agent") == "seo" or task_doc.get("deliverable_type") == "seo_audit":
                data = await agents.write_seo_audit(model_id, brain, task_doc["title"], task_doc.get("objective", ""))
            elif task_doc.get("agent") == "creative" or task_doc.get("deliverable_type") in {"social_post_pack", "image_set"}:
                data = await agents.write_social_post_pack(model_id, brain, task_doc["title"], task_doc.get("objective", ""))
            else:
                data = await llm_service.generate_text(model_id, f"You are the AREVEI {task_doc.get('agent')} agent.", f"Task: {task_doc['title']}\nObjective: {task_doc.get('objective','')}\nProduce a concise, actionable deliverable (bullet points).", max_tokens=1200)
        if task_doc.get("agent") == "content" and task_doc.get("deliverable_type") == "blog_post":
            title = data.get("title", task_doc["title"])
            slug = await unique_slug(agents.slugify(title))
            publish = not task_doc.get("requires_approval", False)
            blog = Blog(workspace_id=ws_id, title=title, slug=slug,
                        excerpt=data.get("excerpt", ""), hero_image=random.choice(BLOG_IMAGE_POOL),
                        read_time=data.get("read_time", "5 min read"), tags=data.get("tags", []),
                        blocks=data.get("blocks", []), meta_title=data.get("meta_title", title),
                        meta_description=data.get("meta_description", ""), keywords=data.get("keywords", []),
                        status="published" if publish else "draft",
                        generated_by=model_id,
                        published_at=now_iso() if publish else None)
            res = await db.blogs.insert_one(blog.to_mongo())
            blog_id = str(res.inserted_id)
            if publish:
                await db.tasks.update_one({"_id": tid}, {"$set": {"status": "done", "output_ref": blog_id,
                                                                  "output_summary": f"Published blog: {title}"}})
                await notify(ws_id, "success", "Blog auto-published", title)
            else:
                await db.tasks.update_one({"_id": tid}, {"$set": {"status": "awaiting_approval", "output_ref": blog_id,
                                                                  "output_summary": f"Draft ready: {title}"}})
                await notify(ws_id, "approval", "Blog draft awaiting approval", title)
        elif task_doc.get("agent") == "seo" or task_doc.get("deliverable_type") == "seo_audit":
            payload = data
            summary = payload.get("summary") or f"SEO audit ready: {task_doc['title']}"
            await db.tasks.update_one({"_id": tid}, {"$set": {
                "status": "done",
                "deliverable_type": "seo_audit",
                "output_summary": summary[:4000],
                "output_payload": payload,
            }})
            await notify(ws_id, "success", "SEO audit ready", task_doc["title"])
        elif task_doc.get("agent") == "creative" or task_doc.get("deliverable_type") in {"social_post_pack", "image_set"}:
            payload = data
            summary = payload.get("summary") or f"Social drafts ready: {task_doc['title']}"
            await db.tasks.update_one({"_id": tid}, {"$set": {
                "status": "done",
                "deliverable_type": "social_post_pack",
                "output_summary": summary[:4000],
                "output_payload": payload,
            }})
            await notify(ws_id, "success", "Creative drafts ready", task_doc["title"])
        else:
            summary = data
            await db.tasks.update_one({"_id": tid}, {"$set": {
                "status": "done",
                "output_summary": summary[:4000],
                "output_payload": {},
            }})
            await notify(ws_id, "success", f"{task_doc.get('agent','agent').title()} task done", task_doc["title"])
    except Exception as e:
        logger.exception("task execution failed")
        await db.tasks.update_one({"_id": tid}, {"$set": {"status": "failed", "output_summary": str(e)[:300]}})
        await notify(ws_id, "error", "Task failed", task_doc["title"])


@api.post("/tasks/{task_id}/run")
async def run_task(task_id: str, request: Request):
    user = await require_user(request)
    task = await db.tasks.find_one({"_id": oid(task_id)})
    if not task:
        raise HTTPException(404, "Task not found")
    await owned_workspace(task["workspace_id"], user)
    await execute_task(task)
    doc = await db.tasks.find_one({"_id": oid(task_id)})
    return doc_out(doc)


@api.post("/tasks/{task_id}/approve")
async def approve_task(task_id: str, request: Request):
    user = await require_user(request)
    task = await db.tasks.find_one({"_id": oid(task_id)})
    if not task:
        raise HTTPException(404, "Task not found")
    await owned_workspace(task["workspace_id"], user)
    if task.get("output_ref"):
        await db.blogs.update_one({"_id": oid(task["output_ref"])},
                                  {"$set": {"status": "published", "published_at": now_iso()}})
    await db.tasks.update_one({"_id": oid(task_id)}, {"$set": {"status": "done"}})
    await notify(task["workspace_id"], "success", "Follow-up completed" if task.get("source") == "qualification_engine" else "Approved & published", task["title"])
    doc = await db.tasks.find_one({"_id": oid(task_id)})
    return doc_out(doc)


@api.delete("/tasks/{task_id}")
async def delete_task(task_id: str, request: Request):
    user = await require_user(request)
    task = await db.tasks.find_one({"_id": oid(task_id)})
    if not task:
        raise HTTPException(404, "Task not found")
    await owned_workspace(task["workspace_id"], user)
    await db.tasks.delete_one({"_id": oid(task_id)})
    return {"ok": True}


# ---------------- BLOGS ----------------
@api.get("/workspaces/{ws_id}/blogs")
async def list_blogs(ws_id: str, request: Request):
    user = await require_user(request)
    await owned_workspace(ws_id, user)
    docs = await db.blogs.find({"workspace_id": ws_id}).sort("created_at", -1).to_list(200)
    return [doc_out(d) for d in docs]


@api.post("/workspaces/{ws_id}/blogs/generate")
async def generate_blog(ws_id: str, request: Request, body: dict = Body(...)):
    user = await require_user(request)
    ws = await owned_workspace(ws_id, user)
    topic = (body.get("topic") or "").strip()
    if not topic:
        raise HTTPException(400, "topic required")
    model_id = body.get("model_id") or ws.get("model_id")
    with usage_scope(ws_id, "blog_generation"):
        data = await agents.write_blog(model_id, ws.get("brain", {}), topic, body.get("objective", ""))
    title = data.get("title", topic)
    slug = await unique_slug(agents.slugify(title))
    blog = Blog(workspace_id=ws_id, title=title, slug=slug, excerpt=data.get("excerpt", ""),
                hero_image=random.choice(BLOG_IMAGE_POOL), read_time=data.get("read_time", "5 min read"),
                tags=data.get("tags", []), blocks=data.get("blocks", []),
                meta_title=data.get("meta_title", title), meta_description=data.get("meta_description", ""),
                keywords=data.get("keywords", []), status="draft", generated_by=model_id)
    res = await db.blogs.insert_one(blog.to_mongo())
    doc = await db.blogs.find_one({"_id": res.inserted_id})
    return doc_out(doc)


@api.get("/blogs/{blog_id}")
async def get_blog(blog_id: str, request: Request):
    user = await require_user(request)
    blog = await db.blogs.find_one({"_id": oid(blog_id)})
    if not blog:
        raise HTTPException(404, "Blog not found")
    await owned_workspace(blog["workspace_id"], user)
    return doc_out(blog)


@api.put("/blogs/{blog_id}")
async def update_blog(blog_id: str, request: Request, body: dict = Body(...)):
    user = await require_user(request)
    blog = await db.blogs.find_one({"_id": oid(blog_id)})
    if not blog:
        raise HTTPException(404, "Blog not found")
    await owned_workspace(blog["workspace_id"], user)
    fields = ["title", "excerpt", "hero_image", "author", "read_time", "tags",
              "blocks", "content_html", "meta_title", "meta_description", "keywords", "status"]
    updates = {k: body[k] for k in fields if k in body}
    if updates:
        await db.blogs.update_one({"_id": oid(blog_id)}, {"$set": updates})
    doc = await db.blogs.find_one({"_id": oid(blog_id)})
    return doc_out(doc)


@api.post("/blogs/{blog_id}/publish")
async def publish_blog(blog_id: str, request: Request, body: dict = Body(None)):
    user = await require_user(request)
    blog = await db.blogs.find_one({"_id": oid(blog_id)})
    if not blog:
        raise HTTPException(404, "Blog not found")
    await owned_workspace(blog["workspace_id"], user)
    requested_status = (body or {}).get("status")
    new_status = requested_status if requested_status in {"draft", "published"} else ("draft" if blog.get("status") == "published" else "published")
    await db.blogs.update_one({"_id": oid(blog_id)},
                              {"$set": {"status": new_status,
                                        "published_at": now_iso() if new_status == "published" else None}})
    doc = await db.blogs.find_one({"_id": oid(blog_id)})
    return doc_out(doc)


@api.delete("/blogs/{blog_id}")
async def delete_blog(blog_id: str, request: Request):
    user = await require_user(request)
    blog = await db.blogs.find_one({"_id": oid(blog_id)})
    if not blog:
        raise HTTPException(404, "Blog not found")
    await owned_workspace(blog["workspace_id"], user)
    await db.blogs.delete_one({"_id": oid(blog_id)})
    return {"ok": True}


# ---------------- NOTIFICATIONS ----------------
@api.get("/workspaces/{ws_id}/notifications")
async def list_notifications(ws_id: str, request: Request):
    user = await require_user(request)
    await owned_workspace(ws_id, user)
    docs = await db.notifications.find({"workspace_id": ws_id}).sort("created_at", -1).to_list(50)
    return [doc_out(d) for d in docs]


async def crm_manager_context(ws_id):
    from crm import build_crm_analytics, decorate_lead, ensure_crm_settings, lead_query, money_value, purge_expired_trashed_leads

    settings = await ensure_crm_settings(db, ws_id)
    await purge_expired_trashed_leads(db, ws_id)
    docs = await db.crm_leads.find(lead_query(ws_id)).sort("updated_at", -1).to_list(5000)
    leads = [decorate_lead(doc, settings) for doc in docs]
    analytics = build_crm_analytics(leads)
    lead_summaries = []
    for lead in leads[:80]:
        values = lead.get("field_values") or {}
        receipts = lead.get("receipts") or []
        payment_total = sum(money_value(r.get("amount")) for r in receipts if str(r.get("status") or "Paid").lower() in {"paid", "success", "successful", "completed", "complete", "collected"})
        lead_summaries.append({
            "id": lead.get("id"),
            "name": values.get("full_name") or lead.get("full_name") or "",
            "phone": values.get("phone") or lead.get("phone") or "",
            "email": values.get("email") or lead.get("email") or "",
            "status": lead.get("status"),
            "customer_status": lead.get("customer_status"),
            "assigned_salesperson": values.get("assigned_salesperson") or lead.get("assigned_salesperson") or "",
            "created_at": lead.get("created_at"),
            "payment_collected": payment_total,
            "receipts": len(receipts),
            "last_note": (lead.get("lead_notes") or [{}])[-1].get("body", ""),
        })
    return settings, leads, analytics, lead_summaries


def _compact_crm_context(analytics, lead_summaries):
    return {
        "analytics": analytics,
        "leads": lead_summaries[:40],
    }


def _find_crm_lead(message, leads):
    text = str(message or "").lower()
    id_match = re.search(r"\b[0-9a-f]{24}\b", text)
    if id_match:
        for lead in leads:
            if str(lead.get("id", "")).lower() == id_match.group(0):
                return lead, None
    digits = re.sub(r"\D+", "", text)
    phone_matches = []
    if len(digits) >= 6:
        for lead in leads:
            phone = re.sub(r"\D+", "", str((lead.get("field_values") or {}).get("phone") or lead.get("phone") or ""))
            if phone and (phone in digits or digits in phone):
                phone_matches.append(lead)
    if len(phone_matches) == 1:
        return phone_matches[0], None
    if len(phone_matches) > 1:
        return None, "Multiple leads match that phone number. Please include the lead name or full lead id."
    name_matches = []
    for lead in leads:
        name = str((lead.get("field_values") or {}).get("full_name") or lead.get("full_name") or "").strip().lower()
        if name and name in text:
            name_matches.append(lead)
    if len(name_matches) == 1:
        return name_matches[0], None
    if len(name_matches) > 1:
        return None, "Multiple leads match that name. Please include the phone number or full lead id."
    return None, "I could not identify the lead. Please include the lead name, phone number, or full lead id."


def _extract_note_body(message):
    patterns = [
        r"(?:add|create|save)\s+(?:a\s+)?(?:call\s+)?note(?:\s+to|\s+for)?\s+.*?(?:\:|\-)\s*(.+)$",
        r"(?:called|call note)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE | re.DOTALL)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return ""


async def try_manager_crm_action(ws_id, message, settings, leads, *, source="web"):
    from crm import default_field_values, normalize_lead_note, validate_field_values

    text = str(message or "")
    lower = text.lower()
    is_note = bool(re.search(r"\b(add|create|save)\b.*\bnote\b|\bcalled\b|\bcall note\b", lower))
    is_status = bool(re.search(r"\b(change|set|update|mark)\b.*\b(status|lead)\b", lower))
    is_assign = bool(re.search(r"\b(assign|salesperson|sales person)\b", lower))
    is_field = bool(re.search(r"\b(update|set|change)\b", lower)) and any(f.get("key") in lower or str(f.get("label", "")).lower() in lower for f in settings.get("fields", []))
    if not any([is_note, is_status, is_assign, is_field]):
        return None

    lead, error = _find_crm_lead(text, leads)
    if not lead:
        return error

    updates = {"updated_at": now_iso()}
    actions = []
    if is_note:
        body = _extract_note_body(text) or text
        note_payload = {"body": body, "author": "Manager Chat"}
        if source == "voice":
            note_payload.update({"author": "AI Manager Phone", "source": "ai_manager_voice"})
        elif "plivo" in lower or "call" in lower or "called" in lower:
            note_payload.update({"source": "call_agent", "call_provider": "plivo", "summary": body})
        note = normalize_lead_note(note_payload)
        result = await db.crm_leads.update_one({"workspace_id": ws_id, "_id": oid(lead["id"])}, {"$push": {"lead_notes": note}, "$set": updates})
        if result.matched_count != 1:
            raise HTTPException(409, "Lead no longer available")
        actions.append("added a lead note")

    states = {s["key"]: s for s in settings.get("states", [])}
    if is_status:
        target_status = next((key for key in states if re.search(rf"\b{re.escape(key)}\b", lower)), "")
        if not target_status:
            target_status = next((s["key"] for s in states.values() if re.search(rf"\b{re.escape(str(s.get('label', '')).lower())}\b", lower)), "")
        if not target_status:
            return f"Which status should I set? Valid statuses are: {', '.join(states.keys())}."
        updates["status"] = target_status
        from meta_fields import pending_sheet_sync
        updates.update(pending_sheet_sync(lead, target_status))
        actions.append(f"set status to {target_status}")

    values = default_field_values(lead, settings)
    active = {f["key"]: f for f in settings.get("fields", []) if f.get("active", True)}
    if is_assign:
        match = re.search(r"(?:assign(?:ed)?(?:\s+salesperson)?|salesperson|sales person)\s+(?:to|as)?\s*([A-Za-z][A-Za-z .'-]{1,60})", text, flags=re.IGNORECASE)
        if match:
            values["assigned_salesperson"] = match.group(1).strip(" .")
            actions.append(f"assigned salesperson to {values['assigned_salesperson']}")
    for key, field in active.items():
        label = str(field.get("label") or key).lower()
        match = re.search(rf"(?:set|update|change)\s+(?:{re.escape(key)}|{re.escape(label)})\s+(?:to|as)\s+(.+?)(?:$|,|\band\b)", text, flags=re.IGNORECASE)
        if match:
            values[key] = match.group(1).strip()
            actions.append(f"updated {field.get('label') or key}")
    if actions and any(action.startswith(("assigned", "updated")) for action in actions):
        values = validate_field_values(values, settings)
        updates.update({
            "field_values": values,
            "email": values.get("email"),
            "full_name": values.get("full_name"),
            "phone": values.get("phone"),
            "address": values.get("address"),
            "source": values.get("source", lead.get("source", "google_sheet")),
            "assigned_salesperson": values.get("assigned_salesperson"),
        })
    if len(updates) > 1:
        result = await db.crm_leads.update_one({"workspace_id": ws_id, "_id": oid(lead["id"])}, {"$set": updates})
        if result.matched_count != 1:
            raise HTTPException(409, "Lead no longer available")
    if actions:
        name = (lead.get("field_values") or {}).get("full_name") or lead.get("phone") or lead.get("id")
        return f"Done. I {', '.join(actions)} for {name}."
    return None


# ---------------- MANAGER CHAT (SSE) ----------------
manager_service = ManagerService(db, crm_manager_context, try_manager_crm_action)


@api.post("/workspaces/{ws_id}/chat")
async def manager_chat(ws_id: str, request: Request, body: dict = Body(...)):
    user = await require_user(request)
    ws = await owned_workspace(ws_id, user)
    message = body.get("message", "")
    history = body.get("history", [])
    model_id = body.get("model_id") or ws.get("model_id")
    async def gen():
        try:
            with usage_scope(ws_id, "manager_chat"):
                async for delta in manager_service.stream(ws, message, history, model_id=model_id):
                    yield delta
        except Exception:
            logger.warning("manager_web_request_failed", extra={"workspace_id": ws_id})
            yield "\n[error: AI manager request failed. Please retry.]"

    return StreamingResponse(gen(), media_type="text/plain",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------- PLIVO CALL WEBHOOKS ----------------
async def _plivo_params(request: Request):
    params = dict(request.query_params)
    if request.method.upper() == "POST":
        form = await request.form()
        params.update({k: v for k, v in form.items()})
    return params


async def _plivo_body_params(request: Request):
    if request.method.upper() != "POST":
        return {}
    form = await request.form()
    return {k: v for k, v in form.items()}


async def _plivo_result_payload(request: Request):
    payload = dict(request.query_params)
    if request.method.upper() != "POST":
        return payload
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                payload.update(body)
                return payload
        except Exception:
            return payload
    form = await request.form()
    payload.update({k: v for k, v in form.items()})
    return payload


@api.api_route("/plivo/workspaces/{ws_id}/calls/{lead_id}/outbound/answer", methods=["GET", "POST"])
async def plivo_outbound_answer(ws_id: str, lead_id: str, request: Request):
    from plivo_calls import agent_flow_xml, callback_urls, plivo_config, public_base_url, require_plivo_signature

    params = await _plivo_params(request)
    await require_plivo_signature(request, await _plivo_body_params(request))
    from plivo_calls import workspace_plivo_config
    cfg = await workspace_plivo_config(request, ws_id)
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": oid(lead_id)})
    if not lead:
        raise HTTPException(404, "Lead not found")
    call_uuid = str(params.get("CallUUID") or params.get("call_uuid") or "").strip()
    if call_uuid:
        from plivo_calls import assign_plivo_call_uuid
        await assign_plivo_call_uuid(db, ws_id, lead_id, call_uuid)
    agent_url = (cfg.get("agent_trigger_url") or "").strip()
    if not agent_url:
        raise HTTPException(500, "PLIVO_AGENT_TRIGGER_URL is not configured")
    urls = callback_urls(public_base_url(request), ws_id, lead_id)
    return agent_flow_xml(agent_url, urls["qualification_result"])


@api.api_route("/plivo/agent/callback", methods=["GET", "POST"])
async def plivo_agent_callback(request: Request):
    from plivo_calls import (
        normalize_contacto_qualification_payload,
        normalize_lead_note,
        require_qualification_callback_auth,
        save_qualification_result,
    )

    await require_qualification_callback_auth(request, await _plivo_body_params(request))

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
    else:
        form_data = await request.form()
        payload = dict(form_data)

    raw_payload = payload
    payload = normalize_contacto_qualification_payload(payload)
    nested_object = None
    if isinstance(payload, dict) and "data" in payload and isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("object"), dict):
        nested_object = payload["data"]["object"]

    call_uuid = (
        payload.get("call_uuid")
        or payload.get("CallUUID")
        or payload.get("callUuid")
        or payload.get("request_uuid")
        or payload.get("RecordingCallUUID")
        or (nested_object or {}).get("call_uuid")
        or (nested_object or {}).get("CallUUID")
        or ""
    )
    conversation_id = (
        payload.get("conversation_id")
        or payload.get("conversationId")
        or payload.get("session_id")
        or payload.get("call_session_id")
        or (nested_object or {}).get("conversation_id")
        or ""
    )
    logger.info("Plivo agent callback received call_uuid=%s conversation_id=%s", call_uuid, conversation_id)

    if not call_uuid:
        logger.warning("Plivo agent callback missing call_uuid")
        raise HTTPException(422, "Missing CallUUID")

    lead = await db.crm_leads.find_one({"workspace_id": request.query_params.get("workspace_id"), "plivo_call_uuid": str(call_uuid)})
    if not lead:
        lead = await db.crm_leads.find_one({"workspace_id": request.query_params.get("workspace_id"), "qualification_call.call_uuid": str(call_uuid)})
    if not lead and conversation_id:
        lead = await db.crm_leads.find_one({"workspace_id": request.query_params.get("workspace_id"), "qualification_call.session_id": str(conversation_id)})
    if not lead:
        session = await db.plivo_call_sessions.find_one({"workspace_id": request.query_params.get("workspace_id"), "$or": [{"provider_identifiers.call_uuid": str(call_uuid)}, {"provider_identifiers.request_uuid": str(call_uuid)}]})
        if session and ObjectId.is_valid(session.get("lead_id", "")):
            lead = await db.crm_leads.find_one({"_id": ObjectId(session["lead_id"]), "workspace_id": session["workspace_id"]})
    if not lead:
        logger.warning("Plivo agent callback could not resolve CRM lead")
        raise HTTPException(404, "Call could not be matched to a lead")

    ws_id = lead.get("workspace_id")
    lead_id = str(lead.get("_id"))
    logger.info("Plivo agent callback resolved workspace_id=%s lead_id=%s call_uuid=%s", ws_id, lead_id, call_uuid)

    result = await save_qualification_result(db, ws_id, lead_id, raw_payload)
    return {"status": "success", "result": result, "call_uuid": call_uuid, "lead_id": lead_id, "workspace_id": ws_id}


@api.get("/plivo/workspaces/{ws_id}/calls/debug")
async def plivo_calls_debug(ws_id: str, request: Request, lead_id: str = None):
    from plivo_calls import plivo_config_debug, public_base_url

    user = await require_user(request)
    await owned_workspace(ws_id, user)
    from voice_api import webhooks
    from voice_config import load_config, public_config
    doc, _ = await load_config(db, ws_id, "plivo", enabled=False)
    return {**public_config(doc), "webhooks": webhooks(ws_id, "plivo")}


@api.api_route("/plivo/workspaces/{ws_id}/calls/outbound/status", methods=["GET", "POST"])
async def plivo_outbound_status(ws_id: str, request: Request):
    from plivo_calls import log_call_note, mark_plivo_event, require_plivo_signature, store_plivo_event, sync_qualification_status_from_payload

    params = await _plivo_params(request)
    await require_plivo_signature(request, await _plivo_body_params(request))
    lead_id = str(params.get("lead_id") or "").strip()
    if not lead_id:
        return {"ok": True, "logged": False}
    from plivo_calls import save_qualification_result
    return await save_qualification_result(db, ws_id, lead_id, params)


@api.api_route("/plivo/workspaces/{ws_id}/calls/{lead_id}/qualification/result", methods=["GET", "POST"])
async def plivo_qualification_result(ws_id: str, lead_id: str, request: Request):
    from plivo_calls import require_qualification_callback_auth, save_qualification_result

    await require_qualification_callback_auth(request, await _plivo_body_params(request))
    payload = await _plivo_result_payload(request)
    return await save_qualification_result(db, ws_id, lead_id, payload)


@api.api_route("/plivo/workspaces/{ws_id}/calls/inbound/answer", methods=["GET", "POST"])
async def plivo_inbound_answer(ws_id: str, request: Request):
    from plivo_calls import callback_urls, find_or_create_inbound_lead, inbound_bridge_xml, plivo_config, public_base_url, require_plivo_signature

    params = await _plivo_params(request)
    await require_plivo_signature(request, await _plivo_body_params(request))
    from plivo_calls import workspace_plivo_config
    cfg = await workspace_plivo_config(request, ws_id)
    caller = params.get("From") or params.get("CallerName") or ""
    lead, created = await find_or_create_inbound_lead(db, ws_id, caller)
    await log_plivo_inbound_started(ws_id, lead["id"], params, created)
    urls = callback_urls(public_base_url(request), ws_id, lead["id"])
    return inbound_bridge_xml(cfg["staff_number"], urls["recording"] + "&call_direction=inbound")


async def log_plivo_inbound_started(ws_id, lead_id, params, created):
    from plivo_calls import log_call_note

    await log_call_note(db, ws_id, lead_id, params, {
        "event": "inbound_started",
        "call_direction": "inbound",
        "body": "Inbound Plivo call received" + (" and new CRM lead created." if created else "."),
        "outcome": "new_lead_created" if created else "matched_existing_lead",
    })


async def maybe_process_recording_as_qualification(db, ws_id, lead_id, payload):
    from plivo_calls import normalize_contacto_qualification_payload, save_qualification_result

    candidate = normalize_contacto_qualification_payload(payload)
    if not isinstance(candidate, dict):
        return None
    text_signal = (
        candidate.get("conversation_summary")
        or candidate.get("summary")
        or candidate.get("call_summary")
        or candidate.get("final_summary")
        or candidate.get("transcript")
        or candidate.get("transcription")
        or candidate.get("recording_url")
        or candidate.get("recordingUrl")
    )
    if not text_signal:
        return None

    target_lead_id = str(lead_id or "").strip()
    if not target_lead_id:
        call_uuid = (
            candidate.get("call_uuid")
            or candidate.get("CallUUID")
            or candidate.get("callUuid")
            or candidate.get("request_uuid")
            or candidate.get("RecordingCallUUID")
            or ""
        )
        if not call_uuid:
            return None
        for query in (
            {"workspace_id": ws_id, "plivo_call_uuid": str(call_uuid)},
            {"workspace_id": ws_id, "qualification_call.call_uuid": str(call_uuid)},
        ):
            lead = await db.crm_leads.find_one(query)
            if lead:
                target_lead_id = str(lead.get("_id"))
                break
        if not target_lead_id:
            return None

    try:
        return await save_qualification_result(db, ws_id, target_lead_id, candidate)
    except Exception:
        logger.exception("Application-side qualification evaluation failed for recording callback ws_id=%s lead_id=%s", ws_id, target_lead_id)
        raise


@api.api_route("/plivo/workspaces/{ws_id}/calls/recording", methods=["GET", "POST"])
async def plivo_recording_callback(ws_id: str, request: Request):
    from plivo_calls import log_call_note, mark_plivo_event, require_plivo_signature, store_plivo_event

    params = await _plivo_params(request)
    await require_plivo_signature(request, await _plivo_body_params(request))
    lead_id = str(params.get("lead_id") or "").strip()
    payload = dict(params)
    nested_object = params.get("data") if isinstance(params.get("data"), dict) else {}
    if isinstance(nested_object.get("object"), dict):
        nested_event_data = nested_object["object"].get("event_data") or {}
        if isinstance(nested_event_data, dict):
            payload.update({k: v for k, v in nested_event_data.items()})
    direction = params.get("call_direction") or params.get("Direction") or "outbound"
    if not lead_id:
        candidate_call_uuid = (
            payload.get("call_uuid")
            or payload.get("CallUUID")
            or payload.get("callUuid")
            or payload.get("request_uuid")
            or (nested_object.get("object") or {}).get("call_uuid")
            or ""
        )
        if candidate_call_uuid:
            for query in (
                {"workspace_id": ws_id, "plivo_call_uuid": str(candidate_call_uuid)},
                {"workspace_id": ws_id, "qualification_call.call_uuid": str(candidate_call_uuid)},
            ):
                lead = await db.crm_leads.find_one(query)
                if lead:
                    lead_id = str(lead.get("_id"))
                    break
    if not lead_id and not payload.get("conversation_summary") and not payload.get("transcript") and not payload.get("transcription"):
        return {"ok": True, "logged": False}
    if not lead_id:
        raise HTTPException(404, "Call could not be matched to a lead")
    from plivo_calls import save_qualification_result
    return await save_qualification_result(db, ws_id, lead_id, payload)


# ---------------- PUBLIC (no auth) ----------------
@api.get("/public/workspace")
async def public_workspace(key: str, request: Request):
    ws = await db.workspaces.find_one({"public_key": key})
    if not ws:
        raise HTTPException(404, "Not found")
    _assert_blog_origin_allowed(ws, request)
    _assert_public_blog_rate(ws, request)
    return {"name": ws.get("name"), "website_url": ws.get("website_url")}


@api.post("/public/check-demo")
async def create_check_demo_lead(request: Request, body: dict = Body(...)):
    from crm import build_manual_lead, ensure_crm_settings
    from plivo_calls import normalize_lead_phone, start_qualification_call

    name = str(body.get("name") or "").strip()
    email = str(body.get("email") or "").strip()
    phone = normalize_lead_phone(body.get("phone"))
    if not name or not email or not phone:
        raise HTTPException(400, "Name, email, and phone number are required")

    configured_workspace = os.environ.get("CHECK_DEMO_WORKSPACE_ID", "").strip()
    ws = None
    if configured_workspace:
        try:
            ws = await db.workspaces.find_one({"_id": oid(configured_workspace)})
        except Exception:
            ws = None
    if not ws:
        ws = await db.workspaces.find_one({}, sort=[("created_at", 1)])
    if not ws:
        raise HTTPException(503, "Demo workspace is not configured")

    ws_id = str(ws["_id"])
    settings = await ensure_crm_settings(db, ws_id)
    lead_doc = build_manual_lead(ws_id, {
        "field_values": {
            "full_name": name,
            "email": email,
            "phone": phone,
            "source": "check_demo",
        },
    }, settings)
    lead_doc["source"] = "check_demo"
    lead_doc["qualification_status"] = "pending"
    lead_doc["timeline"] = [{"type": "created", "label": "Check Demo request submitted", "created_at": now_iso()}]
    await db.crm_leads.insert_one(lead_doc)
    result = await start_qualification_call(db, ws_id, str(lead_doc["_id"]), request)
    return {"status": result.get("status"), "lead_id": str(lead_doc["_id"]), "message": "Your AI demo call is being connected now."}


@api.get("/public/check-demo/{lead_id}")
async def get_check_demo_result(lead_id: str):
    try:
        lead = await db.crm_leads.find_one({"_id": oid(lead_id), "source": "check_demo"})
    except Exception:
        lead = None
    if not lead:
        raise HTTPException(404, "Demo call not found")

    values = lead.get("field_values") or {}
    qualification = lead.get("qualification_call") or {}
    communication = lead.get("communication_summary") or {}
    call_status = qualification.get("status") or communication.get("last_call_status") or "pending"
    return {
        "name": values.get("full_name") or lead.get("full_name") or "",
        "email": values.get("email") or lead.get("email") or "",
        "phone": values.get("phone") or lead.get("phone") or "",
        "call_status": call_status,
        "qualification_status": lead.get("qualification_status") or qualification.get("qualification_status") or "pending",
        "qualification_category": qualification.get("qualification_category") or communication.get("qualification_category") or "",
        "summary": qualification.get("summary") or communication.get("latest_summary") or "",
        "transcript": qualification.get("transcript") or "",
        "call_timestamp": qualification.get("call_timestamp") or lead.get("created_at") or "",
        "duration": qualification.get("duration") or communication.get("last_duration") or "",
        "recording_url": qualification.get("recording_url") or communication.get("last_recording_url") or "",
        "completed": bool(
            qualification.get("transcript")
            or qualification.get("qualification_status")
            or str(call_status).lower() in {"completed", "failed", "busy", "no_answer", "rejected", "cancelled", "canceled", "hangup"}
        ),
    }


@api.get("/public/blogs")
async def public_blogs(key: str, request: Request):
    ws = await db.workspaces.find_one({"public_key": key})
    if not ws:
        raise HTTPException(404, "Not found")
    _assert_blog_origin_allowed(ws, request)
    _assert_public_blog_rate(ws, request)
    docs = await db.blogs.find({"workspace_id": str(ws["_id"]), "status": "published"}).sort("published_at", -1).to_list(100)
    return [_public_blog_list_item(d) for d in docs]


@api.get("/public/blog/{slug}")
async def public_blog(slug: str, request: Request):
    blog = await db.blogs.find_one({"slug": slug, "status": "published"})
    if not blog:
        raise HTTPException(404, "Blog not found")
    ws = await db.workspaces.find_one({"_id": oid(blog["workspace_id"])})
    if ws:
        _assert_blog_origin_allowed(ws, request)
        _assert_public_blog_rate(ws, request)
    return _public_blog_detail(blog, ws)


@api.get("/embed/widget.js")
async def widget_js(key: str, request: Request):
    ws = await db.workspaces.find_one({"public_key": key})
    if not ws:
        raise HTTPException(404, "Not found")
    _assert_blog_origin_allowed(ws, request)
    _assert_public_blog_rate(ws, request)
    proto = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    backend = f"{proto}://{host}"
    js = """
(function(){
  var scripts = document.currentScript;
  var key = "%s";
  var api = "%s";
  var mount = document.getElementById("arevei-blog") || (function(){var d=document.createElement('div');d.id='arevei-blog';document.body.appendChild(d);return d;})();
  var css = "#arevei-blog{font-family:system-ui,sans-serif;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:20px}#arevei-blog a{text-decoration:none;color:inherit;border:1px solid #e5e5e5;border-radius:10px;overflow:hidden;display:block;transition:transform .2s}#arevei-blog a:hover{transform:translateY(-4px)}#arevei-blog img{width:100%%;height:160px;object-fit:cover}#arevei-blog .b{padding:16px}#arevei-blog h3{margin:0 0 8px;font-size:17px}#arevei-blog p{margin:0;color:#666;font-size:14px}";
  var s=document.createElement('style');s.innerHTML=css;document.head.appendChild(s);
  function esc(v){return String(v||'').replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  fetch(api+"/api/public/blogs?key="+encodeURIComponent(key)).then(function(r){
    return r.json().catch(function(){return {};}).then(function(data){
      if(!r.ok){throw new Error(data.detail||('HTTP '+r.status));}
      if(!Array.isArray(data)){throw new Error('Unexpected blog response');}
      return data;
    });
  }).then(function(list){
    if(!list.length){mount.innerHTML='No published blogs yet.';return;}
    mount.innerHTML = list.map(function(b){
      return '<a href="'+api.replace(/\\/api$/,'')+'/blog/'+encodeURIComponent(b.slug)+'" target="_blank"><img src="'+esc(b.hero_image)+'" alt=""/><div class="b"><h3>'+esc(b.title)+'</h3><p>'+esc(b.excerpt)+'</p></div></a>';
    }).join('');
  }).catch(function(e){mount.innerHTML='Unable to load blogs: '+esc(e.message||'check blog key and allowed origins')+'.';});
})();
""" % (key, backend)
    return PlainTextResponse(js, media_type="application/javascript")


# ---------------- SCHEDULER ----------------
async def scheduler_loop():
    await asyncio.sleep(10)
    while True:
        try:
            now = datetime.now(timezone.utc).isoformat()
            workspace_scope = [value.strip() for value in os.environ.get("BACKGROUND_WORKSPACE_IDS", "").split(",") if value.strip()]
            task_query = {"status": "pending", "requires_approval": False, "scheduled_time": {"$lte": now}}
            lead_query = {
                "qualification_call.status": "scheduled",
                "qualification_call.scheduled_for": {"$lte": now},
                "$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}],
            }
            if workspace_scope:
                task_query["workspace_id"] = {"$in": workspace_scope}
                lead_query["workspace_id"] = {"$in": workspace_scope}
            task = await db.tasks.find_one(task_query)
            if task:
                logger.info("Scheduler executing task %s", task.get("title"))
                await execute_task(task)
            from plivo_calls import start_qualification_call

            due_lead = await db.crm_leads.find_one(lead_query)
            if due_lead:
                ws_id = due_lead["workspace_id"]
                lead_id = str(due_lead["_id"])
                fake_request = type("RequestContext", (), {
                    "headers": {},
                    "url": type("UrlContext", (), {"scheme": "http", "netloc": "", "path": "", "query": ""})(),
                })()
                logger.info("Scheduler starting CRM qualification call workspace=%s lead=%s", ws_id, lead_id)
                await start_qualification_call(db, ws_id, lead_id, fake_request, auto=True, raise_on_error=False)
        except Exception:
            logger.exception("scheduler tick failed")
        await asyncio.sleep(5)


async def google_sheets_poller_loop():
    from google_sheets import retry_sheet_statuses, poll_sheet_connection
    await asyncio.sleep(15)
    while True:
        try:
            workflow_query = {"kind": "ads_to_crm", "status": "published"}
            workspace_scope = [value.strip() for value in os.environ.get("BACKGROUND_WORKSPACE_IDS", "").split(",") if value.strip()]
            if workspace_scope:
                workflow_query["workspace_id"] = {"$in": workspace_scope}
            await retry_sheet_statuses(db, workspace_scope)
            cursor = db.workflows.find(workflow_query)
            async for wf in cursor:
                ws_id = wf["workspace_id"]
                conn = await db.google_sheet_connections.find_one({"workspace_id": ws_id})
                if not conn or not conn.get("spreadsheet_id") or not conn.get("sheet_name"):
                    continue
                try:
                    result = await poll_sheet_connection(db, ws_id, conn)
                except Exception as error:
                    logger.warning("Sheet poll failed workspace=%s error_type=%s", ws_id, type(error).__name__)
                    continue
                if result["created"] > 0:
                    await notify(ws_id, "success", f"{result['created']} new leads imported", f"Imported {result['created']} new lead(s) from your connected Google Sheet.")
                    
        except Exception:
            logger.exception("google sheets poller tick failed")
        await asyncio.sleep(30)


from google_sheets import router as google_sheets_router
from workflows import router as workflows_router
from crm import router as crm_router
from plivo_agents import router as plivo_agents_router
from qualification_api import router as qualification_router
from crm_performance import router as crm_performance_router
from crm_workspace import router as crm_workspace_router
from properties import router as properties_router
from catalog import router as catalog_router
from sales_modules import router as sales_modules_router
from ai_usage import router as ai_usage_router

api.include_router(google_sheets_router)
api.include_router(workflows_router)
api.include_router(crm_router)
api.include_router(plivo_agents_router)
from voice_api import router as voice_providers_router
api.include_router(voice_providers_router)
api.include_router(qualification_router)
api.include_router(crm_performance_router)
api.include_router(crm_workspace_router)
api.include_router(properties_router)
api.include_router(catalog_router)
api.include_router(sales_modules_router)
api.include_router(ai_usage_router)
api.include_router(build_voice_router(db, manager_service, owned_workspace, require_user))

app.include_router(build_auth_router(db))
app.include_router(build_coding_router(db))
app.include_router(api)

cors_origins = [origin.strip().rstrip("/") for origin in os.environ.get("CORS_ORIGINS", "*").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    app.state.db = db
    try:
        await initialize_voice_storage(db)
        app.state.voice_storage_ready = True
    except Exception:
        # The optional voice test must not prevent the existing application starting.
        app.state.voice_storage_ready = False
        logger.warning("voice_storage_initialization_failed")
    await db.users.create_index("email", unique=True)
    await db.password_reset_tokens.create_index("token_hash", unique=True)
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.workspaces.create_index("public_key")
    await db.blogs.create_index("slug", unique=True)
    await db.code_projects.create_index("user_id")
    await db.code_projects.create_index("workspace_id")
    await db.workflows.create_index([("workspace_id", 1), ("kind", 1)])
    await db.crm_leads.create_index([("workspace_id", 1), ("sheet_row_key", 1)], unique=True)
    await db.crm_leads.create_index([("workspace_id", 1), ("plivo_call_uuid", 1)])
    await db.crm_settings.create_index("workspace_id", unique=True)
    await db.workspace_voice_provider_configs.create_index([("workspace_id", 1), ("provider", 1)], unique=True)
    await db.plivo_agent_configs.create_index([("workspace_id", 1), ("enabled", 1), ("is_default", 1)])
    await db.plivo_call_sessions.create_index([("workspace_id", 1), ("lead_id", 1), ("status", 1)])
    await db.plivo_call_sessions.create_index([("workspace_id", 1), ("created_at", -1)])
    await db.plivo_call_events.create_index([("workspace_id", 1), ("idempotency_key", 1)], unique=True)
    await db.plivo_call_events.create_index([("workspace_id", 1), ("lead_id", 1), ("created_at", -1)])
    await db.qualification_profiles.create_index([("workspace_id", 1), ("campaign_id", 1)], unique=True, partialFilterExpression={"campaign_id": {"$type": "string"}})
    await db.crm_call_logs.create_index([("workspace_id", 1), ("lead_id", 1), ("kind", 1)])
    await db.catalog_items.create_index([("workspace_id", 1), ("kind", 1), ("status", 1)])
    await db.properties.create_index([("workspace_id", 1), ("status", 1)])
    await db.crm_leads.create_index([("workspace_id", 1), ("status", 1), ("opportunity.total_minor", 1)])
    await db.ai_usage_events.create_index([("workspace_id", 1), ("day", -1), ("process", 1)])
    await seed_admin(db)
    if os.environ.get("DISABLE_BACKGROUND_JOBS", "").strip().lower() not in {"1", "true", "yes"}:
        asyncio.create_task(scheduler_loop())
        asyncio.create_task(google_sheets_poller_loop())
    else:
        logger.info("Background scheduler and Google Sheets poller disabled")
    logger.info("Arevei backend ready")


@app.on_event("shutdown")
async def shutdown():
    client.close()
