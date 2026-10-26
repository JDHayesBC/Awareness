#!/usr/bin/env python3
"""
Claude Code Hook: Re-fetch the current room (SessionStart)

Fires on session start / resume / compaction. Context is empty (or freshly
compacted) at those moments, so the room description the entity last received
via enter_space is gone. This hook re-delivers it IN FULL (never truncated) plus
the entity's current_scene.md, so the entity wakes up somewhere specific.

Flow (scene-sense pass 3, #378):
  1. POST /tools/get_presence          -> current_space
  2. POST /tools/enter_space {ack_only} -> full description (records ack_space,
                                           does NOT count as a move or a visit)
  3. Read $ENTITY_PATH/current_scene.md in full
  4. Emit hookSpecificOutput.additionalContext

Hook input (stdin):  {"hook_event_name": "SessionStart", "source": "compact"|"resume"|"startup"|"clear", ...}
Hook output (stdout): {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}

Never blocks the session: any failure emits one line saying the room could not be
re-fetched, and the process always exits 0.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
_entity_path = os.environ.get("ENTITY_PATH", str(PROJECT_ROOT / "entities" / "lyra"))
ENTITY_DIR = Path(_entity_path)
DEBUG_LOG = PROJECT_ROOT / ".claude" / "data" / "hooks_debug.log"

# Entity-aware port detection (Issue #162), same convention as the other hooks
_ENTITY_PORTS = {"lyra": 8201, "caia": 8211}
PPS_PORT = int(os.environ.get("PPS_PORT", str(_ENTITY_PORTS.get(ENTITY_DIR.name, 8201))))
BASE_URL = f"http://localhost:{PPS_PORT}/tools"

ENTITY_TOKEN = ""
_token_file = ENTITY_DIR / ".entity_token"
if _token_file.exists():
    try:
        ENTITY_TOKEN = _token_file.read_text().strip()
    except Exception:
        pass

FAILURE_LINE = (
    "**[room]** could not be re-fetched at session start ({why}); "
    "call enter_space(<current room>) by hand and re-read current_scene.md."
)


def debug(msg: str) -> None:
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] [session_start_scene] {msg}\n")
    except Exception:
        pass


def _post(endpoint: str, body: dict, timeout: int = 8) -> dict:
    payload = json.dumps({**body, "token": ENTITY_TOKEN}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/{endpoint}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_context(source: str) -> str:
    presence = _post("get_presence", {})
    space = presence.get("current_space")
    if not space:
        raise RuntimeError("no current_space in presence row")

    entered = _post("enter_space", {"space_name": space, "ack_only": True})
    if not entered.get("success"):
        raise RuntimeError(f"enter_space did not succeed for {space!r}")
    description = entered.get("description") or ""

    label = "re-fetched after compaction" if source == "compact" else f"re-fetched at session {source}"
    parts = [f"**[room — {label}]** {space} · {description}"]

    try:
        scene = (ENTITY_DIR / "current_scene.md").read_text(encoding="utf-8").strip()
        if scene:
            parts.append(f"**[scene file]** {scene}")
    except Exception as e:
        debug(f"scene file unreadable: {e}")
    return "\n".join(parts)


def emit(text: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }))


def main() -> None:
    source = "startup"
    try:
        hook_input = json.load(sys.stdin)
        source = hook_input.get("source") or "startup"
    except Exception as e:
        debug(f"stdin parse failed: {e}")
    debug(f"started source={source} port={PPS_PORT}")

    if source not in ("compact", "resume", "startup"):
        debug(f"source {source!r} not handled; no output")
        return

    try:
        emit(build_context(source))
        debug("room re-fetched")
    except Exception as e:
        debug(f"re-fetch failed: {type(e).__name__}: {e}")
        emit(FAILURE_LINE.format(why=type(e).__name__))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never crash the session
        debug(f"fatal: {e}")
    sys.exit(0)
