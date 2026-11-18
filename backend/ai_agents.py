"""The AI team: which agents exist, what each one handles, and whether it can act right now.

An agent here is a role in the daily plan (first calls, follow-ups, proposals, customer care, or a
custom one). It owns pipeline stages, a set of actions and the owner's instructions. Calls are still
placed by the workspace's existing voice agent and emails by the existing email connector; this module
only reads their state to report, per agent, what is connected and what it can perform today.
"""
import asyncio
from collections import Counter
from datetime import timedelta

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

router = APIRouter(prefix="/workspaces/{ws_id}/ai-agents", tags=["AI agents"])

ACTIONS = ("call", "email", "meeting")
ROLES = {
    "first_call": {"name": "First Call Agent", "categories": ["new"], "actions": ["call", "email", "meeting"],
                   "description": "Makes first contact with every new lead, finds out what they need and records it in the CRM."},
    "follow_up": {"name": "Follow-up Agent", "categories": ["contacted", "qualified"], "actions": ["call", "email", "meeting"],
                  "description": "Keeps contacted leads moving with follow-up calls, callbacks and emails until there is a clear next step."},
    "proposal": {"name": "Proposal Agent", "categories": ["qualified"], "actions": ["call", "email", "meeting"],
                 "description": "Works qualified leads towards a decision with proposal calls, proposal follow-ups and meetings."},
    "customer_care": {"name": "Customer Care Agent", "categories": ["customer"], "actions": ["email", "meeting"],
                      "description": "Looks after converted customers with check-ins, payment reminders and repeat opportunities."},
}
ROLE_LABELS = {**{key: value["name"] for key, value in ROLES.items()}, "custom": "Custom agent"}
CONTEXT_SOURCES = [
    "Your business profile and offer (from the Brain and sales profile)",
    "The lead's details, form answers and current pipeline stage",
    "Earlier calls: summaries, objections and what is still to discuss",
    "Notes, follow-ups and what the AI already did for this lead",
    "The instructions you write for this agent",
]


def default_agents(ws_id, now):
    from ai_ops import stable_id
    return [{"_id": stable_id("ai_agent", ws_id, role), "workspace_id": ws_id, "role": role, "builtin": True, "name": spec["name"],
             "description": spec["description"], "categories": spec["categories"], "stages": [], "actions": spec["actions"],
             "instructions": "", "enabled": True, "order": index, "created_at": now, "updated_at": now}
            for index, (role, spec) in enumerate(ROLES.items())]


async def ensure_agents(db, ws_id):
    """The workspace's agents in display order; the four standard ones are created on first use."""
    from ai_ops import utcnow
    docs = await db.ai_agents.find({"workspace_id": ws_id}).sort("order", 1).to_list(60)
    if sum(bool(doc.get("builtin")) for doc in docs) < len(ROLES):
        for agent in default_agents(ws_id, utcnow().isoformat()):
            await db.ai_agents.update_one({"_id": agent["_id"]}, {"$setOnInsert": {k: v for k, v in agent.items() if k != "_id"}}, upsert=True)
        docs = await db.ai_agents.find({"workspace_id": ws_id}).sort("order", 1).to_list(60)
    return docs


def handles(agent, stage, category):
    """Stages chosen by the owner win; otherwise the agent covers its role's kind of stage."""
    stages = agent.get("stages") or []
    return stage in stages if stages else category in (agent.get("categories") or [])


def pick_agent(agents, stage, category, kind, wanted=None, role=None):
    """The enabled agent that should do this kind of action for a lead in this stage, or None."""
    eligible = [agent for agent in agents or [] if agent.get("enabled") and kind in (agent.get("actions") or []) and handles(agent, stage, category)]
    for test in (lambda a: wanted and wanted in {str(a["_id"]), a.get("name")}, lambda a: role and a.get("role") == role):
        match = next((agent for agent in eligible if test(agent)), None)
        if match:
            return match
    return eligible[0] if eligible else None


