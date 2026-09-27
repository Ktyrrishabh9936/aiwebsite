"""Model-selected application capabilities; no prescribed conversation sequences."""
from datetime import datetime, timezone
from bson import ObjectId
from fastapi import HTTPException
from jsonschema import validate


def tool(name, label, section, description, properties=None, required=(), *, writes=False, agent="AI Manager"):
    return {"name": name, "label": label, "section": section, "writes": writes, "agent": agent,
            "schema": {"type": "function", "function": {"name": name, "description": description,
                "parameters": {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}}}}


TEXT = {"type": "string", "minLength": 1, "maxLength": 4000}
ID = {"type": "string", "pattern": "^[a-fA-F0-9]{24}$"}
TIME = {"type": "string", "description": "ISO 8601 timestamp with explicit UTC offset. Ask for timezone if unknown."}
FIELDS = {"type": "object", "description": "Configured lead field keys from get_crm_configuration.", "maxProperties": 40, "additionalProperties": {"type": ["string", "number", "boolean", "null"]}}
TOOLS = [
    tool("get_business_context", "Reading business goals", "Brain", "Read business profile, saved strategy, roadmap and current time."),
    tool("get_crm_configuration", "Reading CRM fields and stages", "CRM", "Discover valid fields, required fields and stages before creating or updating leads."),
    tool("search_leads", "Finding leads", "CRM", "Find leads by name, phone, custom field or stage. Paginated results; total is the matching count. Ask if multiple names match.",
         {"search": {"type": "string", "maxLength": 200}, "status": {"type": "string", "maxLength": 100}, "page": {"type": "integer", "minimum": 1, "maximum": 10000}}),
    tool("get_lead", "Reading lead details", "CRM", "Read an active lead's fields, notes, qualification and assignment.", {"lead_id": ID}, ["lead_id"]),
    tool("get_crm_analytics", "Checking CRM totals", "CRM", "Read lead/payment analytics for up to 5000 most recent leads, with an exact active lead total and a flag when the analytics are capped."),
    tool("list_followups", "Checking follow-ups", "CRM", "Query actual follow-ups with lead names. overdue=true finds overdue work. start/end bound due time.",
         {"lead_id": ID, "status": {"type": "string", "enum": ["pending", "done", "cancelled", "all"]}, "overdue": {"type": "boolean"}, "start": TIME, "end": TIME, "offset": {"type": "integer", "minimum": 0, "maximum": 10000}}),
    tool("create_followup", "Scheduling a human follow-up", "CRM", "Save a reminder with a clear due time and title. Does not call the customer.",
         {"lead_id": ID, "title": {**TEXT, "maxLength": 200}, "note": TEXT, "due_at": TIME}, ["lead_id", "title", "due_at"], writes=True),
    tool("update_followup", "Updating a follow-up", "CRM", "Edit/reschedule a reminder identified by list_followups.",
         {"reminder_id": ID, "title": {**TEXT, "maxLength": 200}, "note": TEXT, "due_at": TIME}, ["reminder_id", "title", "due_at"], writes=True),
    tool("complete_followup", "Recording follow-up outcome", "CRM", "Mark a reminder done or cancelled only after the user reports the outcome.",
         {"reminder_id": ID, "status": {"type": "string", "enum": ["done", "cancelled"]}, "outcome": {**TEXT, "maxLength": 1000}}, ["reminder_id", "status"], writes=True),
    tool("create_lead", "Adding a lead", "CRM", "Save a new lead using the existing automatic initial qualification workflow. Ask for missing required fields. Automatic calling defaults to true; set trigger_ai_call=false ONLY when the owner explicitly asks to skip it. Do not separately start a qualification call after creation; the existing workflow schedules it.",
         {"field_values": FIELDS, "trigger_ai_call": {"type": "boolean", "default": True}}, ["field_values"], writes=True),
    tool("update_lead", "Updating lead information", "CRM", "Update requested fields/stage after reading the lead and valid configuration. Never invent customer outcomes.",
         {"lead_id": ID, "field_values": FIELDS, "status": {"type": "string", "maxLength": 100}}, ["lead_id"], writes=True),
    tool("add_lead_note", "Saving a lead note", "CRM", "Save the user's reported conversation or instruction as a note.", {"lead_id": ID, "body": TEXT}, ["lead_id", "body"], writes=True),
    tool("list_sales_people", "Checking the human sales team", "AI Agents", "Find active human salespeople and channel partners."),
    tool("assign_sales_person", "Handing over to a salesperson", "CRM", "Assign an active salesperson. Saves the handover; does not call/message that person.",
         {"lead_id": ID, "sales_agent_id": ID}, ["lead_id", "sales_agent_id"], writes=True),
    tool("list_tasks", "Reading team tasks", "Tasks", "Read paginated workspace tasks and current execution state.",
         {"status": {"type": "string", "enum": ["pending", "running", "done", "failed", "awaiting_approval"]}, "offset": {"type": "integer", "minimum": 0, "maximum": 10000}}),
    tool("list_properties", "Reading property inventory", "Properties", "Read paginated property records.",
         {"offset": {"type": "integer", "minimum": 0, "maximum": 10000}}),
    tool("suggest_followup", "Consulting the follow-up specialist", "CRM", "Delegate a next-action recommendation to the existing specialist. Does not save a reminder.",
         {"lead_id": ID}, ["lead_id"], agent="Follow-up specialist"),
    tool("start_initial_qualification", "Delegating initial qualification", "AI Agents", "Start initial qualification only when explicitly instructed. Follow-up calls belong to humans. Returns acceptance, not a finished call.",
         {"lead_id": ID}, ["lead_id"], writes=True, agent="Qualification agent"),
    tool("get_qualification_status", "Checking qualification progress", "AI Agents", "Read the latest initial qualification session and outcome.",
         {"lead_id": ID}, ["lead_id"], agent="Qualification agent"),
]
REGISTRY = {item["name"]: item for item in TOOLS}


