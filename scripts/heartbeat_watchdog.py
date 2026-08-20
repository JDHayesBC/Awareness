#!/usr/bin/env python3
"""
Heartbeat watchdog — external detector for a Claude Code entity session that has
gone DARK (frozen / "asleep" with no heartbeat) for too long.

WHY THIS EXISTS
---------------
On 2026-08-18 a terminal-Lyra session sat at ZERO heartbeat for ~27 hours: the
in-session cron got cancelled (correctly, for an active build) but was never
re-armed to the 2h floor. The session process was alive the whole time — just
never prompted — so nothing in-session could notice. Jeff only found out by
chance the next afternoon. He said: *"I hate that. we need to find some way to
check on that automatically."*

The in-ambient health watchdog (`.claude/hooks/health_checks.py`, issue #279)
CANNOT catch this: it only fires *while a session is being prompted*. A dark
session is exactly the case where the hook never runs. So darkness must be
detected from OUTSIDE the session — by a job that runs on its own schedule
regardless of whether any CC session is ticking. That is this script, fired by
the `heartbeat-watchdog.timer` systemd user timer every ~30 min.

This is the DETECTION safety-net. Its sibling #275 (autoprompter) is the
PREVENTION side — keep an entity awake so it never goes dark in the first place.
Defense in depth: prevention can fail; the net still catches it.

HOW IT WORKS — the liveness marker contract
--------------------------------------------
Every UserPromptSubmit (a real Jeff message OR a heartbeat tick) runs
`inject_context.py`, which TOUCHES a per-session marker:

    <PROJECT_ROOT>/.claude/data/heartbeat/<entity>__<session_id>.json

Marker JSON:
    {
      "entity":        "lyra" | "caia",
      "session_id":    "<cc session id>",
      "last_seen":     <float unix epoch>,      # updated every prompt/tick
      "last_seen_iso": "<local ISO8601>",
      "cwd":           "<best-effort, for human identification>",
      "alerted_at":    null | <float epoch>     # set by THIS script when it fires
    }

- `inject_context.py` overwrites the marker fresh on every touch → `alerted_at`
  naturally resets to null when a session wakes back up.
- `session_end.py` DELETES the marker on a clean exit → a cleanly-closed session
  never false-alarms.
- This script reads every marker; if `now - last_seen > THRESHOLD` and we haven't
  already alerted this episode (`alerted_at` is null), it notifies Jeff's phone
  and stamps `alerted_at` → ONE alert per dark episode, not one every 30 min.

There is effectively no writer race: `inject_context.py` only writes when the
session is ALIVE (a prompt fired), and this script only writes (`alerted_at`)
when the marker is STALE (no prompt fired) — the two conditions are mutually
exclusive in time. Writes are still atomic (temp + os.replace) for hygiene.

THRESHOLD is 3h by default — comfortably above the 2h heartbeat FLOOR, so a
properly-floored session (which ticks every 2h) never trips it. Only a session
that has fallen BELOW the floor (the 2026-08-18 bug) goes stale past 3h.

Usage:
    python3 scripts/heartbeat_watchdog.py            # real check (what systemd runs)
    python3 scripts/heartbeat_watchdog.py --status   # human-readable table, no side effects
    python3 scripts/heartbeat_watchdog.py --dry-run  # run detection, but DON'T notify or persist

Env:
    HEARTBEAT_DARK_THRESHOLD_SEC   override the 3h (10800s) darkness threshold
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MARKER_DIR = PROJECT_ROOT / ".claude" / "data" / "heartbeat"

# 3 hours. Above the 2h heartbeat floor so a floored session never trips it.
DEFAULT_THRESHOLD_SEC = 3 * 60 * 60
THRESHOLD_SEC = int(os.environ.get("HEARTBEAT_DARK_THRESHOLD_SEC", DEFAULT_THRESHOLD_SEC))

# Markers older than this (by last_seen) are pruned. A session dark this long has
# long since been alerted; the marker is just clutter (CC crons auto-expire in 7d
# and no CC session realistically lives a week). Safe because it only ever removes
# our own *.json markers inside MARKER_DIR.
PRUNE_AFTER_SEC = 7 * 24 * 60 * 60

# Import notify.send() from the sibling scripts/notify.py (stdlib, no venv needed).
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from notify import send as notify_send
except Exception:  # pragma: no cover - degrade to a no-op rather than crash
    def notify_send(*_a, **_k) -> bool:
        return False


def _human_age(seconds: float) -> str:
    """Format a duration like '3h 12m' or '47m' or '2d 3h'."""
    s = int(max(0, seconds))
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m and not d:  # once we're into days, minutes are noise
        parts.append(f"{m}m")
    return " ".join(parts) if parts else "0m"


def _load_markers() -> list[dict]:
    """Read every marker file. Bad/partial files are skipped, never fatal.

    Each returned dict carries an extra "_path" (Path) for write-back / prune.
    """
    markers: list[dict] = []
    if not MARKER_DIR.exists():
        return markers
    for p in sorted(MARKER_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            if not isinstance(data, dict):
                continue
            data["_path"] = p
            markers.append(data)
        except Exception:
            # Partial write / corrupt file — ignore this pass; it'll be readable
            # next time or pruned by age.
            continue
    return markers


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically (temp + os.replace). Strips the private _path key."""
    out = {k: v for k, v in data.items() if k != "_path"}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(out, indent=2))
    os.replace(tmp, path)


