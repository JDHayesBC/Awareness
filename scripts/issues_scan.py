#!/usr/bin/env python3
"""
issues_scan.py — the issue-landscape ambient block.

A count-level landscape of open GitHub issues, designed to create a gentle
"pull" toward issue work during free time (Jeff's charge, 2026-10-08). Unlike
[urgent] which fires only for priority:critical/high issues that MUST be tended,
[issues] is a peripheral invitation — the board as a horizon to wander toward
when the field wants it, not a to-do list.

Follows the same write/read split as urgent_scan.py:
  * refresh()            — the WRITER. Runs gh, categorizes by label, writes cache.
                           Driven by a ~30-min systemd --user timer (issues-refresh.timer).
                           Never called from the synchronous hook.
  * format_issues_block() — the READER. Reads only the cached JSON (instant),
                           renders a compact one-line front-block entry. Imported by
                           inject_context.py; must never raise.

Shape (mirrors urgent_scan / arc_scan discipline exactly):
  * empty-when-zero    — 0 active open issues → "" (no noise on a clean board);
  * one-line landscape — "N open · X bugs · Y enhancements · Z untriaged"
  * excludes parked    — triage:parked issues are set down deliberately; they are
                         not a pull toward action and are subtracted from active total;
  * never raises       — a broken sense must degrade gracefully, never crash injection.

Usage:
    python3 scripts/issues_scan.py --refresh     # WRITER: gh → cache (the timer runs this)
    python3 scripts/issues_scan.py               # READER: print the ambient block (or nothing)
    python3 scripts/issues_scan.py --list        # human table of the cached counts
    python3 scripts/issues_scan.py --refresh --show  # refresh then print block
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = PROJECT_ROOT / ".claude" / "data" / "issues_cache.json"

# Label to exclude from the "active" count: these are set down deliberately.
PARKED_LABEL = "triage:parked"

# Categories surfaced in the landscape line, in display order.
# Each entry: (display_key, list_of_label_names_to_match).
# A label name must match exactly (case-insensitive) to count toward that category.
# An issue can be counted in multiple categories (e.g. a bug with priority:high).
_CATEGORIES: list[tuple[str, list[str]]] = [
    ("critical",      ["priority:critical"]),
    ("high",          ["priority:high"]),
    ("bugs",          ["bug"]),
    ("enhancements",  ["enhancement"]),
    ("infrastructure",["infrastructure"]),
    ("good-first",    ["good first issue"]),
]

# Display names for the landscape line (default: use the key itself).
_DISPLAY_NAME: dict[str, str] = {
    "critical":      "critical",
    "high":          "high",
    "bugs":          "bugs",
    "enhancements":  "enhancements",
    "infrastructure":"infra",
    "good-first":    "good-first",
}

# How stale the cache may be before the block flags it.
# The timer fires every 30 min; a >2h gap means the timer likely died.
_STALE_CACHE_HOURS = 2


def _label_names(labels: list) -> list[str]:
    """Normalise gh's label list (list of {name:...} dicts or bare strings) to lowercase names."""
    result = []
    for lab in labels or []:
        name = lab.get("name", "") if isinstance(lab, dict) else str(lab)
        result.append(name.strip().lower())
    return result


# --------------------------------------------------------------------------------------
# WRITER — the refresher (timer-driven; never called from the hook)
# --------------------------------------------------------------------------------------

