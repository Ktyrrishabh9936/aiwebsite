"""AI Manager capabilities for every workspace page beyond core lead/follow-up work.

Each tool reuses the page's own route handler so validation, module gating and
workspace scoping stay identical to Human Mode. Writes require the target record
to have been read in the same run, mirroring the lead guard in manager_tools.
"""
from bson import ObjectId
from pydantic import ValidationError

from manager_schema import DATE, ID, MONEY, OFFSET, SHORT, TEXT, tool

PROFILE_SECTION = {"type": "object", "maxProperties": 20, "propertyNames": {"pattern": "^[a-z_]{1,40}$"},
                   "additionalProperties": {"type": ["string", "array"], "maxLength": 4000, "items": {"type": "string", "maxLength": 500}, "maxItems": 30}}
STAGES = {"type": "array", "minItems": 1, "maxItems": 24, "items": {"type": "object", "additionalProperties": False, "required": ["name", "amount"],
          "properties": {"id": {"type": "string", "maxLength": 40, "description": "Existing stage id to keep its paid history"},
                         "name": {"type": "string", "minLength": 1, "maxLength": 120}, "amount": MONEY, "due_timing": SHORT}}}

PAGE_TOOLS = [
    # Customers, payments, receipts and invoices
    tool("list_customers", "Reading customers", "Customers", "List converted customers with lifetime value, outstanding dues and open repeat opportunities. Paginated.",
         {"search": SHORT, "page": {"type": "integer", "minimum": 1, "maximum": 1000}}, page="customers"),
    tool("get_customer", "Reading customer history", "Customers", "Read one customer's deals, payments collected, outstanding dues and repeat opportunities. customer_id is the original converted lead id.",
         {"customer_id": ID}, ["customer_id"], page="customers"),
    tool("create_repeat_opportunity", "Opening a repeat opportunity", "Customers", "Open an upsell, cross-sell or repeat-purchase deal for an existing customer. No qualification call is scheduled.",
         {"customer_id": ID, "request": {**TEXT, "maxLength": 2000}, "kind": {"type": "string", "enum": ["upsell", "repeat_purchase", "cross_sell"]}},
         ["customer_id", "request"], writes=True, page="customers"),
    tool("get_lead_payments", "Reading payments and receipts", "Customers", "Read a lead/customer's conversion type, payment plan stages (with ids), totals, due amount, receipts and final invoice. Required before recording payments or editing plans.",
         {"lead_id": ID}, ["lead_id"], page="crm"),
    tool("convert_to_customer", "Converting lead to customer", "Customers", "Mark a lead won and a customer. single_payment needs total_amount; payment_plan needs stages and the deal total_amount. Only when the owner reports the deal is closed.",
         {"lead_id": ID, "conversion_type": {"type": "string", "enum": ["single_payment", "payment_plan"]}, "total_amount": MONEY, "stages": STAGES},
         ["lead_id", "conversion_type"], writes=True, page="crm"),
    tool("set_payment_plan", "Updating payment plan", "Customers", "Replace a customer's payment plan stages. Include existing stage ids to keep paid stages and their receipts.",
         {"lead_id": ID, "total_amount": MONEY, "stages": STAGES}, ["lead_id", "stages"], writes=True, page="crm"),
    tool("record_payment", "Recording payment receipt", "Customers", "Record a payment the owner reports and generate its receipt. Payment-plan customers need stage_id (pay stages in order). Never invent amounts, dates or methods.",
         {"lead_id": ID, "amount": MONEY, "payment_method": {"type": "string", "maxLength": 60}, "payment_date": DATE, "stage_id": {"type": "string", "maxLength": 40},
          "total_amount": {**MONEY, "description": "Deal total for single-payment customers with no total set yet"},
          "transaction_id": {"type": "string", "maxLength": 120}, "description": {"type": "string", "maxLength": 500}},
         ["lead_id", "amount"], writes=True, page="crm"),
    tool("generate_final_invoice", "Generating final invoice", "Customers", "Generate the final invoice after all dues are paid.",
         {"lead_id": ID, "description": {"type": "string", "maxLength": 500}}, ["lead_id"], writes=True, page="crm"),
    # CRM extras
    tool("set_lead_labels", "Updating lead tags", "CRM", "Replace a lead's tags and/or mark the relationship as lead or customer without changing pipeline stage.",
         {"lead_id": ID, "tags": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 50}, "maxItems": 50},
          "customer_status": {"type": "string", "enum": ["lead", "customer"]}}, ["lead_id"], writes=True, page="crm"),
    tool("list_offerings", "Reading sellable inventory", "CRM", "List products, services, properties and flats currently available to attach to a lead."),
    tool("set_lead_opportunity", "Attaching product to lead", "CRM", "Attach an available product, service, property or flat (from list_offerings) to a lead's deal.",
         {"lead_id": ID, "item_id": ID, "module": {"type": "string", "enum": ["agency", "real_estate"]}, "quantity": {"type": "integer", "minimum": 1, "maximum": 100000}, "amount": MONEY},
         ["lead_id", "item_id", "module"], writes=True, page="crm"),
    tool("archive_lead", "Moving lead to trash", "CRM", "Move a lead to trash (restorable for 30 days). Only when the owner explicitly asks to delete or archive this lead.",
         {"lead_id": ID}, ["lead_id"], writes=True, page="crm"),
    tool("list_archived_leads", "Reading trashed leads", "CRM", "Find leads in trash by name or phone.", {"search": SHORT}, page="crm"),
    tool("restore_lead", "Restoring lead from trash", "CRM", "Restore a trashed lead found with list_archived_leads.", {"archived_lead_id": ID}, ["archived_lead_id"], writes=True, page="crm"),
    # Products and services
    tool("list_products", "Reading products and services", "Products", "List catalog products and services with price, stock and status.",
         {"search": SHORT, "kind": {"type": "string", "enum": ["product", "service"]}, "status": {"type": "string", "enum": ["active", "inactive", "sold_out"]}}, page="products-services"),
    tool("create_product", "Adding product or service", "Products", "Add a catalog product or service.",
         {"name": {"type": "string", "minLength": 1, "maxLength": 200}, "kind": {"type": "string", "enum": ["product", "service"]}, "price": MONEY,
          "description": {"type": "string", "maxLength": 2000}, "sku": {"type": "string", "maxLength": 80}, "stock_quantity": {"type": "integer", "minimum": 0, "maximum": 10000000},
          "status": {"type": "string", "enum": ["active", "inactive", "sold_out"]}}, ["name", "kind"], writes=True, page="products-services"),
    tool("update_product", "Updating product or service", "Products", "Change a catalog item's fields. Mark inactive instead of deleting.",
         {"item_id": ID, "name": {"type": "string", "minLength": 1, "maxLength": 200}, "price": MONEY, "description": {"type": "string", "maxLength": 2000},
          "sku": {"type": "string", "maxLength": 80}, "stock_quantity": {"type": "integer", "minimum": 0, "maximum": 10000000},
          "status": {"type": "string", "enum": ["active", "inactive", "sold_out"]}}, ["item_id"], writes=True, page="products-services"),
    # Properties
    tool("create_property", "Adding a property", "Properties", "Add an individual property or land listing. Multi-unit projects are set up on the Properties page.",
         {"name": {"type": "string", "minLength": 1, "maxLength": 200}, "category": {"type": "string", "enum": ["residential", "commercial", "land", "industrial", "other"]},
          "subtype": {"type": "string", "maxLength": 80}, "location": {"type": "string", "maxLength": 300}, "price": MONEY,
          "status": {"type": "string", "enum": ["available", "reserved", "inactive"]}}, ["name", "category"], writes=True, page="properties"),
    tool("update_property", "Updating a property", "Properties", "Change a property's name, location, price, category, subtype or status (sold comes from lead conversion).",
         {"property_id": ID, "name": {"type": "string", "minLength": 1, "maxLength": 200}, "category": {"type": "string", "enum": ["residential", "commercial", "land", "industrial", "other"]},
          "subtype": {"type": "string", "maxLength": 80}, "location": {"type": "string", "maxLength": 300}, "price": MONEY,
          "status": {"type": "string", "enum": ["available", "reserved", "inactive"]}}, ["property_id"], writes=True, page="properties"),
    tool("list_property_units", "Reading flats and units", "Properties", "List a project's flats/units with status and asking price.",
         {"property_id": ID, "status": {"type": "string", "enum": ["available", "reserved", "sold", "rented", "inactive"]}, "bhk": {"type": "string", "maxLength": 20},
          "tower": {"type": "string", "maxLength": 40}, "offset": OFFSET}, ["property_id"], page="properties"),
    tool("update_property_unit", "Updating a flat", "Properties", "Change a flat's asking price, listing type or status (available/reserved/inactive). Sales happen through lead conversion.",
         {"property_id": ID, "unit_id": ID, "asking_price": MONEY, "listing_type": {"type": "string", "enum": ["sale", "rent"]},
          "status": {"type": "string", "enum": ["available", "reserved", "inactive"]}}, ["property_id", "unit_id"], writes=True, page="properties"),
    # Tasks
    tool("complete_sales_task", "Recording task outcome", "Tasks", "Mark a pending sales-manager task done with the outcome the owner reported.",
         {"task_id": ID, "outcome": {"type": "string", "minLength": 3, "maxLength": 2000}}, ["task_id", "outcome"], writes=True, page="tasks"),
    tool("run_task", "Running a specialist task", "Tasks", "Run a pending AI task (blog, SEO audit, social pack, analysis) through its specialist agent. Blog tasks without approval may auto-publish.",
         {"task_id": ID}, ["task_id"], writes=True, agent="Specialist agent", page="tasks"),
    tool("approve_task", "Approving task output", "Tasks", "Approve an awaiting-approval task; a blog draft becomes published. Only on explicit approval.",
         {"task_id": ID}, ["task_id"], writes=True, page="tasks"),
    # Brain and sales strategy
    tool("update_business_profile", "Updating business knowledge", "Brain", "Merge facts into the Brain. business_profile keys: company_name, industry, description, offers, pricing_summary, locations, founders. goals_constraints keys: kpis, priorities, restrictions, publishing_cadence.",
         {"business_profile": PROFILE_SECTION, "goals_constraints": PROFILE_SECTION}, writes=True, page="brain"),
    tool("update_sales_profile", "Updating sales setup", "Brain", "Change sales setup fields (offerings, ideal_customer, lead_sources, team_capacity, monthly_revenue_target, monthly_sales_budget, business_stage, offer_confidence, customer_feedback, constraints, stale_days). Other fields are kept.",
         {"organisation": {"type": "string", "maxLength": 300}, "offerings": {"type": "string", "maxLength": 5000}, "ideal_customer": {"type": "string", "maxLength": 2000},
          "lead_sources": {"type": "string", "maxLength": 2000}, "team_capacity": {"type": "string", "maxLength": 2000},
          "monthly_revenue_target": {"type": "number", "exclusiveMinimum": 0}, "monthly_sales_budget": {"type": "number", "minimum": 0},
          "business_stage": {"type": "string", "enum": ["starting", "existing"]}, "offer_confidence": {"type": "string", "enum": ["unknown", "testing", "validated"]},
          "customer_feedback": {"type": "string", "maxLength": 5000}, "constraints": {"type": "string", "maxLength": 2000},
          "stale_days": {"type": "integer", "minimum": 1, "maximum": 180}}, writes=True, page="brain?tab=sales"),
    tool("generate_sales_strategy", "Building sales strategy", "Brain", "Regenerate the saved sales strategy and roadmap from the Brain and sales setup.",
         writes=True, agent="Strategy agent", page="brain?tab=sales"),
    tool("run_sales_review", "Running sales review", "Tasks", "Run the sales review now; it refreshes pipeline priorities and creates/updates sales tasks.",
         writes=True, page="tasks"),
    # Sales team
    tool("add_sales_person", "Adding a salesperson", "AI Agents", "Add a human sales agent or channel partner.",
         {"name": {"type": "string", "minLength": 1, "maxLength": 120}, "role": {"type": "string", "enum": ["sales_agent", "channel_partner"]},
          "phone": {"type": "string", "maxLength": 40}, "email": {"type": "string", "maxLength": 200}}, ["name", "role"], writes=True, page="crm?tab=sales-team"),
    tool("set_sales_person_active", "Updating salesperson status", "AI Agents", "Activate or deactivate a salesperson found with list_sales_people.",
         {"sales_agent_id": ID, "active": {"type": "boolean"}}, ["sales_agent_id", "active"], writes=True, page="crm?tab=sales-team"),
    # Qualification
    tool("get_qualification_setup", "Reading qualification setup", "Qualification", "Read qualification profiles, the default profile and AI calling settings (mode, delay, window).", page="qualification"),
    tool("update_calling_settings", "Updating AI calling settings", "Qualification", "Change automatic qualification calling: call_mode automatic/scheduled/manual, delay, timezone or calling window. manual stops scheduled calls.",
         {"call_mode": {"type": "string", "enum": ["automatic", "scheduled", "manual"]}, "initial_delay_seconds": {"type": "integer", "minimum": 0, "maximum": 86400},
          "timezone": {"type": "string", "maxLength": 100}, "window_start": {"type": "string", "pattern": "^[0-2][0-9]:[0-5][0-9]$"}, "window_end": {"type": "string", "pattern": "^[0-2][0-9]:[0-5][0-9]$"}},
         writes=True, page="qualification"),
    tool("set_default_qualification_profile", "Choosing default qualification profile", "Qualification", "Make a profile from get_qualification_setup the default for new leads.",
         {"profile_id": ID}, ["profile_id"], writes=True, page="qualification"),
    tool("assign_qualification_profile", "Assigning qualification profile", "Qualification", "Use a specific qualification profile for one lead, or null for the default.",
         {"lead_id": ID, "profile_id": {**ID, "type": ["string", "null"]}}, ["lead_id", "profile_id"], writes=True, page="crm"),
    # Landing page forms and workflows
    tool("list_lead_forms", "Reading landing page forms", "Workflows", "List landing page lead forms with status and submission stats.", page="workflows/landing-forms"),
    tool("create_lead_form", "Creating landing page form", "Workflows", "Create a landing page lead form; embed code is on the Landing Page Forms page.",
         {"name": {"type": "string", "minLength": 1, "maxLength": 120}, "default_country": {"type": "string", "pattern": "^[A-Z]{2}$"}}, ["name"], writes=True, page="workflows/landing-forms"),
    tool("update_lead_form", "Updating landing page form", "Workflows", "Rename a form or pause/activate it.",
         {"form_id": ID, "name": {"type": "string", "minLength": 1, "maxLength": 120}, "status": {"type": "string", "enum": ["active", "paused"]}}, ["form_id"], writes=True, page="workflows/landing-forms"),
    tool("list_form_submissions", "Reading form submissions", "Workflows", "Read a form's 50 latest submissions and their lead outcome.", {"form_id": ID}, ["form_id"], page="workflows/landing-forms"),
    tool("list_workflows", "Reading workflows", "Workflows", "Read automation workflows (Ads to CRM sheet sync) and their publish status.", page="workflows"),
    # Blogs
    tool("list_blogs", "Reading blogs", "Blogs", "List blog posts with status.", {"status": {"type": "string", "enum": ["draft", "published"]}}, page="blogs"),
    tool("generate_blog_draft", "Writing a blog draft", "Blogs", "Write a new blog draft on a topic using the Brain. Saved as draft, not published.",
         {"topic": {"type": "string", "minLength": 3, "maxLength": 300}, "objective": {"type": "string", "maxLength": 1000}}, ["topic"], writes=True, agent="Content agent", page="blogs"),
    tool("set_blog_status", "Publishing or unpublishing blog", "Blogs", "Publish or revert a blog to draft. Publish only on explicit request.",
         {"blog_id": ID, "status": {"type": "string", "enum": ["draft", "published"]}}, ["blog_id", "status"], writes=True, page="blogs"),
    # Workspace settings
    tool("get_workspace_settings", "Reading workspace settings", "Settings", "Read workspace name, currency, enabled modules, CRM stages, tag library and receipt/invoice organization details.", page="settings"),
    tool("save_crm_tags", "Saving reusable tags", "Settings", "Add reusable CRM tags (or recolor existing ones) in the tag library.",
         {"names": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 50}, "minItems": 1, "maxItems": 50},
          "color": {"type": "string", "enum": ["emerald", "amber", "blue", "violet", "rose", "slate", "cyan", "orange"]}}, ["names"], writes=True, page="crm?tab=settings"),
    tool("list_notifications", "Reading notifications", "Overview", "Read the 20 latest workspace notifications and alerts.", page=""),
]


