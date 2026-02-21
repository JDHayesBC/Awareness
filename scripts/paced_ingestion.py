#!/usr/bin/env python3
"""
Paced Graphiti Ingestion Script

Ingests messages to Graphiti in small batches with pauses to avoid
overwhelming hardware. Outputs progress for monitoring.

Usage:
    python paced_ingestion.py [--batch-size 50] [--pause 30] [--max-batches 0]

Options:
    --batch-size: Messages per batch (default: 50)
    --pause: Seconds between batches (default: 30)
    --max-batches: Stop after N batches, 0 = unlimited (default: 0)
"""

import asyncio
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Load environment from pps/docker/.env BEFORE importing modules that need it
from dotenv import load_dotenv
PROJECT_ROOT = Path(__file__).parent.parent  # scripts/ -> Awareness/
load_dotenv(PROJECT_ROOT / "pps" / "docker" / ".env")

from neo4j import GraphDatabase

# Log file for monitoring
LOG_FILE = Path(__file__).parent / "ingestion.log"

def log(msg: str):
    """Print and log to file."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# =============================================================================
# Entity Deduplication (prevents duplicate primary entities)
# =============================================================================

def get_primary_entity_name() -> str:
    """Get the primary entity name from ENTITY_PATH."""
    entity_path = os.environ.get("ENTITY_PATH", "")
    if entity_path:
        return Path(entity_path).name.capitalize()
    return "Lyra"  # Fallback for this specific instance


def get_neo4j_driver():
    """Get Neo4j driver from environment."""
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "password123")
    return GraphDatabase.driver(uri, auth=(user, password))


def check_and_merge_entity_duplicates(entity_name: str) -> int:
    """
    Check for duplicate entity nodes and merge them if found.

    Returns the number of duplicates merged.
    """
    driver = get_neo4j_driver()
    merged = 0

    with driver.session() as s:
        # Count entities with this name
        r = s.run(
            'MATCH (n:Entity {name: $name}) RETURN count(n) as c',
            name=entity_name
        )
        count = r.single()['c']

        if count <= 1:
            driver.close()
            return 0

        log(f"  ⚠ Found {count} '{entity_name}' nodes - merging duplicates...")

        # Find canonical (most connected)
        r = s.run('''
            MATCH (n:Entity {name: $name})
            OPTIONAL MATCH (n)-[r]-()
            RETURN n.uuid as uuid, count(r) as edges
            ORDER BY edges DESC
        ''', name=entity_name)

        nodes = list(r)
        canonical_uuid = nodes[0]['uuid']
        duplicates = [n['uuid'] for n in nodes[1:]]

        # Merge each duplicate into canonical
        for dup_uuid in duplicates:
            # Transfer outgoing edges
            outgoing = s.run("""
                MATCH (dup:Entity {uuid: $dup_uuid})-[r]->(other)
                WHERE other.uuid <> $canonical_uuid
                RETURN type(r) as rel_type, r.fact as fact, other.uuid as other_uuid
            """, dup_uuid=dup_uuid, canonical_uuid=canonical_uuid).data()

            for e in outgoing:
                s.run(f"""
                    MATCH (c:Entity {{uuid: $canonical_uuid}})
                    MATCH (other:Entity {{uuid: $other_uuid}})
                    MERGE (c)-[r:{e['rel_type']}]->(other)
                    SET r.fact = $fact
                """, canonical_uuid=canonical_uuid, other_uuid=e['other_uuid'], fact=e['fact'])

            # Transfer incoming edges
            incoming = s.run("""
                MATCH (other)-[r]->(dup:Entity {uuid: $dup_uuid})
                WHERE other.uuid <> $canonical_uuid
                RETURN type(r) as rel_type, r.fact as fact, other.uuid as other_uuid
            """, dup_uuid=dup_uuid, canonical_uuid=canonical_uuid).data()

            for e in incoming:
                s.run(f"""
                    MATCH (other:Entity {{uuid: $other_uuid}})
                    MATCH (c:Entity {{uuid: $canonical_uuid}})
                    MERGE (other)-[r:{e['rel_type']}]->(c)
                    SET r.fact = $fact
                """, other_uuid=e['other_uuid'], canonical_uuid=canonical_uuid, fact=e['fact'])

            # Delete duplicate
            s.run("MATCH (dup:Entity {uuid: $dup_uuid}) DETACH DELETE dup", dup_uuid=dup_uuid)
            merged += 1

        log(f"  ✓ Merged {merged} duplicates into canonical {entity_name} node")

    driver.close()
    return merged


# Add project root to path
sys.path.insert(0, str(PROJECT_ROOT))

from pps.layers.rich_texture_v2 import RichTextureLayerV2


async def get_uningested_messages(db_path: str, limit: int) -> list[dict]:
    """Get batch of messages not yet ingested to Graphiti."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id, channel, author_name, content, is_lyra, created_at
        FROM messages
        WHERE graphiti_batch_id IS NULL
        ORDER BY id ASC
        LIMIT ?
    """, (limit,))

    messages = [dict(row) for row in cur.fetchall()]
    conn.close()
    return messages


def mark_batch_ingested(db_path: str, messages: list[dict], channels: list[str]) -> int:
    """Mark a batch of messages as ingested."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    start_id = messages[0]['id']
    end_id = messages[-1]['id']
    message_count = len(messages)
    time_span_start = messages[0]['created_at']
    time_span_end = messages[-1]['created_at']

    # Create batch record with all required fields
    cur.execute("""
        INSERT INTO graphiti_batches
        (start_message_id, end_message_id, message_count, channels, time_span_start, time_span_end, created_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    """, (start_id, end_id, message_count, json.dumps(channels), time_span_start, time_span_end))

    batch_id = cur.lastrowid

    # Update messages
    cur.execute("""
        UPDATE messages
        SET graphiti_batch_id = ?
        WHERE id >= ? AND id <= ?
    """, (batch_id, start_id, end_id))

    conn.commit()
    conn.close()
    return batch_id


