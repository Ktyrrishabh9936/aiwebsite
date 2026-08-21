import os
import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("server")

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="Arevei AI Manager")
api = APIRouter(prefix="/api")


def oid(v):
    return ObjectId(v)


def doc_out(doc):
    if not doc:
        return None
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


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


# ---------------- MODELS ----------------
@api.get("/models")
async def list_models():
    return {"models": llm_service.MODELS, "default": llm_service.DEFAULT_MODEL}


# ---------------- WORKSPACES ----------------
async def _build_brain_bg(ws_id, url, model_id):
    from crawler import crawl_site
    try:
        await db.workspaces.update_one({"_id": oid(ws_id)}, {"$set": {"brain_status": "building"}})
        crawl = await crawl_site(url)
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
    return doc_out(doc)


@api.get("/workspaces")
async def list_workspaces(request: Request):
    user = await require_user(request)
    docs = await db.workspaces.find({"user_id": str(user["_id"])}).sort("created_at", -1).to_list(100)
    return [doc_out(d) for d in docs]


@api.get("/workspaces/{ws_id}")
async def get_workspace(ws_id: str, request: Request):
    user = await require_user(request)
    ws = await owned_workspace(ws_id, user)
    return doc_out(ws)


@api.patch("/workspaces/{ws_id}")
async def update_workspace(ws_id: str, request: Request, body: dict = Body(...)):
    user = await require_user(request)
    await owned_workspace(ws_id, user)
    updates = {k: v for k, v in body.items() if k in ("model_id", "name")}
    if updates:
        await db.workspaces.update_one({"_id": oid(ws_id)}, {"$set": updates})
    doc = await db.workspaces.find_one({"_id": oid(ws_id)})
    return doc_out(doc)


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
    roadmap = await agents.build_roadmap(model_id, brain)
    await db.workspaces.update_one({"_id": oid(ws_id)}, {"$set": {"roadmap": roadmap.get("months", []),
                                                                   "strategy_summary": roadmap.get("strategy_summary", "")}})
    # generate + schedule tasks
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
    ws = await db.workspaces.find_one({"_id": oid(task_doc["workspace_id"])})
    if not ws:
        return
    model_id = ws.get("model_id")
    brain = ws.get("brain", {})
    ws_id = task_doc["workspace_id"]
    tid = task_doc["_id"]
    await db.tasks.update_one({"_id": tid}, {"$set": {"status": "running"}})
    try:
        if task_doc.get("agent") == "content" and task_doc.get("deliverable_type") == "blog_post":
            data = await agents.write_blog(model_id, brain, task_doc["title"], task_doc.get("objective", ""))
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
        else:
            # seo / creative / analytics -> textual deliverable
            summary = await llm_service.generate_text(
                model_id,
                f"You are the AREVEI {task_doc.get('agent')} agent.",
                f"Task: {task_doc['title']}\nObjective: {task_doc.get('objective','')}\n"
                f"Produce a concise, actionable deliverable (bullet points).",
                max_tokens=1200)
            await db.tasks.update_one({"_id": tid}, {"$set": {"status": "done", "output_summary": summary[:4000]}})
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
    await notify(task["workspace_id"], "success", "Approved & published", task["title"])
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
              "blocks", "meta_title", "meta_description", "keywords"]
    updates = {k: body[k] for k in fields if k in body}
    if updates:
        await db.blogs.update_one({"_id": oid(blog_id)}, {"$set": updates})
    doc = await db.blogs.find_one({"_id": oid(blog_id)})
    return doc_out(doc)


@api.post("/blogs/{blog_id}/publish")
async def publish_blog(blog_id: str, request: Request):
    user = await require_user(request)
    blog = await db.blogs.find_one({"_id": oid(blog_id)})
    if not blog:
        raise HTTPException(404, "Blog not found")
    await owned_workspace(blog["workspace_id"], user)
    new_status = "draft" if blog.get("status") == "published" else "published"
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


