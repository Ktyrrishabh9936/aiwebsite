"""Workspace connectors: outgoing email and calendar.

Email works with no setup: the platform SMTP account sends on the workspace's behalf. A workspace
may instead connect its own mailbox (SMTP credentials or Gmail). Calendars use Google Calendar.
Secrets are encrypted at rest and never returned by the API.
"""
import asyncio
import base64
import ipaddress
import json
import logging
import os
import re
import smtplib
import socket
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from auth import get_current_user_and_workspace, get_jwt_secret
from models import now_iso

logger = logging.getLogger("connectors")
router = APIRouter(prefix="/workspaces/{ws_id}/connectors", tags=["Connectors"])

COLLECTION = "workspace_connectors"
STATE_PREFIX = "conn."
SMTP_PORTS = {465, 587, 2525}
GOOGLE_SCOPES = {
    "calendar": ["https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/calendar.freebusy"],
    "gmail": ["https://www.googleapis.com/auth/gmail.send"],
}
BASE_SCOPE = "https://www.googleapis.com/auth/userinfo.email"


# ---------------------------------------------------------------- secrets
def cipher():
    raw = os.getenv("CONNECTOR_CREDENTIAL_KEYS") or os.getenv("VOICE_CREDENTIAL_KEYS", "")
    try:
        keys = [Fernet(key.strip().encode()) for key in raw.split(",") if key.strip()]
        if not keys:
            raise ValueError()
        return MultiFernet(keys)
    except ValueError:
        raise HTTPException(503, "Connector credential encryption is not configured on the server") from None


def seal(ws_id, kind, secrets):
    return cipher().encrypt(json.dumps({"workspace_id": str(ws_id), "kind": kind, "secrets": secrets}).encode()).decode()


