"""Add module defaults and indexes: python migrate_workspace_modules.py [--workspace-id ID]."""
import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


async def migrate(db, workspace_id=None):
    scope = {"_id": workspace_id} if workspace_id else {}
    if workspace_id:
        from bson import ObjectId
        scope["_id"] = ObjectId(workspace_id)
    await db.workspaces.update_many({**scope, "modules": {"$exists": False}}, {"$set": {"modules": {"real_estate": True, "agency": False}}})
    await db.workspaces.update_many({**scope, "currency": {"$exists": False}}, {"$set": {"currency": "INR"}})
    await db.properties.create_index([("workspace_id", 1), ("status", 1)])
    await db.catalog_items.create_index([("workspace_id", 1), ("kind", 1), ("status", 1)])
    await db.crm_leads.create_index([("workspace_id", 1), ("status", 1), ("opportunity.total_minor", 1)])


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id")
    args = parser.parse_args()
    load_dotenv(Path(__file__).with_name(".env"))
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    try:
        await migrate(client[os.environ["DB_NAME"]], args.workspace_id)
        print("Workspace module migration complete.")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
