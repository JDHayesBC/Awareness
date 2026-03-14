#!/usr/bin/env python3
"""
Clean up old break glass packages, keeping only the most recent N versions.

This script removes old break-glass recovery zips to prevent unbounded disk usage.
Default retention: 4 weeks (keeps last 4 packages).
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def find_break_glass_packages(directory: Path) -> list[tuple[Path, datetime]]:
    """
    Find all break glass packages in the directory with their timestamps.

    Returns:
        List of (path, datetime) tuples sorted by date (newest first)
    """
    packages = []

    for zip_file in directory.glob('*-recovery-*.zip'):
        # Extract date from filename: lyra-recovery-2026-03-14.zip
        parts = zip_file.stem.split('-')
        if len(parts) >= 5:
            try:
                date_str = '-'.join(parts[-3:])  # Get YYYY-MM-DD
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                packages.append((zip_file, date_obj))
            except ValueError:
                logger.warning(f"Could not parse date from {zip_file.name}, skipping")
                continue

    # Sort by date, newest first
    packages.sort(key=lambda x: x[1], reverse=True)
    return packages


def cleanup_old_packages(directory: Path, keep_count: int = 4, dry_run: bool = False):
    """
    Remove old break glass packages, keeping the most recent N.

    Args:
        directory: Directory containing break glass zips
        keep_count: Number of recent packages to keep
        dry_run: If True, don't actually delete files
    """
    logger.info("=" * 60)
    logger.info("BREAK GLASS CLEANUP")
    logger.info("=" * 60)

    if dry_run:
        logger.info("MODE: DRY RUN (no files will be deleted)")

    logger.info(f"Directory: {directory}")
    logger.info(f"Retention: Keep {keep_count} most recent packages")
    logger.info("")

    if not directory.exists():
        logger.error(f"Directory does not exist: {directory}")
        return 1

    packages = find_break_glass_packages(directory)

    if not packages:
        logger.info("No break glass packages found")
        return 0

    logger.info(f"Found {len(packages)} package(s):")
    for zip_file, date_obj in packages:
        size_mb = zip_file.stat().st_size / (1024 * 1024)
        logger.info(f"  {zip_file.name} ({size_mb:.1f} MB) - {date_obj.strftime('%Y-%m-%d')}")

    logger.info("")

    if len(packages) <= keep_count:
        logger.info(f"All {len(packages)} package(s) within retention policy, nothing to delete")
        return 0

    # Packages to keep (newest N)
    packages_to_keep = packages[:keep_count]
    # Packages to delete (everything else)
    packages_to_delete = packages[keep_count:]

    logger.info(f"Keeping {len(packages_to_keep)} most recent:")
    for zip_file, date_obj in packages_to_keep:
        logger.info(f"  KEEP: {zip_file.name}")

    logger.info("")
    logger.info(f"Deleting {len(packages_to_delete)} old package(s):")

    total_freed_mb = 0
    for zip_file, date_obj in packages_to_delete:
        size_mb = zip_file.stat().st_size / (1024 * 1024)
        total_freed_mb += size_mb

        if dry_run:
            logger.info(f"  [DRY] Would delete: {zip_file.name} ({size_mb:.1f} MB)")
        else:
            logger.info(f"  Deleting: {zip_file.name} ({size_mb:.1f} MB)")
            zip_file.unlink()

    logger.info("")
    logger.info(f"Total space {'that would be' if dry_run else ''} freed: {total_freed_mb:.1f} MB")

    if dry_run:
        logger.info("Dry run complete. No files deleted.")
    else:
        logger.info("Cleanup complete.")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description='Clean up old break glass recovery packages',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/cleanup_old_break_glass.py                    # Clean with defaults (keep 4)
    python scripts/cleanup_old_break_glass.py --keep 8           # Keep 8 most recent
    python scripts/cleanup_old_break_glass.py --dry-run          # Preview without deleting
    python scripts/cleanup_old_break_glass.py --dir /tmp         # Custom directory
        """
    )

    parser.add_argument(
        '--dir',
        type=Path,
        default=Path.home() / 'awareness_backups' / 'break_glass',
        help='Directory containing break glass packages (default: ~/awareness_backups/break_glass)'
    )

    parser.add_argument(
        '--keep',
        type=int,
        default=4,
        help='Number of recent packages to keep (default: 4)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview what would be deleted without actually deleting files'
    )

    args = parser.parse_args()

    sys.exit(cleanup_old_packages(args.dir, args.keep, args.dry_run))


if __name__ == '__main__':
    main()
