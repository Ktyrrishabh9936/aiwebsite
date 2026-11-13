"""One-time setup of AREVEI's master Sarvam voice agent (admin only, never shown to users).

Run from backend/ while the backend server is running (it receives the Sarvam sign-in redirect):

    python scripts/setup_sarvam_master_agent.py
    python scripts/setup_sarvam_master_agent.py --language Hindi --connection-id <id> --phone +91XXXXXXXXXX

It signs in to Sarvam (browser, valid 24 hours), lists your telephony connections, creates and
commits the master agent, and prints the lines to paste into backend/.env. Users then only set up
their own agent name, business details and behaviour in AREVEI; no further Sarvam sign-in is needed.
"""
import argparse
import asyncio
import os
import sys
import time
import webbrowser
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

import sarvam_agent_builder as builder  # noqa: E402

SIGN_IN_WAIT = 600


async def ensure_signed_in(db):
    doc = await db.sarvam_account_connections.find_one({"workspace_id": builder.PLATFORM_ACCOUNT}) or {}
    connected_at = doc.get("connected_at")
    fresh = connected_at and datetime.fromisoformat(connected_at) > datetime.now(timezone.utc) - timedelta(hours=23)
    if doc.get("status") == "connected" and fresh:
        print("Using the Sarvam sign-in from", connected_at)
        return
    url = await builder.begin_connect(db, builder.PLATFORM_ACCOUNT, {"_id": "setup-script", "email": "setup script"})
    print("\nSign in to Sarvam with AREVEI's account in your browser:\n\n  " + url + "\n")
    webbrowser.open(url)
    started = datetime.now(timezone.utc).isoformat()
    deadline = time.monotonic() + SIGN_IN_WAIT
    while time.monotonic() < deadline:
        await asyncio.sleep(3)
        doc = await db.sarvam_account_connections.find_one({"workspace_id": builder.PLATFORM_ACCOUNT}) or {}
        if doc.get("status") == "connected" and (doc.get("connected_at") or "") >= started:
            print("Signed in.")
            return
    sys.exit("Sign-in was not completed within 10 minutes. Is the backend running and SARVAM_OAUTH_REDIRECT_URI correct?")


async def main(args):
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    await ensure_signed_in(db)

    connections = await builder.list_connections(db, builder.PLATFORM_ACCOUNT)
    print("\nTelephony connections in Sarvam:")
    for item in connections:
        print(f"  {item['connection_id']}  {item['name']}  numbers: {', '.join(item['phone_numbers']) or 'none'}")
    usable = [c for c in connections if c["phone_numbers"]]
    chosen = next((c for c in usable if c["connection_id"] == args.connection_id), None) if args.connection_id else (usable[0] if usable else None)
    if not chosen:
        sys.exit("No telephony connection with an onboarded number. Add a number in the Sarvam dashboard first.")
    phone = args.phone or chosen["phone_numbers"][0]
    if phone not in chosen["phone_numbers"]:
        sys.exit(f"{phone} is not onboarded on connection {chosen['connection_id']}")

    print(f"\nCreating the master agent '{args.name}' ({args.language})...")
    ids = await builder.create_master_agent(db, args.name, args.language, args.voice_id)
    ids.update({"SARVAM_CONNECTION_ID": chosen["connection_id"], "SARVAM_AGENT_PHONE_NUMBER": phone})
    print("\nDone. Add these lines to backend/.env (next to SARVAM_API_KEY) and restart the backend:\n")
    for key, value in ids.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="AREVEI Voice Agent", help="Agent name inside Sarvam (users never see it)")
    parser.add_argument("--language", default="English", choices=builder.SUPPORTED_LANGUAGES)
    parser.add_argument("--voice-id", default=None, help="Optional Sarvam voice id")
    parser.add_argument("--connection-id", default=None, help="Telephony connection to call from (default: first with a number)")
    parser.add_argument("--phone", default=None, help="Calling number on that connection (default: its first number)")
    asyncio.run(main(parser.parse_args()))
