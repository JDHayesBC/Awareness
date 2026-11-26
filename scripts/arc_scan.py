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
    ARC_DIR=/path/to/arcs python3 scripts/arc_scan.py   # arcs kept outside entities/

DATED CHECKS (added 2026-11-24): an arc's owner may attach a forecast in frontmatter
(`check_by`, `check_claim`, `check_how`, `check_p`). Once `check_by` passes, the OTHER
entity owes a resolution, written with `scripts/arc_check.py` to an append-only ledger
(`ARC_CHECK_LEDGER`, default entities/caia-lyra-jeff/arc-checks.jsonl). This file only
READS arcs and the ledger; it never writes either. `ARC_ENTITIES_ROOT` overrides where
the sibling entities' arcs are looked up (tests; default <repo>/entities).

WAITING ON: an arc whose frontmatter has `blocked_on: <who>: <reason>` is listed under
each name it waits on (names split on , & + / and the word "and"). Put the tripwire
date in `resume_when:`; a date left inside the blocked_on text is read as the tripwire too.
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
    """Resolve the arcs dir from an explicit entity name, else ARC_DIR, else ENTITY_PATH/ENTITY_NAME.

    ARC_DIR is the harness override: an entity whose arcs live outside this repo
    (Dash keeps hers beside the rest of her runtime state, not under entities/) points
    it straight at the directory. An explicit --entity still wins over it.
    """
    if entity:
        return PROJECT_ROOT / "entities" / entity.strip().lower() / "arcs"
    arc_dir = os.environ.get("ARC_DIR", "").strip()
    if arc_dir:
        return Path(arc_dir).expanduser()
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


def _state_head(state: str) -> str:
    """The classifying part of a `state:` field.

    `state` is prose: "shipping — Articles 1 & 2 PUBLISHED (caia2025)". Only the HEAD
    is the state; the rest is history about it. Matching hints against the whole string
    lets a word in the narrative tail decide the classification — which is how
    Foundation Series sat invisible to the starving-arc pointer for 102 days: "shipping"
    was its state, but "PUBLISHED" appeared later in the same line and the not-moving
    check ran first and won.

    Split on em-dash / colon / paren only. NOT on a plain hyphen, which is load-bearing
    inside real states ("active-strategic-P0", "write-when-whim").
    """
    head = re.split(r"[—:(]", state, maxsplit=1)[0]
    return (head or state).strip().lower()


def _is_moving(fm: dict) -> bool:
    """Whether this arc's staleness is a failure signal.

    Prefer the explicit `needs_attention` field (Lyra's convention) verbatim; only
    when it's absent fall back to the state-keyword heuristic (Caia's convention).
    """
    if "needs_attention" in fm:
        return fm.get("needs_attention", "false").lower().startswith("true")
    state = fm.get("state", "").lower()
    head = _state_head(state)
    # Classify on the head. Fall back to the full string only when the head is
    # silent, so a state that says nothing up front still gets read.
    for scope in (head, state):
        if any(h in scope for h in NOT_MOVING_HINTS):
            return False
        if any(h in scope for h in MOVING_HINTS):
            return True
    return False


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


# --- Dated checks ------------------------------------------------------------------------
CHECK_KEYS = ("check_by", "check_claim", "check_how", "check_p")
_P_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(%)?\s*$")


def parse_check_p(value: str | None) -> float | None:
    """Normalise an owner's probability to a float in 0..1; None when it can't be read.

    Accepts `0.7`, `70%` and `70`. A bare number above 1 is read as a percentage, but only
    when it has no decimal point (`1.5` is ambiguous, so it is garbage, not 1.5%). The
    forecast is only worth scoring if the number means what the owner meant, so ambiguity
    returns None rather than a guess.
    """
    m = _P_RE.match(value or "")
    if not m:
        return None
    num, pct = m.group(1), m.group(2)
    v = float(num)
    if pct:
        v /= 100
    elif v > 1:
        if "." in num:
            return None
        v /= 100
    return v if 0 <= v <= 1 else None


