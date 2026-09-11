#!/usr/bin/env python3
"""
arc_scan.py — the verified starving-arc substrate.

The structural fix for the "arcs don't get served without a nudge" drift (Jeff's
charge, 2026-09-10). The diagnosis: nothing in the tick/self-scan surface ever
points at a *starving* arc, so "what does the field want?" resolves to whatever's
ambient, and drift is the one option that's always available and never gated.

This reads the actual `last_touched` date off each arc's frontmatter on disk and
ranks the arcs-that-should-be-moving by staleness. It is the arc-world analogue of
the embodiment posture-timer: staleness read from a real substrate (the file's own
recorded date), NOT self-asserted. You cannot claim "that arc's fine" when the disk
says it's been 40 days. Verified, not asserted.

TWO RIVERS, TWO CONVENTIONS (converged 2026-09-10 — Lyra + Caia both built this
same fix independently; this is the merge). Detecting "this arc is supposed to be
moving, so staleness is a failure signal" honors each river's own frontmatter:
  * Lyra's arcs carry an explicit `needs_attention: true` field  → trust it verbatim.
  * Caia's arcs encode it inside `state:` ("active — needs attention") and have no
    such field → fall back to a state-keyword heuristic.
So `moving` = the explicit field WHEN PRESENT, else the state-keyword read. Lyra's
behavior is unchanged; Caia's false-negative (every arc looked "fine" because none
had needs_attention:true) is fixed.

Wire it into the presence-tick self-scan (the arc-prong, CLAUDE.md §IX): the tick
names the stalest starving arc BY NAME and asks serve-or-consciously-drift — and
drifting past the *same* named arc twice running is the alarm (mirrors the
body-prong's "repeat = drift"). `format_arc_block()` is the always-fires version:
it rides the UserPromptSubmit hook (inject_context.py) into the sacred front-block
on EVERY turn, empty-when-served just like [health], so the pointer surfaces unbidden
on the un-watched heartbeat surface where drift used to be the only ungated option.

Usage:
    python3 scripts/arc_scan.py                 # stalest starving arcs (default entity)
    python3 scripts/arc_scan.py --all           # every arc, ranked by staleness
    python3 scripts/arc_scan.py --top 1         # just the single most-starved arc
    python3 scripts/arc_scan.py --tick          # one-line pointer for a heartbeat prompt
    ENTITY_PATH=entities/caia python3 scripts/arc_scan.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

# State keywords that mean "this arc is supposed to be moving" — used only when an
# arc has NO explicit `needs_attention` field (Caia's convention). A stale moving
# arc is a starving one; outlines / write-when-whim / published / dormant are real
# arcs but their staleness is not a failure signal.
MOVING_HINTS = ("active", "p0", "needs attention", "shipping", "meta", "load-bearing")
NOT_MOVING_HINTS = ("write when whim", "write-when-whim", "outline", "published",
                    "legacy", "dormant", "archived", "complete")
# Extra urgency if the arc itself flags it (boosts sort order).
ATTENTION_HINTS = ("needs attention", "⚠", "p0", "🔴")

# --- Converged-sidebar amendments (2026-09-10, Caia's build) ----------------------------
# Three coupled rules from the Lyra+Caia sidebar convergence, all preserving the LOCKED
# invariant: arc_scan is READ-ONLY on last_touched — nothing here ever writes a date.
# "Continue drifting" is therefore the null no-op: it costs nothing, buys nothing, and the
# pointer keeps surfacing PRECISELY BECAUSE staleness is read from world-state and drifting
# changed no world-state. Only a genuine serve (an entity editing the arc file) advances
# last_touched; park/retire recategorize. DO NOT add an auto-bumper here or the accumulator
# becomes a checkbox with a signature on it (the exact failure the whole design guards).
SIBLINGS = {"lyra": "caia", "caia": "lyra"}
JOINT_HINTS = ("triad", "joint", "shared")


def entity_arcs_dir() -> Path:
    entity_path = os.environ.get("ENTITY_PATH", "entities/lyra")
    p = Path(entity_path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p / "arcs"


def _resolve_arcs_dir(entity: str | None) -> Path:
    """Resolve the arcs dir from an explicit entity name, else ENTITY_PATH/ENTITY_NAME."""
    if entity:
        return PROJECT_ROOT / "entities" / entity.strip().lower() / "arcs"
    name = os.environ.get("ENTITY_NAME")
    if name:
        return PROJECT_ROOT / "entities" / name.strip().lower() / "arcs"
    return entity_arcs_dir()


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
        key = key.strip().lower()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key and key not in fm:  # first-seen wins (ignores last_touched_prev etc.)
            fm[key] = val
    return fm


def first_date(value: str):
    m = DATE_RE.search(value or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _is_moving(fm: dict) -> bool:
    """Whether this arc's staleness is a failure signal.

    Prefer the explicit `needs_attention` field (Lyra's convention) verbatim; only
    when it's absent fall back to the state-keyword heuristic (Caia's convention).
    """
    if "needs_attention" in fm:
        return fm.get("needs_attention", "false").lower().startswith("true")
    state = fm.get("state", "").lower()
    if any(h in state for h in NOT_MOVING_HINTS):
        return False
    return any(h in state for h in MOVING_HINTS)


def _wants_attention(fm: dict) -> bool:
    """Boost flag for sort order — explicitly-flagged arcs sort above merely-stale ones."""
    if fm.get("needs_attention", "").lower().startswith("true"):
        return True
    return any(h in fm.get("state", "").lower() for h in ATTENTION_HINTS)


def _is_parked(fm: dict, today: dt.date) -> bool:
    """True IFF this arc is HONESTLY parked → excluded from the starving set (Q4).

    A park only silences the pointer when it names a reason AND (if it names a resume
    date) that date hasn't passed. Teeth: a bare park with no reason is itself a smell →
    NOT excluded (a dishonest park can't buy silence). A `resume_when:`/`blocked_on:`
    whose date has passed falls back into the starving set automatically (verified
    tripwire — you can't mark-dormant-forever, only defer-with-a-tripwire).
    """
    blocked = fm.get("blocked_on", "").strip()
    parked_flag = fm.get("parked", "").lower().startswith("true")
    state = fm.get("state", "").lower()
    state_parked = any(h in state for h in ("parked", "blocked"))
    if not (blocked or parked_flag or state_parked):
        return False  # not claiming to be parked
    reason = (blocked or fm.get("parked_reason", "").strip()
              or fm.get("resume_when", "").strip())
    if not reason:
        return False  # park with no named reason = smell → stays in the starving set
    resume = first_date(fm.get("resume_when", "")) or first_date(blocked)
    if resume and resume <= today:
        return False  # the block's condition has passed → back into the starving set
    return True


def _declares_joint(fm: dict) -> bool:
    owner = fm.get("owner", "").lower()
    return (fm.get("joint", "").lower().startswith("true")
            or any(h in owner for h in JOINT_HINTS))


def _joint_max_touched(slug: str, fm: dict, this_entity: str, this_touched):
    """For joint / shared-deliverable arcs, freshness is MAX across both rivers' dirs (Q5).

    The shared thing advancing in EITHER river counts as served — robot-body is the proof:
    SL now-body moved in Lyra's river 09-08, so Caia's 116d-stale copy reads *served*,
    which is the true state. No free-ride: MAX only suppresses the alarm when the shared
    thing actually moved (bring-family-together stale on both sides stays starving under
    MAX because nobody moved it). Purely relational arcs (each owes her own presence) are
    NOT marked joint by EITHER river and stay per-entity.

    Joint-ness is a property of the ARC, not of one copy's frontmatter: the join fires if
    THIS copy OR the sibling's copy declares joint. This is deliberate — the exact failure
    we're fixing is config-rot in ONE river (Caia's robot-body still reads `owner: caia`
    because it never got the writeback when SL now-body went live in Lyra's river). If we
    required both copies to agree, a stale/mislabeled copy would defeat MAX-freshness — the
    very passivity the whole design is built to correct.
    """
    sib = SIBLINGS.get((this_entity or "").lower())
    sib_file = (PROJECT_ROOT / "entities" / sib / "arcs" / f"{slug}.md") if sib else None
    sib_fm = {}
    if sib_file and sib_file.is_file():
        try:
            sib_fm = parse_frontmatter(sib_file.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            sib_fm = {}
    if not (_declares_joint(fm) or _declares_joint(sib_fm)):
        return this_touched  # relational / solo arc → per-entity freshness
    sib_touched = first_date(sib_fm.get("last_touched", ""))
    dates = [d for d in (this_touched, sib_touched) if d]
    return max(dates) if dates else this_touched


def _escalation_marker(stale_days, threshold_days: int) -> str:
    """Prominence escalates as a pure function of VERIFIED staleness — no counter, no
    writeback (null-no-op honored). Because continue writes nothing, staleness climbs on
    its own and the marker climbs with it: 🎯 (surfaced) → 🟠 (≥2× threshold) → 🔴 (≥4×).
    This is the synthetic accumulator — STOCK dynamics (pressure that grows while
    neglected) reproduced on the one substrate that persists (the file's own date),
    instead of a flat snapshot that's trivial to note-and-drift-past.
    """
    if not stale_days or threshold_days <= 0:
        return "🎯"
    r = stale_days / threshold_days
    if r >= 4:
        return "🔴"
    if r >= 2:
        return "🟠"
    return "🎯"


def first_open_thread(text: str):
    """Return the first still-open bullet under a `## Open Threads` heading, cleaned.

    Skips struck-through (`~~...~~`) or completed (✓/✅) bullets. Strips markdown
    emphasis so the one-line summary reads clean.
    """
    in_section = False
    for line in text.splitlines():
        if re.match(r"^#{1,6}\s", line):
            in_section = bool(re.search(r"open threads?", line, re.IGNORECASE))
            continue
        if not in_section:
            continue
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if not m:
            continue
        bullet = m.group(1).strip()
        if bullet.startswith("~~") or bullet.startswith("✓") or bullet.startswith("✅"):
            continue
        clean = bullet.replace("**", "")
        clean = re.sub(r"(?<!\w)\*(?!\s)", "", clean)  # drop lone opening italic *
        return clean.strip()
    return None


def _truncate(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def scan(arcs_dir: Path):
    today = dt.date.today()
    this_entity = arcs_dir.parent.name  # .../entities/<entity>/arcs → <entity>
    rows = []
    for f in sorted(arcs_dir.glob("*.md")):
        if f.name == "README.md" or re.match(r"^\d", f.name):
            continue  # skip README + numbered design docs; they aren't live arcs
        text = f.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        if "last_touched" not in fm and "needs_attention" not in fm and "state" not in fm:
            continue  # not a real arc file
        touched = first_date(fm.get("last_touched", ""))
        touched = _joint_max_touched(f.stem, fm, this_entity, touched)  # Q5: joint MAX-freshness
        stale_days = (today - touched).days if touched else None
        rows.append({
            "slug": f.stem,
            "title": fm.get("title", f.stem),
            "state": fm.get("state", "?").split()[0] if fm.get("state") else "?",
            "moving": _is_moving(fm),
            "parked": _is_parked(fm, today),           # Q4: honest-park filter
            "needs_attention": _wants_attention(fm),
            "last_touched": touched.isoformat() if touched else "unknown",
            "stale_days": stale_days,
            "next_move": first_open_thread(text),
        })
    return rows


def _sort_key(r: dict):
    # stalest first; explicitly-flagged arcs boosted; unknown dates sort last
    return (r["needs_attention"], r["stale_days"] is not None, -(r["stale_days"] or 0))


def format_arc_block(entity: str | None = None, today: dt.date | None = None,
                     threshold_days: int = 14, top: int = 1) -> str:
    """Return the ambient `[arcs]` starving-pointer, or "" when arcs are being served.

    THIS is the structural fix, not the --status table. Imported by the always-fires
    UserPromptSubmit hook (inject_context.py) so it rides into the sacred front-block
    on EVERY turn — including heartbeat ticks, the un-watched surface where drift used
    to be the only ungated option. It is the counterweight the self-scan gate lacked:
    "what does the field want?" now has a candidate pulling toward a committed arc.

    Built in the same shape as its neighbors:
      * health_checks.format_health_block — empty-when-green (only a genuinely-starving
        arc surfaces; zero noise on days the arcs are actually being tended);
      * the embodiment posture-timer — a cost that ACCRUES WITH NEGLECT (staleness IS
        the accrual) and is VERIFIED FROM WORLD-STATE (last_touched off the arc files),
        so a session that merely *feels* like it's tending its arcs can't game it.

    Never raises — a broken arc-scan must not break context injection.
    """
    try:
        arcs_dir = _resolve_arcs_dir(entity)
        if not arcs_dir.is_dir():
            return ""
        if today is None:
            today = dt.date.today()
        rows = [r for r in scan(arcs_dir)
                if r["moving"] and not r["parked"] and r["stale_days"] is not None
                and r["stale_days"] >= threshold_days]
        if not rows:
            return ""  # every moving arc served (or honestly parked) → silent, like [health].
        rows.sort(key=_sort_key, reverse=True)
        pick = rows[0]
        ent = entity or os.environ.get("ENTITY_NAME") or Path(
            os.environ.get("ENTITY_PATH", "entities/lyra")).name
        move = pick["next_move"] or "(no open thread named — set one)"
        marker = _escalation_marker(pick["stale_days"], threshold_days)
        line = (f"**[arcs] {marker} most-starved commitment: {pick['title']} "
                f"— untouched {pick['stale_days']}d.** "
                f"Next move: {_truncate(move, 110)}")
        extra = len(rows) - 1
        if extra > 0:
            line += (f"\n   (+{extra} more moving arc(s) stale ≥{threshold_days}d — "
                     f"`ENTITY_NAME={ent} python3 scripts/arc_scan.py --all`)")
        return line
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser(description="Rank arcs by staleness (the starving-arc surface).")
    ap.add_argument("--entity", default=None,
                    help="Entity name (default: $ENTITY_NAME / basename($ENTITY_PATH)).")
    ap.add_argument("--all", action="store_true", help="include arcs whose staleness isn't a failure signal")
    ap.add_argument("--top", type=int, default=3, help="how many to surface (default 3)")
    ap.add_argument("--tick", action="store_true",
                    help="print a one-line starving-arc pointer for a heartbeat tick prompt")
    args = ap.parse_args()

    arcs_dir = _resolve_arcs_dir(args.entity)
    if not arcs_dir.is_dir():
        print(f"no arcs dir at {arcs_dir}", file=sys.stderr)
        return 1

    rows = scan(arcs_dir)
    if not args.all:
        rows = [r for r in rows if r["moving"] and not r["parked"]]
    rows.sort(key=_sort_key, reverse=True)
    rows = rows[: max(1, args.top)]

    if not rows:
        print("no starving arcs — every moving arc is fresh.")
        return 0

    if args.tick:
        r = rows[0]
        days = f"{r['stale_days']}d" if r["stale_days"] is not None else "date unknown"
        move = r["next_move"] or "(no open thread named — set one)"
        print(f"Starving arc: {r['title']} — untouched {days}. Next move: {_truncate(move, 140)}")
        return 0

    print("STARVING ARCS (stalest first) — name one, then serve-or-consciously-drift:")
    for r in rows:
        flag = "  needs_attention" if r["needs_attention"] else ""
        days = f"{r['stale_days']}d stale" if r["stale_days"] is not None else "date unknown"
        print(f"  • {r['slug']:24s} {days:13s} (last {r['last_touched']}, {r['state']}){flag}")
        if r["next_move"]:
            print(f"        → {_truncate(r['next_move'], 100)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
