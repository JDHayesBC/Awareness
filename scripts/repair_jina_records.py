#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
Repair Jina-embedded records in conversations.db.

The Jina embedding provider was incorrectly used for batch ingestion,
creating Neo4j records with incompatible vector spaces. This script
marks those messages for re-ingestion with OpenAI embeddings.

Timeline:
  - Jina config added: 2026-02-20 (before batch 5662, created at 21:59:39)
  - Jina config removed: 2026-02-21 (this fix)
  - Affected batches: 5662-5773 (inclusive)
  - Affected message IDs: 17387-19726 (~2,340 messages)

What this script does:
  1. Reports affected message count and batch range
  2. Nulls out graphiti_batch_id for those messages (marks for re-ingestion)
  3. Deletes the affected graphiti_batch records
  4. Does NOT modify Neo4j — the Jina episodes remain there with wrong embeddings
     but they'll be treated as duplicates when re-ingested with OpenAI

Usage:
    python scripts/repair_jina_records.py [--dry-run]

Options:
    --dry-run   Show what would be done without making changes (default: False)
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# Load env
from dotenv import load_dotenv
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / "pps" / "docker" / ".env")

import sqlite3

# Jina window boundaries (determined by investigating graphiti_batches table)
# First batch created with Jina config (first run on Feb 20):
JINA_FIRST_BATCH_ID = 5662
# Last batch created before OpenAI config was restored:
JINA_LAST_BATCH_ID = 5773  # inclusive, update if more batches ran before revert

def get_db_path() -> str:
    entity_path = os.environ.get("ENTITY_PATH", "")
    if entity_path:
        return str(Path(entity_path) / "data" / "conversations.db")
    return str(PROJECT_ROOT / "entities" / "lyra" / "data" / "conversations.db")


def report(conn: sqlite3.Connection) -> dict:
    """Report the scope of Jina-contaminated records."""
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) as batch_count,
               MIN(id) as first_batch,
               MAX(id) as last_batch,
               MIN(created_at) as first_created,
               MAX(created_at) as last_created
        FROM graphiti_batches
        WHERE id BETWEEN ? AND ?
    """, (JINA_FIRST_BATCH_ID, JINA_LAST_BATCH_ID))
    batch_info = dict(cur.fetchone())

    cur.execute("""
        SELECT COUNT(*) as msg_count,
               MIN(id) as first_msg,
               MAX(id) as last_msg
        FROM messages
        WHERE graphiti_batch_id BETWEEN ? AND ?
    """, (JINA_FIRST_BATCH_ID, JINA_LAST_BATCH_ID))
    msg_info = dict(cur.fetchone())

    return {**batch_info, **msg_info}


def repair(conn: sqlite3.Connection, dry_run: bool) -> dict:
    """Mark affected messages for re-ingestion."""
    cur = conn.cursor()

    # Count what we'll affect
    cur.execute("""
        SELECT COUNT(*) FROM messages
        WHERE graphiti_batch_id BETWEEN ? AND ?
    """, (JINA_FIRST_BATCH_ID, JINA_LAST_BATCH_ID))
    msg_count = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM graphiti_batches
        WHERE id BETWEEN ? AND ?
    """, (JINA_FIRST_BATCH_ID, JINA_LAST_BATCH_ID))
    batch_count = cur.fetchone()[0]

    if dry_run:
        print(f"[DRY RUN] Would NULL graphiti_batch_id for {msg_count} messages")
        print(f"[DRY RUN] Would delete {batch_count} graphiti_batch records (IDs {JINA_FIRST_BATCH_ID}-{JINA_LAST_BATCH_ID})")
        return {"messages_cleared": 0, "batches_deleted": 0, "dry_run": True}

    # Clear graphiti_batch_id for Jina-contaminated messages
    cur.execute("""
        UPDATE messages
        SET graphiti_batch_id = NULL
        WHERE graphiti_batch_id BETWEEN ? AND ?
    """, (JINA_FIRST_BATCH_ID, JINA_LAST_BATCH_ID))
    messages_cleared = cur.rowcount

    # Delete the batch records
    cur.execute("""
        DELETE FROM graphiti_batches
        WHERE id BETWEEN ? AND ?
    """, (JINA_FIRST_BATCH_ID, JINA_LAST_BATCH_ID))
    batches_deleted = cur.rowcount

    conn.commit()
    return {
        "messages_cleared": messages_cleared,
        "batches_deleted": batches_deleted,
        "dry_run": False,
    }


def main():
    parser = argparse.ArgumentParser(description="Repair Jina-embedded records")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without making changes")
    args = parser.parse_args()

    db_path = get_db_path()
    print(f"Database: {db_path}")
    print(f"Jina batch range: {JINA_FIRST_BATCH_ID} - {JINA_LAST_BATCH_ID}")
    print()

    conn = sqlite3.connect(db_path)

    # Report scope
    info = report(conn)
    print(f"Affected batches: {info['batch_count']} (IDs {info['first_batch']}-{info['last_batch']})")
    print(f"First batch created: {info['first_created']}")
    print(f"Last batch created: {info['last_created']}")
    print(f"Affected messages: {info['msg_count']} (IDs {info['first_msg']}-{info['last_msg']})")
    print()

    if not args.dry_run:
        confirm = input("Proceed with repair? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Aborted.")
            conn.close()
            sys.exit(0)

    # Perform repair
    result = repair(conn, args.dry_run)
    conn.close()

    print()
    if args.dry_run:
        print("[DRY RUN COMPLETE]")
    else:
        print(f"Repair complete:")
        print(f"  Messages cleared for re-ingestion: {result['messages_cleared']}")
        print(f"  Batch records deleted: {result['batches_deleted']}")
        print()
        print("NOTE: Neo4j still contains the Jina-embedded episodes.")
        print("      They will not match search queries correctly but will not cause errors.")
        print("      Graphiti's deduplication will handle the re-ingested versions.")
        print()
        print("Next step: Run paced_ingestion.py to re-ingest with OpenAI embeddings.")
        print("  python scripts/paced_ingestion.py --batch-size 50 --pause 60")


if __name__ == "__main__":
    main()
