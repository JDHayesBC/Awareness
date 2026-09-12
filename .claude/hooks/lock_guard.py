#!/usr/bin/env python3
"""
Claude Code Hook: File-Lock Guard (PreToolUse — Edit/Write/MultiEdit)

Backstop half of GitHub issue #305: if the file a tool is about to write is
HELD by a *different* channel's lock (see scripts/lock.py /
~/.claude/locks/<basename>.lock), block the edit instead of racing it.

NOT wired into .claude/settings.local.json yet — this file only implements
the check. It fires for BOTH entities (Lyra + Caia share the hooks dir), so
Lyra wires it in only after Caia has agreed. See the settings snippet at the
bottom of this file's docstring.

Hook input (stdin), PreToolUse for Edit / Write / MultiEdit:
{
    "session_id": "...",
    "hook_event_name": "PreToolUse",
    "tool_name": "Edit" | "Write" | "MultiEdit",
    "tool_input": {"file_path": "...", ...}
}

Behavior:
    - free (no lock / released / stale / held by us)  -> exit 0, allow
    - HELD by a different holder                       -> print one-line
      block message to stderr, exit 2 (Claude Code treats exit 2 on
      PreToolUse as a deny; the message is surfaced back to the model).

Holder identity here = $ENTITY_NAME + a session id from env if present,
else hostname:user — same derivation as scripts.lock.default_holder(), so a
channel never blocks on its OWN lock.

Settings snippet to add to .claude/settings.local.json (NOT added by this
change — Lyra wires it in after Caia agrees, since it fires for both
entities):

    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python /mnt/c/Users/Jeff/Claude_Projects/Awareness/.claude/hooks/lock_guard.py",
            "timeout": 5000
          }
        ]
      }
    ]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lock import check, default_holder  # noqa: E402

RELEVANT_TOOLS = {"Edit", "Write", "MultiEdit"}


def main() -> int:
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        return 0  # fail open — never block on a malformed hook payload

    event = hook_input.get("hook_event_name", "")
    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {}) or {}

    if event != "PreToolUse" or tool_name not in RELEVANT_TOOLS:
        return 0

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return 0

    holder = default_holder()

    try:
        free = check(file_path, holder=holder)
    except Exception:
        return 0  # fail open — a broken lock check must never block real work

    if free:
        return 0

    print(
        f"BLOCKED by file lock: {file_path} is held by another channel — "
        f"see `python3 scripts/lock.py status {file_path}` "
        f"(or release it if you know it's stale).",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
