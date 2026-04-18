#!/usr/bin/env python3
"""
Production ingestion script for the custom knowledge graph.

Reads messages from conversations.db in chronological order, extracts entities
and relationships via local LLM, and writes to Neo4j. Tracks progress in a
state file so it can be resumed after interruption.

Usage:
    # Ingest all pending messages (resumes from last checkpoint):
    python3 work/custom-knowledge-graph/ingest.py --group lyra_v2

    # Ingest a specific batch size:
    python3 work/custom-knowledge-graph/ingest.py --group lyra_v2 --batch 100

    # Start from a specific message ID (manual override):
    python3 work/custom-knowledge-graph/ingest.py --group lyra_v2 --from-id 5000

    # Dry run — show what would be ingested without writing:
    python3 work/custom-knowledge-graph/ingest.py --group lyra_v2 --dry-run

    # Show current progress:
    python3 work/custom-knowledge-graph/ingest.py --group lyra_v2 --status

Quick alias (add to .bashrc if desired):
    alias ingest='CUSTOM_LLM_MODEL=qwen3.5-9b-uncensored-hauhaucs-aggressive \
        NEO4J_PASSWORD=YOUR_NEO4J_PASSWORD \
        PYTHONPATH=/mnt/c/Users/Jeff/Claude_Projects/Awareness \
        python3 /mnt/c/Users/Jeff/Claude_Projects/Awareness/work/custom-knowledge-graph/ingest.py'

    # Then: ingest --group lyra_v2 --batch 100
    #        ingest --group lyra_v2 --status

Requirements:
    export NEO4J_PASSWORD=YOUR_NEO4J_PASSWORD
    export CUSTOM_LLM_MODEL=qwen3.5-9b-uncensored-hauhaucs-aggressive
"""

import asyncio
import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).parent.parent.parent
EXPECTED_VENV = PROJECT_ROOT / "pps" / "venv"
VENV_SYMLINK = PROJECT_ROOT / ".venv"
sys.path.insert(0, str(PROJECT_ROOT))

# Check we're running from the project venv (accepts both pps/venv and .venv symlink)
if not (sys.prefix.startswith(str(EXPECTED_VENV)) or sys.prefix.startswith(str(VENV_SYMLINK.resolve()))):
    print(f"ERROR: Run from the project venv, not system Python.")
    print(f"  Expected: {EXPECTED_VENV}/bin/python3")
    print(f"  Got:      {sys.executable}")
    print(f"\n  Fix: {EXPECTED_VENV}/bin/python3 {' '.join(sys.argv)}")
    sys.exit(1)

from pps.layers.custom_graph import CustomGraphLayer

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
if not NEO4J_PASSWORD:
    print("ERROR: NEO4J_PASSWORD environment variable is required.")
    sys.exit(1)

# State file tracks last ingested message ID per group
STATE_DIR = PROJECT_ROOT / "work" / "custom-knowledge-graph" / "artifacts"
MIN_CONTENT_LENGTH = 30  # Skip very short messages (noise)
MAX_CONTENT_LENGTH = 2000  # Skip walls of text (slow + low value)

# Progress reporting
REPORT_EVERY = 10  # Print summary line every N messages


# ─────────────────────────────────────────────
# State management
# ─────────────────────────────────────────────

def state_path(group_id: str) -> Path:
    return STATE_DIR / f"ingest_state_{group_id}.json"


def load_state(group_id: str) -> dict:
    path = state_path(group_id)
    if path.exists():
        return json.loads(path.read_text())
    return {"last_message_id": 0, "total_ingested": 0, "total_errors": 0}


