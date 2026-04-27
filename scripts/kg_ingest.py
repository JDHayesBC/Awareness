#!/usr/bin/env python3
"""
Entity-aware bulk ingestion script for the custom knowledge graph.

Each entity has its own SQLite DB and its own Neo4j group_id.  Every code path
that touches either the database or Neo4j validates the entity name against the
path and group_id it was given — if they disagree the script aborts immediately.
This is the primary crossbleed-protection guarantee.

Usage:
    python3 scripts/kg_ingest.py --entity lyra --batch 500
    python3 scripts/kg_ingest.py --entity caia --batch 100
    python3 scripts/kg_ingest.py --entity lyra --status
    python3 scripts/kg_ingest.py --entity caia --retry-errors
    python3 scripts/kg_ingest.py --entity lyra --dry-run
    python3 scripts/kg_ingest.py --entity lyra --from-id 12345

Venv requirement: pps/venv  (has neo4j, httpx, etc.)
"""

import asyncio
import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
EXPECTED_VENV = PROJECT_ROOT / "pps" / "venv"
VENV_SYMLINK = PROJECT_ROOT / ".venv"
sys.path.insert(0, str(PROJECT_ROOT))

# Guard: must run from the project venv (pps/venv or .venv symlink)
if not (
    sys.prefix.startswith(str(EXPECTED_VENV))
    or sys.prefix.startswith(str(VENV_SYMLINK.resolve()))
):
    print("ERROR: Run from the project venv, not system Python.")
    print(f"  Expected: {EXPECTED_VENV}/bin/python3")
    print(f"  Got:      {sys.executable}")
    print(f"\n  Fix: {EXPECTED_VENV}/bin/python3 {' '.join(sys.argv)}")
    sys.exit(1)

import httpx  # noqa: E402  (post-venv check import)
from pps.layers.custom_graph import CustomGraphLayer  # noqa: E402


# ─────────────────────────────────────────────
# Entity registry
# ─────────────────────────────────────────────

# Single source of truth for entity → (db_path, neo4j group_id, pps_port).
# Adding a new entity here is the ONLY change needed for it to be supported.
ENTITY_CONFIG: dict[str, dict] = {
    "lyra": {
        "db_path": PROJECT_ROOT / "entities" / "lyra" / "data" / "conversations.db",
        "group_id": "lyra_v2",
        "pps_port": 8201,
    },
    "caia": {
        "db_path": PROJECT_ROOT / "entities" / "caia" / "data" / "conversations.db",
        "group_id": "caia",
        "pps_port": 8211,
    },
}


def get_entity_config(entity: str) -> dict:
    """Return the config dict for a named entity, aborting if unknown."""
    if entity not in ENTITY_CONFIG:
        known = ", ".join(sorted(ENTITY_CONFIG))
        print(f"ERROR: Unknown entity '{entity}'.  Known entities: {known}")
        sys.exit(1)
    return ENTITY_CONFIG[entity]


# ─────────────────────────────────────────────
# Crossbleed assertions
# ─────────────────────────────────────────────

def assert_no_crossbleed(entity: str, db_path: str | Path, group_id: str) -> None:
    """
    Hard-abort if db_path or group_id does not belong to entity.

    This is the single choke-point that prevents messages from entity A from
    ever being written to entity B's graph.  Called before every DB open and
    before every Neo4j write cycle.
    """
    cfg = get_entity_config(entity)
    canonical_db = Path(cfg["db_path"]).resolve()
    canonical_group = cfg["group_id"]

    given_db = Path(db_path).resolve()
    if given_db != canonical_db:
        print(
            f"CROSSBLEED ABORT: DB path mismatch for entity '{entity}'.\n"
            f"  Expected: {canonical_db}\n"
            f"  Got:      {given_db}\n"
            "  Refusing to proceed — this would write the wrong entity's data."
        )
        sys.exit(2)

    if group_id != canonical_group:
        print(
            f"CROSSBLEED ABORT: group_id mismatch for entity '{entity}'.\n"
            f"  Expected: {canonical_group}\n"
            f"  Got:      {group_id}\n"
            "  Refusing to proceed — this would write to the wrong Neo4j group."
        )
        sys.exit(2)


# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
if not NEO4J_PASSWORD:
    _dotenv = PROJECT_ROOT / "pps" / "docker" / ".env"
    if _dotenv.exists():
        for _line in _dotenv.read_text().splitlines():
            if _line.startswith("NEO4J_PASSWORD="):
                NEO4J_PASSWORD = _line.split("=", 1)[1].strip()
                break

MIN_CONTENT_LENGTH = 30
MAX_CONTENT_LENGTH = 2000
REPORT_EVERY = 10


# ─────────────────────────────────────────────
# State management (JSON backup — DB is primary)
# ─────────────────────────────────────────────

