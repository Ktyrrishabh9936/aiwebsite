"""Opt-in device push subscriptions and durable follow-up delivery records."""
import asyncio
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from pymongo import ReturnDocument

from auth import get_current_user, get_current_user_and_workspace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/push", tags=["Web Push"])


def configuration():
    return {"public_key": os.getenv("VAPID_PUBLIC_KEY", ""),
            "private_key": os.getenv("VAPID_PRIVATE_KEY", ""),
            "subject": os.getenv("VAPID_SUBJECT", "mailto:support@arevei.ai")}


def configured():
    config = configuration()
    return bool(config["public_key"] and config["private_key"])


def endpoint_id(endpoint):
    return hashlib.sha256(endpoint.encode()).hexdigest()


class DeviceInput(BaseModel):
    endpoint: str = Field(max_length=2048)
    keys: dict[str, str]

    @field_validator("endpoint")
    @classmethod
    def safe_endpoint(cls, value):
        url = urlparse(value)
        host = url.hostname or ""
        # Subscription URLs are sent by our server: never allow arbitrary hosts.
        allowed = (host == "fcm.googleapis.com" or host == "updates.push.services.mozilla.com"
                   or host == "web.push.apple.com" or host.endswith(".push.apple.com")
                   or host.endswith(".notify.windows.com"))
        if url.scheme != "https" or not allowed or url.username or url.password or url.port not in (None, 443):
            raise ValueError("Unsupported push service endpoint")
        return value

    @field_validator("keys")
    @classmethod
    def valid_keys(cls, value):
        import base64
        try:
            for key, size in (("p256dh", 65), ("auth", 16)):
                encoded = value[key]
                if len(encoded) > 100 or len(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))) != size:
                    raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise ValueError("Invalid push subscription keys")
        return {key: value[key] for key in ("p256dh", "auth")}


class EndpointInput(BaseModel):
    endpoint: str = Field(max_length=2048)


@router.get("/config")
async def push_config(request: Request):
    await get_current_user(request, request.app.state.db)
    return {"enabled": configured(), "public_key": configuration()["public_key"]}


@router.get("/workspaces/{ws_id}/subscription")
async def subscription_status(ws_id: str, endpoint: str, request: Request):
    db = request.app.state.db
    user, _ = await get_current_user_and_workspace(request, db, ws_id)
    row = await db.push_subscriptions.find_one({"_id": endpoint_id(endpoint), "user_id": str(user["_id"]),
                                              "workspace_ids": ws_id, "active": True})
    return {"enabled": bool(row)}


@router.put("/workspaces/{ws_id}/subscription")
async def subscribe(ws_id: str, body: DeviceInput, request: Request):
    db = request.app.state.db
    user, _ = await get_current_user_and_workspace(request, db, ws_id)
    if not configured():
        raise HTTPException(503, "Push notifications are not configured on the server yet")
    now = datetime.now(timezone.utc).isoformat()
    key = endpoint_id(body.endpoint)
    existing = await db.push_subscriptions.find_one({"_id": key})
    # A shared browser may change accounts. Do not preserve the previous user's workspaces.
    if existing and existing.get("user_id") != str(user["_id"]):
        await db.push_subscriptions.update_one({"_id": key}, {"$set": {"workspace_ids": []}})
    await db.push_subscriptions.update_one({"_id": key}, {
        "$set": {"user_id": str(user["_id"]), "subscription": body.model_dump(), "active": True, "updated_at": now},
        "$setOnInsert": {"created_at": now}, "$addToSet": {"workspace_ids": ws_id}}, upsert=True)
    return {"enabled": True}


@router.delete("/workspaces/{ws_id}/subscription")
async def unsubscribe_workspace(ws_id: str, body: EndpointInput, request: Request):
    user = await get_current_user(request, request.app.state.db)
    await request.app.state.db.push_subscriptions.update_one(
        {"_id": endpoint_id(body.endpoint), "user_id": str(user["_id"])}, {"$pull": {"workspace_ids": ws_id}})
    return {"enabled": False}


@router.delete("/device")
async def unsubscribe_device(body: EndpointInput, request: Request):
    user = await get_current_user(request, request.app.state.db)
    await request.app.state.db.push_subscriptions.update_one(
        {"_id": endpoint_id(body.endpoint), "user_id": str(user["_id"])}, {"$set": {"active": False, "workspace_ids": []}})
    return {"enabled": False}


