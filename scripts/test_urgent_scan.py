"""Unit tests for urgent_scan.py — the critical-issue klaxon (no network needed).

    python3 scripts/test_urgent_scan.py

Covers label→priority parsing, days-open math, and the ambient block's contract:
empty-when-none, single vs multiple voice, severity ranking (critical outranks
high), live days-open (honest even on an old cache), and the stale-cache warning.
The WRITER (refresh → gh) is not unit-tested here; it's exercised live.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

try:
    from scripts import urgent_scan as us
except ImportError:  # pragma: no cover
    import urgent_scan as us  # type: ignore[no-redef]

_failures: list[str] = []
TODAY = dt.date(2026, 9, 11)


def check(cond: bool, msg: str) -> None:
    print(f"  {'ok  ' if cond else 'FAIL'} {msg}")
    if not cond:
        _failures.append(msg)


def _iso_days_ago(n: int) -> str:
    return (TODAY - dt.timedelta(days=n)).isoformat() + "T00:00:00Z"


def _write_cache(issues: list[dict], generated_at: str | None = None) -> None:
    """Point the module at a temp cache file holding these issues."""
    d = Path(tempfile.mkdtemp(prefix="urgent-"))
    us.CACHE_PATH = d / "urgent_issues.json"
    payload = {
        "generated_at": generated_at or dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "issues": issues,
    }
    us.CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")


def test_priority_of() -> None:
    print("priority_of (label list → severity):")
    check(us._priority_of([{"name": "bug"}, {"name": "priority:critical"}]) == "critical",
          "critical label detected")
    check(us._priority_of([{"name": "priority:high"}]) == "high", "high label detected")
    check(us._priority_of([{"name": "bug"}, {"name": "enhancement"}]) is None, "no priority → None")
    check(us._priority_of([{"name": "priority:low"}]) is None, "low is not klaxon-worthy → None")
    check(us._priority_of([{"name": "priority:high"}, {"name": "priority:critical"}]) == "critical",
          "highest severity wins when both present")
    check(us._priority_of(["priority:high"]) == "high", "bare-string labels tolerated")


def test_days_open() -> None:
    print("days_open (created_at → age):")
    check(us._days_open(_iso_days_ago(185), TODAY) == 185, "185d parsed")
    check(us._days_open("garbage", TODAY) is None, "garbage → None")
    check(us._days_open("", TODAY) is None, "empty → None")


def test_empty_when_none() -> None:
    print("empty-when-none (like [health]/[arcs]):")
    _write_cache([])
    check(us.format_urgent_block(today=TODAY) == "", "no issues → empty string")
    # Missing cache file entirely → empty, never raises.
    us.CACHE_PATH = Path(tempfile.mkdtemp(prefix="urgent-")) / "does_not_exist.json"
    check(us.format_urgent_block(today=TODAY) == "", "missing cache → empty string, no raise")


def test_single_form() -> None:
    print("single-issue voice (march-order-to-self):")
    _write_cache([{"number": 157, "title": 'URGENT: "Break Glass" recovery',
                   "priority": "critical", "created_at": _iso_days_ago(185)}])
    block = us.format_urgent_block(today=TODAY)
    check("#157" in block and "185d" in block, "shows number + live days-open")
    check("not Jeff's to notice" in block, "carries the self-directed reframe tagline")
    check("fix → document → close" in block, "carries the self-order")
    check('"Break Glass"' not in block, "inner double-quotes normalized (no clash)")


def test_multiple_and_ranking() -> None:
    print("multiple-issue voice + severity ranking:")
    _write_cache([
        {"number": 297, "title": "high but recent", "priority": "high", "created_at": _iso_days_ago(18)},
        {"number": 157, "title": "oldest critical", "priority": "critical", "created_at": _iso_days_ago(185)},
        {"number": 214, "title": "younger critical", "priority": "critical", "created_at": _iso_days_ago(122)},
    ])
    block = us.format_urgent_block(today=TODAY)
    # A 185d critical must be PICKED first even though an 18d high exists (severity, then age).
    first_157 = block.find("#157")
    first_297 = block.find("#297")
    check(first_157 != -1 and (first_297 == -1 or first_157 < first_297),
          "stalest critical picked ahead of a fresher high")
    check("2 critical" in block and "1 high" in block, "tail counts the full priority set")
    check("ROTTING" in block, "multiple-form header fires")


def test_high_only_softer_marker() -> None:
    print("high-only set uses the 🟠 marker, not 🔴:")
    _write_cache([{"number": 296, "title": "a high one", "priority": "high",
                   "created_at": _iso_days_ago(20)}])
    block = us.format_urgent_block(today=TODAY)
    check("🟠" in block and "🔴" not in block, "high-only → orange, not red")
    check("HIGH" in block, "severity label reads HIGH")


def test_live_days_open_on_old_cache() -> None:
    print("days-open recomputed live (honest even on a stale cache):")
    # Cache generated 'yesterday' but the issue's real age is computed from created_at.
    _write_cache([{"number": 157, "title": "x", "priority": "critical",
                   "created_at": _iso_days_ago(185)}],
                 generated_at=(dt.datetime(2026, 9, 10, 12, 0)).astimezone().isoformat())
    block = us.format_urgent_block(today=TODAY)
    check("185d" in block, "age from created_at, not from cache generated_at")


def test_stale_cache_warning() -> None:
    print("stale-cache self-check (refresher-down tripwire):")
    old = (dt.datetime.now().astimezone() - dt.timedelta(hours=5)).isoformat(timespec="seconds")
    _write_cache([{"number": 157, "title": "x", "priority": "critical",
                   "created_at": _iso_days_ago(185)}], generated_at=old)
    block = us.format_urgent_block(today=TODAY)
    check("stale" in block.lower(), "cache older than threshold → warns the timer may be down")


def main() -> int:
    for fn in (test_priority_of, test_days_open, test_empty_when_none,
               test_single_form, test_multiple_and_ranking, test_high_only_softer_marker,
               test_live_days_open_on_old_cache, test_stale_cache_warning):
        fn()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
        return 1
    print("all urgent_scan tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
