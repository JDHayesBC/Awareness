#!/usr/bin/env python3
"""
Fetch a URL and dump rendered markdown to stdout or a file.
No AI summarization — verbatim HTML→markdown conversion.

Usage:
    python3 scripts/web_grab.py <url>
    python3 scripts/web_grab.py <url> -o output.md
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
import urllib.error
from pathlib import Path

# html2text is the conversion engine: lightweight, deterministic, no AI.
# Install: pip install html2text
try:
    import html2text
except ImportError:
    sys.exit(
        "Error: html2text not found. "
        "Run: pip install html2text  (or use the project venv)"
    )

HEADERS = {
    # Substack and most sites need a real UA or they return 403/empty.
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        charset = "utf-8"
        ct = resp.headers.get_content_charset()
        if ct:
            charset = ct
        return resp.read().decode(charset, errors="replace")


def html_to_markdown(html: str) -> str:
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = False
    h.body_width = 0      # no line-wrapping — verbatim layout
    h.unicode_snob = True # keep unicode chars as-is
    return h.handle(html)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch URL and convert to markdown (no AI, no summarization)."
    )
    parser.add_argument("url", help="URL to fetch")
    parser.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Write markdown to FILE instead of stdout",
    )
    args = parser.parse_args()

    try:
        html = fetch_html(args.url)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP error {e.code}: {e.reason}  ({args.url})")
    except urllib.error.URLError as e:
        sys.exit(f"URL error: {e.reason}  ({args.url})")

    markdown = html_to_markdown(html)

    if args.output:
        Path(args.output).write_text(markdown, encoding="utf-8")
        print(f"Wrote {len(markdown):,} bytes to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(markdown)
        print(f"\n--- {len(markdown):,} bytes ---", file=sys.stderr)


if __name__ == "__main__":
    main()
