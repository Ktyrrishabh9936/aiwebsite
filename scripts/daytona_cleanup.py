"""Clean up all Daytona sandboxes to free disk quota."""
import asyncio
import sys
import os

# Load env via dotenv (handles quoted values)
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

sys.path.insert(0, "/app/backend")
from daytona import AsyncDaytona


async def main():
    client = AsyncDaytona()
    sandboxes = []
    async for sb in client.list():
        sandboxes.append(sb)
    print(f"found {len(sandboxes)} sandboxes")
    for sb in sandboxes:
        try:
            state = str(getattr(sb, "state", "unknown"))
            labels = getattr(sb, "labels", {}) or {}
            print(f"- {sb.id} state={state} labels={labels}")
        except Exception as e:
            print(f"- err: {e}")
    if "--delete" in sys.argv:
        for sb in sandboxes:
            try:
                await sb.delete()
                print(f"deleted {sb.id}")
            except Exception as e:
                print(f"delete failed {sb.id}: {e}")


asyncio.run(main())
