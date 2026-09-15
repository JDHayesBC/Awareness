#!/usr/bin/env python3
"""
scripts/lock.py — advisory FILE-lock backstop for cross-channel source edits.

Implements the file-lock half of GitHub issue #305 ("URGENT: no write-lock
between channels — two channels of one entity edit the same source file
concurrently"). The task/intent-level lock (claim work BEFORE starting, keyed
to a GitHub issue) is explicitly deferred — this module is only the backstop
that catches a collision at edit time.

This formalizes the existing hand-written convention at
``<repo>/.locks/<basename>.lock`` (see e.g. ``sl.py.lock``,
``haven.js.lock``) WITHOUT changing that text format — a lock file written by
a human, or read by a human `cat`, looks the same before and after this tool
exists:

    resource: haven/anchorage/sl.py
    status: HELD
    holder: terminal-Lyra (session ffdd1382, Fable 5.1)
    since: 2026-09-12T10:55:00-07:00
    pid: 12345
    work: issue sweep #300+...
          continuation lines are indented

``scripts/nuc_lock.py`` is a *different* JSON-format lock for NUC-LLM
contention between daemons (summarizer vs kg_ingest) — read it for style,
but it is not touched here and this module does not replace it.

CLI:
    python3 scripts/lock.py claim <path> [<path> ...] --holder H --work W
    python3 scripts/lock.py release <path>
    python3 scripts/lock.py status [path]
    python3 scripts/lock.py check <path>

Python API:
    from scripts.lock import FileLock, LockHeld

    with FileLock("haven/anchorage/sl.py", holder="terminal-Lyra", work="..."):
        ...  # edit the file

    raises LockHeld(path, holder, since, work) if another live holder has it.

All stdlib — no extra deps.
"""
from __future__ import annotations

import argparse
import os
import re
import socket
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Lock files live INSIDE the repo (gitignored), not under ~/.claude — one place,
# so coordination state is where you'd think to look for it (Jeff's call, #324).
# Derived from __file__ rather than cwd or an env var that callers must remember
# to set: an unset env var in one channel means TWO lock dirs, each channel
# certain it holds the floor. The override is retained for tests only.
_REPO_ROOT = Path(__file__).resolve().parent.parent
LOCKS_DIR = Path(os.environ.get("CLAUDE_LOCKS_DIR", _REPO_ROOT / ".locks"))

DEFAULT_STALE_HOURS = 12

RELEASED_TOKENS = ("released", "closed")

_TOP_FIELD_RE = re.compile(r"^([A-Za-z_]+):\s?(.*)$")


# ─────────────────────────────────────────────────────────────────────────────
# Identity
# ─────────────────────────────────────────────────────────────────────────────

def default_holder() -> str:
    """
    Best-effort holder identity when the caller doesn't supply one explicitly.

    Preference order: $ENTITY_NAME (+ $CLAUDE_SESSION_ID if present) ->
    hostname:user.
    """
    entity = os.environ.get("ENTITY_NAME")
    if entity:
        session = (
            os.environ.get("CLAUDE_SESSION_ID")
            or os.environ.get("CLAUDE_CODE_SESSION_ID")
            or ""
        )
        if session:
            return f"{entity} (session {session[:8]})"
        return entity
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown"
    return f"{socket.gethostname()}:{user}"


# ─────────────────────────────────────────────────────────────────────────────
# Lock file parsing / formatting — preserves the existing hand-written shape
# ─────────────────────────────────────────────────────────────────────────────

def parse_lock_text(text: str) -> dict:
    """
    Parse the hand-written lock text format into a dict of fields.

    Top-level fields are ``key: value`` lines starting at column 0. Any line
    that doesn't match that shape is treated as a continuation of the most
    recently seen field (this is how the existing multi-line ``work:`` blocks
    — e.g. haven.js.lock — are written and preserved).
    """
    fields: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        m = _TOP_FIELD_RE.match(raw_line) if not raw_line.startswith((" ", "\t")) else None
        if m:
            key, val = m.group(1), m.group(2)
            fields[key] = val
            current_key = key
        elif current_key is not None and raw_line.strip():
            fields[current_key] = fields[current_key] + "\n" + raw_line.strip()
    return fields