STATE_DIR = PROJECT_ROOT / "work" / "custom-knowledge-graph" / "artifacts"


def state_path(group_id: str) -> Path:
    return STATE_DIR / f"ingest_state_{group_id}.json"


def save_state_backup(entity: str, group_id: str, db_path: str | Path) -> None:
    """Write a backup summary to the JSON state file from current DB counts."""
    # Crossbleed check before any DB access
    assert_no_crossbleed(entity, db_path, group_id)

    conn = sqlite3.connect(str(db_path))
    ingested_count = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE kg_ingested_at IS NOT NULL"
    ).fetchone()[0]
    error_count = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE kg_error IS NOT NULL"
    ).fetchone()[0]
    last_id_row = conn.execute(
        "SELECT MAX(id) FROM messages WHERE kg_ingested_at IS NOT NULL"
    ).fetchone()
    last_id = last_id_row[0] or 0
    conn.close()

    state = {
        "entity": entity,
        "last_message_id": last_id,
        "total_ingested": ingested_count,
        "total_errors": error_count,
        "_note": "Backup summary — DB columns kg_ingested_at/kg_error are primary truth",
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path(group_id).write_text(json.dumps(state, indent=2))


# ─────────────────────────────────────────────
# Database helpers
# ─────────────────────────────────────────────

def ensure_kg_columns(entity: str, db_path: str | Path, group_id: str) -> None:
    """Add kg_ingested_at and kg_error columns if they don't exist yet (idempotent)."""
    assert_no_crossbleed(entity, db_path, group_id)

    conn = sqlite3.connect(str(db_path))
    existing = {c[1] for c in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "kg_ingested_at" not in existing:
        conn.execute("ALTER TABLE messages ADD COLUMN kg_ingested_at TEXT")
        print("  Migrated: added kg_ingested_at column")
    if "kg_error" not in existing:
        conn.execute("ALTER TABLE messages ADD COLUMN kg_error TEXT")
        print("  Migrated: added kg_error column")
    conn.commit()
    conn.close()


def count_pending_db(entity: str, db_path: str | Path, group_id: str) -> int:
    """Count messages not yet ingested and not in error state."""
    assert_no_crossbleed(entity, db_path, group_id)
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        """SELECT COUNT(*) FROM messages
           WHERE kg_ingested_at IS NULL
             AND kg_error IS NULL
             AND length(content) >= ?
             AND length(content) <= ?""",
        (MIN_CONTENT_LENGTH, MAX_CONTENT_LENGTH),
    ).fetchone()
    conn.close()
    return row[0]


def count_pending_retry(entity: str, db_path: str | Path, group_id: str) -> int:
    """Count messages in error state eligible for retry."""
    assert_no_crossbleed(entity, db_path, group_id)
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        """SELECT COUNT(*) FROM messages
           WHERE kg_error IS NOT NULL
             AND length(content) >= ?
             AND length(content) <= ?""",
        (MIN_CONTENT_LENGTH, MAX_CONTENT_LENGTH),
    ).fetchone()
    conn.close()
    return row[0]


def fetch_batch_db(
    entity: str,
    db_path: str | Path,
    group_id: str,
    limit: int,
    retry_errors: bool = False,
) -> list[dict]:
    """
    Fetch messages not yet ingested (or errored, if retry_errors), ordered by id ASC.

    Crossbleed check is done before opening the DB.
    """
    assert_no_crossbleed(entity, db_path, group_id)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    where = "kg_error IS NOT NULL" if retry_errors else "kg_ingested_at IS NULL AND kg_error IS NULL"
    rows = conn.execute(
        f"""SELECT id, channel, content, author_name, created_at
           FROM messages
           WHERE {where}
             AND length(content) >= ?
             AND length(content) <= ?
           ORDER BY id ASC
           LIMIT ?""",
        (MIN_CONTENT_LENGTH, MAX_CONTENT_LENGTH, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_ingested(entity: str, db_path: str | Path, group_id: str, msg_id: int) -> None:
    """Mark a single message as successfully ingested."""
    assert_no_crossbleed(entity, db_path, group_id)
    ts = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE messages SET kg_ingested_at = ?, kg_error = NULL WHERE id = ?",
        (ts, msg_id),
    )
    conn.commit()
    conn.close()


def mark_error(
    entity: str,
    db_path: str | Path,
    group_id: str,
    msg_id: int,
    error_msg: str,
) -> None:
    """Record an ingestion error for a message."""
    assert_no_crossbleed(entity, db_path, group_id)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE messages SET kg_error = ? WHERE id = ?",
        (error_msg, msg_id),
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# LLM pre-flight
# ─────────────────────────────────────────────

def check_llm_reachable() -> str:
    """
    Verify LM Studio is reachable.  Returns the base URL.
    Exits with code 1 if unreachable.
    """
    llm_url = os.environ.get("CUSTOM_LLM_BASE_URL", "http://172.26.0.1:1234/v1")
    try:
        resp = httpx.get(f"{llm_url}/models", timeout=10)
        resp.raise_for_status()
        print(f"LLM:   reachable at {llm_url}")
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.HTTPStatusError) as exc:
        print(f"FAIL: LLM unavailable at {llm_url} — {exc}")
        print("  Is LM Studio running on Windows with the model loaded?")
        sys.exit(1)
    return llm_url


