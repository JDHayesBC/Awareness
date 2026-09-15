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
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

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


def _age_hours(fields: dict) -> float | None:
    raw = (fields.get("since") or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M %Z", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
        except ValueError:
            continue
    return None


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
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def active(intent_dir=None, stale_hours: float = DEFAULT_STALE_HOURS) -> list:
    """Every live claim: not released, not stale. Sorted oldest-first."""
    d = intent_dir or INTENT_DIR
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.lock")):
        f = _read(p)
        if not f or _is_released(f):
            continue
        age = _age_hours(f)
        if age is not None and age > stale_hours:
            continue
        out.append({
            "issue": (f.get("issue") or p.stem).strip(),
            "holder": (f.get("holder") or "?").strip(),
            "files": _split_files(f.get("files", "")),
            "work": (f.get("work") or "").strip(),
            "age_hours": age,
            "path": p,
        })
    out.sort(key=lambda c: (c["age_hours"] is None, -(c["age_hours"] or 0)))
    return out


def covering(path: str, intent_dir=None) -> list:
    """Live claims whose declared files cover `path` (by basename or suffix)."""
    target = Path(path).name
    hits = []
    for c in active(intent_dir=intent_dir):
        for f in c["files"]:
            if Path(f).name == target or str(path).endswith(f.lstrip("./")):
                hits.append(c)
                break
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
        parts = []
        for c in others[:4]:
            who = c["holder"].split(" (")[0]
            age = f"{c['age_hours']:.0f}h" if c["age_hours"] is not None else "?"
            line = f"{c['issue']} — {who}, {age}"
            if c["files"]:
                shown = ", ".join(Path(f).name for f in c["files"][:3])
                more = f" +{len(c['files']) - 3}" if len(c["files"]) > 3 else ""
                line += f" [{shown}{more}]"
            parts.append(line)
        return "**[intent] sibling claims:** " + " · ".join(parts)
    except Exception:
        return ""


def _cmd_claim(a) -> int:
    files = _split_files(",".join(a.files)) if a.files else []
    r = claim(a.issue, files=files, work=a.work or "")
    if r["superseded"]:
        s = r["superseded"]
        print(f"⚠ was already claimed by {s.get('holder', '?')} — {s.get('work', '')}")
        print("  Not a block. Go look before you build the same thing twice.")
    print(f"claimed: #{str(a.issue).lstrip('#')} -> {r['path']}")
    return 0


def _cmd_release(a) -> int:
    ok = release(a.issue)
    print(f"released: #{str(a.issue).lstrip('#')}" if ok else f"no claim on #{a.issue}")
    return 0 if ok else 1


def _cmd_list(a) -> int:
    cl = active()
    if not cl:
        print("no active intent claims")
        return 0
    for c in cl:
        age = f"{c['age_hours']:.1f}h" if c["age_hours"] is not None else "?"
        print(f"{c['issue']:>6}  {c['holder']}  ({age})")
        if c["files"]:
            print(f"        files: {', '.join(c['files'])}")
        if c["work"]:
            print(f"        work:  {c['work']}")
    return 0


def _cmd_check(a) -> int:
    hits = covering(a.path)
    if not hits:
        print(f"no intent claim covers {a.path}")
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
    c.set_defaults(fn=_cmd_claim)
    r = sub.add_parser("release", help="done with an issue")
    r.add_argument("issue"); r.set_defaults(fn=_cmd_release)
    l = sub.add_parser("list", help="all active claims"); l.set_defaults(fn=_cmd_list)
    k = sub.add_parser("check", help="does any claim cover this file?")
    k.add_argument("path"); k.set_defaults(fn=_cmd_check)
    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
