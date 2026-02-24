#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
PPS Restore Script

Restores PPS data from timestamped tar.gz backup archives.
Includes comprehensive safety checks, validation, and dry-run mode.

SAFETY: This script performs destructive operations. Always:
- Use --dry-run first to preview
- Verify the backup you're restoring
- Ensure you understand what will be overwritten
- Consider creating a backup of current state first

Usage:
    python scripts/restore_pps.py --list                           # List available backups
    python scripts/restore_pps.py --latest --dry-run               # Preview latest restore
    python scripts/restore_pps.py --backup pps_backup_DATE.tar.gz  # Restore specific backup
    python scripts/restore_pps.py --backup /path/to/backup.tar.gz  # Restore from custom path
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path

# =============================================================================
# CONFIGURATION (must match backup_pps.py)
# =============================================================================

# Default backup directory (Windows path accessible from WSL)
DEFAULT_BACKUP_DIR = "/mnt/c/Users/Jeff/awareness_backups"

# Project root (where this script lives in scripts/)
PROJECT_ROOT = Path(__file__).parent.parent

# Restore destinations (must match BACKUP_SOURCES in backup_pps.py)
RESTORE_DESTINATIONS = {
    # SQLite databases (CRITICAL)
    "sqlite": {
        "path": PROJECT_ROOT / "entities" / "lyra" / "data",
        "critical": True,
        "description": "SQLite databases (conversations, inventory, email)",
    },
    # ChromaDB (rebuildable from word-photos on disk)
    "chromadb": {
        "path": PROJECT_ROOT / "docker" / "pps" / "chromadb_data",
        "critical": False,
        "description": "ChromaDB vector database",
    },
    # Neo4j/Graphiti (rebuildable from raw messages)
    "neo4j": {
        "path": PROJECT_ROOT / "docker" / "pps" / "neo4j_data",
        "critical": False,
        "description": "Neo4j graph database (Graphiti)",
    },
    # Entity identity files (also in git, but belt & suspenders)
    "entity_identity": {
        "path": PROJECT_ROOT / "entities" / "lyra",
        "critical": True,
        "description": "Entity identity files",
    },
    # Crystals
    "crystals": {
        "path": PROJECT_ROOT / "entities" / "lyra" / "crystals",
        "critical": True,
        "description": "Crystals (memory artifacts)",
    },
    # Word photos
    "word_photos": {
        "path": PROJECT_ROOT / "entities" / "lyra" / "memories" / "word_photos",
        "critical": True,
        "description": "Word photos (semantic memories)",
    },
}

# Docker compose location for stopping/starting PPS
DOCKER_COMPOSE_DIR = PROJECT_ROOT / "pps" / "docker"


# =============================================================================
# FUNCTIONS
# =============================================================================

