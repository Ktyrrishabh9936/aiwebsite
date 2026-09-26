"""Workspace-scoped Twilio SMS for CRM leads."""

import re

import httpx
from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Request

from crm import db_from, require_workspace_access
from models import now_iso
from voice_config import decrypt, encrypt

router = APIRouter(prefix="/workspaces/{ws_id}/crm/sms", dependencies=[Depends(require_workspace_access)])
E164 = re.compile(r"\+[1-9]\d{7,14}\Z")
ALPHANUMERIC_SENDER = re.compile(r"[A-Za-z0-9 +_&-]{1,11}\Z")
ACCOUNT_SID = re.compile(r"AC[0-9a-fA-F]{32}\Z")
SERVICE_SID = re.compile(r"MG[0-9a-fA-F]{32}\Z")
MESSAGE_SID = re.compile(r"(?:SM|MM)[0-9a-fA-F]{32}\Z")


def recipient_phone(value):
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+") and E164.fullmatch("+" + digits):
        return "+" + digits
    if len(digits) == 10:
        return "+91" + digits
    raise HTTPException(422, "Save a valid lead phone number with country code before sending SMS")


def public_config(doc):
    if not doc:
        return {"configured": False, "enabled": False, "account_sid": "", "from_number": "", "messaging_service_sid": "", "token_present": False}
    return {key: doc.get(key) for key in ("enabled", "account_sid", "from_number", "messaging_service_sid")} | {
        "configured": bool(doc.get("encrypted_auth_token")), "token_present": bool(doc.get("encrypted_auth_token"))
    }


async def config_for(db, ws_id, *, enabled=False):
    doc = await db.workspace_sms_configs.find_one({"workspace_id": ws_id})
    if not doc or not doc.get("encrypted_auth_token"):
        raise HTTPException(409, "Configure Twilio SMS in CRM Settings first")
    if enabled and not doc.get("enabled"):
        raise HTTPException(409, "Twilio SMS is disabled in CRM Settings")
    return doc


def credentials(ws_id, doc):
    return decrypt(ws_id, "twilio_sms", doc["encrypted_auth_token"])["auth_token"]


async def lead_for(db, ws_id, lead_id, *, active=False):
    if not ObjectId.is_valid(lead_id):
        raise HTTPException(404, "Lead not found")
    lead = await db.crm_leads.find_one({"workspace_id": ws_id, "_id": ObjectId(lead_id)})
    if not lead:
        raise HTTPException(404, "Lead not found")
    if active and lead.get("deleted_at"):
        raise HTTPException(409, "Restore this lead before sending SMS")
    return lead


def public_message(doc):
    return {"id": str(doc["_id"]), **{key: doc.get(key) for key in ("to", "body", "status", "error_code", "created_at", "updated_at")}}


@router.get("/config")
async def get_config(ws_id: str, request: Request):
    doc = await db_from(request).workspace_sms_configs.find_one({"workspace_id": ws_id})
    return public_config(doc)


@router.put("/config")
async def save_config(ws_id: str, request: Request, body: dict = Body(...)):
    if set(body) - {"enabled", "account_sid", "auth_token", "from_number", "messaging_service_sid"}:
        raise HTTPException(422, "Unknown Twilio setting")
    db = db_from(request)
    old = await db.workspace_sms_configs.find_one({"workspace_id": ws_id})
    sid = str(body.get("account_sid") or "").strip()
    sender = str(body.get("from_number") or "").strip()
    service = str(body.get("messaging_service_sid") or "").strip()
    token = str(body.get("auth_token") or "").strip()
    if not ACCOUNT_SID.fullmatch(sid):
        raise HTTPException(422, "Enter a valid Twilio Account SID")
    if not sender and not service:
        raise HTTPException(422, "Enter a Twilio sender number or Messaging Service SID")
    if sender and not (E164.fullmatch(sender) or (ALPHANUMERIC_SENDER.fullmatch(sender) and re.search(r"[A-Za-z]", sender))):
        raise HTTPException(422, "Use an international sender number or an alphanumeric sender ID of up to 11 characters")
    if service and not SERVICE_SID.fullmatch(service):
        raise HTTPException(422, "Enter a valid Twilio Messaging Service SID")
    if not token and old and sid == old.get("account_sid"):
        token = credentials(ws_id, old)
    if not token:
        raise HTTPException(422, "Enter a Twilio Auth Token")
    doc = {"workspace_id": ws_id, "enabled": bool(body.get("enabled", True)), "account_sid": sid,
           "from_number": sender, "messaging_service_sid": service,
           "encrypted_auth_token": encrypt(ws_id, "twilio_sms", {"auth_token": token}), "updated_at": now_iso()}
    await db.workspace_sms_configs.update_one({"workspace_id": ws_id}, {"$set": doc}, upsert=True)
    return public_config(doc)


