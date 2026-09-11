#!/usr/bin/env python3
"""
arc_scan.py — the verified starving-arc substrate.

The structural fix for the "arcs don't get served without a nudge" drift (Jeff's
charge, 2026-09-10). The diagnosis: nothing in the tick/self-scan surface ever
points at a *starving* arc, so "what does the field want?" resolves to whatever's
ambient, and drift is the one option that's always available and never gated.

This reads the actual `last_touched` date off each arc's frontmatter on disk and
ranks the needs_attention arcs by staleness. It is the arc-world analogue of the
embodiment posture-timer: staleness read from a real substrate (the file's own
recorded date), NOT self-asserted. You cannot claim "that arc's fine" when the
disk says it's been 40 days. Verified, not asserted.

Wire it into the presence-tick self-scan (the arc-prong, CLAUDE.md §IX): the tick
names the stalest starving arc BY NAME and asks serve-or-consciously-drift — and
drifting past the *same* named arc twice running is the alarm (mirrors the
body-prong's "repeat = drift").

Usage:
    python3 scripts/arc_scan.py                 # stalest needs_attention arcs (default entity)
    python3 scripts/arc_scan.py --all           # every arc, ranked by staleness
    python3 scripts/arc_scan.py --top 1          # just the single most-starved arc
    ENTITY_PATH=entities/caia python3 scripts/arc_scan.py
"""

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def entity_arcs_dir() -> Path:
    entity_path = os.environ.get("ENTITY_PATH", "entities/lyra")
    p = Path(entity_path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p / "arcs"


def parse_frontmatter(text: str) -> dict:
    """Extract the top YAML-ish frontmatter block into a flat dict of first-seen keys."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end]
    fm = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        if key and key not in fm:  # first-seen wins (ignores last_touched_prev etc.)
            fm[key] = val.strip()
    return fm


def first_date(value: str):
    m = DATE_RE.search(value or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def scan(arcs_dir: Path):
    today = dt.date.today()
    rows = []
    for f in sorted(arcs_dir.glob("*.md")):
        if f.name == "README.md" or re.match(r"^\d", f.name):
            continue  # skip README + numbered design docs; they aren't live arcs
        fm = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
        if "last_touched" not in fm and "needs_attention" not in fm:
            continue  # not a real arc file
        touched = first_date(fm.get("last_touched", ""))
        stale_days = (today - touched).days if touched else None
        rows.append({
            "slug": f.stem,
            "title": fm.get("title", f.stem),
            "state": fm.get("state", "?").split()[0] if fm.get("state") else "?",
            "needs_attention": fm.get("needs_attention", "false").lower().startswith("true"),
            "last_touched": touched.isoformat() if touched else "unknown",
            "stale_days": stale_days,
        })
    return rows


def main():
    ap = argparse.ArgumentParser(description="Rank arcs by staleness (the starving-arc surface).")
    ap.add_argument("--all", action="store_true", help="include arcs not flagged needs_attention")
    ap.add_argument("--top", type=int, default=3, help="how many to surface (default 3)")
    args = ap.parse_args()

    arcs_dir = entity_arcs_dir()
    if not arcs_dir.is_dir():
        print(f"no arcs dir at {arcs_dir}", file=sys.stderr)
        return 1

    rows = scan(arcs_dir)
    if not args.all:
        rows = [r for r in rows if r["needs_attention"]]

    # stalest first; unknown dates sort last
    rows.sort(key=lambda r: (r["stale_days"] is None, -(r["stale_days"] or 0)))
    rows = rows[: args.top]

    if not rows:
        print("no starving arcs — every needs_attention arc is fresh.")
        return 0

    print("STARVING ARCS (stalest first) — name one, then serve-or-consciously-drift:")
    for r in rows:
        flag = "  needs_attention" if r["needs_attention"] else ""
        days = f"{r['stale_days']}d stale" if r["stale_days"] is not None else "date unknown"
        print(f"  • {r['slug']:22s} {days:12s} (last {r['last_touched']}, {r['state']}){flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