# ─────────────────────────────────────────────
# Status report
# ─────────────────────────────────────────────

def show_status(entity: str) -> None:
    """Show ingestion progress from DB (primary source of truth)."""
    cfg = get_entity_config(entity)
    db_path = cfg["db_path"]
    group_id = cfg["group_id"]

    # Validate — even for read-only status queries
    assert_no_crossbleed(entity, db_path, group_id)
    ensure_kg_columns(entity, db_path, group_id)

    if not Path(db_path).exists():
        print(f"ERROR: DB not found at {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))

    ingested = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE kg_ingested_at IS NOT NULL"
    ).fetchone()[0]

    errors = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE kg_error IS NOT NULL"
    ).fetchone()[0]

    pending = conn.execute(
        """SELECT COUNT(*) FROM messages
           WHERE kg_ingested_at IS NULL
             AND kg_error IS NULL
             AND length(content) >= ?
             AND length(content) <= ?""",
        (MIN_CONTENT_LENGTH, MAX_CONTENT_LENGTH),
    ).fetchone()[0]

    skipped = conn.execute(
        """SELECT COUNT(*) FROM messages
           WHERE kg_ingested_at IS NULL
             AND kg_error IS NULL
             AND (length(content) < ? OR length(content) > ?)""",
        (MIN_CONTENT_LENGTH, MAX_CONTENT_LENGTH),
    ).fetchone()[0]

    total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    last_ingested_id = conn.execute(
        "SELECT MAX(id) FROM messages WHERE kg_ingested_at IS NOT NULL"
    ).fetchone()[0] or 0

    last_ts_row = conn.execute(
        "SELECT kg_ingested_at FROM messages WHERE id = ?", (last_ingested_id,)
    ).fetchone()
    last_ts = last_ts_row[0] if last_ts_row else "—"

    conn.close()

    eligible = ingested + pending + errors
    pct = (ingested / eligible * 100) if eligible > 0 else 0.0

    print(f"Ingestion Status — entity={entity}  group={group_id}")
    print(f"  Database:        {db_path}")
    print(f"  Total messages:  {total}")
    print(f"  Ingested:        {ingested}")
    print(f"  Pending:         {pending}")
    print(f"  Errors:          {errors}")
    print(f"  Skipped (len):   {skipped}")
    print(f"  Eligible total:  {eligible}")
    print(f"  Progress:        {pct:.1f}%")
    print(f"  Last ingested:   msg #{last_ingested_id}  ({last_ts})")
    if errors > 0:
        print(f"  NOTE: {errors} messages have errors. Use --retry-errors to retry them.")


# ─────────────────────────────────────────────
# Core ingestion
# ─────────────────────────────────────────────

