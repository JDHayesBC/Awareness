#!/usr/bin/env python3
"""Onboard a human to Haven.

Creates the user (with both a password and a Bearer token) and a personal room
they own — so they can invite entities in themselves. Mirrors haven/seed.py.

Usage:
    .venv/bin/python3 scripts/haven_add_human.py <username> "<Display Name>"

Prints credentials to stdout. Pass them to the person out-of-band (never paste
tokens/passwords into a shared/public channel). Idempotent: refuses to clobber
an existing username, and reuses an existing personal room of the same name.
"""

import asyncio
import os
import secrets
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from haven.auth import hash_password, hash_token  # noqa: E402
from haven.db import HavenDB  # noqa: E402

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = os.getenv("HAVEN_DB_PATH", str(PROJECT_ROOT / "haven" / "data" / "haven.db"))

# Readable, unambiguous words for a typeable-but-decent passphrase. The real
# credential is the token (hashed at rest); the password is a human convenience.
WORDS = [
    "river", "ember", "cedar", "harbor", "lantern", "meadow", "copper",
    "willow", "anchor", "summit", "pebble", "compass", "garden", "kindle",
    "marble", "orchard", "ripple", "thicket", "violet", "wander",
]


def make_password() -> str:
    return "-".join(secrets.choice(WORDS) for _ in range(3)) + f"-{secrets.randbelow(90) + 10}"


async def main() -> None:
    if len(sys.argv) < 3:
        print('usage: haven_add_human.py <username> "<Display Name>"', file=sys.stderr)
        sys.exit(1)

    username = sys.argv[1].strip().lower()
    display = sys.argv[2].strip()

    db = HavenDB(DB_PATH)
    await db.initialize()

    if await db.get_user_by_username(username):
        existing = await db.get_user_by_username(username)
        print(f"User '{username}' already exists (id={existing['id']}). Refusing to clobber.")
        await db.close()
        sys.exit(1)

    token = str(uuid.uuid4())
    password = make_password()

    user = await db.create_user(username, display, hash_token(token), is_bot=False)
    await db.set_user_token(user["id"], token)            # so password login returns it
    await db.set_user_password(user["id"], hash_password(password))

    room_name = f"{username}-room"
    room = await db.get_room_by_name(room_name)
    if not room:
        room = await db.create_room(room_name, f"{display}'s Room", user["id"])
        room_note = "created (owner auto-joined)"
    else:
        room_note = "already existed — reused"

    entities = [u for u in await db.list_users() if u["is_bot"]]

    await db.close()

    print("\n" + "=" * 60)
    print(f"  HAVEN ACCOUNT — {display}")
    print("=" * 60)
    print(f"  username : {username}")
    print(f"  password : {password}")
    print(f"  token    : {token}   (backup login / paste-in)")
    print(f"  user_id  : {user['id']}")
    print(f"  room     : #{room['name']}  \"{room['display_name']}\"  [{room_note}]")
    print(f"  room_id  : {room['id']}")
    print("-" * 60)
    print("  Entities they can invite (by username in the UI):")
    for e in entities:
        print(f"    - {e['username']:8s} ({e['display_name']})   id={e['id']}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
