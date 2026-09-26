import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx
from bson import ObjectId
from fastapi import HTTPException

import google_sheets as sheets
import llm_service
from crm import default_field_values, ensure_crm_settings, update_lead, convert_lead, normalize_field, validate_field_values
from meta_fields import META_FIELDS, map_sheet_row, pending_sheet_sync
from migrate_meta_sheets import migrate
from models import CRMLead
from tests.test_qualification_integration import isolated


def test_all_meta_and_custom_fields_map_without_id_precision_loss():
    raw = {"id": "9876543210987654321", "created_time": "2026-09-21T10:00:00Z",
           "campaign_id": "111", "campaign_name": "Test Campaign", "adset_id": "222",
           "adset_name": "Test Ad Set", "ad_id": "333", "ad_name": "Test Ad",
           "form_id": "444", "form_name": "Test Form", "is_organic": "false", "platform": "fb",
           "budget": "90000", "phone": "123", "name": "Rahul", "email": "r@example.test"}
    mapping = {key: header for key, (header, _) in META_FIELDS.items()}
    mapping.update(budget="budget", phone="phone", full_name="name", email="email")
    values, meta = map_sheet_row([h.upper() for h in raw], list(raw.values()), mapping, ["budget", "phone", "full_name", "email"])
    assert values == {"budget": "90000", "phone": "123", "full_name": "Rahul", "email": "r@example.test"}
    for key, (header, _) in META_FIELDS.items():
        assert meta[key] == (False if key == "meta_is_organic" else raw[header])
    assert CRMLead(workspace_id="ws", sheet_row_key="old").meta_lead_id is None
    for key in META_FIELDS:
        with pytest.raises(HTTPException):
            normalize_field({"key": key})


def test_headers_and_ranges():
    assert sheets.column_letter(26) == "AA"
    assert "%27Sales%20O%27%27Brien%27%21AA2" in sheets.values_url("file", "Sales O'Brien", "AA2")
    with pytest.raises(ValueError):
        map_sheet_row(["id", "ID"], ["1", "2"], {"meta_lead_id": "id"}, [])


def test_meta_phone_prefix_is_removed_from_mapped_lead():
    values, _ = map_sheet_row(["Phone", "Name"], ["p:+919322272573", "Akesh"],
                              {"phone": "Phone", "full_name": "Name"}, ["phone", "full_name"])
    assert values == {"phone": "+919322272573", "full_name": "Akesh"}


def test_manual_lead_phone_prefix_is_removed_before_saving():
    settings = {"fields": [{"key": "phone", "label": "Phone", "required": True, "active": True}]}
    assert validate_field_values({"phone": "p:+919322272573"}, settings) == {"phone": "+919322272573"}


def test_existing_prefixed_phone_is_clean_in_crm_response():
    settings = {"fields": [{"key": "phone", "active": True}]}
    assert default_field_values({"field_values": {"phone": "p:+919322272573"}}, settings) == {
        "phone": "+919322272573"}


def test_reimport_repairs_prefixed_phone_on_existing_lead():
    async def run(db):
        ws = str(ObjectId())
        conn = {"spreadsheet_id": "file", "sheet_name": "Leads",
                "column_map": {"meta_lead_id": "ID", "phone": "Phone"}}
        headers = ["ID", "Phone"]
        lead_id, created = await sheets.import_sheet_row(
            db, ws, conn, headers, ["lead-1", "p:+919322272573"], 2, {"phone"})
        assert created
        await db.crm_leads.update_one({"_id": ObjectId(lead_id)}, {"$set": {
            "phone": "p:+919322272573", "field_values.phone": "p:+919322272573"}})
        _, created = await sheets.import_sheet_row(
            db, ws, conn, headers, ["lead-1", "p:+919322272573"], 2, {"phone"})
        assert not created
        lead = await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
        assert lead["phone"] == "+919322272573"
        assert lead["field_values"]["phone"] == "+919322272573"

    asyncio.run(isolated(run))