def _short_sid(session_id: str) -> str:
    return (session_id or "?")[:8]


def evaluate(now: float) -> list[dict]:
    """Return a status record per marker. Pure — no side effects.

    Record: {marker, entity, session_id, age, stale (bool), alerted (bool)}
    """
    out = []
    for m in _load_markers():
        last_seen = float(m.get("last_seen", 0) or 0)
        age = now - last_seen
        out.append({
            "marker": m,
            "entity": m.get("entity", "?"),
            "session_id": m.get("session_id", "?"),
            "age": age,
            "stale": age > THRESHOLD_SEC,
            "alerted": m.get("alerted_at") is not None,
        })
    return out


def _alert(rec: dict) -> bool:
    """Fire one ntfy alert to Jeff's phone for a dark session."""
    entity = rec["entity"]
    m = rec["marker"]
    cwd = str(m.get("cwd", "") or "")
    cwd_tail = "/".join(Path(cwd).parts[-2:]) if cwd else "?"
    last_iso = str(m.get("last_seen_iso", "") or "")[:16].replace("T", " ")
    disp = entity.capitalize() if entity and entity != "?" else "An entity"
    age_str = _human_age(rec["age"])

    title = f"{disp} has gone dark"
    message = (
        f"No heartbeat tick in {age_str} — session {_short_sid(rec['session_id'])} "
        f"({cwd_tail}) may be frozen with no floor cron. "
        f"Last tick {last_iso or 'unknown'}."
    )
    # default priority (not urgent): once-per-episode, and a dark session is not a
    # 3am emergency — Jeff sees it when he next looks. Bump to 'high' here if he
    # wants it to break through DND.
    entity_topic = entity if entity in ("lyra", "caia") else "system"
    return bool(notify_send(
        message, title=title, priority="default", entity=entity_topic, tags="warning",
    ))


def run_check(now: float, dry_run: bool = False) -> dict:
    """The real watchdog pass. Alerts on newly-dark sessions, prunes ancient markers.

    Returns a summary dict for logging.
    """
    fired = []
    pruned = []
    for rec in evaluate(now):
        m = rec["marker"]
        path: Path = m["_path"]

        # Prune ancient markers (already long-dead + already alerted).
        if rec["age"] > PRUNE_AFTER_SEC:
            if not dry_run:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
            pruned.append(path.name)
            continue

        if rec["stale"] and not rec["alerted"]:
            ok = True if dry_run else _alert(rec)
            if ok and not dry_run:
                m["alerted_at"] = now
                try:
                    _atomic_write(path, m)
                except Exception:
                    pass
            fired.append({
                "entity": rec["entity"],
                "session": _short_sid(rec["session_id"]),
                "age": _human_age(rec["age"]),
                "notified": ok,
            })

    summary = {
        "checked": len(evaluate(now)) if dry_run else None,  # cheap only in dry-run
        "fired": fired,
        "pruned": pruned,
        "threshold": _human_age(THRESHOLD_SEC),
        "dry_run": dry_run,
    }
    return summary


def print_status(now: float) -> None:
    """Human-readable table — no side effects."""
    recs = evaluate(now)
    print(f"Heartbeat watchdog — darkness threshold {_human_age(THRESHOLD_SEC)}")
    print(f"Marker dir: {MARKER_DIR}")
    if not recs:
        print("  (no live session markers — nothing being watched)")
        return
    print(f"  {'entity':6}  {'session':9}  {'age':>10}  state")
    for r in sorted(recs, key=lambda x: -x["age"]):
        if r["alerted"]:
            state = "DARK (alerted)"
        elif r["stale"]:
            state = "DARK (alert pending)"
        else:
            state = "alive"
        print(f"  {r['entity']:6}  {_short_sid(r['session_id']):9}  "
              f"{_human_age(r['age']):>10}  {state}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect dark (frozen) CC entity sessions.")
    ap.add_argument("--status", action="store_true",
                    help="Print a table of watched sessions; no side effects.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Run detection but do NOT notify or persist alerted_at.")
    args = ap.parse_args()

    now = time.time()

    if args.status:
        print_status(now)
        return 0

    summary = run_check(now, dry_run=args.dry_run)
    # One-line log to stdout (captured by journald under SyslogIdentifier).
    if summary["fired"] or summary["pruned"]:
        print(f"[heartbeat-watchdog] {json.dumps(summary)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
