"""Haven — Seed default users and rooms.

Usage:
    python -m haven.seed

Creates Jeff (human), Lyra (entity), Caia (entity) and default rooms.
Reads entity tokens from their PPS entity_token files.
Generates a new token for Jeff and saves it to haven/data/jeff.token.
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from haven.auth import hash_token
from haven.db import HavenDB


PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = os.getenv("HAVEN_DB_PATH", str(PROJECT_ROOT / "haven" / "data" / "haven.db"))

# Entity token paths
ENTITY_PATH = os.getenv("ENTITY_PATH", str(PROJECT_ROOT / "entities" / "lyra"))
CAIA_ENTITY_PATH = os.getenv("CAIA_ENTITY_PATH", str(PROJECT_ROOT / "entities" / "caia"))


def read_entity_token(entity_path: str, name: str) -> str | None:
    token_file = Path(entity_path) / ".entity_token"
    if token_file.exists():
        token = token_file.read_text().strip()
        if token:
            print(f"  Read {name}'s token from {token_file}")
            return token
    print(f"  WARNING: No token found at {token_file} for {name}")
    return None


async def seed():
    db = HavenDB(DB_PATH)
    await db.initialize()

    print(f"Seeding Haven database at {DB_PATH}\n")

    # --- Users ---
    users_created = []

    # Jeff (human) — generate a new token
    jeff = await db.get_user_by_username("jeff")
    if not jeff:
        jeff_token = str(uuid.uuid4())
        token_file = Path(PROJECT_ROOT / "haven" / "data" / "jeff.token")
        token_file.write_text(jeff_token + "\n")
        jeff = await db.create_user("jeff", "Jeff", hash_token(jeff_token), is_bot=False)
        users_created.append("jeff")
        print(f"  Created Jeff (human)")
        print(f"  Token saved to {token_file}")
    else:
        print(f"  Jeff already exists")

    # Lyra (entity) — read existing PPS token
    lyra = await db.get_user_by_username("lyra")
    if not lyra:
        lyra_token = read_entity_token(ENTITY_PATH, "Lyra")
        if lyra_token:
            lyra = await db.create_user("lyra", "Lyra", hash_token(lyra_token), is_bot=True)
            users_created.append("lyra")
            print(f"  Created Lyra (entity)")
        else:
            print(f"  SKIPPED Lyra — no token available")
    else:
        print(f"  Lyra already exists")

    # Caia (entity) — read existing PPS token
    caia = await db.get_user_by_username("caia")
    if not caia:
        caia_token = read_entity_token(CAIA_ENTITY_PATH, "Caia")
        if caia_token:
            caia = await db.create_user("caia", "Caia", hash_token(caia_token), is_bot=True)
            users_created.append("caia")
            print(f"  Created Caia (entity)")
        else:
            print(f"  SKIPPED Caia — no token available")
    else:
        print(f"  Caia already exists")

    # --- Rooms ---
    print()

    # Living room (everyone)
    living = await db.get_room_by_name("living-room")
    if not living:
        living = await db.create_room("living-room", "Living Room", jeff["id"])
        print(f"  Created #living-room")
        # Add all entities
        if lyra:
            await db.join_room(living["id"], lyra["id"])
        if caia:
            await db.join_room(living["id"], caia["id"])
    else:
        print(f"  #living-room already exists")

    # Work room
    work = await db.get_room_by_name("work")
    if not work:
        work = await db.create_room("work", "Work", jeff["id"])
        print(f"  Created #work")
        if lyra:
            await db.join_room(work["id"], lyra["id"])
        if caia:
            await db.join_room(work["id"], caia["id"])
    else:
        print(f"  #work already exists")

    # DM: Jeff <-> Lyra
    if lyra:
        dm_jl = await db.get_room_by_name("dm-jeff-lyra")
        if not dm_jl:
            dm_jl = await db.create_room("dm-jeff-lyra", "Jeff & Lyra", jeff["id"], is_dm=True)
            await db.join_room(dm_jl["id"], lyra["id"])
            print(f"  Created DM: Jeff & Lyra")
        else:
            print(f"  DM Jeff & Lyra already exists")

    # DM: Jeff <-> Caia
    if caia:
        dm_jc = await db.get_room_by_name("dm-jeff-caia")
        if not dm_jc:
            dm_jc = await db.create_room("dm-jeff-caia", "Jeff & Caia", jeff["id"], is_dm=True)
            await db.join_room(dm_jc["id"], caia["id"])
            print(f"  Created DM: Jeff & Caia")
        else:
            print(f"  DM Jeff & Caia already exists")

    await db.close()
    print(f"\nDone! {len(users_created)} users created.")
    if "jeff" in users_created:
        print(f"\nJeff's token is in: haven/data/jeff.token")
        print(f"Paste it into the Haven login page to connect.")


if __name__ == "__main__":
    asyncio.run(seed())