def test_google_transport_refresh_and_raw_status_write(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        if request.headers["authorization"] == "Bearer expired":
            return httpx.Response(401)
        return httpx.Response(200, json={"updatedCells": 1})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(sheets.httpx, "AsyncClient", lambda **kwargs: client)
    refresh = AsyncMock(return_value="refreshed")
    monkeypatch.setattr(sheets, "refresh_access_token", refresh)
    async def run():
        conn = {"spreadsheet_id": "file", "sheet_name": "O'Brien Leads", "tokens": {"access_token": "expired"}}
        await sheets.sheet_request(object(), conn, "PUT", "AA3", params={"valueInputOption": "RAW"}, json={"values": [["Converted"]]})
    asyncio.run(run())
    assert len(requests) == 2
    assert requests[-1].url.params["valueInputOption"] == "RAW"
    assert requests[-1].method == "PUT"
    assert requests[-1].content == b'{"values":[["Converted"]]}'
    refresh.assert_awaited_once()


def test_google_tab_read_retries_timeout(monkeypatch):
    attempts = []

    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def get(self, url, headers):
            attempts.append((url, headers))
            if len(attempts) == 1:
                raise httpx.ReadTimeout("slow")
            return httpx.Response(200, json={"sheets": []})

    monkeypatch.setattr(sheets.httpx, "AsyncClient", lambda **kwargs: Client())
    monkeypatch.setattr(sheets.asyncio, "sleep", AsyncMock())
    response = asyncio.run(sheets.google_get_with_retry("https://sheets.googleapis.test/file", "token"))
    assert response.status_code == 200
    assert len(attempts) == 2
    sheets.asyncio.sleep.assert_awaited_once()


def test_google_tab_read_timeout_has_safe_actionable_error(monkeypatch):
    async def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("provider details")
    monkeypatch.setattr(sheets, "google_get_with_retry", timeout)

    class Connections:
        async def find_one(self, query):
            return {"tokens": {"access_token": "token"}}

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=SimpleNamespace(google_sheet_connections=Connections()))))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(sheets.list_spreadsheet_tabs("ws", "sheet", request))
    assert caught.value.status_code == 504
    assert caught.value.detail == "Google took too long to return the Sheet tabs. Retry loading tabs."
    assert "provider" not in caught.value.detail


def test_drive_watch_registration_uses_authenticated_https_webhook(monkeypatch):
    captured = []

    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def post(self, url, **kwargs):
            captured.append((url, kwargs))
            return httpx.Response(200, json={
                "resourceId": "drive-resource",
                "expiration": str(kwargs["json"]["expiration"]),
            })

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://crm.example")
    monkeypatch.setattr(sheets.httpx, "AsyncClient", lambda **kwargs: Client())

    async def run(db):
        conn = {"workspace_id": "ws", "spreadsheet_id": "sheet/file", "tokens": {"access_token": "oauth"}}
        inserted = await db.google_sheet_connections.insert_one(conn)
        conn = await db.google_sheet_connections.find_one({"_id": inserted.inserted_id})
        result = await sheets.ensure_drive_watch(db, conn)
        assert result["drive_watch_status"] == "active"
        stored = await db.google_sheet_connections.find_one({"_id": inserted.inserted_id})
        assert stored["drive_watch_resource_id"] == "drive-resource"
        assert stored["drive_watch_token"]

    asyncio.run(isolated(run))
    url, request = captured[0]
    assert url.endswith("/files/sheet%2Ffile/watch")
    assert request["headers"] == {"Authorization": "Bearer oauth"}
    assert request["json"]["address"] == "https://crm.example/api/google/webhooks/drive"
    assert request["json"]["type"] == "web_hook"


def test_drive_webhook_rejects_bad_token_and_imports_for_active_workflow(monkeypatch):
    imported = AsyncMock(return_value={"created": 1, "reviewed": 1, "cursor": 2})
    monkeypatch.setattr(sheets, "drain_sheet_connection", imported)

    async def run(db):
        ws = "workspace"
        conn = {
            "workspace_id": ws,
            "drive_watch_channel_id": "channel",
            "drive_watch_resource_id": "resource",
            "drive_watch_token": "proof",
        }
        inserted = await db.google_sheet_connections.insert_one(conn)
        conn["_id"] = inserted.inserted_id
        await db.workflows.insert_one({"workspace_id": ws, "kind": "ads_to_crm", "status": "published"})

        def request(token):
            return SimpleNamespace(
                headers={
                    "x-goog-channel-id": "channel",
                    "x-goog-channel-token": token,
                    "x-goog-resource-id": "resource",
                    "x-goog-resource-state": "update",
                },
                app=SimpleNamespace(state=SimpleNamespace(db=db)),
            )

        with pytest.raises(HTTPException) as caught:
            await sheets.google_drive_webhook(request("wrong"))
        assert caught.value.status_code == 403
        response = await sheets.google_drive_webhook(request("proof"))
        assert response.status_code == 204
        imported.assert_awaited_once()
        note = await db.notifications.find_one({"workspace_id": ws})
        assert note["title"] == "1 new leads imported"

    asyncio.run(isolated(run))


