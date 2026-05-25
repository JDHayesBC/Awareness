"""
Integration tests for the NUC coordination contract (Issue #246).

These tests drive the daemon guard logic and NucLock internals at the
function/import level — no real NUC LLM, no PPS server touched.
CLAUDE_LOCKS_DIR is pointed at a tmp dir throughout.
"""
from __future__ import annotations

import json
import os
import sys
import importlib
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import scripts.nuc_lock as nuc_lock_mod
from scripts.nuc_lock import NucLock, is_lock_held, MAX_LOCK_AGE_SECONDS


# ─────────────────────────────────────────────────────────────────────────────
# Fixture: sandboxed locks dir (never touches ~/.claude/locks/)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def lock_dir(tmp_path, monkeypatch):
    locks = tmp_path / "locks"
    locks.mkdir()
    monkeypatch.setattr(nuc_lock_mod, "LOCKS_DIR", locks)
    monkeypatch.setattr(nuc_lock_mod, "SUMMARIZER_LOCK", locks / "summarizer.lock")
    monkeypatch.setattr(nuc_lock_mod, "KG_INGEST_LOCK", locks / "kg_ingest.lock")
    return locks


def write_lock_raw(path: Path, pid: int, started_at: str) -> None:
    path.write_text(json.dumps({"pid": pid, "started_at": started_at}))


def fresh_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# (d) NucLock does NOT acquire when a live lock is already held
#     (live-PID variant — different process, not just re-entrant same process)
# ─────────────────────────────────────────────────────────────────────────────

class TestNucLockDoesNotAcquireWhenLiveHeld:

    def test_second_lock_not_held_when_first_holds(self, lock_dir):
        """
        Write a lock attributed to our own PID (alive) so is_lock_held returns True.
        A new NucLock on the same path must NOT acquire.
        """
        path = lock_dir / "test.lock"
        # Pre-write a "held by us" lock (same PID = definitely alive)
        write_lock_raw(path, os.getpid(), fresh_ts())
        assert is_lock_held(path), "Pre-condition: lock should be seen as held"

        with NucLock(path) as lk:
            assert lk.held is False, "NucLock must not acquire when lock is live-held"
            # File must not have been overwritten
            data = json.loads(path.read_text())
            assert data["pid"] == os.getpid()

        # After exit of the non-owning NucLock, the file must still be there
        # (we don't own it, so we must not delete it)
        assert path.exists(), "Non-owning NucLock must not delete a live lock on exit"

    def test_non_owner_exit_does_not_remove_file(self, lock_dir):
        """
        NucLock.__exit__ must be a no-op when self._owned is False.
        """
        path = lock_dir / "test.lock"
        write_lock_raw(path, os.getpid(), fresh_ts())

        lk = NucLock(path)
        lk.__enter__()
        assert lk.held is False
        lk.__exit__(None, None, None)

        assert path.exists(), "Non-owning exit must not unlink the file"


# ─────────────────────────────────────────────────────────────────────────────
# (e) Release only unlinks when the PID still matches (no clobbering)
# ─────────────────────────────────────────────────────────────────────────────

class TestReleaseOnlyUnlinksWhenPidMatches:

    def test_release_skips_unlink_when_pid_replaced(self, lock_dir):
        """
        If the lock file has been replaced by another process between acquire
        and release, our __exit__ must not unlink the new owner's lock.
        """
        path = lock_dir / "test.lock"
        lk = NucLock(path)
        lk.__enter__()
        assert lk.held is True

        # Simulate another process stealing the lock between acquire and release
        write_lock_raw(path, os.getpid() + 10000, fresh_ts())

        lk.__exit__(None, None, None)

        # The file must still exist (we didn't own it at exit time)
        assert path.exists(), (
            "NucLock.__exit__ must not delete a lock it no longer owns"
        )

    def test_release_unlinks_when_pid_matches(self, lock_dir):
        """Normal release removes the file when PID matches."""
        path = lock_dir / "test.lock"
        with NucLock(path) as lk:
            assert lk.held is True
        assert not path.exists(), "Normal release must remove the lock file"


# ─────────────────────────────────────────────────────────────────────────────
# Lock dir auto-create
# ─────────────────────────────────────────────────────────────────────────────

class TestLockDirAutoCreate:

    def test_lock_dir_created_on_acquire(self, tmp_path, monkeypatch):
        """
        NucLock must create the locks directory if it does not yet exist.
        """
        nonexistent = tmp_path / "new_subdir" / "locks"
        assert not nonexistent.exists(), "Pre-condition: dir must not exist"

        monkeypatch.setattr(nuc_lock_mod, "LOCKS_DIR", nonexistent)
        monkeypatch.setattr(nuc_lock_mod, "SUMMARIZER_LOCK", nonexistent / "summarizer.lock")
        monkeypatch.setattr(nuc_lock_mod, "KG_INGEST_LOCK", nonexistent / "kg_ingest.lock")

        lock_path = nonexistent / "test.lock"
        with NucLock(lock_path) as lk:
            assert lk.held is True
            assert nonexistent.exists(), "Lock dir must have been created"
            assert lock_path.exists()

        assert not lock_path.exists()

    def test_is_lock_held_on_nonexistent_dir_returns_false(self, tmp_path, monkeypatch):
        """
        is_lock_held on a path inside a nonexistent directory should return False
        (path.exists() is False).
        """
        nonexistent = tmp_path / "ghost_dir" / "summarizer.lock"
        result = is_lock_held(nonexistent)
        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# Stale lock (dead PID) treated as absent AND removed as side effect
