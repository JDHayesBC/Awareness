#!/usr/bin/env python3
"""
backup_freshness.py — make damned sure the backups are HAPPENING.

WHY THIS EXISTS
---------------
On 2026-09-29 Jeff looked at Cloudflare and couldn't tell whether backups were
landing there. They weren't: the off-site push (push_break_glass.py) had run
exactly once, by hand, on 09-11, and was never scheduled. Every local job was
green the whole time, so nothing looked wrong. The failure was an ABSENCE, and
absences don't raise errors. The only way to catch one is to check, from
outside, that each backup's newest artifact is actually recent.

This script reads the four artifacts the backup chain produces, and ages each
one against its schedule:

    local     newest pps_backup_*.tar.gz            daily 04:00      stale > 30h
    validate  backup_validation.json (ts + ok)      Sun 04:30        stale > 8d, or ok=false
    package   newest awareness-recovery-*.zip       Sun 03:13        stale > 8d
    offsite   break_glass_offsite.json last_success Sun 03:13 (push) stale > 8d

Any stale or failed check sends a HIGH-priority alert to Jeff's phone
(system-alerts). It re-alerts every day it stays stale, which is deliberate:
this runs daily, so the alert repeats at most once a day until the problem is fixed.

On Sundays, when everything is green, it also sends one LOW-priority
"all backups fresh" summary. Silence is ambiguous (for months notify.py returned 200
to zero subscribers, and every alert went nowhere), so a weekly positive signal
is what lets Jeff tell "all fine" from "the watcher itself is dead".

Usage:
    python3 scripts/backup_freshness.py             # real check (what systemd runs)
    python3 scripts/backup_freshness.py --status    # table, no notifications
    python3 scripts/backup_freshness.py --summary   # force the green summary today
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = Path("/mnt/c/Users/Jeff/awareness_backups")
BREAK_GLASS_DIR = BACKUP_DIR / "break_glass"
OFFSITE_MARKER = PROJECT_ROOT / ".claude" / "data" / "break_glass_offsite.json"
# validate_backup.py prefers ~/.claude/data/ but falls back when that's root-owned.
VALIDATION_PATHS = [
    Path.home() / ".claude" / "data" / "backup_validation.json",
    Path.home() / ".claude" / "backup_validation.json",
]

HOUR = 3600
DAY = 24 * HOUR
LOCAL_MAX = 30 * HOUR   # daily job + slack for a slow night
WEEKLY_MAX = 8 * DAY    # weekly jobs + one day of slack

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from notify import send as notify_send
except Exception:  # pragma: no cover - degrade to no-op rather than crash
    def notify_send(*_a, **_k) -> bool:
        return False


def _age_str(seconds: float | None) -> str:
    if seconds is None:
        return "never"
    s = int(max(0, seconds))
    d, s = divmod(s, DAY)
    h, s = divmod(s, HOUR)
    if d:
        return f"{d}d {h}h"
    return f"{h}h {s // 60}m"


def _newest(dir_: Path, pattern: str) -> Path | None:
    files = [p for p in dir_.glob(pattern) if p.is_file()]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _iso_age(ts: str | None, now: float) -> float | None:
    if not ts:
        return None
    try:
        return now - _dt.datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return None


def evaluate(now: float) -> list[dict]:
    """One record per check: name, age (s or None), limit, ok (bool), detail."""
    out = []

    p = _newest(BACKUP_DIR, "pps_backup_*.tar.gz")
    age = now - p.stat().st_mtime if p else None
    out.append({"name": "local daily", "age": age, "limit": LOCAL_MAX,
                "ok": age is not None and age <= LOCAL_MAX,
                "detail": p.name if p else "no pps_backup_*.tar.gz found"})

    verdict, vpath = None, None
    for vp in VALIDATION_PATHS:
        if vp.exists():
            try:
                verdict, vpath = json.loads(vp.read_text()), vp
                break
            except Exception:
                continue
    age = _iso_age((verdict or {}).get("ts"), now)
    passed = bool((verdict or {}).get("ok"))
    out.append({"name": "restore-validate", "age": age, "limit": WEEKLY_MAX,
                "ok": age is not None and age <= WEEKLY_MAX and passed,
                "detail": ("passed" if passed else f"FAILED: {(verdict or {}).get('errors')}")
                          if verdict else "no backup_validation.json"})

    p = _newest(BREAK_GLASS_DIR, "awareness-recovery-*.zip")
    age = now - p.stat().st_mtime if p else None
    out.append({"name": "break-glass pkg", "age": age, "limit": WEEKLY_MAX,
                "ok": age is not None and age <= WEEKLY_MAX,
                "detail": p.name if p else "no awareness-recovery-*.zip found"})

    marker = {}
    if OFFSITE_MARKER.exists():
        try:
            marker = json.loads(OFFSITE_MARKER.read_text())
        except Exception:
            marker = {}
    age = _iso_age(marker.get("last_success_at"), now)
    out.append({"name": "off-site (R2)", "age": age, "limit": WEEKLY_MAX,
                "ok": age is not None and age <= WEEKLY_MAX,
                "detail": marker.get("object_key", "no off-site marker")})
    return out


def print_status(recs: list[dict]) -> None:
    for r in recs:
        mark = "OK   " if r["ok"] else "STALE"
        print(f"  {mark}  {r['name']:17} {_age_str(r['age']):>9} old "
              f"(limit {_age_str(r['limit'])})  {r['detail']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Alert if any backup stage has gone stale.")
    ap.add_argument("--status", action="store_true", help="print table; no notifications")
    ap.add_argument("--summary", action="store_true", help="send the green summary even if not Sunday")
    args = ap.parse_args()

    now = _dt.datetime.now().timestamp()
    recs = evaluate(now)
    print_status(recs)
    if args.status:
        return 0

    bad = [r for r in recs if not r["ok"]]
    if bad:
        lines = [f"{r['name']}: {_age_str(r['age'])} old — {r['detail']}" for r in bad]
        notify_send("\n".join(lines), title=f"🚨 Backups NOT happening ({len(bad)} stale)",
                    priority="high", entity="system", tags="rotating_light")
        print(f"[backup-freshness] ALERT sent: {len(bad)} stale")
        return 1

    if args.summary or _dt.date.today().weekday() == 6:  # Sunday
        lines = [f"{r['name']}: {_age_str(r['age'])} old" for r in recs]
        notify_send("\n".join(lines), title="✅ All backups fresh",
                    priority="low", entity="system", tags="white_check_mark")
        print("[backup-freshness] weekly green summary sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
