#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
PPS Backup Script

Creates timestamped tar.gz archives of PPS data.
Designed for manual invocation (not cron) to avoid interference with ingestion.

Usage:
    python scripts/backup_pps.py                    # Use defaults
    python scripts/backup_pps.py --keep 10          # Keep 10 most recent
    python scripts/backup_pps.py --dry-run          # Show what would happen
    python scripts/backup_pps.py --backup-dir /path # Custom backup location
    python scripts/backup_pps.py --entity lyra      # Back up specific entity only
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

# =============================================================================
# CONFIGURATION
# =============================================================================

# Default backup directory (Windows path accessible from WSL)
DEFAULT_BACKUP_DIR = "/mnt/c/Users/Jeff/awareness_backups"

# Default number of backups to keep
DEFAULT_KEEP = 7

# Project root (where this script lives in scripts/)
PROJECT_ROOT = Path(__file__).parent.parent

# Docker compose location for stopping/starting PPS
DOCKER_COMPOSE_DIR = PROJECT_ROOT / "pps" / "docker"

# Shared infrastructure sources (not entity-specific)
SHARED_SOURCES = {
    # ChromaDB (rebuildable from word-photos on disk)
    "chromadb": {
        "path": PROJECT_ROOT / "docker" / "pps" / "chromadb_data",
        "patterns": ["**/*"],
        "critical": False,
    },
    # Neo4j/Graphiti (rebuildable from raw messages)
    "neo4j": {
        "path": PROJECT_ROOT / "docker" / "pps" / "neo4j_data",
        "patterns": ["**/*"],
        "critical": False,
    },
    # Haven (chat history + email archive — NOT rebuildable)
    "haven": {
        "path": PROJECT_ROOT / "haven" / "data",
        "patterns": ["*.db"],
        "critical": True,
    },
}


# =============================================================================
# ENTITY DISCOVERY
# =============================================================================

def discover_entity_sources(entity_filter: str | None = None) -> dict:
    """Discover all entity directories and build backup sources.

    Scans entities/ for subdirectories that have a data/ subdirectory.
    Skips directories starting with '_' (e.g. _template).

    Args:
        entity_filter: If given, only include this entity. If None, include all.

    Returns:
        Dict of source_name -> source_config, same format as SHARED_SOURCES.
    """
    sources = {}
    entities_dir = PROJECT_ROOT / "entities"

    if not entities_dir.exists():
        return sources

    for entity_dir in sorted(entities_dir.iterdir()):
        if not entity_dir.is_dir():
            continue
        if entity_dir.name.startswith("_"):  # Skip _template and similar
            continue
        if not (entity_dir / "data").exists():
            continue

        name = entity_dir.name

        # Apply entity filter if specified
        if entity_filter is not None and name != entity_filter:
            continue

        # SQLite databases (CRITICAL)
        sources[f"{name}_sqlite"] = {
            "path": entity_dir / "data",
            "patterns": ["*.db"],
            "critical": True,
        }

        # Identity files (CRITICAL)
        sources[f"{name}_identity"] = {
            "path": entity_dir,
            "patterns": [
                "identity.md",
                "relationships.md",
                "active_agency_framework.md",
                ".entity_token",       # auth token (hidden file)
                "growth_notes.md",     # Jeff's coaching notes
                "goals.md",            # sovereignty tracking
                "current_scene.md",    # current scene state
            ],
            "critical": True,
        }

        # Crystals (CRITICAL) - only if directory exists
        if (entity_dir / "crystals").exists():
            sources[f"{name}_crystals"] = {
                "path": entity_dir / "crystals",
                "patterns": ["**/*.md"],
                "critical": True,
            }

        # Word photos (CRITICAL) - only if directory exists
        if (entity_dir / "memories" / "word_photos").exists():
            sources[f"{name}_word_photos"] = {
                "path": entity_dir / "memories" / "word_photos",
                "patterns": ["*.md"],
                "critical": True,
            }

        # Journals (CRITICAL) - reflection logs, not rebuildable
        if (entity_dir / "journals").exists():
            sources[f"{name}_journals"] = {
                "path": entity_dir / "journals",
                "patterns": ["**/*.md"],
                "critical": True,
            }

        # Notebooks (CRITICAL) - essays, working notes, not rebuildable
        if (entity_dir / "notebook").exists():
            sources[f"{name}_notebook"] = {
                "path": entity_dir / "notebook",
                "patterns": ["**/*.md"],
                "critical": True,
            }

    return sources


