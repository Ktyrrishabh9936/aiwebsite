"""The agent team, the AI's memory between runs, and the owner's single approval of the daily plan."""
import asyncio
import time
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from fastapi import HTTPException

import ai_agents
import ai_ops
from tests.test_ai_ops import NOW, RUN, STATES, WORKFLOW, candidates_for, context, finished_call, iso, lead, settings, world  # noqa: F401


def team(**changes):
    """The four standard agents, with optional per-role overrides."""
    agents = ai_agents.default_agents("ws", NOW.isoformat())
    for agent in agents:
        agent.update(changes.get(agent["role"], {}))
    return agents


CHANNELS = {"voice": {"connected": True, "reason": "", "number": "+911234567890"}, "calling": {"enabled": True},
            "email": {"connected": True, "sending_from": "hello@platform.test"}, "calendar": {"connected": False}}


def plan(leads, agents=None, channels=CHANNELS, choices=()):
    return ai_ops.build_actions({"name": "Studio"}, RUN, settings(), candidates_for(*leads), list(choices), WORKFLOW, NOW, agents or team(), channels)[0]


# ------------------------------------------------------------ the agent team
def test_each_stage_goes_to_the_agent_responsible_for_it():
    fresh = lead("new")
    contacted = lead("contacted", last_call_at=iso(days=3), last_call_outcome="NO_ANSWER", call_attempt_count=1)
    qualified = lead("ai_qualified", last_call_at=iso(days=4), last_call_outcome="CONNECTED")
    quoting = lead("ai_qualified", last_call_at=iso(days=4), last_call_outcome="CONNECTED", next_action="SEND_QUOTATION")
    customer = lead("won", customer_status="customer", converted_at=iso(days=5))
    by_lead = {a["lead_id"]: (a["agent_name"], a["purpose"]) for a in plan([fresh, contacted, qualified, quoting, customer])}
    assert by_lead[str(fresh["_id"])] == ("First Call Agent", "first_call")
    assert by_lead[str(contacted["_id"])] == ("Follow-up Agent", "follow_up_call")
    assert by_lead[str(qualified["_id"])] == ("Follow-up Agent", "follow_up_call")
    assert by_lead[str(quoting["_id"])] == ("Proposal Agent", "proposal_call")
    assert by_lead[str(customer["_id"])] == ("Customer Care Agent", "check_in")


def test_the_model_may_pick_an_agent_only_if_it_handles_the_stage():
    quoting = lead("ai_qualified", last_call_at=iso(days=4), last_call_outcome="CONNECTED", next_action="SEND_QUOTATION")
    agents = team()

    def choose(agent):
        choice = {"lead_id": str(quoting["_id"]), "kind": "call", "agent": str(agent["_id"]), "purpose": "follow_up_call", "reason": "Check in first."}
        return plan([quoting], agents, choices=[choice])[0]

    assert (choose(agents[1])["agent_name"], choose(agents[1])["purpose"]) == ("Follow-up Agent", "follow_up_call")
    assert choose(agents[0])["agent_name"] == "Proposal Agent"  # the First Call Agent does not handle qualified leads


def test_work_without_an_active_connected_agent_goes_to_a_person_or_another_channel():
    fresh, phone_only = lead("new"), lead("new")
    phone_only["field_values"]["email"] = ""
    unstaffed = plan([fresh], team(first_call={"enabled": False}))[0]
    assert unstaffed["kind"] == "task" and unstaffed["agent_id"] is None and "No active agent handles New leads" in unstaffed["reason"]

    no_voice = {**CHANNELS, "voice": {"connected": False, "reason": "No voice agent is set up yet."}}
    by_lead = {a["lead_id"]: a for a in plan([fresh, phone_only], channels=no_voice)}
    assert by_lead[str(fresh["_id"])]["kind"] == "email" and "voice agent is not connected" in by_lead[str(fresh["_id"])]["reason"]
    assert by_lead[str(phone_only["_id"])]["kind"] == "task" and by_lead[str(phone_only["_id"])]["status"] == "suggested"

    reassigned = plan([fresh], team(follow_up={"stages": ["new", "contacted"]}, first_call={"enabled": False}))[0]
    assert reassigned["kind"] == "call" and reassigned["agent_name"] == "Follow-up Agent"  # the owner moved the New stage