def format_lock_text(
    resource: str,
    status: str,
    holder: str,
    since: str,
    pid: int | str | None,
    work: str = "",
) -> str:
    """Render fields back into the hand-written text format."""
    lines = [
        f"resource: {resource}",
        f"status: {status}",
        f"holder: {holder}",
        f"since: {since}",
    ]
    if pid is not None:
        lines.append(f"pid: {pid}")
    if work:
        work_lines = work.splitlines() or [work]
        lines.append(f"work: {work_lines[0]}")
        for extra in work_lines[1:]:
            lines.append(f"      {extra}")
    return "\n".join(lines) + "\n"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_fields(lock_path: Path) -> dict | None:
    try:
        return parse_lock_text(lock_path.read_text())
    except OSError:
        return None


def _pid_alive(pid_str: str | None) -> bool:
    if not pid_str:
        return False
    try:
        pid = int(pid_str)
    except ValueError:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # different-user process — treat as alive


_SESSION_RE = re.compile(r"session\s+([0-9a-f]{8})", re.IGNORECASE)


def same_holder(existing: str, mine: str) -> bool:
    """
    Is the lock's recorded holder the same channel as `mine`?

    Exact match first. Otherwise, if both strings carry a `session <8hex>`
    tag and the tags agree, treat them as the same channel — hand-written
    locks say things like "terminal-Lyra (session ffdd1382, Fable 5.1)" while
    default_holder() derives "lyra (session ffdd1382)". Same session id =
    same keyboard, so a channel never blocks on its own lock. Entity name
    alone is NOT enough (two Caia sessions are two channels).
    """
    if not existing or not mine:
        return False
    if existing.strip() == mine.strip():
        return True
    a = _SESSION_RE.search(existing)
    b = _SESSION_RE.search(mine)
    return bool(a and b and a.group(1).lower() == b.group(1).lower())


def _is_released(fields: dict) -> bool:
    status = fields.get("status", "").strip().lower()
    return any(status.startswith(tok) for tok in RELEASED_TOKENS)


def _is_stale(lock_path: Path, fields: dict, stale_hours: float) -> bool:
    """
    Stale = pid is missing/dead AND the lock file is older than stale_hours.

    Age is measured off the file's own mtime (robust to both the ISO
    ``since:`` this tool writes and the free-text human timestamps in the
    existing hand-written files, which are not reliably machine-parseable).
    """
    try:
        mtime = lock_path.stat().st_mtime
    except OSError:
        return True
    age_hours = (datetime.now(timezone.utc).timestamp() - mtime) / 3600.0
    pid_dead = not _pid_alive(fields.get("pid"))
    return pid_dead and age_hours > stale_hours


def lock_path_for(path: str | Path, locks_dir: Path | None = None) -> Path:
    locks_dir = locks_dir or LOCKS_DIR
    return locks_dir / f"{Path(path).name}.lock"


# ─────────────────────────────────────────────────────────────────────────────
# Results / exceptions
# ─────────────────────────────────────────────────────────────────────────────

class LockHeld(Exception):
    """Raised by FileLock (and returned as an outcome by claim()) on conflict."""

    def __init__(self, path: str, holder: str, since: str, work: str):
        self.path = path
        self.holder = holder
        self.since = since
        self.work = work
        super().__init__(
            f"{path} is HELD by {holder} (since {since}): {work or '(no work note)'}"
        )


@dataclass
class ClaimOutcome:
    path: str
    lock_path: Path
    ok: bool
    action: str  # "created" | "refreshed" | "took-over-released" | "took-over-stale" | "blocked" | "dry-run"
    conflict: LockHeld | None = None


