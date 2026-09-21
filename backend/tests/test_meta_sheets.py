import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx
from bson import ObjectId
from fastapi import HTTPException

import google_sheets as sheets
from crm import ensure_crm_settings, update_lead, convert_lead, normalize_field
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
    writes = fake_sheet(monkeypatch)
    async def run(db):
        ws, lead_id, conn, request = await seed(db)
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