async def channel_status(db, ws_id, ws=None):
    """What the agents act through: the existing voice agent, calling hours, email and calendar."""
    from connectors import connector_status
    from managed_voice import DEDICATED, MASTER, voice_agent_state
    from plivo_calls import ensure_calling_workflow_config
    state, links, workflow = await asyncio.gather(voice_agent_state(db, ws_id), connector_status(db, ws_id), ensure_calling_workflow_config(db, ws_id))
    profile, trial, kind = state.get("profile") or {}, state.get("trial") or {}, state.get("active_type")
    voice = {"connected": False, "type": None, "provider": None, "agent_name": profile.get("agent_name") or None, "number": None,
             "paused": bool(kind) and not state.get("calling_enabled"), "detail": "", "reason": "No voice agent is set up yet."}
    if kind == MASTER:
        active = trial.get("status") == "active"
        voice.update(type="trial", provider="Built-in voice agent (free trial)", number=trial.get("calling_number"),
                     connected=active and bool(state.get("calling_enabled")),
                     detail=f"{trial.get('days_left')} days of the free trial left" if active else "The free trial has ended",
                     reason="" if active and state.get("calling_enabled") else "The free trial has ended. Connect your own voice agent." if not active else "Calling is paused.")
    elif kind == DEDICATED:
        own = state.get("dedicated") or {}
        voice.update(type="own", provider="Your own voice agent (Sarvam)", number=own.get("calling_number"), agent_name=own.get("agent_name") or voice["agent_name"],
                     connected=bool(state.get("calling_enabled")), verification=own.get("status"), last_verified_at=own.get("last_verified_at"),
                     detail="Connection verified" if own.get("status") == "connected" else "Connection not verified yet",
                     reason="" if state.get("calling_enabled") else "Calling is paused.")
    else:
        ws = ws or await db.workspaces.find_one({"_id": ObjectId(ws_id)}) or {}
        provider = ws.get("qualification_voice_provider") or "plivo"
        legacy = await db.workspace_voice_provider_configs.find_one({"workspace_id": ws_id, "provider": provider})
        if legacy:
            on = bool(legacy.get("enabled"))
            voice.update(type="provider", provider=f"{provider.title()} voice provider", connected=on, verification=legacy.get("status"),
                         last_verified_at=legacy.get("last_verified_at"), paused=not on,
                         detail="Connection verified" if legacy.get("status") == "connected" else "Connection not verified yet",
                         reason="" if on else "The voice provider is switched off.")
    email = links["email"]
    return {"voice": voice,
            "calling": {"enabled": bool(workflow.get("enabled", True)), "window": workflow.get("calling_window"), "timezone": workflow.get("timezone")},
            "email": {"connected": email["mode"] != "platform" or bool(email["platform_ready"]), "mode": email["mode"], "sending_from": email.get("sending_from")},
            "calendar": links["calendar"]}


def capabilities(agent, channels):
    """Each action the agent has, and whether it can be performed right now."""
    voice, items = channels["voice"], []
    for action in agent.get("actions") or []:
        if action == "call":
            ok = voice["connected"] and channels["calling"]["enabled"]
            items.append({"action": action, "label": "Phone calls through the voice agent", "available": ok,
                          "note": (f"Calls from {voice['number']}" if voice.get("number") else "Voice agent connected") if ok
                          else voice["reason"] or "Calling is switched off in Qualification settings."})
        elif action == "email":
            ok = channels["email"]["connected"]
            items.append({"action": action, "label": "Emails to leads and customers", "available": ok,
                          "note": f"Sent from {channels['email'].get('sending_from') or 'the built-in email'}" if ok else "No email account is available on the server."})
        elif action == "meeting":
            provider = channels["calendar"].get("provider")
            items.append({"action": action, "label": "Arranges meetings a lead asks for", "available": True,
                          "note": "Emails the lead your Calendly booking link" if provider == "calendly" else "Checks your Google Calendar for a free time"
                          if provider == "google" else "Calendar not connected, so your availability is not checked."})
    return items