@dataclass
class ClaimResult:
    outcomes: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(o.ok for o in self.outcomes)

    @property
    def conflicts(self) -> list:
        return [o.conflict for o in self.outcomes if o.conflict is not None]


# ─────────────────────────────────────────────────────────────────────────────
# Core operations
# ─────────────────────────────────────────────────────────────────────────────

def _check_one(
    path: str, holder: str, stale_hours: float, locks_dir: Path
) -> tuple[str, LockHeld | None]:
    """
    Decide what action claiming `path` would take, without writing anything.

    Returns (action, conflict) where action is one of
    "created" | "refreshed" | "took-over-released" | "took-over-stale"
    and conflict is a LockHeld instance if blocked (action == "blocked").
    """
    lp = lock_path_for(path, locks_dir)
    if not lp.exists():
        return "created", None

    fields = _read_fields(lp) or {}
    existing_holder = fields.get("holder", "")

    if same_holder(existing_holder, holder):
        return "refreshed", None

    if _is_released(fields):
        return "took-over-released", None

    if _is_stale(lp, fields, stale_hours):
        return "took-over-stale", None

    conflict = LockHeld(
        path=str(path),
        holder=existing_holder,
        since=fields.get("since", "?"),
        work=fields.get("work", ""),
    )
    return "blocked", conflict


