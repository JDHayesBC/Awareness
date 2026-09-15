#!/usr/bin/env python3
"""Render the CLAUDE.md §VIII arc list from arc frontmatter.

The §VIII "Currently active" list has always been hand-authored, and it drifts:
it silently dropped `thorough-mode` for four days (noted in §VIII itself), and as
of 2026-09-14 it omits `knowledge-commons` entirely. A hand-maintained index of
files that live on disk is a cache with no invalidation.

This is the `[v1] Index-as-rendering` open thread on the arcs-architecture arc:
generate the list, never hand-author it. Staleness is read off each file's own
`last_touched`, so the rendered list cannot claim an arc is fine when the disk says
otherwise -- the same verified-not-asserted property `arc_scan.py` gives the
starving-arc pointer.

Usage:
    ENTITY_NAME=lyra python3 scripts/arc_index.py            # print the block
    ENTITY_NAME=lyra python3 scripts/arc_index.py --check    # diff vs CLAUDE.md, exit 1 on drift

Writing the block into CLAUDE.md stays a human/entity edit -- this prints, it does
not patch identity files.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arc_scan import PROJECT_ROOT, parse_frontmatter, first_date  # noqa: E402


def resolve_arcs_dir(entity: str | None) -> Path:
    name = entity or os.environ.get("ENTITY_NAME") or "lyra"
    return PROJECT_ROOT / "entities" / name.strip().lower() / "arcs"


def load(arcs_dir: Path) -> list[dict]:
    """Every real arc file on disk, with its frontmatter facts. Disk is the truth."""
    today = dt.date.today()
    arcs = []
    for f in sorted(arcs_dir.glob("*.md")):
        if f.name == "README.md" or re.match(r"^\d", f.name):
            continue  # numbered files are design docs, not live arcs
        fm = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
        if not {"last_touched", "state", "needs_attention"} & set(fm):
            continue
        touched = first_date(fm.get("last_touched", ""))
        parent = (fm.get("parent") or "").split("#")[0].strip()
        arcs.append({
            "slug": f.stem,
            "title": fm.get("title", f.stem),
            "kind": (fm.get("kind") or "?").strip(),
            "state": (fm.get("state") or "?").split("—")[0].split(",")[0].strip(),
            "owner": (fm.get("owner") or "?").strip(),
            "parent": "" if parent.lower() in ("", "null", "none") else parent,
            "attn": (fm.get("needs_attention") or "false").lower().startswith("true"),
            "stake": (fm.get("stake") or "").strip(),
            "note": (fm.get("note") or "").strip(),
            "stale": (today - touched).days if touched else None,
        })
    return arcs


def _line(a: dict, depth: int) -> str:
    bits = [a["kind"], a["state"], f"owner={a['owner']}"]
    if a["attn"]:
        bits.append("**needs_attention**")
    stale = "undated" if a["stale"] is None else f"{a['stale']}d"
    name = f"**`{a['slug']}.md`**" if depth == 0 else f"`{a['slug']}.md`"
    head = f"{'  ' * depth}- {name} — {' · '.join(bits)} · {stale} stale"
    pad = "  " * depth
    if a["stake"]:
        stake = re.sub(r"\s+", " ", a["stake"]).strip().rstrip('"')
        if len(stake) > 150:
            stake = stake[:149].rsplit(" ", 1)[0] + "…"
        head += f"\n{pad}  {stake}"
    if a["note"]:
        head += f"\n{pad}  ↳ {re.sub(r'\s+', ' ', a['note']).strip()}"
    return head


def render(arcs: list[dict]) -> str:
    """Tree by parent, roots first; orphans (parent names no local file) surface flat."""
    slugs = {a["slug"] for a in arcs}
    kids: dict[str, list[dict]] = {}
    roots = []
    for a in arcs:
        (kids.setdefault(a["parent"], []) if a["parent"] in slugs else roots).append(a)

    def key(a):  # flagged first, then stalest, then name
        return (not a["attn"], -(a["stale"] or 0), a["slug"])

    out = []

    def emit(a: dict, depth: int):
        out.append(_line(a, depth))
        for k in sorted(kids.get(a["slug"], []), key=key):
            emit(k, depth + 1)

    for r in sorted(roots, key=key):
        emit(r, 0)

    flagged = sum(1 for a in arcs if a["attn"])
    return (
        f"<!-- RENDERED by scripts/arc_index.py on {dt.date.today().isoformat()} — "
        "do not hand-edit; edit the arc frontmatter instead. -->\n"
        f"**Currently active** ({len(arcs)} arcs on disk, {flagged} flagged needs_attention):\n\n"
        + "\n".join(out)
    )


# Splice boundaries for --write. The start marker is emitted by render() itself; the
# end marker is the hand-authored index-drift note that must survive a rewrite.
RENDER_MARKER = "<!-- RENDERED by scripts/arc_index.py"
END_MARKER = "> **Index-drift note"


def main():
    ap = argparse.ArgumentParser(description="Render the §VIII arc list from frontmatter.")
    ap.add_argument("--entity", default=None, help="entity name (default: $ENTITY_NAME, else lyra)")
    ap.add_argument("--check", action="store_true",
                    help="report arcs on disk that the entity's CLAUDE.md §VIII never mentions")
    ap.add_argument("--write", action="store_true",
                    help="splice the render into the entity's CLAUDE.md §VIII in place")
    args = ap.parse_args()

    arcs_dir = resolve_arcs_dir(args.entity)
    if not arcs_dir.is_dir():
        sys.exit(f"no arcs dir at {arcs_dir}")
    arcs = load(arcs_dir)

    if args.check:
        claude_md = arcs_dir.parent / "CLAUDE.md"
        if not claude_md.is_file():
            sys.exit(f"no CLAUDE.md at {claude_md}")
        text = claude_md.read_text(encoding="utf-8", errors="replace")
        missing = [a["slug"] for a in arcs if f"{a['slug']}.md" not in text]
        if missing:
            print("INDEX DRIFT — on disk but absent from CLAUDE.md §VIII:")
            for m in missing:
                print(f"  • {m}.md")
            sys.exit(1)
        print(f"§VIII mentions all {len(arcs)} arcs on disk.")
        return

    block = render(arcs)

    if not args.write:
        print(block)
        return

    # A render that has to be hand-pasted drifts -- which is the very failure this
    # script exists to kill (#327). Splice it in place instead.
    claude_md = arcs_dir.parent / "CLAUDE.md"
    if not claude_md.is_file():
        sys.exit(f"no CLAUDE.md at {claude_md}")
    text = claude_md.read_text(encoding="utf-8")

    start = text.find(RENDER_MARKER)
    if start == -1:
        sys.exit(f"no rendered block found in {claude_md} (looked for {RENDER_MARKER!r}).\n"
                 "Paste the render in once by hand, then --write keeps it current.")
    end = text.find(END_MARKER, start)
    if end == -1:
        sys.exit(f"found the render start but no {END_MARKER!r} terminator after it; "
                 "refusing to guess where the block ends.")

    new = text[:start] + block.rstrip("\n") + "\n\n" + text[end:]
    if new == text:
        print("§VIII already current — no change.")
        return
    claude_md.write_text(new, encoding="utf-8")
    print(f"§VIII rewritten in {claude_md} ({len(arcs)} arcs).")


if __name__ == "__main__":
    main()
