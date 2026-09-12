"""
Tests for scripts/validate_backup.py (Issue #317).

Builds a tiny fake PPS backup archive (small sqlite dbs + a few marker files)
and runs the validator against it, monkeypatching PROJECT_ROOT / verdict
paths so the test never touches real backups, real entity data, or
~/.claude/*.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _load_validate_backup_module():
    """Import scripts/validate_backup.py as a module without requiring
    scripts/ to be a package (matches how other scripts/ tests do it)."""
    spec = importlib.util.spec_from_file_location(
        "validate_backup", SCRIPTS_DIR / "validate_backup.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_backup"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def vb(monkeypatch, tmp_path):
    """Loaded validate_backup module with PROJECT_ROOT and verdict paths
    redirected into tmp_path."""
    module = _load_validate_backup_module()
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "_PREFERRED_VERDICT_PATH", tmp_path / "verdict.json")
    monkeypatch.setattr(module, "_FALLBACK_VERDICT_PATH", tmp_path / "verdict_fallback.json")
    return module


def _make_sqlite_db(path: Path, message_rows: int, summary_rows: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT)")
    con.execute("CREATE TABLE message_summaries (id INTEGER PRIMARY KEY, summary TEXT)")
    for i in range(message_rows):
        con.execute("INSERT INTO messages (body) VALUES (?)", (f"msg {i}",))
    for i in range(summary_rows):
        con.execute("INSERT INTO message_summaries (summary) VALUES (?)", (f"sum {i}",))
    con.commit()
    con.close()


def _make_live_tree(root: Path, message_rows: int = 100, summary_rows: int = 10) -> None:
    """Fake entities/lyra/data/conversations.db + haven/data/haven.db,
    matching the live-db paths validate_backup.py expects to compare against."""
    _make_sqlite_db(root / "entities" / "lyra" / "data" / "conversations.db",
                     message_rows, summary_rows)
    haven_dir = root / "haven" / "data"
    haven_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(haven_dir / "haven.db")
    con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT)")
    for i in range(5):
        con.execute("INSERT INTO messages (body) VALUES (?)", (f"h{i}",))
    con.commit()
    con.close()


def _make_backup_archive(tmp_path: Path, name: str, *,
                          lyra_message_rows: int, lyra_summary_rows: int,
                          include_identity: bool = True,
                          include_haven: bool = True,
                          haven_message_rows: int = 5,
                          corrupt_db: bool = False,
                          truncate: bool = False) -> Path:
    """Build a small fake backup tar.gz mirroring backup_pps.py's layout:
    {source_name}/{relative_path}. Includes all of lyra's critical sources
    by default so the "healthy" case doesn't trip the critical-source check."""
    stage = tmp_path / "stage"
    stage.mkdir(exist_ok=True)

    lyra_sqlite_dir = stage / "lyra_sqlite"
    _make_sqlite_db(lyra_sqlite_dir / "conversations.db", lyra_message_rows, lyra_summary_rows)

    if corrupt_db:
        # Truncate the sqlite file mid-header — guaranteed integrity_check failure.
        db_path = lyra_sqlite_dir / "conversations.db"
        data = db_path.read_bytes()
        db_path.write_bytes(data[: len(data) // 2])

    if include_identity:
        identity_dir = stage / "lyra_identity"
        identity_dir.mkdir(exist_ok=True)
        (identity_dir / "identity.md").write_text("# fake identity\n")

    # The other critical entity sources (backup_pps.py: crystals, word_photos,
    # journals, notebook) — always included so tests other than the
    # missing-critical-source one don't trip on them incidentally.
    for suffix in ("crystals", "word_photos", "journals", "notebook"):
        d = stage / f"lyra_{suffix}"
        d.mkdir(exist_ok=True)
        (d / "placeholder.md").write_text("placeholder\n")

    if include_haven:
        haven_dir = stage / "haven"
        haven_dir.mkdir(exist_ok=True)
        con = sqlite3.connect(haven_dir / "haven.db")
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT)")
        for i in range(haven_message_rows):
            con.execute("INSERT INTO messages (body) VALUES (?)", (f"h{i}",))
        con.commit()
        con.close()

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(exist_ok=True)
    archive_path = backup_dir / name

    with tarfile.open(archive_path, "w:gz") as tar:
        for f in stage.rglob("*"):
            if f.is_file():
                tar.add(f, arcname=str(f.relative_to(stage)))

    if truncate:
        data = archive_path.read_bytes()
        archive_path.write_bytes(data[: len(data) // 2])

    return archive_path


def test_healthy_backup_passes(vb, tmp_path):
    _make_live_tree(tmp_path, message_rows=100, summary_rows=10)
    archive = _make_backup_archive(
        tmp_path, "pps_backup_20260101_000000.tar.gz",
        lyra_message_rows=99, lyra_summary_rows=10,  # 99/100 = 99% >= 90%
    )

    ok, checks, errors = vb.validate(archive, dry_run=False)

    assert ok is True
    assert errors == []
    assert any("conversations.db: integrity_check=ok" in c for c in checks)
    assert any("messages: backup=99 live=100" in c for c in checks)


def test_corrupt_sqlite_fails(vb, tmp_path):
    _make_live_tree(tmp_path, message_rows=100, summary_rows=10)
    archive = _make_backup_archive(
        tmp_path, "pps_backup_20260102_000000.tar.gz",
        lyra_message_rows=99, lyra_summary_rows=10,
        corrupt_db=True,
    )

    ok, checks, errors = vb.validate(archive, dry_run=False)

    assert ok is False
    assert any("could not open/check" in e or "INTEGRITY FAILURE" in e for e in errors)


def test_stale_backup_fails_row_count_ratio(vb, tmp_path):
    _make_live_tree(tmp_path, message_rows=1000, summary_rows=100)
    archive = _make_backup_archive(
        tmp_path, "pps_backup_20260103_000000.tar.gz",
        lyra_message_rows=100, lyra_summary_rows=100,  # 100/1000 = 10%, way under 90%
    )

    ok, checks, errors = vb.validate(archive, dry_run=False)

    assert ok is False
    assert any("row count too low" in e for e in errors)


def test_missing_critical_source_fails(vb, tmp_path):
    _make_live_tree(tmp_path, message_rows=10, summary_rows=1)
    archive = _make_backup_archive(
        tmp_path, "pps_backup_20260104_000000.tar.gz",
        lyra_message_rows=10, lyra_summary_rows=1,
        include_identity=False,  # lyra_identity is critical — must be flagged missing
    )

    ok, checks, errors = vb.validate(archive, dry_run=False)

    assert ok is False
    assert any("lyra_identity" in e for e in errors)


def test_truncated_archive_fails(vb, tmp_path):
    _make_live_tree(tmp_path, message_rows=10, summary_rows=1)
    archive = _make_backup_archive(
        tmp_path, "pps_backup_20260105_000000.tar.gz",
        lyra_message_rows=10, lyra_summary_rows=1,
        truncate=True,
    )

    ok, checks, errors = vb.validate(archive, dry_run=False)

    assert ok is False
    assert any("Archive integrity FAILED" in e for e in errors)


def test_dry_run_does_not_extract(vb, tmp_path):
    _make_live_tree(tmp_path, message_rows=10, summary_rows=1)
    archive = _make_backup_archive(
        tmp_path, "pps_backup_20260106_000000.tar.gz",
        lyra_message_rows=10, lyra_summary_rows=1,
    )

    ok, checks, errors = vb.validate(archive, dry_run=True)

    assert ok is True
    assert errors == []
    assert checks == ["dry-run: not extracted/checked"]


def test_find_newest_backup(vb, tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(exist_ok=True)
    old = backup_dir / "pps_backup_20260101_000000.tar.gz"
    new = backup_dir / "pps_backup_20260102_000000.tar.gz"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    import os
    import time
    os.utime(old, (time.time() - 1000, time.time() - 1000))

    found = vb.find_newest_backup(backup_dir)
    assert found == new


def test_write_verdict_falls_back_on_permission_error(vb, tmp_path, monkeypatch):
    unwritable = tmp_path / "no_such_dir_parent_will_fail" / "verdict.json"

    class UnwritablePath(type(unwritable)):
        def write_text(self, *a, **kw):
            raise PermissionError("simulated")

    monkeypatch.setattr(vb, "_PREFERRED_VERDICT_PATH", UnwritablePath(unwritable))
    fallback = tmp_path / "verdict_fallback.json"
    monkeypatch.setattr(vb, "_FALLBACK_VERDICT_PATH", fallback)

    vb.write_verdict(tmp_path / "fake.tar.gz", True, ["ok check"], [])

    assert fallback.exists()
    assert '"ok": true' in fallback.read_text()
