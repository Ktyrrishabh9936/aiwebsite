"""Run once before deploying workspace invitations and member portals."""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from models import now_iso


async def migrate(db):
    await db.workspace_memberships.create_index([("workspace_id", 1), ("user_id", 1)], unique=True)
    await db.workspace_memberships.create_index([("workspace_id", 1), ("sales_person_id", 1)], unique=True, partialFilterExpression={"sales_person_id": {"$type": "string"}})
    await db.workspace_invitations.create_index("token_hash", unique=True)
    await db.workspace_memberships.create_index([("user_id", 1), ("active", 1)])
    for key in ("sales_agent_id", "channel_partner_id", "introduced_by_id"):
        await db.crm_leads.create_index([("workspace_id", 1), (f"sales_assignment.{key}", 1), ("deleted_at", 1), ("created_at", -1)])
    owners = 0
    async for workspace in db.workspaces.find({"user_id": {"$type": "string"}}):
        ws_id, user_id = str(workspace["_id"]), workspace["user_id"]
        await db.workspace_memberships.update_one({"workspace_id": ws_id, "user_id": user_id}, {"$setOnInsert": {"_id": f"{ws_id}:{user_id}", "role": "owner", "active": True, "created_at": now_iso()}}, upsert=True)
        owners += 1
    retired = await db.crm_leads.update_many({"lead_share.token_hash": {"$exists": True}}, {"$unset": {"lead_share": ""}})
    return {"owner_workspaces": owners, "retired_bearer_links": retired.modified_count}


async def main():
    load_dotenv(Path(__file__).with_name(".env"))
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    try:
        print(await migrate(client[os.environ["DB_NAME"]]))
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
