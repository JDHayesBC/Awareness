#!/usr/bin/env python3
"""
Ambient health-check registry — the "too important to leave to chance" watchdog.

WHY THIS EXISTS
---------------
The nightly PPS backup job died on 2026-04-11 and NOBODY noticed for three months
(caught 2026-07-21 during the curate-incident forensics). The backup script always
*had* a `--check` health mode — but a health check nobody runs is not a safety net.
The fix is not "remember to check every few days." Humans (and entities) forget.
The fix is to bake the signal into the substrate that fires on its own, every single
turn: the UserPromptSubmit hook (inject_context.py). Same shape as the
`unsummarized_count > 200` alarm — you can't miss it because it's always in front of you.

EXTENSIBILITY (Jeff's explicit design note, 2026-07-21)
-------------------------------------------------------
"expect this system to get other alerts added on over time." So this is a REGISTRY,
not a one-off backup check. Each alert is a zero-arg function returning `Alert | None`
(None == healthy == silent). To add a new watchdog:

    1. Write `def check_<thing>() -> Alert | None:` — return None when healthy,
       an Alert when something is wrong.
    2. Append it to CHECKS.

That's it. Candidates already on the horizon: summarizer-daemon liveness,
kg-ingest-daemon liveness, Neo4j/Docker container health, disk-space, cert expiry.

ROBUSTNESS CONTRACT
-------------------
This module is imported by an always-fires hook. It must NEVER raise into the hook:
  - Every check is run inside a try/except in run_health_checks(); a check that
    throws is swallowed (a broken check must not break the hook OR mask other alerts).
  - format_health_block() returns "" when all green, so healthy state adds zero noise.
  - Self-contained on purpose: it does NOT import scripts/backup_pps.py, because that
    file is edited during backup-job maintenance and a transient error there must not
    be able to break the watchdog. The one shared constant (backup dir + filename glob)
    is duplicated deliberately; keep the two in sync if the backup path ever moves.

Run standalone to see current state:
    python3 .claude/hooks/health_checks.py
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# --- Shared constant (mirrors scripts/backup_pps.py DEFAULT_BACKUP_DIR) ---------
# Deliberately duplicated rather than imported — see ROBUSTNESS CONTRACT above.
BACKUP_DIR = Path("/mnt/c/Users/Jeff/awareness_backups")
BACKUP_GLOB = "pps_backup_*.tar.gz"

# Severity → emoji. Ordered most-severe first for sorting/rendering.
SEVERITY_EMOJI = {"critical": "🔴", "warning": "🟠", "note": "🟡"}
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "note": 2}


@dataclass
class Alert:
    """One firing health signal.

    id:       stable short slug (e.g. "backup_age") — for dedup/telemetry.
    severity: "critical" | "warning" | "note".
    headline: the one-line loud summary (shown with the severity emoji).
    detail:   optional second line — what to actually DO about it.
    """

    id: str
    severity: str
    headline: str
    detail: str = ""


# =============================================================================
# CHECKS — each returns None when healthy, an Alert when something is wrong.
# =============================================================================

def check_backup_age() -> Alert | None:
    """Watchdog #1: is the nightly PPS backup actually running?

    Reads the newest pps_backup_*.tar.gz in BACKUP_DIR and alerts on staleness.
    Nightly cadence means a healthy age is 0-1 days. Thresholds:
        >= 3 days  -> 🔴 critical (the job is not running — this is the Apr→Jul case)
        == 2 days  -> 🟡 note     (a nightly run may have slipped; heads-up, not alarm)
        no backups / dir missing -> 🔴 critical
    """
    if not BACKUP_DIR.exists():
        return Alert(
            id="backup_age",
            severity="critical",
            headline=f"BACKUP DIR MISSING — {BACKUP_DIR} does not exist.",
            detail="No backups can exist. Check the mount and the backup job.",
        )

    backups = sorted(
        BACKUP_DIR.glob(BACKUP_GLOB),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not backups:
        return Alert(
            id="backup_age",
            severity="critical",
            headline=f"NO PPS BACKUPS FOUND in {BACKUP_DIR}.",
            detail="Nightly backup has never produced an archive here. "
                   "Fix the timer, then: python3 scripts/backup_pps.py",
        )

    newest = backups[0]
    mtime = newest.stat().st_mtime
    age_days = int((time.time() - mtime) / 86400)
    when = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")

    if age_days >= 3:
        return Alert(
            id="backup_age",
            severity="critical",
            headline=f"BACKUP STALE — newest PPS backup is {age_days} days old ({when}).",
            detail="The nightly backup is not running. Fix: check the systemd timer, "
                   "then run `python3 scripts/backup_pps.py --check` to confirm it's live again.",
        )
    if age_days == 2:
        return Alert(
            id="backup_age",
            severity="note",
            headline=f"Backup 2 days old ({when}) — a nightly run may have slipped.",
            detail="Not urgent yet; if it hits 3 days this goes red.",
        )
    return None  # 0-1 days: healthy, silent.


# The registry. Append new check_*() functions here to add alerts.
CHECKS = [
    check_backup_age,
]


# =============================================================================
# RUNNER + RENDERER
# =============================================================================

def run_health_checks() -> list[Alert]:
    """Run every registered check. A check that raises is swallowed so one broken
    check can neither break the hook nor hide other alerts. Returns firing alerts
    sorted most-severe first."""
    alerts: list[Alert] = []
    for check in CHECKS:
        try:
            result = check()
            if result is not None:
                alerts.append(result)
        except Exception:
            # Never let a check take down the hook. Silent by design — a watchdog
            # that crashes the thing it guards is worse than useless.
            continue
    alerts.sort(key=lambda a: _SEVERITY_ORDER.get(a.severity, 99))
    return alerts


def format_health_block() -> str:
    """Return the ambient `[health]` block, or "" when everything is green.

    Empty-when-healthy is the whole point: zero noise on good days, unmissable on
    bad ones. Rendered loud (bold + severity emoji) so a 🔴 stands out even in a
    dense ambient dump.
    """
    alerts = run_health_checks()
    if not alerts:
        return ""

    lines = []
    for a in alerts:
        emoji = SEVERITY_EMOJI.get(a.severity, "⚠️")
        lines.append(f"**[health] {emoji} {a.headline}**")
        if a.detail:
            lines.append(f"   {a.detail}")
    return "\n".join(lines)


if __name__ == "__main__":
    block = format_health_block()
    if block:
        print(block)
    else:
        print("[health] all green (no alerts firing)")