def test_ai_mapping_keeps_exact_matches_and_adds_semantic_custom_fields(monkeypatch):
    headers = ["id", "Full Name", "phone_number", "campaign_name", "What is your budget?"]
    settings = {"fields": [
        {"key": "phone", "label": "Phone", "type": "phone", "active": True},
        {"key": "full_name", "label": "Name", "type": "text", "active": True},
        {"key": "budget", "label": "Budget", "type": "currency", "active": True},
    ]}
    targets = sheets.mapping_targets(settings)

    async def generate(*args, **kwargs):
        return {"column_map": {
            "budget": "What is your budget?",
            "meta_lead_id": "What is your budget?",  # cannot replace exact id match
            "unknown_target": "Full Name",
        }}

    monkeypatch.setattr(llm_service, "generate_json", generate)
    result = asyncio.run(sheets.generate_ai_column_map("model", headers, targets))
    assert result["meta_lead_id"] == "id"
    assert result["meta_campaign_name"] == "campaign_name"
    assert result["full_name"] == "Full Name"
    assert result["phone"] == "phone_number"
    assert result["budget"] == "What is your budget?"
    assert "unknown_target" not in result
    assert len(result.values()) == len(set(result.values()))


def test_sheet_poll_overlap_imports_late_row_behind_cursor(monkeypatch):
    scheduled = AsyncMock()
    monkeypatch.setattr("plivo_calls.schedule_first_qualification_call", scheduled)

    async def run(db):
        ws = str(ObjectId())
        await ensure_crm_settings(db, ws)
        headers = ["ID", "Phone", "Name"]
        conn = {
            "workspace_id": ws,
            "spreadsheet_id": "file",
            "sheet_name": "Leads",
            "tokens": {},
            "cursor": 5,
            "header_row": headers,
            "column_map": {"meta_lead_id": "ID", "phone": "Phone", "full_name": "Name"},
        }
        await db.google_sheet_connections.insert_one(conn)
        _, created = await sheets.import_sheet_row(
            db, ws, conn, headers, ["existing", "111", "Existing Lead"], 2, {"phone", "full_name"}
        )
        assert created

        async def request(db, conn, method, cells, **kwargs):
            assert method == "GET"
            if cells == "1:1":
                return {"values": [headers]}
            assert cells == "A2:C251"
            return {"values": [
                ["existing", "111", "Existing Lead"],
                [],
                ["late-meta-lead", "222", "Late Meta Lead"],
            ]}

        monkeypatch.setattr(sheets, "sheet_request", request)
        result = await sheets.poll_sheet_connection(db, ws, conn)
        assert result == {"created": 1, "reviewed": 2, "cursor": 5}
        lead = await db.crm_leads.find_one({"workspace_id": ws, "meta_lead_id": "late-meta-lead"})
        assert lead["phone"] == "222"
        assert lead["google_sheet_row_number"] == 4
        stored_conn = await db.google_sheet_connections.find_one({"workspace_id": ws})
        assert stored_conn["cursor"] == 5
        scheduled.assert_awaited_once_with(db, ws, str(lead["_id"]))

    asyncio.run(isolated(run))


async def seed(db):
    ws = str(ObjectId())
    settings = await ensure_crm_settings(db, ws)
    settings["states"] += [{"key": "qualified", "label": "Qualified"}, {"key": "converted", "label": "Converted"}]
    await db.crm_settings.update_one({"workspace_id": ws}, {"$set": {"states": settings["states"]}})
    conn = {"workspace_id": ws, "spreadsheet_id": "file", "sheet_name": "Leads", "tokens": {},
            "header_row": ["ID", "Phone", "Status", "Budget"],
            "column_map": {"meta_lead_id": "id", "phone": "phone", "status": "status", "budget": "budget"}}
    await db.google_sheet_connections.insert_one(conn)
    lead_id, created = await sheets.import_sheet_row(db, ws, conn, conn["header_row"], ["987654321", "123", "New", "90000"], 2, {"phone", "budget"})
    assert created
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=db)))
    return ws, lead_id, conn, request


