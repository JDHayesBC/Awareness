"""
Cooperative lockfile helpers for NUC LLM contention management.

Two daemons drive the same local NUC LLM:
  - scripts/summarize_daemon.py  (higher priority — holds NUC while summarizing)
  - scripts/kg_ingest_daemon.py  (lower priority — defers when summarizer is active)

Protocol:
  - summarizer writes  ~/.claude/locks/summarizer.lock  while doing LLM work
  - kg_ingest writes   ~/.claude/locks/kg_ingest.lock   while running

Lockfile format (JSON):
  {"pid": <int>, "started_at": "<ISO-8601 UTC>"}

Stale rules (fail-safe toward "let the other process proceed"):
  A lock is stale if:
    (a) its PID is not alive (ProcessLookupError from os.kill(pid, 0)), OR
    (b) its timestamp is older than MAX_LOCK_AGE_SECONDS

Any process reading a stale lock must remove it and treat it as absent.

All stdlib — no extra deps.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Directory shared with the existing instance-coordination locks in the repo.
LOCKS_DIR = Path(os.environ.get("CLAUDE_LOCKS_DIR", Path.home() / ".claude" / "locks"))

SUMMARIZER_LOCK = LOCKS_DIR / "summarizer.lock"
KG_INGEST_LOCK = LOCKS_DIR / "kg_ingest.lock"

# A lock whose timestamp is older than this is considered stale regardless of PID.
# Worst-case summarizer run is ~5 min per entity × 2 entities = ~10 min.
# kg_ingest worst-case is DAEMON_BATCH (50) × per-message LLM time.
# 15 min is safely above both.
MAX_LOCK_AGE_SECONDS = 15 * 60


def _ensure_locks_dir() -> None:
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)


def _read_lock(path: Path) -> dict | None:
    """
    Read a lock file and return its parsed contents, or None if unreadable/missing.

    Does NOT check for staleness — caller handles that.
    """
    try:
        raw = path.read_text()
        data = json.loads(raw)
        if "pid" in data and "started_at" in data:
            return data
        return None
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def _pid_alive(pid: int) -> bool:
    """
    Return True if the process with the given PID exists.

    Uses signal 0 (existence check, sends no actual signal).
    PermissionError means the process exists but is owned by another user — alive.
    ProcessLookupError means the PID is gone — not alive.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Different-user process — treat as alive for safety.
        return True


def _is_stale(lock_data: dict) -> bool:
    """
    Return True if the lock data represents a dead or time-expired lock.

    Stale = PID not alive OR timestamp older than MAX_LOCK_AGE_SECONDS.
    """
    pid = lock_data.get("pid")
    started_at = lock_data.get("started_at", "")

    if pid is None:
        return True

    if not _pid_alive(pid):
        return True

    try:
        started = datetime.fromisoformat(started_at)
        age_seconds = (datetime.now(timezone.utc) - started).total_seconds()
        if age_seconds > MAX_LOCK_AGE_SECONDS:
            return True
    except (ValueError, TypeError):
        # Unparseable timestamp — treat as stale.
        return True

    return False


def _write_lock(path: Path) -> None:
    """Write our PID + UTC timestamp to the lock file."""
    _ensure_locks_dir()
    payload = {
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload))


def is_lock_held(path: Path) -> bool:
    """
    Return True if the given lock file is present and held by a live, non-stale process.

    Side effect: removes the lock file if it is found to be stale (fail-safe).
    """
    if not path.exists():
        return False

    data = _read_lock(path)
    if data is None:
        # Unreadable or malformed — remove defensively.
        logger.debug("nuc_lock: removing unreadable lock at %s", path)
        path.unlink(missing_ok=True)
        return False

    if _is_stale(data):
        logger.debug(
            "nuc_lock: removing stale lock at %s (pid=%s started_at=%s)",
            path,
            data.get("pid"),
            data.get("started_at"),
        )
        path.unlink(missing_ok=True)
        return False

    return True


class NucLock:
    """
    Context manager that acquires a lockfile on entry and releases it on exit.

    Always releases in __exit__ (exception or not) so the lock is never
    orphaned by a crash inside the with-block.

    Example:
        with NucLock(SUMMARIZER_LOCK, log_fn=log) as acquired:
            if not acquired:
                # another instance already holds it
                return
            do_llm_work()
    """

    def __init__(self, path: Path, log_fn=None) -> None:
        self._path = path
        self._log = log_fn or (lambda msg: logger.info(msg))
        self._owned = False

    def __enter__(self) -> "NucLock":
        _ensure_locks_dir()

        if is_lock_held(self._path):
            self._log(
                f"nuc_lock: {self._path.name} already held by another process — not acquiring"
            )
            self._owned = False
        else:
            _write_lock(self._path)
            self._owned = True
            self._log(
                f"nuc_lock: acquired {self._path.name} (pid={os.getpid()})"
            )
        return self

    def __exit__(self, *_) -> None:
        if self._owned:
            try:
                # Only remove the file if it still contains our PID (defensive).
                data = _read_lock(self._path)
                if data and data.get("pid") == os.getpid():
                    self._path.unlink(missing_ok=True)
                    self._log(f"nuc_lock: released {self._path.name}")
            except OSError:
                pass  # best-effort release
            self._owned = False

    @property
    def held(self) -> bool:
        """True after a successful acquisition."""
        return self._owned