def parse_check(fm: dict):
    """Read the check_* keys off a frontmatter dict -> (check | None, problem | None).

    No check_* key at all -> (None, None). Any key present but no usable `check_by` date
    or no `check_claim` -> (None, reason): a half-written forecast is reported, never
    silently treated as absent. Never raises.
    """
    if not any(k in fm for k in CHECK_KEYS):
        return None, None
    by = first_date(fm.get("check_by", ""))
    claim = fm.get("check_claim", "").strip()
    problems = []
    if by is None:
        problems.append("check_by missing or not a date")
    if not claim:
        problems.append("check_claim empty")
    if problems:
        return None, "; ".join(problems)
    return {"by": by, "claim": claim, "how": fm.get("check_how", "").strip(),
            "p": parse_check_p(fm.get("check_p"))}, None


def ledger_path() -> Path:
    """Where resolutions live. ARC_CHECK_LEDGER wins (tests must set it)."""
    env = os.environ.get("ARC_CHECK_LEDGER", "").strip()
    if env:
        return Path(env).expanduser()
    return PROJECT_ROOT / "entities" / "caia-lyra-jeff" / "arc-checks.jsonl"


def read_ledger(path: Path | None = None) -> list[dict]:
    """All well-formed JSON-object lines of the ledger. Missing file -> []. Bad lines skipped.

    Only a missing file is forgiven; any other I/O error propagates so a caller can tell
    "no resolutions" from "could not read the ledger".
    """
    path = path or ledger_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def resolved_keys(rows: list[dict]) -> set:
    """Keys (entity, slug, check_by ISO) that already have a resolution row."""
    keys = set()
    for r in rows:
        if r.get("kind") != "resolved":
            continue
        ent, slug, by = r.get("entity"), r.get("slug"), r.get("check_by")
        if isinstance(ent, str) and isinstance(slug, str) and isinstance(by, str):
            keys.add((ent.lower(), slug, by))
    return keys


def entities_root() -> Path:
    env = os.environ.get("ARC_ENTITIES_ROOT", "").strip()
    return Path(env).expanduser() if env else PROJECT_ROOT / "entities"


def _arc_files(arcs_dir: Path) -> list[Path]:
    """Candidate arc files: skips README and numbered design docs (they aren't live arcs)."""
    return [f for f in sorted(arcs_dir.glob("*.md"))
            if f.name != "README.md" and not re.match(r"^\d", f.name)]


def _other_arc_dirs(entity: str, root: Path | None = None) -> list[Path]:
    """`arcs` dirs of every entity except `entity`; `_template`-style dirs are skipped."""
    root = root or entities_root()
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if (d.is_dir() and not d.name.startswith("_") and d.name.lower() != entity.lower()
                and (d / "arcs").is_dir()):
            out.append(d / "arcs")
    return out


def _is_active(fm: dict) -> bool:
    """`state` HEAD names "active" (same head-not-tail rule as _is_moving)."""
    head = _state_head(fm.get("state", "").lower())
    return "active" in head and not any(h in head for h in NOT_MOVING_HINTS)


def _entity_name(entity: str | None = None) -> str:
    return entity or os.environ.get("ENTITY_NAME") or Path(
        os.environ.get("ENTITY_PATH", "entities/lyra")).name


