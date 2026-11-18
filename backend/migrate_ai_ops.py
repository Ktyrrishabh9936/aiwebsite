"""Idempotent indexes for the daily AI run, connectors and meetings.

Run once per environment before deploying the API:
    python migrate_ai_ops.py
"""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).with_name(".env"))


async def migrate():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], appname="arevei-migration")
    db = client[os.environ["DB_NAME"]]
    indexes = [
        (db.workspaces, [("ai_ops.enabled", 1), ("ai_ops.next_run_at", 1)], {"sparse": True}),
        (db.ai_ops_runs, [("workspace_id", 1), ("created_at", -1)], {}),
        (db.ai_ops_runs, [("status", 1), ("created_at", 1)], {}),
        (db.ai_ops_actions, [("status", 1), ("scheduled_for", 1)], {}),
        (db.ai_ops_actions, [("workspace_id", 1), ("run_id", 1)], {}),
        (db.ai_ops_actions, [("workspace_id", 1), ("created_at", -1)], {}),
        (db.ai_ops_meetings, [("workspace_id", 1), ("start", 1)], {}),
        (db.workspace_connectors, [("workspace_id", 1), ("kind", 1)], {"unique": True}),
        (db.ai_agents, [("workspace_id", 1), ("order", 1)], {}),
        (db.crm_leads, [("workspace_id", 1), ("last_call_at", -1)], {"sparse": True}),
    ]
    for collection, keys, options in indexes:
        name = await collection.create_index(keys, **options)
        print(f"{collection.name}: {name}")
    client.close()


if __name__ == "__main__":
    asyncio.run(migrate())