def unseal(ws_id, kind, value):
    try:
        data = json.loads(cipher().decrypt(value.encode()))
        if data["workspace_id"] != str(ws_id) or data["kind"] != kind:
            raise ValueError()
        return data["secrets"]
    except (InvalidToken, ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(503, "Saved connector credentials cannot be read. Please reconnect.") from None


async def get_connector(db, ws_id, kind):
    return await db[COLLECTION].find_one({"workspace_id": str(ws_id), "kind": kind})


# ---------------------------------------------------------------- email
def platform_smtp():
    """The platform's own SMTP account, used whenever a workspace has not connected a mailbox."""
    keys = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_FROM")
    if not all(os.environ.get(key) for key in keys):
        return None
    return {"host": os.environ["SMTP_HOST"], "port": int(os.environ["SMTP_PORT"]), "username": os.environ["SMTP_USER"],
            "password": os.environ["SMTP_PASS"], "from_email": os.environ["SMTP_FROM"],
            "from_name": os.environ.get("SMTP_FROM_NAME", "AI Manager")}


def assert_public_host(host):
    """User-supplied mail servers must be public hosts; never let the backend dial internal addresses."""
    host = (host or "").strip().lower()
    if not host or len(host) > 253 or any(ch in host for ch in "/@: \t"):
        raise HTTPException(422, "Enter a valid SMTP server name")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except (socket.gaierror, UnicodeError):
        raise HTTPException(422, "The SMTP server name could not be found") from None
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise HTTPException(422, "This SMTP server address is not allowed")
    return host


def _open_smtp(transport, timeout=15):
    port = int(transport["port"])
    if port == 465:
        server = smtplib.SMTP_SSL(transport["host"], port, timeout=timeout)
    else:
        server = smtplib.SMTP(transport["host"], port, timeout=timeout)
        server.starttls()
    server.login(transport["username"], transport["password"])
    return server


def build_message(to_email, subject, html_body, from_email, from_name="", reply_to=""):
    message = MIMEMultipart("alternative")
    message["Subject"] = " ".join(str(subject).split())[:200]
    message["From"] = formataddr((" ".join(str(from_name or "").split())[:80], from_email)) if from_name else from_email
    message["To"] = to_email
    if valid_email(reply_to):
        message["Reply-To"] = valid_email(reply_to)
    message.attach(MIMEText("Please view this email in an HTML-capable email client.", "plain"))
    message.attach(MIMEText(html_body, "html"))
    return message


def _smtp_send_sync(transport, to_email, subject, html_body, from_name, reply_to):
    message = build_message(to_email, subject, html_body, transport["from_email"], from_name or transport.get("from_name"), reply_to)
    with _open_smtp(transport) as server:
        server.sendmail(transport["from_email"], [to_email], message.as_string())


async def smtp_send(transport, to_email, subject, html_body, from_name="", reply_to=""):
    await asyncio.to_thread(_smtp_send_sync, transport, to_email, subject, html_body, from_name, reply_to)


_ATOM = r"[^\s@<>,;:\"()\[\]\\]+"
EMAIL_PATTERN = re.compile(_ATOM + "@" + _ATOM + r"\." + _ATOM)


def valid_email(value):
    """A single plain address, or "" (rejects lists, display names, whitespace and header characters)."""
    address = str(value or "").strip()
    return address if len(address) <= 254 and EMAIL_PATTERN.fullmatch(address) else ""


async def send_workspace_email(db, ws, to_email, subject, html_body, *, reply_to=""):
    """Send one email for a workspace: its own mailbox when connected, otherwise the platform SMTP.

    Returns {"sent": bool, "via": "smtp"|"gmail"|"platform"|None, "error": str}. Never raises.
    """
    to_email = valid_email(to_email)
    if not to_email:
        return {"sent": False, "via": None, "error": "No valid email address"}
    ws_id, name = str(ws["_id"]), ws.get("name") or "AI Manager"
    fallback_reason = ""
    try:
        own = await get_connector(db, ws_id, "email_smtp")
        if own and own.get("enabled", True):
            transport = {**own["config"], "password": unseal(ws_id, "email_smtp", own["secrets"])["password"]}
            await asyncio.to_thread(assert_public_host, transport["host"])  # re-checked on every send, not only when saved
            await smtp_send(transport, to_email, subject, html_body, own["config"].get("from_name") or name, reply_to)
            return {"sent": True, "via": "smtp", "error": ""}
        google = await get_connector(db, ws_id, "google")
        if google and google.get("send_email") and "gmail" in (google.get("services") or []):
            await gmail_send(db, ws_id, google, to_email, subject, html_body, name, reply_to)
            return {"sent": True, "via": "gmail", "error": ""}
    except Exception as exc:  # the workspace mailbox failed: record it and still deliver from the platform
        fallback_reason = type(exc).__name__
        logger.warning("workspace_mailbox_failed workspace=%s error_type=%s", ws_id, fallback_reason)
        await db[COLLECTION].update_many({"workspace_id": ws_id, "kind": {"$in": ["email_smtp", "google"]}},
                                         {"$set": {"last_email_error": fallback_reason, "last_email_error_at": now_iso()}})
    transport = platform_smtp()
    if not transport:
        return {"sent": False, "via": None, "error": "Email is not configured on the server"}
    try:
        await smtp_send(transport, to_email, subject, html_body, f"{name} via Arevei" if name else "", reply_to)
        return {"sent": True, "via": "platform", "error": fallback_reason}
    except Exception as exc:
        logger.warning("platform_email_failed workspace=%s error_type=%s", ws_id, type(exc).__name__)
        return {"sent": False, "via": None, "error": "The email could not be delivered"}


# ---------------------------------------------------------------- google
def google_credentials():
    client_id, client_secret = os.environ.get("GOOGLE_CLIENT_ID"), os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(503, "Google sign-in is not configured on the server")
    return client_id, client_secret


def sign_state(ws_id, user_id, services):
    payload = {"ws": str(ws_id), "sub": str(user_id), "svc": services, "exp": datetime.now(timezone.utc) + timedelta(minutes=15)}
    return STATE_PREFIX + jwt.encode(payload, get_jwt_secret(), algorithm="HS256")


def read_state(state):
    try:
        return jwt.decode(str(state)[len(STATE_PREFIX):], get_jwt_secret(), algorithms=["HS256"])
    except jwt.InvalidTokenError:
        raise HTTPException(400, "This sign-in link has expired. Start the connection again.") from None


def is_connector_state(state):
    return isinstance(state, str) and state.startswith(STATE_PREFIX)


def _popup_page(message, ok):
    event = "CONNECTOR_CONNECTED" if ok else "CONNECTOR_FAILED"
    safe = json.dumps(message)
    return HTMLResponse(f"""<html><body style="font-family:sans-serif;padding:24px">
<p id="m"></p><script>document.getElementById('m').textContent = {safe};
if (window.opener) {{ window.opener.postMessage({{ type: '{event}' }}, '*'); }}
setTimeout(function () {{ window.close(); }}, {600 if ok else 4000});</script></body></html>""")


async def google_oauth_callback(request, code, state):
    """Completes the Google sign-in started by /connectors/google/start (shares the Sheets callback URL)."""
    claims = read_state(state)
    from google_sheets import get_redirect_uri
    client_id, client_secret = google_credentials()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": client_id, "client_secret": client_secret,
            "redirect_uri": get_redirect_uri(request), "grant_type": "authorization_code"})
        if response.status_code != 200:
            return _popup_page("Google did not complete the connection. Please try again.", False)
        tokens = response.json()
        profile = await client.get("https://www.googleapis.com/oauth2/v3/userinfo",
                                   headers={"Authorization": f"Bearer {tokens['access_token']}"})
    email = profile.json().get("email") if profile.status_code == 200 else None
    db, ws_id = request.app.state.db, claims["ws"]
    existing = await get_connector(db, ws_id, "google")
    granted = set(str(tokens.get("scope") or "").split())
    services = [name for name, scopes in GOOGLE_SCOPES.items() if set(scopes) <= granted]
    if not services:
        return _popup_page("Google access was not granted. Tick the permission boxes and try again.", False)
    secrets = {"access_token": tokens["access_token"], "refresh_token": tokens.get("refresh_token"),
               "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in") or 3600))).isoformat()}
    if not secrets["refresh_token"] and existing:
        secrets["refresh_token"] = unseal(ws_id, "google", existing["secrets"]).get("refresh_token")
    if not secrets["refresh_token"]:
        return _popup_page("Google did not grant ongoing access. Remove Arevei from your Google account permissions and connect again.", False)
    await db[COLLECTION].update_one({"workspace_id": ws_id, "kind": "google"}, {
        "$set": {"account_email": email, "services": sorted(services), "secrets": seal(ws_id, "google", secrets),
                 "enabled": True, "status": "connected", "connected_by": claims["sub"], "updated_at": now_iso(),
                 # Gmail sending switches on when it is first granted; afterwards the owner's toggle is kept.
                 "send_email": "gmail" in services and ("gmail" not in ((existing or {}).get("services") or []) or bool(existing.get("send_email")))},
        "$setOnInsert": {"created_at": now_iso(), "calendar_id": "primary"}}, upsert=True)
    return _popup_page("Connected. You can close this window.", True)