# ─────────────────────────────────────────────────────────────────────────────

class TestStaleLockSideEffect:

    def test_dead_pid_lock_removed_and_returns_false(self, lock_dir):
        """
        is_lock_held with a dead PID must return False AND delete the file.
        PID 999999 is used — functionally guaranteed not to exist.
        """
        path = lock_dir / "summarizer.lock"
        write_lock_raw(path, 999999, fresh_ts())
        assert path.exists()

        result = is_lock_held(path)

        assert result is False
        assert not path.exists(), "Stale lock must be removed as a side effect"

    def test_subsequent_acquire_succeeds_after_stale_removal(self, lock_dir):
        """
        After a stale lock is removed by is_lock_held, a fresh NucLock must
        be able to acquire the same path.
        """
        path = lock_dir / "test.lock"
        write_lock_raw(path, 999999, fresh_ts())

        # Trigger stale removal via is_lock_held
        assert is_lock_held(path) is False
        assert not path.exists()

        # Now NucLock must acquire cleanly
        with NucLock(path) as lk:
            assert lk.held is True
            data = json.loads(path.read_text())
            assert data["pid"] == os.getpid()

        assert not path.exists()


# ─────────────────────────────────────────────────────────────────────────────
# Integration: kg_ingest_daemon guard logic (import-level, no LLM/PPS calls)
# ─────────────────────────────────────────────────────────────────────────────

class TestKgIngestDaemonGuard:
    """
    Drive the SUMMARIZER_LOCK guard at the top of kg_ingest_daemon.main()
    without actually running the daemon or touching the NUC.

    Strategy: monkeypatch SUMMARIZER_LOCK in nuc_lock_mod (which kg_ingest_daemon
    imports from scripts.nuc_lock).  Write a live lock there.  Call is_lock_held
    with the patched path to confirm the daemon guard would defer.

    We cannot call main() directly because it has a hard sys.exit(0) and also
    tries to reach real services (LLM, Neo4j).  Instead we test the guard
    predicate — is_lock_held(SUMMARIZER_LOCK) — which is the exact expression
    used in the if-statement at the top of main().
    """

    def test_guard_detects_live_summarizer_lock(self, lock_dir):
        """
        When summarizer.lock is held (live PID, fresh timestamp),
        is_lock_held(SUMMARIZER_LOCK) returns True — matching the guard condition
        in kg_ingest_daemon.main() that triggers the "Deferring" path.
        """
        summarizer_lock = nuc_lock_mod.SUMMARIZER_LOCK  # already patched to lock_dir
        write_lock_raw(summarizer_lock, os.getpid(), fresh_ts())

        # This is the exact predicate used in the daemon guard
        should_defer = is_lock_held(nuc_lock_mod.SUMMARIZER_LOCK)

        assert should_defer is True, (
            "Guard must return True for a live summarizer lock — daemon would defer"
        )

    def test_guard_allows_run_when_no_summarizer_lock(self, lock_dir):
        """
        When no summarizer.lock exists, the guard passes — daemon would proceed.
        """
        summarizer_lock = nuc_lock_mod.SUMMARIZER_LOCK
        assert not summarizer_lock.exists()

        should_defer = is_lock_held(nuc_lock_mod.SUMMARIZER_LOCK)

        assert should_defer is False, (
            "Guard must return False when no summarizer lock exists — daemon proceeds"
        )

    def test_guard_allows_run_when_summarizer_lock_stale(self, lock_dir):
        """
        A crashed summarizer leaves a stale lock (dead PID).
        The guard must return False and remove the lock so kg_ingest proceeds
        and is never permanently blocked.
        """
        summarizer_lock = nuc_lock_mod.SUMMARIZER_LOCK
        write_lock_raw(summarizer_lock, 999999, fresh_ts())  # dead PID

        should_defer = is_lock_held(nuc_lock_mod.SUMMARIZER_LOCK)

        assert should_defer is False, "Dead-PID summarizer lock must not block kg_ingest"
        assert not summarizer_lock.exists(), "Stale lock must have been removed"

    def test_nuc_lock_roundtrip_pid_in_file(self, lock_dir):
        """
        NucLock round-trip: acquiring writes current PID to file; releasing removes it.
        This is the contract kg_ingest_daemon relies on for KG_INGEST_LOCK.
        """
        path = nuc_lock_mod.KG_INGEST_LOCK

        with NucLock(path) as lk:
            assert lk.held is True
            data = json.loads(path.read_text())
            assert data["pid"] == os.getpid(), "Lock file must contain our PID"
            assert "started_at" in data

        assert not path.exists(), "Lock file must be removed after context exit"