def compact_lead(lead):
    return {key: lead.get(key) for key in ("id", "field_values", "status", "customer_status", "created_at", "sales_assignment", "qualification_status", "qualification_call", "auto_qualification_enabled", "lead_notes")}


class ManagerTools:
    def __init__(self, db, workspace, request):
        self.db, self.workspace, self.request = db, workspace, request
        self.ws_id = str(workspace["_id"])
        self.known_leads, self.known_reminders, self.known_people = set(), set(), set()
        self.field_keys = None

    async def lead(self, lead_id):
        from crm import lead_query
        row = await self.db.crm_leads.find_one({**lead_query(self.ws_id), "_id": ObjectId(lead_id)})
        if not row: raise HTTPException(404, "Active lead not found in this workspace")
        return row

    async def execute(self, name, args):
        if name not in REGISTRY: raise ValueError("Unknown manager tool")
        validate(args, REGISTRY[name]["schema"]["function"]["parameters"])
        from auth import get_current_user_and_workspace
        await get_current_user_and_workspace(self.request, self.db, self.ws_id)
        from crm import doc_out, ensure_crm_settings
        from crm_workspace import ReminderInput, ReminderStatus
        if "lead_id" in args:
            await self.lead(args["lead_id"])
            if REGISTRY[name]["writes"] and args["lead_id"] not in self.known_leads:
                raise ValueError("Read or search this lead before changing or delegating it")
        if "reminder_id" in args and args["reminder_id"] not in self.known_reminders:
            raise ValueError("Read follow-ups to identify this reminder before changing it")
        if name in {"create_lead", "update_lead"} and "field_values" in args:
            if self.field_keys is None: raise ValueError("Read CRM configuration before writing lead fields")
            if set(args["field_values"]) - self.field_keys: raise ValueError("Use only configured active lead fields")
        if name == "get_business_context":
            return {"name": self.workspace.get("name"), "business": self.workspace.get("brain", {}).get("business_profile", {}),
                    "goals_constraints": self.workspace.get("brain", {}).get("goals_constraints", {}),
                    "strategy": self.workspace.get("strategy_summary", ""), "roadmap": self.workspace.get("roadmap", []), "now_utc": datetime.now(timezone.utc).isoformat()}
        if name == "get_crm_configuration":
            settings = await ensure_crm_settings(self.db, self.ws_id)
            self.field_keys = {field["key"] for field in settings.get("fields", []) if field.get("active", True)}
            return {"fields": settings.get("fields", []), "states": settings.get("states", [])}
        if name == "search_leads":
            from crm import paginated_leads
            result = await paginated_leads(self.db, self.ws_id, await ensure_crm_settings(self.db, self.ws_id), status=args.get("status"), search=args.get("search", ""), page=args.get("page", 1), limit=20)
            self.known_leads.update(row["id"] for row in result["items"])
            return {**result, "items": [compact_lead(row) for row in result["items"]]}
        if name == "get_lead":
            result = doc_out(await self.lead(args["lead_id"]))
            self.known_leads.add(args["lead_id"])
            return compact_lead(result)
        if name == "get_crm_analytics":
            from crm import crm_analytics_overview
            from crm import lead_query
            result = await crm_analytics_overview(self.ws_id, self.request)
            total = await self.db.crm_leads.count_documents(lead_query(self.ws_id))
            return {**result, "active_lead_total": total, "analytics_limit": 5000, "analytics_capped": total > 5000}
        if name == "list_followups":
            from crm_workspace import reminders
            result = await reminders(self.ws_id, self.request, lead_id=args.get("lead_id"),
                start=datetime.fromisoformat(args["start"]) if args.get("start") else None,
                end=datetime.fromisoformat(args["end"]) if args.get("end") else None,
                status=args.get("status", "pending"), overdue=args.get("overdue", False), offset=args.get("offset", 0), limit=30)
            self.known_reminders.update(row["id"] for row in result["items"])
            self.known_leads.update(row["lead_id"] for row in result["items"] if row.get("lead_available"))
            return result
        if name in {"create_followup", "update_followup", "complete_followup"}:
            from crm_workspace import create_reminder, update_reminder
            body = ReminderStatus(**{key: value for key, value in args.items() if key != "reminder_id"}) if name == "complete_followup" else ReminderInput(**{key: value for key, value in args.items() if key not in {"lead_id", "reminder_id"}})
            result = await create_reminder(self.ws_id, args["lead_id"], self.request, body) if name == "create_followup" else await update_reminder(self.ws_id, args["reminder_id"], self.request, body)
            self.known_reminders.add(result["id"])
            return result
        if name == "create_lead":
            from crm import create_lead
            result = await create_lead(self.ws_id, self.request, {**args, "trigger_ai_call": args.get("trigger_ai_call", True)})
            self.known_leads.add(result["id"])
            return compact_lead(result)
        if name == "update_lead":
            from crm import update_lead
            if not args.get("field_values") and not args.get("status"): raise ValueError("Supply requested fields or a stage")
            result = await update_lead(self.ws_id, args["lead_id"], self.request, {key: value for key, value in args.items() if key != "lead_id"})
            return compact_lead(result)
        if name == "add_lead_note":
            from crm import add_lead_note
            return await add_lead_note(self.ws_id, args["lead_id"], self.request, {"body": args["body"], "author": "AI Manager", "source": "manager_agent"})
        if name == "list_sales_people":
            rows = await self.db.crm_sales_people.find({"workspace_id": self.ws_id, "active": True}).to_list(100)
            self.known_people.update(str(row["_id"]) for row in rows)
            return {"items": [{key: doc_out(row).get(key) for key in ("id", "name", "role", "active")} for row in rows]}
        if name == "assign_sales_person":
            from sales_team import assign_lead
            if args["sales_agent_id"] not in self.known_people: raise ValueError("Read the sales team before choosing an assignee")
            lead = await self.lead(args["lead_id"])
            assignment = {**(lead.get("sales_assignment") or {}), "sales_agent_id": args["sales_agent_id"]}
            return compact_lead(await assign_lead(self.ws_id, args["lead_id"], self.request, assignment))
        if name in {"list_tasks", "list_properties"}:
            query = {"workspace_id": self.ws_id}
            if args.get("status"): query["status"] = args["status"]
            collection = self.db.tasks if name == "list_tasks" else self.db.properties
            projection = {"title": 1, "name": 1, "status": 1, "scheduled_time": 1, "objective": 1, "lead_id": 1, "source": 1, "location": 1, "price": 1, "category": 1}
            rows = await collection.find(query, projection).skip(args.get("offset", 0)).limit(30).to_list(30)
            return {"items": [doc_out(row) for row in rows], "total": await collection.count_documents(query)}
        if name == "suggest_followup":
            from crm_workspace import suggest_follow_up
            return await suggest_follow_up(self.ws_id, args["lead_id"], self.request)
        if name == "start_initial_qualification":
            from plivo_calls import start_qualification_call
            lead = await self.lead(args["lead_id"])
            call = lead.get("qualification_call") or {}
            if lead.get("customer_status") == "customer" or lead.get("qualification_status") in {"qualified", "unqualified"} or call.get("qualification_status") in {"qualified", "unqualified"} or call.get("status") == "completed":
                raise ValueError("Qualification is complete. Hand customer follow-up calls to a human salesperson.")
            result = await start_qualification_call(self.db, self.ws_id, args["lead_id"], self.request)
            if result.get("status") not in {"started", "queued", "scheduled", "answered", "reconcile_required"}:
                raise ValueError("Initial qualification was not accepted. Check the lead and voice provider configuration.")
            return {"delegated": True, "job_type": "qualification", "lead_id": args["lead_id"],
                    "session_id": result.get("session_id"), "state": result.get("status", "started"), "provider": result.get("provider"), "message": "Qualification requested; call outcome is pending."}
        if name == "get_qualification_status":
            lead = await self.lead(args["lead_id"])
            session = await self.db.plivo_call_sessions.find_one({"workspace_id": self.ws_id, "lead_id": args["lead_id"]}, sort=[("created_at", -1)])
            return {"qualification": lead.get("qualification_call", {}), "session": {key: (session or {}).get(key) for key in ("status", "created_at", "updated_at", "provider")}}
        raise ValueError("Tool implementation unavailable")