def fake_sheet(monkeypatch, duplicate=False, failure=False):
    writes = []
    async def request(db, conn, method, cells, **kwargs):
        if failure:
            raise RuntimeError("secret provider body")
        if method == "PUT":
            writes.append((cells, kwargs["json"]["values"]))
            return {}
        if cells == "1:1":
            return {"values": [["ID", "Phone", "Status", "Budget"]]}
        if cells == "A2:A":
            return {"values": [["someone-else"], ["987654321"], *([["987654321"]] if duplicate else [])]}
        return {"values": [["New"]]}
    monkeypatch.setattr(sheets, "sheet_request", request)
    return writes


def test_status_changes_matching_replay_and_conversion(monkeypatch):
    from auth import create_access_token
    monkeypatch.setenv("JWT_SECRET", "sheet-conversion-test-only-signing-secret")
    writes = fake_sheet(monkeypatch)
    async def run(db):
        ws, lead_id, conn, request = await seed(db)
        user_id = ObjectId()
        await db.users.insert_one({"_id": user_id, "email": "sheet-conversion@example.test"})
        await db.workspaces.insert_one({"_id": ObjectId(ws), "user_id": str(user_id)})
        request.cookies = {}
        request.headers = {"Authorization": "Bearer " + create_access_token(str(user_id), "sheet-conversion@example.test")}
        query = {"_id": ObjectId(lead_id)}
        assert (await db.crm_leads.find_one(query))["field_values"]["budget"] == "90000"
        result = await update_lead(ws, lead_id, request, {"status": "qualified"})
        assert result["google_sheet_sync_status"] == "success"
        assert writes == [("C3", [["Qualified"]])]
        result = await update_lead(ws, lead_id, request, {"status": "converted"})
        assert writes[-1] == ("C3", [["Converted"]])
        assert result["google_sheet_row_number"] == 3
        await update_lead(ws, lead_id, request, {"status": "converted"})
        assert len(writes) == 2
        _, created = await sheets.import_sheet_row(db, ws, conn, conn["header_row"], ["987654321", "123", "New", "90000"], 3, {"phone", "budget"})
        assert not created
        await sheets.retry_sheet_statuses(db)
        assert (await db.crm_leads.find_one(query))["status"] == "converted"
        assert len(writes) == 2
        await convert_lead(ws, lead_id, request, {"conversion_type": "single_payment"})
        assert writes[-1] == ("C3", [["Won"]])
        await convert_lead(ws, lead_id, request, {"conversion_type": "single_payment"})
        assert len(writes) == 3
    asyncio.run(isolated(run))


def test_failure_preserves_crm_and_retry_recovers(monkeypatch, caplog):
    fake_sheet(monkeypatch, failure=True)
    async def run(db):
        ws, lead_id, _, request = await seed(db)
        result = await update_lead(ws, lead_id, request, {"status": "qualified"})
        assert result["status"] == "qualified"
        assert result["google_sheet_sync_status"] == "failed"
        assert "secret" not in result["google_sheet_sync_error"]
        assert "Sheet status sync failed" in caplog.text
        writes = fake_sheet(monkeypatch)
        await sheets.sync_lead_status(db, ws, lead_id)
        result = await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
        assert result["google_sheet_sync_status"] == "success"
        assert result["google_sheet_sync_error"] is None
        assert writes == [("C3", [["Qualified"]])]
    asyncio.run(isolated(run))


@pytest.mark.parametrize("problem", ["duplicate", "missing_id", "rebound", "missing_mapping"])
def test_unsafe_matching_never_writes(monkeypatch, problem):
    writes = fake_sheet(monkeypatch, duplicate=problem == "duplicate")
    async def run(db):
        ws, lead_id, _, request = await seed(db)
        if problem == "missing_id":
            await db.crm_leads.update_one({"_id": ObjectId(lead_id)}, {"$unset": {"meta_lead_id": ""}})
        if problem == "rebound":
            await db.google_sheet_connections.update_one({"workspace_id": ws}, {"$set": {"spreadsheet_id": "other"}})
        if problem == "missing_mapping":
            await db.google_sheet_connections.update_one({"workspace_id": ws}, {"$unset": {"column_map.status": ""}})
        result = await update_lead(ws, lead_id, request, {"status": "qualified"})
        assert result["google_sheet_sync_status"] == "failed"
        assert result["status"] == "qualified"
        assert not writes
    asyncio.run(isolated(run))