def test_agent_panel_reports_what_each_agent_can_do_right_now():
    stages = ai_agents.stage_list(STATES)
    assert [stage["key"] for stage in stages] == ["new", "contacted", "ai_qualified", "won"]  # lost leads are nobody's job
    follow_up = team()[1]
    ready = ai_agents.agent_view(follow_up, CHANNELS, stages)
    assert ready["status"] == "ready" and [stage["key"] for stage in ready["stages"]] == ["contacted", "ai_qualified"]
    no_voice = {**CHANNELS, "voice": {"connected": False, "reason": "Calling is paused."}}
    limited = ai_agents.agent_view(follow_up, no_voice, stages)
    call = next(item for item in limited["capabilities"] if item["action"] == "call")
    assert limited["status"] == "limited" and not call["available"] and call["note"] == "Calling is paused."
    assert ai_agents.agent_view({**follow_up, "enabled": False}, CHANNELS, stages)["status"] == "off"
    assert ai_agents.agent_view({**follow_up, "actions": ["call"]}, no_voice, stages)["status"] == "blocked"


def test_team_view_and_agent_editing(world, monkeypatch):
    async def scenario():
        ws = await world.db.workspaces.find_one({"_id": ObjectId(world.ws_id)})
        monkeypatch.setattr(ai_agents, "access", AsyncMock(return_value=(world.db, {"email": "owner@example.com"}, ws)))
        listed = await ai_agents.list_agents(world.ws_id, None)
        follow_up = next(a for a in listed["agents"] if a["role"] == "follow_up")
        edited = await ai_agents.update_agent(world.ws_id, follow_up["id"], None, ai_agents.AgentFields(stages=["contacted"], instructions=" Always offer a site visit. "))
        created = await ai_agents.create_agent(world.ws_id, None, ai_agents.AgentFields(name="Site Visit Agent", stages=["ai_qualified"], actions=["email"]))
        with pytest.raises(HTTPException) as bad_stage:
            await ai_agents.update_agent(world.ws_id, follow_up["id"], None, ai_agents.AgentFields(stages=["lost"]))
        with pytest.raises(HTTPException) as builtin:
            await ai_agents.delete_agent(world.ws_id, follow_up["id"], None)
        custom = next(a for a in created["agents"] if a["name"] == "Site Visit Agent")
        removed = await ai_agents.delete_agent(world.ws_id, custom["id"], None)
        return listed, edited, created, bad_stage.value.status_code, builtin.value.status_code, removed

    listed, edited, created, bad_stage, builtin, removed = asyncio.run(scenario())
    assert [a["name"] for a in listed["agents"]] == ["First Call Agent", "Follow-up Agent", "Proposal Agent", "Customer Care Agent"]
    assert listed["channels"]["voice"]["connected"] and listed["channels"]["voice"]["provider"] == "Plivo voice provider"
    assert listed["channels"]["email"] == {"connected": True, "mode": "platform", "sending_from": "hello@platform.test"}
    assert listed["unassigned_stages"] == [] and all(a["status"] == "ready" for a in listed["agents"])
    changed = next(a for a in edited["agents"] if a["role"] == "follow_up")
    assert [stage["key"] for stage in changed["stages"]] == ["contacted"] and changed["instructions"] == "Always offer a site visit."
    assert len(created["agents"]) == 5 and (bad_stage, builtin) == (422, 409) and len(removed["agents"]) == 4


# ------------------------------------------------------------ context: a run does not start from zero
def test_leads_that_declined_or_were_chased_enough_are_left_alone():
    declined = lead("contacted", last_call_at=iso(days=6), last_call_outcome="CONNECTED", lead_status="UNQUALIFIED")
    ctx = context()
    assert ai_ops.assess(declined, ctx) is None and "no current requirement" in ctx["resting"][0]["why"]
    long_ago = lead("contacted", created_at=iso(days=60), last_call_at=iso(days=40), last_call_outcome="CONNECTED", lead_status="UNQUALIFIED")
    again = ai_ops.assess(long_ago, context())
    assert again["suggested"]["template"] == "re_engage" and again["purpose"] == "re_engage"  # one light check-in after a month

    chased = lead("contacted", created_at=iso(days=20), last_call_at=iso(days=3), last_call_outcome="NO_ANSWER")

    def touches(count):
        return {str(chased["_id"]): [{"at": iso(days=day + 3), "kind": "call", "purpose": "follow_up_call", "agent": "Follow-up Agent", "result": "No answer"}
                                     for day in range(count)]}

    assert ai_ops.assess(chased, context(history=touches(3))) is not None
    ctx = context(history=touches(4))
    assert ai_ops.assess(chased, ctx) is None and "resting" in ctx["resting"][0]["why"]
    ctx = context(history=touches(6))
    assert ai_ops.assess(chased, ctx) is None and "paused" in ctx["resting"][0]["why"]

    spoke_since = lead("contacted", last_call_at=iso(days=3), last_call_outcome="CONNECTED")
    earlier = {str(spoke_since["_id"]): [{"at": iso(days=10 + day), "kind": "email"} for day in range(5)]}
    assert ai_ops.assess(spoke_since, context(history=earlier)) is not None  # the lead has spoken to us since those attempts
    overdue = {str(chased["_id"]): [{"title": "Call back", "scheduled_time": iso(days=1)}]}
    assert ai_ops.assess(chased, context(history=touches(6), tasks=overdue))["suggested"]["kind"] == "task"  # a person's overdue job is still raised