async def send_push(subscription, payload):
    from pywebpush import webpush
    config = configuration()
    await asyncio.to_thread(webpush, subscription_info=subscription, data=json.dumps(payload),
                            vapid_private_key=config["private_key"], vapid_claims={"sub": config["subject"]},
                            ttl=3600, timeout=10)


def payload_for(task, lead):
    values = lead.get("field_values") or {}
    name = values.get("full_name") or lead.get("full_name") or "Lead"
    ws_id, lead_id = task["workspace_id"], task["lead_id"]
    return {"title": f"Follow-up: {task['title']}", "body": f"{name} · Follow-up is due",
            "tag": f"crm-reminder-{ws_id}-{task['_id']}",
            "url": f"/app/w/{ws_id}/crm?lead={lead_id}", "reminder_id": str(task["_id"])}


async def dispatch_due(db, *, now=None, sender=send_push):
    if not configured():
        return {"sent": 0, "failed": 0, "enabled": False}
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=24)).isoformat()
    sent = failed = 0
    # Only the reminder creator receives it, on devices opted into that workspace.
    async for task in db.tasks.find({"source": "crm_reminder", "status": "pending",
                                    "scheduled_time": {"$gte": cutoff, "$lte": now.isoformat()}}).sort("scheduled_time", 1):
        user_id, ws_id, lead_id = task.get("created_by"), task.get("workspace_id"), task.get("lead_id")
        if not all(ObjectId.is_valid(value or "") for value in (user_id, ws_id, lead_id)):
            continue
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        workspace = await db.workspaces.find_one({"_id": ObjectId(ws_id)})
        if not user or not workspace or (str(workspace.get("user_id")) != user_id and user.get("role") != "admin"):
            continue
        lead = await db.crm_leads.find_one({"_id": ObjectId(lead_id), "workspace_id": ws_id, "deleted_at": None})
        if not lead:
            continue
        async for device in db.push_subscriptions.find({"user_id": user_id, "workspace_ids": ws_id, "active": True}):
            delivery_id = endpoint_id(f"{task['_id']}:{task['scheduled_time']}:{device['_id']}")
            await db.push_deliveries.update_one({"_id": delivery_id}, {"$setOnInsert": {
                "status": "pending", "attempts": 0, "next_attempt_at": now, "created_at": now,
                "expires_at": now + timedelta(days=7)}}, upsert=True)
            lease = secrets.token_hex(16)
            claimed = await db.push_deliveries.find_one_and_update({"_id": delivery_id, "status": {"$in": ["pending", "sending"]},
                "attempts": {"$lt": 5}, "next_attempt_at": {"$lte": now}},
                {"$set": {"status": "sending", "lease": lease, "next_attempt_at": now + timedelta(minutes=2)},
                 "$inc": {"attempts": 1}}, return_document=ReturnDocument.AFTER)
            if not claimed:
                continue
            # Recheck edits, completion, subscription disablement just before delivery.
            current = await db.tasks.find_one({"_id": task["_id"], "status": "pending", "scheduled_time": task["scheduled_time"]})
            active = await db.push_subscriptions.find_one({"_id": device["_id"], "user_id": user_id, "workspace_ids": ws_id, "active": True})
            if not current or not active:
                await db.push_deliveries.delete_one({"_id": delivery_id, "lease": lease})
                continue
            try:
                await sender(active["subscription"], payload_for(current, lead))
                await db.push_deliveries.update_one({"_id": delivery_id, "lease": lease}, {"$set": {"status": "sent", "sent_at": now}})
                sent += 1
            except Exception as error:
                code = getattr(getattr(error, "response", None), "status_code", None)
                if code in (404, 410):
                    await db.push_subscriptions.update_one({"_id": device["_id"]}, {"$set": {"active": False}})
                await db.push_deliveries.update_one({"_id": delivery_id, "lease": lease}, {"$set": {"status": "failed" if code in (404, 410) else "pending"}})
                failed += 1
                logger.warning("Follow-up push failed: delivery=%s status=%s error_type=%s", delivery_id, code, type(error).__name__)
    return {"sent": sent, "failed": failed, "enabled": True}


@router.api_route("/dispatch", methods=["GET", "POST"])
async def dispatch(request: Request):
    secret = os.getenv("CRON_SECRET", "")
    if not secret or not secrets.compare_digest(request.headers.get("authorization", ""), f"Bearer {secret}"):
        raise HTTPException(401, "Unauthorized")
    return await dispatch_due(request.app.state.db)


async def push_scheduler(db):
    while True:
        try:
            await dispatch_due(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Follow-up push scheduler failed")
        await asyncio.sleep(30)
