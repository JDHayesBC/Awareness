#!/usr/bin/env python3
"""
Cron-friendly auto-ingester for all entities' custom knowledge graphs.

Designed for:
    */5 * * * * /path/to/pps/venv/bin/python3 /path/to/scripts/kg_ingest_daemon.py

Behavior:
- One LLM pre-flight check shared across all entities.
- Iterates ALL configured entities in order.
- For each entity: ingests up to DAEMON_BATCH messages.
- Per-entity crossbleed validation on every DB access and Neo4j write.
- If LM Studio is down → exits cleanly (cron mail shows the reason).
- If no entity has pending messages → exits cleanly (silent cron run).
- Logs everything to stdout (captured by cron mail or journald).

Venv requirement: pps/venv
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
EXPECTED_VENV = PROJECT_ROOT / "pps" / "venv"
VENV_SYMLINK = PROJECT_ROOT / ".venv"
sys.path.insert(0, str(PROJECT_ROOT))

# Guard: must run from the project venv
if not (
    sys.prefix.startswith(str(EXPECTED_VENV))
    or sys.prefix.startswith(str(VENV_SYMLINK.resolve()))
):
    print("ERROR: Run from the project venv, not system Python.")
    print(f"  Expected: {EXPECTED_VENV}/bin/python3")
    print(f"  Got:      {sys.executable}")
    sys.exit(1)

import httpx  # noqa: E402
from pps.layers.custom_graph import CustomGraphLayer  # noqa: E402


# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.WARNING,  # suppress noisy library output
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("kg_ingest_daemon")


def log(msg: str) -> None:
    """Timestamped stdout line (captured by cron mail / journald)."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

# How many messages to ingest per entity per cron tick.
# Keep low — daemon runs every 5 min so small batches stay responsive.
DAEMON_BATCH = int(os.environ.get("KG_DAEMON_BATCH", "50"))

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

MIN_CONTENT_LENGTH = 30
MAX_CONTENT_LENGTH = 2000

# ─────────────────────────────────────────────
# Entity registry (same as kg_ingest.py — kept in sync manually)
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# Crossbleed assertions
# ─────────────────────────────────────────────

def assert_no_crossbleed(entity: str, db_path: Path, group_id: str) -> None:
    """
    Hard-abort if db_path or group_id does not belong to entity.

    This check runs before every database open and before every Neo4j write
    cycle.  It ensures that messages from entity A cannot reach entity B's
    graph under any circumstances.
    """
    cfg = ENTITY_CONFIG[entity]  # entity must already be in registry
    canonical_db = Path(cfg["db_path"]).resolve()
    canonical_group = cfg["group_id"]

    given_db = Path(db_path).resolve()
    if given_db != canonical_db:
        log(
            f"CROSSBLEED ABORT [{entity}]: DB path mismatch.\n"
            f"  Expected: {canonical_db}\n"
            f"  Got:      {given_db}\n"
            "  Skipping this entity entirely."
        )
        raise RuntimeError(f"crossbleed: db_path mismatch for entity '{entity}'")

    if group_id != canonical_group:
        log(
            f"CROSSBLEED ABORT [{entity}]: group_id mismatch.\n"
            f"  Expected: {canonical_group}\n"
            f"  Got:      {group_id}\n"
            "  Skipping this entity entirely."
        )
        raise RuntimeError(f"crossbleed: group_id mismatch for entity '{entity}'")


# ─────────────────────────────────────────────
# Database helpers
# ─────────────────────────────────────────────

def ensure_kg_columns(entity: str, db_path: Path, group_id: str) -> None:
    """Add kg_ingested_at and kg_error columns if they don't exist (idempotent)."""
    assert_no_crossbleed(entity, db_path, group_id)
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    existing = {c[1] for c in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "kg_ingested_at" not in existing:
        conn.execute("ALTER TABLE messages ADD COLUMN kg_ingested_at TEXT")
        log(f"[{entity}] Migrated: added kg_ingested_at column")
    if "kg_error" not in existing:
        conn.execute("ALTER TABLE messages ADD COLUMN kg_error TEXT")
        log(f"[{entity}] Migrated: added kg_error column")
    conn.commit()
    conn.close()


def count_pending(entity: str, db_path: Path, group_id: str) -> int:
    """Count messages not yet ingested and not in error state."""
    assert_no_crossbleed(entity, db_path, group_id)
    import sqlite3
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


def fetch_batch(entity: str, db_path: Path, group_id: str, limit: int) -> list[dict]:
    """Fetch up to `limit` pending messages for the entity."""
    assert_no_crossbleed(entity, db_path, group_id)
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT id, channel, content, author_name, created_at
           FROM messages
           WHERE kg_ingested_at IS NULL
             AND kg_error IS NULL
             AND length(content) >= ?
             AND length(content) <= ?
           ORDER BY id ASC
           LIMIT ?""",
        (MIN_CONTENT_LENGTH, MAX_CONTENT_LENGTH, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_ingested(entity: str, db_path: Path, group_id: str, msg_id: int) -> None:
    """Mark a message as successfully ingested."""
    assert_no_crossbleed(entity, db_path, group_id)
    import sqlite3
    ts = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE messages SET kg_ingested_at = ?, kg_error = NULL WHERE id = ?",
        (ts, msg_id),
    )
    conn.commit()
    conn.close()


def mark_error(
    entity: str, db_path: Path, group_id: str, msg_id: int, error_msg: str
) -> None:
    """Record an ingestion error for a message."""
    assert_no_crossbleed(entity, db_path, group_id)
    import sqlite3
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
    Returns "" if unreachable (caller decides how to handle).
    """
    llm_url = os.environ.get("CUSTOM_LLM_BASE_URL", "http://172.26.0.1:1234/v1")
    try:
        resp = httpx.get(f"{llm_url}/models", timeout=10)
        resp.raise_for_status()
        return llm_url
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.HTTPStatusError) as exc:
        log(f"LLM pre-flight FAILED at {llm_url}: {exc}")
        return ""