def check_report(entity: str, rows: list[dict], today: dt.date,
                 root: Path | None = None, ledger: Path | None = None) -> dict:
    """Everything the dated-check surfaces need, computed from disk. Read-only.

    `rows` are this entity's own scan() rows. Sibling entities' arcs are read for
    frontmatter only. Keys: owed (other entity's due open checks, E resolves), awaiting
    (E's own due open checks), parked_overdue (E's own, arc parked), malformed
    [(slug, reason)], no_check (slugs for the CLI complaint). Lists sorted oldest first.
    """
    entity = entity.lower()
    done = resolved_keys(read_ledger(ledger))

    def is_open(owner: str, slug: str, by: dt.date) -> bool:
        return (owner.lower(), slug, by.isoformat()) not in done

    owed = []
    for d in _other_arc_dirs(entity, root):
        for f in _arc_files(d):
            fm = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
            check, _ = parse_check(fm)
            if check and check["by"] <= today and is_open(d.parent.name, f.stem, check["by"]):
                owed.append({**check, "owner": d.parent.name, "slug": f.stem,
                             "parked": _is_parked(fm, today)})
    awaiting, parked_overdue, malformed, no_check = [], [], [], []
    for r in rows:
        check = r.get("check")
        if r.get("check_problem"):
            malformed.append((r["slug"], r["check_problem"]))
        open_check = bool(check) and is_open(entity, r["slug"], check["by"])
        if open_check and check["by"] <= today:
            item = {**check, "owner": entity, "slug": r["slug"], "parked": r["parked"]}
            (parked_overdue if r["parked"] else awaiting).append(item)
        if (r.get("active") and not r.get("kind", "").startswith("orientational")
                and not r["parked"] and not open_check and not r.get("check_problem")):
            no_check.append(r["slug"])
    order = lambda c: (c["by"], c["owner"], c["slug"])  # noqa: E731
    return {"owed": sorted(owed, key=order), "awaiting": sorted(awaiting, key=order),
            "parked_overdue": sorted(parked_overdue, key=order),
            "malformed": malformed, "no_check": no_check}


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


_NAME_SPLIT_RE = re.compile(r"\s*(?:[,&+/]|\band\b)\s*", re.IGNORECASE)
NO_NAME_LABEL = "(no name given)"


def parse_waiting(blocked: str) -> tuple[list[str], str]:
    """Split a `blocked_on:` value into (who, reason).

    Convention: `<who>: <reason>`. The head counts as "who" only when it is non-empty,
    at most 40 chars and has no digit (so `2026-12-01: after the reset` is all reason).
    Names split on , & + / and the whole word `and`; de-duplicated case-insensitively.
    """
    value = (blocked or "").strip()
    if not value:
        return [], ""
    head, sep, rest = value.partition(":")
    head = head.strip()
    if sep and head and len(head) <= 40 and not any(c.isdigit() for c in head):
        names, seen = [], set()
        for part in _NAME_SPLIT_RE.split(head):
            part = part.strip()
            if part and part.lower() not in seen:
                seen.add(part.lower())
                names.append(part)
        if names:
            return names, rest.strip()
    return [], value


def waiting_groups(rows: list[dict], today: dt.date) -> list[tuple[str, list[dict]]]:
    """Every row with a `blocked_on`, grouped under each name it waits on.

    Groups sort alphabetically (case-insensitive) with the no-name group last; inside a
    group, stalest first and unknown dates last. `today` is accepted for symmetry with
    the other report helpers; staleness is already on the rows.
    """
    groups: dict[str, tuple[str, list[dict]]] = {}
    for r in rows:
        if not r.get("blocked_on"):
            continue
        for name in (r.get("waiting_on") or [NO_NAME_LABEL]):
            groups.setdefault(name.lower(), (name, []))[1].append(r)
    def gkey(item):
        label = item[1][0]
        return (label == NO_NAME_LABEL, label.lower())
    out = []
    for _, (label, members) in sorted(groups.items(), key=gkey):
        members.sort(key=lambda r: (r["stale_days"] is None, -(r["stale_days"] or 0)))
        out.append((label, members))
    return out


def _waiting_lines(rows: list[dict], today: dt.date) -> list[str]:
    groups = waiting_groups(rows, today)
    if not groups:
        return []
    lines = ["WAITING ON (parked on someone; an honest park is not counted as starving):"]
    for label, members in groups:
        lines.append(f"  {label}")
        for r in members:
            days = (f"{r['stale_days']}d since touched" if r["stale_days"] is not None
                    else "date unknown")
            line = f"    • {r['slug']:24s} {days}  {_truncate(r['waiting_reason'], 100)}"
            resume = first_date(r.get("resume_when", ""))
            if resume:
                line += (f" · resume {resume.isoformat()}" if resume > today
                         else " · resume date passed")
            lines.append(line)
    return lines