def log(msg: str, level: str = "INFO"):
    """Simple logging with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}")


def prompt_confirmation(message: str, default_no: bool = True) -> bool:
    """Prompt user for yes/no confirmation."""
    if default_no:
        prompt = f"{message} [y/N]: "
    else:
        prompt = f"{message} [Y/n]: "

    response = input(prompt).strip().lower()

    if default_no:
        return response == "y" or response == "yes"
    else:
        return response != "n" and response != "no"


def find_backups(backup_dir: Path) -> list[Path]:
    """Find all backup archives, sorted newest first."""
    if not backup_dir.exists():
        return []

    backups = sorted(
        backup_dir.glob("pps_backup_*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,  # Newest first
    )
    return backups


def list_backups(backup_dir: Path) -> None:
    """List all available backups with details."""
    backups = find_backups(backup_dir)

    if not backups:
        log("No backups found!", "WARN")
        return

    log(f"Found {len(backups)} backup(s) in {backup_dir}:")
    print()

    for i, backup in enumerate(backups):
        size_mb = backup.stat().st_size / 1024 / 1024
        mtime = datetime.fromtimestamp(backup.stat().st_mtime)
        age_days = (datetime.now() - mtime).days

        marker = "[LATEST]" if i == 0 else ""
        print(f"  {i+1}. {backup.name} {marker}")
        print(f"     Size: {size_mb:.1f} MB")
        print(f"     Date: {mtime.strftime('%Y-%m-%d %H:%M:%S')} ({age_days} days ago)")
        print()


def validate_backup(backup_path: Path) -> tuple[bool, dict]:
    """Validate backup archive and return contents info.

    Returns:
        Tuple of (is_valid, contents_dict)
    """
    log("Validating backup archive...")

    if not backup_path.exists():
        log(f"  Backup file not found: {backup_path}", "ERROR")
        return False, {}

    try:
        with tarfile.open(backup_path, "r:gz") as tar:
            members = tar.getmembers()
            log(f"  Archive contains {len(members)} entries")

            # Analyze contents
            contents = {}
            for member in members:
                parts = member.name.split("/", 1)
                if len(parts) < 1:
                    continue

                source = parts[0]
                if source not in contents:
                    contents[source] = {"files": 0, "bytes": 0}

                contents[source]["files"] += 1
                contents[source]["bytes"] += member.size

            # Check for critical sources
            critical_sources = {name for name, cfg in RESTORE_DESTINATIONS.items() if cfg["critical"]}
            found_sources = set(contents.keys())
            missing_critical = critical_sources - found_sources

            if missing_critical:
                log(f"  WARNING: Missing critical sources: {missing_critical}", "WARN")
                return False, contents

            # Display contents
            for source, stats in sorted(contents.items()):
                critical = "[CRITICAL]" if RESTORE_DESTINATIONS.get(source, {}).get("critical") else "[optional]"
                desc = RESTORE_DESTINATIONS.get(source, {}).get("description", "unknown")
                log(f"  {critical} {source}: {stats['files']} files, {stats['bytes']:,} bytes ({desc})")

            log("  Validation PASSED", "OK")
            return True, contents

    except Exception as e:
        log(f"  Validation failed: {e}", "ERROR")
        return False, {}


def stop_pps_containers(dry_run: bool = False) -> bool:
    """Stop PPS Docker containers before restore."""
    log("Stopping PPS containers...")
    if dry_run:
        log("  (dry-run: would stop containers)", "DRY")
        return True

    try:
        result = subprocess.run(
            ["docker", "compose", "stop"],
            cwd=DOCKER_COMPOSE_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            log("  Containers stopped")
            return True
        else:
            log(f"  Warning: {result.stderr}", "WARN")
            return False
    except Exception as e:
        log(f"  Error stopping containers: {e}", "ERROR")
        return False


def start_pps_containers(dry_run: bool = False) -> bool:
    """Start PPS Docker containers after restore."""
    log("Starting PPS containers...")
    if dry_run:
        log("  (dry-run: would start containers)", "DRY")
        return True

    try:
        result = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=DOCKER_COMPOSE_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            log("  Containers started")
            return True
        else:
            log(f"  Warning: {result.stderr}", "WARN")
            return False
    except Exception as e:
        log(f"  Error starting containers: {e}", "ERROR")
        return False


def check_container_health(dry_run: bool = False) -> dict:
    """Check health of PPS containers after restore."""
    log("Checking container health...")
    if dry_run:
        log("  (dry-run: would check health)", "DRY")
        return {"status": "skipped"}

    try:
        # Give containers time to initialize
        log("  Waiting 10 seconds for containers to initialize...")
        time.sleep(10)

        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            cwd=DOCKER_COMPOSE_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            # Parse container status
            import json
            containers = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    try:
                        containers.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

            healthy = 0
            unhealthy = 0
            for container in containers:
                status = container.get("State", "unknown")
                health = container.get("Health", "")
                name = container.get("Name", "unknown")

                if status == "running" and (not health or health == "healthy"):
                    log(f"  OK: {name} ({status})", "OK")
                    healthy += 1
                else:
                    log(f"  WARN: {name} ({status}, health: {health})", "WARN")
                    unhealthy += 1

            return {
                "status": "ok" if unhealthy == 0 else "degraded",
                "healthy": healthy,
                "unhealthy": unhealthy,
            }
        else:
            log(f"  Could not check status: {result.stderr}", "WARN")
            return {"status": "unknown"}

    except Exception as e:
        log(f"  Error checking health: {e}", "ERROR")
        return {"status": "error"}


def backup_current_state(dry_run: bool = False) -> Path | None:
    """Create a backup of current state before restore (safety net)."""
    if dry_run:
        log("(dry-run: would create safety backup of current state)", "DRY")
        return None

    log("Creating safety backup of current state...")

    try:
        # Create a quick backup using the existing backup script
        import backup_pps

        safety_dir = PROJECT_ROOT / "work" / "pps_backup" / "pre_restore_safety"
        safety_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_backup = safety_dir / f"pre_restore_safety_{timestamp}.tar.gz"

        log(f"  Creating: {safety_backup}")

        # Create quick tar of critical data only
        with tarfile.open(safety_backup, "w:gz") as tar:
            for name, config in RESTORE_DESTINATIONS.items():
                if config["critical"]:
                    path = Path(config["path"])
                    if path.exists():
                        tar.add(path, arcname=f"{name}/{path.name}")

        size_mb = safety_backup.stat().st_size / 1024 / 1024
        log(f"  Safety backup created: {size_mb:.1f} MB", "OK")
        return safety_backup

    except Exception as e:
        log(f"  Warning: Could not create safety backup: {e}", "WARN")
        log("  Continuing without safety backup (original data will be lost!)", "WARN")
        return None


def restore_from_archive(backup_path: Path, dry_run: bool = False, skip_sources: list = None) -> bool:
    """Extract and restore data from backup archive.

    Args:
        backup_path: Path to backup archive
        dry_run: If True, only show what would be restored
        skip_sources: List of source names to skip

    Returns:
        True if successful
    """
    skip_sources = skip_sources or []

    log(f"Restoring from: {backup_path.name}")

    if dry_run:
        log("  (dry-run: no files will be modified)", "DRY")

    # Create temporary extraction directory
    temp_dir = None
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="pps_restore_"))
        log(f"Extracting to temporary location: {temp_dir}")

        # Extract archive
        with tarfile.open(backup_path, "r:gz") as tar:
            tar.extractall(temp_dir)

        # Restore each source
        for source_name, config in RESTORE_DESTINATIONS.items():
            if source_name in skip_sources:
                log(f"Skipping {source_name} (--skip)", "INFO")
                continue

            source_path = temp_dir / source_name
            dest_path = Path(config["path"])
            critical = "[CRITICAL]" if config["critical"] else "[optional]"

            if not source_path.exists():
                log(f"  {critical} {source_name}: Not in backup (skipping)", "WARN")
                continue

            # Count files to restore
            files = list(source_path.rglob("*"))
            file_count = len([f for f in files if f.is_file()])

            log(f"  {critical} {source_name}: Restoring {file_count} files to {dest_path}")

            if dry_run:
                log(f"    (dry-run: would remove {dest_path})", "DRY")
                log(f"    (dry-run: would copy {source_path} -> {dest_path})", "DRY")
                continue

            # DESTRUCTIVE: Remove existing destination
            if dest_path.exists():
                log(f"    Removing existing: {dest_path}")
                if dest_path.is_dir():
                    shutil.rmtree(dest_path)
                else:
                    dest_path.unlink()

            # Restore from backup
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Copy all files preserving structure
            for item in source_path.rglob("*"):
                if item.is_file():
                    rel_path = item.relative_to(source_path)
                    dest_file = dest_path / rel_path
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_file)

            log(f"    Restored {file_count} files", "OK")

        return True

    except Exception as e:
        log(f"Restore failed: {e}", "ERROR")
        return False

    finally:
        # Cleanup temp directory
        if temp_dir and temp_dir.exists():
            if dry_run:
                log(f"  (dry-run: would remove temp dir {temp_dir})", "DRY")
            else:
                log(f"Cleaning up temporary files: {temp_dir}")
                shutil.rmtree(temp_dir)


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Restore PPS data from backup archive",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/restore_pps.py --list                           # List available backups
    python scripts/restore_pps.py --latest --dry-run               # Preview latest restore
    python scripts/restore_pps.py --backup pps_backup_DATE.tar.gz  # Restore specific
    python scripts/restore_pps.py --latest --skip chromadb neo4j   # Restore without DBs

SAFETY WARNINGS:
    - Always use --dry-run first!
    - This script DELETES existing data before restoring
    - Consider running backup_pps.py before restoring
    - Verify the backup with --list before restoring
        """,
    )

    # Action arguments
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument(
        "--list",
        action="store_true",
        help="List available backups and exit",
    )
    action_group.add_argument(
        "--latest",
        action="store_true",
        help="Restore from the most recent backup",
    )
    action_group.add_argument(
        "--backup",
        type=str,
        help="Backup file to restore (filename or full path)",
    )

    # Configuration arguments
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path(DEFAULT_BACKUP_DIR),
        help=f"Backup directory (default: {DEFAULT_BACKUP_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be restored without making changes",
    )
    parser.add_argument(
        "--skip",
        nargs="+",
        choices=list(RESTORE_DESTINATIONS.keys()),
        help="Skip restoring specific sources (e.g., --skip chromadb neo4j)",
    )
    parser.add_argument(
        "--no-safety-backup",
        action="store_true",
        help="Skip creating a safety backup of current state (DANGEROUS)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompts (DANGEROUS)",
    )

    args = parser.parse_args()

    # List mode
    if args.list:
        list_backups(args.backup_dir)
        return

    # Determine backup to restore
    if args.latest:
        backups = find_backups(args.backup_dir)
        if not backups:
            log(f"No backups found in {args.backup_dir}", "ERROR")
            sys.exit(1)
        backup_path = backups[0]
    else:
        # Check if it's a full path or just a filename
        backup_path = Path(args.backup)
        if not backup_path.exists():
            # Try in backup directory
            backup_path = args.backup_dir / args.backup
            if not backup_path.exists():
                log(f"Backup not found: {args.backup}", "ERROR")
                log(f"Tried: {Path(args.backup).absolute()}", "ERROR")
                log(f"Tried: {backup_path}", "ERROR")
                sys.exit(1)

    # Validate backup
    is_valid, contents = validate_backup(backup_path)
    if not is_valid:
        log("Backup validation failed!", "ERROR")
        sys.exit(1)

    # Banner
    log("=" * 70)
    log("PPS RESTORE")
    log("=" * 70)
    log(f"Backup: {backup_path.name}")
    log(f"Size: {backup_path.stat().st_size / 1024 / 1024:.1f} MB")
    log(f"Date: {datetime.fromtimestamp(backup_path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
    if args.skip:
        log(f"Skipping: {', '.join(args.skip)}")
    if args.dry_run:
        log("MODE: DRY RUN (no changes will be made)", "DRY")
    log("=" * 70)

    # SAFETY: Confirm with user
    if not args.dry_run and not args.yes:
        print()
        log("WARNING: This will DELETE existing PPS data and replace it!", "WARN")
        log("WARNING: All current conversations, memories, and state will be lost!", "WARN")
        print()

        if not prompt_confirmation("Are you ABSOLUTELY SURE you want to proceed?"):
            log("Restore cancelled by user")
            sys.exit(0)

        print()
        if not prompt_confirmation("Last chance - proceed with DESTRUCTIVE restore?"):
            log("Restore cancelled by user")
            sys.exit(0)

    # Create safety backup (unless disabled or dry-run)
    safety_backup = None
    if not args.dry_run and not args.no_safety_backup:
        safety_backup = backup_current_state(dry_run=args.dry_run)
        if safety_backup:
            log(f"Safety backup saved to: {safety_backup}", "OK")

    # Stop containers
    containers_stopped = stop_pps_containers(dry_run=args.dry_run)
    if not containers_stopped and not args.dry_run:
        log("Failed to stop containers - aborting restore", "ERROR")
        sys.exit(1)

    try:
        # Perform restore
        success = restore_from_archive(
            backup_path,
            dry_run=args.dry_run,
            skip_sources=args.skip or [],
        )

        if not success:
            log("Restore FAILED!", "ERROR")
            sys.exit(1)

    finally:
        # Always restart containers if we stopped them
        if containers_stopped:
            start_pps_containers(dry_run=args.dry_run)

    # Check health
    health = check_container_health(dry_run=args.dry_run)

    # Summary
    log("=" * 70)
    if args.dry_run:
        log("DRY RUN COMPLETE - No changes were made", "DRY")
        log("To perform actual restore, remove --dry-run flag")
    else:
        log("RESTORE COMPLETE", "OK")
        if safety_backup:
            log(f"Safety backup: {safety_backup}")
        if health.get("status") == "ok":
            log(f"Container health: {health['healthy']} healthy, {health['unhealthy']} unhealthy", "OK")
        else:
            log(f"Container health: {health.get('status', 'unknown')}", "WARN")
            log("Run 'docker compose ps' to check container status")
    log("=" * 70)


if __name__ == "__main__":
    main()
