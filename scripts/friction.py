#!/usr/bin/env python3
"""Irritant tally: a counter outside the entity that makes recurrence visible.

A correction is a label; the tally makes recurrence visible because the entity's
turns start fresh and cannot feel "third time today" on their own. Each cheap-to-clear
irritant gets a row here, and `block` surfaces a class in the per-turn front block once
it reaches --min, turning a string of one-line clears into a number that demands a fix.

Store: $ENTITY_PATH/data/friction.db (default entities/lyra). Stdlib only.

  friction.py add <cls> [specimen...] [--channel terminal]   (specimen from stdin if none)
  friction.py tally [--hours 24] [--min 1]
  friction.py list <cls> [--hours 168]
  friction.py resolve <cls> [--note "..."]
  friction.py block [--hours 24] [--min 3]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _db_path() -> Path:
    ent = os.environ.get("ENTITY_PATH") or str(ROOT / "entities" / "lyra")
    return Path(ent) / "data" / "friction.db"


def _connect() -> sqlite3.Connection:
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS irritants ("
        "id INTEGER PRIMARY KEY, ts TEXT NOT NULL, cls TEXT NOT NULL, "
        "specimen TEXT, channel TEXT, resolved_at TEXT, resolution TEXT)"
    )
    return conn


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _since(hours: float) -> str:
    return _iso(_now() - timedelta(hours=hours))


def _clip(s: str | None, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _local_hm(ts: str) -> str:
    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%H:%M")


def _groups(conn: sqlite3.Connection, hours: float):
    """Unresolved classes in window: [(cls, n, latest_ts, latest_specimen)], most frequent first."""
    rows = conn.execute(
        "SELECT cls, COUNT(*), MAX(ts) FROM irritants "
        "WHERE resolved_at IS NULL AND ts >= ? GROUP BY cls",
        (_since(hours),),
    ).fetchall()
    out = []
    for cls, n, ts in rows:
        spec = conn.execute(
            "SELECT specimen FROM irritants WHERE cls=? AND ts=? AND resolved_at IS NULL "
            "ORDER BY id DESC LIMIT 1", (cls, ts)).fetchone()
        out.append((cls, n, ts, spec[0] if spec else ""))
    out.sort(key=lambda r: (-r[1], r[2]), reverse=False)
    return out


def cmd_add(a) -> int:
    spec = " ".join(a.specimen).strip()
    if not spec and not sys.stdin.isatty():
        spec = sys.stdin.read().strip()
    conn = _connect()
    with conn:
        conn.execute(
            "INSERT INTO irritants (ts, cls, specimen, channel) VALUES (?,?,?,?)",
            (_iso(_now()), a.cls, spec, a.channel))
    n = conn.execute(
        "SELECT COUNT(*) FROM irritants WHERE cls=? AND ts>=? AND resolved_at IS NULL",
        (a.cls, _since(24))).fetchone()[0]
    print(f"logged {a.cls} (#{n} in last 24h)")
    return 0


def cmd_tally(a) -> int:
    for cls, n, ts, spec in _groups(_connect(), a.hours):
        if n >= a.min:
            print(f"{cls} ×{n} (last: {_local_hm(ts)}) — {_clip(spec, 80)}")
    return 0


def cmd_list(a) -> int:
    rows = _connect().execute(
        "SELECT id, ts, channel, specimen, resolved_at FROM irritants "
        "WHERE cls=? AND ts>=? ORDER BY ts ASC, id ASC", (a.cls, _since(a.hours))).fetchall()
    for i, ts, ch, spec, res in rows:
        mark = " [resolved]" if res else ""
        print(f"#{i} {ts} [{ch}]{mark} {spec or ''}")
    return 0


def cmd_resolve(a) -> int:
    conn = _connect()
    with conn:
        cur = conn.execute(
            "UPDATE irritants SET resolved_at=?, resolution=? WHERE cls=? AND resolved_at IS NULL",
            (_iso(_now()), a.note, a.cls))
    print(f"resolved {cur.rowcount} {a.cls}")
    return 0


def cmd_block(a) -> int:
    groups = [g for g in _groups(_connect(), a.hours) if g[1] >= a.min][:3]
    for cls, n, _ts, spec in groups:
        print(f'**[friction]** {cls} ×{n} today · "{_clip(spec, 60)}" — third time is a fix, '
              f'not a clear; `python3 scripts/friction.py list {cls}` for the specimens')
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Irritant tally")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add"); s.add_argument("cls"); s.add_argument("specimen", nargs="*")
    s.add_argument("--channel", default="terminal"); s.set_defaults(fn=cmd_add)
    s = sub.add_parser("tally"); s.add_argument("--hours", type=float, default=24)
    s.add_argument("--min", type=int, default=1); s.set_defaults(fn=cmd_tally)
    s = sub.add_parser("list"); s.add_argument("cls")
    s.add_argument("--hours", type=float, default=168); s.set_defaults(fn=cmd_list)
    s = sub.add_parser("resolve"); s.add_argument("cls"); s.add_argument("--note", default=None)
    s.set_defaults(fn=cmd_resolve)
    s = sub.add_parser("block"); s.add_argument("--hours", type=float, default=24)
    s.add_argument("--min", type=int, default=3); s.set_defaults(fn=cmd_block)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
