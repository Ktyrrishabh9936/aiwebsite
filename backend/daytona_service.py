"""Daytona sandbox lifecycle + filesystem/exec helpers for the coding platform."""
import asyncio
import logging
import os
import posixpath
from daytona import AsyncDaytona, CreateSandboxFromSnapshotParams

logger = logging.getLogger("daytona")

BASE = "/home/daytona/project"
PREVIEW_PORT = 5173

_client = AsyncDaytona()
_locks = {}


def _lock(key):
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


async def create_sandbox(project_id):
    params = CreateSandboxFromSnapshotParams(language="typescript", labels={"project_id": project_id})
    sb = await _client.create(params)
    await sb.process.exec(f"mkdir -p {BASE}", timeout=30)
    return sb


async def get_sandbox(sandbox_id):
    return await _client.get(sandbox_id)


async def ensure_started(sandbox_id):
    async with _lock(sandbox_id):
        sb = await _client.get(sandbox_id)
        try:
            await sb.refresh_data()
        except Exception:
            pass
        state = str(getattr(sb, "state", "")).lower()
        if "stop" in state or state in {"paused", "archived"}:
            logger.info("Auto-starting stopped sandbox %s", sandbox_id)
            await sb.start()
            await sb.refresh_data()
        elif "error" in state and getattr(sb, "recoverable", False):
            await sb.recover()
            await sb.refresh_data()
    return sb


async def exec_cmd(sb, command, timeout=120):
    r = await sb.process.exec(f"cd {BASE} && {command}", timeout=timeout)
    return {"exit_code": r.exit_code, "output": (r.result or "")[:60000]}


async def write_file(sb, rel_path, content):
    rel_path = rel_path.lstrip("/")
    full = posixpath.join(BASE, rel_path)
    parent = posixpath.dirname(full)
    if parent and parent != BASE:
        await sb.process.exec(f"mkdir -p {parent}", timeout=30)
    await sb.fs.upload_file(content.encode("utf-8"), full)
    return full


async def read_file(sb, rel_path):
    rel_path = rel_path.lstrip("/")
    full = posixpath.join(BASE, rel_path)
    data = await sb.fs.download_file(full)
    return data.decode("utf-8", errors="replace")


async def list_tree(sb):
    r = await sb.process.exec(
        f"cd {BASE} && find . -not -path '*/node_modules/*' -not -path '*/.git/*' -not -name '.' -printf '%y|%P\\n' 2>/dev/null | sort | head -500",
        timeout=30,
    )
    entries = []
    for line in (r.result or "").splitlines():
        if "|" not in line:
            continue
        t, p = line.split("|", 1)
        if p:
            entries.append((t, p))
    return _build_tree(entries)


def _build_tree(entries):
    root = {}
    for t, path in entries:
        parts = path.split("/")
        node = root
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            if part not in node:
                node[part] = {"__type": "dir" if (not is_last or t == "d") else "file", "__children": {}}
            node = node[part]["__children"]

    def to_list(d, prefix=""):
        out = []
        for name, meta in sorted(d.items(), key=lambda kv: (kv[1]["__type"] != "dir", kv[0])):
            full = f"{prefix}/{name}".lstrip("/")
            item = {"name": name, "path": full, "type": meta["__type"]}
            if meta["__type"] == "dir":
                item["children"] = to_list(meta["__children"], full)
            out.append(item)
        return out

    return to_list(root)


async def start_dev_server(sb):
    session_id = "devserver"
    try:
        await sb.process.get_session(session_id)
        await sb.process.delete_session(session_id)
    except Exception:
        pass
    from daytona import SessionExecuteRequest
    await sb.process.create_session(session_id)
    cmd = (
        f"cd {BASE} && (pkill -f vite || true) && "
        f"if [ -f package.json ]; then ([ -d node_modules ] || npm install) && "
        f"(npm run dev -- --host 0.0.0.0 --port {PREVIEW_PORT} || npx --yes vite --host 0.0.0.0 --port {PREVIEW_PORT}); "
        f"else npx --yes serve -l {PREVIEW_PORT} .; fi"
    )
    await sb.process.execute_session_command(session_id, SessionExecuteRequest(command=cmd, run_async=True))


async def preview_status(sb, existing_url=None):
    url = existing_url
    if not url:
        try:
            signed = await sb.create_signed_preview_url(PREVIEW_PORT, expires_in_seconds=3600)
            url = getattr(signed, "url", None) or (signed.get("url") if isinstance(signed, dict) else None)
        except Exception:
            pass
    if not url:
        link = await sb.get_preview_link(PREVIEW_PORT)
        url = getattr(link, "url", None) or (link.get("url") if isinstance(link, dict) else str(link))
    r = await sb.process.exec(
        f"curl -s -o /dev/null -w '%{{http_code}}' -m 3 http://localhost:{PREVIEW_PORT} 2>/dev/null || echo 000",
        timeout=15,
    )
    code = (r.result or "").strip()[-3:]
    return {"url": url, "ready": code.startswith("2") or code.startswith("3")}


async def delete_sandbox(sandbox_id):
    try:
        sb = await _client.get(sandbox_id)
        await sb.delete()
    except Exception:
        logger.warning("delete sandbox failed")
