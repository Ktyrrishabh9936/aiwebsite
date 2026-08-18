"""AI coding platform router: projects, sandbox files/terminal/preview, coding agent."""
import asyncio
import json
import logging
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
            "    <div className=\"app\">\n"
            "      <h1>Welcome to your Arevei app</h1>\n"
            "      <p>Ask the coding agent in the chat to build anything.</p>\n"
            "    </div>\n"
            "  )\n"
            "}\n"
        ),
        "src/index.css": (
            ":root{color-scheme:light dark}\n"
            "*{box-sizing:border-box}\n"
            "body{margin:0;font-family:system-ui,sans-serif;background:#0a0a0a;color:#f5f5f5}\n"
            ".app{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;text-align:center;padding:24px}\n"
            "h1{font-size:2rem;margin:0}\n"
            "p{color:#a3a3a3;margin:0}\n"
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
        return {"models": coding_agent.CODING_MODELS, "default": coding_agent.DEFAULT_CODING_MODEL,
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
