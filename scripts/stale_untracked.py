#!/usr/bin/env python3
"""Surface untracked files that have gone quietly stale.

Why this exists (2026-09-15). Caia wrote a Sextant axis vignette on 2026-06-09 with
"Awaiting Lyra's review" in its header and never committed it. It sat untracked for
98 days. Untracked is the one state that is invisible to *every* habit we have: it is
not in `git log`, not on the board, not in an arc, not in the ambient front-block. Both
of us walked past it daily. Neither of us was careless -- there was simply no surface on
which it could appear.

This is the missing surface. It reports untracked files by age, and flags the ones whose
first lines contain a hand-off marker ("awaiting X's review", TODO, DRAFT), because a
file that is *waiting on a person* and invisible is the expensive case.

Deliberately NOT printed: file contents. Only a matched marker phrase and the path.
Gitignored files never appear -- `git status --porcelain` excludes them by default, which
is what keeps entity data, .env secrets and runtime dirs out of this report.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

REPOS = [
    Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness"),
    Path("/mnt/c/Users/Jeff/Claude_Projects/sextant"),
]

# Hand-off markers: this file is waiting on a human/entity, not just unfinished.
HANDOFF = re.compile(
    r"(awaiting\s+(\w+)(?:'s)?\s+review|"
    r"\bfor\s+(\w+)\s+to\s+review\b|"
    r"\bTODO\b|\bFIXME\b|\bDRAFT\b|\bWIP\b)",
    re.IGNORECASE,
)
SCAN_BYTES = 4096          # only the head of a file; we are not reading anyone's work
SKIP_SUFFIXES = {".pyc", ".log", ".db", ".sqlite", ".png", ".jpg", ".jpeg", ".gif",
                 ".webp", ".mp4", ".wav", ".zip", ".tar", ".gz", ".bin", ".onnx"}


def untracked(repo: Path) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  (could not read {repo.name}: {exc})", file=sys.stderr)
        return []
    if out.returncode != 0:
        print(f"  (git failed in {repo.name}: {out.stderr.strip()})", file=sys.stderr)
        return []
    paths = []
    for line in out.stdout.splitlines():
        if not line.startswith("?? "):
            continue
        rel = line[3:].strip().strip('"')
        p = repo / rel
        # MUST be --untracked-files=all, not the default "normal". `normal` collapses
        # an untracked DIRECTORY to one entry, so old files inside a recently-created
        # dir are hidden and the dir's own fresh mtime filters the whole thing out.
        # Caught by the regression test below on first run: the scanner reported
        # "nothing is waiting invisibly" against a tree containing the exact case it
        # was written for -- a clean report produced by not looking.
        if p.is_file():
            paths.append(p)
    return paths


def age_days(p: Path) -> float:
    try:
        return (dt.datetime.now().timestamp() - p.stat().st_mtime) / 86400.0
    except OSError:
        return -1.0


def marker(p: Path) -> str | None:
    if p.is_dir() or p.suffix.lower() in SKIP_SUFFIXES:
        return None
    try:
        head = p.open("rb").read(SCAN_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return None
    # Leftmost-match is wrong here: "v0 draft" often precedes "Awaiting X's review" in a
    # header, and the review hand-off is the far more actionable signal. Rank instead.
    best = None
    for m in HANDOFF.finditer(head):
        txt = m.group(0).strip()
        rank = 0 if re.search(r"awaiting|to\s+review", txt, re.IGNORECASE) else 1
        if best is None or rank < best[0]:
            best = (rank, txt)
    return best[1] if best else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=float, default=14.0,
                    help="report untracked files older than this (default 14)")
    ap.add_argument("--all", action="store_true", help="ignore --days, show everything")
    a = ap.parse_args()

    rows = []
    for repo in REPOS:
        if not (repo / ".git").exists():
            continue
        for p in untracked(repo):
            d = age_days(p)
            if not a.all and d < a.days:
                continue
            rows.append((d, repo.name, p.relative_to(repo), marker(p)))

    if not rows:
        print(f"No untracked files older than {a.days:.0f}d. Nothing is waiting invisibly.")
        return 0

    rows.sort(key=lambda r: -r[0])
    waiting = [r for r in rows if r[3]]
    if waiting:
        print("⚠ UNTRACKED AND WAITING ON SOMEONE — invisible to every other scan:")
        for d, repo, p, mk in waiting:
            print(f"  • {d:5.0f}d  {repo}/{p}   [{mk}]")
        print()
    rest = [r for r in rows if not r[3]]
    if rest:
        print(f"Other untracked files ≥{a.days:.0f}d ({len(rest)}):")
        for d, repo, p, _ in rest[:20]:
            print(f"  · {d:5.0f}d  {repo}/{p}")
        if len(rest) > 20:
            print(f"    … and {len(rest) - 20} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