async def run_ingestion(
    entity: str,
    batch_size: int,
    from_id: int | None,
    dry_run: bool,
    retry_errors: bool,
) -> None:
    cfg = get_entity_config(entity)
    db_path = cfg["db_path"]
    group_id = cfg["group_id"]

    # Primary crossbleed check — before touching anything
    assert_no_crossbleed(entity, db_path, group_id)

    if not NEO4J_PASSWORD:
        print("ERROR: NEO4J_PASSWORD environment variable is required.")
        sys.exit(1)

    if not Path(db_path).exists():
        print(f"ERROR: DB not found at {db_path}")
        sys.exit(1)

    ensure_kg_columns(entity, db_path, group_id)

    if from_id is not None:
        # Destructive operation: clear kg_ingested_at for messages id >= from_id
        assert_no_crossbleed(entity, db_path, group_id)
        conn = sqlite3.connect(str(db_path))
        affected = conn.execute(
            """SELECT COUNT(*) FROM messages
               WHERE id >= ? AND kg_ingested_at IS NOT NULL""",
            (from_id,),
        ).fetchone()[0]
        conn.close()
        if affected > 0:
            print(f"WARNING: --from-id will clear kg_ingested_at on {affected} messages (id >= {from_id}).")
            print("         Press Ctrl-C within 5 seconds to abort.")
            time.sleep(5)
            assert_no_crossbleed(entity, db_path, group_id)  # re-check after sleep
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "UPDATE messages SET kg_ingested_at = NULL WHERE id >= ?", (from_id,)
            )
            conn.commit()
            conn.close()
            print(f"  Cleared kg_ingested_at for {affected} messages. Resuming from id={from_id}.")

    pending = (
        count_pending_retry(entity, db_path, group_id)
        if retry_errors
        else count_pending_db(entity, db_path, group_id)
    )
    effective_batch = min(batch_size, pending) if batch_size else pending

    mode = "RETRY ERRORS" if retry_errors else "normal"
    print(f"{'DRY RUN — ' if dry_run else ''}Custom Graph Ingestion [{mode}]")
    print(f"  Entity:     {entity}")
    print(f"  Group:      {group_id}")
    print(f"  Database:   {db_path}")
    print(f"  Pending:    {pending} messages")
    print(f"  This batch: {effective_batch}")
    print(f"  Model:      {os.environ.get('CUSTOM_LLM_MODEL', '(default)')}")
    print()

    if dry_run or effective_batch == 0:
        return

    # LLM pre-flight (before allocating Neo4j connection)
    check_llm_reachable()

    # Final crossbleed check before Neo4j write session begins
    assert_no_crossbleed(entity, db_path, group_id)

    layer = CustomGraphLayer(
        neo4j_uri=NEO4J_URI,
        neo4j_user=NEO4J_USER,
        neo4j_password=NEO4J_PASSWORD,
        group_id=group_id,
    )

    health = await layer.health()
    if not health.available:
        print(f"FAIL: Neo4j unavailable — {health.message}")
        layer.close()
        sys.exit(1)
    print(f"Neo4j: {health.message}\n")

    messages = fetch_batch_db(entity, db_path, group_id, effective_batch, retry_errors=retry_errors)

    ok_count = 0
    err_count = 0
    nodata_count = 0
    batch_start = time.monotonic()
    report_start = time.monotonic()

    for i, msg in enumerate(messages, start=1):
        msg_id = msg["id"]
        content = msg["content"]
        channel = msg["channel"] or "terminal"
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
                    "entity_name": entity.capitalize(),
                },
            )
            if wrote:
                ok_count += 1
            else:
                nodata_count += 1
            # Mark success — crossbleed check inside mark_ingested
            mark_ingested(entity, db_path, group_id, msg_id)
        except Exception as exc:
            err_count += 1
            error_text = str(exc)[:500]
            print(f"  ERROR msg={msg_id}: {error_text}")
            mark_error(entity, db_path, group_id, msg_id, error_text)

        if i % REPORT_EVERY == 0 or i == len(messages):
            batch_elapsed = time.monotonic() - report_start
            chunk_size = REPORT_EVERY if i % REPORT_EVERY == 0 else i % REPORT_EVERY
            avg = batch_elapsed / chunk_size if chunk_size > 0 else 0
            total_elapsed = time.monotonic() - batch_start
            remaining = len(messages) - i
            eta_s = remaining * avg
            eta_m = eta_s / 60
            print(
                f"  [{i:5d}/{len(messages)}]  "
                f"ok={ok_count} skip={nodata_count} err={err_count}  "
                f"avg={avg:.1f}s/msg  "
                f"elapsed={total_elapsed/60:.1f}m  "
                f"eta={eta_m:.1f}m"
            )
            report_start = time.monotonic()
            if i % REPORT_EVERY == 0:
                ok_count = 0
                err_count = 0
                nodata_count = 0

    total_elapsed = time.monotonic() - batch_start

    save_state_backup(entity, group_id, db_path)

    health = await layer.health()
    entity_count = health.details.get("entity_count", 0) if health.details else 0
    edge_count = health.details.get("edge_count", 0) if health.details else 0

    print()
    print(f"Done. {len(messages)} messages in {total_elapsed/60:.1f} minutes.")
    print(f"Graph now: {entity_count} entities, {edge_count} edges (group={group_id})")

    layer.close()


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Entity-aware bulk ingestion for the custom knowledge graph.\n"
            "--entity is REQUIRED — there is no default.\n"
        )
    )
    parser.add_argument(
        "--entity", required=True,
        help=f"Entity name (one of: {', '.join(sorted(ENTITY_CONFIG))}).  REQUIRED.",
    )
    parser.add_argument(
        "--batch", type=int, default=0,
        help="Max messages to process (0 = all pending).",
    )
    parser.add_argument(
        "--from-id", type=int, default=None,
        help="Re-ingest from this message ID (clears kg_ingested_at for id >= N).",
    )
    parser.add_argument(
        "--retry-errors", action="store_true",
        help="Retry messages that previously failed ingestion.",
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

    # Validate entity name first — before anything else touches config
    get_entity_config(args.entity)  # exits on unknown entity

    if args.status:
        show_status(args.entity)
        return

    await run_ingestion(
        entity=args.entity,
        batch_size=args.batch,
        from_id=args.from_id,
        dry_run=args.dry_run,
        retry_errors=args.retry_errors,
    )


if __name__ == "__main__":
    asyncio.run(main())
