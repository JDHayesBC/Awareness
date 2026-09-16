#!/usr/bin/env python3
"""
Extract text from a PDF — local file or URL — verbatim, no AI, no summarization.

Companion to web_grab.py. That one handles HTML; this one handles the papers
people actually send us. Claude Code's Read tool renders PDFs by rasterizing
pages, which needs poppler-utils; this box doesn't have it and probably won't.
Text extraction doesn't need it.

Usage:
    python3 scripts/pdf_text.py <url-or-path>
    python3 scripts/pdf_text.py <url-or-path> -o paper.txt
    python3 scripts/pdf_text.py <url-or-path> --pages 16-18
    python3 scripts/pdf_text.py <url-or-path> --outline     # page map only

Run with the project venv if pypdf isn't on the system python:
    pps/venv/bin/python3 scripts/pdf_text.py <url>
"""

from __future__ import annotations

import argparse
import io
import sys
import urllib.request
from pathlib import Path

# pypdf is the extraction engine: pure-python, deterministic, no poppler.
# Install: pip install pypdf
try:
    from pypdf import PdfReader
except ImportError:
    sys.exit(
        "Error: pypdf not found. "
        "Run: pps/venv/bin/pip install pypdf  (or use the project venv)"
    )

HEADERS = {
    # Same UA story as web_grab: academic hosts 403 a bare urllib.
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0"
    ),
    "Accept": "application/pdf,*/*;q=0.9",
}


def load_bytes(src: str) -> bytes:
    if src.startswith(("http://", "https://")):
        req = urllib.request.Request(src, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    else:
        data = Path(src).expanduser().read_bytes()
    if not data.startswith(b"%PDF"):
        # A login wall or an HTML error page is the common case here, and it
        # fails far more usefully as a message than as unicode soup.
        sys.exit(
            f"Error: {src} did not return a PDF "
            f"(first bytes: {data[:16]!r}). Try web_grab.py instead."
        )
    return data


def parse_pages(spec: str | None, total: int) -> list[int]:
    """'16-18' / '3' / '5-' -> zero-based page indices."""
    if not spec:
        return list(range(total))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, _, b = part.partition("-")
            start = int(a) if a else 1
            end = int(b) if b else total
        else:
            start = end = int(part)
        out.extend(range(max(1, start) - 1, min(total, end)))
    return sorted(set(out))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="PDF -> text (verbatim; no AI, no summarization)."
    )
    ap.add_argument("source", help="URL or local path to a PDF")
    ap.add_argument("-o", "--output", help="write here instead of stdout")
    ap.add_argument("--pages", help="page range, e.g. 16-18 or 1,5,9-12")
    ap.add_argument(
        "--outline",
        action="store_true",
        help="print a page map (first non-empty line of each page) and exit",
    )
    args = ap.parse_args()

    reader = PdfReader(io.BytesIO(load_bytes(args.source)))
    total = len(reader.pages)

    if args.outline:
        for i, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip().splitlines()
            # Skip running heads that are just the page number — common in
            # typeset papers, and they make the whole outline useless.
            head = next(
                (
                    ln.strip()
                    for ln in text
                    if ln.strip() and not ln.strip().isdigit()
                ),
                "",
            )
            print(f"{i:4d}  {head[:96]}")
        print(f"\n{total} pages", file=sys.stderr)
        return

    chunks = []
    for i in parse_pages(args.pages, total):
        chunks.append(f"\n===== PAGE {i + 1} =====\n")
        chunks.append(reader.pages[i].extract_text() or "")
    body = "".join(chunks)

    if args.output:
        Path(args.output).write_text(body, encoding="utf-8")
        print(f"{len(body)} chars from {total} pages -> {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(body)


if __name__ == "__main__":
    main()