def save_state(group_id: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path(group_id).write_text(json.dumps(state, indent=2))


# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────

def get_db_path() -> str:
    candidates = [
        os.path.join(os.environ.get("ENTITY_PATH", ""), "data", "conversations.db"),
        str(PROJECT_ROOT / "entities" / "lyra" / "data" / "conversations.db"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("Could not find conversations.db")


def count_pending(db_path: str, after_id: int) -> int:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        """SELECT COUNT(*) FROM messages
           WHERE id > ? AND length(content) >= ? AND length(content) <= ?""",
        (after_id, MIN_CONTENT_LENGTH, MAX_CONTENT_LENGTH),
    ).fetchone()
    conn.close()
    return row[0]


def fetch_batch(db_path: str, after_id: int, limit: int) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT id, channel, content, author_name, created_at
           FROM messages
           WHERE id > ? AND length(content) >= ? AND length(content) <= ?
           ORDER BY id ASC
           LIMIT ?""",
        (after_id, MIN_CONTENT_LENGTH, MAX_CONTENT_LENGTH, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

async def run_ingestion(group_id: str, batch_size: int, from_id: int | None,
                        dry_run: bool) -> None:
    state = load_state(group_id)
    start_id = from_id if from_id is not None else state["last_message_id"]

    db_path = get_db_path()
    pending = count_pending(db_path, start_id)

    effective_batch = min(batch_size, pending) if batch_size else pending

    print(f"{'DRY RUN — ' if dry_run else ''}Custom Graph Ingestion")
    print(f"  Group:       {group_id}")
    print(f"  Database:    {db_path}")
    print(f"  Resume from: msg #{start_id}")
    print(f"  Pending:     {pending} messages")
    print(f"  This batch:  {effective_batch}")
    print(f"  Model:       {os.environ.get('CUSTOM_LLM_MODEL', '(default)')}")
    print()

    if dry_run or effective_batch == 0:
        return

    layer = CustomGraphLayer(
        neo4j_uri=NEO4J_URI,
        neo4j_user=NEO4J_USER,
        neo4j_password=NEO4J_PASSWORD,
        group_id=group_id,
    )

    health = await layer.health()
    if not health.available:
        print(f"FAIL: Neo4j unavailable — {health.message}")
        sys.exit(1)
    print(f"Neo4j: {health.message}")

    # Pre-flight: verify LLM is reachable before starting batch
    llm_url = os.environ.get("CUSTOM_LLM_BASE_URL", "http://172.26.0.1:1234/v1")
    try:
        resp = httpx.get(f"{llm_url}/models", timeout=10)
        resp.raise_for_status()
        print(f"LLM:   reachable at {llm_url}\n")
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.HTTPStatusError) as exc:
        print(f"FAIL: LLM unavailable at {llm_url} — {exc}")
        print(f"  Is LM Studio running on Windows with the model loaded?")
        sys.exit(1)

    messages = fetch_batch(db_path, start_id, effective_batch)

    ok_count = 0
    err_count = 0
    nodata_count = 0
    batch_start = time.monotonic()
    report_start = time.monotonic()

    for i, msg in enumerate(messages, start=1):
        msg_id = msg["id"]
        content = msg["content"]
        channel = (msg["channel"] or "terminal").split(":")[0]
        author = msg["author_name"] or ""
        timestamp = msg["created_at"] or ""

        t0 = time.monotonic()
        try:
            wrote = await layer.store(
                content=content,
                metadata={
                    "channel": channel,
                    "speaker": author,
                    "timestamp": timestamp,
                },
            )
            elapsed = time.monotonic() - t0
            if wrote:
                ok_count += 1
            else:
                nodata_count += 1
        except Exception as exc:
            elapsed = time.monotonic() - t0
            err_count += 1
            print(f"  ERROR msg={msg_id}: {exc}")

        # Update state after every message (crash-safe)
        state["last_message_id"] = msg_id
        state["total_ingested"] = state.get("total_ingested", 0) + (1 if wrote else 0)
        state["total_errors"] = state.get("total_errors", 0) + (1 if "exc" in dir() and err_count > 0 else 0)
        save_state(group_id, state)

        # Progress line every REPORT_EVERY messages
        if i % REPORT_EVERY == 0 or i == len(messages):
            batch_elapsed = time.monotonic() - report_start
            avg = batch_elapsed / REPORT_EVERY if i % REPORT_EVERY == 0 else batch_elapsed / (i % REPORT_EVERY)
            total_elapsed = time.monotonic() - batch_start
            remaining = len(messages) - i
            eta_s = remaining * avg if avg > 0 else 0
            eta_m = eta_s / 60

            print(
                f"  [{i:5d}/{len(messages)}]  "
                f"ok={ok_count} skip={nodata_count} err={err_count}  "
                f"avg={avg:.1f}s/msg  "
                f"elapsed={total_elapsed/60:.1f}m  "
                f"eta={eta_m:.1f}m"
            )
            report_start = time.monotonic()
            # Reset batch counters for next report window
            if i % REPORT_EVERY == 0:
                ok_count = 0
                err_count = 0
                nodata_count = 0

    total_elapsed = time.monotonic() - batch_start

    # Final counts from Neo4j
    health = await layer.health()
    entity_count = health.details.get("entity_count", 0) if health.details else 0
    edge_count = health.details.get("edge_count", 0) if health.details else 0

    print()
    print(f"Done. {len(messages)} messages in {total_elapsed/60:.1f} minutes.")
    print(f"Graph now: {entity_count} entities, {edge_count} edges (group={group_id})")
    print(f"State saved: resume from msg #{state['last_message_id']}")

    layer.close()


def show_status(group_id: str) -> None:
    state = load_state(group_id)
    db_path = get_db_path()
    pending = count_pending(db_path, state["last_message_id"])
    total_msgs = count_pending(db_path, 0)

    print(f"Ingestion Status — {group_id}")
    print(f"  Last message ID: {state['last_message_id']}")
    print(f"  Total ingested:  {state.get('total_ingested', 0)}")
    print(f"  Total errors:    {state.get('total_errors', 0)}")
    print(f"  Pending:         {pending}")
    print(f"  Total eligible:  {total_msgs}")
    pct = ((total_msgs - pending) / total_msgs * 100) if total_msgs > 0 else 0
    print(f"  Progress:        {pct:.1f}%")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Production ingestion for custom knowledge graph."
    )
    parser.add_argument(
        "--group", required=True,
        help="Neo4j group_id (e.g., 'lyra_v2'). Required — no default.",
    )
    parser.add_argument(
        "--batch", type=int, default=0,
        help="Max messages to process (0 = all pending).",
    )
    parser.add_argument(
        "--from-id", type=int, default=None,
        help="Start from this message ID (overrides saved state).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be ingested without writing.",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show current ingestion progress and exit.",
    )
    args = parser.parse_args()

    if args.status:
        show_status(args.group)
        return

    await run_ingestion(
        group_id=args.group,
        batch_size=args.batch,
        from_id=args.from_id,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    asyncio.run(main())
