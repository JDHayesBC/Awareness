"""
Unit tests for scripts/lock.py — advisory file-lock backstop (issue #305).

Fully isolated: every test redirects lock storage to a tmp_path directory
via the `locks_dir` fixture / CLAUDE_LOCKS_DIR env var, never touching
production ~/.claude/locks.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import scripts.lock as lock_mod
from scripts.lock import (
    FileLock,
    LockHeld,
    check,
    claim,
    format_lock_text,
    lock_path_for,
    parse_lock_text,
    release,
    status,
)


@pytest.fixture()
def locks_dir(tmp_path, monkeypatch):
    """
    Redirect all lock operations to a temporary directory. Patches the
    module-level LOCKS_DIR (read at import time from CLAUDE_LOCKS_DIR/HOME),
    the same pattern used by tests/test_nuc_lock.py.
    """
    d = tmp_path / "locks"
    d.mkdir()
    monkeypatch.setattr(lock_mod, "LOCKS_DIR", d)
    return d


def write_raw(locks_dir: Path, basename: str, text: str) -> Path:
    p = locks_dir / f"{basename}.lock"
    p.write_text(text)
    return p


def age_file(path: Path, hours: float) -> None:
    """Backdate a file's mtime by `hours`."""
    past = time.time() - hours * 3600
    os.utime(path, (past, past))


# ─────────────────────────────────────────────────────────────────────────────
# Text format round-trip — must not break the hand-written convention
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatCompat:
    def test_parses_existing_multiline_work_field(self):
        text = (
            "resource: haven/static/haven.js + haven/server.py room endpoints\n"
            "status: HELD\n"
            "holder: terminal-Lyra (session ffdd1382, Fable 5.1)\n"
            "since: 2026-09-12 10:55 PDT\n"
            "work: issue sweep #300+ (Jeff's fire-and-forget, 2026-09-12). #318 x\n"
            "      Crew agents edit under this lock; released when batch lands.\n"
        )
        fields = parse_lock_text(text)
        assert fields["status"] == "HELD"
        assert fields["holder"] == "terminal-Lyra (session ffdd1382, Fable 5.1)"
        assert "since we started" not in fields["work"]
        assert "Crew agents edit under this lock" in fields["work"]
        assert fields["work"].startswith("issue sweep #300+")

    def test_round_trip_format_then_parse(self):
        text = format_lock_text(
            resource="foo/bar.py",
            status="HELD",
            holder="terminal-Lyra",
            since="2026-09-12T10:00:00-07:00",
            pid=123,
            work="line one\nline two",
        )
        fields = parse_lock_text(text)
        assert fields["resource"] == "foo/bar.py"
        assert fields["status"] == "HELD"
        assert fields["pid"] == "123"
        assert fields["work"] == "line one\nline two"

    def test_hand_written_released_lock_parses(self):
        text = (
            "resource: .claude/hooks/inject_context.py\n"
            "status: RELEASED — free for either session to acquire\n"
            "holder: (released by terminal-Lyra)\n"
            "since: 2026-09-11 ~11:38 PDT\n"
            "work: issue-klaxon\n"
        )
        fields = parse_lock_text(text)
        assert fields["status"].startswith("RELEASED")


# ─────────────────────────────────────────────────────────────────────────────
# claim
# ─────────────────────────────────────────────────────────────────────────────