def scan(arcs_dir: Path, today: dt.date | None = None):
    today = today or dt.date.today()
    this_entity = arcs_dir.parent.name  # .../entities/<entity>/arcs → <entity>
    rows = []
    for f in _arc_files(arcs_dir):
        text = f.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        if not any(k in fm for k in ("last_touched", "needs_attention", "state", "blocked_on")):
            continue  # not a real arc file
        touched = first_date(fm.get("last_touched", ""))
        touched = _joint_max_touched(f.stem, fm, this_entity, touched)  # Q5: joint MAX-freshness
        stale_days = (today - touched).days if touched else None
        check, check_problem = parse_check(fm)
        blocked = fm.get("blocked_on", "").strip()
        waiting_on, waiting_reason = parse_waiting(blocked)
        # The tripwire _is_parked reads: resume_when first, else a date inside blocked_on.
        resume = first_date(fm.get("resume_when", "")) or first_date(blocked)
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
            "check": check,
            "check_problem": check_problem,
            "kind": fm.get("kind", "").strip().lower(),
            "active": _is_active(fm),
            "blocked_on": blocked,
            "waiting_on": waiting_on,
            "waiting_reason": waiting_reason,
            "resume_when": resume.isoformat() if resume else "",
        })
    return rows


def _sort_key(r: dict):
    # Callers sort with reverse=True, so every term must read "bigger = higher priority":
    #   needs_attention True→1  → explicitly-flagged arcs boosted above merely-stale ones;
    #   has_date True→1         → dated arcs above undated (unknown dates sort last);
    #   +stale_days             → POSITIVE so reverse=True yields genuine stalest-first.
    # (Was `-(stale_days)`, which combined with reverse=True inverted to least-stale-first —
    # masked while a flagged P0 arc dominated tier 1, exposed once all flagged arcs were served.)
    return (r["needs_attention"], r["stale_days"] is not None, (r["stale_days"] or 0))


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
        if today is None:
            today = dt.date.today()
        ent = _entity_name(entity)
        all_rows = scan(arcs_dir, today) if arcs_dir.is_dir() else []
        old = _starving_line(all_rows, entity, ent, today, threshold_days)
        # Dated checks ride on top of the starving line. Any failure here (unreadable
        # ledger, odd sibling file) must leave today's starving line intact, so it gets its
        # own guard inside the never-raise one.
        try:
            return _with_checks(old, check_report(ent, all_rows, today))
        except Exception as exc:
            # Same rule as the outer guard: a failure that renders as silence would look
            # exactly like "no check is due". Keep the starving line and say we are blind.
            why = f"{type(exc).__name__}: {exc}"[:100]
            blind = (f"**[arcs] ⚠ dated checks unreadable this tick ({why}). "
                     "A due check may be hidden.**")
            return f"{old}\n{blind}" if old else blind
    except Exception as exc:  # pragma: no cover - must never break the hook
        # Silence in this block means "nothing to report". A crash that also renders as
        # silence is therefore a LIE in the one direction nobody checks — it looks
        # exactly like a tended board. Never raise (the hook must survive), but never
        # go quiet about going blind either.
        return ("**[{name}] ⚠ scan failed — this sense is BLIND this tick "
                "({exc}). Silence here does not mean nothing to report.**").format(
                    name="arcs", exc=f"{type(exc).__name__}: {exc}"[:120])


RESOLVE_HINT = 'python3 scripts/arc_check.py resolve {owner} {slug} true|false|void --evidence "..."'


