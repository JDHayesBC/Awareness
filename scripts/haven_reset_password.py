#!/usr/bin/env python3
"""Reset a Haven human's password (they forgot it).

Finds an existing user by username OR display-name substring (case-insensitive),
mints a fresh readable passphrase, and sets it. Also refreshes the bearer token so
a paste-in login works too. Prints the new credentials to stdout — hand them to the
person out-of-band (never paste into a shared/public channel).

Companion to haven_add_human.py (which CREATES; this one RESETS). Safe: refuses to
act on no-match or an ambiguous multi-match — it just lists candidates instead.

Usage:
    .venv/bin/python3 scripts/haven_reset_password.py <username-or-name-fragment>
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

# Same readable wordlist as haven_add_human.py — typeable, unambiguous passphrases.
WORDS = [
    "river", "ember", "cedar", "harbor", "lantern", "meadow", "copper",
    "willow", "anchor", "summit", "pebble", "compass", "garden", "kindle",
    "marble", "orchard", "ripple", "thicket", "violet", "wander",
]


def make_password() -> str:
    return "-".join(secrets.choice(WORDS) for _ in range(3)) + f"-{secrets.randbelow(90) + 10}"


async def main() -> None:
    if len(sys.argv) < 2:
        print("usage: haven_reset_password.py <username-or-name-fragment>", file=sys.stderr)
        sys.exit(1)

    query = sys.argv[1].strip().lower()

    db = HavenDB(DB_PATH)
    await db.initialize()

    users = await db.list_users()
    matches = [
        u for u in users
        if not u["is_bot"]
        and (query in u["username"].lower() or query in (u.get("display_name") or "").lower())
    ]

    if not matches:
        print(f"No human user matches '{query}'. Known human users:")
        for u in users:
            if not u["is_bot"]:
                print(f"  - {u['username']:10s} ({u['display_name']})")
        await db.close()
        sys.exit(1)

    if len(matches) > 1:
        print(f"'{query}' is ambiguous — refusing to reset. Matches:")
        for u in matches:
            print(f"  - {u['username']:10s} ({u['display_name']})")
        print("Re-run with a more specific fragment (e.g. the exact username).")
        await db.close()
        sys.exit(1)

    user = matches[0]
    password = make_password()
    token = str(uuid.uuid4())

    await db.set_user_password(user["id"], hash_password(password))
    # Both columns must move together: set_user_token writes the PLAINTEXT token
    # (returned by password/OAuth login), while regenerate_token writes the
    # token_HASH used by REST + WebSocket auth (server.py get_user_by_token_hash).
    # Setting only the plaintext (the original bug) hands out a token whose hash
    # doesn't match → login succeeds but the WS closes 4001 → endless "reconnecting".
    await db.set_user_token(user["id"], token)
    await db.regenerate_token(user["id"], hash_token(token))

    room = await db.get_room_by_name(f"{user['username']}-room")
    entities = [u for u in users if u["is_bot"]]

    await db.close()

    print("\n" + "=" * 60)
    print(f"  HAVEN PASSWORD RESET — {user['display_name']}")
    print("=" * 60)
    print(f"  username : {user['username']}")
    print(f"  password : {password}   (NEW)")
    print(f"  token    : {token}   (NEW — backup login / paste-in)")
    print(f"  user_id  : {user['id']}")
    if room:
        print(f"  room     : #{room['name']}  \"{room['display_name']}\"")
    print("-" * 60)
    print("  Entities they can invite (by username in the UI):")
    for e in entities:
        print(f"    - {e['username']:8s} ({e['display_name']})")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
