"""Idempotent deployment migration for indexes and hot-path data normalization.

Run once per environment before deploying the API:
    python migrate_runtime.py

Set SEED_ADMIN=1 only when the environment should provision/update the configured
admin account. Keeping it opt-in avoids bcrypt work during normal deployments.
"""

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

from auth import seed_admin
from crm import ensure_crm_settings, normalize_states, phone_first_fields


load_dotenv(Path(__file__).with_name(".env"))


def _iso_to_datetime(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def migrate():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], appname="arevei-migration")
    db = client[os.environ["DB_NAME"]]
    indexes = [
        (db.users, "email", {"unique": True}),
        (db.password_reset_tokens, "token_hash", {"unique": True}),
        (db.password_reset_tokens, "expires_at", {"expireAfterSeconds": 0}),
        (db.workspaces, "public_key", {}),
        (db.blogs, "slug", {"unique": True}),
        (db.code_projects, "user_id", {}),
        (db.code_projects, "workspace_id", {}),
        (db.workflows, [("workspace_id", 1), ("kind", 1)], {}),
        (db.google_sheet_connections, "drive_watch_channel_id", {"unique": True, "sparse": True}),
        (db.crm_leads, [("workspace_id", 1), ("sheet_row_key", 1)], {"unique": True}),
        (db.crm_leads, [("workspace_id", 1), ("plivo_call_uuid", 1)], {}),
        (db.crm_leads, [("workspace_id", 1), ("created_at", -1)], {}),
        (db.crm_leads, [("workspace_id", 1), ("deleted_at", 1), ("created_at", -1)], {}),
        (db.crm_leads, [("workspace_id", 1), ("status", 1), ("deleted_at", 1), ("created_at", -1)], {}),
        (db.crm_leads, "delete_after", {"expireAfterSeconds": 0}),
        (db.crm_settings, "workspace_id", {"unique": True}),
        (db.workspace_voice_provider_configs, [("workspace_id", 1), ("provider", 1)], {"unique": True}),
        (db.plivo_agent_configs, [("workspace_id", 1), ("enabled", 1), ("is_default", 1)], {}),
        (db.plivo_call_sessions, [("workspace_id", 1), ("lead_id", 1), ("status", 1)], {}),
        (db.plivo_call_sessions, [("workspace_id", 1), ("created_at", -1)], {}),
        (db.plivo_call_events, [("workspace_id", 1), ("idempotency_key", 1)], {"unique": True}),
        (db.plivo_call_events, [("workspace_id", 1), ("lead_id", 1), ("created_at", -1)], {}),
        (db.qualification_profiles, [("workspace_id", 1), ("campaign_id", 1)], {"unique": True, "partialFilterExpression": {"campaign_id": {"$type": "string"}}}),
        (db.crm_call_logs, [("workspace_id", 1), ("lead_id", 1), ("kind", 1)], {}),
        (db.tasks, [("workspace_id", 1), ("lead_id", 1), ("source", 1), ("status", 1)], {}),
        (db.catalog_items, [("workspace_id", 1), ("kind", 1), ("status", 1)], {}),
        (db.properties, [("workspace_id", 1), ("status", 1)], {}),
        (db.property_units, [("workspace_id", 1), ("property_id", 1), ("tower", 1), ("unit_number", 1)], {"unique": True}),
        (db.property_units, [("workspace_id", 1), ("status", 1), ("property_id", 1)], {}),
        (db.crm_leads, [("workspace_id", 1), ("status", 1), ("opportunity.total_minor", 1)], {}),
        (db.ai_usage_events, [("workspace_id", 1), ("day", -1), ("process", 1)], {}),
        (db.ai_manager_voice_sessions, "expires_at", {"expireAfterSeconds": 0}),
        (db.ai_manager_voice_sessions, [("workspace_id", 1), ("started_at", -1)], {}),
        (db.ai_manager_voice_sessions, [("caller_phone", 1), ("session_id", 1)], {}),
    ]
    for collection, keys, options in indexes:
        name = await collection.create_index(keys, **options)
        print(f"index ready: {collection.name}.{name}")

    async for settings in db.crm_settings.find({}, {"fields": 1, "states": 1}):
        fields = phone_first_fields(settings.get("fields") or [])
        states = normalize_states(settings.get("states") or [])
        if fields != settings.get("fields") or states != settings.get("states"):
            await db.crm_settings.update_one({"_id": settings["_id"]}, {"$set": {"fields": fields, "states": states}})

    async for workspace in db.workspaces.find({}, {"_id": 1}):
        await ensure_crm_settings(db, str(workspace["_id"]))

    async for lead in db.crm_leads.find({"delete_after": {"$type": "string"}}, {"delete_after": 1}):
        converted = _iso_to_datetime(lead.get("delete_after"))
        if converted:
            await db.crm_leads.update_one({"_id": lead["_id"]}, {"$set": {"delete_after": converted}})

    if os.environ.get("SEED_ADMIN", "").strip().lower() in {"1", "true", "yes"}:
        await seed_admin(db)
        print("admin provisioning complete")
    client.close()


if __name__ == "__main__":
    asyncio.run(migrate())
