#!/usr/bin/env python3
"""
Migration script: summaries → crystals

This script renames the summaries directory structure to crystals for terminology consistency.

Changes:
  ~/.claude/summaries/          → ~/.claude/crystals/
  ~/.claude/summaries/current/  → ~/.claude/crystals/current/
  ~/.claude/summaries/archive/  → ~/.claude/crystals/archive/
  summary_001.md                → crystal_001.md

Usage:
  python migrate_summaries_to_crystals.py --dry-run    # See what would happen
  python migrate_summaries_to_crystals.py              # Actually migrate
  python migrate_summaries_to_crystals.py --rollback   # Undo migration

Safety:
  - Creates backup before any changes
  - Dry-run mode to preview changes
  - Rollback capability
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path


def get_claude_home() -> Path:
    """Get CLAUDE_HOME path."""
    import os
    return Path(os.getenv("CLAUDE_HOME", Path.home() / ".claude"))


def backup_directory(source: Path, backup_root: Path) -> Path:
    """Create a timestamped backup of a directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_root / f"summaries_backup_{timestamp}"

    if source.exists():
        shutil.copytree(source, backup_path)
        print(f"  Backed up {source} → {backup_path}")
        return backup_path
    return None


def rename_files_in_directory(directory: Path, dry_run: bool = False) -> list:
    """Rename summary_*.md files to crystal_*.md in a directory."""
    changes = []

    if not directory.exists():
        return changes

    for old_path in directory.glob("summary_*.md"):
        # Extract the number part
        name = old_path.name
        new_name = name.replace("summary_", "crystal_")
        new_path = old_path.parent / new_name

        changes.append((old_path, new_path))

        if not dry_run:
            old_path.rename(new_path)
            print(f"  Renamed: {name} → {new_name}")
        else:
            print(f"  Would rename: {name} → {new_name}")

    return changes


def migrate(dry_run: bool = False) -> bool:
    """Perform the migration from summaries to crystals."""
    claude_home = get_claude_home()
    old_dir = claude_home / "summaries"
    new_dir = claude_home / "crystals"
    backup_root = claude_home / "backups"

    print(f"\nMigration: summaries → crystals")
    print(f"CLAUDE_HOME: {claude_home}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("-" * 50)

    # Check if migration is needed
    if not old_dir.exists():
        if new_dir.exists():
            print("Already migrated (crystals/ exists, summaries/ does not)")
            return True
        else:
            print("Nothing to migrate (no summaries/ directory)")
            return True

    if new_dir.exists():
        print("ERROR: Both summaries/ and crystals/ exist!")
        print("Please resolve manually or use --rollback first")
        return False

    # Step 1: Create backup
    print("\nStep 1: Creating backup...")
    if not dry_run:
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_path = backup_directory(old_dir, backup_root)
        if backup_path:
            print(f"  Backup created at: {backup_path}")
    else:
        print(f"  Would backup {old_dir} → {backup_root}/summaries_backup_<timestamp>")

    # Step 2: Rename the main directory
    print("\nStep 2: Renaming directory...")
    if not dry_run:
        old_dir.rename(new_dir)
        print(f"  Renamed: summaries/ → crystals/")
    else:
        print(f"  Would rename: summaries/ → crystals/")

    # Step 3: Rename files in current/
    print("\nStep 3: Renaming files in current/...")
    current_dir = new_dir / "current" if not dry_run else old_dir / "current"
    rename_files_in_directory(current_dir, dry_run)

    # Step 4: Rename files in archive/
    print("\nStep 4: Renaming files in archive/...")
    archive_dir = new_dir / "archive" if not dry_run else old_dir / "archive"
    rename_files_in_directory(archive_dir, dry_run)

    print("\n" + "=" * 50)
    if dry_run:
        print("DRY RUN COMPLETE - No changes made")
        print("Run without --dry-run to apply changes")
    else:
        print("MIGRATION COMPLETE")
        print(f"Backup saved in: {backup_root}")

    return True


def rollback() -> bool:
    """Rollback the migration (crystals → summaries)."""
    claude_home = get_claude_home()
    old_dir = claude_home / "summaries"
    new_dir = claude_home / "crystals"

    print(f"\nRollback: crystals → summaries")
    print(f"CLAUDE_HOME: {claude_home}")
    print("-" * 50)

    if not new_dir.exists():
        print("Nothing to rollback (no crystals/ directory)")
        return True

    if old_dir.exists():
        print("ERROR: Both summaries/ and crystals/ exist!")
        print("Please resolve manually")
        return False

    # Step 1: Rename files back
    print("\nStep 1: Renaming files in current/...")
    current_dir = new_dir / "current"
    if current_dir.exists():
        for old_path in current_dir.glob("crystal_*.md"):
            new_name = old_path.name.replace("crystal_", "summary_")
            new_path = old_path.parent / new_name
            old_path.rename(new_path)
            print(f"  Renamed: {old_path.name} → {new_name}")

    print("\nStep 2: Renaming files in archive/...")
    archive_dir = new_dir / "archive"
    if archive_dir.exists():
        for old_path in archive_dir.glob("crystal_*.md"):
            new_name = old_path.name.replace("crystal_", "summary_")
            new_path = old_path.parent / new_name
            old_path.rename(new_path)
            print(f"  Renamed: {old_path.name} → {new_name}")

    # Step 3: Rename directory back
    print("\nStep 3: Renaming directory...")
    new_dir.rename(old_dir)
    print(f"  Renamed: crystals/ → summaries/")

    print("\n" + "=" * 50)
    print("ROLLBACK COMPLETE")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Migrate summaries to crystals for terminology consistency"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--rollback", "-r",
        action="store_true",
        help="Rollback migration (crystals → summaries)"
    )

    args = parser.parse_args()

    if args.rollback:
        success = rollback()
    else:
        success = migrate(dry_run=args.dry_run)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