async def google_access_token(db, ws_id, connector=None):
    connector = connector or await get_connector(db, ws_id, "google")
    if not connector:
        raise HTTPException(409, "Google is not connected for this workspace")
    secrets = unseal(ws_id, "google", connector["secrets"])
    try:
        fresh = datetime.fromisoformat(secrets["expires_at"]) - datetime.now(timezone.utc) > timedelta(seconds=90)
    except (KeyError, ValueError, TypeError):
        fresh = False
    if fresh:
        return secrets["access_token"]
    client_id, client_secret = google_credentials()
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id": client_id, "client_secret": client_secret,
            "refresh_token": secrets.get("refresh_token"), "grant_type": "refresh_token"})
    if response.status_code != 200:
        await db[COLLECTION].update_one({"_id": connector["_id"]}, {"$set": {"status": "reconnect_required", "updated_at": now_iso()}})
        raise HTTPException(409, "Google access has expired. Reconnect Google in Settings.")
    data = response.json()
    secrets.update({"access_token": data["access_token"],
                    "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in") or 3600))).isoformat()})
    await db[COLLECTION].update_one({"_id": connector["_id"]}, {"$set": {"secrets": seal(ws_id, "google", secrets), "status": "connected", "updated_at": now_iso()}})
    return secrets["access_token"]


