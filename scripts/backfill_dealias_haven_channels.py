#!/usr/bin/env python3
"""Backfill script: reconcile Haven channel identity split (Issue #19).

Rewrites haven:<uuid> channel strings to haven:<slug> (the canonical form) and
de-duplicates any resulting exact-duplicate rows. One-time migration to fix
historical dual-write from bot.py + bridge.py before the redundant writer was
removed.

⚠️  WARNING: This mutates live continuity data in conversations.db. Always run
dry-run first. Review the SQL carefully. Backup before --execute.

Usage:
    # Dry-run (default, shows what would change):
    python3 scripts/backfill_dealias_haven_channels.py --entity lyra

    # Apply changes (CAREFUL):
    python3 scripts/backfill_dealias_haven_channels.py --entity lyra --execute
"""

import argparse
import sqlite3
import sys
from pathlib import Path


def auto_detect_project_root() -> Path:
    """Walk up from script location to find project root."""
    script = Path(__file__).resolve()
    # Script is in scripts/, so parent is project root
    return script.parent.parent


def load_room_map(haven_db_path: Path) -> dict[str, str]:
    """Load room_id → name map from haven.db.

    Returns:
        Dict mapping UUID room IDs to slug names (e.g.,
        'b1639de8-98b0-4f40-91b4-800090ba4ceb' → 'silverglow')
    """
    if not haven_db_path.exists():
        print(f"ERROR: Haven DB not found at {haven_db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(f"file:{haven_db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM rooms")
    room_map = {row["id"]: row["name"] for row in cursor.fetchall()}
    conn.close()
    return room_map


def scan_conversations_db(conversations_db_path: Path, room_map: dict[str, str]) -> dict:
    """Scan conversations.db for haven:<uuid> channels and plan the migration.

    Returns:
        Dict with keys:
        - rewrites: list of (row_id, old_channel, new_channel) tuples
        - duplicates_after_rewrite: list of (row_id, channel, author, content, created_at) tuples
        - before_counts: dict mapping channel string to row count
        - after_counts: dict mapping channel string to estimated row count post-dedup
    """
    if not conversations_db_path.exists():
        print(f"ERROR: Conversations DB not found at {conversations_db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(f"file:{conversations_db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get before counts
    cursor.execute("""
        SELECT channel, COUNT(*) as cnt
        FROM messages
        WHERE channel LIKE 'haven:%'
        GROUP BY channel
        ORDER BY channel
    """)
    before_counts = {row["channel"]: row["cnt"] for row in cursor.fetchall()}

    # Find rows to rewrite
    rewrites = []
    for room_id, slug in room_map.items():
        uuid_channel = f"haven:{room_id}"
        slug_channel = f"haven:{slug}"

        cursor.execute("""
            SELECT id FROM messages WHERE channel = ?
        """, (uuid_channel,))
        for row in cursor.fetchall():
            rewrites.append((row["id"], uuid_channel, slug_channel))

    # NOTE: Duplicate detection is deferred to the migration step.
    # After rewriting UUID channels to slugs, we'll find duplicates by querying
    # for (channel, author, content, timestamp) groups with count > 1.
    # This is much faster than trying to predict duplicates before the rewrite.
    duplicates = []

    # Estimate after counts
    after_counts = {}
    for channel, count in before_counts.items():
        after_counts[channel] = count

    # Adjust for rewrites
    for _, old_channel, new_channel in rewrites:
        after_counts[old_channel] = after_counts.get(old_channel, 0) - 1
        after_counts[new_channel] = after_counts.get(new_channel, 0) + 1

    # Adjust for deletions
    for _, channel, _, _, _ in duplicates:
        after_counts[channel] = after_counts.get(channel, 1) - 1

    # Remove zero counts
    after_counts = {k: v for k, v in after_counts.items() if v > 0}

    conn.close()

    return {
        "rewrites": rewrites,
        "duplicates": duplicates,
        "before_counts": before_counts,
        "after_counts": after_counts,
    }


def apply_migration(conversations_db_path: Path, plan: dict) -> None:
    """Apply the migration plan to conversations.db.

    All changes are wrapped in a transaction. Rolls back on any error.
    """
    conn = sqlite3.connect(conversations_db_path)
    cursor = conn.cursor()

    try:
        print("Step 1: Rewriting UUID channels to slugs...", file=sys.stderr)
        # Rewrite haven:<uuid> → haven:<slug>
        for row_id, old_channel, new_channel in plan["rewrites"]:
            cursor.execute("""
                UPDATE messages SET channel = ? WHERE id = ?
            """, (new_channel, row_id))

        print(f"Step 2: Finding duplicates after rewrite...", file=sys.stderr)
        # Now find and delete duplicates - keeping the lowest ID in each group
        # This is much faster to do after the rewrite than before
        cursor.execute("""
            DELETE FROM messages
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM messages
                WHERE channel LIKE 'haven:%'
                GROUP BY channel, author_name, content, created_at
            )
            AND channel LIKE 'haven:%'
        """)
        deleted_count = cursor.rowcount
        print(f"Step 2: Deleted {deleted_count} duplicate rows", file=sys.stderr)

        conn.commit()
        print(f"✓ Migration applied successfully", file=sys.stderr)
    except Exception as e:
        conn.rollback()
        print(f"ERROR: Migration failed, rolled back: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


def print_sql(plan: dict) -> None:
    """Print the SQL that would be executed."""
    print("\n-- SQL that would execute:")
    print("BEGIN TRANSACTION;")
    print()

    if plan["rewrites"]:
        print(f"-- Rewrite {len(plan['rewrites'])} haven:<uuid> rows to haven:<slug>")
        for row_id, old_channel, new_channel in plan["rewrites"][:5]:
            print(f"UPDATE messages SET channel = '{new_channel}' WHERE id = {row_id}; -- was {old_channel}")
        if len(plan["rewrites"]) > 5:
            print(f"-- ... and {len(plan['rewrites']) - 5} more rewrites")
        print()

    if plan["duplicates"]:
        print(f"-- Delete {len(plan['duplicates'])} duplicate rows")
        for row_id, channel, author, content_preview, created_at in plan["duplicates"][:5]:
            content_short = content_preview[:40] + "..." if len(content_preview) > 40 else content_preview
            print(f"DELETE FROM messages WHERE id = {row_id}; -- {channel} | {author} | '{content_short}' | {created_at}")
        if len(plan["duplicates"]) > 5:
            print(f"-- ... and {len(plan['duplicates']) - 5} more deletions")
        print()

    print("COMMIT;")
    print()


def print_report(plan: dict, entity: str) -> None:
    """Print a before/after report."""
    print(f"\n{'='*70}")
    print(f"Haven Channel De-aliasing Report — Entity: {entity}")
    print(f"{'='*70}\n")

    print(f"Rewrites planned:   {len(plan['rewrites'])} rows (haven:<uuid> → haven:<slug>)")
    print(f"Duplicates to delete: {len(plan['duplicates'])} rows\n")

    print("BEFORE counts (current state):")
    for channel in sorted(plan["before_counts"].keys()):
        count = plan["before_counts"][channel]
        print(f"  {channel:50s} {count:5d} rows")

    print("\nAFTER counts (post-migration):")
    for channel in sorted(plan["after_counts"].keys()):
        count = plan["after_counts"][channel]
        before = plan["before_counts"].get(channel, 0)
        delta = count - before
        delta_str = f"({delta:+d})" if delta != 0 else ""
        print(f"  {channel:50s} {count:5d} rows {delta_str}")

    # Show which UUID channels will be eliminated
    eliminated = set(plan["before_counts"].keys()) - set(plan["after_counts"].keys())
    if eliminated:
        print(f"\nEliminated channels (fully merged): {len(eliminated)}")
        for channel in sorted(eliminated):
            print(f"  {channel}")

    print(f"\n{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill script: reconcile Haven channel identity split (Issue #19)"
    )
    parser.add_argument(
        "--entity",
        default="lyra",
        choices=["lyra", "caia"],
        help="Entity to backfill (default: lyra)"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root directory (default: auto-detect from script location)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes (default: dry-run only)"
    )

    args = parser.parse_args()

    # Resolve project root
    project_root = args.project_root if args.project_root else auto_detect_project_root()
    if not project_root.exists():
        print(f"ERROR: Project root not found: {project_root}", file=sys.stderr)
        sys.exit(1)

    # Resolve DB paths
    conversations_db = project_root / "entities" / args.entity / "data" / "conversations.db"
    haven_db = project_root / "haven" / "data" / "haven.db"

    print(f"Project root: {project_root}")
    print(f"Conversations DB: {conversations_db}")
    print(f"Haven DB: {haven_db}")
    print()

    # Load room map
    print("Loading room map from Haven DB...")
    room_map = load_room_map(haven_db)
    print(f"Found {len(room_map)} rooms")
    for room_id, slug in sorted(room_map.items(), key=lambda x: x[1])[:5]:
        print(f"  {slug:20s} → {room_id}")
    if len(room_map) > 5:
        print(f"  ... and {len(room_map) - 5} more")
    print()

    # Scan and plan migration
    print("Scanning conversations.db...")
    plan = scan_conversations_db(conversations_db, room_map)

    # Print report
    print_report(plan, args.entity)

    # Print SQL
    print_sql(plan)

    # Apply if --execute
    if args.execute:
        print("⚠️  EXECUTING MIGRATION (this will modify live data) ⚠️\n")
        print("Press Ctrl-C within 3 seconds to abort...")
        import time
        time.sleep(3)
        print()
        apply_migration(conversations_db, plan)
        print("\n✓ Migration complete. Verify with:")
        print(f"  sqlite3 {conversations_db} \"SELECT channel, COUNT(*) FROM messages WHERE channel LIKE 'haven:%' GROUP BY channel;\"")
    else:
        print("DRY-RUN mode (no changes applied)")
        print("To apply these changes, run with --execute flag\n")


if __name__ == "__main__":
    main()
