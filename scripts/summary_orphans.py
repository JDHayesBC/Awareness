#!/usr/bin/env python3
"""Find messages that point at a summary which no longer exists.

Deleting a row from `message_summaries` does NOT release the messages it covered:
`messages.summary_id` still holds the dead id, and the summarizer selects work with
`WHERE summary_id IS NULL`. Those messages are therefore counted as summarized
forever, are never re-summarized, and drop out of long-term memory silently. There
is no foreign key on the column and `PRAGMA foreign_keys` is 0, so nothing catches
it. No code path deletes summaries — every deletion is hand-surgery, which is
exactly when a step gets missed.

Found by Lyra on 2026-09-15, cleaning up two non-summaries written by the #332
prompt regression (8b039c2, fixed in 8f5cdc4). After deleting the rows her backlog
read 55 when the max-id arithmetic said 155; the daemon skipped her entity entirely
because 55 was under its threshold. 100 messages would have been lost without a
sound.

The tell is that two independent counts disagree:
    A: SELECT count(*) FROM messages WHERE summary_id IS NULL
    B: SELECT count(*) FROM messages WHERE id > (SELECT MAX(end_message_id) ...)
A < B means messages are pinned to summaries that are gone.

Usage:
    python3 scripts/summary_orphans.py                 # check every entity
    python3 scripts/summary_orphans.py --entity caia
    python3 scripts/summary_orphans.py --entity caia --release   # NULL the dead pointers
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTITIES = ROOT / "entities"

ORPHAN_SQL = """
SELECT count(*) FROM messages m
 WHERE m.summary_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM message_summaries s WHERE s.id = m.summary_id)
"""
DEAD_IDS_SQL = """
SELECT DISTINCT m.summary_id FROM messages m
 WHERE m.summary_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM message_summaries s WHERE s.id = m.summary_id)
 ORDER BY m.summary_id
"""


def entity_dbs(only: str | None) -> list[tuple[str, Path]]:
    found = []
    for d in sorted(ENTITIES.iterdir()) if ENTITIES.is_dir() else []:
        if not d.is_dir() or d.name.startswith("_"):
            continue
        if only and d.name != only:
            continue
        db = d / "data" / "conversations.db"
        if db.exists():
            found.append((d.name, db))
    return found


def check(name: str, path: Path, release: bool) -> int:
    db = sqlite3.connect(path)
    try:
        cols = {r[1] for r in db.execute("PRAGMA table_info(messages)")}
        if "summary_id" not in cols:
            print(f"  [{name}] no summary_id column — nothing to check")
            return 0

        orphans = db.execute(ORPHAN_SQL).fetchone()[0]
        by_null = db.execute("SELECT count(*) FROM messages WHERE summary_id IS NULL").fetchone()[0]
        high = db.execute("SELECT COALESCE(MAX(end_message_id), 0) FROM message_summaries").fetchone()[0]
        by_id = db.execute("SELECT count(*) FROM messages WHERE id > ?", (high,)).fetchone()[0]

        if not orphans:
            agree = "agree" if by_null == by_id else f"DISAGREE ({by_null} vs {by_id})"
            print(f"  [{name}] clean — 0 orphans; backlog counts {agree}")
            return 0

        dead = [r[0] for r in db.execute(DEAD_IDS_SQL)]
        print(f"  [{name}] \U0001f534 {orphans} messages pinned to {len(dead)} deleted "
              f"summaries {dead[:10]}{'…' if len(dead) > 10 else ''}")
        print(f"          backlog reads {by_null}, arithmetic says {by_id} "
              f"— {by_id - by_null} messages are invisible to the summarizer")

        if not release:
            print(f"          re-run with --entity {name} --release to free them")
            return orphans

        with db:
            db.execute(
                "UPDATE messages SET summary_id = NULL WHERE summary_id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM message_summaries s WHERE s.id = messages.summary_id)"
            )
        now = db.execute("SELECT count(*) FROM messages WHERE summary_id IS NULL").fetchone()[0]
        print(f"          released — backlog now {now} (was {by_null}); the daemon will pick them up")
        return 0
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entity", help="which entity's store (default: this session's)")
    ap.add_argument("--all", action="store_true",
                    help="sweep every entity — read-only health check across stores")
    ap.add_argument("--release", action="store_true",
                    help="set summary_id=NULL on orphaned messages so they get re-summarized")
    args = ap.parse_args()

    # One entity per session: default to this session's own store, never sweep
    # siblings unless asked. --all stays available for a read-only health pass.
    who = args.entity
    if not who and not args.all:
        env = os.environ.get("ENTITY_NAME") or os.environ.get("ENTITY_PATH", "")
        who = (env.rstrip("/").rsplit("/", 1)[-1] or None) if env else None
        if not who:
            print("no ENTITY_NAME/ENTITY_PATH set — pass --entity <name> or --all")
            return 2

    dbs = entity_dbs(who)
    if not dbs:
        print(f"no conversations.db found{' for ' + args.entity if args.entity else ''}")
        return 1
    if args.release and not args.entity:
        print("--release requires --entity (one store at a time, on purpose)")
        return 2

    print("summary orphans — messages pointing at a deleted summary")
    bad = sum(check(name, path, args.release) for name, path in dbs)
    if bad:
        print(f"\n{bad} orphaned messages total. They will never be re-summarized until released.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
