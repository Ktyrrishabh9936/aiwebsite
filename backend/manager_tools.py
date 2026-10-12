"""Model-selected application capabilities; no prescribed conversation sequences."""
from datetime import datetime, timezone
from bson import ObjectId
from fastapi import HTTPException
from jsonschema import validate

from manager_page_tools import PAGE_TOOLS, PageTools
from manager_schema import FIELDS, ID, OFFSET, TEXT, TIME, tool

CORE_TOOLS = [
    tool("get_sales_briefing", "Reviewing live sales priorities", "Overview", "Read live pipeline risks, overdue work, offer questions, team and products. No writes or calls.", page=""),
    tool("get_lead_sales_insights", "Reviewing lead sales insights", "CRM", "Inspect grounded lead risks and next actions without changing qualification or customer state.", {"lead_id": ID}, ["lead_id"], page="crm"),
    tool("get_business_context", "Reading business goals", "Brain", "Read business profile, saved strategy, roadmap and current time.", page="brain"),
    tool("get_crm_configuration", "Reading CRM fields and stages", "CRM", "Discover valid fields, required fields and stages before creating or updating leads.", page="crm"),
    tool("search_leads", "Finding leads", "CRM", "Find leads by name, phone or custom field text. status is an optional pipeline stage key (e.g. new, won); omit it when searching by name. Paginated; total is the matching count. Ask if multiple names match.",
         {"search": {"type": "string", "maxLength": 200}, "status": {"type": "string", "maxLength": 100}, "page": {"type": "integer", "minimum": 1, "maximum": 10000}}, page="crm"),
    tool("get_lead", "Reading lead details", "CRM", "Read an active lead's fields, notes, qualification and assignment.", {"lead_id": ID}, ["lead_id"], page="crm"),
    tool("get_crm_analytics", "Checking CRM totals", "CRM", "Read lead/payment analytics (collections, dues, conversions) for up to 5000 most recent leads, with an exact active lead total and a flag when capped.", page="crm"),
    tool("list_followups", "Checking follow-ups", "CRM", "Query actual follow-ups with lead names. overdue=true finds overdue work. start/end bound due time.",
         {"lead_id": ID, "status": {"type": "string", "enum": ["pending", "done", "cancelled", "all"]}, "overdue": {"type": "boolean"}, "start": TIME, "end": TIME, "offset": OFFSET}, page="crm?tab=reminders"),
    tool("create_followup", "Scheduling a human follow-up", "CRM", "Save a reminder with a clear due time and title. Does not call the customer.",
         {"lead_id": ID, "title": {**TEXT, "maxLength": 200}, "note": TEXT, "due_at": TIME}, ["lead_id", "title", "due_at"], writes=True, page="crm?tab=reminders"),
    tool("update_followup", "Updating a follow-up", "CRM", "Edit/reschedule a reminder identified by list_followups.",
         {"reminder_id": ID, "title": {**TEXT, "maxLength": 200}, "note": TEXT, "due_at": TIME}, ["reminder_id", "title", "due_at"], writes=True, page="crm?tab=reminders"),
    tool("complete_followup", "Recording follow-up outcome", "CRM", "Mark a reminder done or cancelled only after the user reports the outcome.",
         {"reminder_id": ID, "status": {"type": "string", "enum": ["done", "cancelled"]}, "outcome": {**TEXT, "maxLength": 1000}}, ["reminder_id", "status"], writes=True, page="crm?tab=reminders"),
    tool("create_lead", "Adding a lead", "CRM", "Save a new lead using the existing automatic initial qualification workflow. Ask for missing required fields. Automatic calling defaults to true; set trigger_ai_call=false ONLY when the owner explicitly asks to skip it. Do not separately start a qualification call after creation; the existing workflow schedules it.",
         {"field_values": FIELDS, "trigger_ai_call": {"type": "boolean", "default": True}}, ["field_values"], writes=True, page="crm"),
    tool("update_lead", "Updating lead information", "CRM", "Update requested fields/stage after reading the lead and valid configuration. Never invent customer outcomes.",
         {"lead_id": ID, "field_values": FIELDS, "status": {"type": "string", "maxLength": 100}}, ["lead_id"], writes=True, page="crm"),
    tool("add_lead_note", "Saving a lead note", "CRM", "Save the user's reported conversation or instruction as a note.", {"lead_id": ID, "body": TEXT}, ["lead_id", "body"], writes=True, page="crm"),
    tool("list_sales_people", "Checking the human sales team", "AI Agents", "Find human salespeople and channel partners. include_inactive also returns deactivated people.",
         {"include_inactive": {"type": "boolean"}}, page="crm?tab=sales-team"),
    tool("assign_sales_person", "Handing over to a salesperson", "CRM", "Assign an active salesperson. Saves the handover; does not call/message that person.",
         {"lead_id": ID, "sales_agent_id": ID}, ["lead_id", "sales_agent_id"], writes=True, page="crm"),
    tool("list_tasks", "Reading team tasks", "Tasks", "Read paginated workspace tasks with source, agent, approval need and output. Needed before running, approving or completing a task.",
         {"status": {"type": "string", "enum": ["pending", "running", "done", "failed", "awaiting_approval"]}, "offset": OFFSET}, page="tasks"),
    tool("list_properties", "Reading property inventory", "Properties", "Read property and project inventory with status, price and generated unit counts.",
         {"search": {"type": "string", "maxLength": 200}, "category": {"type": "string", "enum": ["residential", "commercial", "land", "industrial", "other"]},
          "status": {"type": "string", "enum": ["available", "reserved", "sold", "inactive"]}}, page="properties"),
    tool("suggest_followup", "Consulting the follow-up specialist", "CRM", "Delegate a next-action recommendation to the existing specialist. Does not save a reminder.",
         {"lead_id": ID}, ["lead_id"], agent="Follow-up specialist", page="crm"),
    tool("start_initial_qualification", "Delegating initial qualification", "AI Agents", "Start initial qualification only when explicitly instructed. Follow-up calls belong to humans. Returns acceptance, not a finished call.",
         {"lead_id": ID}, ["lead_id"], writes=True, agent="Qualification agent", page="crm"),
    tool("get_product_help", "Checking Arevei product guide", "Help", "Look up how Arevei features work, why they help and how to set them up (AI Manager, Brain, strategy, CRM, qualification, voice agent, SMS, WhatsApp, Ads to CRM, Landing Page Forms, sales team, properties, notifications, billing). Use for any question about the product itself or what to set up next.",
         {"question": {"type": "string", "minLength": 1, "maxLength": 500}}, ["question"]),
    tool("get_qualification_status", "Checking qualification progress", "AI Agents", "Read the latest initial qualification session and outcome.",
         {"lead_id": ID}, ["lead_id"], agent="Qualification agent", page="crm"),
]
TOOLS = CORE_TOOLS + PAGE_TOOLS
REGISTRY = {item["name"]: item for item in TOOLS}