# ---------------- MANAGER CHAT (SSE) ----------------
@api.post("/workspaces/{ws_id}/chat")
async def manager_chat(ws_id: str, request: Request, body: dict = Body(...)):
    user = await require_user(request)
    ws = await owned_workspace(ws_id, user)
    message = body.get("message", "")
    history = body.get("history", [])
    model_id = body.get("model_id") or ws.get("model_id")
    roadmap = {"strategy_summary": ws.get("strategy_summary", ""), "months": ws.get("roadmap", [])}

    async def gen():
        try:
            async for delta in agents.manager_chat_stream(model_id, ws.get("brain", {}), roadmap, history, message):
                yield delta
        except Exception as e:
            yield f"\n[error: {str(e)[:120]}]"

    return StreamingResponse(gen(), media_type="text/plain",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------- PUBLIC (no auth) ----------------
@api.get("/public/workspace")
async def public_workspace(key: str):
    ws = await db.workspaces.find_one({"public_key": key})
    if not ws:
        raise HTTPException(404, "Not found")
    return {"name": ws.get("name"), "website_url": ws.get("website_url")}


@api.get("/public/blogs")
async def public_blogs(key: str):
    ws = await db.workspaces.find_one({"public_key": key})
    if not ws:
        raise HTTPException(404, "Not found")
    docs = await db.blogs.find({"workspace_id": str(ws["_id"]), "status": "published"}).sort("published_at", -1).to_list(100)
    return [{"title": d["title"], "slug": d["slug"], "excerpt": d.get("excerpt", ""),
             "hero_image": d.get("hero_image", ""), "read_time": d.get("read_time", ""),
             "tags": d.get("tags", []), "published_at": d.get("published_at")} for d in docs]


@api.get("/public/blog/{slug}")
async def public_blog(slug: str):
    blog = await db.blogs.find_one({"slug": slug, "status": "published"})
    if not blog:
        raise HTTPException(404, "Blog not found")
    ws = await db.workspaces.find_one({"_id": oid(blog["workspace_id"])})
    return {**doc_out(blog), "workspace_name": ws.get("name") if ws else "",
            "workspace_url": ws.get("website_url") if ws else "",
            "public_key": ws.get("public_key") if ws else ""}


@api.get("/embed/widget.js")
async def widget_js(key: str, request: Request):
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
  fetch(api+"/api/public/blogs?key="+key).then(function(r){return r.json()}).then(function(list){
    mount.innerHTML = list.map(function(b){
      return '<a href="'+api.replace(/\\/api$/,'')+'/blog/'+b.slug+'" target="_blank"><img src="'+(b.hero_image||'')+'"/><div class="b"><h3>'+b.title+'</h3><p>'+(b.excerpt||'')+'</p></div></a>';
    }).join('');
  }).catch(function(e){mount.innerHTML='Unable to load blogs.';});
})();
""" % (key, backend)
    return PlainTextResponse(js, media_type="application/javascript")


# ---------------- SCHEDULER ----------------
async def scheduler_loop():
    await asyncio.sleep(10)
    while True:
        try:
            now = datetime.now(timezone.utc).isoformat()
            task = await db.tasks.find_one({"status": "pending", "requires_approval": False,
                                            "scheduled_time": {"$lte": now}})
            if task:
                logger.info("Scheduler executing task %s", task.get("title"))
                await execute_task(task)
        except Exception:
            logger.exception("scheduler tick failed")
        await asyncio.sleep(30)


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
    await db.users.create_index("email", unique=True)
    await db.workspaces.create_index("public_key")
    await db.blogs.create_index("slug", unique=True)
    await db.code_projects.create_index("user_id")
    await seed_admin(db)
    asyncio.create_task(scheduler_loop())
    logger.info("Arevei backend ready")


@app.on_event("shutdown")
async def shutdown():
    client.close()