def test_each_plan_builds_on_the_previous_ones(world):
    world.model.return_value = {"headline": "Day plan", "summary": "Two leads need a first conversation today.", "focus": ["Call new leads"], "actions": []}

    async def scenario():
        await ai_ops.tick(world.db, now=NOW, budget_seconds=60)
        ws = await world.db.workspaces.find_one({"_id": ObjectId(world.ws_id)})
        first_prompt = world.model.call_args.args[2]
        await ai_ops.tick(world.db, now=NOW + timedelta(minutes=10), budget_seconds=60)  # the email goes out
        await ai_ops.tick(world.db, now=NOW + timedelta(days=1), budget_seconds=60)      # nothing is due again yet: a quiet day
        await ai_ops.tick(world.db, now=NOW + timedelta(days=4), budget_seconds=60)
        return ws, first_prompt, world.model.call_args.args[2], await world.db.workspaces.find_one({"_id": ObjectId(world.ws_id)})

    ws, first_prompt, second_prompt, after = asyncio.run(scenario())
    memory = ws["ai_ops"]["memory"]
    assert [day["day"] for day in memory] == ["2026-11-17"] and memory[0]["planned"] == {"calls": 2, "emails": 1, "for_people": 0}
    assert '"previous_days": []' in first_prompt and "First Call Agent" in first_prompt and '"can_do_now": ["call", "email", "meeting"]' in first_prompt
    assert '"headline": "Day plan"' in second_prompt and "already_done_by_ai" in second_prompt  # yesterday's plan and each lead's history
    assert [day["day"] for day in after["ai_ops"]["memory"]] == ["2026-11-17", "2026-11-18", "2026-11-21"]


# ------------------------------------------------------------ one approval for the whole plan
def request_for(db):
    return type("Request", (), {"app": type("App", (), {"state": type("State", (), {"db": db})})})()


