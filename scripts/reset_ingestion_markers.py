#!/usr/bin/env python3
"""
Reset Graphiti ingestion markers in the conversations database.

After a buggy ingestion run where messages were marked as ingested but
nothing was actually written to Graphiti, this script clears the markers
so paced_ingestion.py can re-process them correctly.

By default, only clears markers for messages in batches created on or after
2026-02-14 (when the false-ingestion bug was active). Use --all to reset
everything, or --since-message-id / --since-date to target a specific range.

Usage:
    python reset_ingestion_markers.py [options]

Options:
    --dry-run          Show what would be reset without making changes
    --all              Reset ALL ingestion markers (original behavior, explicit opt-in required)
    --since-date DATE  Only clear markers for batches created >= DATE (default: 2026-02-14)
    --since-message-id ID  Only clear markers for messages with id >= ID
"""

import argparse
import os
import sqlite3
from pathlib import Path

# Load env for ENTITY_PATH
from dotenv import load_dotenv
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / "pps" / "docker" / ".env")

DEFAULT_SINCE_DATE = "2026-02-14"


def get_db_path() -> Path:
    entity_path = os.environ.get("ENTITY_PATH", "")
    if entity_path:
        return Path(entity_path) / "data" / "conversations.db"
    return PROJECT_ROOT / "entities" / "lyra" / "data" / "conversations.db"


def show_summary(cur: sqlite3.Cursor, since_date: str | None, since_message_id: int | None) -> tuple[int, int, int, int]:
    """Compute and print summary statistics. Returns (total, keep, reset, batches_to_delete)."""
    cur.execute("SELECT COUNT(*) FROM messages")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM messages WHERE graphiti_batch_id IS NOT NULL")
    total_marked = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM graphiti_batches")
    total_batches = cur.fetchone()[0]

    # Determine which batches are fake
    if since_date:
        cur.execute(
            "SELECT COUNT(*) FROM graphiti_batches WHERE created_at >= ?",
            (since_date,)
        )
        fake_batches = cur.fetchone()[0]

        cur.execute(
            """SELECT COUNT(*) FROM messages
               WHERE graphiti_batch_id IN (
                   SELECT id FROM graphiti_batches WHERE created_at >= ?
               )""",
            (since_date,)
        )
        to_reset = cur.fetchone()[0]

    elif since_message_id is not None:
        cur.execute(
            "SELECT COUNT(*) FROM messages WHERE id >= ? AND graphiti_batch_id IS NOT NULL",
            (since_message_id,)
        )
        to_reset = cur.fetchone()[0]

        # Batches whose start_message_id is >= the cutoff
        cur.execute(
            "SELECT COUNT(*) FROM graphiti_batches WHERE start_message_id >= ?",
            (since_message_id,)
        )
        fake_batches = cur.fetchone()[0]

    else:
        # --all mode
        to_reset = total_marked
        fake_batches = total_batches

    keep = total_marked - to_reset

    print(f"\nSummary:")
    print(f"  Total messages in DB:              {total:>7}")
    print(f"  Messages keeping their markers:    {keep:>7}  (legitimately ingested)")
    print(f"  Messages that will be reset:       {to_reset:>7}  (false markers)")
    print(f"  Batch records that will be deleted:{fake_batches:>7}")

    return total, keep, to_reset, fake_batches


def reset_by_date(cur: sqlite3.Cursor, since_date: str) -> tuple[int, int]:
    """Clear markers for messages in batches created on or after since_date."""
    cur.execute(
        """UPDATE messages
           SET graphiti_batch_id = NULL, graphiti_ingested = FALSE
           WHERE graphiti_batch_id IN (
               SELECT id FROM graphiti_batches WHERE created_at >= ?
           )""",
        (since_date,)
    )
    updated = cur.rowcount

    cur.execute(
        "DELETE FROM graphiti_batches WHERE created_at >= ?",
        (since_date,)
    )
    deleted = cur.rowcount

    return updated, deleted


def reset_by_message_id(cur: sqlite3.Cursor, since_message_id: int) -> tuple[int, int]:
    """Clear markers for messages with id >= since_message_id."""
    cur.execute(
        """UPDATE messages
           SET graphiti_batch_id = NULL, graphiti_ingested = FALSE
           WHERE id >= ? AND graphiti_batch_id IS NOT NULL""",
        (since_message_id,)
    )
    updated = cur.rowcount

    cur.execute(
        "DELETE FROM graphiti_batches WHERE start_message_id >= ?",
        (since_message_id,)
    )
    deleted = cur.rowcount

    return updated, deleted


def reset_all(cur: sqlite3.Cursor) -> tuple[int, int]:
    """Clear all ingestion markers."""
    cur.execute(
        "UPDATE messages SET graphiti_batch_id = NULL, graphiti_ingested = FALSE "
        "WHERE graphiti_batch_id IS NOT NULL"
    )
    updated = cur.rowcount

    cur.execute("DELETE FROM graphiti_batches")
    deleted = cur.rowcount

    return updated, deleted


def main():
    parser = argparse.ArgumentParser(description="Reset Graphiti ingestion markers")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be reset without making changes")
    parser.add_argument("--all", action="store_true",
                        help="Reset ALL ingestion markers (requires explicit opt-in)")
    parser.add_argument("--since-date", default=DEFAULT_SINCE_DATE,
                        metavar="DATE",
                        help=f"Only clear markers for batches created >= DATE "
                             f"(default: {DEFAULT_SINCE_DATE})")
    parser.add_argument("--since-message-id", type=int,
                        metavar="ID",
                        help="Only clear markers for messages with id >= ID "
                             "(overrides --since-date)")
    args = parser.parse_args()

    db_path = get_db_path()
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    print(f"Database: {db_path}")

    # Determine mode
    if args.all:
        mode = "all"
        since_date = None
        since_message_id = None
        print("Mode: RESET ALL (full wipe)")
    elif args.since_message_id is not None:
        mode = "message_id"
        since_date = None
        since_message_id = args.since_message_id
        print(f"Mode: reset messages with id >= {since_message_id}")
    else:
        mode = "date"
        since_date = args.since_date
        since_message_id = None
        print(f"Mode: reset batches created >= {since_date}")

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    show_summary(cur, since_date, since_message_id)

    if args.dry_run:
        print("\n[DRY RUN] No changes made.")
        conn.close()
        return

    print(f"\nResetting ingestion markers...")

    if mode == "all":
        updated, deleted = reset_all(cur)
    elif mode == "message_id":
        updated, deleted = reset_by_message_id(cur, since_message_id)
    else:
        updated, deleted = reset_by_date(cur, since_date)

    conn.commit()
    conn.close()

    print(f"  Cleared graphiti_batch_id for {updated} messages")
    print(f"  Deleted {deleted} batch records")
    print(f"\nDone. {updated} messages are now ready for re-ingestion.")
    print("Run paced_ingestion.py to re-ingest them.")


if __name__ == "__main__":
    main()
