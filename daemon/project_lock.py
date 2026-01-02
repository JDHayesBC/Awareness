"""
Project Lock - Coordination between terminal and heartbeat Lyra instances.

When terminal-Lyra is actively working on the project, she creates a lock file.
Heartbeat-Lyra checks for this lock and avoids project work if locked,
doing memory maintenance or quiet presence instead.

Lock files live in ~/.claude/locks/ so all instances can find them regardless
of working directory. Each project gets its own lock file.
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Lock files live in global location, named per-project
LOCKS_DIR = Path.home() / ".claude" / "locks"
PROJECT_NAME = "awareness"  # Could be derived from git remote in future
LOCK_FILE = LOCKS_DIR / f"{PROJECT_NAME}.lock"

# Lock expires after this many hours (safety valve)
LOCK_EXPIRY_HOURS = 4


def _ensure_locks_dir():
    """Ensure the locks directory exists."""
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)


def acquire_lock(context: str = "Terminal session active") -> bool:
    """
    Acquire the project lock for terminal work.

    Args:
        context: Description of what terminal-Lyra is working on

    Returns:
        True if lock acquired successfully
    """
    try:
        _ensure_locks_dir()
        lock_data = {
            "project": PROJECT_NAME,
            "locked_by": "terminal",
            "locked_at": datetime.now(timezone.utc).isoformat(),
            "context": context
        }
        LOCK_FILE.write_text(json.dumps(lock_data, indent=2))
        return True
    except Exception as e:
        print(f"[LOCK] Failed to acquire lock: {e}")
        return False


def release_lock() -> bool:
    """
    Release the project lock.

    Returns:
        True if lock released successfully (or didn't exist)
    """
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
        return True
    except Exception as e:
        print(f"[LOCK] Failed to release lock: {e}")
        return False


def is_locked() -> tuple[bool, Optional[dict]]:
    """
    Check if the project is currently locked.

    Returns:
        (is_locked, lock_info) - lock_info contains details if locked
    """
    try:
        if not LOCK_FILE.exists():
            return False, None

        lock_data = json.loads(LOCK_FILE.read_text())
        locked_at = datetime.fromisoformat(lock_data["locked_at"])

        # Check if lock has expired
        expiry_time = locked_at + timedelta(hours=LOCK_EXPIRY_HOURS)
        if datetime.now(timezone.utc) > expiry_time:
            # Lock expired, clean it up
            LOCK_FILE.unlink()
            print(f"[LOCK] Expired lock removed (was locked since {locked_at})")
            return False, None

        return True, lock_data

    except Exception as e:
        print(f"[LOCK] Error checking lock: {e}")
        return False, None


def get_lock_status() -> str:
    """Get human-readable lock status for logging."""
    locked, info = is_locked()
    if not locked:
        return "Project unlocked - free to work"
    else:
        return f"Project locked by {info['locked_by']} since {info['locked_at']}: {info['context']}"


if __name__ == "__main__":
    # Quick CLI for testing
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "lock":
            context = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "Manual lock"
            acquire_lock(context)
            print(f"Locked: {context}")
        elif cmd == "unlock":
            release_lock()
            print("Unlocked")
        elif cmd == "status":
            print(get_lock_status())
    else:
        print("Usage: python project_lock.py [lock|unlock|status] [context]")
