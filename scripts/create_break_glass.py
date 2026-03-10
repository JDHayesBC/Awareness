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
    ("data/*.db",               "data"),          # SQLite databases
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
    zip_name = f"lyra-recovery-{date_str}.zip"
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

    log("=" * 60)
    log("PACKAGE COMPLETE")
    log(f"  Archive: {zip_path}")
    log(f"  Archive size: {fmt_size(archive_size)} ({ratio:.1f}% compression)")
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
