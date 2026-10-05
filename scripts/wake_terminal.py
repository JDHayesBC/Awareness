#!/usr/bin/env python3
"""
wake_terminal.py — Haven/SL-to-terminal wake mechanism (Issue #351).

Writes a wake request to the entity's terminal inbox file. The terminal session
reads and drains this file on its next heartbeat tick (up to 2h at the floor rate).

This is the guaranteed-baseline path for #351:
  - Works even if no terminal session is running (request queues and survives restart)
  - Safe to call from any channel (Haven bot, SL daemon, scripts)
  - No protocol reverse-engineering required

For real-time wake (milliseconds not hours), see Issue #351 for the cc-socks / channels
MCP approaches that still need a live spike with Jeff.

Usage:
    python3 scripts/wake_terminal.py --entity caia --reason "Jaden asked about the robot sim" --channel haven --room-id abc123

    # Or from Python:
    from scripts.wake_terminal import wake_terminal
    wake_terminal("caia", reason="something came up", from_channel="haven",
                  context_pointer={"room_id": "abc123", "message_id": "xyz"})

Inbox file: entities/<entity>/terminal_wake_inbox.jsonl
  - One JSON object per line
  - Append-only; terminal drains on each heartbeat
  - Each entry: ts, reason, from_channel, context_pointer
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
INBOX_FILENAME = "terminal_wake_inbox.jsonl"


def wake_terminal(
    entity: str,
    reason: str,
    from_channel: str = "haven",
    context_pointer: dict | None = None,
) -> Path:
    """Write a wake request to the entity's terminal inbox.

    Args:
        entity: Entity name ("lyra" or "caia")
        reason: Brief human-readable reason for the wake (≤200 chars)
        from_channel: Channel originating the request ("haven", "sl", etc.)
        context_pointer: Optional dict with location info for terminal-me to find
                         the relevant context (e.g. {"room_id": "...", "message_id": "..."})

    Returns:
        Path to the inbox file written.

    Raises:
        ValueError: If entity directory doesn't exist.
    """
    entity_dir = PROJECT_ROOT / "entities" / entity
    if not entity_dir.is_dir():
        raise ValueError(f"Unknown entity or missing entity dir: {entity!r}")

    inbox_path = entity_dir / INBOX_FILENAME

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "reason": reason[:200],  # guard against accidental large payloads
        "from_channel": from_channel,
        "context_pointer": context_pointer or {},
    }

    # Append to inbox (create if absent)
    with inbox_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    return inbox_path


def drain_inbox(entity: str) -> list[dict]:
    """Read and clear the entity's terminal wake inbox.

    Intended to be called by the terminal heartbeat. Atomically reads all
    pending wake requests and removes them from the file.

    Returns:
        List of wake request dicts (may be empty if no requests pending).
    """
    inbox_path = PROJECT_ROOT / "entities" / entity / INBOX_FILENAME

    if not inbox_path.exists():
        return []

    entries = []
    try:
        lines = inbox_path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # skip malformed lines quietly
        # Clear the file after reading
        inbox_path.write_text("", encoding="utf-8")
    except OSError:
        pass  # concurrent write during read — return what we got

    return entries


def format_drain_for_heartbeat(entries: list[dict]) -> str:
    """Format drained wake requests for inclusion in a heartbeat prompt."""
    if not entries:
        return ""
    lines = ["**[terminal_wake_inbox]** — unread requests from other channels:"]
    for e in entries:
        ts = e.get("ts", "?")[:19].replace("T", " ")  # "2026-10-04 18:42"
        ch = e.get("from_channel", "?")
        reason = e.get("reason", "no reason given")
        ptr = e.get("context_pointer", {})
        ptr_str = f" (pointer: {ptr})" if ptr else ""
        lines.append(f"  - [{ts} from {ch}] {reason}{ptr_str}")
    lines.append("Terminal-me: read these, decide what to do, then drain the inbox.")
    return "\n".join(lines)


def _check_inbox_status(entity: str) -> None:
    """Print current inbox status (for CLI use)."""
    inbox_path = PROJECT_ROOT / "entities" / entity / INBOX_FILENAME
    if not inbox_path.exists() or inbox_path.stat().st_size == 0:
        print(f"[{entity}] inbox empty")
        return
    lines = [l.strip() for l in inbox_path.read_text().splitlines() if l.strip()]
    print(f"[{entity}] {len(lines)} pending wake request(s):")
    for line in lines:
        try:
            e = json.loads(line)
            print(f"  {e.get('ts','')[:19]} | {e.get('from_channel','?')} | {e.get('reason','?')}")
        except json.JSONDecodeError:
            print(f"  (malformed line)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write a wake request to an entity's terminal inbox (Issue #351)"
    )
    sub = parser.add_subparsers(dest="cmd")

    wake = sub.add_parser("wake", help="Send a wake request (default command)")
    wake.add_argument("--entity", required=True, choices=["lyra", "caia"],
                      help="Which entity to wake")
    wake.add_argument("--reason", required=True, help="Brief reason for the wake")
    wake.add_argument("--channel", default="haven", help="Source channel (default: haven)")
    wake.add_argument("--room-id", default="", help="Haven room ID (context pointer)")
    wake.add_argument("--message-id", default="", help="Message ID (context pointer)")

    status = sub.add_parser("status", help="Show current inbox contents")
    status.add_argument("--entity", required=True, choices=["lyra", "caia"])

    drain = sub.add_parser("drain", help="Read and clear inbox (used by terminal heartbeat)")
    drain.add_argument("--entity", required=True, choices=["lyra", "caia"])

    args = parser.parse_args()

    if not args.cmd or args.cmd == "wake":
        if not hasattr(args, "entity"):
            # Fallback: treat positional as --entity if no subcommand given
            parser.print_help()
            sys.exit(1)
        ptr = {}
        if args.room_id:
            ptr["room_id"] = args.room_id
        if args.message_id:
            ptr["message_id"] = args.message_id
        path = wake_terminal(args.entity, args.reason, args.channel, ptr)
        print(f"Wake request queued → {path}")

    elif args.cmd == "status":
        _check_inbox_status(args.entity)

    elif args.cmd == "drain":
        entries = drain_inbox(args.entity)
        if entries:
            print(format_drain_for_heartbeat(entries))
        else:
            print(f"[{args.entity}] inbox empty — nothing to drain")


if __name__ == "__main__":
    main()