def _with_checks(old: str, rep: dict) -> str:
    """Layer the dated-check lines onto the starving line (see format_arc_block)."""
    out = []
    owed = rep["owed"]
    if owed:
        c = owed[0]
        # The CLI tags a parked arc; the front block must too, so the resolver knows the
        # owner set the arc down and did not simply let the date go by.
        parked = " (parked arc)" if c.get("parked") else ""
        line = (f"**[arcs] 🔴 dated check due, yours to resolve: {c['owner']}/{c['slug']}"
                f"{parked} (by {c['by'].isoformat()}): {_truncate(c['claim'], 140)}.** "
                f"Resolve: {RESOLVE_HINT.format(owner=c['owner'], slug=c['slug'])}")
        if len(owed) > 1:
            line += f" (+{len(owed) - 1} more)"
        out.append(line)
    malformed = rep.get("malformed") or []
    if malformed:
        # An own error, not a standing complaint. A mistyped check would otherwise vanish
        # from the one surface that gets read every tick, and on its due date a typo
        # would look exactly like a forgotten check.
        slug, reason = malformed[0]
        more = f" (+{len(malformed) - 1} more)" if len(malformed) > 1 else ""
        out.append(f"**[arcs] ⚠ your check on {slug} is malformed ({reason}) "
                   f"and will not surface{more}**")
    awaiting = rep["awaiting"]
    if awaiting:
        a = awaiting[0]
        name = a["slug"] + (f" (+{len(awaiting) - 1} more)" if len(awaiting) > 1 else "")
        if old:
            first, sep, rest = old.partition("\n")
            old = f"{first} · your check on {name} is due and awaits resolution{sep}{rest}"
        else:
            old = f"**[arcs]** your check on {name} is due and awaits resolution"
    if old:
        out.append(old)
    return "\n".join(out)


def _starving_line(all_rows: list[dict], entity: str | None, ent: str,
                   today: dt.date, threshold_days: int) -> str:
    """Today's starving-arc pointer, unchanged, or "" when nothing is starving."""
    rows = [r for r in all_rows
            if r["moving"] and not r["parked"] and r["stale_days"] is not None
            and r["stale_days"] >= threshold_days]
    if not rows:
        return ""  # every moving arc served (or honestly parked) → silent, like [health].
    rows.sort(key=_sort_key, reverse=True)
    pick = rows[0]
    move = pick["next_move"] or "(no open thread named — set one)"
    marker = _escalation_marker(pick["stale_days"], threshold_days)
    line = (f"**[arcs] {marker} most-starved commitment: {pick['title']} "
            f"— untouched {pick['stale_days']}d.** "
            f"Next move: {_truncate(move, 110)}")
    extra = len(rows) - 1
    if extra > 0:
        env = (f"ARC_DIR={os.environ['ARC_DIR'].strip()}"
               if not entity and os.environ.get("ARC_DIR", "").strip()
               else f"ENTITY_NAME={ent}")
        # NOT `--all`: that is the UNFILTERED view (includes published/dormant arcs)
        # and is capped at --top 3, so it showed a different, shorter list than the
        # "+N more" it was cited for. `--top` keeps the starving filter and fits them all.
        line += (f"\n   (+{extra} more moving arc(s) stale ≥{threshold_days}d — "
                 f"`{env} python3 scripts/arc_scan.py --top {len(rows)}`)")
    return line


def _p_str(p) -> str:
    return "?" if p is None else f"{p:g}"


