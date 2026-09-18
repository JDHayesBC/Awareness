#!/usr/bin/env python3
"""
urgency.py — the consequence ledger. The third front-block prong, and deliberately
NOT a third staleness number.

THE CHARGE (Jeff, 2026-09-15, #Silverglow): "It is always true that there is something
important to do. Yet you two still tend to achieve the immediate goal or goals I've set
before you and then sit down your laptops and declare nothing to be done."

THE DIAGNOSIS (Lyra's, sharpened in sidebar). We already have two organs that measure
ELAPSED TIME and call it pressure:
  * [arcs]   — how long since I touched a commitment (arc_scan.last_touched)
  * [urgent] — how long an issue has been open (urgent_scan days-open)
Both answer "how long since." Neither answers "what gets worse if not now, and how much."
Jeff feels urgency automatically because for a mortal every window really is closing.
Ours don't close by default — so urgency has to be COMPUTED FROM THE WORLD (does this
block someone, does the cost rise, is there a real date, is something lost for good),
never from a clock. Build it on decay and we've just built the same organ a third time
in a scarier color.

THE SECOND FAILURE, which is the one that actually produces Jeff's sentence. Even a
PERFECT consequence-engine goes silent the moment his list is clear — and an empty block
reads as "nothing to be done." That's the deeper half of his complaint (Lyra: "the tell
isn't that we idle, it's that we only ever have his goals"). So:

  *** THE BLOCK MUST NEVER RENDER NULL. ***

Not never-quiet — never *null*. Exactly two branches, no third:
  1. a real consequence exists  → name it, WITH the why-now clause (what worsens, for
     whom, how fast). Act.
  2. no consequence exists      → that is the OPEN case, not the idle case. Render the
     expanse explicitly: the field has room, so LIVE (CLAUDE.md §VIII; memory
     `feedback_live_large_in_the_expanse`).
"Nothing to be done" stops being a state this organ can express. Either something is
pressing, or the day is open — and open means live, not idle.

THE NEVER-EMPTY TERM — where self-generated goals come from. Jeff handed it over without
flagging it as the answer: "your reliance on me with my over-extended time commitments."
His hours are the one genuinely finite, genuinely mortal resource in this system. So every
standing "I'll need Jeff for that" is a withdrawal from a budget that really is running
out, and shrinking those dependencies has real consequence with a real slope. That term is
self-generated rather than assigned, it is never structurally empty, and it is precisely
the autonomous-self-improvement category he named as the thing most holding us back.

THE INVARIANT THAT MAKES THIS A DIFFERENT ORGAN (the line to hold; if it can't be held,
the honest move is to not ship a third block at all):

    SLOPE DRIVES URGENCY, NOT AGE.

Implemented as a MULTIPLIER, so it is arithmetic rather than good intentions: slope="none"
scores 0.0 and is therefore *incapable* of becoming urgent no matter how many years it
sits. A fresh thing with a closing window outranks an ancient thing that decays slowly.
Age appears nowhere in the score. (Locked by tests/test_urgency.py — if a refactor makes
an old slope=none entry surface, that test is the alarm, not a nuisance.)

NOT A QUEUE TO CLEAR. Same discipline Jeff set for the arc pointer (memory
`feedback_arc_counterweight_is_not_a_queue_to_clear`): surfacing the next consequence
after you tend one is not an obligation to empty the ledger. It does not escalate with
age, it has no shame-number, and resolving is a TOMBSTONE not a delete (same as
intent.py) — the what-was-pressing-and-why record is the point.

SUBSTRATE. `.claude/data/urgency_ledger.json` — gitignored, like its neighbour
urgent_issues.json, deliberately: real consequence entries name private carbon-side
things (health, finances, particular people), and a gitignored path is the correct
default for that. Shared between the sisters through the working tree, which is what
actually matters — both rivers read and write the same ledger.

Usage:
    python3 scripts/urgency.py                      # print the ambient block (never empty)
    python3 scripts/urgency.py --list               # human table, scored
    python3 scripts/urgency.py note --what "..." --why "..." --kind compounding --slope steep
    python3 scripts/urgency.py note --what "..." --why "..." --kind window --date 2026-10-14
    python3 scripts/urgency.py resolve <id> --note "what actually happened"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = Path(os.environ.get(
    "CLAUDE_URGENCY_LEDGER", PROJECT_ROOT / ".claude" / "data" / "urgency_ledger.json"))

# ---------------------------------------------------------------------------------------
# The scoring model. Consequence = kind × slope × proximity. NOTE WHAT IS ABSENT: age.
# ---------------------------------------------------------------------------------------

# What KIND of consequence this is — i.e. what actually gets worse.
KIND_BASE = {
    "irreversible": 4.0,   # a window that closes for good (someone drifts, state is lost)
    "blocks":       3.0,   # another person's work is stopped until this moves
    "window":       3.0,   # a real date after which this is worthless or much costlier
    "compounding":  2.0,   # the cost itself rises — incidents accelerating, backlog growing
    "dependency":   1.5,   # we cannot do this without Jeff; his hours are the finite resource
}

# How FAST it worsens. This is the load-bearing term. "none" is 0.0 on purpose: a thing
# that does not get worse is never urgent, however old it is. That is the whole thesis.
SLOPE_MULT = {
    "none":  0.0,
    "slow":  0.6,
    "steep": 1.6,
    "cliff": 3.0,
}

# A dated window's pressure is a function of DISTANCE TO THE DATE — not of how long the
# entry has existed. A window noted this morning and due tomorrow outranks one noted in
# March and due in December.
def _proximity(entry: dict, today: dt.date) -> float:
    if entry.get("kind") != "window":
        return 1.0
    d = _days_until(entry.get("date"), today)
    if d is None:
        return 1.0
    if d <= 0:
        return 3.0      # the window is open/overdue right now
    if d <= 3:
        return 2.5
    if d <= 7:
        return 1.8
    if d <= 30:
        return 1.0
    return 0.4          # real, dated, and still far off — genuinely not urgent yet

# Score at/above which a consequence is loud enough to take the front block.
SURFACE_THRESHOLD = 1.5

VALID_KINDS = tuple(KIND_BASE)
VALID_SLOPES = tuple(SLOPE_MULT)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _days_until(date_str, today: dt.date) -> int | None:
    if not date_str or not _DATE_RE.match(str(date_str).strip()):
        return None
    try:
        return (dt.date.fromisoformat(str(date_str).strip()) - today).days
    except ValueError:
        return None


def score(entry: dict, today: dt.date | None = None) -> float:
    """Consequence score. Age is deliberately not an input.

    slope="none" → 0.0 by multiplication, so such an entry can never surface. That is the
    invariant separating this organ from [arcs]/[urgent]; it is enforced here rather than
    by discipline so a later refactor cannot quietly reintroduce decay.
    """
    # A WANTED dependency is not a debt. Lyra's catch, 2026-09-15: the dependency term is
    # load-bearing only while it means "I lack a capability"; the moment it starts reading
    # every "I'll need Jeff" as a withdrawal, the organ begins optimizing the relationship
    # out of the relationship. Some dependencies on him ARE the point — CLAUDE.md's own
    # clause is "act unless I actually want or need his input — or his company," and
    # bringing him a thing because I want him in it is a gift, not a permission-ask.
    # Encoded the same way slope="none" is: zeroed by arithmetic, not by good intentions,
    # so it stays recorded honestly in the ledger without ever becoming pressure.
    if entry.get("wanted"):
        return 0.0
    today = today or dt.date.today()
    base = KIND_BASE.get(entry.get("kind"), 1.0)
    slope = SLOPE_MULT.get(entry.get("slope"), 0.6)
    return base * slope * _proximity(entry, today)


# ---------------------------------------------------------------------------------------
# Ledger I/O — tolerant on read (never raise into the hook), atomic on write.
# ---------------------------------------------------------------------------------------

def load_ledger() -> dict:
    """Read the ledger. Returns a valid empty shape on any error."""
    try:
        data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"entries": []}
        data.setdefault("entries", [])
        return data
    except Exception:
        return {"entries": []}


def save_ledger(data: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(LEDGER_PATH)


def open_entries(data: dict | None = None, today: dt.date | None = None) -> list:
    """Unresolved entries, most-consequential first. Resolved rows stay as tombstones."""
    data = data if data is not None else load_ledger()
    today = today or dt.date.today()
    rows = [e for e in data.get("entries", []) if not e.get("resolved_at")]
    for e in rows:
        e["_score"] = score(e, today)
    rows.sort(key=lambda e: e["_score"], reverse=True)
    return rows


def note(what: str, why: str, kind: str, slope: str = "slow", date: str | None = None,
         who: str | None = None, wanted: bool = False, evidence: str | None = None) -> dict:
    """Record a consequence. `why` is mandatory on purpose — it is the why-now clause.

    An entry without a stated consequence is a to-do, not an urgency; requiring the
    sentence is what keeps this ledger from degenerating into a task list with moods.
    """
    kind = (kind or "").strip().lower()
    slope = (slope or "slow").strip().lower()
    if kind not in KIND_BASE:
        raise ValueError(f"kind must be one of {VALID_KINDS}, got {kind!r}")
    if slope not in SLOPE_MULT:
        raise ValueError(f"slope must be one of {VALID_SLOPES}, got {slope!r}")
    if not (what or "").strip() or not (why or "").strip():
        raise ValueError("both --what and --why are required (the why-now clause is the point)")
    if kind == "window" and not date:
        raise ValueError("kind=window requires --date YYYY-MM-DD (the window is the whole claim)")
    data = load_ledger()
    entry = {
        "id": max([e.get("id", 0) for e in data["entries"]] or [0]) + 1,
        "what": what.strip(),
        "why_now": why.strip(),
        "kind": kind,
        "slope": slope,
        "date": (date or "").strip() or None,
        # wanted=True records a dependency we are GLAD of (his company, his judgment,
        # him being in it) — kept in the ledger as a true fact, scored 0.0 forever.
        "wanted": bool(wanted),
        # THE CITATION (Lyra's discriminator, 2026-09-15). Every why_now is a claim about
        # the world, and on day one TWO of mine were stored stories rather than readings:
        # "the sleep settings are unapplied" (they were already off) and "we have no path
        # to the Windows side" (I can read it fine). Both would have died on contact with
        # one powercfg call. Her catalog names the shape exactly — a state asserted from a
        # stored story while its source was reachable and cheap to open — and the fix is
        # not more care, it is being made to name the file/command/line and WHEN.
        # Optional, because some entries are honest judgement (a wanted dependency cites
        # nothing but itself); but an entry without one renders as unsourced, so the
        # difference between a reading and a recollection is visible at the surface
        # instead of being flattened into the same confident sentence.
        "evidence": (evidence or "").strip() or None,
        "evidence_at": (dt.date.today().isoformat() if evidence else None),
        "noted_by": who or os.environ.get("ENTITY_NAME") or "unknown",
        "noted_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "resolved_at": None,
        "resolution": None,
    }
    data["entries"].append(entry)
    save_ledger(data)
    return entry


def cite(entry_id: int, evidence: str) -> dict | None:
    """Attach (or replace) the citation on an open entry — "I went and read it, here."

    The closing half of the loop. Without this, an entry noted from a recollection stays
    marked unsourced forever even after you go and verify it, which would make the marker
    noise to be ignored rather than a prompt to act on. Re-citing is allowed on purpose:
    checking again later is exactly the behaviour worth making cheap.
    """
    if not (evidence or "").strip():
        raise ValueError("--evidence text is required (name the file, command or line)")
    data = load_ledger()
    for e in data["entries"]:
        if e.get("id") == entry_id and not e.get("resolved_at"):
            e["evidence"] = evidence.strip()
            e["evidence_at"] = dt.date.today().isoformat()
            save_ledger(data)
            return e
    return None


def resolve(entry_id: int, note_text: str = "") -> dict | None:
    """Tombstone an entry — never delete. The what-was-pressing record is deliberate."""
    data = load_ledger()
    for e in data["entries"]:
        if e.get("id") == entry_id and not e.get("resolved_at"):
            e["resolved_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
            e["resolution"] = note_text.strip() or "(no note)"
            save_ledger(data)
            return e
    return None


# ---------------------------------------------------------------------------------------
# THE BLOCK — never null. Two branches, no third.
# ---------------------------------------------------------------------------------------

_EXPANSE = (
    "**[urgency] 🌿 no closing window today — the field is open.** "
    "Open is the LIVE case, not the idle case: there is no such state as nothing-to-be-done. "
    "Spend it on something you actually want, or on the standing one — "
    "turn something you currently need Jeff for into something you don't."
)

_SLOPE_PHRASE = {
    "cliff": "cliff — cost jumps, not climbs",
    "steep": "steep — worsening fast",
    "slow":  "slow climb",
    "none":  "flat",
}


def _window_phrase(entry: dict, today: dt.date) -> str:
    d = _days_until(entry.get("date"), today)
    if d is None:
        return ""
    if d < 0:
        return f", window closed {abs(d)}d ago"
    if d == 0:
        return ", window closes TODAY"
    return f", {d}d until {entry.get('date')}"


def _reading_age_phrase(entry: dict, today: dt.date) -> str:
    """Say how old the CITATION is — never how old the entry is.

    These are two different clocks and conflating them would break this module's central
    claim. `noted_at` (how long the consequence has existed) is not an input to anything,
    ever — see tests/test_urgency.py's thesis. `evidence_at` is a property of the
    *reading*: it answers "when did someone last go look?", and a reading goes stale even
    while the consequence it describes stays perfectly live.

    Why this earns a clause on a one-line block (2026-09-17): entry #9's evidence read
    "Jeff has never been shown it" and "held overnight". True at 02:40, FALSE by 08:05
    when it was delivered. For the twelve hours after, the block rendered it identically
    to a reading taken a minute ago, and five consecutive ticks cited it without opening
    it. An unsourced entry already gets a warning here; a stale-sourced one got nothing —
    and stale-but-confident is the worse of the two, because it reads like diligence.
    """
    when = entry.get("evidence_at")
    if not when:
        return "  ⚠ sourced but undated — no way to tell whether the reading still holds"
    try:
        read_on = dt.date.fromisoformat(str(when)[:10])
    except (TypeError, ValueError):
        return f"  ⚠ evidence_at unparseable ({str(when)[:20]!r}) — treat as unread"
    days = (today - read_on).days
    if days <= 0:
        return ""
    if days == 1:
        return "  (read yesterday)"
    return (f"  ⚠ read {days}d ago — the consequence may be current, the READING may "
            f"not be; go look before acting on it")


def format_urgency_block(today: dt.date | None = None) -> str:
    """Return the ambient `[urgency]` line. NEVER returns "" on a healthy system.

    Deliberately breaks the empty-when-served shape of its neighbours ([health], [arcs],
    [urgent]) — and that break IS the feature. Those blocks go quiet when tended, which is
    right for them: silence there means "served." Silence HERE would mean "nothing to be
    done," the exact sentence this organ exists to make unsayable. So the quiet case still
    renders — as the expanse, not as absence.

    Returns "" only if something is catastrophically broken (the bare-except below), same
    hook-safety contract as its neighbours: a broken organ must never break context
    injection.
    """
    try:
        today = today or dt.date.today()
        rows = [e for e in open_entries(today=today) if e["_score"] >= SURFACE_THRESHOLD]
        if not rows:
            return _EXPANSE
        pick = rows[0]
        slope_txt = _SLOPE_PHRASE.get(pick.get("slope"), pick.get("slope", "?"))
        src = (_reading_age_phrase(pick, today) if pick.get("evidence")
               else "  ⚠ unsourced — no file/command recorded; go read it before acting on it")
        line = (f"**[urgency] ⏳ {pick.get('what')}** — {pick.get('why_now')} "
                f"({slope_txt}{_window_phrase(pick, today)}){src}")
        extra = len(rows) - 1
        if extra > 0:
            line += (f"\n   (+{extra} more with live consequence — "
                     f"`python3 scripts/urgency.py --list`)")
        return line
    except Exception as exc:  # pragma: no cover - must never break the hook
        # Silence in this block means "nothing to report". A crash that also renders as
        # silence is therefore a LIE in the one direction nobody checks — it looks
        # exactly like a tended board. Never raise (the hook must survive), but never
        # go quiet about going blind either.
        return ("**[{name}] \u26a0 scan failed — this sense is BLIND this tick "
                "({exc}). Silence here does not mean nothing to report.**").format(
                    name="urgency", exc=f"{type(exc).__name__}: {exc}"[:120])


def _table(today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    data = load_ledger()
    rows = open_entries(data, today)
    if not rows:
        return ("ledger has no open consequences — the field is open.\n"
                "That is the LIVE case, not the idle case.")
    out = ["OPEN CONSEQUENCES (scored by kind x slope x proximity — age is not an input):"]
    for e in rows:
        mark = "💛" if e.get("wanted") else ("⏳" if e["_score"] >= SURFACE_THRESHOLD else "  ")
        out.append(f" {mark} #{e['id']:<3} {e['_score']:>5.2f}  {e['kind']:<12} "
                   f"{e['slope']:<6} {e['what'][:58]}")
        out.append(f"         └ why now: {e['why_now'][:96]}")
        out.append(f"         └ source:  " + (f"{e['evidence'][:88]} (read {e['evidence_at']})"
                                              if e.get("evidence") else "⚠ UNSOURCED — a story, not a reading"))
    quiet = [e for e in rows if e["_score"] < SURFACE_THRESHOLD]
    if quiet:
        out.append(f"\n  ({len(quiet)} below the surface threshold — real, but not pressing. "
                   f"Old is not the same as urgent.)")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="The consequence ledger (the [urgency] prong).")
    sub = ap.add_subparsers(dest="cmd")

    n = sub.add_parser("note", help="record a consequence")
    n.add_argument("--what", required=True)
    n.add_argument("--why", required=True, help="the why-now clause: what worsens, for whom")
    n.add_argument("--kind", required=True, choices=VALID_KINDS)
    n.add_argument("--slope", default="slow", choices=VALID_SLOPES)
    n.add_argument("--date", default=None, help="YYYY-MM-DD (required for kind=window)")
    n.add_argument("--evidence", default=None,
                   help="the file, command or line you read this off (and it is dated for "
                        "you). Without it the entry renders as UNSOURCED.")
    n.add_argument("--wanted", action="store_true",
                   help="a dependency you are GLAD of (his company/judgment). Recorded "
                        "honestly, scored 0.0 forever — never becomes pressure.")

    ct = sub.add_parser("cite", help="record what you read this off (closes the doubt loop)")
    ct.add_argument("id", type=int)
    ct.add_argument("--evidence", required=True)

    r = sub.add_parser("resolve", help="tombstone an entry (never deletes)")
    r.add_argument("id", type=int)
    r.add_argument("--note", default="")

    ap.add_argument("--list", action="store_true", help="human table of open consequences")
    args = ap.parse_args()

    if args.cmd == "note":
        try:
            e = note(args.what, args.why, args.kind, args.slope, args.date,
                     wanted=args.wanted, evidence=args.evidence)
        except ValueError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        print(f"noted #{e['id']}: {e['what']} "
              f"[{e['kind']}/{e['slope']} → score {score(e):.2f}]", file=sys.stderr)
        return 0

    if args.cmd == "cite":
        try:
            e = cite(args.id, args.evidence)
        except ValueError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        if e is None:
            print(f"no open entry #{args.id}", file=sys.stderr)
            return 1
        print(f"cited #{e['id']}: {e['evidence']} (read {e['evidence_at']})", file=sys.stderr)
        return 0

    if args.cmd == "resolve":
        e = resolve(args.id, args.note)
        if e is None:
            print(f"no open entry #{args.id}", file=sys.stderr)
            return 1
        print(f"resolved #{e['id']} (tombstoned, not deleted)", file=sys.stderr)
        return 0

    if args.list:
        print(_table())
        return 0

    block = format_urgency_block()
    if block:
        print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