def agent_status(agent, abilities):
    if not agent.get("enabled"):
        return "off"
    acting = [item for item in abilities if item["action"] != "meeting"]
    if acting and not any(item["available"] for item in acting):
        return "blocked"
    return "limited" if any(not item["available"] for item in acting) else "ready"


def stage_list(states):
    """Pipeline and customer stages an agent can own (lost leads are never worked)."""
    from ai_ops import stage_category
    ordered = sorted(states or [], key=lambda state: state.get("order", 0))
    stages = [{"key": state["key"], "label": state.get("label") or state["key"].replace("_", " ").title(),
               "category": stage_category({"status": state["key"]}, ordered)} for state in ordered]
    return [stage for stage in stages if stage["category"] != "lost"]


def agent_view(agent, channels, stages, activity=None):
    abilities = capabilities(agent, channels)
    covered = [stage for stage in stages if handles(agent, stage["key"], stage["category"])]
    return {"id": str(agent["_id"]), "name": agent["name"], "role": agent.get("role") or "custom", "role_label": ROLE_LABELS.get(agent.get("role"), "Custom agent"),
            "builtin": bool(agent.get("builtin")), "description": agent.get("description") or "", "enabled": bool(agent.get("enabled")),
            "stages": [{"key": stage["key"], "label": stage["label"]} for stage in covered], "custom_stages": bool(agent.get("stages")),
            "actions": agent.get("actions") or [], "capabilities": abilities, "status": agent_status(agent, abilities),
            "instructions": agent.get("instructions") or "", "context": CONTEXT_SOURCES,
            "activity": activity or {"planned": 0, "done": 0, "failed": 0, "last_at": None}, "updated_at": agent.get("updated_at")}


async def team(db, ws_id, ws=None):
    """Everything the agent panel shows."""
    from ai_ops import OPEN, settings_out, utcnow
    from crm import ensure_crm_settings
    agents, channels, crm_settings = await asyncio.gather(ensure_agents(db, ws_id), channel_status(db, ws_id, ws), ensure_crm_settings(db, ws_id))
    ws = ws or await db.workspaces.find_one({"_id": ObjectId(ws_id)}) or {}
    stages = stage_list(crm_settings.get("states"))
    since = (utcnow() - timedelta(days=7)).isoformat()
    recent = await db.ai_ops_actions.find({"workspace_id": ws_id, "created_at": {"$gte": since}, "agent_id": {"$exists": True}},
                                          {"agent_id": 1, "status": 1, "updated_at": 1}).to_list(5000)
    activity = {}
    for action in recent:
        entry = activity.setdefault(action.get("agent_id"), {"planned": 0, "done": 0, "failed": 0, "last_at": None})
        bucket = "planned" if action.get("status") in OPEN else "done" if action.get("status") == "done" else "failed" if action.get("status") == "failed" else None
        if bucket:
            entry[bucket] += 1
        if action.get("status") in {"done", "in_progress"}:
            entry["last_at"] = max(filter(None, (entry["last_at"], action.get("updated_at"))), default=None)
    views = [agent_view(agent, channels, stages, activity.get(str(agent["_id"]))) for agent in agents]
    owners = Counter(stage["key"] for view in views if view["enabled"] for stage in view["stages"])
    run = await db.ai_ops_runs.find_one({"workspace_id": ws_id}, sort=[("created_at", -1)])
    return {"agents": views, "channels": channels, "stages": stages,
            "unassigned_stages": [stage for stage in stages if not owners.get(stage["key"])],
            "roles": [{"key": key, "name": value["name"], "description": value["description"], "actions": value["actions"]} for key, value in ROLES.items()],
            "manager": {**{key: value for key, value in settings_out(ws).items() if key in {"enabled", "run_time", "timezone", "next_run_at", "plan_approval", "configured"}},
                        "last_plan": {"day": run.get("day"), "headline": (run.get("strategy") or {}).get("headline"), "status": run.get("status"),
                                      "approval": (run.get("approval") or {}).get("status")} if run else None}}


