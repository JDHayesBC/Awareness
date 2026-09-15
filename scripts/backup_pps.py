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
    python scripts/backup_pps.py --fast-backup      # Stop only neo4j+graphiti (~1-2 min dark vs ~15 min)
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


def _alert_verify_failure(backup_path: Path, reason: str) -> None:
    """Loudly alert Jeff when backup verification fails (issue #333).

    A failed verification is WORSE than a missing backup — it means something
    was written but is corrupt or short, and may silently replace a good archive
    in the rotation.  entity/ is gitignored; this archive is the only safety net
    for crystals, word-photos, memories, and journals.
    """
    size_mb = backup_path.stat().st_size / 1024 / 1024 if backup_path.exists() else 0
    msg = (
        f"PPS backup FAILED verification: {backup_path.name} "
        f"({size_mb:.0f} MB). Reason: {reason}. "
        f"Entity data (crystals/memories/journals) is NOT safely backed up."
    )
    log(msg, "ERROR")
    try:
        notify = PROJECT_ROOT / "scripts" / "notify.py"
        if notify.exists():
            subprocess.run(
                ["python3", str(notify), "--title", "🔴 BACKUP FAILED",
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


def _neo4j_service_names() -> list[str]:
    """Return the compose service names containing 'neo4j' or 'graphiti'.

    Discovered at runtime from `docker compose ps` so we never hardcode names
    that may differ per entity or compose file revision.
    """
    names = []
    for row in _compose_ps():
        svc = row.get("Service", "")
        if svc and ("neo4j" in svc.lower() or "graphiti" in svc.lower()):
            names.append(svc)
    if not names:
        # Fallback: query config in case nothing is running yet
        for svc in _service_names():
            if "neo4j" in svc.lower() or "graphiti" in svc.lower():
                names.append(svc)
    return sorted(set(names))


def stop_neo4j_containers(dry_run: bool = False) -> bool:
    """Stop only the neo4j + graphiti containers and confirm they are down.

    Used by --fast-backup: the rest of the PPS stack stays live.  The caller
    logs the start of the dark window for timing purposes.

    Returns True only when all targeted services are confirmed stopped.
    """
    targets = _neo4j_service_names()
    if not targets:
        log("  No neo4j/graphiti services found in compose ps — nothing to stop", "WARN")
        return False

    log(f"Stopping neo4j/graphiti containers: {targets}")
    if dry_run:
        log("  (dry-run: would stop neo4j/graphiti containers)", "DRY")
        return True

    try:
        result = _compose("stop", "-t", "30", *targets, timeout=120)
        if result.returncode != 0:
            log(f"  compose stop returned nonzero: {result.stderr.strip()}", "WARN")
    except Exception as e:
        log(f"  Error stopping neo4j/graphiti: {e}", "ERROR")
        return False

    # Poll until targeted services are confirmed stopped.
    deadline = time.monotonic() + 90
    while True:
        still_up = [
            r for r in _compose_ps()
            if r.get("Service") in targets
            and r.get("State") in ("running", "restarting", "paused")
        ]
        if not still_up:
            break
        if time.monotonic() > deadline:
            names = ", ".join(
                f"{r.get('Service')}={r.get('State')}" for r in still_up
            )
            log(f"  TIMEOUT — neo4j/graphiti still not stopped: {names}", "ERROR")
            return False
        time.sleep(2)

    # Brief grace for WSL2 NTFS bind-mount flush.
    time.sleep(3)
    log(f"  neo4j/graphiti containers confirmed stopped: {targets}")
    return True


def start_neo4j_containers(dry_run: bool = False) -> bool:
    """Restart only the neo4j + graphiti containers and verify they come up healthy.

    Used by --fast-backup to end the memory-dark window before the slow tar step.
    Returns True only when all targeted services are running/healthy.
    """
    targets = _neo4j_service_names()
    if not targets:
        # Nothing to start is not a hard failure — just warn and return True so
        # the caller can continue with the tar phase.
        log("  No neo4j/graphiti services to restart — skipping", "WARN")
        return True

    log(f"Starting neo4j/graphiti containers: {targets}")
    if dry_run:
        log("  (dry-run: would start neo4j/graphiti containers)", "DRY")
        return True

    try:
        # --wait blocks until healthchecked services report healthy; neo4j's
        # health start_period is 90s so we allow 300s.
        result = _compose(
            "up", "-d", "--wait", "--wait-timeout", "300", *targets, timeout=360
        )
        if result.returncode != 0:
            log(
                f"  compose up --wait returned nonzero: {result.stderr.strip()}", "WARN"
            )
    except subprocess.TimeoutExpired:
        log("  compose up --wait exceeded wrapper timeout (360s)", "WARN")
    except Exception as e:
        log(f"  Error starting neo4j/graphiti: {e}", "ERROR")

    # Per-container verify (same pattern as start_pps_containers).
    rows = {r.get("Service"): r for r in _compose_ps() if r.get("Service") in targets}
    all_ok = True
    for svc in targets:
        row = rows.get(svc, {})
        state = row.get("State", "absent")
        health = row.get("Health", "") or ""
        ok = state == "running" and (not health or health == "healthy")
        mark = "OK " if ok else "BAD"
        log(f"    [{mark}] {svc}: state={state} health={health or 'n/a'}")
        if not ok:
            all_ok = False

    if all_ok:
        log("  neo4j/graphiti containers confirmed running/healthy")
    else:
        bad = [s for s in targets if not rows.get(s, {}).get("State") == "running"]
        _alert_restart_failure(bad or targets)
    return all_ok


def copy_neo4j_staging(
    neo4j_data_path: Path,
    backup_dir: Path,
    dry_run: bool = False,
) -> Path:
    """Copy neo4j_data to a local staging directory for offline tar-ing.

    Using shutil.copytree avoids the slow cross-mount compression that occurs
    when neo4j_data is tarred directly over the WSL2 /mnt/c bind mount.

    The staging dir is named ``neo4j_staging_<timestamp>`` inside backup_dir.
    The CALLER is responsible for cleaning it up (try/finally in main()).

    Args:
        neo4j_data_path: Absolute path to the live neo4j_data volume directory.
        backup_dir: Parent directory for the staging copy.
        dry_run: If True, log intent but do not copy.

    Returns:
        Path to the staging directory (even in dry-run mode, for logging).
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    staging_dir = backup_dir / f"neo4j_staging_{timestamp}"
    staging_neo4j = staging_dir / "neo4j_data"

    log(f"Copying neo4j_data to staging: {staging_neo4j}")
    if dry_run:
        log("  (dry-run: would copy neo4j_data to staging)", "DRY")
        return staging_dir

    if not neo4j_data_path.exists():
        log(f"  neo4j_data path does not exist: {neo4j_data_path}", "WARN")
        staging_dir.mkdir(parents=True, exist_ok=True)
        return staging_dir

    t0 = time.monotonic()
    shutil.copytree(str(neo4j_data_path), str(staging_neo4j))
    elapsed = time.monotonic() - t0

    size_bytes = sum(f.stat().st_size for f in staging_neo4j.rglob("*") if f.is_file())
    log(
        f"  Staging copy complete: {size_bytes / 1024 / 1024:.1f} MB "
        f"in {elapsed:.1f}s  →  {staging_dir}"
    )
    return staging_dir


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


def create_backup(
    backup_dir: Path,
    backup_sources: dict,
    dry_run: bool = False,
    staging_neo4j: Path | None = None,
) -> tuple[Path | None, dict]:
    """Create a tar.gz backup of all PPS data.

    Args:
        backup_dir: Directory to write the archive into.
        backup_sources: Dict of source_name -> source_config to back up.
        dry_run: If True, collect stats only without writing.
        staging_neo4j: When set (--fast-backup path), neo4j files are read from
            ``staging_neo4j / "neo4j_data"`` instead of the live volume path.
            The staging directory is created by copy_neo4j_staging() while the
            stack is still stopped; by the time this function runs the stack is
            live again, so the staging copy is the safe consistent snapshot.

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
    if staging_neo4j is not None:
        log(f"  (neo4j source: staging at {staging_neo4j})")

    # Build an effective source map: redirect the "neo4j" source to the
    # staging copy when one is provided.  All other sources are unchanged.
    effective_sources: dict = {}
    for name, config in backup_sources.items():
        if staging_neo4j is not None and name == "neo4j":
            staged_path = staging_neo4j / "neo4j_data"
            effective_sources[name] = {**config, "path": staged_path}
        else:
            effective_sources[name] = config

    if dry_run:
        # Just collect stats
        for name, config in effective_sources.items():
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
        for name, config in effective_sources.items():
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


def verify_backup(backup_path: Path, backup_sources: dict,
                  size_floor_ratio: float = 0.60) -> tuple[bool, str]:
    """Verify backup archive integrity.

    Args:
        backup_path: The archive to verify.
        backup_sources: Source config dict (used to identify critical sources).
        size_floor_ratio: Reject the archive if it is smaller than this fraction
            of the most recent PRIOR backup in the same directory.  Default 0.60
            (60%) catches the kind of half-size corruption seen in issue #333
            while tolerating normal day-to-day variation.  Pass 0.0 to disable
            the size check.

    Returns:
        (ok, reason) — reason is a human-readable string; empty when ok=True.
    """
    log(f"Verifying backup integrity...")

    # ── size sanity: compare against the most recent prior backup ─────────────
    if size_floor_ratio > 0:
        backup_dir = backup_path.parent
        prior_backups = sorted(
            [p for p in backup_dir.glob("pps_backup_*.tar.gz") if p != backup_path],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if prior_backups:
            prev = prior_backups[0]
            new_bytes = backup_path.stat().st_size
            prev_bytes = prev.stat().st_size
            ratio = new_bytes / prev_bytes if prev_bytes else 1.0
            log(
                f"  Size: {new_bytes / 1024 / 1024:.1f} MB "
                f"vs prior {prev.name}: {prev_bytes / 1024 / 1024:.1f} MB "
                f"(ratio {ratio:.2f})"
            )
            if ratio < size_floor_ratio:
                reason = (
                    f"archive is {ratio:.0%} of prior backup "
                    f"({new_bytes / 1024 / 1024:.0f} MB vs "
                    f"{prev_bytes / 1024 / 1024:.0f} MB) — "
                    f"below floor of {size_floor_ratio:.0%}"
                )
                log(f"  FAIL: {reason}", "ERROR")
                return False, reason
        else:
            log("  No prior backup found — skipping size comparison")

    # ── content check: all critical sources present ────────────────────────────
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
                reason = f"missing critical sources: {missing}"
                log(f"  FAIL: {reason}", "WARN")
                return False, reason

            log(f"  All critical sources present: {critical_found}")
            return True, ""

    except Exception as e:
        reason = f"archive unreadable: {e}"
        log(f"  Verification failed: {e}", "ERROR")
        return False, reason


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

def check_sources_ready(backup_sources: dict) -> tuple[bool, list[str]]:
    """Verify critical sources exist and contain expected files before backup.

    Catches the WSL2 bind-mount-not-ready failure mode: after an overnight NUC
    restart, mount-points are visible but empty because the underlying filesystem
    hasn't been mounted yet. Without this guard, the backup proceeds silently and
    produces an incomplete archive that looks valid from the outside.

    Observed: 2026-09-15 08:29 AM timer fire after NUC restart → 871MB archive
    (chromadb + partial neo4j only; entity SQLite and Haven data absent). GH#335.

    Args:
        backup_sources: Dict of source_name -> source_config.

    Returns:
        (all_ok, list_of_failure_messages). Caller should abort if not ok.
    """
    failures = []
    for name, config in backup_sources.items():
        if not config.get("critical"):
            continue
        path = Path(config["path"])
        if not path.exists():
            failures.append(f"  MISSING: {name}: path does not exist: {path}")
            continue
        files = collect_files(config)
        if not files:
            failures.append(
                f"  EMPTY: {name}: path exists but 0 matching files at {path} "
                f"(patterns: {config['patterns']}) "
                f"— WSL2 bind-mount may not be ready yet"
            )
    return (len(failures) == 0, failures)


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
    parser.add_argument(
        "--fast-backup",
        action="store_true",
        help=(
            "Stop only neo4j+graphiti containers, copy neo4j_data to a local "
            "staging dir, restart neo4j immediately, then tar from staging while "
            "the full stack is live. Reduces memory-dark time from ~15 min to "
            "~1-2 min. DEFAULT behavior (stop-all) is unchanged unless this flag "
            "is passed."
        ),
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
    if args.fast_backup:
        log("MODE: FAST BACKUP (stop neo4j+graphiti only; rest of stack stays live)")
    if args.dry_run:
        log("MODE: DRY RUN (no changes will be made)", "DRY")

    # Path-readiness guard (GH#335): verify critical sources before touching
    # any containers. Catches the WSL2-bind-mount-not-ready failure mode where
    # paths are visible but empty after an overnight NUC restart.
    ready, path_failures = check_sources_ready(backup_sources)
    if not ready:
        log("ABORTING: one or more critical backup sources are empty or missing.", "ERROR")
        log("This is the WSL2 bind-mount-not-ready failure mode (see GH#335).", "ERROR")
        log("Check that the stack is fully up and entity data is accessible:", "ERROR")
        for failure in path_failures:
            log(failure, "ERROR")
        try:
            import subprocess as _sp
            _sp.run(
                [
                    "python3",
                    str(PROJECT_ROOT / "scripts" / "notify.py"),
                    "--title", "PPS Backup ABORTED",
                    "--priority", "high",
                    "Critical backup sources empty — WSL2 bind-mounts not ready? "
                    "Run backup manually after verifying entity data is accessible.",
                ],
                timeout=10,
            )
        except Exception:
            pass
        sys.exit(1)

    # ---- Fast-backup path -------------------------------------------------------
    if args.fast_backup and not args.no_stop:
        neo4j_data_path: Path = SHARED_SOURCES["neo4j"]["path"]
        staging: Path | None = None

        dark_start = time.monotonic()
        log(f"[FAST-BACKUP] Memory-dark window START: {datetime.now().strftime('%H:%M:%S')}")

        neo4j_stopped = stop_neo4j_containers(dry_run=args.dry_run)

        try:
            if not args.dry_run and not neo4j_stopped:
                log(
                    "[FAST-BACKUP] neo4j/graphiti stop not confirmed — ABORTING "
                    "to avoid an inconsistent capture.",
                    "ERROR",
                )
                sys.exit(1)

            # Copy neo4j_data while the databases are stopped.
            staging = copy_neo4j_staging(neo4j_data_path, args.backup_dir, dry_run=args.dry_run)

        finally:
            # Restart neo4j BEFORE tarring — this ends the dark window.
            start_neo4j_containers(dry_run=args.dry_run)
            dark_elapsed = time.monotonic() - dark_start
            log(
                f"[FAST-BACKUP] Memory-dark window END: {datetime.now().strftime('%H:%M:%S')} "
                f"(elapsed {dark_elapsed:.1f}s / {dark_elapsed / 60:.1f} min)"
            )

        # Tar from the staging copy while the stack is fully live.
        try:
            backup_path, stats = create_backup(
                args.backup_dir,
                backup_sources,
                dry_run=args.dry_run,
                staging_neo4j=staging,
            )

            if backup_path and not args.dry_run:
                ok, reason = verify_backup(backup_path, backup_sources)
                if not ok:
                    log(f"Backup verification FAILED: {reason}", "ERROR")
                    _alert_verify_failure(backup_path, reason)
                    sys.exit(1)

            cleanup_old_backups(args.backup_dir, args.keep, dry_run=args.dry_run)

        finally:
            # Always clean up the staging directory, success or failure.
            if staging is not None and not args.dry_run and staging.exists():
                log(f"[FAST-BACKUP] Removing staging dir: {staging}")
                shutil.rmtree(staging, ignore_errors=True)

    # ---- Default path (stop-all) — COMPLETELY UNCHANGED -------------------------
    else:
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
                ok, reason = verify_backup(backup_path, backup_sources)
                if not ok:
                    log(f"Backup verification FAILED: {reason}", "ERROR")
                    _alert_verify_failure(backup_path, reason)
                    sys.exit(1)

            # Cleanup old backups
            cleanup_old_backups(args.backup_dir, args.keep, dry_run=args.dry_run)

        finally:
            # Always bring the stack back if we attempted to stop it — gated on
            # not-no_stop, NOT on containers_stopped, so a partial/failed stop can
            # never leave the stack down. Restart is force-recreate + health-
            # verified and idempotent, so it's safe to run even on the abort path.
            if not args.no_stop:
                start_pps_containers(dry_run=args.dry_run)

    # ---- Summary (shared) -------------------------------------------------------
    log("=" * 60)
    log("BACKUP COMPLETE")
    log(f"  Total files: {stats['total_files']}")
    log(f"  Total size: {stats['total_bytes']:,} bytes ({stats['total_bytes'] / 1024 / 1024:.1f} MB)")
    if backup_path:
        log(f"  Archive: {backup_path}")
        log(f"  Archive size: {stats.get('archive_bytes', 0):,} bytes ({stats.get('archive_bytes', 0) / 1024 / 1024:.1f} MB)")
    log("=" * 60)


if __name__ == "__main__":
    main()