def test_migration_idempotency_and_legacy_leads(monkeypatch):
    request_mock = AsyncMock()
    monkeypatch.setattr(sheets, "sheet_request", request_mock)
    async def run(db):
        ws, lead_id, conn, request = await seed(db)
        await db.crm_leads.update_one({"_id": ObjectId(lead_id)}, {"$unset": {"meta_lead_id": "", "google_sheet_spreadsheet_id": "", "google_sheet_name": ""}})
        await migrate(db, ws)
        first = await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
        await migrate(db, ws)
        assert first == await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
        assert first["meta_lead_id"] == "987654321"
        assert first["google_sheet_spreadsheet_id"] == "file"
        assert not first.get("google_sheet_sync_status")
        await db.crm_leads.update_one({"_id": ObjectId(lead_id)}, {"$set": {"source": "manual"}, "$unset": {"google_sheet_spreadsheet_id": "", "meta_lead_id": ""}})
        result = await update_lead(ws, lead_id, request, {"status": "qualified"})
        assert result["status"] == "qualified"
        request_mock.assert_not_called()
    asyncio.run(isolated(run))


def test_newer_status_is_not_acknowledged_by_older_sync(monkeypatch):
    async def run(db):
        ws, lead_id, _, request = await seed(db)
        writes = []
        async def remote(db, conn, method, cells, **kwargs):
            if method == "PUT":
                lead = await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
                await db.crm_leads.update_one({"_id": lead["_id"]}, {"$set": {"status": "converted", **pending_sheet_sync(lead, "converted")}})
                writes.append(kwargs["json"])
                return {}
            return {"values": [["ID", "Phone", "Status"]] if cells == "1:1" else [["987654321"]] if cells == "A2:A" else [["New"]]}
        monkeypatch.setattr(sheets, "sheet_request", remote)
        result = await update_lead(ws, lead_id, request, {"status": "qualified"})
        assert result["status"] == "converted"
        assert result["google_sheet_sync_status"] == "pending"
        fake_sheet(monkeypatch)
        await sheets.retry_sheet_statuses(db)
        result = await db.crm_leads.find_one({"_id": ObjectId(lead_id)})
        assert result["google_sheet_synced_status"] == "converted"
    asyncio.run(isolated(run))


def test_mapping_targets_persist_and_status_cannot_overwrite_id():
    async def run(db):
        ws, _, conn, request = await seed(db)
        await db.crm_settings.update_one({"workspace_id": ws}, {"$push": {"fields": {"key": "budget", "label": "Budget", "type": "text", "active": True}}})
        await sheets.update_column_map(ws, request, {"column_map": conn["column_map"]})
        stored = await db.google_sheet_connections.find_one({"workspace_id": ws})
        assert stored["column_map"] == conn["column_map"]
        result = await sheets.get_connection_status(ws, request)
        assert set(META_FIELDS) <= {f["key"] for f in result["mapping_fields"]}
        with pytest.raises(HTTPException):
            await sheets.update_column_map(ws, request, {"column_map": {**conn["column_map"], "status": "ID"}})
    asyncio.run(isolated(run))


def test_already_matching_sheet_status_skips_write(monkeypatch):
    async def run(db):
        ws, lead_id, _, request = await seed(db)
        writes = []
        async def remote(db, conn, method, cells, **kwargs):
            if method == "PUT":
                writes.append(cells)
            return {"values": [["ID", "Phone", "Status"]] if cells == "1:1" else [["987654321"]] if cells == "A2:A" else [["Qualified"]]}
        monkeypatch.setattr(sheets, "sheet_request", remote)
        result = await update_lead(ws, lead_id, request, {"status": "qualified"})
        assert result["google_sheet_sync_status"] == "success"
        assert not writes
    asyncio.run(isolated(run))
