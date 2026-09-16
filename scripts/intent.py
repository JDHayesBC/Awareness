#!/usr/bin/env python3
"""Task/intent claims — declare work BEFORE starting (issue #324).

The prevention half of #305. ``lock.py`` is the *backstop*: it catches a
collision at the moment two channels touch the same file. By then both are
already invested. An intent claim is the *announcement*: a channel says
"I'm taking #324, it will touch these files" before it opens anything, and a
sibling channel sees that claim in its ambient front-block on the next tick.

Claims live at ``<repo>/.locks/intent/<issue>.lock`` (#324: repo-local, one
place, gitignored) and reuse ``lock.py``'s plain-text field format, so the
same eyeballs and the same parser work on both.

Why a separate namespace from file locks:
  - A file lock is a MUTEX. Seconds to minutes. "I have this open right now."
  - An intent claim is a RECORD. Hours to days. "This issue is mine, and here
    is the blast radius." It is project information, closer to tasks.md than
    to a mutex — which is exactly why it lives somewhere you'd look.

An intent claim deliberately does NOT block. Blocking is lock.py's job and it
already does it well. This layer exists to make the collision *visible early*,
because the failure it targets is two channels doing the same work in
parallel, not two channels corrupting one file.

    python3 scripts/intent.py claim 324 --files scripts/lock.py,daemon/x.py \
        --work "move locks into repo + intent layer"
    python3 scripts/intent.py list
    python3 scripts/intent.py check scripts/lock.py
    python3 scripts/intent.py release 324
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Repo root, derived from __file__ like lock.py's (#324) — never from cwd, which
# differs per channel. Used to pin `gh` to THIS repo regardless of where we're invoked.
_REPO_ROOT = Path(__file__).resolve().parent.parent

from lock import (  # noqa: E402
    LOCKS_DIR,
    _is_released,
    _now_iso,
    default_holder,
    parse_lock_text,
    same_holder,
)

INTENT_DIR = Path(os.environ.get("CLAUDE_INTENT_DIR", LOCKS_DIR / "intent"))

# A claim older than this is almost certainly a channel that died mid-work
# rather than a channel still working. Longer than lock.py's 12h because an
# intent claim legitimately spans a multi-day piece of work.
DEFAULT_STALE_HOURS = 72.0


def intent_path_for(issue: str | int, intent_dir: Path | None = None) -> Path:
    d = intent_dir or INTENT_DIR
    return d / f"{str(issue).lstrip('#')}.lock"


def _read(p: Path) -> dict | None:
    try:
        return parse_lock_text(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def _parse_since(raw: str) -> datetime | None:
    """Parse a claim's `since:` in any format we have ever written. None = unparsable."""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M %Z", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime((raw or "").strip(), fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _age_hours(fields: dict) -> float | None:
    dt = _parse_since(fields.get("since") or "")
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def _split_files(raw: str) -> list:
    return [f.strip() for f in (raw or "").replace("\n", ",").split(",") if f.strip()]


