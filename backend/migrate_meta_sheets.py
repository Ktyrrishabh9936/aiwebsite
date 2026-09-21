"""Idempotent source-data migration: python migrate_meta_sheets.py [--workspace-id ID].

Uses saved raw import data and configured mappings; never changes sales status.
"""
import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from meta_fields import META_FIELDS, map_sheet_row


async def migrate(db, workspace_id=None):
    scope = {"workspace_id": workspace_id} if workspace_id else {}
    async for lead in db.crm_leads.find({**scope, "source": "google_sheet"}):
        conn = await db.google_sheet_connections.find_one({"workspace_id": lead["workspace_id"]})
        if not conn or not conn.get("spreadsheet_id"):
            continue
        raw = lead.get("fields") or {}
        headers = list(raw)
        mapping = dict(conn.get("column_map") or {})
        for key, (header, _) in META_FIELDS.items():
            if key not in mapping and any(str(h).strip().casefold() == header for h in headers):
                mapping[key] = header
        try:
            _, attribution = map_sheet_row(headers, list(raw.values()), mapping, [])
        except ValueError:
            continue  # Do not guess after a mapping/binding change; reimport instead.
        patch = {k: v for k, v in attribution.items() if lead.get(k) is None and v is not None}
        # Old imports used the mapped ID as row key. Only attach a source when that
        # identity can be verified, or the stored key explicitly names this tab.
        meta_id = lead.get("meta_lead_id") or patch.get("meta_lead_id")
        prefix = f"{conn['spreadsheet_id']}_{conn['sheet_name']}_"
        row_key = str(lead.get("sheet_row_key") or "")
        if row_key.startswith(prefix):
            try:
                patch["google_sheet_row_number"] = int(row_key[len(prefix):])
            except ValueError:
                pass
        if not lead.get("google_sheet_spreadsheet_id") and (row_key.startswith(prefix) or meta_id and row_key == meta_id):
            patch.update(google_sheet_spreadsheet_id=conn["spreadsheet_id"], google_sheet_name=conn["sheet_name"])
        for key in ("last_google_sheet_sync_at", "google_sheet_sync_status", "google_sheet_sync_error"):
            if key not in lead:
                patch[key] = None
        if patch:
            await db.crm_leads.update_one({"_id": lead["_id"], "workspace_id": lead["workspace_id"]}, {"$set": patch})
    # Nonunique: legacy duplicates are reported by sync, never deleted by migration.
    await db.crm_leads.create_index([("workspace_id", 1), ("meta_lead_id", 1)])
    await db.crm_leads.create_index([("google_sheet_sync_status", 1), ("google_sheet_sync_next_attempt_at", 1)])


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id")
    args = parser.parse_args()
    load_dotenv(Path(__file__).with_name(".env"))
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    try:
        await migrate(client[os.environ["DB_NAME"]], args.workspace_id)
        print("Meta attribution and Sheet sync migration complete.")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
