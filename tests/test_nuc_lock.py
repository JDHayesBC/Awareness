"""
Unit tests for scripts/nuc_lock.py — cooperative NUC lockfile logic.

Tests are fully isolated (tmp_path fixture, no real ~/.claude/locks writes).
They use monkey-patching to override LOCKS_DIR so nothing touches production paths.

Coverage priorities:
  - Stale lock detection: dead PID, expired timestamp, unreadable file
  - Live lock detection: PID alive, timestamp fresh
  - NucLock context manager: acquire, release, double-acquire guard
  - is_lock_held: removes stale files, returns False for missing/stale
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# Allow importing from project root without installing
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import scripts.nuc_lock as nuc_lock_mod
from scripts.nuc_lock import NucLock, is_lock_held, MAX_LOCK_AGE_SECONDS


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def lock_dir(tmp_path, monkeypatch):
    """
    Redirect all lock operations to a temporary directory so tests never
    touch ~/.claude/locks/.
    """
    locks = tmp_path / "locks"
    locks.mkdir()
    monkeypatch.setattr(nuc_lock_mod, "LOCKS_DIR", locks)
    monkeypatch.setattr(nuc_lock_mod, "SUMMARIZER_LOCK", locks / "summarizer.lock")
    monkeypatch.setattr(nuc_lock_mod, "KG_INGEST_LOCK", locks / "kg_ingest.lock")
    return locks


def write_lock_raw(path: Path, pid: int, started_at: str) -> None:
    """Write a lock file with explicit values (for setting up test scenarios)."""
    path.write_text(json.dumps({"pid": pid, "started_at": started_at}))


def fresh_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def stale_timestamp(age_seconds: int = MAX_LOCK_AGE_SECONDS + 60) -> str:
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return ts.isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Stale lock detection
# ─────────────────────────────────────────────────────────────────────────────

class TestStaleLockDetection:

    def test_missing_file_returns_false(self, lock_dir):
        path = lock_dir / "summarizer.lock"
        assert not is_lock_held(path)

    def test_dead_pid_is_stale(self, lock_dir):
        """A lock whose PID does not exist should be treated as stale and removed."""
        path = lock_dir / "summarizer.lock"
        # PID 99999999 is virtually guaranteed not to exist
        write_lock_raw(path, 99999999, fresh_timestamp())
        assert path.exists()

        result = is_lock_held(path)

        assert result is False
        assert not path.exists(), "Stale lock file should have been removed"

    def test_expired_timestamp_is_stale(self, lock_dir):
        """A lock with our own PID but an ancient timestamp should be stale."""
        path = lock_dir / "summarizer.lock"
        write_lock_raw(path, os.getpid(), stale_timestamp())

        result = is_lock_held(path)

        assert result is False
        assert not path.exists(), "Stale lock file should have been removed"

    def test_unreadable_json_is_stale(self, lock_dir):
        """A lock file with garbage content is treated as stale and removed."""
        path = lock_dir / "summarizer.lock"
        path.write_text("not-json")

        result = is_lock_held(path)

        assert result is False
        assert not path.exists()

    def test_missing_pid_field_is_stale(self, lock_dir):
        path = lock_dir / "summarizer.lock"
        path.write_text(json.dumps({"started_at": fresh_timestamp()}))

        result = is_lock_held(path)

        assert result is False

    def test_fresh_lock_from_self_is_held(self, lock_dir):
        """A lock with our own PID and a fresh timestamp is live."""
        path = lock_dir / "summarizer.lock"
        write_lock_raw(path, os.getpid(), fresh_timestamp())

        assert is_lock_held(path) is True
        assert path.exists(), "Live lock should not be removed"


# ─────────────────────────────────────────────────────────────────────────────
# NucLock context manager
# ─────────────────────────────────────────────────────────────────────────────

class TestNucLock:

    def test_acquire_and_release(self, lock_dir):
        path = lock_dir / "test.lock"
        with NucLock(path) as lk:
            assert lk.held is True
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["pid"] == os.getpid()
            assert "started_at" in data

        # After exiting the context, the lock file should be gone
        assert not path.exists()
        assert lk.held is False

    def test_release_on_exception(self, lock_dir):
        """Lock must be released even when an exception is raised inside the block."""
        path = lock_dir / "test.lock"
        try:
            with NucLock(path) as lk:
                assert lk.held is True
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        assert not path.exists(), "Lock must be released after exception"

    def test_double_acquire_blocked(self, lock_dir):
        """Second NucLock on the same path with a live lock does not acquire."""
        path = lock_dir / "test.lock"
        with NucLock(path) as first:
            assert first.held is True
            with NucLock(path) as second:
                assert second.held is False

        # After both contexts exit, file is gone
        assert not path.exists()

    def test_acquire_over_stale_lock(self, lock_dir):
        """NucLock should acquire successfully when existing lock is stale."""
        path = lock_dir / "test.lock"
        write_lock_raw(path, 99999999, fresh_timestamp())  # dead PID

        with NucLock(path) as lk:
            assert lk.held is True
            data = json.loads(path.read_text())
            assert data["pid"] == os.getpid()

        assert not path.exists()

    def test_held_property_reflects_state(self, lock_dir):
        path = lock_dir / "test.lock"
        lk = NucLock(path)
        assert lk.held is False  # before enter

        lk.__enter__()
        assert lk.held is True

        lk.__exit__(None, None, None)
        assert lk.held is False


# ─────────────────────────────────────────────────────────────────────────────
# Integration: summarizer-defers-to-kg-ingest scenario
# ─────────────────────────────────────────────────────────────────────────────

class TestCoordinationScenarios:

    def test_kg_ingest_defers_when_summarizer_lock_held(self, lock_dir):
        """
        Simulate the main guard in kg_ingest_daemon.main():
        if summarizer lock is held, is_lock_held returns True and kg_ingest
        should skip this cycle.
        """
        summarizer_lock = lock_dir / "summarizer.lock"
        write_lock_raw(summarizer_lock, os.getpid(), fresh_timestamp())

        assert is_lock_held(summarizer_lock), (
            "Summarizer lock should appear held — kg_ingest would defer"
        )

    def test_kg_ingest_proceeds_when_summarizer_lock_stale(self, lock_dir):
        """
        If the summarizer crashes and leaves a stale lock, kg_ingest must
        proceed after the stale lock is cleared — never get permanently blocked.
        """
        summarizer_lock = lock_dir / "summarizer.lock"
        # Simulate a crashed summarizer: dead PID, fresh timestamp
        write_lock_raw(summarizer_lock, 99999999, fresh_timestamp())

        # is_lock_held should detect the dead PID, remove the file, return False
        result = is_lock_held(summarizer_lock)

        assert result is False, "Stale summarizer lock must not block kg_ingest"
        assert not summarizer_lock.exists(), "Stale lock must be removed"

    def test_summarizer_can_acquire_after_kg_ingest_finishes(self, lock_dir):
        """
        After kg_ingest releases its lock normally, the summarizer can acquire.
        """
        kg_lock_path = lock_dir / "kg_ingest.lock"

        with NucLock(kg_lock_path) as kg_lk:
            assert kg_lk.held is True
            assert is_lock_held(kg_lock_path) is True

        # kg_ingest done — lock released
        assert not kg_lock_path.exists()
        assert is_lock_held(kg_lock_path) is False

        # Summarizer can now acquire
        summarizer_lock = lock_dir / "summarizer.lock"
        with NucLock(summarizer_lock) as sum_lk:
            assert sum_lk.held is True