# ─────────────────────────────────────────────
# Per-entity ingestion
# ─────────────────────────────────────────────

async def ingest_entity(entity: str) -> dict:
    """
    Ingest up to DAEMON_BATCH pending messages for one entity.

    Returns a summary dict: {"entity", "processed", "ok", "errors", "skipped", "pending_after"}
    Raises RuntimeError on crossbleed violations (caller catches and skips entity).
    """
    cfg = ENTITY_CONFIG[entity]
    db_path = Path(cfg["db_path"])
    group_id = cfg["group_id"]

    summary = {
        "entity": entity,
        "processed": 0,
        "ok": 0,
        "errors": 0,
        "skipped": 0,
        "pending_after": 0,
    }

    # Crossbleed check — before anything touches db or neo4j
    assert_no_crossbleed(entity, db_path, group_id)

    if not db_path.exists():
        log(f"[{entity}] DB not found at {db_path} — skipping")
        return summary

    if not NEO4J_PASSWORD:
        log(f"[{entity}] NEO4J_PASSWORD not set — skipping")
        return summary

    ensure_kg_columns(entity, db_path, group_id)
    pending = count_pending(entity, db_path, group_id)

    if pending == 0:
        return summary

    log(f"[{entity}] {pending} pending messages, ingesting up to {DAEMON_BATCH}")

    messages = fetch_batch(entity, db_path, group_id, DAEMON_BATCH)

    # Final crossbleed check before opening Neo4j connection
    assert_no_crossbleed(entity, db_path, group_id)

    layer = CustomGraphLayer(
        neo4j_uri=NEO4J_URI,
        neo4j_user=NEO4J_USER,
        neo4j_password=NEO4J_PASSWORD,
        group_id=group_id,
    )

    health = await layer.health()
    if not health.available:
        log(f"[{entity}] Neo4j unavailable: {health.message}")
        layer.close()
        return summary

    start = time.monotonic()

    for msg in messages:
        msg_id = msg["id"]
        content = msg["content"]
        channel = (msg["channel"] or "terminal").split(":")[0]
        author = msg["author_name"] or ""
        timestamp = msg["created_at"] or ""

        try:
            wrote = await layer.store(
                content=content,
                metadata={
                    "channel": channel,
                    "speaker": author,
                    "timestamp": timestamp,
                },
            )
            summary["processed"] += 1
            if wrote:
                summary["ok"] += 1
            else:
                summary["skipped"] += 1
            mark_ingested(entity, db_path, group_id, msg_id)
        except Exception as exc:
            summary["processed"] += 1
            summary["errors"] += 1
            error_text = str(exc)[:500]
            mark_error(entity, db_path, group_id, msg_id, error_text)

    elapsed = time.monotonic() - start
    summary["pending_after"] = count_pending(entity, db_path, group_id)

    log(
        f"[{entity}] Done: {summary['processed']} processed "
        f"({summary['ok']} ok, {summary['skipped']} no-data, {summary['errors']} errors) "
        f"in {elapsed:.1f}s — {summary['pending_after']} still pending"
    )

    layer.close()
    return summary


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

async def main() -> None:
    run_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log(f"kg_ingest_daemon starting — batch={DAEMON_BATCH} per entity")

    # Single LLM pre-flight shared across all entities
    llm_url = check_llm_reachable()
    if not llm_url:
        log("LLM unreachable — exiting cleanly (will retry next cron tick)")
        sys.exit(0)
    log(f"LLM reachable at {llm_url}")

    total_processed = 0
    total_ok = 0
    total_errors = 0
    entities_with_work = 0

    for entity in sorted(ENTITY_CONFIG.keys()):
        try:
            summary = await ingest_entity(entity)
        except RuntimeError as exc:
            # Crossbleed violation — logged inside assert_no_crossbleed; skip entity
            log(f"[{entity}] Skipped due to safety violation: {exc}")
            continue

        if summary["processed"] > 0:
            entities_with_work += 1
            total_processed += summary["processed"]
            total_ok += summary["ok"]
            total_errors += summary["errors"]

    if total_processed == 0:
        log("No pending messages for any entity — exiting cleanly")
    else:
        log(
            f"Run complete: {total_processed} total processed "
            f"({total_ok} ok, {total_errors} errors) "
            f"across {entities_with_work} entit{'y' if entities_with_work == 1 else 'ies'}"
        )

    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
