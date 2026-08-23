"""Haven — Seed "The Anchorage" room + the SL relay account.

Idempotent. Safe to run repeatedly. Non-destructive: it only creates rows that
do not already exist and joins members who are not already members.

What it does:
  1. Ensures the "anchorage" room exists (display "The Anchorage").
  2. Creates the "anchorage" relay user (is_bot=False so the entity bots treat
     relayed SL speech as a human worth answering) with a fresh token, saved to
     haven/data/anchorage-relay.token — this is what the relay service logs in with.
  3. Generates a shared secret for the SL<->relay HTTP hop, saved to
     haven/data/anchorage-sl-secret.txt (the LSL prims carry the same string).
  4. Adds lyra + caia (the two Haven bots that already run) and invites the
     humans jeff / jaden / crusher / night — whichever of them already exist.

Usage:
    /mnt/c/Users/Jeff/Claude_Projects/Awareness/.venv/bin/python -m haven.anchorage.seed
"""

import asyncio
import os
import secrets
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from haven.auth import hash_token
from haven.db import HavenDB

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = os.getenv("HAVEN_DB_PATH", str(PROJECT_ROOT / "haven" / "data" / "haven.db"))
DATA_DIR = PROJECT_ROOT / "haven" / "data"

ROOM_NAME = "anchorage"
ROOM_DISPLAY = "The Anchorage"
RELAY_USERNAME = "anchorage"
RELAY_DISPLAY = "The Anchorage"  # how SL-origin speech is labelled in Haven

# Room members. Bots that carry a voice, plus the humans to invite.
BOT_MEMBERS = ["lyra", "caia"]
HUMAN_MEMBERS = ["jeff", "jaden", "crusher", "night"]

RELAY_TOKEN_FILE = DATA_DIR / "anchorage-relay.token"
SL_SECRET_FILE = DATA_DIR / "anchorage-sl-secret.txt"


async def _ensure_member(db, room_id: str, username: str) -> None:
    user = await db.get_user_by_username(username)
    if not user:
        print(f"  - {username}: no such Haven user yet (skipped — create the account first)")
        return
    newly = await db.join_room(room_id, user["id"])
    print(f"  - {username}: {'added' if newly else 'already a member'}")


async def seed():
    db = HavenDB(DB_PATH)
    await db.initialize()
    print(f"Seeding The Anchorage into {DB_PATH}\n")

    # --- Relay user (SL-origin speech is authored by this account) ---
    relay = await db.get_user_by_username(RELAY_USERNAME)
    if not relay:
        relay_token = str(uuid.uuid4())
        relay = await db.create_user(
            RELAY_USERNAME, RELAY_DISPLAY, hash_token(relay_token), is_bot=False
        )
        RELAY_TOKEN_FILE.write_text(relay_token + "\n")
        os.chmod(RELAY_TOKEN_FILE, 0o600)
        print(f"  Created relay user '{RELAY_USERNAME}'")
        print(f"  Relay token -> {RELAY_TOKEN_FILE}")
    else:
        print(f"  Relay user '{RELAY_USERNAME}' already exists")
        if not RELAY_TOKEN_FILE.exists():
            # User exists but we lost the token file — mint a fresh one and rotate.
            relay_token = str(uuid.uuid4())
            await db.regenerate_token(relay["id"], hash_token(relay_token))
            RELAY_TOKEN_FILE.write_text(relay_token + "\n")
            os.chmod(RELAY_TOKEN_FILE, 0o600)
            print(f"  (token file was missing — rotated; new token -> {RELAY_TOKEN_FILE})")

    # --- Shared secret for the SL <-> relay HTTP hop ---
    if not SL_SECRET_FILE.exists():
        SL_SECRET_FILE.write_text(secrets.token_urlsafe(32) + "\n")
        os.chmod(SL_SECRET_FILE, 0o600)
        print(f"  Generated SL shared secret -> {SL_SECRET_FILE}")
    else:
        print(f"  SL shared secret already present -> {SL_SECRET_FILE}")

    # --- Room ---
    room = await db.get_room_by_name(ROOM_NAME)
    if not room:
        # Creator = jeff if present, else the relay account (creator auto-joins).
        jeff = await db.get_user_by_username("jeff")
        creator_id = jeff["id"] if jeff else relay["id"]
        room = await db.create_room(ROOM_NAME, ROOM_DISPLAY, creator_id)
        print(f"  Created room '{ROOM_NAME}' ({ROOM_DISPLAY})")
    else:
        print(f"  Room '{ROOM_NAME}' already exists")

    # --- Membership ---
    print("\n  Members:")
    await _ensure_member(db, room["id"], RELAY_USERNAME)
    for u in BOT_MEMBERS:
        await _ensure_member(db, room["id"], u)
    for u in HUMAN_MEMBERS:
        await _ensure_member(db, room["id"], u)

    await db.close()
    print("\nDone. The Anchorage room is ready.")
    print(f"  Relay logs in with the token in {RELAY_TOKEN_FILE.name}")
    print(f"  SL prims carry the secret in {SL_SECRET_FILE.name}")


if __name__ == "__main__":
    asyncio.run(seed())
