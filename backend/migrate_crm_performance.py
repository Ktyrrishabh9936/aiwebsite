"""Run once during deployment: python migrate_crm_performance.py.

Only adds indexes to existing collections; does not modify lead or call records.
"""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


async def main():
    load_dotenv(Path(__file__).with_name(".env"))
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    try:
        db = client[os.environ["DB_NAME"]]
        await db.crm_leads.create_index([("workspace_id", 1), ("created_at", -1)])
        await db.tasks.create_index([("workspace_id", 1), ("lead_id", 1), ("source", 1), ("status", 1)])
        await db.tasks.create_index([("workspace_id", 1), ("source", 1), ("status", 1), ("scheduled_time", 1)])
        await db.crm_leads.create_index([("workspace_id", 1), ("status", 1), ("created_at", -1), ("_id", -1)])
        print("CRM performance indexes ready")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