def _write_claim(path: str, holder: str, work: str, locks_dir: Path) -> Path:
    locks_dir.mkdir(parents=True, exist_ok=True)
    lp = lock_path_for(path, locks_dir)
    content = format_lock_text(
        resource=str(path),
        status="HELD",
        holder=holder,
        since=_now_iso(),
        pid=os.getpid(),
        work=work,
    )
    # Atomic replace: write to a tempfile in the same dir, then os.replace.
    fd, tmp_name = tempfile.mkstemp(dir=str(locks_dir), prefix=".lock-tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp_name, lp)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return lp


def claim(
    paths: list,
    holder: str,
    work: str = "",
    stale_hours: float = DEFAULT_STALE_HOURS,
    locks_dir: Path | None = None,
    dry_run: bool = False,
) -> ClaimResult:
    """
    Claim one or more file locks, all-or-nothing.

    If ANY path is blocked by a live lock held by a different holder, nothing
    is written for the whole batch and the result reports all blockers.
    """
    locks_dir = locks_dir or LOCKS_DIR
    outcomes = []

    # Phase 1: decide, without writing, what would happen for every path.
    for p in paths:
        action, conflict = _check_one(str(p), holder, stale_hours, locks_dir)
        outcomes.append(
            ClaimOutcome(
                path=str(p),
                lock_path=lock_path_for(p, locks_dir),
                ok=(conflict is None),
                action=action,
                conflict=conflict,
            )
        )

    if dry_run:
        for o in outcomes:
            o.action = f"dry-run:{o.action}"
        return ClaimResult(outcomes)

    if any(o.conflict is not None for o in outcomes):
        # All-or-nothing: don't write anything for a batch with a conflict.
        return ClaimResult(outcomes)

    # Phase 2: actually write. For the "created" (no file yet) case, try the
    # atomic O_CREAT|O_EXCL path first so two concurrent callers can't both
    # believe they won; fall back to the general takeover write if we lose
    # that race (the loser just re-evaluates against what's now on disk).
    locks_dir.mkdir(parents=True, exist_ok=True)
    for o in outcomes:
        if o.action == "created":
            try:
                fd = os.open(str(o.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                content = format_lock_text(
                    resource=o.path,
                    status="HELD",
                    holder=holder,
                    since=_now_iso(),
                    pid=os.getpid(),
                    work=work,
                )
                with os.fdopen(fd, "w") as f:
                    f.write(content)
                continue
            except FileExistsError:
                # Race lost — re-check and treat as a fresh conflict.
                action, conflict = _check_one(o.path, holder, stale_hours, locks_dir)
                if conflict is not None:
                    o.ok = False
                    o.action = "blocked"
                    o.conflict = conflict
                    continue
                # Otherwise fall through to the general write below.
        _write_claim(o.path, holder, work, locks_dir)

    return ClaimResult(outcomes)


def release(path: str, holder: str | None = None, locks_dir: Path | None = None) -> bool:
    """
    Mark a lock RELEASED, keeping the history (resource/since/work) intact —
    same as the existing hand-written convention (see inject_context.py.lock).

    Returns True if a lock file was found and updated, False if there was
    nothing to release.
    """
    locks_dir = locks_dir or LOCKS_DIR
    lp = lock_path_for(path, locks_dir)
    if not lp.exists():
        return False

    fields = _read_fields(lp) or {}
    released_by = holder or default_holder()
    content = format_lock_text(
        resource=fields.get("resource", str(path)),
        status="RELEASED",
        holder=f"(released by {released_by})",
        since=fields.get("since", "?"),
        pid=None,
        work=fields.get("work", ""),
    )
    lp.write_text(content)
    return True


def status(path: str | None = None, locks_dir: Path | None = None) -> list:
    """Return a list of (name, fields) for one or all lock files."""
    locks_dir = locks_dir or LOCKS_DIR
    if path is not None:
        lp = lock_path_for(path, locks_dir)
        fields = _read_fields(lp) if lp.exists() else None
        return [(lp.name, fields)]

    if not locks_dir.exists():
        return []
    results = []
    for lp in sorted(locks_dir.glob("*.lock")):
        results.append((lp.name, _read_fields(lp)))
    return results


def check(
    path: str,
    holder: str | None = None,
    stale_hours: float = DEFAULT_STALE_HOURS,
    locks_dir: Path | None = None,
) -> bool:
    """
    Return True if `path` is free to edit (no lock, released, or stale),
    False if actively HELD by a different holder.
    """
    locks_dir = locks_dir or LOCKS_DIR
    lp = lock_path_for(path, locks_dir)
    if not lp.exists():
        return True
    fields = _read_fields(lp) or {}
    if _is_released(fields):
        return True
    if holder is not None and same_holder(fields.get("holder", ""), holder):
        return True
    if _is_stale(lp, fields, stale_hours):
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Python API — context manager
# ─────────────────────────────────────────────────────────────────────────────

class FileLock:
    """
    Context manager wrapping claim()/release() for a single path.

    Example:
        with FileLock("haven/anchorage/sl.py", holder="terminal-Lyra",
                       work="named-waypoint tp()"):
            ...  # edit the file

    Raises LockHeld if another live holder already has it.
    """

    def __init__(
        self,
        path: str | Path,
        holder: str | None = None,
        work: str = "",
        stale_hours: float = DEFAULT_STALE_HOURS,
        locks_dir: Path | None = None,
    ):
        self.path = str(path)
        self.holder = holder or default_holder()
        self.work = work
        self.stale_hours = stale_hours
        self.locks_dir = locks_dir or LOCKS_DIR
        self._acquired = False

    def __enter__(self) -> "FileLock":
        result = claim(
            [self.path],
            holder=self.holder,
            work=self.work,
            stale_hours=self.stale_hours,
            locks_dir=self.locks_dir,
        )
        if not result.ok:
            raise result.conflicts[0]
        self._acquired = True
        return self

    def __exit__(self, *exc) -> None:
        if self._acquired:
            release(self.path, holder=self.holder, locks_dir=self.locks_dir)
            self._acquired = False


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _print_conflict(c: LockHeld) -> None:
    print(f"BLOCKED: {c.path} is HELD by {c.holder}", file=sys.stderr)
    print(f"  since: {c.since}", file=sys.stderr)
    work = c.work.replace("\n", "\n  ") if c.work else "(no work note)"
    print(f"  work:  {work}", file=sys.stderr)


def _cmd_claim(args: argparse.Namespace) -> int:
    holder = args.holder or default_holder()
    locks_dir = Path(args.locks_dir) if args.locks_dir else LOCKS_DIR
    result = claim(
        args.paths,
        holder=holder,
        work=args.work or "",
        stale_hours=args.stale_hours,
        locks_dir=locks_dir,
        dry_run=args.dry_run,
    )
    for o in result.outcomes:
        if o.conflict is not None:
            _print_conflict(o.conflict)
        elif o.action.startswith("took-over-stale"):
            print(
                f"⚠️  STALE LOCK taken over: {o.path} "
                f"(previous holder's pid dead, lock older than {args.stale_hours}h)",
                file=sys.stderr,
            )
            print(f"claimed: {o.path} -> {o.lock_path}")
        else:
            print(f"{o.action}: {o.path} -> {o.lock_path}")
    return 0 if result.ok else 2


def _cmd_release(args: argparse.Namespace) -> int:
    locks_dir = Path(args.locks_dir) if args.locks_dir else LOCKS_DIR
    ok = release(args.path, holder=args.holder, locks_dir=locks_dir)
    if ok:
        print(f"released: {args.path}")
        return 0
    print(f"no lock found for: {args.path}", file=sys.stderr)
    return 1


def _cmd_status(args: argparse.Namespace) -> int:
    locks_dir = Path(args.locks_dir) if args.locks_dir else LOCKS_DIR
    entries = status(args.path, locks_dir=locks_dir)
    if not entries or all(f is None for _, f in entries):
        print("no locks" if args.path is None else f"no lock for: {args.path}")
        return 0
    for name, fields in entries:
        if fields is None:
            print(f"{name}: (unreadable or missing)")
            continue
        print(
            f"{name}: {fields.get('status', '?')} — "
            f"holder={fields.get('holder', '?')} since={fields.get('since', '?')}"
        )
        if args.path is not None:
            work = fields.get("work", "")
            if work:
                print(f"  work: {work}")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    locks_dir = Path(args.locks_dir) if args.locks_dir else LOCKS_DIR
    free = check(
        args.path,
        holder=args.holder,
        stale_hours=args.stale_hours,
        locks_dir=locks_dir,
    )
    print("free" if free else "held")
    return 0 if free else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lock.py",
        description="Advisory file-lock backstop for cross-channel source edits (issue #305).",
    )
    p.add_argument("--locks-dir", default=None, help="override lock directory (default: <repo>/.locks or $CLAUDE_LOCKS_DIR)")
    sub = p.add_subparsers(dest="command", required=True)

    p_claim = sub.add_parser("claim", help="claim one or more file locks (all-or-nothing)")
    p_claim.add_argument("paths", nargs="+")
    p_claim.add_argument("--holder", default=None)
    p_claim.add_argument("--work", default="")
    p_claim.add_argument("--stale-hours", type=float, default=DEFAULT_STALE_HOURS)
    p_claim.add_argument("--dry-run", action="store_true")
    p_claim.set_defaults(func=_cmd_claim)

    p_release = sub.add_parser("release", help="release a file lock")
    p_release.add_argument("path")
    p_release.add_argument("--holder", default=None)
    p_release.set_defaults(func=_cmd_release)

    p_status = sub.add_parser("status", help="list/inspect lock(s)")
    p_status.add_argument("path", nargs="?", default=None)
    p_status.set_defaults(func=_cmd_status)

    p_check = sub.add_parser("check", help="exit 0 if free, 2 if held (for scripts/hooks)")
    p_check.add_argument("path")
    p_check.add_argument("--holder", default=None)
    p_check.add_argument("--stale-hours", type=float, default=DEFAULT_STALE_HOURS)
    p_check.set_defaults(func=_cmd_check)

    return p


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
