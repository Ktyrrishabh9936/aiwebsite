"""AI coding platform router: projects, sandbox files/terminal/preview, coding agent."""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from bson import ObjectId
from fastapi import APIRouter, Request, HTTPException, Body
from fastapi.responses import StreamingResponse

from auth import get_current_user
import daytona_service as dz
import coding_agent

logger = logging.getLogger("coding")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


SCAFFOLDS = {
    "react-vite": {
        "package.json": json.dumps({
            "name": "arevei-app", "private": True, "version": "0.0.0", "type": "module",
            "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
            "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
            "devDependencies": {"@vitejs/plugin-react": "^4.3.1", "vite": "^5.4.0"},
        }, indent=2),
        "vite.config.js": (
            "import { defineConfig } from 'vite'\n"
            "import react from '@vitejs/plugin-react'\n\n"
            "export default defineConfig({\n"
            "  plugins: [react()],\n"
            "  server: { host: true, port: 5173, strictPort: true, allowedHosts: true },\n"
            "})\n"
        ),
        "index.html": (
            "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\" />\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n"
            "<title>Arevei App</title>\n</head>\n<body>\n<div id=\"root\"></div>\n"
            "<script type=\"module\" src=\"/src/main.jsx\"></script>\n</body>\n</html>\n"
        ),
        "src/main.jsx": (
            "import React from 'react'\nimport { createRoot } from 'react-dom/client'\n"
            "import App from './App.jsx'\nimport './index.css'\n\n"
            "createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>)\n"
        ),
        "src/App.jsx": (
            "export default function App() {\n"
            "  return (\n"
            "    <main className=\"shell\">\n"
            "      <section className=\"hero\">\n"
            "        <p className=\"eyebrow\">Arevei starter</p>\n"
            "        <h1>Welcome to your Arevei app</h1>\n"
            "        <p className=\"lead\">A polished React canvas is ready. Ask the coding agent to turn this into a product, portfolio, store, dashboard, or game.</p>\n"
            "        <div className=\"actions\">\n"
            "          <a href=\"#features\">Explore starter</a>\n"
            "          <button>Start building</button>\n"
            "        </div>\n"
            "      </section>\n"
            "      <section id=\"features\" className=\"grid\">\n"
            "        {['Responsive layout', 'Production spacing', 'Design-first edits'].map((item) => <article key={item}><span></span><h2>{item}</h2><p>Use this as the foundation for a more complete generated experience.</p></article>)}\n"
            "      </section>\n"
            "    </main>\n"
            "  )\n"
            "}\n"
        ),
        "src/index.css": (
            ":root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#101010;background:#f6f3ee}\n"
            "*{box-sizing:border-box} body{margin:0} a{color:inherit;text-decoration:none} button{font:inherit}\n"
            ".shell{min-height:100vh;padding:48px clamp(20px,5vw,72px);background:linear-gradient(135deg,#f6f3ee 0%,#f8fbff 48%,#eaf6ef 100%);color:#101010}\n"
            ".hero{min-height:62vh;display:flex;flex-direction:column;justify-content:center;max-width:920px}\n"
            ".eyebrow{margin:0 0 18px;text-transform:uppercase;letter-spacing:.16em;font-size:12px;font-weight:800;color:#126b55}\n"
            "h1{font-size:clamp(44px,9vw,104px);line-height:.9;margin:0;letter-spacing:0;font-weight:900;max-width:10ch}\n"
            ".lead{font-size:clamp(18px,2vw,24px);line-height:1.45;max-width:700px;margin:28px 0;color:#3b3b3b}\n"
            ".actions{display:flex;gap:12px;flex-wrap:wrap}.actions a,.actions button{height:46px;border-radius:8px;padding:0 18px;display:inline-flex;align-items:center;border:1px solid #111;background:#111;color:white;font-weight:800}.actions button{background:white;color:#111}\n"
            ".grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:26px}.grid article{background:rgba(255,255,255,.68);border:1px solid rgba(16,16,16,.12);border-radius:8px;padding:20px;box-shadow:0 20px 70px rgba(20,40,60,.08)}\n"
            ".grid span{display:block;width:32px;height:4px;border-radius:4px;background:#126b55;margin-bottom:20px}.grid h2{font-size:18px;margin:0 0 8px}.grid p{margin:0;color:#555;line-height:1.5}\n"
            "@media(max-width:760px){.shell{padding:28px 18px}.hero{min-height:58vh}.grid{grid-template-columns:1fr}}\n"
        ),
    },
    "node": {
        "package.json": json.dumps({
            "name": "arevei-node", "version": "1.0.0", "type": "module",
            "scripts": {"dev": "node index.js", "start": "node index.js"},
        }, indent=2),
        "index.js": (
            "import http from 'http'\n\n"
            "const server = http.createServer((req, res) => {\n"
            "  res.writeHead(200, { 'Content-Type': 'text/html' })\n"
            "  res.end('<h1>Arevei Node server</h1><p>Ask the agent to build your API or app.</p>')\n"
            "})\n\n"
            "server.listen(5173, '0.0.0.0', () => console.log('listening on 5173'))\n"
        ),
    },
    "static": {
        "index.html": (
            "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\" />\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n"
            "<title>Arevei Site</title>\n<style>body{font-family:system-ui;background:#0a0a0a;color:#f5f5f5;display:grid;place-items:center;height:100vh;margin:0;text-align:center}</style>\n"
            "</head>\n<body>\n<div><h1>Welcome to your Arevei site</h1><p>Ask the agent to build anything.</p></div>\n</body>\n</html>\n"
        ),
    },
    "blank": {
        "README.md": "# New Arevei project\n\nThis is a blank sandbox. Ask the coding agent to build anything in any language or framework — it controls the full filesystem, config, and terminal.\n",
    },
}
TEMPLATES = list(SCAFFOLDS.keys())