class TestClaim:
    def test_claim_fresh_creates_lock(self, locks_dir):
        result = claim(["foo.py"], holder="terminal-Lyra", work="doing a thing")
        assert result.ok
        lp = lock_path_for("foo.py", locks_dir)
        assert lp.exists()
        fields = parse_lock_text(lp.read_text())
        assert fields["status"] == "HELD"
        assert fields["holder"] == "terminal-Lyra"
        assert fields["pid"] == str(os.getpid())
        assert "since" in fields

    def test_claim_blocked_by_other_holder(self, locks_dir):
        claim(["foo.py"], holder="terminal-Lyra", work="first")
        result = claim(["foo.py"], holder="terminal-Caia", work="second")
        assert not result.ok
        assert len(result.conflicts) == 1
        c = result.conflicts[0]
        assert c.holder == "terminal-Lyra"
        assert "first" in c.work

        # original lock must be untouched
        lp = lock_path_for("foo.py", locks_dir)
        fields = parse_lock_text(lp.read_text())
        assert fields["holder"] == "terminal-Lyra"

    def test_claim_refresh_by_same_holder(self, locks_dir):
        claim(["foo.py"], holder="terminal-Lyra", work="first")
        lp = lock_path_for("foo.py", locks_dir)
        first_mtime = lp.stat().st_mtime

        time.sleep(0.01)
        result = claim(["foo.py"], holder="terminal-Lyra", work="second work note")
        assert result.ok
        assert result.outcomes[0].action == "refreshed"
        fields = parse_lock_text(lp.read_text())
        assert fields["work"] == "second work note"
        assert lp.stat().st_mtime >= first_mtime

    def test_claim_takeover_of_released_lock(self, locks_dir):
        claim(["foo.py"], holder="terminal-Lyra", work="first")
        release("foo.py", holder="terminal-Lyra")

        result = claim(["foo.py"], holder="terminal-Caia", work="taking over")
        assert result.ok
        assert result.outcomes[0].action == "took-over-released"
        fields = parse_lock_text(lock_path_for("foo.py", locks_dir).read_text())
        assert fields["status"] == "HELD"
        assert fields["holder"] == "terminal-Caia"

    def test_claim_takeover_of_stale_lock(self, locks_dir):
        # Dead PID, old file -> stale, takeable with a warning.
        write_raw(
            locks_dir,
            "foo.py",
            format_lock_text(
                resource="foo.py",
                status="HELD",
                holder="terminal-Lyra",
                since="2020-01-01T00:00:00-07:00",
                pid=999999999,
                work="crashed mid-edit",
            ),
        )
        lp = lock_path_for("foo.py", locks_dir)
        age_file(lp, hours=48)

        result = claim(["foo.py"], holder="terminal-Caia", work="taking over", stale_hours=12)
        assert result.ok
        assert result.outcomes[0].action == "took-over-stale"
        fields = parse_lock_text(lp.read_text())
        assert fields["holder"] == "terminal-Caia"

    def test_claim_not_stale_if_pid_alive_even_if_old(self, locks_dir):
        # Our own PID is alive; even an old lock must NOT be taken over.
        write_raw(
            locks_dir,
            "foo.py",
            format_lock_text(
                resource="foo.py",
                status="HELD",
                holder="terminal-Lyra",
                since="2020-01-01T00:00:00-07:00",
                pid=os.getpid(),
                work="still going, just old",
            ),
        )
        lp = lock_path_for("foo.py", locks_dir)
        age_file(lp, hours=48)

        result = claim(["foo.py"], holder="terminal-Caia", work="want it", stale_hours=12)
        assert not result.ok
        assert result.outcomes[0].action == "blocked"

    def test_claim_not_stale_within_threshold(self, locks_dir):
        write_raw(
            locks_dir,
            "foo.py",
            format_lock_text(
                resource="foo.py",
                status="HELD",
                holder="terminal-Lyra",
                since="2026-01-01T00:00:00-07:00",
                pid=999999999,  # dead
                work="recent",
            ),
        )
        lp = lock_path_for("foo.py", locks_dir)
        age_file(lp, hours=1)  # well under default 12h threshold

        result = claim(["foo.py"], holder="terminal-Caia", work="want it", stale_hours=12)
        assert not result.ok

    def test_claim_batch_all_or_nothing(self, locks_dir):
        claim(["a.py"], holder="terminal-Lyra", work="already held")

        result = claim(["b.py", "a.py", "c.py"], holder="terminal-Caia", work="batch")
        assert not result.ok
        # Neither b.py nor c.py should have been claimed, since the batch failed.
        assert not lock_path_for("b.py", locks_dir).exists()
        assert not lock_path_for("c.py", locks_dir).exists()

    def test_claim_batch_success_locks_all_paths(self, locks_dir):
        result = claim(["a.py", "b.py", "c.py"], holder="terminal-Lyra", work="batch ok")
        assert result.ok
        for name in ("a.py", "b.py", "c.py"):
            assert lock_path_for(name, locks_dir).exists()

    def test_dry_run_writes_nothing(self, locks_dir):
        result = claim(["foo.py"], holder="terminal-Lyra", work="just checking", dry_run=True)
        assert result.ok
        assert result.outcomes[0].action == "dry-run:created"
        assert not lock_path_for("foo.py", locks_dir).exists()


# ─────────────────────────────────────────────────────────────────────────────
# release / status / check
# ─────────────────────────────────────────────────────────────────────────────