async def _google(db, ws_id, method, url, connector=None, **kwargs):
    token = await google_access_token(db, ws_id, connector)
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs)
    if response.status_code >= 400:
        logger.warning("google_api_failed workspace=%s status=%s", ws_id, response.status_code)
        raise HTTPException(502, "Google did not accept the request")
    return response.json() if response.content else {}


async def gmail_send(db, ws_id, connector, to_email, subject, html_body, from_name="", reply_to=""):
    message = build_message(to_email, subject, html_body, connector.get("account_email") or "me", from_name, reply_to)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    await _google(db, ws_id, "POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", connector, json={"raw": raw})


# ---------------------------------------------------------------- calendar
class GoogleCalendar:
    """Calendar provider interface: busy(), create(), update(), cancel(). Other providers implement the same four."""
    name = "google"

    def __init__(self, db, ws_id, connector):
        self.db, self.ws_id, self.connector = db, ws_id, connector
        self.calendar_id = urllib.parse.quote(connector.get("calendar_id") or "primary", safe="")

    async def busy(self, start, end):
        data = await _google(self.db, self.ws_id, "POST", "https://www.googleapis.com/calendar/v3/freeBusy", self.connector,
                             json={"timeMin": start.isoformat(), "timeMax": end.isoformat(),
                                   "items": [{"id": self.connector.get("calendar_id") or "primary"}]})
        slots = []
        for calendar in (data.get("calendars") or {}).values():
            for item in calendar.get("busy") or []:
                try:
                    slots.append((datetime.fromisoformat(item["start"].replace("Z", "+00:00")),
                                  datetime.fromisoformat(item["end"].replace("Z", "+00:00"))))
                except (KeyError, ValueError):
                    continue
        return slots

    def _body(self, summary, description, start, end, attendee_email):
        body = {"summary": summary[:200], "description": description[:4000],
                "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}
        if attendee_email:
            body["attendees"] = [{"email": attendee_email}]
        return body

    @staticmethod
    def _event(data, event_id=""):
        video = next((point.get("uri") for point in (data.get("conferenceData") or {}).get("entryPoints") or []
                      if isinstance(point, dict) and point.get("entryPointType") == "video"), "")
        return {"event_id": data.get("id", event_id), "link": data.get("htmlLink", ""), "meet_link": data.get("hangoutLink") or video or ""}

    async def create(self, summary, description, start, end, attendee_email=""):
        data = await _google(self.db, self.ws_id, "POST",
                             f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events?sendUpdates=all&conferenceDataVersion=1",
                             self.connector, json={**self._body(summary, description, start, end, attendee_email),
                                                   "conferenceData": {"createRequest": {"requestId": uuid.uuid4().hex, "conferenceSolutionKey": {"type": "hangoutsMeet"}}}})
        return self._event(data)

    async def update(self, event_id, summary, description, start, end, attendee_email=""):
        data = await _google(self.db, self.ws_id, "PATCH",
                             f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events/{urllib.parse.quote(event_id, safe='')}?sendUpdates=all",
                             self.connector, json=self._body(summary, description, start, end, attendee_email))
        return self._event(data, event_id)  # moving an event keeps its Meet link

    async def cancel(self, event_id):
        token = await google_access_token(self.db, self.ws_id, self.connector)
        async with httpx.AsyncClient(timeout=15) as client:
            await client.delete(f"https://www.googleapis.com/calendar/v3/calendars/{self.calendar_id}/events/{urllib.parse.quote(event_id, safe='')}?sendUpdates=all",
                                headers={"Authorization": f"Bearer {token}"})


async def calendar_for(db, ws_id):
    """The workspace's connected calendar, or None when no calendar is connected."""
    connector = await get_connector(db, ws_id, "google")
    if connector and connector.get("enabled", True) and "calendar" in (connector.get("services") or []) and connector.get("status") != "reconnect_required":
        return GoogleCalendar(db, str(ws_id), connector)
    return None


# ---------------------------------------------------------------- API
class SmtpInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = Field(min_length=3, max_length=253)
    port: int = Field(default=587)
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=500)
    from_email: EmailStr
    from_name: str = Field(default="", max_length=80)


class GoogleStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    services: list[str] = Field(default_factory=lambda: ["calendar"], max_length=2)


class GooglePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    send_email: bool | None = None
    calendar_id: str | None = Field(default=None, max_length=300)


async def owner(request, ws_id):
    db = request.app.state.db
    user, ws = await get_current_user_and_workspace(request, db, ws_id)
    return db, user, ws


async def connector_status(db, ws_id):
    smtp, google, calendly = await asyncio.gather(get_connector(db, ws_id, "email_smtp"), get_connector(db, ws_id, "google"),
                                                  get_connector(db, ws_id, "calendly"))
    google_calendar = bool(google and "calendar" in ((google or {}).get("services") or []) and google.get("status") != "reconnect_required")
    services = (google or {}).get("services") or []
    gmail_active = bool(google and google.get("send_email") and "gmail" in services)
    mode = "smtp" if smtp and smtp.get("enabled", True) else "gmail" if gmail_active else "platform"
    platform = platform_smtp()
    return {
        "email": {"mode": mode, "platform_ready": bool(platform),
                  "sending_from": (smtp or {}).get("config", {}).get("from_email") if mode == "smtp"
                  else (google or {}).get("account_email") if mode == "gmail" else (platform or {}).get("from_email"),
                  "smtp": {"host": smtp["config"]["host"], "port": smtp["config"]["port"], "username": smtp["config"]["username"],
                           "from_email": smtp["config"]["from_email"], "from_name": smtp["config"].get("from_name", ""),
                           "last_error": smtp.get("last_email_error")} if smtp else None},
        "google": {"connected": bool(google), "account_email": (google or {}).get("account_email"), "services": services,
                   "status": (google or {}).get("status"), "send_email": gmail_active,
                   "calendar_id": (google or {}).get("calendar_id") or "primary"} if google else {"connected": False, "services": []},
        "calendly": {"connected": bool(calendly), "url": (calendly or {}).get("config", {}).get("url")},
        # A booking link takes over meeting requests; otherwise Google Calendar is used to find a free time.
        "calendar": {"connected": google_calendar or bool(calendly), "google": google_calendar,
                     "provider": "calendly" if calendly else "google" if google_calendar else None},
    }


@router.get("")
async def get_connectors(ws_id: str, request: Request):
    db, _, _ = await owner(request, ws_id)
    return await connector_status(db, ws_id)


@router.put("/email/smtp")
async def save_smtp(ws_id: str, request: Request, body: SmtpInput):
    db, _, _ = await owner(request, ws_id)
    if body.port not in SMTP_PORTS:
        raise HTTPException(422, "Use port 465, 587 or 2525")
    host = await asyncio.to_thread(assert_public_host, body.host)
    config = {"host": host, "port": body.port, "username": body.username.strip(), "from_email": str(body.from_email),
              "from_name": body.from_name.strip()}
    try:  # prove the credentials work before saving them
        server = await asyncio.to_thread(_open_smtp, {**config, "password": body.password}, 12)
        await asyncio.to_thread(server.quit)
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(422, "The mail server rejected this username or password") from None
    except Exception:
        raise HTTPException(422, "Could not connect to this mail server. Check the server name and port.") from None
    await db[COLLECTION].update_one({"workspace_id": ws_id, "kind": "email_smtp"}, {
        "$set": {"config": config, "secrets": seal(ws_id, "email_smtp", {"password": body.password}), "enabled": True,
                 "status": "connected", "updated_at": now_iso()},
        "$unset": {"last_email_error": "", "last_email_error_at": ""}, "$setOnInsert": {"created_at": now_iso()}}, upsert=True)
    return await connector_status(db, ws_id)


