from bson import ObjectId
from fastapi import APIRouter, Body, HTTPException, Query, Request

from crm import db_from, require_workspace_access
from models import now_iso
from plivo_calls import (
    AGENT_CONFIGS_COLLECTION,
    CALL_SESSIONS_COLLECTION,
    agent_readiness,
    legacy_agent_config_from_env,
    normalize_agent_config,
    sanitize_agent_config,
)


router = APIRouter(prefix="/workspaces/{ws_id}/crm/plivo")


def oid(value):
    try:
        return ObjectId(str(value))
    except Exception:
        raise HTTPException(status_code=404, detail="Plivo agent configuration not found")


def doc_out(doc):
    if not doc:
        return None
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


async def _workspace_agents(db, ws_id):
    docs = await db[AGENT_CONFIGS_COLLECTION].find({"workspace_id": ws_id}).sort("created_at", -1).to_list(100)
    return [sanitize_agent_config(doc) for doc in docs]


async def _selected_agent_id(db, ws_id):
    selected = await db[AGENT_CONFIGS_COLLECTION].find_one({"workspace_id": ws_id, "enabled": True, "is_default": True})
    if selected:
        return str(selected["_id"])
    first = await db[AGENT_CONFIGS_COLLECTION].find_one({"workspace_id": ws_id, "enabled": True})
    if first:
        return str(first["_id"])
    legacy = legacy_agent_config_from_env()
    return "environment" if legacy else ""


@router.get("/agents")
async def list_plivo_agents(ws_id: str, request: Request):
    await require_workspace_access(request, ws_id)
    db = db_from(request)
    agents = await _workspace_agents(db, ws_id)
    legacy = legacy_agent_config_from_env()
    return {
        "agents": agents,
        "selected_agent_config_id": await _selected_agent_id(db, ws_id),
        "legacy_environment_agent": sanitize_agent_config(legacy) if legacy else None,
    }


@router.post("/agents")
async def create_plivo_agent(ws_id: str, request: Request, body: dict = Body(...)):
    await require_workspace_access(request, ws_id)
    db = db_from(request)
    config = normalize_agent_config(body)
    config["workspace_id"] = ws_id
    config["credential_ref"] = ""
    existing_default = await db[AGENT_CONFIGS_COLLECTION].find_one({"workspace_id": ws_id, "enabled": True, "is_default": True})
    if not existing_default and config.get("enabled", True):
        config["is_default"] = True
    result = await db[AGENT_CONFIGS_COLLECTION].insert_one(config)
    config["_id"] = result.inserted_id
    credential_ref = f"plivo_agent_config:{result.inserted_id}:trigger_auth"
    await db[AGENT_CONFIGS_COLLECTION].update_one(
        {"_id": result.inserted_id},
        {"$set": {"credential_ref": credential_ref, "updated_at": now_iso()}},
    )
    if config.get("is_default"):
        await db[AGENT_CONFIGS_COLLECTION].update_many(
            {"workspace_id": ws_id, "_id": {"$ne": result.inserted_id}},
            {"$set": {"is_default": False, "updated_at": now_iso()}},
        )
    saved = await db[AGENT_CONFIGS_COLLECTION].find_one({"workspace_id": ws_id, "_id": result.inserted_id})
    return sanitize_agent_config(saved)


@router.patch("/agents/{agent_id}")
async def update_plivo_agent(ws_id: str, agent_id: str, request: Request, body: dict = Body(...)):
    await require_workspace_access(request, ws_id)
    db = db_from(request)
    existing = await db[AGENT_CONFIGS_COLLECTION].find_one({"workspace_id": ws_id, "_id": oid(agent_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Plivo agent configuration not found")
    config = normalize_agent_config(body, existing)
    config.pop("_id", None)
    config["workspace_id"] = ws_id
    if not config.get("credential_ref"):
        config["credential_ref"] = f"plivo_agent_config:{agent_id}:trigger_auth"
    if not config.get("enabled", True):
        config["is_default"] = False
    await db[AGENT_CONFIGS_COLLECTION].update_one({"workspace_id": ws_id, "_id": oid(agent_id)}, {"$set": config})
    if config.get("is_default"):
        await db[AGENT_CONFIGS_COLLECTION].update_many(
            {"workspace_id": ws_id, "_id": {"$ne": oid(agent_id)}},
            {"$set": {"is_default": False, "updated_at": now_iso()}},
        )
    saved = await db[AGENT_CONFIGS_COLLECTION].find_one({"workspace_id": ws_id, "_id": oid(agent_id)})
    return sanitize_agent_config(saved)


@router.post("/agents/{agent_id}/select")
async def select_plivo_agent(ws_id: str, agent_id: str, request: Request):
    await require_workspace_access(request, ws_id)
    db = db_from(request)
    agent = await db[AGENT_CONFIGS_COLLECTION].find_one({"workspace_id": ws_id, "_id": oid(agent_id)})
    if not agent:
        raise HTTPException(status_code=404, detail="Plivo agent configuration not found")
    readiness = agent_readiness(agent)
    if not readiness["ready"]:
        raise HTTPException(status_code=400, detail=f"Plivo agent is not ready: missing {', '.join(readiness['missing'])}")
    await db[AGENT_CONFIGS_COLLECTION].update_many(
        {"workspace_id": ws_id},
        {"$set": {"is_default": False, "updated_at": now_iso()}},
    )
    await db[AGENT_CONFIGS_COLLECTION].update_one(
        {"workspace_id": ws_id, "_id": oid(agent_id)},
        {"$set": {"is_default": True, "enabled": True, "updated_at": now_iso()}},
    )
    saved = await db[AGENT_CONFIGS_COLLECTION].find_one({"workspace_id": ws_id, "_id": oid(agent_id)})
    return sanitize_agent_config(saved)


@router.get("/call-sessions")
async def list_plivo_call_sessions(
    ws_id: str,
    request: Request,
    lead_id: str = Query(None),
    limit: int = Query(25),
):
    await require_workspace_access(request, ws_id)
    db = db_from(request)
    query = {"workspace_id": ws_id}
    if lead_id:
        query["lead_id"] = str(lead_id)
    safe_limit = max(1, min(int(limit or 25), 100))
    docs = await db[CALL_SESSIONS_COLLECTION].find(query).sort("created_at", -1).to_list(safe_limit)
    return [doc_out(doc) for doc in docs]