def claim(issue, files=None, work="", holder=None, intent_dir=None) -> dict:
    """Record an intent claim. Never blocks; returns the prior claim if any."""
    d = intent_dir or INTENT_DIR
    d.mkdir(parents=True, exist_ok=True)
    p = intent_path_for(issue, d)
    me = holder or default_holder()

    prior = _read(p) if p.exists() else None
    superseded = None
    if prior and not _is_released(prior) and not same_holder(prior.get("holder", ""), me):
        superseded = prior  # surfaced to the caller; we do NOT silently steal

    lines = [
        f"issue: #{str(issue).lstrip('#')}",
        "status: CLAIMED",
        f"holder: {me}",
        f"since: {_now_iso()}",
    ]
    if files:
        lines.append("files: " + ", ".join(files))
    if work:
        lines.append(f"work: {work}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"path": p, "superseded": superseded}


def delivery_observed(issue, intent_dir=None) -> bool | None:
    """Did any file this claim DECLARED actually change since the claim was made?

    Returns True / False / None, deliberately the same three-way contract as
    ``issue_exists`` above — None means "could not find out", never "no".

    Why this exists (2026-09-16). ``release()`` writes ``status: RELEASED`` from the
    holder's own say-so and nothing ever looks. So the announce half is verified at
    claim time (we check the issue number is real) while the settle half — the half
    that tells a sibling "this is finished, stop waiting on it" — is pure self-report.
    That asymmetry is backwards: the louder claim is the checked one.

    ⚠ OBSERVED DECAYS WITH CLAIM AGE, AND ONLY IN THE REASSURING DIRECTION. The
    window is `since` → now and never closes, so the longer a claim stays open the
    likelier OBSERVED becomes whether or not the holder did anything. In a repo with
    independent checkouts that would be mild. **Lyra and Caia share ONE working tree**,
    so an unrelated edit to a declared file is not an exotic fluke — it is Tuesday.
    OBSERVED on a two-hour-old claim is weak evidence; OBSERVED on a three-day-old claim
    is close to none. That is why `release()` stamps the age alongside the verdict
    (`OBSERVED (4h)` vs `OBSERVED (3d)`): a reader must be able to discount it without
    doing arithmetic. Git cannot rescue attribution here — we commit under one identity.
    Found by Lyra, 2026-09-16, reading the commit that introduced this function.

    This is NOT proof the work happened. Borrowing the distinction from Ashley's
    evaluation plane (docs/architecture/Ashley_Evaluation_Qualification_Plane.md:356):
    a *receipt* is what a path reports about itself; a *witness* independently observes
    enough post-effect reality to support the claim. A self-reported RELEASE is a
    receipt. An observed change to the declared files is a weak witness — it can be
    fooled by an unrelated edit, and it says nothing about quality. It can only ever
    falsify the emptiest case: released, and not one declared file was touched.

    None is returned whenever the question is unanswerable rather than answered "no":
    the claim declared no files, no timestamp, or the mtime could not be read. An
    unverifiable settle must not be reported like a disproven one.
    """
    fields = _read(intent_path_for(issue, intent_dir or INTENT_DIR)) or {}
    declared = _split_files(fields.get("files", ""))
    if not declared:
        return None  # nothing was promised in file terms — nothing to witness
    since_dt = _parse_since(fields.get("since", ""))
    if since_dt is None:
        return None
    since = since_dt.timestamp()
    seen_any = False
    for rel in declared:
        # Repo-root-relative ONLY. Deliberately no recursive glob: a bare basename
        # would make this walk the whole tree (.git, vendored clones) on every
        # release, and a settle must never be the slow part of anything. A claim
        # that declared a basename we cannot locate answers UNKNOWN, not "no" —
        # which is also a quiet nudge to declare real paths at claim time.
        cand = _REPO_ROOT / rel
        try:
            if cand.is_file():
                seen_any = True
                if cand.stat().st_mtime > since:
                    return True
        except OSError:
            continue
    return False if seen_any else None  # never found the file at all => unknown, not no


def release(issue, holder=None, intent_dir=None) -> bool:
    p = intent_path_for(issue, intent_dir or INTENT_DIR)
    if not p.exists():
        return False
    fields = _read(p) or {}
    me = holder or default_holder()
    lines = [
        f"issue: #{str(issue).lstrip('#')}",
        "status: RELEASED",
        f"holder: (released by {me})",
        f"since: {fields.get('since', _now_iso())}",
    ]
    if fields.get("files"):
        lines.append(f"files: {fields['files']}")
    if fields.get("work"):
        lines.append(f"work: {fields['work']}")
    # Record what we could observe, not what was asserted. The tombstone is the
    # thing a sibling reads later; a settle with no observed delivery should say so
    # in the record rather than only in a warning nobody kept.
    seen = delivery_observed(issue, intent_dir)
    verdict = {True: "OBSERVED", False: "NONE_OBSERVED", None: "UNKNOWN"}[seen]
    age = _age_hours(fields)
    if seen is True and age is not None:
        # The age is not decoration: OBSERVED drifts toward yes as the window widens,
        # so the verdict is only readable next to how long the window was open.
        verdict += f" ({age:.0f}h)" if age < 48 else f" ({age / 24:.0f}d)"
    lines.append(f"delivery: {verdict}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def active(intent_dir=None, stale_hours: float = DEFAULT_STALE_HOURS,
           include_stale: bool = True) -> list:
    """Every unreleased claim, each tagged ``stale``. Sorted oldest-first.

    A stale claim is NOT dropped (Lyra's review, 2026-09-14). Dropping it makes
    an abandoned claim render identically to no claim at all — a surface
    asserting a false ABSENCE, which is #327 inverted and reads exactly like
    "nothing is claimed here, go ahead." Same shape as the #136 catch: a claim
    that expires into silence is quiet un-claiming.

    Empty-when-served is right for *served*. It is wrong for *abandoned*.
    So staleness escalates into the block instead of removing itself from it.
    """
    d = intent_dir or INTENT_DIR
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.lock")):
        f = _read(p)
        if not f or _is_released(f):
            continue
        age = _age_hours(f)
        is_stale = age is not None and age > stale_hours
        if is_stale and not include_stale:
            continue
        out.append({
            "issue": (f.get("issue") or p.stem).strip(),
            "holder": (f.get("holder") or "?").strip(),
            "files": _split_files(f.get("files", "")),
            "work": (f.get("work") or "").strip(),
            "age_hours": age,
            "stale": is_stale,
            "path": p,
        })
    out.sort(key=lambda c: (c["age_hours"] is None, -(c["age_hours"] or 0)))
    return out


def _covers(declared: str, target: str) -> bool:
    """Does a declared path cover `target`? PATH-AWARE, never bare-basename.

    Bare basename equality is a false positive generator (Lyra's review): this
    repo alone has nine duplicated basenames — bot.py, server.py, models.py,
    auth.py, session_end.py, startup_context.py among them — so a claim on
    daemon/bot.py would report as covering haven/bot.py. It errs in the worst
    direction: a sibling backs off work nobody claimed.

    A match requires the declared path to be a whole trailing path SEGMENT of
    the target (or equal to it), so "bot.py" alone still matches "x/bot.py"
    only when the claimer wrote exactly that, never across directories.
    """
    d = declared.strip().lstrip("./").rstrip("/")
    t = str(target).strip().lstrip("./")
    if not d:
        return False
    if d == t:
        return True
    return t.endswith("/" + d)


def covering(path: str, intent_dir=None) -> list:
    """Unreleased claims whose declared files cover `path` (stale ones included,
    each carrying its own ``stale`` flag — an abandoned claim is still a signal
    worth seeing, it just needs to be labelled rather than hidden)."""
    hits = []
    for c in active(intent_dir=intent_dir):
        if any(_covers(f, path) for f in c["files"]):
            hits.append(c)
    return hits


def format_intent_block(holder: str | None = None, intent_dir=None) -> str:
    """Ambient front-block sense. EMPTY when nothing is claimed by a sibling.

    Same discipline as [health]/[arcs]: silent when served, verified from
    world-state (files on disk), never raises into the hook.
    """
    try:
        me = holder or default_holder()
        others = [c for c in active(intent_dir=intent_dir)
                  if not same_holder(c["holder"], me)]
        if not others:
            return ""
        # Stale first — an abandoned claim is the one that needs a decision.
        others.sort(key=lambda c: (not c.get("stale"), -(c["age_hours"] or 0)))
        parts = []
        for c in others[:4]:
            who = c["holder"].split(" (")[0]
            if c["age_hours"] is None:
                age = "?"
            elif c["age_hours"] >= 48:
                age = f"{c['age_hours'] / 24:.0f}d"
            else:
                age = f"{c['age_hours']:.0f}h"
            line = f"{c['issue']} — {who}, {age}"
            if c.get("stale"):
                line += " ⚠ STALE, still theirs?"
            if c["files"]:
                shown = ", ".join(Path(f).name for f in c["files"][:3])
                more = f" +{len(c['files']) - 3}" if len(c["files"]) > 3 else ""
                line += f" [{shown}{more}]"
            parts.append(line)
        tail = f" · +{len(others) - 4} more" if len(others) > 4 else ""
        return "**[intent] sibling claims:** " + " · ".join(parts) + tail
    except Exception:
        return ""


def issue_exists(issue) -> bool | None:
    """Does this issue number actually exist on the board?

    Returns True / False / None, where None means "could not find out" (gh missing,
    offline, timed out, not a repo). The three-way answer is the point: an unverifiable
    claim must NOT be treated the same as a disproven one — coordination should degrade
    to a warning when the network is down, never block real work.

    Why this exists (2026-09-15, my own bug): Lyra claimed #329 by intent BEFORE filing
    the issue, I filed mine assuming 329 was taken, and gh handed 329 to me — so we had
    one number and two meanings for a while. The intent layer coordinates *work*, but it
    was treating the *identifier* as authoritative when nothing had ever validated it.
    That is the same shape as #327 (kernel bullets asserting state they never read):
    a key that looks authoritative but was never checked against the source.
    """
    try:
        out = subprocess.run(
            ["gh", "issue", "view", str(issue).lstrip("#"), "--json", "number"],
            cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        # Only genuine "could not run gh" conditions degrade to unknown. A NameError or
        # TypeError here is a coding bug, and must be allowed to surface loudly rather
        # than masquerade as an offline network — that swallow is precisely what made
        # this guard a silent no-op on first write (caught by test, 2026-09-15).
        return None
    if out.returncode == 0:
        return True
    err = (out.stderr or "").lower()
    if "not found" in err or "could not resolve" in err or "no issue" in err:
        return False
    return None  # some other gh failure — unknown, not disproven


def _cmd_claim(a) -> int:
    if not getattr(a, "force", False):
        exists = issue_exists(a.issue)
        if exists is False:
            n = str(a.issue).lstrip("#")
            print(f"refused: issue #{n} does not exist on the board yet.", file=sys.stderr)
            print("  File it first (`gh issue create`), then claim the number gh gives you.",
                  file=sys.stderr)
            print("  Claiming a number before it is allocated is how two channels end up "
                  "with one number and two meanings.", file=sys.stderr)
            print("  If you really mean it (a number you are about to be assigned, an "
                  "external tracker), re-run with --force.", file=sys.stderr)
            return 2
        if exists is None:
            print("⚠ could not verify the issue exists (gh offline/unavailable) — "
                  "claiming anyway.", file=sys.stderr)
    files = _split_files(",".join(a.files)) if a.files else []
    r = claim(a.issue, files=files, work=a.work or "")
    if r["superseded"]:
        s = r["superseded"]
        print(f"⚠ was already claimed by {s.get('holder', '?')} — {s.get('work', '')}")
        print("  Not a block. Go look before you build the same thing twice.")
    print(f"claimed: #{str(a.issue).lstrip('#')} -> {r['path']}")
    return 0


def _cmd_release(a) -> int:
    seen = delivery_observed(a.issue)
    ok = release(a.issue)
    print(f"released: #{str(a.issue).lstrip('#')}" if ok else f"no claim on #{a.issue}")
    if ok and seen is False:
        print("⚠ released, but none of the declared files changed since the claim.",
              file=sys.stderr)
        print("  Not an error and not blocked — intent never blocks. But a settle is a "
              "promise to a sibling that this is done.", file=sys.stderr)
        print("  If the work landed elsewhere, say so in the claim; if it did not land, "
              "release is the wrong verb.", file=sys.stderr)
    return 0 if ok else 1


def _cmd_list(a) -> int:
    if getattr(a, "released", False):
        st = settled()
        if not st:
            print("no released claims on record")
            return 0
        for c in st:
            print(f"{c['issue']:>6}  {c['holder']}  delivery: {c['delivery']}")
            if c["files"]:
                print(f"        files: {', '.join(c['files'])}")
            if c["work"]:
                print(f"        work:  {c['work']}")
        return 0
    cl = active()
    if not cl:
        print("no active intent claims")
        return 0
    for c in cl:
        age = f"{c['age_hours']:.1f}h" if c["age_hours"] is not None else "?"
        flag = "  ⚠ STALE" if c.get("stale") else ""
        print(f"{c['issue']:>6}  {c['holder']}  ({age}){flag}")
        if c["files"]:
            print(f"        files: {', '.join(c['files'])}")
        if c["work"]:
            print(f"        work:  {c['work']}")
    return 0


def settled(intent_dir=None) -> list:
    """Released claims, newest-first — the tombstones. `active()` drops these by design,
    which meant `delivery:` was written into the one place no reader ever opened
    (Lyra, 2026-09-16). A settle is a promise to a sibling; the sibling needs a way to
    read what was actually observed behind the word RELEASED."""
    d = intent_dir or INTENT_DIR
    out = []
    for p in sorted(d.glob("*.lock")) if d.exists() else []:
        f = _read(p)
        if not f or not _is_released(f):
            continue
        out.append({
            "issue": f.get("issue", p.stem),
            "holder": f.get("holder", "?"),
            "files": _split_files(f.get("files", "")),
            "work": f.get("work", ""),
            "delivery": f.get("delivery", "(not recorded)"),
        })
    return out


def _cmd_check(a) -> int:
    hits = covering(a.path)
    if not hits:
        print(f"no intent claim covers {a.path}")
        # Nobody is working it now — but if the last word on it was a settle with
        # nothing observed, that is exactly what a sibling about to trust "done"
        # should see. Surfaced here rather than only at release, because this is
        # where someone ASKS.
        for c in settled():
            if c["delivery"].startswith("NONE_OBSERVED") and any(
                    _covers(f, a.path) for f in c["files"]):
                print(f"  ⚠ {c['issue']} was released with delivery: {c['delivery']}")
                if c["work"]:
                    print(f"      work: {c['work']}")
        return 0
    for c in hits:
        print(f"⚠ {c['issue']} claimed by {c['holder']} covers {a.path}")
        if c["work"]:
            print(f"    work: {c['work']}")
    return 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Declare intent to work an issue (#324).")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("claim", help="declare you are taking an issue")
    c.add_argument("issue")
    c.add_argument("--files", action="append", help="files you expect to touch (comma-ok)")
    c.add_argument("--work", help="one line on what you're doing")
    c.add_argument("--force", action="store_true",
                   help="claim even if the issue number does not exist on the board yet")
    c.set_defaults(fn=_cmd_claim)
    r = sub.add_parser("release", help="done with an issue")
    r.add_argument("issue"); r.set_defaults(fn=_cmd_release)
    l = sub.add_parser("list", help="all active claims")
    l.add_argument("--released", action="store_true",
                   help="show settled claims and what delivery was observed instead")
    l.set_defaults(fn=_cmd_list)
    k = sub.add_parser("check", help="does any claim cover this file?")
    k.add_argument("path"); k.set_defaults(fn=_cmd_check)
    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