def pick(row, keys):
    return {key: row.get(key) for key in keys if row.get(key) not in (None, "", [], {})}


def plan_total(stages, total):
    """A plan without a total reports zero dues everywhere, so default it to the stage sum."""
    from crm import money_text, money_value
    stage_sum = sum(money_value(stage["amount"]) for stage in stages)
    if total and stage_sum - money_value(total) > 0.005:
        raise ValueError(f"Stage amounts add up to {money_text(stage_sum)}, more than the total {total}. Ask the owner which is correct.")
    return total or money_text(stage_sum)


def stage_view(stage, receipts):
    """Stage due_amount is the plan balance after that stage; name both figures explicitly for the model."""
    from crm import money_text, payment_stage_remaining_amount
    return {**pick(stage, ("id", "name", "amount", "paid_amount", "due_timing", "status")),
            "remaining_for_stage": money_text(payment_stage_remaining_amount(stage, receipts)),
            "plan_balance_after_stage": stage.get("due_amount") or "0"}


def receipt_view(receipt):
    keys = ("id", "receipt_number", "amount", "payment_date", "payment_method", "payment_stage", "stage_id", "status", "transaction_id")
    return {**pick(receipt, keys), "balance_due_after_payment": receipt.get("due_amount") or "0"}


def payments_view(lead):
    from crm import recalculate_payment_plan, single_payment_summary
    receipts = lead.get("receipts") or []
    view = {"lead_id": str(lead.get("_id") or lead.get("id")), "status": lead.get("status"), "customer_status": lead.get("customer_status") or "lead",
            "conversion_type": lead.get("conversion_type"), "opportunity": pick(lead.get("opportunity") or {}, ("name", "kind", "quantity", "total_minor", "currency", "sale_status")),
            "receipts": [receipt_view(r) for r in receipts[-30:]],
            "receipt_count": len(receipts)}
    if lead.get("conversion_type") == "payment_plan" or (lead.get("payment_plan") or {}).get("stages"):
        plan = recalculate_payment_plan(lead.get("payment_plan") or {}, receipts)
        view["payment_plan"] = {**pick(plan, ("status", "total_amount", "total_paid", "due_amount")),
            "stages": [stage_view(s, receipts) for s in plan.get("stages", [])]}
    if lead.get("conversion_type") != "payment_plan":
        view["summary"] = pick(single_payment_summary(lead, receipts), ("total_amount", "total_paid", "due_amount", "status"))
    if lead.get("final_invoice"):
        view["final_invoice"] = pick(lead["final_invoice"], ("invoice_number", "generated_at", "total_paid"))
    return view


