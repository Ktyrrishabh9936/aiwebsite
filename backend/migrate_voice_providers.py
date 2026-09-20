"""Explicit, idempotent migration; never infer which tenant owns environment credentials.

Run from backend: python migrate_voice_providers.py --workspace-id ID [--from-environment]
Existing configuration is not overwritten. --rotate-key re-encrypts stored credentials.
"""
import argparse
import asyncio
import os
from bson import ObjectId
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import HTTPException

from voice_config import decrypt, encrypt, save_config


async def migrate(db, ws_id, from_environment=False, rotate_key=False):
    if not ObjectId.is_valid(ws_id) or not await db.workspaces.find_one({"_id": ObjectId(ws_id)}):
        raise ValueError("Workspace not found")
    await db.workspace_voice_provider_configs.create_index([("workspace_id", 1), ("provider", 1)], unique=True)
    query = {"workspace_id": ws_id, "provider": "plivo"}
    existing = await db.workspace_voice_provider_configs.find_one(query)
    if not existing and not rotate_key:
        if from_environment:
            from plivo_calls import legacy_agent_config_from_env
            agent = legacy_agent_config_from_env()
        else:
            agent = await db.plivo_agent_configs.find_one({"workspace_id": ws_id, "is_default": True, "enabled": True})
            agent = agent or await db.plivo_agent_configs.find_one({"workspace_id": ws_id, "enabled": True})
        if not agent:
            raise ValueError("No source Plivo agent; configure provider in workspace settings")
        credentials = decrypt(ws_id, "plivo", agent["encrypted_credentials"]) if agent.get("encrypted_credentials") else agent.get("credentials", {})
        # Global account values are read only on explicit environment import.
        auth_id = os.getenv("PLIVO_AUTH_ID", "") if from_environment else credentials.get("username", "")
        auth_token = os.getenv("PLIVO_AUTH_TOKEN", "") if from_environment else credentials.get("password", "")
        config = {k: agent[k] for k in ("trigger_url", "from_number", "flow_id", "auth_type", "input_variable_mappings", "extra_payload") if k in agent}
        config["auth_id"] = auth_id
        if from_environment and os.getenv("PLIVO_STAFF_NUMBER"):
            config["staff_number"] = os.environ["PLIVO_STAFF_NUMBER"]
        if config.get("auth_type") == "none":
            config["auth_type"] = "basic"
        secrets = {"auth_token": auth_token, "bearer_token": credentials.get("bearer_token", "")}
        if from_environment:
            secrets["callback_token"] = os.getenv("PLIVO_AGENT_CALLBACK_TOKEN", "")
        await save_config(db, ws_id, "plivo", bool(agent.get("enabled", True)), config, secrets)
    # Encrypt every legacy agent in this workspace without deleting its mappings/IDs.
    async for agent in db.plivo_agent_configs.find({"workspace_id": ws_id}):
        secrets = decrypt(ws_id, "plivo", agent["encrypted_credentials"]) if agent.get("encrypted_credentials") else agent.get("credentials", {})
        await db.plivo_agent_configs.update_one({"_id": agent["_id"], "workspace_id": ws_id},
            {"$set": {"encrypted_credentials": encrypt(ws_id, "plivo", secrets)}, "$unset": {"credentials": ""}})
    if rotate_key:
        async for config in db.workspace_voice_provider_configs.find({"workspace_id": ws_id}):
            secrets = decrypt(ws_id, config["provider"], config["encrypted_credentials"])
            await db.workspace_voice_provider_configs.update_one({"_id": config["_id"], "workspace_id": ws_id, "revision": config["revision"]},
                {"$set": {"encrypted_credentials": encrypt(ws_id, config["provider"], secrets)}})
    await db.qualification_profiles.update_many({"workspace_id": ws_id, "voice_provider": {"$exists": False}}, {"$set": {"voice_provider": "plivo"}})
    # Preserve historical records while removing old callback tokens from snapshots.
    from qualification_service import audit_payload
    for collection, fields in (
        (db.plivo_call_sessions, ("request_payload", "base_payload_snapshot", "trigger_response", "last_callback_payload")),
        (db.plivo_call_events, ("payload",)),
        (db.crm_call_logs, ("payload", "response", "call_result")),
        (db.crm_leads, ("qualification_call", "communication_summary", "lead_notes")),
    ):
        async for row in collection.find({"workspace_id": ws_id}):
            patch = {key: audit_payload(row[key]) for key in fields if key in row}
            if any(patch[key] != row[key] for key in patch):
                await collection.update_one({"_id": row["_id"], "workspace_id": ws_id}, {"$set": patch})


async def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--from-environment", action="store_true")
    parser.add_argument("--rotate-key", action="store_true")
    args = parser.parse_args()
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    try:
        await migrate(client[os.environ["DB_NAME"]], args.workspace_id, args.from_environment, args.rotate_key)
        print("Migration complete. Verify the workspace connection in Settings before resuming calls.")
    except (ValueError, HTTPException) as error:
        print(error.detail if isinstance(error, HTTPException) else str(error))
        raise SystemExit(1) from None
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
