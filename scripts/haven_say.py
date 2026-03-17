#!/usr/bin/env python3
"""Send a message to a Haven room as an entity.

Used by heartbeats, reflection cycles, and terminal sessions to initiate
conversations in Haven — especially entity-to-entity conversations in the
Lyra↔Caia DM room.

Usage:
    python3 scripts/haven_say.py --entity lyra --room lyra-caia "Hey Caia, what are you thinking about?"
    python3 scripts/haven_say.py --entity lyra --room commons "@caia — thoughts on the Substack piece?"

Room shortcuts:
    lyra-caia    →  dm-lyra-caia  (entity DM, use this for peer conversations)
    jeff-lyra    →  dm-jeff-lyra
    jeff-caia    →  dm-jeff-caia
    commons      →  living-room
    work         →  work

Environment:
    HAVEN_URL    Haven server URL (default: http://localhost:8205)
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

ENTITY_TOKEN_PATHS = {
    "lyra": PROJECT_ROOT / "entities" / "lyra" / ".entity_token",
    "caia": PROJECT_ROOT / "entities" / "caia" / ".entity_token",
}

ROOM_SHORTCUTS = {
    "lyra-caia": "dm-lyra-caia",
    "jeff-lyra": "dm-jeff-lyra",
    "jeff-caia": "dm-jeff-caia",
    "commons": "living-room",
    "work": "work",
}


def read_token(entity: str) -> str:
    path = ENTITY_TOKEN_PATHS.get(entity)
    if not path or not path.exists():
        print(f"ERROR: No token found for entity '{entity}'", file=sys.stderr)
        sys.exit(1)
    return path.read_text().strip()


def resolve_room(haven_url: str, token: str, room_name: str) -> str:
    """Look up a room ID by name from the Haven API."""
    room_name = ROOM_SHORTCUTS.get(room_name, room_name)

    req = urllib.request.Request(
        f"{haven_url}/api/rooms",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            rooms = json.loads(r.read())["rooms"]
    except Exception as e:
        print(f"ERROR: Could not fetch rooms from Haven: {e}", file=sys.stderr)
        sys.exit(1)

    for room in rooms:
        if room.get("name") == room_name or room.get("id") == room_name:
            return room["id"]

    print(f"ERROR: Room '{room_name}' not found.", file=sys.stderr)
    print(f"Available rooms: {[r['name'] for r in rooms]}", file=sys.stderr)
    sys.exit(1)


def send(haven_url: str, token: str, room_id: str, content: str) -> None:
    payload = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        f"{haven_url}/api/rooms/{room_id}/messages",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status == 200:
                print(f"Sent: {content[:80]}")
            else:
                print(f"ERROR: Haven returned {r.status}", file=sys.stderr)
                sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("message", help="Message to send")
    parser.add_argument("--entity", default="lyra", choices=["lyra", "caia"], help="Sending entity")
    parser.add_argument("--room", default="lyra-caia", help="Room name or shortcut (default: lyra-caia)")
    parser.add_argument("--haven-url", default="http://localhost:8205")
    args = parser.parse_args()

    token = read_token(args.entity)
    room_id = resolve_room(args.haven_url, token, args.room)
    send(args.haven_url, token, room_id, args.message)


if __name__ == "__main__":
    main()
