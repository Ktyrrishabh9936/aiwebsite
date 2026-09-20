import os
from typing import Literal
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from crm import db_from, require_workspace_access
from models import now_iso
from qualification_engine import CallResult, QualificationProfile, LeadQualificationEngine, RETRYABLE, validated_facts

router = APIRouter(prefix="/workspaces/{ws_id}/crm/qualification", tags=["qualification"])


def oid(value):
    if not ObjectId.is_valid(value):
        raise HTTPException(422, "Invalid identifier")
    return ObjectId(value)


def public(doc):
    return {**{k: v for k, v in doc.items() if k != "_id"}, "id": str(doc["_id"])}


@router.get("/profiles")
async def profiles(ws_id: str, request: Request):
    await require_workspace_access(request, ws_id)
    db = db_from(request)
    ws = await db.workspaces.find_one({"_id": oid(ws_id)})
    docs = await db.qualification_profiles.find({"workspace_id": ws_id}).sort("created_at", -1).to_list(200)
    default_profile = next((doc for doc in docs if str(doc["_id"]) == ws.get("qualification_profile_id")), None)
    default_voice_provider = ws.get("qualification_voice_provider") or (default_profile or {}).get("voice_provider") or "plivo"
    from plivo_calls import ensure_calling_workflow_config
    workflow = await ensure_calling_workflow_config(db, ws_id)
    template = QualificationProfile(voice_provider=default_voice_provider, retry={"max_attempts": workflow.get("max_attempts", 4), "retry_rules": [{"outcome": o.value, "delay_minutes": workflow.get("retry_delay_minutes", 30)} for o in sorted(RETRYABLE)]})
    return {"profiles": [public(doc) for doc in docs], "default_profile_id": ws.get("qualification_profile_id"),
        "default_voice_provider": default_voice_provider, "legacy_config": ws.get("ai_qualification_config"),
        "calling_settings": {key: workflow.get(key) for key in ("call_mode", "initial_delay_seconds", "timezone", "calling_window", "retry_delay_minutes")},
        "template": template.model_dump(mode="json"), "callback_authentication": "Workspace provider authentication; see Settings > Voice Providers"}


class CallingSettings(BaseModel):
    call_mode: Literal["automatic", "scheduled", "manual"]
    initial_delay_seconds: int = Field(default=300, ge=0, le=86400)
    timezone: str = "Asia/Kolkata"
    calling_window: dict = Field(default_factory=lambda: {"start": "09:30", "end": "19:00"})


@router.put("/calling-settings")
async def update_calling_settings(ws_id: str, request: Request, body: CallingSettings):
    await require_workspace_access(request, ws_id)
    db = db_from(request)
    from plivo_calls import ensure_calling_workflow_config, normalize_workflow_config, public_workflow_config
    old = await ensure_calling_workflow_config(db, ws_id)
    normalized = normalize_workflow_config(body.model_dump(), old)
    await db.plivo_workflow_configs.update_one({"workspace_id": ws_id}, {"$set": {**normalized, "updated_at": now_iso()}})
    if normalized["call_mode"] == "manual":
        await db.crm_leads.update_many({"workspace_id": ws_id, "qualification_call.status": "scheduled"}, {"$set": {
            "qualification_call.status": "manual", "qualification_call.scheduled_for": None,
            "qualification_call.auto_triggered": False, "updated_at": now_iso(),
        }})
    return public_workflow_config(await db.plivo_workflow_configs.find_one({"workspace_id": ws_id}))


@router.post("/profiles")
async def create_profile(ws_id: str, request: Request, body: QualificationProfile):
    await require_workspace_access(request, ws_id)
    doc = {"_id": ObjectId(), "workspace_id": ws_id, **body.model_dump(mode="json"), "created_at": now_iso(), "updated_at": now_iso()}
    try:
        await db_from(request).qualification_profiles.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "A profile already exists for this campaign")
    return public(doc)


@router.put("/profiles/{profile_id}")
async def update_profile(ws_id: str, profile_id: str, request: Request, body: QualificationProfile):
    await require_workspace_access(request, ws_id)
    db = db_from(request)
    query = {"_id": oid(profile_id), "workspace_id": ws_id}
    try:
        result = await db.qualification_profiles.update_one(query, {"$set": {**body.model_dump(mode="json"), "updated_at": now_iso()}})
    except DuplicateKeyError:
        raise HTTPException(409, "A profile already exists for this campaign")
    if not result.matched_count:
        raise HTTPException(404, "Profile not found")
    await db.workspaces.update_one(
        {"_id": oid(ws_id), "qualification_profile_id": profile_id},
        {"$set": {"qualification_voice_provider": body.voice_provider}},
    )
    return public(await db.qualification_profiles.find_one(query))


@router.post("/profiles/{profile_id}/default")
async def set_default(ws_id: str, profile_id: str, request: Request):
    await require_workspace_access(request, ws_id)
    db = db_from(request)
    profile = await db.qualification_profiles.find_one({"_id": oid(profile_id), "workspace_id": ws_id})
    if not profile:
        raise HTTPException(404, "Profile not found")
    voice_provider = profile.get("voice_provider") or "plivo"
    await db.workspaces.update_one({"_id": oid(ws_id)}, {"$set": {
        "qualification_profile_id": profile_id,
        "qualification_voice_provider": voice_provider,
    }})
    return {"default_profile_id": profile_id, "default_voice_provider": voice_provider}


class Assignment(BaseModel):
    profile_id: str | None = None


@router.put("/leads/{lead_id}/profile")
async def assign_profile(ws_id: str, lead_id: str, request: Request, body: Assignment):
    await require_workspace_access(request, ws_id)
    db = db_from(request)
    if body.profile_id and not await db.qualification_profiles.find_one({"_id": oid(body.profile_id), "workspace_id": ws_id}):
        raise HTTPException(404, "Profile not found")
    result = await db.crm_leads.update_one({"_id": oid(lead_id), "workspace_id": ws_id}, {"$set": {"qualification_profile_id": body.profile_id, "updated_at": now_iso()}})
    if not result.matched_count:
        raise HTTPException(404, "Lead not found")
    return {"profile_id": body.profile_id}


@router.get("/leads/{lead_id}/history")
async def history(ws_id: str, lead_id: str, request: Request):
    await require_workspace_access(request, ws_id)
    docs = await db_from(request).crm_call_logs.find({"workspace_id": ws_id, "lead_id": lead_id, "kind": "qualification_engine"}).sort("created_at", -1).to_list(100)
    # Raw provider payloads stay in the audit collection, not in the normal UI response.
    for doc in docs:
        doc.get("call_result", {}).pop("raw_provider_data", None)
    return [public(doc) for doc in docs]


class Preview(BaseModel):
    profile: QualificationProfile
    call: CallResult


@router.post("/preview")
async def preview(ws_id: str, request: Request, body: Preview):
    await require_workspace_access(request, ws_id)
    return LeadQualificationEngine().process(body.call, body.profile, validated_facts(body.call.extracted_data)).model_dump(mode="json")