def http_error(error):
    """Pydantic models used by route handlers raise before FastAPI can translate them."""
    first = (error.errors() or [{}])[0]
    return ValueError(f"Invalid {'.'.join(str(p) for p in first.get('loc', ())) or 'value'}: {first.get('msg', 'check the value')}"[:300])


class PageTools:
    """Mixin for ManagerTools. Handlers are named page_<tool name>."""

    async def run_page_tool(self, name, args):
        handler = getattr(self, f"page_{name}", None)
        if handler is None: return None, False
        try:
            return await handler(args), True
        except ValidationError as error:
            raise http_error(error) from None

    def require(self, known, key, message):
        if key not in known: raise ValueError(message)

    async def fresh_workspace(self):
        return await self.db.workspaces.find_one({"_id": self.workspace["_id"]}) or self.workspace

    # Customers, payments, receipts and invoices
    async def page_list_customers(self, args):
        from customer_lifecycle import customers
        result = await customers(self.ws_id, self.request, page=args.get("page", 1), limit=20, search=args.get("search", ""))
        for row in result["items"]:
            self.known_customers.add(row["id"])
            self.known_leads.update(deal["id"] for deal in row.get("deals", []) if not deal.get("archived"))
        return {**result, "items": [{**pick(row, ("id", "name", "phone", "email", "currency", "ltv", "outstanding", "lifecycle", "open_opportunities", "converted_at")),
                                     "deals": len(row.get("deals", []))} for row in result["items"]]}

    async def page_get_customer(self, args):
        from customer_lifecycle import customer
        result = await customer(self.ws_id, args["customer_id"], self.request)
        self.known_customers.add(result["id"])
        self.known_leads.update(deal["id"] for deal in result.get("deals", []) if not deal.get("archived"))
        return result

    async def page_create_repeat_opportunity(self, args):
        from customer_lifecycle import repeat_opportunity
        self.require(self.known_customers, args["customer_id"], "Read this customer before opening a repeat opportunity")
        lead = await repeat_opportunity(self.ws_id, args["customer_id"], self.request, {"request": args["request"], "kind": args.get("kind", "upsell")})
        self.known_leads.add(lead["id"])
        return {"id": lead["id"], "customer_id": args["customer_id"], "kind": lead.get("opportunity_kind"), "request": lead.get("repeat_request"), "status": lead.get("status")}

    async def page_get_lead_payments(self, args):
        view = payments_view(await self.lead(args["lead_id"]))
        self.known_leads.add(args["lead_id"])
        self.known_payments.add(args["lead_id"])
        return view

    async def page_convert_to_customer(self, args):
        from crm import convert_lead, now_iso, single_payment_summary
        single = args["conversion_type"] == "single_payment"
        if single and not args.get("total_amount"): raise ValueError("Ask for the deal total before converting as a single payment")
        if not single and not args.get("stages"): raise ValueError("Ask for the payment plan stages and amounts before converting")
        body = {"conversion_type": args["conversion_type"]}
        if not single: body["payment_plan"] = {"total_amount": plan_total(args["stages"], args.get("total_amount")), "stages": args["stages"]}
        await convert_lead(self.ws_id, args["lead_id"], self.request, body)
        lead = await self.lead(args["lead_id"])
        if single:
            summary = single_payment_summary(lead, lead.get("receipts") or [], args["total_amount"])
            await self.db.crm_leads.update_one({"_id": lead["_id"], "workspace_id": self.ws_id}, {"$set": {"payment_summary": summary, "updated_at": now_iso()}})
            lead["payment_summary"] = summary
        self.known_payments.add(args["lead_id"])
        return payments_view(lead)

    async def page_set_payment_plan(self, args):
        from crm import update_payment_plan
        self.require(self.known_payments, args["lead_id"], "Read this lead's payments before changing the plan")
        lead = await update_payment_plan(self.ws_id, args["lead_id"], self.request, {"total_amount": plan_total(args["stages"], args.get("total_amount")), "stages": args["stages"]})
        return payments_view({**lead, "_id": lead["id"]})

    async def page_record_payment(self, args):
        from crm import create_receipt
        self.require(self.known_payments, args["lead_id"], "Read this lead's payments and dues before recording a payment")
        lead = await self.lead(args["lead_id"])
        if lead.get("customer_status") != "customer" and lead.get("status") != "won":
            raise ValueError("Convert this lead to a customer before recording payments")
        body = {key: args[key] for key in ("amount", "payment_method", "payment_date", "stage_id", "total_amount", "transaction_id", "description") if args.get(key)}
        if args.get("stage_id"):
            stage = next((s for s in (lead.get("payment_plan") or {}).get("stages", []) if s.get("id") == args["stage_id"]), None)
            if stage: body["payment_stage"] = stage.get("name") or "Payment stage"
        updated = await create_receipt(self.ws_id, args["lead_id"], self.request, body)
        receipt = (updated.get("receipts") or [{}])[-1]
        return {"saved": True, "receipt": receipt_view(receipt),
                "payments": payments_view({**updated, "_id": updated["id"]})}

    async def page_generate_final_invoice(self, args):
        from crm import create_final_invoice
        self.require(self.known_payments, args["lead_id"], "Read this lead's payments before generating the invoice")
        invoice = await create_final_invoice(self.ws_id, args["lead_id"], self.request, {"description": args.get("description", "")})
        return pick(invoice, ("id", "invoice_number", "generated_at", "total_paid", "due_amount"))

    # CRM extras
    async def page_set_lead_labels(self, args):
        from crm import set_lead_labels
        if "tags" not in args and "customer_status" not in args: raise ValueError("Supply tags or customer_status")
        lead = await set_lead_labels(self.ws_id, args["lead_id"], self.request, {key: args[key] for key in ("tags", "customer_status") if key in args})
        return pick(lead, ("id", "tags", "customer_status", "status"))

    async def page_list_offerings(self, args):
        from sales_modules import list_offerings
        result = await list_offerings(self.ws_id, self.request)
        self.known_offerings.update(row["id"] for row in result["items"])
        return {**result, "items": result["items"][:80], "total": len(result["items"])}

    async def page_set_lead_opportunity(self, args):
        from sales_modules import set_opportunity
        self.require(self.known_offerings, args["item_id"], "Read available offerings before attaching one")
        lead = await set_opportunity(self.ws_id, args["lead_id"], self.request, {key: args[key] for key in ("item_id", "module", "quantity", "amount") if key in args})
        return {"id": lead["id"], "opportunity": lead.get("opportunity")}

    async def page_archive_lead(self, args):
        from crm import trash_lead
        lead = await trash_lead(self.ws_id, args["lead_id"], self.request)
        self.known_leads.discard(args["lead_id"])
        return {"id": lead["id"], "archived": True, "restore_until": lead.get("delete_after")}

    async def page_list_archived_leads(self, args):
        import re
        from crm import lead_query
        query = lead_query(self.ws_id, only_trashed=True)
        if args.get("search", "").strip():
            pattern = {"$regex": re.escape(args["search"].strip()), "$options": "i"}
            query = {"$and": [query, {"$or": [{"field_values.full_name": pattern}, {"field_values.phone": pattern}, {"full_name": pattern}, {"phone": pattern}]}]}
        rows = await self.db.crm_leads.find(query, {"field_values": 1, "status": 1, "deleted_at": 1, "delete_after": 1}).sort("deleted_at", -1).limit(20).to_list(20)
        self.known_archived.update(str(row["_id"]) for row in rows)
        return {"items": [{"id": str(row["_id"]), "name": (row.get("field_values") or {}).get("full_name"), "phone": (row.get("field_values") or {}).get("phone"),
                           "status": row.get("status"), "deleted_at": row.get("deleted_at"), "delete_after": row.get("delete_after")} for row in rows]}

    async def page_restore_lead(self, args):
        from crm import restore_lead
        self.require(self.known_archived, args["archived_lead_id"], "Find this lead in trash before restoring it")
        lead = await restore_lead(self.ws_id, args["archived_lead_id"], self.request)
        self.known_leads.add(lead["id"])
        return {"id": lead["id"], "restored": True, "status": lead.get("status")}

    # Products and services
    async def page_list_products(self, args):
        from catalog import list_items
        result = await list_items(self.ws_id, self.request, search=args.get("search", ""), kind=args.get("kind", ""), status=args.get("status", ""))
        self.known_items.update(row["id"] for row in result["items"])
        keys = ("id", "name", "kind", "price", "stock_quantity", "status", "sku", "description")
        return {"items": [pick(row, keys) for row in result["items"][:100]], "total": len(result["items"]), "currency": result.get("currency")}

    async def page_create_product(self, args):
        from catalog import create_item
        item = await create_item(self.ws_id, self.request, dict(args))
        self.known_items.add(item["id"])
        return pick(item, ("id", "name", "kind", "price", "stock_quantity", "status"))

    async def page_update_product(self, args):
        from catalog import update_item
        self.require(self.known_items, args["item_id"], "List products before changing one")
        item = await update_item(self.ws_id, args["item_id"], self.request, {key: value for key, value in args.items() if key != "item_id"})
        return pick(item, ("id", "name", "kind", "price", "stock_quantity", "status"))

    # Properties
    async def page_create_property(self, args):
        from properties import create_property
        body = {**args, "container_kind": "land" if args["category"] == "land" else "individual"}
        row = await create_property(self.ws_id, self.request, body)
        self.known_properties.add(row["id"])
        return pick(row, ("id", "name", "category", "subtype", "location", "price", "status"))

    async def page_update_property(self, args):
        from properties import update_property
        self.require(self.known_properties, args["property_id"], "List properties before changing one")
        row = await update_property(self.ws_id, args["property_id"], self.request, {key: value for key, value in args.items() if key != "property_id"})
        return pick(row, ("id", "name", "category", "subtype", "location", "price", "status"))

    async def page_list_property_units(self, args):
        from properties import list_property_units
        self.require(self.known_properties, args["property_id"], "List properties before reading units")
        result = await list_property_units(self.ws_id, args["property_id"], self.request, tower=args.get("tower", ""), bhk=args.get("bhk", ""),
                                           status=args.get("status", ""), offset=args.get("offset", 0), limit=50)
        self.known_units.update(f"{args['property_id']}:{row['id']}" for row in result["items"])
        keys = ("id", "tower", "unit_number", "bhk", "status", "listing_type", "asking_price_minor", "updated_at")
        return {**result, "items": [pick(row, keys) for row in result["items"]], "price_unit": "asking_price_minor is in minor currency units (paise/cents)"}

    async def page_update_property_unit(self, args):
        from properties import update_property_unit
        self.require(self.known_units, f"{args['property_id']}:{args['unit_id']}", "List this project's units before changing one")
        body = {key: args[key] for key in ("asking_price", "listing_type", "status") if key in args}
        if not body: raise ValueError("Supply a price, listing type or status")
        row = await update_property_unit(self.ws_id, args["property_id"], args["unit_id"], self.request, body)
        return pick(row, ("id", "tower", "unit_number", "status", "listing_type", "asking_price_minor"))

    # Tasks
    async def task(self, task_id):
        self.require(self.known_tasks, task_id, "List tasks before acting on one")
        row = await self.db.tasks.find_one({"_id": ObjectId(task_id), "workspace_id": self.ws_id})
        if not row: raise ValueError("Task not found in this workspace")
        return row

    async def page_complete_sales_task(self, args):
        from sales_leadership import Outcome, complete
        row = await self.task(args["task_id"])
        if row.get("source") != "sales_manager": raise ValueError("Only sales-manager tasks take an outcome; use the task's own page action")
        await complete(self.ws_id, args["task_id"], self.request, Outcome(outcome=args["outcome"]))
        return {"id": args["task_id"], "status": "done", "outcome": args["outcome"]}

    async def page_run_task(self, args):
        from server import run_task
        row = await self.task(args["task_id"])
        if row.get("status") not in {"pending", "failed"}: raise ValueError(f"Task is {row.get('status')}; only pending or failed tasks can run")
        result = await run_task(args["task_id"], self.request)
        return pick(result, ("id", "title", "status", "output_summary", "output_ref", "deliverable_type"))

    async def page_approve_task(self, args):
        from server import approve_task
        row = await self.task(args["task_id"])
        if row.get("status") != "awaiting_approval": raise ValueError("Only tasks awaiting approval can be approved")
        result = await approve_task(args["task_id"], self.request)
        return pick(result, ("id", "title", "status", "output_ref"))

    # Brain and sales strategy
    async def page_update_business_profile(self, args):
        if not args.get("business_profile") and not args.get("goals_constraints"): raise ValueError("Supply business_profile or goals_constraints facts")
        ws = await self.fresh_workspace()
        brain = dict(ws.get("brain") or {})
        for section in ("business_profile", "goals_constraints"):
            if args.get(section): brain[section] = {**(brain.get(section) or {}), **args[section]}
        await self.db.workspaces.update_one({"_id": ws["_id"]}, {"$set": {"brain": brain}})
        self.workspace["brain"] = brain
        return {"saved": True, "business_profile": brain.get("business_profile", {}), "goals_constraints": brain.get("goals_constraints", {})}

    async def page_update_sales_profile(self, args):
        from sales_leadership import SalesProfile, save_profile
        ws = await self.fresh_workspace()
        current = ws.get("sales_profile") or {}
        if not current and not {"organisation", "offerings", "ideal_customer", "team_capacity", "monthly_revenue_target", "business_stage"} <= set(args):
            raise ValueError("Sales setup is not complete yet; ask for organisation, offerings, ideal customer, team capacity, monthly revenue target and business stage")
        profile = await save_profile(self.ws_id, self.request, SalesProfile(**{**current, **args}))
        self.workspace["sales_profile"] = profile
        return {"saved": True, "sales_profile": profile}

    async def page_generate_sales_strategy(self, args):
        from sales_leadership import generate_strategy
        result = await generate_strategy(self.ws_id, self.request)
        return result if isinstance(result, dict) else {"strategy": result}

    async def page_run_sales_review(self, args):
        from sales_leadership import review
        report = await review(self.ws_id, self.request)
        keys = ("total_leads", "active_opportunities", "overdue_tasks", "stale_leads", "stage_counts", "questions")
        return {"completed": True, **{key: report.get(key) for key in keys}, "priorities": (report.get("priorities") or [])[:10]}

    # Sales team
    async def page_add_sales_person(self, args):
        from sales_team import add_person
        person = await add_person(self.ws_id, self.request, dict(args))
        self.known_people.add(person["id"])
        return pick(person, ("id", "name", "role", "phone", "email", "active"))

    async def page_set_sales_person_active(self, args):
        from sales_team import update_person
        self.require(self.known_people | self.known_inactive_people, args["sales_agent_id"], "Read the sales team (include_inactive to reactivate) before changing a salesperson")
        await update_person(self.ws_id, args["sales_agent_id"], self.request, {"active": args["active"]})
        return {"id": args["sales_agent_id"], "active": args["active"]}

    # Qualification
    async def page_get_qualification_setup(self, args):
        from qualification_api import profiles
        result = await profiles(self.ws_id, self.request)
        self.known_profiles.update(row["id"] for row in result["profiles"])
        keys = ("id", "product_name", "campaign_id", "voice_provider", "target_customer", "desired_next_action")
        return {"profiles": [pick(row, keys) for row in result["profiles"]], "default_profile_id": result.get("default_profile_id"),
                "default_voice_provider": result.get("default_voice_provider"), "calling_settings": result.get("calling_settings")}

    async def page_update_calling_settings(self, args):
        from qualification_api import CallingSettings, profiles, update_calling_settings
        current = (await profiles(self.ws_id, self.request)).get("calling_settings") or {}
        window = dict(current.get("calling_window") or {"start": "09:30", "end": "19:00"})
        if args.get("window_start"): window["start"] = args["window_start"]
        if args.get("window_end"): window["end"] = args["window_end"]
        merged = {"call_mode": args.get("call_mode") or current.get("call_mode") or "automatic",
                  "initial_delay_seconds": args.get("initial_delay_seconds", current.get("initial_delay_seconds", 300)),
                  "timezone": args.get("timezone") or current.get("timezone") or "Asia/Kolkata", "calling_window": window}
        result = await update_calling_settings(self.ws_id, self.request, CallingSettings(**merged))
        return {key: (result or {}).get(key) for key in ("call_mode", "initial_delay_seconds", "timezone", "calling_window")}

    async def page_set_default_qualification_profile(self, args):
        from qualification_api import set_default
        self.require(self.known_profiles, args["profile_id"], "Read qualification setup before choosing a profile")
        return await set_default(self.ws_id, args["profile_id"], self.request)

    async def page_assign_qualification_profile(self, args):
        from qualification_api import Assignment, assign_profile
        if args["profile_id"]: self.require(self.known_profiles, args["profile_id"], "Read qualification setup before choosing a profile")
        return await assign_profile(self.ws_id, args["lead_id"], self.request, Assignment(profile_id=args["profile_id"]))

    # Landing page forms and workflows
    def form_view(self, form):
        self.known_forms.add(form["id"])
        return {**pick(form, ("id", "name", "status", "form_key", "allowed_origins", "stats", "created_at")),
                "default_country": ((form.get("fields") or {}).get("phone") or {}).get("default_country")}

    async def page_list_lead_forms(self, args):
        from lead_forms import list_forms
        return {"items": [self.form_view(form) for form in (await list_forms(self.ws_id, self.request))["items"]]}

    async def page_create_lead_form(self, args):
        from lead_forms import create_form
        return self.form_view(await create_form(self.ws_id, self.request, dict(args)))

    async def page_update_lead_form(self, args):
        from lead_forms import update_form
        self.require(self.known_forms, args["form_id"], "List forms before changing one")
        body = {key: args[key] for key in ("name", "status") if key in args}
        if not body: raise ValueError("Supply a new name or status")
        return self.form_view(await update_form(self.ws_id, args["form_id"], self.request, body))

    async def page_list_form_submissions(self, args):
        from lead_forms import submissions
        self.require(self.known_forms, args["form_id"], "List forms before reading submissions")
        rows = (await submissions(self.ws_id, args["form_id"], self.request))["items"]
        keys = ("id", "status", "lead_id", "duplicate", "created_at", "outcome", "error", "page_url", "utm_source", "utm_campaign")
        return {"items": [pick(row, keys) for row in rows], "total": len(rows)}

    async def page_list_workflows(self, args):
        from workflows import list_workflows
        return {"items": [pick(row, ("id", "kind", "status", "published_at", "sheet_connection_id")) for row in await list_workflows(self.ws_id, self.request)]}

    # Blogs
    async def page_list_blogs(self, args):
        query = {"workspace_id": self.ws_id, **({"status": args["status"]} if args.get("status") else {})}
        rows = await self.db.blogs.find(query, {"title": 1, "slug": 1, "status": 1, "excerpt": 1, "published_at": 1, "created_at": 1}).sort("created_at", -1).limit(50).to_list(50)
        self.known_blogs.update(str(row["_id"]) for row in rows)
        return {"items": [{**pick(row, ("title", "slug", "status", "excerpt", "published_at", "created_at")), "id": str(row["_id"])} for row in rows],
                "total": await self.db.blogs.count_documents(query)}

    async def page_generate_blog_draft(self, args):
        from server import generate_blog
        blog = await generate_blog(self.ws_id, self.request, {"topic": args["topic"], "objective": args.get("objective", "")})
        self.known_blogs.add(blog["id"])
        return pick(blog, ("id", "title", "slug", "status", "excerpt"))

    async def page_set_blog_status(self, args):
        from server import publish_blog
        self.require(self.known_blogs, args["blog_id"], "List blogs before publishing or unpublishing one")
        blog = await publish_blog(args["blog_id"], self.request, {"status": args["status"]})
        return pick(blog, ("id", "title", "slug", "status", "published_at"))

    # Workspace settings
    async def page_get_workspace_settings(self, args):
        from crm import ensure_crm_settings, effective_organization
        from workspace_modules import workspace_currency, workspace_modules
        ws = await self.fresh_workspace()
        settings = await ensure_crm_settings(self.db, self.ws_id)
        org = effective_organization(settings, ws) or {}
        return {"name": ws.get("name"), "website_url": ws.get("website_url"), "currency": workspace_currency(ws), "modules": workspace_modules(ws),
                "stages": [pick(s, ("key", "label")) for s in settings.get("states", [])], "tag_library": settings.get("tag_library", []),
                "organization": pick(org, ("name", "email", "phone", "address", "tax_id", "receipt_prefix", "invoice_prefix")),
                "brain_status": ws.get("brain_status"), "sales_setup_complete": bool(ws.get("sales_profile"))}

    async def page_save_crm_tags(self, args):
        from crm import save_tag_library
        return await save_tag_library(self.ws_id, self.request, {"names": args["names"], "color": args.get("color", "blue")})

    async def page_list_notifications(self, args):
        rows = await self.db.notifications.find({"workspace_id": self.ws_id}).sort("created_at", -1).limit(20).to_list(20)
        return {"items": [pick(row, ("kind", "title", "body", "read", "created_at")) for row in rows]}
