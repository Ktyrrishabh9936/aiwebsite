"""Transport adapters; qualification decisions remain in qualification_engine."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from urllib.parse import urlsplit
from typing import Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from qualification_engine import CallResult, Outcome, validated_facts
from voice_config import load_config, public_base, safe_config


class VoiceProvider:
    name = ""

    async def configuration(self, db, ws_id, agent_config_id=None):
        doc, secrets = await load_config(db, ws_id, self.name)
        config = safe_config(self.name, doc["config"])
        self.validate_configuration(config, secrets)
        return {**config, "provider": self.name, "arevei_workspace_id": ws_id, "credentials": secrets,
                "display_name": self.name.title(), "enabled": True, "id": str(doc["_id"])}

    def validate_configuration(self, config, secrets):
        missing = [k for k in self.required_config if not config.get(k)]
        missing += [k for k in self.required_secrets if not secrets.get(k)]
        if missing:
            raise HTTPException(409, "Missing configuration: " + ", ".join(missing))

    async def initiate_call(self, client, config, payload):
        url, headers, auth = self.transport(config)
        return await client.post(url, json=payload, headers=headers, auth=auth)

    async def test_connection(self, config, secrets):
        try:
            self.validate_configuration(config, secrets)
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                response = await self.probe(client, config, secrets)
            if response.status_code in (401, 403):
                return "invalid_credentials"
            if response.status_code >= 500 or response.status_code == 429:
                return "provider_unavailable"
            return "connected" if response.status_code == 200 else "configuration_error"
        except HTTPException:
            return "missing_configuration"
        except httpx.HTTPError:
            return "provider_unavailable"


class PlivoVoiceProvider(VoiceProvider):
    name = "plivo"
    required_config = ("auth_id", "from_number", "trigger_url")
    required_secrets = ("auth_token",)

    async def configuration(self, db, ws_id, agent_config_id=None):
        config = await super().configuration(db, ws_id)
        if not agent_config_id:
            default = await db.plivo_agent_configs.find_one({"workspace_id": ws_id, "enabled": True, "is_default": True})
            if default:
                agent_config_id = str(default["_id"])
        # Preserve selected workspace agent mappings/flow, but never its old credentials.
        if agent_config_id and agent_config_id != "environment":
            from bson import ObjectId
            if not ObjectId.is_valid(agent_config_id):
                raise HTTPException(404, "Voice agent not found")
            agent = await db.plivo_agent_configs.find_one({"workspace_id": ws_id, "_id": ObjectId(agent_config_id)})
            if not agent or not agent.get("enabled"):
                raise HTTPException(409, "Selected voice agent is missing or disabled")
            config["id"] = str(agent["_id"])
            for key in ("trigger_url", "flow_id", "input_variable_mappings", "extra_payload", "display_name"):
                if key in agent:
                    config[key] = agent[key]
            safe_config(self.name, {k: config[k] for k in ("trigger_url", "extra_payload", "input_variable_mappings") if k in config})
        return config

    def transport(self, config):
        secrets = config["credentials"]
        if config.get("auth_type") == "bearer":
            if not secrets.get("bearer_token"):
                raise HTTPException(409, "Missing bearer token")
            return config["trigger_url"], {"Authorization": "Bearer " + secrets["bearer_token"]}, None
        return config["trigger_url"], {}, (config["auth_id"], secrets["auth_token"])

    def build_payload(self, base, config, session_id):
        from plivo_calls import build_agent_trigger_payload
        return build_agent_trigger_payload(base, config, session_id)

    def identifiers(self, data):
        from plivo_calls import extract_provider_identifiers
        return extract_provider_identifiers(data)

    def normalize(self, raw, lead_id, fallback=""):
        from plivo_response_adapter import PlivoResponseAdapter
        return PlivoResponseAdapter().adapt(raw, lead_id, fallback)

    async def probe(self, client, config, secrets):
        return await client.get(f"https://api.plivo.com/v1/Account/{config['auth_id']}/", auth=(config["auth_id"], secrets["auth_token"]))


class SarvamChannelInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    channel_type: str
    channel_provider: str
    agent_phone_number: str = Field(pattern=r"^\+[1-9]\d{7,14}$")


class SarvamWebhookConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str | None = None
    metadata: dict | None = None


class SarvamCallback(BaseModel):
    model_config = ConfigDict(extra="ignore")

    attempt_id: str = Field(min_length=1, max_length=200)
    status: Literal["connected", "no_answer", "busy", "failed"]
    channel_info: SarvamChannelInfo
    interaction_id: str | None = None
    duration: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    failure_reason: str | None = None
    final_agent_variables: dict | None = None
    interaction_transcript: list[dict[str, str]] | None = None
    webhook_config: SarvamWebhookConfig | None = None


class SarvamVoiceProvider(VoiceProvider):
    name = "sarvam"
    required_config = ("organization_id", "workspace_id", "app_id", "app_version", "connection_id", "agent_phone_number")
    required_secrets = ("api_key", "callback_token")

    def transport(self, config):
        return (f"https://apps.sarvam.ai/api/outbounds/v1/orgs/{config['organization_id']}/workspaces/{config['workspace_id']}/outbounds",
                {"X-API-Key": config["credentials"]["api_key"]}, None)

    def build_payload(self, base, config, session_id):
        # Per-session capability is passed as metadata, never in a URL/access log.
        proof = callback_proof(config["credentials"]["callback_token"], base["workspace_id"], session_id)
        if config.get("payload_mode") == "lead_context_v1":
            agent_variables = {
                "lead_name": str(base.get("lead_name") or base.get("customer_name") or ""),
                "lead_phone": str(base.get("lead_phone") or base.get("to_number") or ""),
                "lead_context": str(base.get("lead_context") or ""),
            }
        else:
            agent_variables = {"qualification_profile": base["qualification_profile"], "customer_name": base["customer_name"],
                               "previous_answers": base["previous_answers"], "pending_discussion": base["pending_discussion"]}
        return {"app_config": {"app_id": config["app_id"], "app_version": config["app_version"],
                "connection_config": {"connection_id": config["connection_id"], "agent_phone_number": config["agent_phone_number"]},
                "agent_variables": agent_variables},
                "user_config": {"user_phone_number": base["to_number"]},
                "webhook_config": {"url": f"{public_base()}/api/sarvam/workspaces/{base['workspace_id']}/calls/{session_id}/result",
                                   "metadata": {"callback_proof": proof, "arevei_workspace_id": base["workspace_id"],
                                                "lead_id": base["lead_id"], "qualification_session_id": session_id}}}

    def identifiers(self, data):
        attempt = data.get("attempt_id")
        if not isinstance(attempt, str) or not attempt:
            return {}
        return {"call_uuid": attempt, "request_uuid": attempt, "attempt_id": attempt}

    def normalize(self, raw, lead_id, fallback=""):
        try:
            data = SarvamCallback.model_validate(raw)
        except ValidationError:
            raise HTTPException(422, "Malformed Sarvam callback") from None
        statuses = {"connected": "completed", "no_answer": "no_answer", "busy": "busy", "failed": "failed"}
        variables = data.final_agent_variables or {}
        facts = variables.get("qualification_data", variables)
        if not isinstance(facts, dict):
            raise HTTPException(422, "Malformed qualification facts")
        transcript = "\n".join(f"{turn.get('role', '')}: {turn.get('en_text', '')}" for turn in data.interaction_transcript or [])
        # Shared fact parsing retains DND/budget normalization without accepting provider scores.
        from plivo_response_adapter import PlivoResponseAdapter
        call = PlivoResponseAdapter().adapt({"call_uuid": data.attempt_id, "status": statuses[data.status],
                "qualification_data": facts, "transcript": transcript, "duration": data.duration or 0}, lead_id)
        call.provider = self.name
        call.recording_url = raw.get("_arevei_recording_url")
        call.raw_provider_data = {"attempt_id": data.attempt_id, "interaction_id": data.interaction_id}
        return call

    async def recording(self, config, secrets, attempt_id, started_at):
        """The attempts API documents audio_url; the recordings API has no response schema."""
        from plivo_response_adapter import parse_time
        now = datetime.now(timezone.utc)
        start = parse_time(started_at) or now
        url = f"https://apps.sarvam.ai/api/analytics/v1/{config['organization_id']}/{config['workspace_id']}/{config['app_id']}/attempts"
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
                response = await client.get(url, headers={"X-API-Key": secrets["api_key"]}, params={
                    "start_datetime": (start - timedelta(minutes=5)).isoformat(), "end_datetime": now.isoformat(), "limit": 1,
                    "filter_conditions": json.dumps([{"id": "attempt", "field": "attempt_id", "operator": "equals", "value": attempt_id}])})
            if response.status_code != 200:
                return None
            for item in response.json().get("items", []):
                if item.get("attempt_id") == attempt_id and item.get("audio_url"):
                    parsed = urlsplit(item["audio_url"])
                    if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
                        return item["audio_url"]
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            pass
        return None

    async def probe(self, client, config, secrets):
        now = datetime.now(timezone.utc)
        return await client.get(f"https://apps.sarvam.ai/api/analytics/v1/{config['organization_id']}/{config['workspace_id']}/{config['app_id']}/attempts",
            params={"start_datetime": (now - timedelta(minutes=1)).isoformat(), "end_datetime": now.isoformat(), "limit": 1},
            headers={"X-API-Key": secrets["api_key"]})


def callback_proof(secret, ws_id, session_id):
    return hmac.new(secret.encode(), f"sarvam:{ws_id}:{session_id}".encode(), hashlib.sha256).hexdigest()


def get_provider(name):
    providers = {"plivo": PlivoVoiceProvider, "sarvam": SarvamVoiceProvider}
    if name not in providers:
        raise HTTPException(422, "Unsupported voice provider")
    return providers[name]()