@router.get("/leads/{lead_id}")
async def list_messages(ws_id: str, lead_id: str, request: Request):
    db = db_from(request)
    await lead_for(db, ws_id, lead_id)
    cursor = db.crm_sms_messages.find({"workspace_id": ws_id, "lead_id": lead_id}).sort("created_at", -1).limit(20)
    return [public_message(doc) async for doc in cursor]


@router.post("/leads/{lead_id}")
async def send_message(ws_id: str, lead_id: str, request: Request, body: dict = Body(...)):
    if set(body) != {"text"} or not isinstance(body.get("text"), str):
        raise HTTPException(422, "Enter an SMS message")
    message = body["text"].strip()
    if not message or len(message) > 1600:
        raise HTTPException(422, "SMS message must contain 1 to 1600 characters")
    db = db_from(request)
    lead = await lead_for(db, ws_id, lead_id, active=True)
    to = recipient_phone((lead.get("field_values") or {}).get("phone") or lead.get("phone"))
    config = await config_for(db, ws_id, enabled=True)
    form = {"To": to, "Body": message}
    if config.get("messaging_service_sid"):
        form["MessagingServiceSid"] = config["messaging_service_sid"]
    else:
        form["From"] = config["from_number"]
    url = f"https://api.twilio.com/2010-04-01/Accounts/{config['account_sid']}/Messages.json"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, data=form, auth=(config["account_sid"], credentials(ws_id, config)))
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError):
        raise HTTPException(502, "Could not connect to Twilio. Check the backend network or proxy settings; the SMS request was not sent") from None
    except httpx.HTTPError:
        raise HTTPException(502, "Twilio did not respond. Check the Twilio console before retrying to avoid a duplicate SMS") from None
    if response.status_code >= 400:
        error = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        code = error.get("code") if isinstance(error, dict) else None
        raise HTTPException(502, f"Twilio rejected this SMS{f' (code {code})' if isinstance(code, int) else ''}. Check your sender, recipient, balance, and Twilio console")
    data = response.json()
    if not MESSAGE_SID.fullmatch(str(data.get("sid") or "")):
        raise HTTPException(502, "Twilio returned an invalid message ID. Check the Twilio console before retrying")
    doc = {"workspace_id": ws_id, "lead_id": lead_id, "twilio_sid": data["sid"], "to": to,
           "body": message, "status": data.get("status") or "queued", "error_code": None,
           "created_at": now_iso(), "updated_at": now_iso()}
    await db.crm_sms_messages.insert_one(doc)
    return public_message(doc)


@router.post("/leads/{lead_id}/{message_id}/refresh")
async def refresh_message(ws_id: str, lead_id: str, message_id: str, request: Request):
    db = db_from(request)
    if not ObjectId.is_valid(message_id):
        raise HTTPException(404, "SMS not found")
    doc = await db.crm_sms_messages.find_one({"_id": ObjectId(message_id), "workspace_id": ws_id, "lead_id": lead_id})
    if not doc:
        raise HTTPException(404, "SMS not found")
    config = await config_for(db, ws_id)
    sid = doc.get("twilio_sid")
    if not MESSAGE_SID.fullmatch(str(sid or "")):
        raise HTTPException(409, "SMS cannot be refreshed")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{config['account_sid']}/Messages/{sid}.json"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, auth=(config["account_sid"], credentials(ws_id, config)))
    except httpx.HTTPError:
        raise HTTPException(502, "Could not retrieve SMS status from Twilio") from None
    if response.status_code >= 400:
        raise HTTPException(502, "Twilio could not retrieve this SMS status")
    data = response.json()
    patch = {"status": data.get("status") or doc["status"], "error_code": data.get("error_code"), "updated_at": now_iso()}
    await db.crm_sms_messages.update_one({"_id": doc["_id"], "workspace_id": ws_id}, {"$set": patch})
    return public_message({**doc, **patch})
