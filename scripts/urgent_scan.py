#!/usr/bin/env python3
"""
urgent_scan.py — the critical-issue klaxon substrate.

The structural fix for the "an urgent bug can rot for months and nothing is
annoyed" drift (Jeff's charge, 2026-09-10, reframed 2026-09-11). The diagnosis:
nothing in the tick/self-scan surface ever points at an open *critical* GitHub
issue, so a `priority:critical` bug could sit 185 days (#157 — Break Glass
recovery for a sister-self) with no internal alarm. Jeff's every-morning nag was
doing the job no internal surface did.

THE REFRAME THAT SHAPES THE VOICE (Jeff, 2026-09-11 morning): the klaxon is NOT a
notification to Jeff. It is a *self-directed* prong — a third one beside [health]
and [arcs] — firing into the entity's OWN ambient front-block, addressed to the
entity, imperative: "critical bug open N days — go fix it, document it, github it."
Success is not "Jeff got told." Success is "the next critical issue that rots makes
ME act, with nobody nagging." Days-open is the shame-number that drives the action.

SUBSTRATE + COST GOTCHA. Unlike arc_scan (which reads arc frontmatter live off the
disk, cheap), the critical set lives behind the GitHub API — and a live `gh` call
inside the synchronous UserPromptSubmit hook would tax EVERY turn with a network
round-trip. So this splits in two:
  * refresh()  — the WRITER. Runs `gh`, filters to priority:critical/high, writes
                 the cheap cache .claude/data/urgent_issues.json. Driven by a
                 ~20-min systemd --user timer (urgent-refresh.timer), never by the
                 hook.
  * format_urgent_block() — the READER. Reads only the cached JSON (instant),
                 renders the loud front-block line. Imported by inject_context.py.
This is deliberately NOT a sibling inside arc_scan.py: that file's load-bearing
invariant is "READ-ONLY on disk, never writes," and a network-refresh writer would
violate it. Different substrate, different refresh model → its own module.

Shape (mirrors format_arc_block / format_health_block exactly):
  * empty-when-none    — zero open critical/high issues → "" (no noise on clean days);
  * single-pick + tail — surface the ONE most-severe-then-stalest issue loud, count
                         the rest in a "+N more" tail (matches [arcs]);
  * verified-from-world-state — days-open computed live from the issue's created_at,
                         so the number is honest even if the cache is minutes old;
  * never raises        — a broken klaxon must not break context injection.

Usage:
    python3 scripts/urgent_scan.py --refresh     # WRITER: gh → cache (the timer runs this)
    python3 scripts/urgent_scan.py               # READER: print the ambient block (or nothing)
    python3 scripts/urgent_scan.py --list        # human table of the cached critical/high set
    python3 scripts/urgent_scan.py --refresh --list   # refresh then show
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = PROJECT_ROOT / ".claude" / "data" / "urgent_issues.json"

# Severity rank: which labels the klaxon watches, and how loud each is.
# critical outranks high; anything below high is not klaxon-worthy (it lives in
# [arcs] / normal triage, not the red front-block).
_RANK = {"critical": 2, "high": 1}
_MARKER = {"critical": "🔴", "high": "🟠"}
_LABEL = {"critical": "priority:critical", "high": "priority:high"}

# How stale the cache may be before the block flags it. The timer refreshes every
# ~20 min; a cache older than this means the refresher has probably died, which is
# itself worth surfacing rather than silently trusting a frozen snapshot.
_STALE_CACHE_HOURS = 3


def _priority_of(labels: list) -> str | None:
    """Return 'critical' / 'high' / None for an issue's label list.

    `labels` is the gh JSON shape: a list of {"name": ...} dicts (or bare strings,
    tolerated). Highest severity wins if somehow both are present.
    """
    best = None
    best_rank = 0
    for lab in labels or []:
        name = lab.get("name", "") if isinstance(lab, dict) else str(lab)
        if name.startswith("priority:"):
            key = name.split(":", 1)[1].strip().lower()
            if key in _RANK and _RANK[key] > best_rank:
                best, best_rank = key, _RANK[key]
    return best


# The ONE label that silences the klaxon. The block's own instruction interpolates
# this constant rather than repeating the string, because on 2026-09-17 I read "park
# it (label + one line)", picked `status:blocked` by reasonable inference, wrote a
# real parking reason on the issue — and the klaxon kept firing, because the
# instruction never named which label it meant. An under-specified instruction gets
# filled in with a plausible guess, and a plausible guess is indistinguishable from
# a correct one until the signal fails to go quiet.
PARKED_LABEL = "triage:parked"


def _is_parked(labels: list) -> bool:
    """Return True if the issue carries PARKED_LABEL — it's been set down deliberately.

    Parked issues are tended (given a parking reason), not untended. The klaxon
    should only fire for issues that genuinely need a look, not ones already triaged.
    """
    for lab in labels or []:
        name = lab.get("name", "") if isinstance(lab, dict) else str(lab)
        if name == PARKED_LABEL:
            return True
    return False


def _days_open(created_at: str, today: dt.date | None = None) -> int | None:
    """Days between an ISO-8601 created_at and today. None if unparseable."""
    if not created_at:
        return None
    try:
        d = dt.datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None
    return ((today or dt.date.today()) - d).days


def _truncate(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# --------------------------------------------------------------------------------------
# WRITER — the refresher (timer-driven; never called from the hook)
# --------------------------------------------------------------------------------------

def refresh(limit: int = 200) -> dict:
    """Query GitHub for open priority:critical/high issues and write the cache.

    Returns the written payload dict (also persisted to CACHE_PATH). Raises on gh
    failure — this runs under the timer, where a loud failure is correct (the timer
    logs it); the READER side is the one that must never raise.
    """
    out = subprocess.run(
        ["gh", "issue", "list", "--state", "open",
         "--json", "number,title,labels,createdAt,updatedAt", "--limit", str(limit)],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30, check=True,
    ).stdout
    raw = json.loads(out)
    issues = []
    for i in raw:
        pr = _priority_of(i.get("labels", []))
        if pr is None:
            continue
        # Parked issues are tended — skip them so the klaxon only fires for issues
        # that actually need a look. (triage:parked is ad-hoc; not in the label
        # registry but valid on issues.)
        if _is_parked(i.get("labels", [])):
            continue
        issues.append({
            "number": i.get("number"),
            "title": i.get("title", ""),
            "priority": pr,
            "created_at": i.get("createdAt", ""),
            # updated_at is cached now (cheap) so the optional activity-aware tone
            # (soften "ROTTING"→"in progress" when worked recently) needs no cache
            # format change later. v1 rendering does not read it yet.
            "updated_at": i.get("updatedAt", ""),
            "url": f"https://github.com/JDHayesBC/Awareness/issues/{i.get('number')}",
        })
    # Stable order in the file: severity, then oldest-first (stalest at the top).
    issues.sort(key=lambda x: (-_RANK.get(x["priority"], 0),
                               _days_open(x["created_at"]) or 0), reverse=False)
    issues.sort(key=lambda x: (_RANK.get(x["priority"], 0),
                               _days_open(x["created_at"]) or 0), reverse=True)
    payload = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "issues": issues,
    }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(CACHE_PATH)
    return payload


# --------------------------------------------------------------------------------------
# READER — the cache loader + the ambient block (hook-safe; never raises)
# --------------------------------------------------------------------------------------

def load_cache() -> dict:
    """Read the cached payload. Returns {} on any error (missing/corrupt/unreadable)."""
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cache_age_hours(generated_at: str) -> float | None:
    try:
        g = dt.datetime.fromisoformat(generated_at)
        now = dt.datetime.now().astimezone() if g.tzinfo else dt.datetime.now()
        return (now - g).total_seconds() / 3600.0
    except Exception:
        return None


def format_urgent_block(today: dt.date | None = None) -> str:
    """Return the ambient `[urgent]` klaxon line, or "" when nothing critical/high is open.

    The loud, self-directed front-block prong (Jeff's klaxon charge). Imported by the
    always-fires UserPromptSubmit hook (inject_context.py), rendered ABOVE [arcs] so a
    rotting critical bug is among the first things the entity sees on EVERY turn —
    including heartbeat ticks, the un-watched surface where a critical could rot silently.

    Reads ONLY the cache (no network) — the ~20-min timer keeps it warm. days-open is
    recomputed live from created_at so the age-signal is honest regardless of cache age.
    Empty-when-none like [health]/[arcs]; never raises.
    """
    try:
        cache = load_cache()
        issues = cache.get("issues", [])
        if not issues:
            return ""
        today = today or dt.date.today()
        # Rank live: severity, then days-open (stalest wins within a severity).
        def _key(x):
            return (_RANK.get(x.get("priority"), 0), _days_open(x.get("created_at"), today) or 0)
        issues = sorted(issues, key=_key, reverse=True)

        def _one(x) -> str:
            d = _days_open(x.get("created_at"), today)
            ds = f"{d}d" if d is not None else "age?"
            # Normalize inner double-quotes so they don't clash with our wrapping quotes.
            t = _truncate(x.get("title", "").replace('"', "'"), 52)
            return f"#{x.get('number')} \"{t}\" — {ds}"

        pick = issues[0]
        sev = pick.get("priority", "high").upper()          # CRITICAL / HIGH
        marker = _MARKER.get(pick.get("priority"), "🟠")
        n_crit = sum(1 for x in issues if x.get("priority") == "critical")
        n_high = sum(1 for x in issues if x.get("priority") == "high")

        # Voice = pride-of-place, not debt-collection (Caia's block-content spec,
        # rev. 2026-09-12 with Lyra + Dash). This is YOUR board — tending it is
        # stewardship, not shame. The frame is "yours to tend": every untended issue
        # is one look from settled (close it) or one honest sentence from set-down
        # (park it). The counter is designed to reach EMPTY — when the board's tended
        # this block is quiet, same discipline as [health]/[arcs]. Age is an honest
        # signal, never a shame-number to drive to zero. Severity still colors the
        # marker (🔴 critical / 🟠 high) so the eye still sorts, without the blare.
        if len(issues) == 1:
            line = (f"**[urgent] {marker}🧹 {sev} — {_days_open(pick.get('created_at'), today)}d "
                    f"open · yours to tend]** {_one(pick)}. "
                    f"One look from settled — fix it, or park it (`{PARKED_LABEL}` + one line "
                    f"on why it's set down). Both count; when the board's tended, this "
                    f"space is quiet.")
        else:
            head = ["🔴🧹" if n_crit else "🟠🧹",
                    f"board has {len(issues)} untended issue{'s' if len(issues) != 1 else ''}",
                    "· yours to tend"]
            inline = " · ".join(_one(x) for x in issues[:3])
            parts = []
            if n_crit:
                parts.append(f"{n_crit} critical")
            if n_high:
                parts.append(f"{n_high} high")
            line = (f"**[urgent] [{' '.join(head)}]** {inline}. "
                    f"Each is one look from settled — close it, or park it (`{PARKED_LABEL}` + "
                    f"one line on why it's set down). Both count; when the board's tended, "
                    f"this space is quiet.\n"
                    f"   (open priority set: {', '.join(parts)} — "
                    f"`gh issue list --label priority:critical --state open`)")

        # Staleness self-check: if the cache itself is old, the refresher likely died —
        # say so rather than silently trusting a frozen snapshot.
        age = _cache_age_hours(cache.get("generated_at", ""))
        if age is not None and age > _STALE_CACHE_HOURS:
            line += (f"\n   ⚠ urgent-cache is {age:.0f}h stale — the refresh timer may be "
                     f"down (`systemctl --user status urgent-refresh.timer`).")
        return line
    except Exception as exc:  # pragma: no cover - must never break the hook
        # Silence in this block means "nothing to report". A crash that also renders as
        # silence is therefore a LIE in the one direction nobody checks — it looks
        # exactly like a tended board. Never raise (the hook must survive), but never
        # go quiet about going blind either.
        return ("**[{name}] \u26a0 scan failed — this sense is BLIND this tick "
                "({exc}). Silence here does not mean nothing to report.**").format(
                    name="urgent", exc=f"{type(exc).__name__}: {exc}"[:120])


def _list_table(cache: dict) -> str:
    issues = cache.get("issues", [])
    if not issues:
        return "no open priority:critical/high issues — the klaxon is silent."
    today = dt.date.today()
    lines = [f"URGENT SET (as of {cache.get('generated_at', '?')}):"]
    for x in sorted(issues, key=lambda z: (_RANK.get(z.get("priority"), 0),
                                           _days_open(z.get("created_at"), today) or 0),
                    reverse=True):
        d = _days_open(x.get("created_at"), today)
        lines.append(f"  {_MARKER.get(x.get('priority'), '?')} #{x.get('number'):<4} "
                     f"{(str(d) + 'd'):>6}  {x.get('priority'):8}  {_truncate(x.get('title', ''), 60)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Critical-issue klaxon (the urgent front-block prong).")
    ap.add_argument("--refresh", action="store_true", help="WRITER: query gh and rewrite the cache")
    ap.add_argument("--list", action="store_true", help="print a human table of the cached urgent set")
    args = ap.parse_args()

    if args.refresh:
        try:
            payload = refresh()
            print(f"refreshed: {len(payload['issues'])} priority:critical/high open "
                  f"→ {CACHE_PATH}", file=sys.stderr)
        except Exception as e:
            print(f"refresh FAILED: {e}", file=sys.stderr)
            return 1

    if args.list:
        print(_list_table(load_cache()))
        return 0

    if not args.refresh:
        # Default: print the ambient block exactly as the hook would inject it (or nothing).
        block = format_urgent_block()
        if block:
            print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