def build_backup_sources(entity_filter: str | None = None) -> dict:
    """Build the full set of backup sources for the given run.

    Args:
        entity_filter: If given, only include this entity's sources (plus shared).
                       If None, include all entities.

    Returns:
        Combined dict of source_name -> source_config.
    """
    entity_sources = discover_entity_sources(entity_filter)
    return {**SHARED_SOURCES, **entity_sources}


# =============================================================================
# FUNCTIONS
# =============================================================================

def log(msg: str, level: str = "INFO"):
    """Simple logging with timestamp.

    flush=True so an unattended/backgrounded run streams to its logfile and
    journald in real time — block-buffered stdout otherwise hides all progress
    until the process exits (observed during the 2026-08-20 live test).
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}", flush=True)


def get_backup_filename() -> str:
    """Generate timestamped backup filename."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"pps_backup_{timestamp}.tar.gz"


# ---- Docker Compose helpers (stack control + per-container verification) ----

def _compose(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a `docker compose <args>` command in the PPS compose directory."""
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=DOCKER_COMPOSE_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _compose_ps() -> list[dict]:
    """Return parsed `docker compose ps -a` rows.

    Handles both the JSON-array and newline-delimited-JSON (JSONL) shapes that
    different Compose versions emit. Each row has at least Service/State/Health.
    """
    try:
        result = _compose("ps", "-a", "--format", "json", timeout=30)
    except Exception as e:
        log(f"  Could not query container status: {e}", "WARN")
        return []
    out = (result.stdout or "").strip()
    if not out:
        return []
    try:
        parsed = json.loads(out)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        rows = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return rows


def _service_names() -> list[str]:
    """All service names declared in the compose file (authoritative expected set)."""
    try:
        result = _compose("config", "--services", timeout=30)
        return sorted(s.strip() for s in result.stdout.splitlines() if s.strip())
    except Exception:
        return []


def _verify_stack_running(require_healthy: bool = True) -> tuple[bool, dict]:
    """Check every compose service is running (and healthy if it declares a
    healthcheck).

    Returns (all_ok, {service: {ok, state, health}}). A service with no
    healthcheck (Health == "") is OK as long as it is running; one that
    declares a healthcheck must report "healthy", not "starting"/"unhealthy".
    """
    expected = set(_service_names())
    rows: dict[str, dict] = {}
    for row in _compose_ps():
        svc = row.get("Service")
        if not svc:
            continue
        state = row.get("State", "") or ""
        health = row.get("Health", "") or ""
        ok = state == "running"
        if require_healthy and health and health != "healthy":
            ok = False
        rows[svc] = {"ok": ok, "state": state, "health": health}
    report = {
        svc: rows.get(svc, {"ok": False, "state": "absent", "health": ""})
        for svc in expected
    }
    all_ok = bool(report) and all(v["ok"] for v in report.values())
    return all_ok, report


def _alert_restart_failure(bad_services: list[str]) -> None:
    """Loudly alert Jeff when the stack does NOT come back after a backup.
    An unattended restart failure means PPS (memory) is down until noticed."""
    msg = ("PPS backup: stack did NOT restart clean. "
           f"Down/unhealthy: {', '.join(bad_services) or 'unknown'}")
    log(msg, "ERROR")
    try:
        notify = PROJECT_ROOT / "scripts" / "notify.py"
        if notify.exists():
            subprocess.run(
                ["python3", str(notify), "--title", "🔴 PPS BACKUP",
                 "--priority", "urgent", msg],
                timeout=30, capture_output=True,
            )
    except Exception as e:
        log(f"  (could not send ntfy alert: {e})", "WARN")


def stop_pps_containers(dry_run: bool = False) -> bool:
    """Stop the PPS stack and CONFIRM every container reached a stopped state
    before returning.

    Returns True only when the stack is verified down. The caller must not tar
    the data volumes otherwise — a still-running database is an inconsistent
    capture (see docs/neo4j-data-loss-2026-03-07.md).
    """
    log("Stopping PPS containers...")
    if dry_run:
        log("  (dry-run: would stop containers)", "DRY")
        return True

    try:
        result = _compose("stop", "-t", "30", timeout=120)
        if result.returncode != 0:
            # Don't bail yet — some containers may have stopped; the verify
            # loop below is the source of truth.
            log(f"  compose stop returned nonzero: {result.stderr.strip()}", "WARN")
    except Exception as e:
        log(f"  Error stopping containers: {e}", "ERROR")
        return False

    # Verify: poll until nothing is still running/restarting/paused.
    deadline = time.monotonic() + 90
    while True:
        still_up = [r for r in _compose_ps()
                    if r.get("State") in ("running", "restarting", "paused")]
        if not still_up:
            break
        if time.monotonic() > deadline:
            names = ", ".join(f"{r.get('Service')}={r.get('State')}" for r in still_up)
            log(f"  TIMEOUT — containers still not stopped: {names}", "ERROR")
            return False
        time.sleep(2)

    # Brief grace so WSL2 NTFS bind-mount writes flush before we read the files.
    time.sleep(5)
    log("  All containers confirmed stopped")
    return True


def start_pps_containers(dry_run: bool = False) -> bool:
    """Restart the PPS stack robustly and CONFIRM the whole stack is up+healthy.

    Hardening over a bare `docker compose up -d` (validated 2026-08-20):
      * --force-recreate re-stages bind mounts, curing the WSL2 single-file
        bind-mount staleness that made caddy (and, latently, neo4j's entrypoint
        script) fail to start after a stop.
      * --wait blocks until healthchecked services report healthy, so a slow
        neo4j (~90s start_period) isn't mistaken for failure, and a leaf
        create-failure can't silently orphan the health-gated dependents
        (graphiti / pps-lyra / pps-caia) the way a bare `up` did.
      * An explicit per-container verify catches services without a healthcheck
        and retries force-recreate once on any straggler.

    Returns True only when every service is confirmed running/healthy.
    """
    log("Starting PPS containers...")
    if dry_run:
        log("  (dry-run: would start containers)", "DRY")
        return True

    # Generous wrapper timeout: neo4j health start_period (90s) + dependent
    # chain (graphiti 30s, pps-* 75s) can serialize to a few minutes.
    try:
        result = _compose("up", "-d", "--force-recreate", "--wait",
                          "--wait-timeout", "300", timeout=360)
        if result.returncode != 0:
            log(f"  compose up --wait returned nonzero: {result.stderr.strip()}", "WARN")
    except subprocess.TimeoutExpired:
        log("  compose up --wait exceeded wrapper timeout (360s)", "WARN")
    except Exception as e:
        log(f"  Error starting containers: {e}", "ERROR")

    ok, report = _verify_stack_running(require_healthy=True)
    if not ok:
        bad = sorted(s for s, st in report.items() if not st["ok"])
        log(f"  Stragglers after first start: {bad} — retrying force-recreate", "WARN")
        try:
            _compose("up", "-d", "--force-recreate", "--wait",
                     "--wait-timeout", "180", *bad, timeout=240)
        except Exception as e:
            log(f"  retry error: {e}", "WARN")
        ok, report = _verify_stack_running(require_healthy=True)

    for svc, st in sorted(report.items()):
        mark = "OK " if st["ok"] else "BAD"
        log(f"    [{mark}] {svc}: state={st['state']} health={st['health'] or 'n/a'}")

    if ok:
        log("  All containers confirmed running/healthy")
    else:
        bad = sorted(s for s, st in report.items() if not st["ok"])
        _alert_restart_failure(bad)
    return ok


def collect_files(source_config: dict) -> list[Path]:
    """Collect files matching patterns from a source."""
    files = []
    path = Path(source_config["path"])

    if not path.exists():
        return files

    for pattern in source_config["patterns"]:
        if "**" in pattern:
            # Recursive glob
            files.extend(path.glob(pattern))
        else:
            # Non-recursive
            files.extend(path.glob(pattern))

    return [f for f in files if f.is_file()]


def create_backup(backup_dir: Path, backup_sources: dict, dry_run: bool = False) -> tuple[Path | None, dict]:
    """Create a tar.gz backup of all PPS data.

    Args:
        backup_dir: Directory to write the archive into.
        backup_sources: Dict of source_name -> source_config to back up.
        dry_run: If True, collect stats only without writing.

    Returns:
        Tuple of (backup_path, stats_dict)
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_filename = get_backup_filename()
    backup_path = backup_dir / backup_filename

    stats = {
        "sources": {},
        "total_files": 0,
        "total_bytes": 0,
    }

    log(f"Creating backup: {backup_path}")

    if dry_run:
        # Just collect stats
        for name, config in backup_sources.items():
            files = collect_files(config)
            size = sum(f.stat().st_size for f in files)
            stats["sources"][name] = {"files": len(files), "bytes": size}
            stats["total_files"] += len(files)
            stats["total_bytes"] += size
            critical = "CRITICAL" if config["critical"] else "optional"
            log(f"  [{critical}] {name}: {len(files)} files, {size:,} bytes", "DRY")
        return None, stats

    # Actually create the archive
    with tarfile.open(backup_path, "w:gz") as tar:
        for name, config in backup_sources.items():
            files = collect_files(config)
            source_path = Path(config["path"])

            for f in files:
                # Create archive path preserving structure
                arcname = f"{name}/{f.relative_to(source_path)}"
                tar.add(f, arcname=arcname)

            size = sum(f.stat().st_size for f in files)
            stats["sources"][name] = {"files": len(files), "bytes": size}
            stats["total_files"] += len(files)
            stats["total_bytes"] += size

            critical = "CRITICAL" if config["critical"] else "optional"
            log(f"  [{critical}] {name}: {len(files)} files, {size:,} bytes")

    # Get final archive size
    archive_size = backup_path.stat().st_size
    stats["archive_bytes"] = archive_size
    compression_ratio = (1 - archive_size / stats["total_bytes"]) * 100 if stats["total_bytes"] > 0 else 0

    log(f"  Archive size: {archive_size:,} bytes ({compression_ratio:.1f}% compression)")

    return backup_path, stats


def verify_backup(backup_path: Path, backup_sources: dict) -> bool:
    """Verify backup archive integrity."""
    log(f"Verifying backup integrity...")

    try:
        with tarfile.open(backup_path, "r:gz") as tar:
            # List all members to verify archive is readable
            members = tar.getmembers()
            log(f"  Archive contains {len(members)} entries")

            # Check for critical sources
            critical_found = set()
            for member in members:
                source = member.name.split("/")[0]
                if source in backup_sources and backup_sources[source]["critical"]:
                    critical_found.add(source)

            critical_sources = {name for name, cfg in backup_sources.items() if cfg["critical"]}
            missing = critical_sources - critical_found

            if missing:
                log(f"  WARNING: Missing critical sources: {missing}", "WARN")
                return False

            log(f"  All critical sources present: {critical_found}")
            return True

    except Exception as e:
        log(f"  Verification failed: {e}", "ERROR")
        return False


def cleanup_old_backups(backup_dir: Path, keep: int, dry_run: bool = False) -> int:
    """Remove old backups, keeping only the most recent N."""
    log(f"Cleaning up old backups (keeping {keep})...")

    # Find all backup files
    backups = sorted(
        backup_dir.glob("pps_backup_*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,  # Newest first
    )

    to_delete = backups[keep:]

    if not to_delete:
        log(f"  No old backups to remove ({len(backups)} total)")
        return 0

    deleted = 0
    for backup in to_delete:
        if dry_run:
            log(f"  (dry-run: would delete {backup.name})", "DRY")
        else:
            backup.unlink()
            log(f"  Deleted: {backup.name}")
        deleted += 1

    return deleted


def get_last_backup_age(backup_dir: Path) -> int | None:
    """Get age of most recent backup in days. Returns None if no backups exist."""
    backups = sorted(
        backup_dir.glob("pps_backup_*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not backups:
        return None

    newest = backups[0]
    age_seconds = datetime.now().timestamp() - newest.stat().st_mtime
    return int(age_seconds / 86400)


def check_backup_health(backup_dir: Path) -> dict:
    """Check backup health status for monitoring."""
    backup_dir = Path(backup_dir)

    if not backup_dir.exists():
        return {"status": "ERROR", "message": "Backup directory does not exist"}

    backups = list(backup_dir.glob("pps_backup_*.tar.gz"))

    if not backups:
        return {"status": "WARNING", "message": "No backups found!", "days_since_backup": None}

    age_days = get_last_backup_age(backup_dir)

    if age_days is not None and age_days >= 7:
        return {
            "status": "WARNING",
            "message": f"Last backup is {age_days} days old - backup recommended!",
            "days_since_backup": age_days,
            "backup_count": len(backups),
        }

    return {
        "status": "OK",
        "message": f"Last backup {age_days} days ago",
        "days_since_backup": age_days,
        "backup_count": len(backups),
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Backup PPS data to timestamped tar.gz archive",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/backup_pps.py                    # Create backup with defaults
    python scripts/backup_pps.py --dry-run          # Preview without creating
    python scripts/backup_pps.py --keep 14          # Keep 14 backups
    python scripts/backup_pps.py --no-stop          # Don't stop containers
    python scripts/backup_pps.py --check            # Check backup health only
    python scripts/backup_pps.py --entity lyra      # Back up specific entity only
        """,
    )

    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path(DEFAULT_BACKUP_DIR),
        help=f"Backup directory (default: {DEFAULT_BACKUP_DIR})",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=DEFAULT_KEEP,
        help=f"Number of backups to keep (default: {DEFAULT_KEEP})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be backed up without creating archive",
    )
    parser.add_argument(
        "--no-stop",
        action="store_true",
        help="Don't stop PPS containers (use if you know nothing is writing)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check backup health status, don't create backup",
    )
    parser.add_argument(
        "--entity",
        default="all",
        metavar="NAME",
        help="Back up a specific entity only (default: all). E.g. --entity lyra",
    )

    args = parser.parse_args()

    # Health check mode
    if args.check:
        health = check_backup_health(args.backup_dir)
        print(f"Backup Status: {health['status']}")
        print(f"  {health['message']}")
        if health.get("backup_count"):
            print(f"  Total backups: {health['backup_count']}")
        sys.exit(0 if health["status"] == "OK" else 1)

    # Build the set of sources for this run
    entity_filter = None if args.entity == "all" else args.entity
    backup_sources = build_backup_sources(entity_filter)

    if entity_filter is not None and not any(
        k.startswith(f"{entity_filter}_") for k in backup_sources
    ):
        log(f"No entity '{entity_filter}' found in entities/ with a data/ directory.", "ERROR")
        sys.exit(1)

    # Banner
    log("=" * 60)
    log("PPS BACKUP")
    log("=" * 60)
    log(f"Backup directory: {args.backup_dir}")
    log(f"Keep backups: {args.keep}")
    log(f"Entity filter: {args.entity}")
    if args.dry_run:
        log("MODE: DRY RUN (no changes will be made)", "DRY")

    # Stop containers unless --no-stop
    containers_stopped = False
    if not args.no_stop:
        containers_stopped = stop_pps_containers(dry_run=args.dry_run)

    try:
        # Safety gate: if we meant to stop the stack but couldn't CONFIRM it is
        # down, do NOT tar — a live database is an inconsistent capture. The
        # finally block still runs and brings the stack back up.
        if not args.no_stop and not args.dry_run and not containers_stopped:
            log("Stop not confirmed (containers may still be running) — ABORTING "
                "backup to avoid an inconsistent capture.", "ERROR")
            sys.exit(1)

        # Create backup
        backup_path, stats = create_backup(args.backup_dir, backup_sources, dry_run=args.dry_run)

        # Verify backup (skip if dry run)
        if backup_path and not args.dry_run:
            if not verify_backup(backup_path, backup_sources):
                log("Backup verification FAILED!", "ERROR")
                sys.exit(1)

        # Cleanup old backups
        cleanup_old_backups(args.backup_dir, args.keep, dry_run=args.dry_run)

        # Summary
        log("=" * 60)
        log("BACKUP COMPLETE")
        log(f"  Total files: {stats['total_files']}")
        log(f"  Total size: {stats['total_bytes']:,} bytes ({stats['total_bytes'] / 1024 / 1024:.1f} MB)")
        if backup_path:
            log(f"  Archive: {backup_path}")
            log(f"  Archive size: {stats.get('archive_bytes', 0):,} bytes ({stats.get('archive_bytes', 0) / 1024 / 1024:.1f} MB)")
        log("=" * 60)

    finally:
        # Always bring the stack back if we attempted to stop it — gated on
        # not-no_stop, NOT on containers_stopped, so a partial/failed stop can
        # never leave the stack down. Restart is force-recreate + health-
        # verified and idempotent, so it's safe to run even on the abort path.
        if not args.no_stop:
            start_pps_containers(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
