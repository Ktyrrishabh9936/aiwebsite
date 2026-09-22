"""Workspace-scoped AI metering without storing prompts or model responses."""
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Query, Request

from crm import db_from, require_workspace_access

router = APIRouter(prefix="/workspaces/{ws_id}/ai-usage", tags=["AI usage"])
_context = ContextVar("ai_usage_context", default={})
_db = None

PROCESS_LABELS = {
    "brain_training": "Business brain training",
    "roadmap_strategy": "Roadmap strategy",
    "roadmap_tasks": "Roadmap task planning",
    "manager_chat": "AI Manager chat",
    "blog_generation": "Blog generation",
    "seo_audit": "SEO audit",
    "creative_content": "Creative content",
    "analytics_task": "Analytics task",
    "sheet_column_mapping": "Sheet column mapping",
    "lead_qualification": "Lead qualification",
    "lead_context": "Lead context preparation",
}


def configure_usage(db):
    global _db
    _db = db


@contextmanager
def usage_scope(workspace_id, process, metadata=None):
    token = _context.set({"workspace_id": str(workspace_id), "process": str(process), "metadata": metadata or {}})
    try:
        yield
    finally:
        _context.reset(token)


def normalize_usage(value):
    value = value or {}
    input_tokens = int(value.get("inputTokens") or value.get("input_tokens") or value.get("prompt_tokens") or 0)
    output_tokens = int(value.get("outputTokens") or value.get("output_tokens") or value.get("completion_tokens") or 0)
    total_tokens = int(value.get("totalTokens") or value.get("total_tokens") or input_tokens + output_tokens)
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens}


async def record_usage(provider, model, usage, latency_ms, status="success", error_type=""):
    context = _context.get()
    if _db is None or not context.get("workspace_id"):
        return
    tokens = normalize_usage(usage)
    now = datetime.now(timezone.utc)
    doc = {
        "_id": ObjectId(), "workspace_id": context["workspace_id"], "process": context.get("process") or "other",
        "provider": str(provider or "unknown"), "model": str(model or "unknown"), **tokens,
        "metered": bool(tokens["total_tokens"]), "latency_ms": max(0, int(latency_ms or 0)),
        "status": status, "error_type": str(error_type or "")[:120], "metadata": context.get("metadata") or {},
        "created_at": now.isoformat(), "day": now.date().isoformat(),
    }
    try:
        await _db.ai_usage_events.insert_one(doc)
    except Exception:
        # Metering must never break the user-facing AI action.
        return


def summarize_usage(events, days, now=None):
    now = now or datetime.now(timezone.utc)
    by_day = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0})
    by_process = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0, "failed_calls": 0})
    by_model = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0})
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0, "failed_calls": 0, "metered_calls": 0, "latency_ms": 0}
    for event in events:
        totals["calls"] += 1
        totals["failed_calls"] += event.get("status") != "success"
        totals["metered_calls"] += bool(event.get("metered"))
        totals["latency_ms"] += int(event.get("latency_ms") or 0)
        process = event.get("process") or "other"
        model_key = f"{event.get('provider') or 'unknown'}::{event.get('model') or 'unknown'}"
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = int(event.get(key) or 0)
            totals[key] += value
            by_day[event.get("day") or str(event.get("created_at", ""))[:10]][key] += value
            by_process[process][key] += value
            by_model[model_key][key] += value
        by_day[event.get("day") or str(event.get("created_at", ""))[:10]]["calls"] += 1
        by_process[process]["calls"] += 1
        by_process[process]["failed_calls"] += event.get("status") != "success"
        by_model[model_key]["calls"] += 1
    daily = []
    for offset in range(days - 1, -1, -1):
        day = (now.date() - timedelta(days=offset)).isoformat()
        daily.append({"day": day, **by_day[day]})
    processes = [{"key": key, "label": PROCESS_LABELS.get(key, key.replace("_", " ").title()), **value} for key, value in by_process.items()]
    models = [{"provider": key.split("::", 1)[0], "model": key.split("::", 1)[1], **value} for key, value in by_model.items()]
    totals["average_latency_ms"] = round(totals.pop("latency_ms") / totals["calls"]) if totals["calls"] else 0
    return {"days": days, "totals": totals, "daily": daily,
            "processes": sorted(processes, key=lambda row: row["total_tokens"], reverse=True),
            "models": sorted(models, key=lambda row: row["total_tokens"], reverse=True)}


@router.get("")
async def usage_report(ws_id: str, request: Request, days: int = Query(default=30, ge=7, le=90)):
    await require_workspace_access(request, ws_id)
    since = (datetime.now(timezone.utc) - timedelta(days=days - 1)).date().isoformat()
    events = await db_from(request).ai_usage_events.find({"workspace_id": ws_id, "day": {"$gte": since}}, {"metadata": 0}).sort("created_at", -1).to_list(20000)
    report = summarize_usage(events, days)
    report["recent"] = [{key: value for key, value in event.items() if key != "_id"} for event in events[:12]]
    return report
