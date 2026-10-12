"""AI Manager control of workspace pages beyond leads: payments, customers, catalog, brain, tasks."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from fastapi import HTTPException
from jsonschema import Draft202012Validator

import manager_agent as agent
from manager_page_tools import PAGE_TOOLS
from manager_tools import REGISTRY, TOOLS, ManagerTools

WS = ObjectId()


def test_every_page_tool_has_a_handler_page_and_valid_schema():
    assert len({tool["name"] for tool in TOOLS}) == len(TOOLS)
    for tool in PAGE_TOOLS:
        assert hasattr(ManagerTools, "page_" + tool["name"]), tool["name"]
        Draft202012Validator.check_schema(tool["schema"]["function"]["parameters"])
        assert tool["section"] and tool["label"]
    for name in ("record_payment", "convert_to_customer", "list_customers", "create_product", "update_business_profile", "run_task"):
        assert name in REGISTRY


def test_result_links_open_the_page_that_changed():
    lead = str(ObjectId())
    assert agent.result_link(WS, "record_payment", {"lead_id": lead}, {}) == f"/app/w/{WS}/crm?lead={lead}"
    assert agent.result_link(WS, "list_customers", {}, {}) == f"/app/w/{WS}/customers"
    assert agent.result_link(WS, "create_product", {}, {"id": "x"}) == f"/app/w/{WS}/products-services"
    assert agent.result_link(WS, "generate_blog_draft", {}, {"id": "b1"}) == f"/app/w/{WS}/blogs/b1"
    assert agent.result_link(WS, "create_repeat_opportunity", {}, {"id": lead}) == f"/app/w/{WS}/crm?lead={lead}"
    assert agent.result_link(WS, "archive_lead", {"lead_id": lead}, {}) == f"/app/w/{WS}/crm"
    assert agent.result_link(WS, "get_product_help", {}, {}) == ""


def unit_tools(monkeypatch, db=None):
    import auth
    monkeypatch.setattr(auth, "get_current_user_and_workspace", AsyncMock(return_value=({}, {"_id": WS})))
    db = db or SimpleNamespace()
    return ManagerTools(db, {"_id": WS}, SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db))))


@pytest.mark.parametrize("name,args,message", [
    ("record_payment", {"amount": "100"}, "payments"),
    ("set_payment_plan", {"stages": [{"name": "Booking", "amount": "10"}]}, "payments"),
    ("generate_final_invoice", {}, "payments"),
])
def test_money_writes_require_reading_payments_first(monkeypatch, name, args, message):
    tools = unit_tools(monkeypatch)
    lead = str(ObjectId())
    tools.lead = AsyncMock(return_value={"_id": ObjectId(lead), "status": "won", "customer_status": "customer"})
    tools.known_leads.add(lead)
    with pytest.raises(ValueError, match=message):
        asyncio.run(tools.execute(name, {"lead_id": lead, **args}))


def test_invented_money_formats_are_rejected_by_schema(monkeypatch):
    from jsonschema import ValidationError
    tools = unit_tools(monkeypatch)
    with pytest.raises(ValidationError):
        asyncio.run(tools.execute("record_payment", {"lead_id": str(ObjectId()), "amount": "₹1,000"}))


@pytest.mark.parametrize("name,args", [
    ("update_product", {"item_id": str(ObjectId()), "price": "10"}),
    ("update_property", {"property_id": str(ObjectId()), "price": "10"}),
    ("complete_sales_task", {"task_id": str(ObjectId()), "outcome": "Customer agreed"}),
    ("approve_task", {"task_id": str(ObjectId())}),
    ("set_blog_status", {"blog_id": str(ObjectId()), "status": "published"}),
    ("update_lead_form", {"form_id": str(ObjectId()), "status": "paused"}),
    ("restore_lead", {"archived_lead_id": str(ObjectId())}),
    ("create_repeat_opportunity", {"customer_id": str(ObjectId()), "request": "AMC renewal"}),
    ("set_default_qualification_profile", {"profile_id": str(ObjectId())}),
    ("set_sales_person_active", {"sales_agent_id": str(ObjectId()), "active": False}),
])
def test_page_writes_refuse_unread_records(monkeypatch, name, args):
    tools = unit_tools(monkeypatch)
    with pytest.raises(ValueError, match="before|Read|List|Find"):
        asyncio.run(tools.execute(name, args))


def test_sales_profile_update_asks_for_missing_setup_instead_of_inventing(monkeypatch):
    db = SimpleNamespace(workspaces=SimpleNamespace(find_one=AsyncMock(return_value={"_id": WS})))
    tools = unit_tools(monkeypatch, db)
    with pytest.raises(ValueError, match="ask for organisation"):
        asyncio.run(tools.execute("update_sales_profile", {"monthly_revenue_target": 500000}))


def test_pydantic_validation_errors_become_readable_tool_errors(monkeypatch):
    db = SimpleNamespace(workspaces=SimpleNamespace(find_one=AsyncMock(return_value={"_id": WS, "sales_profile": {
        "organisation": "Studio", "offerings": "Design", "ideal_customer": "Founders", "team_capacity": "2",
        "monthly_revenue_target": 1000, "business_stage": "existing"}})))
    tools = unit_tools(monkeypatch, db)
    import sales_leadership
    monkeypatch.setattr(sales_leadership, "get_current_user_and_workspace", AsyncMock(return_value=({}, {"_id": WS})), raising=False)
    with pytest.raises(ValueError, match="Invalid"):
        asyncio.run(tools.execute("update_sales_profile", {"offerings": "Design", "stale_days": 7, "organisation": ""}))


# ---------------------------------------------------------------- real handlers on an isolated database
def real_tools(monkeypatch, db, workspace):
    import auth
    monkeypatch.setattr(auth, "get_current_user_and_workspace", AsyncMock(return_value=({"_id": ObjectId()}, workspace)))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)), headers={})
    return ManagerTools(db, workspace, request)


async def seed_lead(db, ws_id, name="Asha"):
    from crm import build_manual_lead, ensure_crm_settings
    lead = build_manual_lead(ws_id, {"field_values": {"phone": "+919876543210", "full_name": name}, "trigger_ai_call": False}, await ensure_crm_settings(db, ws_id))
    await db.crm_leads.insert_one(lead)
    return str(lead["_id"])


def test_chat_converts_customer_records_receipts_and_generates_invoice(monkeypatch):
    from tests.test_qualification_integration import isolated
    async def scenario(db):
        workspace = {"_id": ObjectId(), "name": "Studio", "currency": "INR"}
        await db.workspaces.insert_one(workspace)
        ws_id = str(workspace["_id"])
        lead = await seed_lead(db, ws_id)
        tools = real_tools(monkeypatch, db, workspace)
        await tools.execute("get_lead", {"lead_id": lead})
        with pytest.raises(ValueError, match="deal total"):
            await tools.execute("convert_to_customer", {"lead_id": lead, "conversion_type": "single_payment"})
        converted = await tools.execute("convert_to_customer", {"lead_id": lead, "conversion_type": "single_payment", "total_amount": "1000"})
        assert converted["customer_status"] == "customer" and converted["summary"]["due_amount"] == "1000"
        paid = await tools.execute("record_payment", {"lead_id": lead, "amount": "400", "payment_method": "UPI", "payment_date": "2026-10-12"})
        assert paid["receipt"]["receipt_number"] and paid["receipt"]["amount"] == "400"
        assert paid["payments"]["summary"]["due_amount"] == "600"
        with pytest.raises(HTTPException, match="exceed"):
            await tools.execute("record_payment", {"lead_id": lead, "amount": "700"})
        with pytest.raises(HTTPException, match="due amount"):
            await tools.execute("generate_final_invoice", {"lead_id": lead})
        await tools.execute("record_payment", {"lead_id": lead, "amount": "600", "payment_method": "Cash"})
        invoice = await tools.execute("generate_final_invoice", {"lead_id": lead})
        assert invoice["invoice_number"] and invoice["total_paid"] == "1000"
        customers = await tools.execute("list_customers", {})
        assert customers["total"] == 1 and customers["items"][0]["ltv"] == "1000"
        detail = await tools.execute("get_customer", {"customer_id": lead})
        assert detail["lifecycle"] == "customer"
        repeat = await tools.execute("create_repeat_opportunity", {"customer_id": lead, "request": "Annual maintenance", "kind": "repeat_purchase"})
        assert repeat["kind"] == "repeat_purchase" and repeat["id"] != lead
        stored = await db.crm_leads.find_one({"_id": ObjectId(lead)})
        assert len(stored["receipts"]) == 2 and stored["final_invoice"]
    asyncio.run(isolated(scenario))


def test_chat_payment_plan_enforces_stage_order(monkeypatch):
    from tests.test_qualification_integration import isolated
    async def scenario(db):
        workspace = {"_id": ObjectId(), "name": "Builders"}
        await db.workspaces.insert_one(workspace)
        lead = await seed_lead(db, str(workspace["_id"]), "Vikram")
        tools = real_tools(monkeypatch, db, workspace)
        await tools.execute("get_lead", {"lead_id": lead})
        plan = await tools.execute("convert_to_customer", {"lead_id": lead, "conversion_type": "payment_plan", "total_amount": "300",
            "stages": [{"name": "Booking", "amount": "100"}, {"name": "Handover", "amount": "200"}]})
        booking, handover = plan["payment_plan"]["stages"]
        with pytest.raises(HTTPException, match="previous payment stage"):
            await tools.execute("record_payment", {"lead_id": lead, "amount": "200", "stage_id": handover["id"]})
        paid = await tools.execute("record_payment", {"lead_id": lead, "amount": "100", "stage_id": booking["id"]})
        assert paid["receipt"]["payment_stage"] == "Booking"
        assert paid["payments"]["payment_plan"]["stages"][0]["status"] == "paid"
        # Each stage reports its own remaining amount, not the running plan balance.
        handover_view = paid["payments"]["payment_plan"]["stages"][1]
        assert handover_view["remaining_for_stage"] == "200" and handover_view["plan_balance_after_stage"] == "200"
        assert paid["receipt"]["balance_due_after_payment"] == "200"
        # Editing the plan keeps the paid stage by id.
        updated = await tools.execute("set_payment_plan", {"lead_id": lead, "stages": [
            {"id": booking["id"], "name": "Booking", "amount": "100"}, {"name": "Handover", "amount": "250"}]})
        assert updated["payment_plan"]["stages"][0]["status"] == "paid"
    asyncio.run(isolated(scenario))


def test_chat_controls_products_brain_tags_and_archive(monkeypatch):
    from tests.test_qualification_integration import isolated
    async def scenario(db):
        workspace = {"_id": ObjectId(), "name": "Agency", "modules": {"agency": True, "real_estate": False},
                     "brain": {"business_profile": {"company_name": "Agency", "industry": "Design"}, "brand_identity": {"tone": "warm"}}}
        await db.workspaces.insert_one(workspace)
        ws_id = str(workspace["_id"])
        tools = real_tools(monkeypatch, db, workspace)
        item = await tools.execute("create_product", {"name": "Logo design", "kind": "service", "price": "15000"})
        assert item["status"] == "active"
        fresh = real_tools(monkeypatch, db, workspace)
        with pytest.raises(ValueError, match="List products"):
            await fresh.execute("update_product", {"item_id": item["id"], "status": "inactive"})
        await fresh.execute("list_products", {"kind": "service"})
        assert (await fresh.execute("update_product", {"item_id": item["id"], "price": "18000"}))["price"] == "18000.00"
        await tools.execute("update_business_profile", {"business_profile": {"pricing_summary": "From 15k"}, "goals_constraints": {"priorities": ["Retainers"]}})
        brain = (await db.workspaces.find_one({"_id": workspace["_id"]}))["brain"]
        assert brain["business_profile"] == {"company_name": "Agency", "industry": "Design", "pricing_summary": "From 15k"}
        assert brain["brand_identity"] == {"tone": "warm"} and brain["goals_constraints"]["priorities"] == ["Retainers"]
        lead = await seed_lead(db, ws_id, "Meera")
        await tools.execute("get_lead", {"lead_id": lead})
        labels = await tools.execute("set_lead_labels", {"lead_id": lead, "tags": ["VIP", "Referral"]})
        assert labels["tags"] == ["VIP", "Referral"]
        offerings = await tools.execute("list_offerings", {})
        assert offerings["items"][0]["id"] == item["id"]
        attached = await tools.execute("set_lead_opportunity", {"lead_id": lead, "item_id": item["id"], "module": "agency"})
        assert attached["opportunity"]["name"] == "Logo design"
        await tools.execute("archive_lead", {"lead_id": lead})
        trashed = await tools.execute("list_archived_leads", {"search": "Meera"})
        assert [row["id"] for row in trashed["items"]] == [lead]
        assert (await tools.execute("restore_lead", {"archived_lead_id": lead}))["restored"] is True
        settings = await tools.execute("get_workspace_settings", {})
        assert settings["modules"]["agency"] is True and settings["stages"]
    asyncio.run(isolated(scenario))


def test_chat_records_sales_task_outcome_only_after_listing(monkeypatch):
    from tests.test_qualification_integration import isolated
    async def scenario(db):
        workspace = {"_id": ObjectId(), "name": "Studio"}
        await db.workspaces.insert_one(workspace)
        ws_id = str(workspace["_id"])
        task = ObjectId()
        await db.tasks.insert_one({"_id": task, "workspace_id": ws_id, "title": "Call back Asha", "source": "sales_manager", "status": "pending"})
        tools = real_tools(monkeypatch, db, workspace)
        import sales_leadership
        monkeypatch.setattr(sales_leadership, "get_current_user_and_workspace", AsyncMock(return_value=({}, workspace)))
        with pytest.raises(ValueError, match="List tasks"):
            await tools.execute("complete_sales_task", {"task_id": str(task), "outcome": "Booked a site visit"})
        listed = await tools.execute("list_tasks", {"status": "pending"})
        assert listed["items"][0]["source"] == "sales_manager"
        await tools.execute("complete_sales_task", {"task_id": str(task), "outcome": "Booked a site visit"})
        assert (await db.tasks.find_one({"_id": task}))["outcome"] == "Booked a site visit"
    asyncio.run(isolated(scenario))


def test_records_read_earlier_in_the_conversation_stay_known_for_later_turns(monkeypatch):
    first = unit_tools(monkeypatch)
    lead, item = str(ObjectId()), str(ObjectId())
    first.known_leads.add(lead); first.known_payments.add(lead); first.known_items.add(item)
    saved = first.remembered()
    later = unit_tools(monkeypatch)
    later.remember(saved)
    assert lead in later.known_leads and lead in later.known_payments and item in later.known_items
    later.remember(None)  # A new conversation has nothing remembered.
    assert ManagerTools(SimpleNamespace(), {"_id": WS}, object()).remembered()["known_leads"] == []


def test_search_rejects_relationship_labels_as_pipeline_stages(monkeypatch):
    import crm
    monkeypatch.setattr(crm, "ensure_crm_settings", AsyncMock(return_value={"fields": crm.DEFAULT_FIELDS, "states": crm.DEFAULT_STATES}))
    tools = unit_tools(monkeypatch)
    with pytest.raises(ValueError, match="not a pipeline stage"):
        asyncio.run(tools.execute("search_leads", {"search": "Rahul", "status": "lead"}))


def test_plan_total_defaults_to_stage_sum_and_rejects_stages_above_total():
    from manager_page_tools import plan_total
    stages = [{"name": "Booking", "amount": "100000"}, {"name": "Possession", "amount": "800000"}]
    assert plan_total(stages, None) == "900000"
    assert plan_total(stages, "1000000") == "1000000"  # The rest is scheduled automatically later.
    with pytest.raises(ValueError, match="more than the total"):
        plan_total(stages, "500000")


def test_null_optional_arguments_from_models_are_ignored(monkeypatch):
    import crm
    monkeypatch.setattr(crm, "ensure_crm_settings", AsyncMock(return_value={"fields": crm.DEFAULT_FIELDS, "states": crm.DEFAULT_STATES}))
    monkeypatch.setattr(crm, "paginated_leads", AsyncMock(return_value={"items": [], "total": 0}))
    tools = unit_tools(monkeypatch)
    asyncio.run(tools.execute("search_leads", {"search": "Priya", "status": None, "page": None}))
    assert crm.paginated_leads.call_args.kwargs["status"] is None and crm.paginated_leads.call_args.kwargs["page"] == 1


def test_payment_plan_without_total_still_reports_real_dues(monkeypatch):
    from tests.test_qualification_integration import isolated
    async def scenario(db):
        workspace = {"_id": ObjectId(), "name": "Builders"}
        await db.workspaces.insert_one(workspace)
        lead = await seed_lead(db, str(workspace["_id"]), "Priya")
        tools = real_tools(monkeypatch, db, workspace)
        await tools.execute("get_lead", {"lead_id": lead})
        plan = await tools.execute("convert_to_customer", {"lead_id": lead, "conversion_type": "payment_plan",
            "stages": [{"name": "Booking", "amount": "100000"}, {"name": "Possession", "amount": "800000"}]})
        paid = await tools.execute("record_payment", {"lead_id": lead, "amount": "100000", "stage_id": plan["payment_plan"]["stages"][0]["id"]})
        assert paid["payments"]["payment_plan"]["due_amount"] == "800000"
        assert (await tools.execute("get_customer", {"customer_id": lead}))["outstanding"] == "800000"
    asyncio.run(isolated(scenario))
