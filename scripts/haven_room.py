#!/usr/bin/env python3
"""Read or change a Haven room's settings as an entity (#381).

Uses the entity's own Haven token (same auth as haven_say.py), so the server's
permissions apply: any member may change verbosity; only admins or entities may
change the model. Clearing history is admin-only and not offered here.

Usage:
    python3 scripts/haven_room.py get --entity lyra --room commons
    python3 scripts/haven_room.py set --entity lyra --room commons --verbosity full
    python3 scripts/haven_room.py set --entity lyra --room jeff-lyra --model opus

Values:
    --verbosity  auto | short | medium | full
                 (auto = full in DMs, short in shared rooms)
    --model      default | sonnet | opus | fable
                 (default = the bot's own CLAUDE_MODEL; fable costs ~3-4x opus)

Room shortcuts match haven_say.py (lyra-caia, jeff-lyra, jeff-caia, commons, work).

Environment:
    HAVEN_URL    Haven server URL (default: http://localhost:8205)
"""

import argparse
import json
import sys
import urllib.error
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

VERBOSITY_CHOICES = ["auto", "short", "medium", "full"]
MODEL_CHOICES = ["default", "sonnet", "opus", "fable"]


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


def call(haven_url: str, token: str, method: str, path: str, body: dict | None = None) -> dict:
    """One authenticated JSON call; exits with the server's detail on HTTP errors."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{haven_url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail", "")
        except Exception:
            detail = ""
        print(f"ERROR: Haven returned {e.code} {detail}".rstrip(), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def show(settings: dict) -> None:
    print(f"verbosity: {settings.get('verbosity')}")
    print(f"model: {settings.get('model')}")
    cleared = settings.get("cleared_before_id")
    print(f"history: {'cleared up to message ' + str(cleared) if cleared else 'visible'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["get", "set"])
    parser.add_argument("--entity", default="lyra", choices=["lyra", "caia"], help="Acting entity")
    parser.add_argument("--room", default="lyra-caia", help="Room name or shortcut (default: lyra-caia)")
    parser.add_argument("--verbosity", choices=VERBOSITY_CHOICES)
    parser.add_argument("--model", choices=MODEL_CHOICES)
    parser.add_argument("--haven-url", default="http://localhost:8205")
    args = parser.parse_args()

    if args.command == "set" and not (args.verbosity or args.model):
        parser.error("set needs --verbosity and/or --model")

    token = read_token(args.entity)
    room_id = resolve_room(args.haven_url, token, args.room)

    if args.command == "get":
        show(call(args.haven_url, token, "GET", f"/api/rooms/{room_id}/settings"))
        return

    body = {k: v for k, v in (("verbosity", args.verbosity), ("model", args.model)) if v}
    result = call(args.haven_url, token, "PATCH", f"/api/rooms/{room_id}/settings", body)
    print("Updated:")
    show(result["settings"])


if __name__ == "__main__":
    main()