def compact_lead(lead):
    return {key: lead.get(key) for key in ("id", "field_values", "status", "customer_status", "created_at", "sales_assignment", "qualification_status", "qualification_call", "auto_qualification_enabled", "lead_notes")}


class ManagerTools(PageTools):
    def __init__(self, db, workspace, request):
        self.db, self.workspace, self.request = db, workspace, request
        self.ws_id = str(workspace["_id"])
        self.known_leads, self.known_reminders, self.known_people = set(), set(), set()
        # Records read in this run; writes to them are refused until they are read.
        self.known_inactive_people, self.known_customers, self.known_payments, self.known_archived = set(), set(), set(), set()
        self.known_items, self.known_offerings, self.known_properties, self.known_units = set(), set(), set(), set()
        self.known_tasks, self.known_profiles, self.known_forms, self.known_blogs = set(), set(), set(), set()
        self.field_keys = None

    KNOWN = ("known_leads", "known_reminders", "known_people", "known_inactive_people", "known_customers", "known_payments", "known_archived",
             "known_items", "known_offerings", "known_properties", "known_units", "known_tasks", "known_profiles", "known_forms", "known_blogs")

    def remembered(self):
        """Records read in this conversation; later turns may act on them without re-reading. Writes still validate scope."""
        return {key: sorted(getattr(self, key))[-500:] for key in self.KNOWN}

    def remember(self, saved):
        for key in self.KNOWN:
            getattr(self, key).update((saved or {}).get(key) or [])

    async def lead(self, lead_id):
        from crm import lead_query
        row = await self.db.crm_leads.find_one({**lead_query(self.ws_id), "_id": ObjectId(lead_id)})
        if not row: raise HTTPException(404, "Active lead not found in this workspace")
        return row

    async def execute(self, name, args):
        if name not in REGISTRY: raise ValueError("Unknown manager tool")
        schema = REGISTRY[name]["schema"]["function"]["parameters"]
        # Models often send null for omitted optional fields; drop them unless the field accepts null.
        args = {key: value for key, value in args.items() if value is not None or "null" in str(schema["properties"].get(key, {}).get("type", ""))}
        validate(args, schema)
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
        if name == "get_sales_briefing":
            from sales_leadership import snapshot
            return await snapshot(self.db, self.workspace)
        if name == "get_lead_sales_insights":
            from sales_leadership import lead_insight
            lead = await self.lead(args["lead_id"])
            tasks = await self.db.tasks.find({"workspace_id": self.ws_id, "lead_id": args["lead_id"], "status": {"$in": ["pending", "awaiting_approval"]}}).to_list(200)
            result = lead_insight(lead, tasks, self.workspace.get("sales_profile") or {})
            customer_id = lead.get("customer_id") or (str(lead["_id"]) if lead.get("customer_status") == "customer" or lead.get("status") == "won" else None)
            if customer_id and not lead.get("is_test_lead"):
                from customer_lifecycle import customer_history
                result["customer"] = await customer_history(self.db, self.ws_id, customer_id, self.workspace.get("currency") or "INR")
                result["request"] = lead.get("repeat_request") or ""
                result["opportunity_kind"] = lead.get("opportunity_kind") or "initial"
            return result
        if name == "get_business_context":
            return {"name": self.workspace.get("name"), "business": self.workspace.get("brain", {}).get("business_profile", {}),
                    "goals_constraints": self.workspace.get("brain", {}).get("goals_constraints", {}),
                    "sales_profile": self.workspace.get("sales_profile", {}), "strategy": self.workspace.get("strategy_summary", ""), "roadmap": self.workspace.get("roadmap", []), "now_utc": datetime.now(timezone.utc).isoformat()}
        if name == "get_crm_configuration":
            settings = await ensure_crm_settings(self.db, self.ws_id)
            self.field_keys = {field["key"] for field in settings.get("fields", []) if field.get("active", True)}
            return {"fields": settings.get("fields", []), "states": settings.get("states", [])}
        if name == "search_leads":
            from crm import paginated_leads
            settings = await ensure_crm_settings(self.db, self.ws_id)
            stages = [state["key"] for state in settings.get("states", [])]
            if args.get("status") and args["status"] not in stages:
                raise ValueError(f"'{args['status']}' is not a pipeline stage. Use one of {stages}, or omit status. Customers are listed with list_customers.")
            result = await paginated_leads(self.db, self.ws_id, settings, status=args.get("status"), search=args.get("search", ""), page=args.get("page", 1), limit=20)
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
            total = await self.db.crm_leads.count_documents(lead_query(self.ws_id, exclude_test=True))
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
            query = {"workspace_id": self.ws_id, **({} if args.get("include_inactive") else {"active": True})}
            rows = await self.db.crm_sales_people.find(query).to_list(100)
            self.known_people.update(str(row["_id"]) for row in rows if row.get("active", True))
            self.known_inactive_people.update(str(row["_id"]) for row in rows if not row.get("active", True))
            return {"items": [{key: doc_out(row).get(key) for key in ("id", "name", "role", "phone", "email", "active")} for row in rows]}
        if name == "assign_sales_person":
            from sales_team import assign_lead
            if args["sales_agent_id"] not in self.known_people: raise ValueError("Read the sales team before choosing an assignee")
            lead = await self.lead(args["lead_id"])
            assignment = {**(lead.get("sales_assignment") or {}), "sales_agent_id": args["sales_agent_id"]}
            return compact_lead(await assign_lead(self.ws_id, args["lead_id"], self.request, assignment))
        if name == "list_tasks":
            query = {"workspace_id": self.ws_id}
            if args.get("status"): query["status"] = args["status"]
            projection = {"title": 1, "status": 1, "scheduled_time": 1, "objective": 1, "lead_id": 1, "source": 1, "agent": 1,
                          "deliverable_type": 1, "requires_approval": 1, "output_summary": 1, "output_ref": 1, "outcome": 1}
            rows = await self.db.tasks.find(query, projection).sort("scheduled_time", 1).skip(args.get("offset", 0)).limit(30).to_list(30)
            self.known_tasks.update(str(row["_id"]) for row in rows)
            items = [{**doc_out(row), "output_summary": str(row.get("output_summary") or "")[:400]} for row in rows]
            return {"items": items, "total": await self.db.tasks.count_documents(query)}
        if name == "list_properties":
            from properties import list_properties
            result = await list_properties(self.ws_id, self.request, search=args.get("search", ""), category=args.get("category", ""), status=args.get("status", ""))
            self.known_properties.update(row["id"] for row in result["items"])
            keys = ("id", "name", "container_kind", "category", "subtype", "location", "price", "status", "generated_units", "assigned_agent")
            return {"items": [{key: row.get(key) for key in keys} for row in result["items"][:60]], "total": len(result["items"]), "currency": result.get("currency")}
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
        if name == "get_product_help":
            import product_knowledge
            matches = product_knowledge.search(args["question"], limit=2) or [product_knowledge.get("getting-started-with-arevei")]
            return {"docs": [m for m in matches if m], "contact": {"name": "arevei", "email": "admin@arevei.com"}}
        if name == "get_qualification_status":
            lead = await self.lead(args["lead_id"])
            session = await self.db.plivo_call_sessions.find_one({"workspace_id": self.ws_id, "lead_id": args["lead_id"]}, sort=[("created_at", -1)])
            return {"qualification": lead.get("qualification_call", {}), "session": {key: (session or {}).get(key) for key in ("status", "created_at", "updated_at", "provider")}}
        result, handled = await self.run_page_tool(name, args)
        if handled: return result
        raise ValueError("Tool implementation unavailable")