class TestReleaseStatusCheck:
    def test_release_keeps_history(self, locks_dir):
        claim(["foo.py"], holder="terminal-Lyra", work="doing the thing, details here")
        ok = release("foo.py", holder="terminal-Lyra")
        assert ok

        fields = parse_lock_text(lock_path_for("foo.py", locks_dir).read_text())
        assert fields["status"].startswith("RELEASED")
        assert "released by terminal-Lyra" in fields["holder"]
        assert "doing the thing, details here" in fields["work"]

    def test_release_missing_lock_returns_false(self, locks_dir):
        assert release("nope.py") is False

    def test_status_lists_all(self, locks_dir):
        claim(["a.py", "b.py"], holder="terminal-Lyra", work="w")
        entries = status(locks_dir=locks_dir)
        names = {n for n, _ in entries}
        assert names == {"a.py.lock", "b.py.lock"}

    def test_status_single_path(self, locks_dir):
        claim(["a.py"], holder="terminal-Lyra", work="w")
        entries = status("a.py", locks_dir=locks_dir)
        assert len(entries) == 1
        name, fields = entries[0]
        assert fields["holder"] == "terminal-Lyra"

    def test_check_free_when_no_lock(self, locks_dir):
        assert check("nope.py") is True

    def test_check_held_when_locked_by_other(self, locks_dir):
        claim(["a.py"], holder="terminal-Lyra", work="w")
        assert check("a.py") is False

    def test_check_free_when_held_by_same_holder(self, locks_dir):
        claim(["a.py"], holder="terminal-Lyra", work="w")
        assert check("a.py", holder="terminal-Lyra") is True

    def test_check_free_after_release(self, locks_dir):
        claim(["a.py"], holder="terminal-Lyra", work="w")
        release("a.py", holder="terminal-Lyra")
        assert check("a.py") is True

    def test_check_free_when_stale(self, locks_dir):
        write_raw(
            locks_dir,
            "a.py",
            format_lock_text(
                resource="a.py",
                status="HELD",
                holder="terminal-Lyra",
                since="2020-01-01T00:00:00-07:00",
                pid=999999999,
                work="crashed",
            ),
        )
        age_file(lock_path_for("a.py", locks_dir), hours=48)
        assert check("a.py", stale_hours=12) is True


# ─────────────────────────────────────────────────────────────────────────────
# FileLock context manager
# ─────────────────────────────────────────────────────────────────────────────

class TestFileLock:
    def test_context_manager_acquires_and_releases(self, locks_dir):
        with FileLock("foo.py", holder="terminal-Lyra", work="editing"):
            fields = parse_lock_text(lock_path_for("foo.py", locks_dir).read_text())
            assert fields["status"] == "HELD"

        fields = parse_lock_text(lock_path_for("foo.py", locks_dir).read_text())
        assert fields["status"].startswith("RELEASED")

    def test_context_manager_raises_lock_held(self, locks_dir):
        claim(["foo.py"], holder="terminal-Lyra", work="already going")

        with pytest.raises(LockHeld) as exc_info:
            with FileLock("foo.py", holder="terminal-Caia", work="want in too"):
                pass  # pragma: no cover

        assert exc_info.value.holder == "terminal-Lyra"

    def test_context_manager_releases_on_exception(self, locks_dir):
        try:
            with FileLock("foo.py", holder="terminal-Lyra", work="risky"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        fields = parse_lock_text(lock_path_for("foo.py", locks_dir).read_text())
        assert fields["status"].startswith("RELEASED")


class TestSameHolder:
    def test_exact_match(self):
        from scripts.lock import same_holder
        assert same_holder("lyra (session ffdd1382)", "lyra (session ffdd1382)")

    def test_hand_written_lock_matches_derived_holder_by_session(self):
        from scripts.lock import same_holder
        assert same_holder("terminal-Lyra (session ffdd1382, Fable 5.1)", "lyra (session ffdd1382)")

    def test_different_session_same_entity_is_not_same(self):
        from scripts.lock import same_holder
        assert not same_holder("caia (session deadbeef)", "caia (session ffdd1382)")

    def test_no_session_tag_requires_exact(self):
        from scripts.lock import same_holder
        assert not same_holder("terminal-Caia", "caia")
        assert same_holder("terminal-Caia", "terminal-Caia")

    def test_check_free_for_hand_written_own_lock(self, locks_dir, tmp_path):
        from scripts.lock import check
        f = tmp_path / "sl.py"; f.write_text("x")
        (locks_dir / "sl.py.lock").write_text(
            "resource: haven/anchorage/sl.py\nstatus: HELD\nholder: terminal-Lyra (session ffdd1382, Fable 5.1)\nsince: 2026-09-12 10:55 PDT\n"
        )
        assert check(str(f), holder="lyra (session ffdd1382)", locks_dir=locks_dir)
        assert not check(str(f), holder="caia (session deadbeef)", locks_dir=locks_dir)