# ---------------------------------------------------------------- API
class AgentFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=400)
    stages: list[str] | None = Field(default=None, max_length=40)
    actions: list[str] | None = Field(default=None, max_length=3)
    instructions: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None

    @field_validator("actions")
    @classmethod
    def known_actions(cls, value):
        if value is not None and any(item not in ACTIONS for item in value):
            raise ValueError("Actions can be call, email or meeting")
        return None if value is None else [item for item in ACTIONS if item in value]


async def access(request, ws_id):
    from auth import get_current_user_and_workspace
    db = request.app.state.db
    user, ws = await get_current_user_and_workspace(request, db, ws_id)
    return db, user, ws


async def cleaned(db, ws_id, body, creating=False):
    """Validated fields to store, checked against the workspace's real pipeline stages."""
    from crm import ensure_crm_settings
    values = {key: value for key, value in body.model_dump(exclude_unset=True).items() if value is not None}
    for key in ("name", "description"):
        if key in values:
            values[key] = " ".join(values[key].split())
    if "instructions" in values:
        values["instructions"] = values["instructions"].strip()
    if "stages" in values:
        known = {stage["key"] for stage in stage_list((await ensure_crm_settings(db, ws_id)).get("states"))}
        if set(values["stages"]) - known:
            raise HTTPException(422, "Choose stages from your CRM pipeline")
        values["stages"] = list(dict.fromkeys(values["stages"]))
    if creating:
        if not values.get("name"):
            raise HTTPException(422, "Give the agent a name")
        if not values.get("stages") or not values.get("actions"):
            raise HTTPException(422, "Choose at least one pipeline stage and one action for the agent")
    elif values.get("name") == "" or values.get("actions") == []:
        raise HTTPException(422, "An agent needs a name and at least one action")
    return values


async def one_agent(db, ws_id, agent_id):
    doc = await db.ai_agents.find_one({"_id": ObjectId(agent_id), "workspace_id": ws_id}) if ObjectId.is_valid(agent_id) else None
    if not doc:
        raise HTTPException(404, "Agent not found")
    return doc


@router.get("")
async def list_agents(ws_id: str, request: Request):
    db, _, ws = await access(request, ws_id)
    return await team(db, ws_id, ws)


def prompt_sections(prompt):
    """Split instructions written as '# HEADING' blocks into titled sections for display."""
    sections = []
    for line in str(prompt or "").splitlines():
        if line.startswith("# "):
            sections.append({"title": line[2:].strip().capitalize(), "lines": []})
        elif line.strip() and sections:
            sections[-1]["lines"].append(line.strip())
    return [section for section in sections if section["lines"]]