def test_nothing_runs_until_the_owner_approves_the_plan(world):
    world.model.side_effect = RuntimeError("model offline")

    async def scenario():
        await world.db.workspaces.update_one({"_id": ObjectId(world.ws_id)}, {"$set": {"ai_ops.plan_approval": "review"}})
        await ai_ops.tick(world.db, now=NOW, budget_seconds=60)
        await ai_ops.tick(world.db, now=NOW + timedelta(minutes=1), budget_seconds=60)
        idle = await ai_ops.tick(world.db, now=NOW + timedelta(minutes=30), budget_seconds=60)
        idle["calls_placed"] = len(world.calls)
        run = await world.db.ai_ops_runs.find_one({"workspace_id": world.ws_id})
        waiting = await world.db.ai_ops_actions.find({}).to_list(50)
        token = world.sent[0]["html"].split("/plan?t=")[1].split('"')[0]
        shown = await ai_ops.emailed_plan(token, request_for(world.db))
        with pytest.raises(HTTPException) as forged:
            await ai_ops.plan_from_token(world.db, token[:-4] + "abcd")
        drop = next(a for a in waiting if a["kind"] == "email")
        later = NOW + timedelta(minutes=40)
        result = await ai_ops.approve_emailed_plan(token, request_for(world.db), ai_ops.PlanApproval(skip=[str(drop["_id"])]))
        again = await ai_ops.approve_plan(world.db, world.ws_id, await world.db.ai_ops_runs.find_one({"_id": run["_id"]}), "owner@example.com", later)
        released = await world.db.ai_ops_actions.find({}).sort("scheduled_for", 1).to_list(50)
        ran = await ai_ops.tick(world.db, now=later, budget_seconds=60)
        return idle, run, waiting, shown, forged.value.status_code, result, again, released, ran, await world.db.ai_ops_runs.find_one({"_id": run["_id"]})

    idle, run, waiting, shown, forged, result, again, released, ran, approved = asyncio.run(scenario())
    assert run["approval"]["status"] == "pending" and len(waiting) == 3 and all(a["status"] == "awaiting_approval" for a in waiting)
    assert idle["actions"] == 0 and idle["calls_placed"] == 0  # thirty minutes on, nothing has gone out
    brief = world.sent[0]
    assert brief["subject"].startswith("Approve today’s plan") and "Review and approve the plan" in brief["html"]
    assert "First Call Agent" in brief["html"] and "Follow-up Agent" in brief["html"]  # the plan is laid out by agent
    assert shown["approval"] == "pending" and len(shown["actions"]) == 3 and not shown["replaced"] and forged == 410
    assert result == {"approved": 2, "removed": 1} and again == {"approved": 0, "removed": 0}
    assert sorted((a["kind"], a["status"]) for a in released) == [("call", "scheduled"), ("call", "scheduled"), ("email", "cancelled")]
    times = sorted(ai_ops.parse(a["scheduled_for"]) for a in released if a["status"] == "scheduled")  # re-timed from the moment of approval
    assert times[0] >= NOW and times[1] - times[0] == timedelta(minutes=ai_ops.CALL_SPACING_MINUTES)
    assert approved["approval"]["status"] == "approved" and approved["approval"]["by"] == "email link"
    assert ran["actions"] == 2 and len(world.calls) == 2  # approved work runs, calls through the existing entry point


def test_owner_can_change_and_add_actions_before_approving(world, monkeypatch):
    world.model.side_effect = RuntimeError("model offline")

    async def scenario():
        await world.db.workspaces.update_one({"_id": ObjectId(world.ws_id)}, {"$set": {"ai_ops.plan_approval": "review"}})
        await ai_ops.tick(world.db, now=NOW, budget_seconds=60)
        await ai_ops.tick(world.db, now=NOW + timedelta(minutes=1), budget_seconds=60)
        ws = await world.db.workspaces.find_one({"_id": ObjectId(world.ws_id)})
        monkeypatch.setattr(ai_ops, "access", AsyncMock(return_value=(world.db, {"email": "owner@example.com", "name": "Owner"}, ws)))
        call = await world.db.ai_ops_actions.find_one({"lead_id": str(world.leads["new"]["_id"])})
        as_email = await ai_ops.edit_action(world.ws_id, str(call["_id"]), None, ai_ops.ActionEdit(kind="email"))
        timed = await ai_ops.edit_action(world.ws_id, str(call["_id"]), None, ai_ops.ActionEdit(scheduled_for=NOW + timedelta(hours=3), subject="A quick hello"))
        care = next(a for a in await ai_agents.ensure_agents(world.db, world.ws_id) if a["role"] == "customer_care")
        with pytest.raises(HTTPException) as wrong_agent:
            await ai_ops.edit_action(world.ws_id, str(call["_id"]), None, ai_ops.ActionEdit(kind="call", agent_id=str(care["_id"])))
        extra = lead("contacted", workspace_id=world.ws_id, created_at=iso(hours=2))  # too fresh for the AI to have picked it
        await world.db.crm_leads.insert_one(extra)
        added = await ai_ops.add_plan_action(world.ws_id, None, ai_ops.PlanAction(lead_id=str(extra["_id"]), kind="call", reason="Met at the expo."))
        with pytest.raises(HTTPException) as twice:
            await ai_ops.add_plan_action(world.ws_id, None, ai_ops.PlanAction(lead_id=str(extra["_id"]), kind="email"))
        return as_email, timed, wrong_agent.value.status_code, added, twice.value.status_code

    as_email, timed, wrong_agent, added, twice = asyncio.run(scenario())
    assert as_email["kind"] == "email" and as_email["status"] == "awaiting_approval" and as_email["purpose"] == "intro_email"
    assert as_email["agent_name"] == "First Call Agent" and "Thanks for your interest" in as_email["payload"]["subject"]
    assert timed["payload"]["subject"] == "A quick hello" and ai_ops.parse(timed["scheduled_for"]) == NOW + timedelta(hours=3)
    assert added["status"] == "awaiting_approval" and added["agent_name"] == "Follow-up Agent" and added["reason"] == "Met at the expo."
    assert (wrong_agent, twice) == (409, 409)


