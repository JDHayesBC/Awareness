#!/usr/bin/env python3
"""Backfill historical Haven messages into PPS.

Haven messages were not stored in PPS until 2026-03-16 when store_haven_message()
was added to haven/bot.py. This script reads all historical messages from Haven's
SQLite DB and stores them in PPS with channel="haven".

Run at a quiet time (low PPS load) since it will add many unsummarized messages.
After running, spawn a summarizer to process the backlog.

Usage:
    python3 scripts/backfill_haven_to_pps.py [--dry-run] [--entity lyra|caia]

Options:
    --dry-run    Print what would be stored without actually storing
    --entity     Which entity's PPS to store to (default: lyra)
    --since      Only backfill messages after this date (ISO format, e.g. 2026-03-10)
    --batch-size Number of messages per batch with a pause between (default: 50)
"""

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

ENTITY_PPS_PORTS = {
    "lyra": 8201,
    "caia": 8211,
}

ENTITY_TOKEN_PATHS = {
    "lyra": PROJECT_ROOT / "entities" / "lyra" / ".entity_token",
    "caia": PROJECT_ROOT / "entities" / "caia" / ".entity_token",
}

HAVEN_DB = PROJECT_ROOT / "haven" / "data" / "haven.db"

# Messages shorter than this are probably noise (warmup acks, etc.)
MIN_CONTENT_LENGTH = 20

# Known warmup messages to skip
SKIP_MESSAGES = {"ready", "warmed up", "warmed up.", "ready.", "connected"}


def read_token(entity: str) -> str:
    path = ENTITY_TOKEN_PATHS[entity]
    if not path.exists():
        print(f"ERROR: Token file not found: {path}")
        sys.exit(1)
    return path.read_text().strip()


def load_haven_messages(since: str | None) -> list[dict]:
    """Load all Haven messages with author info, newest-first."""
    db = sqlite3.connect(str(HAVEN_DB))
    db.row_factory = sqlite3.Row

    query = """
        SELECT
            m.id,
            m.room_id,
            m.content,
            m.created_at,
            u.username,
            u.display_name,
            u.is_bot,
            r.name as room_name,
            r.display_name as room_display_name
        FROM messages m
        JOIN users u ON m.user_id = u.id
        JOIN rooms r ON m.room_id = r.id
        WHERE 1=1
    """
    params = []
    if since:
        query += " AND m.created_at > ?"
        params.append(since)

    query += " ORDER BY m.created_at ASC"

    rows = db.execute(query, params).fetchall()
    db.close()
    return [dict(r) for r in rows]


def store_message(pps_url: str, token: str, msg: dict) -> bool:
    """Store one message in PPS. Returns True on success."""
    is_entity = msg["is_bot"] or msg["username"].lower() not in ("jeff",)
    payload = json.dumps({
        "content": msg["content"],
        "author_name": msg["display_name"],
        "channel": "haven",
        "is_lyra": bool(is_entity),
        "session_id": msg["room_id"],
        "token": token,
    }).encode()
    req = urllib.request.Request(
        f"{pps_url}/tools/store_message",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            return data.get("success", False)
    except Exception as e:
        print(f"  ERROR storing msg {msg['id']}: {e}")
        return False


def should_skip(msg: dict) -> bool:
    content = msg["content"].strip()
    if len(content) < MIN_CONTENT_LENGTH:
        return True
    if content.lower() in SKIP_MESSAGES:
        return True
    # Skip the bot's own warmup internal prompts (starts with [IDENTITY WARMUP])
    if content.startswith("[IDENTITY WARMUP]") or content.startswith("[ambient context]"):
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Don't actually store")
    parser.add_argument("--entity", default="lyra", choices=["lyra", "caia"])
    parser.add_argument("--since", default=None, help="Only messages after this ISO date")
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()

    entity = args.entity
    port = ENTITY_PPS_PORTS[entity]
    pps_url = f"http://localhost:{port}"
    token = read_token(entity)

    print(f"Haven → PPS backfill for {entity} (port {port})")
    if args.dry_run:
        print("DRY RUN — no messages will be stored")
    if args.since:
        print(f"Only messages since: {args.since}")
    print()

    messages = load_haven_messages(args.since)
    print(f"Loaded {len(messages)} Haven messages from SQLite")

    # Filter
    filtered = [m for m in messages if not should_skip(m)]
    skipped = len(messages) - len(filtered)
    print(f"Filtered to {len(filtered)} messages (skipped {skipped} trivial/warmup)")
    print()

    if not filtered:
        print("Nothing to backfill.")
        return

    # Preview first few
    print("Sample messages:")
    for m in filtered[:5]:
        ts = m["created_at"][:16]
        print(f"  [{ts}] {m['display_name']}: {m['content'][:80]}")
    print()

    if args.dry_run:
        print(f"Would store {len(filtered)} messages to {pps_url}")
        return

    confirm = input(f"Store {len(filtered)} messages to {entity}'s PPS? [y/N] ")
    if confirm.lower() != "y":
        print("Aborted.")
        return

    # Store in batches
    stored = 0
    failed = 0
    batch_size = args.batch_size

    for i in range(0, len(filtered), batch_size):
        batch = filtered[i:i + batch_size]
        print(f"Batch {i // batch_size + 1}: storing messages {i+1}–{i+len(batch)}...")

        for msg in batch:
            ok = store_message(pps_url, token, msg)
            if ok:
                stored += 1
            else:
                failed += 1

        # Brief pause between batches to avoid overwhelming PPS
        if i + batch_size < len(filtered):
            print(f"  Pausing 2s between batches...")
            time.sleep(2)

    print()
    print(f"Done: {stored} stored, {failed} failed out of {len(filtered)} messages")
    print()
    print("NOTE: Unsummarized count will be high after this.")
    print("Spawn a background summarizer to process the backlog:")
    print("  python3 -c \"import asyncio; ...\"  (or use the reflection daemon's summarization task)")


if __name__ == "__main__":
    main()
