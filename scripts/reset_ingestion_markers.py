#!/usr/bin/env python3
"""
Reset Graphiti ingestion markers in the conversations database.

After a buggy ingestion run where messages were marked as ingested but
nothing was actually written to Graphiti, this script clears the markers
so paced_ingestion.py can re-process them correctly.

Usage:
    python reset_ingestion_markers.py [--dry-run]

Options:
    --dry-run: Show what would be reset without making changes
"""

import argparse
import os
import sqlite3
from pathlib import Path

# Load env for ENTITY_PATH
from dotenv import load_dotenv
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / "pps" / "docker" / ".env")


def get_db_path() -> Path:
    entity_path = os.environ.get("ENTITY_PATH", "")
    if entity_path:
        return Path(entity_path) / "data" / "conversations.db"
    return PROJECT_ROOT / "entities" / "lyra" / "data" / "conversations.db"


def main():
    parser = argparse.ArgumentParser(description="Reset Graphiti ingestion markers")
    parser.add_argument("--dry-run", action="store_true", help="Show counts without modifying")
    args = parser.parse_args()

    db_path = get_db_path()
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    print(f"Database: {db_path}")

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Show current state
    cur.execute("SELECT COUNT(*) FROM messages WHERE graphiti_batch_id IS NOT NULL")
    marked = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM messages WHERE graphiti_batch_id IS NULL")
    unmarked = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM graphiti_batches")
    batches = cur.fetchone()[0]

    print(f"Currently marked as ingested: {marked}")
    print(f"Currently unmarked (pending): {unmarked}")
    print(f"Batch records: {batches}")

    if args.dry_run:
        print("\n[DRY RUN] Would reset all ingestion markers.")
        print(f"  - Set graphiti_batch_id = NULL for {marked} messages")
        print(f"  - Delete {batches} batch records from graphiti_batches")
        conn.close()
        return

    print(f"\nResetting all ingestion markers...")

    # Clear batch IDs on messages
    cur.execute("UPDATE messages SET graphiti_batch_id = NULL WHERE graphiti_batch_id IS NOT NULL")
    updated = cur.rowcount
    print(f"  Cleared graphiti_batch_id for {updated} messages")

    # Clear batch records
    cur.execute("DELETE FROM graphiti_batches")
    deleted = cur.rowcount
    print(f"  Deleted {deleted} batch records")

    conn.commit()
    conn.close()

    print(f"\nDone. {updated} messages are now ready for ingestion.")
    print("Run paced_ingestion.py to re-ingest them.")


if __name__ == "__main__":
    main()