def refresh(limit: int = 500) -> dict:
    """Query GitHub for all open issues and write the issues landscape cache.

    Returns the written payload. Raises on gh failure — the caller (timer service)
    logs it. The READER side must never raise.
    """
    out = subprocess.run(
        ["gh", "issue", "list", "--state", "open",
         "--json", "number,title,labels,createdAt", "--limit", str(limit)],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30, check=True,
    ).stdout
    raw = json.loads(out)

    total = len(raw)
    parked_count = 0
    counts: dict[str, int] = {key: 0 for key, _ in _CATEGORIES}
    untriaged_count = 0

    for issue in raw:
        names = _label_names(issue.get("labels", []))
        is_parked = PARKED_LABEL in names
        if is_parked:
            parked_count += 1
        # Count category membership (parked issues still counted in category totals
        # so the block is honest, but excluded from the active headline number).
        matched_any = False
        for cat_key, patterns in _CATEGORIES:
            for p in patterns:
                if p.lower() in names:
                    counts[cat_key] += 1
                    matched_any = True
                    break
        # Untriaged: no recognized category label and not parked
        if not matched_any and not is_parked:
            untriaged_count += 1

    payload = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "total": total,
        "active": total - parked_count,  # what the headline number shows
        "parked": parked_count,
        "counts": counts,
        "untriaged": untriaged_count,
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
    """Read the cached payload. Returns {} on any error (missing/corrupt)."""
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


def format_issues_block() -> str:
    """Return the ambient [issues] landscape line, or "" when the board is empty.

    A count-level view designed to create a gentle pull toward issue work during
    free time. Not a klaxon — the [urgent] block handles critical/high already.
    Empty-when-zero; never raises.

    Example output:
      [issues] 43 open · 9 high · 10 bugs · 25 enhancements · 4 untriaged
    """
    try:
        cache = load_cache()
        if not cache:
            return ""

        active = cache.get("active", cache.get("total", 0))
        if active == 0:
            return ""

        counts = cache.get("counts", {})
        untriaged = cache.get("untriaged", 0)

        parts: list[str] = [f"{active} open"]

        for cat_key, _ in _CATEGORIES:
            n = counts.get(cat_key, 0)
            if n:
                label = _DISPLAY_NAME.get(cat_key, cat_key)
                parts.append(f"{n} {label}")

        if untriaged:
            parts.append(f"{untriaged} untriaged")

        line = "**[issues]** " + " · ".join(parts)

        # Staleness self-check: a frozen cache is worse than no cache.
        age = _cache_age_hours(cache.get("generated_at", ""))
        if age is not None and age > _STALE_CACHE_HOURS:
            line += (f" ⚠ (cache {age:.0f}h stale — "
                     f"`systemctl --user status issues-refresh.timer`)")

        return line

    except Exception as exc:  # pragma: no cover - must never break the hook
        # Same contract as urgent_scan / arc_scan: silence reads as "board clear".
        # A crash that renders as silence is a lie in exactly that direction.
        return ("**[issues] ⚠ scan failed — this sense is BLIND this tick "
                f"({type(exc).__name__}: {str(exc)[:80]})**")


def _list_table(cache: dict) -> str:
    """Human-readable summary of the cached landscape."""
    if not cache:
        return "no cache — run with --refresh first."
    lines = [f"ISSUE LANDSCAPE (as of {cache.get('generated_at', '?')}):"]
    lines.append(f"  total: {cache.get('total', 0)}  active: {cache.get('active', 0)}  "
                 f"parked: {cache.get('parked', 0)}")
    counts = cache.get("counts", {})
    for cat_key, _ in _CATEGORIES:
        n = counts.get(cat_key, 0)
        if n:
            lines.append(f"  {n:3d}  {cat_key}")
    untriaged = cache.get("untriaged", 0)
    if untriaged:
        lines.append(f"  {untriaged:3d}  untriaged")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Issue-landscape ambient block.")
    ap.add_argument("--refresh", action="store_true",
                    help="WRITER: query gh and rewrite the cache")
    ap.add_argument("--show", action="store_true",
                    help="print the ambient block as the hook would see it")
    ap.add_argument("--list", action="store_true",
                    help="print a human table of the cached counts")
    args = ap.parse_args()

    if args.refresh:
        try:
            payload = refresh()
            print(f"refreshed: {payload['total']} total, {payload['active']} active "
                  f"({payload['parked']} parked) → {CACHE_PATH}", file=sys.stderr)
        except Exception as e:
            print(f"refresh FAILED: {e}", file=sys.stderr)
            return 1

    if args.list:
        print(_list_table(load_cache()))
        return 0

    if args.show or not args.refresh:
        block = format_issues_block()
        if block:
            print(block)
        else:
            print("(empty — no active issues or no cache)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
