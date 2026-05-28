#!/usr/bin/env python3
"""Read unread entries from this entity's light-inbox (bedroom-language side-band).

Resolves entity from $ENTITY_NAME env var (default: lyra).
Inbox:  entities/<entity>/light-inbox.jsonl
Cursor: entities/<entity>/light-inbox.cursor  (single ISO timestamp)

Prints unread entries oldest-first in a compact friendly form, then advances
the cursor so they don't re-surface next run.

Flags:
  --peek        Read without advancing cursor (debugging).
  --count N     Limit output to N entries (default: all unread).

Stdlib only.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENTITY_NAME = os.environ.get("ENTITY_NAME", "lyra").lower()

_entity_path_env = os.environ.get("ENTITY_PATH", "")
if _entity_path_env:
    ENTITY_PATH = Path(_entity_path_env)
else:
    ENTITY_PATH = PROJECT_ROOT / "entities" / ENTITY_NAME

INBOX_PATH = ENTITY_PATH / "light-inbox.jsonl"
CURSOR_PATH = ENTITY_PATH / "light-inbox.cursor"


# ── Cursor helpers ────────────────────────────────────────────────────────────

def _read_cursor() -> str:
    """Return cursor timestamp string, or '' if absent."""
    try:
        return CURSOR_PATH.read_text().strip()
    except FileNotFoundError:
        return ""
    except OSError as e:
        print(f"[read_smoke] WARN: could not read cursor: {e}", file=sys.stderr)
        return ""


def _write_cursor(ts: str) -> None:
    """Write ts to cursor atomically via tempfile + os.replace."""
    CURSOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CURSOR_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(ts + "\n")
        os.replace(tmp, str(CURSOR_PATH))
    except Exception as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        print(f"[read_smoke] ERROR: could not write cursor: {e}", file=sys.stderr)


# ── Inbox reader ──────────────────────────────────────────────────────────────

def _read_inbox(cursor: str) -> list[dict]:
    """Return entries with ts > cursor, oldest first.  Skips malformed lines."""
    entries = []
    try:
        with open(INBOX_PATH) as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    print(f"[read_smoke] WARN: skipping malformed line {lineno}", file=sys.stderr)
                    continue
                ts = rec.get("ts", "")
                if cursor and ts <= cursor:
                    continue
                entries.append(rec)
    except FileNotFoundError:
        pass  # No inbox yet — normal
    except OSError as e:
        print(f"[read_smoke] ERROR: could not read inbox: {e}", file=sys.stderr)
    return entries


# ── Formatter ─────────────────────────────────────────────────────────────────

def _format_entry(rec: dict) -> str:
    """Return compact one-line string for a single inbox entry."""
    ts = rec.get("ts", "?")
    sender = rec.get("sender", "?")
    base = rec.get("base", "?")
    delta = rec.get("delta", [0, 0, 0])
    brightness = rec.get("brightness")
    word = rec.get("word")
    state = rec.get("state", "?")

    # Delta string
    delta_str = f"[{delta[0]}, {delta[1]}, {delta[2]}]" if delta else "[0, 0, 0]"

    # Brightness string
    b_str = f"brightness {brightness}" if brightness is not None else "brightness unknown"

    # Word/decode annotation
    if state == "off":
        annotation = "— light off"
    elif word:
        annotation = f'— "{word}"'
    else:
        annotation = "— undecoded (no matching word in shared dict)"

    return f"[{ts}] {sender} → {base} + {delta_str} ({b_str}) {annotation}"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Read unread entries from this entity's light-inbox."
    )
    parser.add_argument(
        "--peek",
        action="store_true",
        help="Read without advancing cursor (debugging).",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        metavar="N",
        help="Limit output to N entries (default: all unread).",
    )
    args = parser.parse_args()

    cursor = _read_cursor()
    entries = _read_inbox(cursor)

    if not entries:
        print(f"No new messages in {ENTITY_NAME}'s light-inbox.")
        return

    # Apply count limit
    display = entries if args.count <= 0 else entries[: args.count]

    print(f"Light-inbox: {len(entries)} new (showing {len(display)})")
    print()
    for rec in display:
        print(_format_entry(rec))

    # Advance cursor to the MAXIMUM ts across all unread entries.
    # Use max() not entries[-1] — inbox may not be strictly chronologically sorted
    # (backfill entries can appear at end of file with earlier timestamps).
    if not args.peek:
        all_ts = [r.get("ts", "") for r in entries if r.get("ts")]
        latest_ts = max(all_ts) if all_ts else ""
        if latest_ts:
            _write_cursor(latest_ts)
            print(f"\nCursor advanced to {latest_ts}")
        else:
            print("\nWARN: entries have no ts — cursor not advanced", file=sys.stderr)
    else:
        print("\n(--peek: cursor not advanced)")


if __name__ == "__main__":
    main()