@router.delete("/email/smtp")
async def remove_smtp(ws_id: str, request: Request):
    db, _, _ = await owner(request, ws_id)
    await db[COLLECTION].delete_one({"workspace_id": ws_id, "kind": "email_smtp"})
    return await connector_status(db, ws_id)


@router.post("/email/test")
async def send_test_email(ws_id: str, request: Request):
    db, user, ws = await owner(request, ws_id)
    from ai_ops_emails import simple_email
    result = await send_workspace_email(db, ws, user["email"], "Test email from your AI Manager",
                                        simple_email("Email is working", "Connection test",
                                                     ["This is a test from your AI Manager. Emails to you and your leads will be sent from this address."]))
    if not result["sent"]:
        raise HTTPException(502, result["error"] or "The test email could not be sent")
    return {"sent_to": user["email"], "via": result["via"], "fallback": bool(result["error"])}


class CalendlyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=10, max_length=300)


def calendly_link(value):
    """A public Calendly booking page (https://calendly.com/name or /name/event), or a 422."""
    link = urllib.parse.urlsplit(value.strip() if "://" in value else "https://" + value.strip())
    path = link.path.strip("/")
    hosted = (link.hostname or "").lower() in {"calendly.com", "www.calendly.com"}
    if link.scheme != "https" or not hosted or link.username or link.password or not re.fullmatch("[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)?", path):
        raise HTTPException(422, "Paste your Calendly booking link, for example https://calendly.com/your-name/30min")
    return f"https://calendly.com/{path}"


async def booking_link(db, ws_id):
    connector = await get_connector(db, ws_id, "calendly")
    return (connector or {}).get("config", {}).get("url")


@router.put("/calendly")
async def save_calendly(ws_id: str, request: Request, body: CalendlyInput):
    db, _, _ = await owner(request, ws_id)
    await db[COLLECTION].update_one({"workspace_id": ws_id, "kind": "calendly"}, {
        "$set": {"config": {"url": calendly_link(body.url)}, "enabled": True, "status": "connected", "updated_at": now_iso()},
        "$setOnInsert": {"created_at": now_iso()}}, upsert=True)
    return await connector_status(db, ws_id)


@router.delete("/calendly")
async def remove_calendly(ws_id: str, request: Request):
    db, _, _ = await owner(request, ws_id)
    await db[COLLECTION].delete_one({"workspace_id": ws_id, "kind": "calendly"})
    return await connector_status(db, ws_id)


@router.post("/google/start")
async def start_google(ws_id: str, request: Request, body: GoogleStart):
    _, user, _ = await owner(request, ws_id)
    services = [name for name in dict.fromkeys(body.services) if name in GOOGLE_SCOPES]
    if not services:
        raise HTTPException(422, "Choose calendar or gmail")
    cipher()  # fail before sending the user to Google if tokens could not be stored
    client_id, _ = google_credentials()
    from google_sheets import get_redirect_uri
    scopes = [BASE_SCOPE, *[scope for name in services for scope in GOOGLE_SCOPES[name]]]
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": get_redirect_uri(request),
              "scope": " ".join(scopes), "state": sign_state(ws_id, user["_id"], services),
              "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"}
    return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)}


@router.patch("/google")
async def update_google(ws_id: str, request: Request, body: GooglePatch):
    db, _, _ = await owner(request, ws_id)
    connector = await get_connector(db, ws_id, "google")
    if not connector:
        raise HTTPException(404, "Google is not connected")
    updates = {"updated_at": now_iso()}
    if body.send_email is not None:
        if body.send_email and "gmail" not in (connector.get("services") or []):
            raise HTTPException(409, "Connect Gmail first to send from your Google address")
        updates["send_email"] = body.send_email
    if body.calendar_id is not None:
        updates["calendar_id"] = body.calendar_id.strip() or "primary"
    await db[COLLECTION].update_one({"_id": connector["_id"]}, {"$set": updates})
    return await connector_status(db, ws_id)


@router.delete("/google")
async def remove_google(ws_id: str, request: Request):
    db, _, _ = await owner(request, ws_id)
    await db[COLLECTION].delete_one({"workspace_id": ws_id, "kind": "google"})
    return await connector_status(db, ws_id)
