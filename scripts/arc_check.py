#!/usr/bin/env python3
"""
arc_check.py — resolve a dated check on an arc, and list the open ones.

An arc's owner attaches a forecast to her arc (`check_by`, `check_claim`, `check_how`,
`check_p` in the frontmatter). Once `check_by` passes, the OTHER entity looks at the
disk, decides true / false / void, and records it here. The point of the split is that
the person who made the forecast is not the person who grades it.

Resolutions go to an append-only JSON Lines ledger (`ARC_CHECK_LEDGER`, default
entities/caia-lyra-jeff/arc-checks.jsonl). This script never modifies an arc file and
never rewrites or deletes a ledger line. The claim, how and p are copied into the row on
purpose: the ledger must stay scoreable after the owner replaces the frontmatter with
her next check.

Usage:
    python3 scripts/arc_check.py resolve <owner> <slug> true|false|void --evidence "..."
            [--by NAME] [--self-checked] [--early]
    python3 scripts/arc_check.py list

Exit codes: 0 ok, 2 refused (nothing written).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_scan  # noqa: E402  (shared parsing so the scanner and this agree on what a check is)


class Refusal(Exception):
    """A reason to write nothing. Carries the message shown to the caller."""


def _session_name() -> str:
    return (os.environ.get("ENTITY_NAME")
            or Path(os.environ.get("ENTITY_PATH", "")).name or "").strip().lower()


def _resolver_name(by: str | None) -> tuple[str, str]:
    """Who is resolving, and where the name came from: "env" or "flag".

    The session's own name wins. `--by` exists for shells with no entity environment. If
    the session does have a name, a `--by` that disagrees with it is refused: a row that
    can say someone else did the grading is the one row this ledger cannot afford.
    """
    session = _session_name()
    typed = (by or "").strip().lower()
    if session:
        if typed and typed != session:
            raise Refusal(f"--by {typed!r} does not match this session ({session!r}): a "
                          "resolution is recorded under the session that made it")
        return session, "env"
    if not typed:
        raise Refusal("cannot tell who is resolving: pass --by NAME or set ENTITY_NAME/ENTITY_PATH")
    return typed, "flag"


def resolve(owner: str, slug: str, outcome: str, evidence: str, by: str | None = None,
            self_checked: bool = False, early: bool = False,
            today: dt.date | None = None) -> dict:
    """Validate, then append exactly one resolution row. Returns the row.

    Raises Refusal (nothing written) on any failed precondition. The arc file is only read.
    """
    today = today or dt.date.today()
    owner = owner.strip().lower()
    if not owner or not slug or any(c in owner + slug for c in "/\\") or ".." in owner + slug:
        raise Refusal(f"bad owner/slug: {owner!r}/{slug!r}")
    if outcome not in ("true", "false", "void"):
        raise Refusal(f"outcome must be true, false or void, not {outcome!r}")
    resolver, resolver_source = _resolver_name(by)
    evidence = (evidence or "").strip()
    if not evidence:
        raise Refusal("--evidence is empty: say what you looked at")

    arc = arc_scan.entities_root() / owner / "arcs" / f"{slug}.md"
    if not arc.is_file():
        raise Refusal(f"no arc file at {arc}")
    fm = arc_scan.parse_frontmatter(arc.read_text(encoding="utf-8", errors="replace"))
    check, problem = arc_scan.parse_check(fm)
    if not check:
        raise Refusal(f"{owner}/{slug} has no well-formed check"
                      + (f" ({problem})" if problem else ""))
    if resolver == owner and not self_checked:
        raise Refusal("the owner is resolving her own check: have the other entity do it, "
                      "or pass --self-checked to record that it was self-graded")
    if today < check["by"] and not early:
        raise Refusal(f"check_by is {check['by'].isoformat()}, not reached yet: pass --early "
                      "to resolve ahead of the date")

    ledger = arc_scan.ledger_path()
    if not ledger.parent.is_dir():
        raise Refusal(f"ledger directory does not exist: {ledger.parent}")
    key = (owner, slug, check["by"].isoformat())
    if key in arc_scan.resolved_keys(arc_scan.read_ledger(ledger)):
        raise Refusal(f"{owner}/{slug} by {key[2]} already has a resolution in {ledger}")

    row = {
        "kind": "resolved",
        "entity": owner,
        "slug": slug,
        "check_by": key[2],
        "claim": check["claim"],
        "how": check["how"],
        "p": check["p"],
        "outcome": outcome,
        "resolved_by": resolver,
        # "env" when the name is the session's own ENTITY_NAME/ENTITY_PATH, "flag" when
        # it was typed with --by in a shell that has neither. A typed name cannot be
        # checked against anything, so it is marked.
        "resolver_source": resolver_source,
        # Recorded as what happened, not as what was typed: a flag passed by a different
        # resolver would otherwise label an honest cross-check as self-graded.
        "self_checked": resolver == owner,
        "early": today < check["by"],
        "evidence": evidence,
        "resolved_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    payload = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    # One write on an append-mode handle, so two resolvers cannot interleave inside a line.
    # If the file exists without a trailing newline (hand-edited), lead with one so this
    # row cannot glue onto the previous line.
    if ledger.is_file() and ledger.stat().st_size > 0:
        with ledger.open("rb") as fh:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                payload = b"\n" + payload
    with ledger.open("ab") as fh:
        fh.write(payload)
    return row


def _all_open_checks(today: dt.date) -> list[dict]:
    """Every well-formed, unresolved check across all entities (frontmatter read only)."""
    done = arc_scan.resolved_keys(arc_scan.read_ledger())
    root = arc_scan.entities_root()
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        arcs = d / "arcs"
        if d.name.startswith("_") or not arcs.is_dir():
            continue
        for f in arc_scan._arc_files(arcs):
            fm = arc_scan.parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
            check, _ = arc_scan.parse_check(fm)
            if check and (d.name.lower(), f.stem, check["by"].isoformat()) not in done:
                out.append({**check, "owner": d.name, "slug": f.stem})
    return sorted(out, key=lambda c: (c["by"], c["owner"], c["slug"]))


def list_checks(today: dt.date | None = None) -> list[str]:
    today = today or dt.date.today()
    lines = []
    for c in _all_open_checks(today):
        p = "?" if c["p"] is None else f"{c['p']:g}"
        due = "  (due)" if c["by"] <= today else ""
        lines.append(f"{c['owner']}/{c['slug']}  by {c['by'].isoformat()}  p={p}  — {c['claim']}{due}")
    if not lines:
        lines.append("no open checks")
    rows = [r for r in arc_scan.read_ledger() if r.get("kind") == "resolved"]
    count = lambda o: sum(1 for r in rows if r.get("outcome") == o)  # noqa: E731
    selfc = sum(1 for r in rows if r.get("self_checked") is True)
    lines.append(f"resolved {len(rows)} · true {count('true')} · false {count('false')} · "
                 f"void {count('void')} · self-checked {selfc}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Resolve or list dated arc checks.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve", help="record the outcome of a due check")
    r.add_argument("owner")
    r.add_argument("slug")
    r.add_argument("outcome", choices=("true", "false", "void"))
    r.add_argument("--evidence", required=True)
    r.add_argument("--by", default=None)
    r.add_argument("--self-checked", action="store_true")
    r.add_argument("--early", action="store_true")
    sub.add_parser("list", help="open checks across entities, plus the ledger score")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        print("\n".join(list_checks()))
        return 0
    try:
        row = resolve(args.owner, args.slug, args.outcome, args.evidence, by=args.by,
                      self_checked=args.self_checked, early=args.early)
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"refused: could not write the ledger ({exc})", file=sys.stderr)
        return 2
    print(f"resolved {row['entity']}/{row['slug']} (by {row['check_by']}): {row['outcome']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