# ------------------------------------------------------------ calls keep using the existing voice agent
def test_follow_up_calls_brief_the_voice_agent_and_leave_the_lead_record_clean(world, monkeypatch):
    import plivo_calls
    seen = []

    async def spy_call(db_, ws_id_, lead_id, request, auto=False, raise_on_error=True, agent_config_id=None):
        doc = await db_.crm_leads.find_one({"_id": ObjectId(lead_id)})
        seen.append(list((doc.get("communication_summary") or {}).get("pending_discussion") or []))
        return {"status": "started", "session_id": "s"}

    monkeypatch.setattr(plivo_calls, "start_qualification_call", spy_call)

    async def scenario():
        first, follow_up = (await ai_agents.ensure_agents(world.db, world.ws_id))[:2]
        await world.db.ai_agents.update_one({"_id": follow_up["_id"]}, {"$set": {"instructions": "Offer a site visit this week."}})
        target = world.leads["contacted"]
        await world.db.crm_leads.update_one({"_id": target["_id"]}, {"$set": {"communication_summary": {"pending_discussion": ["Budget"]}}})
        base = {"workspace_id": world.ws_id, "kind": "call", "segment": "pipeline", "created_at": NOW.isoformat(), "attempts": 1}
        followed = await ai_ops.perform(world.db, {**base, "lead_id": str(target["_id"]), "purpose": "follow_up_call", "reason": "Spoke 3 days ago, no next step.",
                                                   "agent_id": str(follow_up["_id"]), "agent_name": "Follow-up Agent"}, NOW)
        plain = await ai_ops.perform(world.db, {**base, "lead_id": str(world.leads["new"]["_id"]), "purpose": "first_call", "reason": "New lead.",
                                                "agent_id": str(first["_id"]), "agent_name": "First Call Agent"}, NOW)
        await world.db.ai_agents.update_one({"_id": follow_up["_id"]}, {"$set": {"enabled": False}})
        off = await ai_ops.perform(world.db, {**base, "lead_id": str(world.leads["qualified"]["_id"]), "purpose": "follow_up_call",
                                              "agent_id": str(follow_up["_id"]), "agent_name": "Follow-up Agent"}, NOW)
        return followed, plain, off, await world.db.crm_leads.find_one({"_id": target["_id"]})

    followed, plain, off, saved = asyncio.run(scenario())
    assert followed[0] == "in_progress" and plain[0] == "in_progress" and len(seen) == 2
    assert seen[0][0] == "Budget" and "Follow-up call today by the Follow-up Agent" in seen[0][1] and "Offer a site visit this week." in seen[0][1]
    assert seen[1] == []                                                       # a plain first call is placed exactly as before
    assert saved["communication_summary"]["pending_discussion"] == ["Budget"]  # the brief is removed once the call is placed
    assert off[0] == "skipped" and "switched off" in off[1]


def test_a_meeting_request_goes_to_the_owner_when_no_agent_arranges_meetings_for_the_stage(world):
    finished_call(world)
    world.model.return_value = {"meeting_requested": True, "preferred_time": "2026-11-19T15:00", "preferred_time_text": "Thursday at 3 pm",
                                "meeting_topic": "", "requests_for_admin": []}

    async def scenario():
        for agent in await ai_agents.ensure_agents(world.db, world.ws_id):
            await world.db.ai_agents.update_one({"_id": agent["_id"]}, {"$set": {"actions": [a for a in agent["actions"] if a != "meeting"]}})
        await ai_ops.process_finished_calls(world.db, NOW, time.monotonic() + 60, [world.ws_id])
        return await world.db.ai_ops_meetings.count_documents({}), await world.db.ai_ops_actions.find_one({"kind": "lead_request"})

    meetings_made, request = asyncio.run(scenario())
    assert meetings_made == 0 and "Asked for a meeting (Thursday at 3 pm)" in request["payload"]["requests"][0]