def build_coding_router(db):
    router = APIRouter(prefix="/api/code", tags=["coding"])

    async def user_of(request):
        return await get_current_user(request, db)

    async def owned(pid, user):
        try:
            proj = await db.code_projects.find_one({"_id": ObjectId(pid)})
        except Exception:
            raise HTTPException(404, "Project not found")
        if not proj:
            raise HTTPException(404, "Project not found")
        if str(proj["user_id"]) != str(user["_id"]) and user.get("role") != "admin":
            raise HTTPException(403, "Forbidden")
        return proj

    def out(p):
        p = dict(p)
        p["id"] = str(p.pop("_id"))
        return p

    async def provision(pid, template):
        try:
            sb = await dz.create_sandbox(pid)
            for path, content in SCAFFOLDS.get(template, SCAFFOLDS["blank"]).items():
                await dz.write_file(sb, path, content)
            await db.code_projects.update_one({"_id": ObjectId(pid)},
                                              {"$set": {"sandbox_id": sb.id, "sandbox_status": "ready"}})
        except Exception as e:
            logger.exception("provision failed")
            await db.code_projects.update_one({"_id": ObjectId(pid)},
                                              {"$set": {"sandbox_status": "error", "error": str(e)[:300]}})

    async def get_started_sandbox(proj):
        if not proj.get("sandbox_id"):
            raise HTTPException(409, "Sandbox not provisioned yet")
        return await dz.ensure_started(proj["sandbox_id"])

    # ---------- models ----------
    @router.get("/models")
    async def models():
        def ready(provider):
            if provider == "openai":
                return bool(os.environ.get("OPENAI_API_KEY"))
            if provider == "openrouter":
                return bool(os.environ.get("OPENROUTER_API_KEY"))
            if provider == "nvidia":
                return bool(os.environ.get("NVIDIA_NIM_API_KEY"))
            return False

        models = [{**m, "configured": ready(m.get("provider"))} for m in coding_agent.CODING_MODELS]
        return {"models": models, "default": coding_agent.DEFAULT_CODING_MODEL,
                "providers": {
                    "openai": {"configured": ready("openai"), "env": "OPENAI_API_KEY"},
                    "openrouter": {"configured": ready("openrouter"), "env": "OPENROUTER_API_KEY"},
                    "nvidia": {"configured": ready("nvidia"), "env": "NVIDIA_NIM_API_KEY"},
                    "github": {"configured": bool(os.environ.get("GITHUB_TOKEN")), "env": "GITHUB_TOKEN"},
                    "skills": {"configured": True, "env": "Built-in coding, design, terminal, file, and testing skills"},
                },
                "templates": [
                    {"id": "react-vite", "label": "React (Vite)"},
                    {"id": "node", "label": "Node.js"},
                    {"id": "static", "label": "Static HTML"},
                    {"id": "blank", "label": "Blank (any language)"},
                ]}

    # ---------- projects ----------
    @router.post("/projects")
    async def create_project(request: Request, body: dict = Body(...)):
        user = await user_of(request)
        template = body.get("template") or "react-vite"
        if template not in SCAFFOLDS:
            template = "react-vite"
        doc = {
            "user_id": str(user["_id"]),
            "name": body.get("name") or "Untitled project",
            "template": template,
            "model_id": body.get("model_id") or coding_agent.DEFAULT_CODING_MODEL,
            "sandbox_id": None,
            "sandbox_status": "provisioning",
            "preview_url": None,
            "deployed_url": None,
            "created_at": now_iso(),
        }
        res = await db.code_projects.insert_one(doc)
        pid = str(res.inserted_id)
        asyncio.create_task(provision(pid, template))
        doc["_id"] = res.inserted_id
        return out(doc)

    @router.post("/projects/import/github")
    async def import_github(request: Request, body: dict = Body(...)):
        user = await user_of(request)
        repo_url = (body.get("repo_url") or "").strip()
        if not repo_url:
            raise HTTPException(400, "repo_url required")
        doc = {
            "user_id": str(user["_id"]),
            "name": body.get("name") or repo_url.rstrip("/").split("/")[-1].replace(".git", "") or "GitHub project",
            "template": "github",
            "model_id": body.get("model_id") or coding_agent.DEFAULT_CODING_MODEL,
            "sandbox_id": None,
            "sandbox_status": "provisioning",
            "preview_url": None,
            "deployed_url": None,
            "repo_url": repo_url,
            "branch": body.get("branch") or None,
            "created_at": now_iso(),
        }
        res = await db.code_projects.insert_one(doc)
        pid = str(res.inserted_id)

        async def import_bg():
            try:
                sb = await dz.create_sandbox(pid)
                await dz.import_github_repo(sb, repo_url, body.get("branch"), os.environ.get("GITHUB_TOKEN"))
                await db.code_projects.update_one({"_id": ObjectId(pid)},
                                                  {"$set": {"sandbox_id": sb.id, "sandbox_status": "ready"}})
            except Exception as e:
                logger.exception("github import failed")
                await db.code_projects.update_one({"_id": ObjectId(pid)},
                                                  {"$set": {"sandbox_status": "error", "error": str(e)[:300]}})

        asyncio.create_task(import_bg())
        doc["_id"] = res.inserted_id
        return out(doc)

    @router.get("/projects")
    async def list_projects(request: Request):
        user = await user_of(request)
        docs = await db.code_projects.find({"user_id": str(user["_id"])}).sort("created_at", -1).to_list(100)
        return [out(d) for d in docs]

    @router.get("/projects/{pid}")
    async def get_project(pid: str, request: Request):
        user = await user_of(request)
        proj = await owned(pid, user)
        return out(proj)

    @router.patch("/projects/{pid}")
    async def update_project(pid: str, request: Request, body: dict = Body(...)):
        user = await user_of(request)
        await owned(pid, user)
        updates = {k: v for k, v in body.items() if k in ("name", "model_id")}
        if updates:
            await db.code_projects.update_one({"_id": ObjectId(pid)}, {"$set": updates})
        proj = await db.code_projects.find_one({"_id": ObjectId(pid)})
        return out(proj)

    @router.delete("/projects/{pid}")
    async def delete_project(pid: str, request: Request):
        user = await user_of(request)
        proj = await owned(pid, user)
        if proj.get("sandbox_id"):
            asyncio.create_task(dz.delete_sandbox(proj["sandbox_id"]))
        await db.code_projects.delete_one({"_id": ObjectId(pid)})
        await db.code_messages.delete_many({"project_id": pid})
        return {"ok": True}

    @router.post("/projects/{pid}/restart")
    async def restart(pid: str, request: Request):
        user = await user_of(request)
        proj = await owned(pid, user)
        await get_started_sandbox(proj)
        return {"ok": True, "status": "ready"}

    # ---------- files ----------
    @router.get("/projects/{pid}/files")
    async def files(pid: str, request: Request):
        user = await user_of(request)
        proj = await owned(pid, user)
        sb = await get_started_sandbox(proj)
        return {"tree": await dz.list_tree(sb)}

    @router.get("/projects/{pid}/file")
    async def get_file(pid: str, path: str, request: Request):
        user = await user_of(request)
        proj = await owned(pid, user)
        sb = await get_started_sandbox(proj)
        return {"path": path, "content": await dz.read_file(sb, path)}

    @router.put("/projects/{pid}/file")
    async def put_file(pid: str, request: Request, body: dict = Body(...)):
        user = await user_of(request)
        proj = await owned(pid, user)
        sb = await get_started_sandbox(proj)
        await dz.write_file(sb, body["path"], body.get("content", ""))
        return {"ok": True}

    # ---------- terminal ----------
    @router.post("/projects/{pid}/terminal")
    async def terminal(pid: str, request: Request, body: dict = Body(...)):
        user = await user_of(request)
        proj = await owned(pid, user)
        sb = await get_started_sandbox(proj)
        res = await dz.exec_cmd(sb, body.get("command", "echo"), timeout=min(int(body.get("timeout", 90)), 110))
        return res

    # ---------- preview ----------
    @router.post("/projects/{pid}/run")
    async def run(pid: str, request: Request):
        user = await user_of(request)
        proj = await owned(pid, user)
        sb = await get_started_sandbox(proj)
        await dz.start_dev_server(sb)
        await db.code_projects.update_one({"_id": ObjectId(pid)}, {"$set": {"preview_url": None}})
        return {"starting": True}

    @router.get("/projects/{pid}/preview")
    async def preview(pid: str, request: Request):
        user = await user_of(request)
        proj = await owned(pid, user)
        sb = await get_started_sandbox(proj)
        status = await dz.preview_status(sb, existing_url=proj.get("preview_url"))
        if status.get("url"):
            await db.code_projects.update_one({"_id": ObjectId(pid)}, {"$set": {"preview_url": status["url"]}})
        return status

    # ---------- chat / agent ----------
    @router.get("/projects/{pid}/messages")
    async def messages(pid: str, request: Request):
        user = await user_of(request)
        await owned(pid, user)
        docs = await db.code_messages.find({"project_id": pid}).sort("created_at", 1).to_list(500)
        return [{"id": str(d["_id"]), "role": d["role"], "content": d["content"],
                 "steps": d.get("steps", []), "created_at": d["created_at"]} for d in docs]

    @router.post("/projects/{pid}/chat")
    async def chat(pid: str, request: Request, body: dict = Body(...)):
        user = await user_of(request)
        proj = await owned(pid, user)
        message = body.get("message", "")
        model_id = body.get("model_id") or proj.get("model_id")
        sb = await get_started_sandbox(proj)

        ops = {
            "list_files": lambda: dz.list_tree(sb),
            "read_file": lambda p: dz.read_file(sb, p),
            "write_file": lambda p, c: dz.write_file(sb, p, c),
            "run_command": lambda c: dz.exec_cmd(sb, c),
        }

        hist_docs = await db.code_messages.find({"project_id": pid}).sort("created_at", 1).to_list(500)
        history = [{"role": d["role"], "content": d["content"]} for d in hist_docs]

        await db.code_messages.insert_one({"project_id": pid, "role": "user", "content": message,
                                           "steps": [], "created_at": now_iso()})

        async def gen():
            collected_steps = []
            summary = "Done."
            try:
                async for ev in coding_agent.run_agent(ops, model_id, history, message):
                    if ev.get("type") == "done":
                        collected_steps = ev.get("steps", [])
                        summary = ev.get("summary", summary)
                    yield f"data: {json.dumps(ev)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type':'error','message':str(e)[:200]})}\n\n"
            await db.code_messages.insert_one({"project_id": pid, "role": "assistant", "content": summary,
                                               "steps": collected_steps, "model_id": model_id, "created_at": now_iso()})
            yield "data: {\"type\":\"end\"}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return router