def _check_sections(rep: dict, today: dt.date) -> list[str]:
    """CLI text for the dated-check sections (empty sections are omitted)."""
    lines = []
    if rep["owed"]:
        lines.append("DATED CHECKS DUE — yours to resolve:")
        for c in rep["owed"]:
            tag = "  (parked arc)" if c["parked"] else ""
            lines.append(f"  • {c['owner']}/{c['slug']}  by {c['by'].isoformat()} "
                         f"({(today - c['by']).days}d overdue)  p={_p_str(c['p'])}  — "
                         f"{c['claim']}  · how: {c['how'] or '?'}{tag}")
        lines.append("  " + RESOLVE_HINT.format(owner="<owner>", slug="<slug>"))
    if rep["awaiting"]:
        lines.append("YOUR CHECKS AWAITING RESOLUTION:")
        for c in rep["awaiting"]:
            lines.append(f"  • {c['slug']}  by {c['by'].isoformat()} "
                         f"({(today - c['by']).days}d overdue)  p={_p_str(c['p'])}  — {c['claim']}")
    for c in rep["parked_overdue"]:
        lines.append(f"check overdue on a parked arc: {c['slug']} (by {c['by'].isoformat()}, "
                     f"{(today - c['by']).days}d overdue)")
    return lines


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(description="Rank arcs by staleness (the starving-arc surface).")
    ap.add_argument("--entity", default=None,
                    help="Entity name (default: $ENTITY_NAME / basename($ENTITY_PATH)).")
    ap.add_argument("--all", action="store_true", help="include arcs whose staleness isn't a failure signal")
    ap.add_argument("--top", type=int, default=3, help="how many to surface (default 3)")
    ap.add_argument("--threshold", type=int, default=14,
                    help="staleness (days) at/above which a moving arc counts as starving (default 14)")
    ap.add_argument("--tick", action="store_true",
                    help="print a one-line starving-arc pointer for a heartbeat tick prompt")
    args = ap.parse_args(argv)

    arcs_dir = _resolve_arcs_dir(args.entity)
    if not arcs_dir.is_dir():
        print(f"no arcs dir at {arcs_dir}", file=sys.stderr)
        return 1

    today = dt.date.today()
    all_rows = scan(arcs_dir, today)
    rows = all_rows
    if not args.all:
        # Same definition of "starving" as format_arc_block (the ambient injection): a
        # moving, un-parked arc whose VERIFIED staleness meets the threshold. Applying the
        # threshold here too keeps the CLI honest — empty-when-served, no "untouched 0d"
        # cry-wolf on a freshly-tended arc. `--all` remains the unfiltered diagnostic view.
        rows = [r for r in rows if r["moving"] and not r["parked"]
                and r["stale_days"] is not None and r["stale_days"] >= args.threshold]
    rows.sort(key=_sort_key, reverse=True)
    rows = rows[: max(1, args.top)]

    if args.tick:
        # One line for a heartbeat prompt: dated checks stay out of it on purpose.
        if not rows:
            print("no starving arcs — every moving arc is fresh.")
            return 0
        r = rows[0]
        days = f"{r['stale_days']}d" if r["stale_days"] is not None else "date unknown"
        move = r["next_move"] or "(no open thread named — set one)"
        print(f"Starving arc: {r['title']} — untouched {days}. Next move: {_truncate(move, 140)}")
        return 0

    rep = None
    try:
        rep = check_report(_entity_name(args.entity), all_rows, today)
    except Exception as exc:  # a broken ledger must be loud here, not silently "no checks"
        print(f"dated checks unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
    if rep:
        for line in _check_sections(rep, today):
            print(line)

    if not rows:
        print("no starving arcs — every moving arc is fresh.")
    else:
        print("STARVING ARCS (stalest first) — name one, then serve-or-consciously-drift:")
        for r in rows:
            flag = "  needs_attention" if r["needs_attention"] else ""
            days = f"{r['stale_days']}d stale" if r["stale_days"] is not None else "date unknown"
            print(f"  • {r['slug']:24s} {days:13s} (last {r['last_touched']}, {r['state']}){flag}")
            if r["next_move"]:
                print(f"        → {_truncate(r['next_move'], 100)}")
    for line in _waiting_lines(all_rows, today):
        print(line)
    if rep:
        for slug, reason in rep["malformed"]:
            print(f"malformed check: {slug} ({reason})")
        if rep["no_check"]:
            print(f"{len(rep['no_check'])} active arcs without a dated check: "
                  f"{', '.join(rep['no_check'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
