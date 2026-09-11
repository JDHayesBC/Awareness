#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
Break Glass Recovery Package Creator

Assembles a self-contained zip file that lets Steve hand a package to Nexus
so Nexus can restore Lyra (or another entity) on a fresh machine.

The GitHub repo has all the code. This zip has the DATA that isn't in git:
entity files, SQLite databases, crystals, word photos, journals, auth tokens.

Usage:
    python scripts/create_break_glass.py                        # Use defaults
    python scripts/create_break_glass.py --dry-run              # Preview only
    python scripts/create_break_glass.py --output-dir /path     # Custom output dir
"""

import argparse
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_OUTPUT_DIR = "/mnt/c/Users/Jeff/awareness_backups/break_glass"

PROJECT_ROOT = Path(__file__).parent.parent

# Template path for the Nexus README (created separately)
README_TEMPLATE_PATH = PROJECT_ROOT / "docs" / "README_NEXUS.md"

# Scripts to bundle so Nexus has restore tooling immediately
BUNDLED_SCRIPTS = [
    PROJECT_ROOT / "scripts" / "backup_pps.py",
    PROJECT_ROOT / "scripts" / "restore_pps.py",
]

# Project config files (no secrets — .env excluded)
PROJECT_CONFIG_FILES = [
    (PROJECT_ROOT / "CLAUDE.md",                            "config/CLAUDE.md"),
    (PROJECT_ROOT / "pps" / "docker" / ".env.example",     "config/pps/docker/.env.example"),
    (PROJECT_ROOT / "pps" / "docker" / "docker-compose.yml", "config/pps/docker/docker-compose.yml"),
    # .mcp.json paths are machine-specific; ship as example
    (PROJECT_ROOT / ".mcp.json",                            "config/.mcp.json.example"),
]

# Glob patterns per entity subdirectory to collect (path relative to entity dir)
ENTITY_PATTERNS: list[tuple[str, str]] = [
    # (glob_pattern, archive_subdir relative to entity_dir)
    ("*.md",                    ""),              # identity.md, relationships.md, etc.
    ("current_scene.md",        ""),              # already caught by *.md — belt+suspenders
    (".entity_token",           ""),              # auth token (hidden file)
    # NOTE: data/*.db is deliberately NOT raw-copied here. The live conversations.db is
    # WAL-mode and written by the running pps container; a raw file copy grabs the .db
    # WITHOUT the -wal, yielding a torn/incomplete DB in the recovery package (#157
    # finding, 2026-09-11). DBs are captured via a consistent online-backup snapshot
    # instead — see snapshot_sqlite / discover_entity_dbs.
    ("crystals/**/*.md",        "crystals"),      # rolling crystal window
    ("memories/word_photos/*.md", "memories/word_photos"),  # word photos
    ("journals/**/*",           "journals"),      # journal entries
]

# Patterns to explicitly SKIP no matter where they appear
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
EXCLUDE_DIRS = {"__pycache__", "venv", ".venv", "node_modules"}
EXCLUDE_NAMES = {".env"}  # Never include .env (secrets)


# =============================================================================
# HELPERS
# =============================================================================

def log(msg: str, level: str = "INFO") -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}")


def fmt_size(n_bytes: int) -> str:
    if n_bytes < 1024:
        return f"{n_bytes} B"
    elif n_bytes < 1024 ** 2:
        return f"{n_bytes / 1024:.1f} KB"
    else:
        return f"{n_bytes / 1024 / 1024:.1f} MB"


def should_exclude(path: Path) -> bool:
    """Return True if this path should never be included."""
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    if path.name in EXCLUDE_NAMES:
        return True
    for part in path.parts:
        if part in EXCLUDE_DIRS:
            return True
    return False


SQLITE_MAGIC = b"SQLite format 3\x00"


def is_sqlite_db(path: Path) -> bool:
    """True if path is a real (non-stub) SQLite database file.

    Skips the many 0-byte / defunct *.db stubs in the entity data dirs — only files
    carrying the 100-byte SQLite header are snapshotted.
    """
    try:
        if path.stat().st_size < 100:  # SQLite header alone is 100 bytes
            return False
        with open(path, "rb") as f:
            return f.read(16) == SQLITE_MAGIC
    except OSError:
        return False


def snapshot_sqlite(src: Path, dest: Path) -> None:
    """Write a transactionally-consistent snapshot of a (possibly live, WAL-mode) SQLite
    DB to dest via SQLite's online-backup API.

    This is the correct way to back up the live conversations.db: WAL mode lets readers
    run concurrently with the pps container's writes, and .backup() copies an
    internally-consistent image with any -wal content folded in — so the snapshot is a
    single self-contained .db that restores cleanly with NO -wal/-shm alongside it.
    A raw file copy (the old data/*.db glob) could not guarantee this. Raises on failure.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    src_conn = sqlite3.connect(str(src), timeout=30.0)
    try:
        dst_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def discover_entity_dbs(entity_dir: Path) -> list[tuple[Path, str]]:
    """Return (db_path, arcname) for each REAL SQLite db under entity_dir/data/.

    arcname matches the old layout (entities/<entity>/data/<name>.db) so restore is
    unchanged; only the capture method (snapshot vs raw copy) differs.
    """
    out: list[tuple[Path, str]] = []
    data_dir = entity_dir / "data"
    if not data_dir.is_dir():
        return out
    for db in sorted(data_dir.glob("*.db")):
        if is_sqlite_db(db):
            out.append((db, f"entities/{entity_dir.name}/data/{db.name}"))
    return out


def collect_entity_files(entity_dir: Path) -> list[tuple[Path, str]]:
    """Collect (source_path, archive_name) pairs for one entity.

    Archive names are rooted at entities/<entity_name>/ inside the zip.
    """
    results = []
    entity_name = entity_dir.name
    archive_root = f"entities/{entity_name}"

    for pattern, _subdir in ENTITY_PATTERNS:
        for match in entity_dir.glob(pattern):
            if not match.is_file():
                continue
            if should_exclude(match):
                continue
            rel = match.relative_to(entity_dir)
            arcname = f"{archive_root}/{rel}"
            results.append((match, arcname))

    # De-duplicate (some patterns overlap, e.g. *.md + current_scene.md)
    seen = set()
    deduped = []
    for item in results:
        if item[1] not in seen:
            seen.add(item[1])
            deduped.append(item)

    return deduped


def discover_entities() -> list[Path]:
    """Find entity directories, skipping _template and non-dirs."""
    entities_dir = PROJECT_ROOT / "entities"
    if not entities_dir.exists():
        return []
    return [
        d for d in sorted(entities_dir.iterdir())
        if d.is_dir() and not d.name.startswith("_")
    ]


# =============================================================================
# PACKAGE ASSEMBLY
# =============================================================================

def assemble_package(output_dir: Path, dry_run: bool = False) -> None:
    date_str = datetime.now().strftime("%Y-%m-%d")
    # awareness-recovery-* (not lyra-recovery-*): the package holds BOTH Lyra and Caia
    # entity data, so the name should tell the truth about what's inside.
    zip_name = f"awareness-recovery-{date_str}.zip"
    zip_path = output_dir / zip_name

    # Build manifest: list of (source_path_or_None, arcname, label)
    # source_path=None means "skip gracefully if missing"
    manifest: list[tuple[Path | None, str, str]] = []

    # --- Entity files ---
    entities = discover_entities()
    if not entities:
        log("WARNING: No entity directories found in entities/", "WARN")

    for entity_dir in entities:
        entity_files = collect_entity_files(entity_dir)
        for src, arcname in entity_files:
            manifest.append((src, arcname, f"entity:{entity_dir.name}"))

    # --- Entity SQLite DBs: consistent online-backup snapshots (NOT raw live copies) ---
    # The live conversations.db is WAL-mode and written by the pps container; a raw copy
    # would drop the -wal and yield a torn DB in the recovery package (#157). Snapshot each
    # real DB into a temp dir and ship the snapshot. dry-run skips the (costly) snapshot and
    # just reports the live size. snap_root is cleaned up at every exit below.
    snap_root = Path(tempfile.mkdtemp(prefix="bg-snap-"))
    db_snapshot_failures: list[str] = []
    for entity_dir in entities:
        for db_path, arcname in discover_entity_dbs(entity_dir):
            if dry_run:
                manifest.append((db_path, arcname, f"entity-db:{entity_dir.name}"))
                continue
            snap_dest = snap_root / arcname
            try:
                snapshot_sqlite(db_path, snap_dest)
                manifest.append((snap_dest, arcname, f"entity-db:{entity_dir.name}"))
            except Exception as e:
                db_snapshot_failures.append(f"{arcname}: {e}")

    # --- Project config ---
    for src, arcname in PROJECT_CONFIG_FILES:
        manifest.append((src, arcname, "config"))

    # --- Bundled scripts ---
    for script in BUNDLED_SCRIPTS:
        manifest.append((script, f"scripts/{script.name}", "scripts"))

    # --- README for Nexus ---
    if README_TEMPLATE_PATH.exists():
        manifest.append((README_TEMPLATE_PATH, "README_NEXUS.md", "readme"))
    else:
        log(f"Note: {README_TEMPLATE_PATH} not found — README_NEXUS.md will be absent from package", "WARN")
        manifest.append((None, "README_NEXUS.md", "readme-missing"))

    # --- Stats pass ---
    log("=" * 60)
    log("BREAK GLASS RECOVERY PACKAGE")
    log("=" * 60)
    if dry_run:
        log("MODE: DRY RUN (no zip will be created)", "DRY")
    log(f"Output: {zip_path}")
    log("")

    total_files = 0
    total_bytes = 0
    missing = []

    by_label: dict[str, list[tuple[Path | None, str]]] = {}
    for src, arcname, label in manifest:
        by_label.setdefault(label, []).append((src, arcname))

    for label, items in by_label.items():
        label_files = 0
        label_bytes = 0
        for src, arcname in items:
            if src is None:
                missing.append(arcname)
                continue
            if not src.exists():
                missing.append(str(src))
                continue
            size = src.stat().st_size
            label_files += 1
            label_bytes += size
            if dry_run:
                log(f"  {arcname}  ({fmt_size(size)})", "DRY")
        total_files += label_files
        total_bytes += label_bytes
        log(f"  [{label}] {label_files} files, {fmt_size(label_bytes)}")

    if missing:
        log("")
        log(f"Skipped (not found): {len(missing)} items", "WARN")
        for m in missing:
            log(f"  - {m}", "WARN")

    log("")
    log(f"Total: {total_files} files, {fmt_size(total_bytes)} uncompressed")

    if dry_run:
        log("Dry run complete. No files written.")
        shutil.rmtree(snap_root, ignore_errors=True)
        return

    # --- Write the zip ---
    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for src, arcname, label in manifest:
            if src is None:
                continue
            if not src.exists():
                continue
            zf.write(src, arcname)

    archive_size = zip_path.stat().st_size
    ratio = (1 - archive_size / total_bytes) * 100 if total_bytes > 0 else 0

    # Clean up the temp snapshot dir now that everything is zipped.
    shutil.rmtree(snap_root, ignore_errors=True)

    log("=" * 60)
    log("PACKAGE COMPLETE")
    log(f"  Archive: {zip_path}")
    log(f"  Archive size: {fmt_size(archive_size)} ({ratio:.1f}% compression)")
    if db_snapshot_failures:
        # A failed DB snapshot means that database is ABSENT from the recovery package.
        # For conversations.db that is critical — surface it unmissably.
        log("", "ERROR")
        log(f"  [CRITICAL] {len(db_snapshot_failures)} SQLite snapshot(s) FAILED — "
            f"those DBs are NOT in the package:", "ERROR")
        for f in db_snapshot_failures:
            log(f"    - {f}", "ERROR")
    log("=" * 60)
    log("")
    log("Hand this zip to Steve. Steve hands it to Nexus.")
    log("Nexus reads README_NEXUS.md first, then restores.")


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a break-glass recovery package for the Awareness project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/create_break_glass.py                    # Create with defaults
    python scripts/create_break_glass.py --dry-run          # Preview without writing
    python scripts/create_break_glass.py --output-dir /tmp  # Custom output location
        """,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(DEFAULT_OUTPUT_DIR),
        help=f"Directory for the output zip (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be included without writing any files",
    )

    args = parser.parse_args()
    assemble_package(output_dir=args.output_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