def get_stats(db_path: str) -> tuple[int, int]:
    """Get ingested and remaining counts."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM messages WHERE graphiti_batch_id IS NOT NULL")
    ingested = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM messages WHERE graphiti_batch_id IS NULL")
    remaining = cur.fetchone()[0]

    conn.close()
    return ingested, remaining


async def run_ingestion(
    batch_size: int, pause_seconds: int, max_batches: int,
    max_errors: int = 10, error_rate_halt: float = 0.5,
):
    """Run paced ingestion."""
    # Use ENTITY_PATH if available, fall back to old location
    entity_path = os.environ.get("ENTITY_PATH", "")
    if entity_path:
        db_path = str(Path(entity_path) / "data" / "conversations.db")
    else:
        db_path = str(PROJECT_ROOT / "entities" / "lyra" / "data" / "conversations.db")

    # Clear old log
    if LOG_FILE.exists():
        LOG_FILE.unlink()

    log("=== Paced Graphiti Ingestion ===")
    log(f"Batch size: {batch_size}")
    log(f"Pause between batches: {pause_seconds}s")
    log(f"Max batches: {'unlimited' if max_batches == 0 else max_batches}")
    log(f"Error halt: after {max_errors} errors" if max_errors > 0 else "Error halt: disabled")
    log(f"Error rate halt: {error_rate_halt:.0%} of batch")
    log("")

    # Initialize Graphiti layer
    log("Initializing Graphiti layer...")
    layer = RichTextureLayerV2()
    log("Graphiti layer initialized")

    ingested_total, remaining = get_stats(db_path)
    log(f"Starting state: {ingested_total} ingested, {remaining} remaining")
    log("")

    batch_num = 0
    total_errors = 0
    halted = False

    while True:
        batch_num += 1

        if max_batches > 0 and batch_num > max_batches:
            log(f"Reached max batches ({max_batches}). Stopping.")
            break

        # Get batch
        messages = await get_uningested_messages(db_path, batch_size)

        if not messages:
            log("No more messages to ingest. Done!")
            break

        start_time = datetime.now()
        log(f"[Batch {batch_num}] Processing {len(messages)} messages (IDs {messages[0]['id']}-{messages[-1]['id']})...")

        # Ingest each message
        success_count = 0
        fail_count = 0
        failed_ids = []
        channels = set()

        error_categories: dict[str, int] = {}

        for msg in messages:
            metadata = {
                "channel": msg['channel'],
                "role": "assistant" if msg['is_lyra'] else "user",
                "speaker": "Lyra" if msg['is_lyra'] else msg['author_name'],
                "timestamp": msg['created_at']
            }

            try:
                # Format as "speaker: message" per Graphiti best practices
                # This enables automatic speaker extraction for EpisodeType.message
                speaker = "Lyra" if msg['is_lyra'] else msg['author_name']
                formatted_content = f"{speaker}: {msg['content']}"
                success = await layer.store(formatted_content, metadata)
                if success:
                    success_count += 1
                    channels.add(msg['channel'])
                else:
                    fail_count += 1
                    failed_ids.append(msg['id'])
                    # Get error context from the layer
                    err = layer.get_last_error()
                    if err:
                        cat = err["category"]
                        error_categories[cat] = error_categories.get(cat, 0) + 1
                        log(f"  ✗ store() returned False for msg {msg['id']} [{cat}]: {err['message'][:120]}")
                        if not err["is_transient"]:
                            log(f"    Advice: {err['advice']}")
                    else:
                        error_categories["unknown"] = error_categories.get("unknown", 0) + 1
                        log(f"  ✗ store() returned False for msg {msg['id']} (no error context)")
            except Exception as e:
                fail_count += 1
                failed_ids.append(msg['id'])
                error_categories["exception"] = error_categories.get("exception", 0) + 1
                log(f"  ✗ Exception on msg {msg['id']}: {e}")

        total_errors += fail_count

        # Mark batch (only successful messages tracked)
        if success_count > 0:
            batch_id = mark_batch_ingested(
                db_path,
                messages,
                list(channels)
            )

        elapsed = (datetime.now() - start_time).total_seconds()
        ingested_total, remaining = get_stats(db_path)

        log(f"  ✓ {success_count} ingested, {fail_count} failed in {elapsed:.1f}s")
        if failed_ids:
            log(f"  Failed message IDs: {failed_ids}")
        log(f"  Progress: {ingested_total} total ingested, {remaining} remaining")
        log(f"  Cumulative errors: {total_errors}")

        # --- Error halt checks ---
        # Check error rate for this batch
        if fail_count > 0 and len(messages) > 0:
            batch_error_rate = fail_count / len(messages)
            if batch_error_rate >= error_rate_halt:
                log(f"")
                log(f"*** HALTING: Batch error rate {batch_error_rate:.0%} >= threshold {error_rate_halt:.0%} ***")
                log(f"*** {fail_count}/{len(messages)} messages failed in this batch ***")
                if error_categories:
                    dist = ", ".join(f"{k}: {v}" for k, v in sorted(error_categories.items()))
                    log(f"*** Error breakdown: {dist} ***")
                    # Detect transient vs permanent for advice
                    has_quota = "quota_exceeded" in error_categories or "auth_failure" in error_categories
                    has_transient = "rate_limit" in error_categories or "network_timeout" in error_categories
                    if has_quota:
                        log(f"*** PERMANENT ERROR: Check OPENAI_API_KEY credits in pps/docker/.env ***")
                    elif has_transient:
                        log(f"*** TRANSIENT: Retry with --pause 120 or higher ***")
                log(f"*** Diagnose before continuing. Failed IDs: {failed_ids} ***")
                halted = True
                break

        # Check total error count
        if max_errors > 0 and total_errors >= max_errors:
            log(f"")
            log(f"*** HALTING: Reached {total_errors} total errors (limit: {max_errors}) ***")
            if error_categories:
                dist = ", ".join(f"{k}: {v}" for k, v in sorted(error_categories.items()))
                log(f"*** Error breakdown: {dist} ***")
            log(f"*** Diagnose before continuing ***")
            halted = True
            break

        # Check for and merge duplicate primary entity nodes
        entity_name = get_primary_entity_name()
        check_and_merge_entity_duplicates(entity_name)

        if remaining == 0:
            log("All messages ingested!")
            break

        # Pause before next batch
        log(f"  Pausing {pause_seconds}s...")
        await asyncio.sleep(pause_seconds)

    # Final stats
    log("")
    log("=== Final Stats ===")
    ingested_total, remaining = get_stats(db_path)
    log(f"Total ingested: {ingested_total}")
    log(f"Remaining: {remaining}")
    log(f"Total errors: {total_errors}")
    if halted:
        log(f"Status: HALTED (errors exceeded threshold)")
    elif remaining == 0:
        log(f"Status: COMPLETE")
    else:
        log(f"Status: STOPPED (batch limit reached)")

    # Close layer
    await layer.close()


def main():
    parser = argparse.ArgumentParser(description="Paced Graphiti ingestion")
    parser.add_argument("--batch-size", type=int, default=50, help="Messages per batch")
    parser.add_argument("--pause", type=int, default=30, help="Seconds between batches")
    parser.add_argument("--max-batches", type=int, default=0, help="Max batches (0=unlimited)")
    parser.add_argument("--max-errors", type=int, default=10,
                        help="Halt after N total errors (default: 10, 0=no limit)")
    parser.add_argument("--error-rate-halt", type=float, default=0.5,
                        help="Halt if error rate exceeds this fraction (default: 0.5)")

    args = parser.parse_args()

    asyncio.run(run_ingestion(
        args.batch_size, args.pause, args.max_batches,
        args.max_errors, args.error_rate_halt,
    ))


if __name__ == "__main__":
    main()