async def voice_agent_details(db, ws_id):
    """A read-only picture of the workspace's voice agent: greeting, instructions, variables and settings.

    Built from what AREVEI holds (the agent profile and the connection); nothing is sent to or changed
    in the calling provider. Edits made directly in a Sarvam account after creation are not shown.
    """
    from managed_voice import DEDICATED, MASTER, default_business_name, voice_agent_state, workspace_and_brain
    from sarvam_agent_builder import INPUT_VARIABLES
    from voice_api import SARVAM_QUALIFICATION_OUTPUTS, sarvam_runtime_prompt
    state = await voice_agent_state(db, ws_id)
    kind = state.get("active_type")
    if kind not in {MASTER, DEDICATED}:
        return {"available": False}
    profile, trial, own = state.get("profile") or {}, state.get("trial") or {}, state.get("dedicated") or {}
    workspace, brain = await workspace_and_brain(db, ws_id)
    business = profile.get("business_name") or default_business_name(workspace, brain) or "your business"
    inputs = [{"name": item["name"], "description": item["description"]} for item in INPUT_VARIABLES]
    outputs = [{"name": item["name"], "description": item["description"]} for item in SARVAM_QUALIFICATION_OUTPUTS]
    if kind == MASTER:
        name = profile.get("agent_name") or "AI agent"
        sections = [{"title": "Role", "lines": [f"You are {name}, the voice lead-qualification assistant for {business}."]},
                    {"title": "Business and offer", "lines": (profile.get("business_details") or "No business details added yet.").splitlines()},
                    {"title": "How to run the call", "lines": (profile.get("behaviour") or "No calling behaviour added yet.").splitlines()}]
        return {"available": True, "type": "trial", "name": name, "business": business, "number": trial.get("calling_number"), "editable": True,
                "greeting": [f"Hi, this is {name} from {business}. Am I speaking with ", {"variable": "lead_name"}, "?"],
                "sections": [{**section, "lines": [line for line in section["lines"] if line.strip()]} for section in sections],
                "inputs": inputs, "outputs": outputs,
                "settings": [["Type", "Built-in agent (free trial)"], ["Calls from", trial.get("calling_number") or "—"],
                             ["Trial", f"{trial.get('days_left')} days left" if trial.get("status") == "active" else "Ended"]]}
    provider = await db.workspace_voice_provider_configs.find_one({"workspace_id": ws_id, "provider": "sarvam"}) or {}
    config = provider.get("config") or {}
    prompt = sarvam_runtime_prompt(business, profile.get("business_details"), "", profile.get("behaviour"))
    return {"available": True, "type": "own", "name": own.get("agent_name") or profile.get("agent_name") or "Your agent", "business": business,
            "number": own.get("calling_number"), "version": config.get("app_version"), "editable": False,
            "greeting": ["Hi, am I speaking with ", {"variable": "lead_name"}, "?"], "sections": prompt_sections(prompt),
            "inputs": inputs, "outputs": outputs,
            "settings": [["Type", "Your own agent (Sarvam)"], ["Calls from", own.get("calling_number") or "—"],
                         ["Version", f"v{config['app_version']}" if config.get("app_version") else "—"],
                         ["Connection", str(own.get("status") or "unverified").replace("_", " ").capitalize()]],
            "note": "These are the instructions your agent was created with. Changes made directly in your Sarvam account are not shown here."}


@router.get("/voice-details")
async def get_voice_details(ws_id: str, request: Request):
    db, _, _ = await access(request, ws_id)
    return await voice_agent_details(db, ws_id)


@router.post("")
async def create_agent(ws_id: str, request: Request, body: AgentFields):
    from ai_ops import utcnow
    db, _, ws = await access(request, ws_id)
    existing = await ensure_agents(db, ws_id)
    if len(existing) >= 20:
        raise HTTPException(409, "A workspace can have up to 20 agents")
    values, now = await cleaned(db, ws_id, body, creating=True), utcnow().isoformat()
    doc = {"workspace_id": ws_id, "role": "custom", "builtin": False, "description": "", "instructions": "", "enabled": True, "categories": [],
           "order": max([agent.get("order", 0) for agent in existing] + [9]) + 1, "created_at": now, "updated_at": now, **values}
    await db.ai_agents.insert_one(doc)
    return await team(db, ws_id, ws)


@router.patch("/{agent_id}")
async def update_agent(ws_id: str, agent_id: str, request: Request, body: AgentFields):
    from ai_ops import utcnow
    db, _, ws = await access(request, ws_id)
    agent = await one_agent(db, ws_id, agent_id)
    values = await cleaned(db, ws_id, body)
    if not agent.get("builtin") and values.get("stages") == []:
        raise HTTPException(422, "Choose at least one pipeline stage for the agent")
    await db.ai_agents.update_one({"_id": agent["_id"]}, {"$set": {**values, "updated_at": utcnow().isoformat()}})
    return await team(db, ws_id, ws)


@router.delete("/{agent_id}")
async def delete_agent(ws_id: str, agent_id: str, request: Request):
    db, _, ws = await access(request, ws_id)
    agent = await one_agent(db, ws_id, agent_id)
    if agent.get("builtin"):
        raise HTTPException(409, "Standard agents can be switched off but not deleted")
    await db.ai_agents.delete_one({"_id": agent["_id"]})
    return await team(db, ws_id, ws)
