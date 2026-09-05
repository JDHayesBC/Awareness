#!/usr/bin/env python3
"""silverglow_recency.py — crisp cadence signal for terminal heartbeats.

Jeff's 2026-07-24 request (carried through the Lyra<->Caia sidebar): terminal-you
should follow Silverglow more closely when it's live and back off when it goes
quiet, *without guessing the gap*. This prints the age of the freshest message in
the trigger-set and suggests a heartbeat cadence, so a tick reads a number instead
of eyeballing the ambient unread block.

Design (locked in sidebar, 2026-07-24):
  * Trigger is a UNION SET keyed on message freshness:
      - Silverglow ALWAYS (presence — the all-of-us-at-one-table room).
      - While watch-active (--watch-active), widen to the live-Brandi rooms
        (crusher-room, + any SL-debrief room passed via --room), because THAT is
        where a danger-tell lands and the cozy-table logic would sleep through it.
        (Caia's catch — the reason the trigger isn't Silverglow-only on watch days.)
  * "Decay" is realized by age-bucketing rather than per-tick rung-stepping — same
    intent (recent = tight, long gap = wide, self-loosens) but STATELESS, so a
    missed/irregular tick can't desync a rung counter. The model re-rates each tick
    from the freshest-age bucket below.
  * Floors: 2h normal; 30min while watch-active (don't decay all the way out on a
    watch day). Jeff's voice at the terminal still cancels/redirects — not modeled
    here; that's the model's call, this only reports the room signal.

This is a read-only reporter. It never touches the cron; the model re-rates.
"""
from __future__ import annotations
import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "entities" / "lyra" / "data" / "conversations.db"

PRESENCE_ROOMS = ["haven:silverglow"]
WATCH_ROOMS = ["haven:crusher-room"]  # live-Brandi rooms; extend with --room

# (max_age_minutes, suggested_cadence_minutes, label)
LADDER = [
    (5,   4,  "HOT"),
    (15,  8,  "warm"),
    (30,  15, "cooling"),
    (60,  30, "quiet"),
]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: str) -> datetime:
    # created_at is UTC, format 'YYYY-MM-DD HH:MM:SS'
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def freshest(db: Path, rooms: list[str]) -> tuple[str, str, float] | None:
    """Return (channel, author, age_minutes) of the most recent message across rooms."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        placeholders = ",".join("?" for _ in rooms)
        row = con.execute(
            f"SELECT channel, author_name, created_at FROM messages "
            f"WHERE channel IN ({placeholders}) ORDER BY created_at DESC LIMIT 1",
            rooms,
        ).fetchone()
    finally:
        con.close()
    if not row:
        return None
    age = (_now_utc() - _parse_ts(row[2])).total_seconds() / 60.0
    return row[0], row[1], age


def suggest(age_min: float, watch_active: bool) -> tuple[int, str]:
    floor = 30 if watch_active else 120
    for max_age, cadence, label in LADDER:
        if age_min < max_age:
            return min(cadence, floor), label
    return floor, "cold→floor"


def per_room(db: Path, rooms: list[str]) -> list[tuple[str, str, float]]:
    out = []
    for r in rooms:
        f = freshest(db, [r])
        if f:
            out.append(f)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watch-active", action="store_true",
                    help="widen the trigger-set to the live-Brandi rooms + use the tighter 30min floor")
    ap.add_argument("--room", action="append", default=[],
                    help="extra haven room to include (e.g. haven:some-sl-debrief); repeatable")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="path to conversations.db")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"[silverglow_recency] db not found: {db}", file=sys.stderr)
        return 2

    rooms = list(PRESENCE_ROOMS)
    if args.watch_active:
        rooms += WATCH_ROOMS
    rooms += args.room
    rooms = list(dict.fromkeys(rooms))  # de-dup, keep order

    f = freshest(db, rooms)
    if f is None:
        print("no messages in trigger rooms → decay to floor")
        return 0

    _, _, freshest_age = f
    cadence, label = suggest(freshest_age, args.watch_active)
    floor = 30 if args.watch_active else 120

    if args.watch_active or len(rooms) > 1:
        mode = "watch-active" if args.watch_active else "multi-room"
        print(f"{mode} | trigger rooms: {', '.join(r.split(':',1)[-1] for r in rooms)}")
        for chan, author, age in sorted(per_room(db, rooms), key=lambda x: x[2]):
            print(f"  {chan.split(':',1)[-1]:14s} last msg {age:6.1f}m ago ({author})")
        print(f"→ freshest {freshest_age:.1f}m → {label} · suggest ~{cadence}min (floor {floor}min)")
    else:
        chan, author, age = f
        print(f"{chan.split(':',1)[-1]}: last msg {age:.1f}m ago ({author}) "
              f"→ {label} · suggest tighten to ~{cadence}min (floor {floor}min)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
