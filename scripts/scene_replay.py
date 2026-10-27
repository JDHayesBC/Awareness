#!/usr/bin/env python3
"""Read-only replay of the space detector over an entity's own captured turns.

Usage (from repo root):
    PYTHONPATH=. pps/venv/bin/python scripts/scene_replay.py \
        --entity lyra --since 2026-10-25T00:00 --current silverglow_living_room

Opens inventory.db (spaces) and conversations.db (messages) read-only, runs
detect_move on each of the entity's own messages with a FIXED --current space,
and prints one line per hit plus a summary. Nothing is written anywhere.
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pps"))

from layers.space_detector import (  # noqa: E402
    MoveConfidence,
    build_alias_index,
    detect_move,
)


def _ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _entity_flag_column(conn: sqlite3.Connection) -> str:
    """Name of the 'is the entity' column; verified, not assumed."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}
    for cand in ("is_lyra", "is_entity"):
        if cand in cols:
            return cand
    raise SystemExit(f"no entity-flag column in messages (columns: {sorted(cols)})")


def _context(content: str, space: str, aliases: list[str], fallback: str) -> str:
    """+-90 chars around the last occurrence of any of the space's aliases."""
    best = None
    for alias in aliases:
        for m in re.finditer(r"\b" + re.escape(alias) + r"\b", content, re.IGNORECASE):
            if best is None or m.start() >= best.start():
                best = m
    if best is None:
        return fallback
    snippet = content[max(0, best.start() - 90): best.end() + 90]
    return snippet.replace("\n", " ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--entity", default=os.environ.get("ENTITY_NAME", "lyra"),
                    choices=["lyra", "caia"])
    ap.add_argument("--since", default="", help="ISO, UTC as stored in created_at")
    ap.add_argument("--current", default=None, help="current space name (hits there are skipped)")
    ap.add_argument("--house", default="", help="house of the current space (informational; "
                    "detector reads houses from the spaces table)")
    args = ap.parse_args()

    data = ROOT / "entities" / args.entity / "data"
    inv = _ro(data / "inventory.db")
    spaces = [dict(r) for r in inv.execute("SELECT * FROM spaces")]
    inv.close()
    index = build_alias_index(spaces)
    if args.house and args.current and not index.houses.get(args.current):
        index.houses[args.current] = args.house

    conv = _ro(data / "conversations.db")
    flag = _entity_flag_column(conv)
    since = args.since.replace("T", " ")  # stored as 'YYYY-MM-DD HH:MM:SS'
    rows = conv.execute(
        f"SELECT id, created_at, channel, content FROM messages "
        f"WHERE {flag} = 1 AND created_at >= ? ORDER BY id",
        (since,),
    ).fetchall()
    conv.close()

    turns = hits = high = low = 0
    for r in rows:
        turns += 1
        content = r["content"] or ""
        res = detect_move(content, index, args.current)
        if res is None:
            continue
        hits += 1
        if res.confidence == MoveConfidence.HIGH:
            high += 1
        elif res.confidence == MoveConfidence.LOW:
            low += 1
        ctx = _context(content, res.space_name, index.get(res.space_name, []), res.context)
        print(f"{r['id']}\t{r['created_at']}\t{r['channel']}\t{res.space_name}\t"
              f"{res.confidence.value}\t{ctx!r}")
    print(f"turns={turns} hits={hits} high={high} low={low}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