# ------------------------------------------------------------ the voice agent, shown read-only
def test_voice_agent_details_show_the_instructions_the_agent_was_created_with(world):
    async def scenario():
        nothing = await ai_agents.voice_agent_details(world.db, world.ws_id)
        await world.db.workspace_voice_provider_configs.insert_one({"workspace_id": world.ws_id, "provider": "sarvam", "enabled": True, "status": "connected",
                                                                    "configured_secrets": ["api_key"],
                                                                    "config": {"organization_id": "org", "workspace_id": "sws", "app_id": "app", "app_version": 2,
                                                                               "connection_id": "conn", "agent_phone_number": "+911234567890"}})
        await world.db.workspace_voice_agents.insert_one({"workspace_id": world.ws_id, "agent_type": "dedicated", "enabled": True, "agent_name": "Priya",
                                                          "business_name": "Doon Alliance", "business_details": "Premium gated townships and villas.",
                                                          "behaviour": "Ask the budget first."})
        await world.db.sarvam_agent_creations.insert_one({"workspace_id": world.ws_id, "status": "connected", "agent_name": "Doon Alliance", "updated_at": iso(days=1)})
        before = await world.db.workspace_voice_provider_configs.find_one({"provider": "sarvam"})
        shown = await ai_agents.voice_agent_details(world.db, world.ws_id)
        return nothing, shown, before == await world.db.workspace_voice_provider_configs.find_one({"provider": "sarvam"})

    nothing, shown, untouched = asyncio.run(scenario())
    assert nothing == {"available": False}
    assert shown["name"] == "Doon Alliance" and shown["number"] == "+911234567890" and shown["version"] == 2 and shown["editable"] is False
    assert shown["greeting"] == ["Hi, am I speaking with ", {"variable": "lead_name"}, "?"]
    titles = [section["title"] for section in shown["sections"]]
    assert titles[:4] == ["Role", "Call inputs", "Objective", "Business and offer"]
    assert shown["sections"][0]["lines"] == ["You are the voice lead-qualification assistant for Doon Alliance."]
    assert shown["sections"][3]["lines"] == ["Premium gated townships and villas."]
    assert [item["name"] for item in shown["inputs"]] == ["lead_name", "lead_phone", "lead_context"] and len(shown["outputs"]) == 12
    assert untouched  # reading the details changes nothing in the voice configuration


# ------------------------------------------------------------ Calendly
def test_calendly_links_are_validated():
    import connectors
    assert connectors.calendly_link(" calendly.com/asha-rao/30min ") == "https://calendly.com/asha-rao/30min"
    assert connectors.calendly_link("https://www.calendly.com/asha") == "https://calendly.com/asha"
    for bad in ("https://example.com/asha", "http://calendly.com/asha", "https://calendly.com/", "https://calendly.com/a/b/c", "https://evil.com/calendly.com/asha"):
        with pytest.raises(HTTPException):
            connectors.calendly_link(bad)


def test_with_calendly_connected_the_lead_is_emailed_the_booking_link(world):
    target = finished_call(world)
    world.model.return_value = {"meeting_requested": True, "preferred_time": None, "preferred_time_text": "sometime next week",
                                "meeting_topic": "Demo", "requests_for_admin": []}

    async def scenario():
        await world.db.workspace_connectors.insert_one({"workspace_id": world.ws_id, "kind": "calendly", "config": {"url": "https://calendly.com/studio/demo"}})
        await ai_ops.process_finished_calls(world.db, NOW, time.monotonic() + 60, [world.ws_id])
        import connectors
        return (await world.db.ai_ops_meetings.find({}).to_list(5), await world.db.crm_leads.find_one({"_id": target["_id"]}),
                await connectors.connector_status(world.db, world.ws_id))

    held, saved, status = asyncio.run(scenario())
    assert len(held) == 1 and held[0]["status"] == "link_sent" and held[0]["start"] is None and held[0]["lead_notified"] is True
    to_lead = next(m for m in world.sent if m["to"] == "asha@example.com")
    assert "Book your meeting" in to_lead["subject"] and "https://calendly.com/studio/demo" in to_lead["html"]
    to_owner = next(m for m in world.sent if m["to"] == "owner@example.com")
    assert "Meeting requested: Asha Rao" in to_owner["subject"] and "Calendly link" in to_owner["html"]
    assert "Calendly booking link was emailed" in saved["lead_notes"][-1]["body"]
    assert status["calendly"] == {"connected": True, "url": "https://calendly.com/studio/demo"} and status["calendar"]["provider"] == "calendly"
