#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
PPS Backup Validation

Issue #317: nothing previously proved that a nightly `backup_pps.py` archive
was actually *restorable* — only that it was *created*. An unvalidated backup
is Schrodinger's backup: you find out it's torn/truncated/empty only at the
moment you desperately need it.

This script picks the most recent backup (or a given one), extracts it to a
scratch directory, and proves it's non-corrupt and restorable:

  1. Archive integrity  — a full sequential read of the tar.gz. tarfile/gzip
     validates the stream CRC at EOF, so a truncated/torn file raises here
     rather than silently returning a partial member list.
  2. Per-SQLite integrity — for every *.db file under the entity `_sqlite`
     sources and `haven`, run `PRAGMA integrity_check` and `PRAGMA
     quick_check` against the EXTRACTED copy (never touches the live db).
  3. Row-count sanity — for a set of "crown jewel" tables (messages,
     message_summaries, rooms, users, ...), compare the backup's row count
     against the LIVE db's: backup must be <= live (a backup can't have more
     rows than history contains) and >= 90% of live (catches a "valid but
     stale/near-empty" backup, not just a well-formed one).
  4. ChromaDB — best-effort: open the extracted copy with chromadb's
     PersistentClient and count collections/items. Non-fatal (chromadb is
     explicitly non-critical/rebuildable in backup_pps.py) — a failure here
     is reported as a WARN, not a hard FAIL.
  5. Critical-source presence — re-derive backup_pps.py's own critical-source
     check independently (every `*_sqlite`, `*_identity`, `*_crystals`,
     `*_word_photos`, `*_journals`, `*_notebook`, and `haven` source must be
     present in the archive).

Writes a one-line verdict to ~/.claude/data/backup_validation.json:
    {"ts": "...", "backup": "...", "ok": true/false, "checks": [...], "errors": [...]}

Exits 0 on success, 1 on any hard failure.

Usage:
    python3 scripts/validate_backup.py                  # validate newest backup
    python3 scripts/validate_backup.py --backup PATH    # validate a specific archive
    python3 scripts/validate_backup.py --dry-run        # show plan, don't extract/check
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# =============================================================================
# CONFIGURATION (mirrors backup_pps.py / restore_pps.py — keep in sync)
# =============================================================================

DEFAULT_BACKUP_DIR = Path("/mnt/c/Users/Jeff/awareness_backups")
PROJECT_ROOT = Path(__file__).parent.parent

# NOTE: ~/.claude/data/ is root-owned on this host (same issue documented for
# sl_shop_cache — see reference_sl_shop_tool.md), so a jeff-run script can't
# write there. Fall back to ~/.claude/ directly (jeff-owned), which is the
# same established workaround pattern.
_PREFERRED_VERDICT_PATH = Path.home() / ".claude" / "data" / "backup_validation.json"
_FALLBACK_VERDICT_PATH = Path.home() / ".claude" / "backup_validation.json"

# Row-count sanity: backup must have at least this fraction of the live count.
MIN_ROW_RATIO = 0.90

# "Crown jewel" tables worth a row-count sanity check, if present.
WATCH_TABLES = [
    "messages",
    "message_summaries",
    "rooms",
    "users",
    "room_members",
    "claims",
    "graphiti_batches",
]

# Suffixes that identify an entity's SQLite-database source dir in the
# archive (matches backup_pps.py's discover_entity_sources naming:
# f"{entity}_{suffix}"), and whether that source is critical.
ENTITY_SUFFIXES_CRITICAL = {
    "sqlite": True,
    "identity": True,
    "crystals": True,
    "word_photos": True,
    "journals": True,
    "notebook": True,
}

# Shared sources (backup_pps.py SHARED_SOURCES) and criticality.
SHARED_SOURCES_CRITICAL = {
    "chromadb": False,
    "neo4j": False,
    "haven": True,
}

# Top-level archive dirs we actually extract + deep-check. Neo4j is skipped
# on purpose: it is explicitly non-critical/rebuildable in backup_pps.py,
# its live data is multiple GB (uncompressed) on this host, and its data
# files aren't SQLite — a meaningful "integrity check" for it is a separate,
# heavier project. We still confirm its *presence* in the archive (check 5)
# without extracting its bytes.
DIRS_TO_EXTRACT_PREFIXES = ("_sqlite", "haven", "chromadb", "_identity",
                             "_crystals", "_word_photos", "_journals",
                             "_notebook")


def log(msg: str, level: str = "INFO") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


# =============================================================================
# DISCOVERY
# =============================================================================

def find_newest_backup(backup_dir: Path) -> Path | None:
    backups = sorted(
        backup_dir.glob("pps_backup_*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return backups[0] if backups else None


def entity_name_from_sqlite_source(source_name: str) -> str | None:
    """'lyra_sqlite' -> 'lyra'."""
    if source_name.endswith("_sqlite"):
        return source_name[: -len("_sqlite")]
    return None


def live_db_path_for(source_name: str, filename: str) -> Path | None:
    """Map an archive source dir + filename back to the LIVE file on disk,
    mirroring restore_pps.py's ENTITY_SOURCE_SUFFIXES / SHARED_DESTINATIONS."""
    if source_name == "haven":
        return PROJECT_ROOT / "haven" / "data" / filename
    entity = entity_name_from_sqlite_source(source_name)
    if entity:
        return PROJECT_ROOT / "entities" / entity / "data" / filename
    return None


# =============================================================================
# CHECKS
# =============================================================================

def check_archive_integrity(backup_path: Path) -> tuple[bool, list[str]]:
    """Full sequential read of the tar.gz. A truncated/torn file raises here
    (gzip validates its trailing CRC32+size only once the whole stream has
    been read)."""
    errors = []
    try:
        member_count = 0
        with tarfile.open(backup_path, "r:gz") as tar:
            for _ in tar:
                member_count += 1
        log(f"  Archive integrity OK — {member_count} entries, fully readable")
        return True, errors
    except Exception as e:
        errors.append(f"Archive integrity FAILED: {e}")
        return False, errors


def list_archive_sources(backup_path: Path) -> dict[str, list[str]]:
    """Top-level source dir -> list of member names (relative), without
    extracting anything."""
    sources: dict[str, list[str]] = {}
    with tarfile.open(backup_path, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            parts = member.name.split("/", 1)
            if len(parts) != 2:
                continue
            source, rel = parts
            sources.setdefault(source, []).append(rel)
    return sources


def check_critical_sources_present(sources: dict[str, list[str]]) -> tuple[bool, list[str], list[str]]:
    """Re-derive backup_pps.py's critical-source check independently."""
    errors: list[str] = []
    checks: list[str] = []

    entities_seen = {
        entity_name_from_sqlite_source(s)
        for s in sources
        if entity_name_from_sqlite_source(s)
    }
    if not entities_seen:
        errors.append("No entity *_sqlite sources found in archive at all")

    missing_critical = []
    for entity in sorted(entities_seen):
        for suffix, critical in ENTITY_SUFFIXES_CRITICAL.items():
            source_name = f"{entity}_{suffix}"
            present = source_name in sources and len(sources[source_name]) > 0
            if critical and not present:
                missing_critical.append(source_name)

    for name, critical in SHARED_SOURCES_CRITICAL.items():
        present = name in sources and len(sources[name]) > 0
        if critical and not present:
            missing_critical.append(name)

    if missing_critical:
        errors.append(f"Missing critical sources: {sorted(missing_critical)}")
    else:
        checks.append(f"All critical sources present for entities {sorted(entities_seen)}")

    return (len(missing_critical) == 0), checks, errors


def extract_selected(backup_path: Path, scratch_dir: Path) -> None:
    """Extract only the dirs we deep-check (skip neo4j's multi-GB payload)."""
    with tarfile.open(backup_path, "r:gz") as tar:
        wanted_members = [
            m for m in tar.getmembers()
            if m.isfile() and m.name.split("/", 1)[0] != "neo4j"
        ]
        # Python 3.12+ tarfile requires an explicit `filter` for extractall;
        # "data" is the safe default (no absolute paths / no traversal).
        try:
            tar.extractall(scratch_dir, members=wanted_members, filter="data")
        except TypeError:
            # Older Python without the `filter` kwarg.
            tar.extractall(scratch_dir, members=wanted_members)


def sqlite_integrity_check(db_path: Path) -> tuple[bool, str, str]:
    """Run PRAGMA integrity_check + quick_check against an extracted (never
    live) copy. Returns (ok, integrity_result, quick_result)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        quick = con.execute("PRAGMA quick_check").fetchone()[0]
        ok = (integrity == "ok") and (quick == "ok")
        return ok, integrity, quick
    finally:
        con.close()


def table_row_count(db_path: Path, table: str) -> int | None:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = {
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if table not in tables:
            return None
        return con.execute(f"SELECT COUNT(*) FROM '{table}'").fetchone()[0]
    except sqlite3.Error:
        return None
    finally:
        con.close()


def check_sqlite_sources(scratch_dir: Path, sources: dict[str, list[str]]) -> tuple[bool, list[str], list[str]]:
    """For every *_sqlite / haven source: integrity_check each *.db, and
    row-count-sanity-check watch tables against the live db."""
    errors: list[str] = []
    checks: list[str] = []
    ok = True

    sqlite_sources = [s for s in sources if s.endswith("_sqlite") or s == "haven"]
    if not sqlite_sources:
        return False, checks, ["No *_sqlite or haven sources found to validate"]

    for source_name in sorted(sqlite_sources):
        for rel in sorted(sources[source_name]):
            if not rel.endswith(".db"):
                continue
            extracted = scratch_dir / source_name / rel
            if not extracted.exists():
                errors.append(f"{source_name}/{rel}: expected file missing after extraction")
                ok = False
                continue

            # 1. Integrity check
            try:
                db_ok, integrity, quick = sqlite_integrity_check(extracted)
            except Exception as e:
                errors.append(f"{source_name}/{rel}: could not open/check ({e})")
                ok = False
                continue

            if not db_ok:
                errors.append(
                    f"{source_name}/{rel}: INTEGRITY FAILURE "
                    f"(integrity_check={integrity!r}, quick_check={quick!r})"
                )
                ok = False
                continue

            checks.append(f"{source_name}/{rel}: integrity_check=ok, quick_check=ok")

            # 2. Row-count sanity vs live db (best-effort — skip if no live db)
            live_path = live_db_path_for(source_name, rel)
            if not live_path or not live_path.exists():
                continue

            for table in WATCH_TABLES:
                live_count = table_row_count(live_path, table)
                if live_count is None:
                    continue
                backup_count = table_row_count(extracted, table)
                if backup_count is None:
                    continue
                if live_count == 0:
                    checks.append(f"{source_name}/{rel}:{table}: live=0 (nothing to compare), backup={backup_count}")
                    continue
                ratio = backup_count / live_count
                if backup_count > live_count:
                    errors.append(
                        f"{source_name}/{rel}:{table}: backup has MORE rows than live "
                        f"({backup_count} > {live_count}) — suspicious"
                    )
                    ok = False
                elif ratio < MIN_ROW_RATIO:
                    errors.append(
                        f"{source_name}/{rel}:{table}: backup row count too low "
                        f"({backup_count}/{live_count} = {ratio:.0%}, need >= {MIN_ROW_RATIO:.0%})"
                    )
                    ok = False
                else:
                    checks.append(
                        f"{source_name}/{rel}:{table}: backup={backup_count} live={live_count} "
                        f"({ratio:.0%}) OK"
                    )

    return ok, checks, errors


def check_chromadb(scratch_dir: Path, sources: dict[str, list[str]]) -> tuple[bool, list[str], list[str]]:
    """Best-effort ChromaDB check. Non-fatal — chromadb is explicitly
    non-critical/rebuildable, so failures here are WARNs, never hard fails."""
    checks: list[str] = []
    errors: list[str] = []

    if "chromadb" not in sources:
        checks.append("chromadb: not present in archive (non-critical, skipped)")
        return True, checks, errors

    chroma_dir = scratch_dir / "chromadb"
    if not chroma_dir.exists():
        checks.append("chromadb: extracted dir missing (non-critical, skipped)")
        return True, checks, errors

    try:
        import chromadb  # noqa: local import — only pps/venv has this
    except ImportError:
        checks.append("chromadb: python package not importable in this interpreter (non-critical, skipped)")
        return True, checks, errors

    try:
        client = chromadb.PersistentClient(path=str(chroma_dir))
        collections = client.list_collections()
        total_items = 0
        for coll in collections:
            try:
                total_items += coll.count()
            except Exception as e:
                errors.append(f"chromadb: collection {coll.name!r} count() failed: {e} (non-fatal)")
        checks.append(f"chromadb: {len(collections)} collection(s), {total_items} total item(s)")
    except Exception as e:
        errors.append(f"chromadb: could not open extracted copy: {e} (non-fatal)")

    # Never hard-fail on chromadb — it's non-critical/rebuildable.
    return True, checks, errors


# =============================================================================
# VERDICT
# =============================================================================

def write_verdict(backup_path: Path, ok: bool, checks: list[str], errors: list[str]) -> None:
    verdict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "backup": str(backup_path),
        "ok": ok,
        "checks": checks,
        "errors": errors,
    }
    payload = json.dumps(verdict) + "\n"

    for path in (_PREFERRED_VERDICT_PATH, _FALLBACK_VERDICT_PATH):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload)
            log(f"Verdict written to {path}")
            return
        except (PermissionError, OSError) as e:
            log(f"  Could not write verdict to {path}: {e}", "WARN")

    log("Could not write verdict to any location!", "ERROR")


def alert_failure(backup_path: Path, errors: list[str]) -> None:
    msg = (f"PPS BACKUP VALIDATION FAILED for {backup_path.name}: "
           f"{len(errors)} error(s). First: {errors[0] if errors else 'unknown'}")
    log(msg, "ERROR")
    try:
        notify = PROJECT_ROOT / "scripts" / "notify.py"
        if notify.exists():
            import subprocess
            subprocess.run(
                ["python3", str(notify), "--title", "🔴🟠🚨 BACKUP VALIDATION",
                 "--priority", "urgent", msg],
                timeout=30, capture_output=True,
            )
    except Exception as e:
        log(f"  (could not send ntfy alert: {e})", "WARN")


# =============================================================================
# MAIN
# =============================================================================

def validate(backup_path: Path, dry_run: bool = False) -> tuple[bool, list[str], list[str]]:
    checks: list[str] = []
    errors: list[str] = []

    log(f"Validating backup: {backup_path}")
    log(f"  Size: {backup_path.stat().st_size / 1024 / 1024:.1f} MB")

    if dry_run:
        try:
            sources = list_archive_sources(backup_path)
        except Exception as e:
            log(f"  (dry-run) could not list archive contents: {e}", "ERROR")
            return False, checks, [str(e)]
        log("  (dry-run) sources found:")
        for name, files in sorted(sources.items()):
            log(f"    {name}: {len(files)} file(s)", "DRY")
        return True, ["dry-run: not extracted/checked"], errors

    # 1. Archive integrity (full read)
    ok, errs = check_archive_integrity(backup_path)
    errors.extend(errs)
    if not ok:
        return False, checks, errors
    checks.append("Archive integrity: full sequential read succeeded")

    # Enumerate sources (cheap second pass — tarfile caches nothing across
    # `with` blocks, so we reopen; the file is local disk, this is fast).
    sources = list_archive_sources(backup_path)

    # 5. Critical-source presence
    ok, c, e = check_critical_sources_present(sources)
    checks.extend(c)
    errors.extend(e)
    overall_ok = ok

    # Extract what we need to deep-check
    scratch_dir = Path(tempfile.mkdtemp(prefix="pps_validate_"))
    try:
        log(f"Extracting selected sources to scratch: {scratch_dir}")
        extract_selected(backup_path, scratch_dir)

        # 2 + 3. SQLite integrity + row-count sanity
        ok, c, e = check_sqlite_sources(scratch_dir, sources)
        checks.extend(c)
        errors.extend(e)
        overall_ok = overall_ok and ok

        # 4. ChromaDB (best-effort, never hard-fails)
        ok, c, e = check_chromadb(scratch_dir, sources)
        checks.extend(c)
        errors.extend(e)
        # intentionally not AND'd into overall_ok — non-critical

    finally:
        log(f"Cleaning up scratch dir: {scratch_dir}")
        shutil.rmtree(scratch_dir, ignore_errors=True)

    return overall_ok, checks, errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate that the most recent PPS backup is non-corrupt and restorable.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 scripts/validate_backup.py
    python3 scripts/validate_backup.py --backup /path/to/pps_backup_20260912_040035.tar.gz
    python3 scripts/validate_backup.py --dry-run
        """,
    )
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR,
                         help=f"Directory to look for backups in (default: {DEFAULT_BACKUP_DIR})")
    parser.add_argument("--backup", type=Path, default=None,
                         help="Validate a specific backup archive instead of the newest one")
    parser.add_argument("--dry-run", action="store_true",
                         help="List what would be checked without extracting/checking")
    args = parser.parse_args()

    if args.backup:
        backup_path = args.backup
        if not backup_path.exists():
            candidate = args.backup_dir / args.backup.name
            if candidate.exists():
                backup_path = candidate
        if not backup_path.exists():
            log(f"Backup not found: {args.backup}", "ERROR")
            return 1
    else:
        backup_path = find_newest_backup(args.backup_dir)
        if backup_path is None:
            log(f"No backups found in {args.backup_dir}", "ERROR")
            return 1

    log("=" * 70)
    log("PPS BACKUP VALIDATION")
    log("=" * 70)

    ok, checks, errors = validate(backup_path, dry_run=args.dry_run)

    log("-" * 70)
    for c in checks:
        log(f"  [OK ] {c}")
    for e in errors:
        log(f"  [ERR] {e}", "ERROR")
    log("-" * 70)

    if args.dry_run:
        log("DRY RUN COMPLETE — no verdict written", "DRY")
        return 0

    write_verdict(backup_path, ok, checks, errors)

    if ok:
        log(f"VALIDATION PASSED: {backup_path.name}", "OK")
        return 0
    else:
        log(f"VALIDATION FAILED: {backup_path.name}", "ERROR")
        alert_failure(backup_path, errors)
        return 1


if __name__ == "__main__":
    sys.exit(main())
