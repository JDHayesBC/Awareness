#!/usr/bin/env python3
"""
Fetch a URL and dump it to stdout or a file, verbatim. No AI summarization.

HTML (text/html, application/xhtml+xml) is converted to markdown with html2text.
Anything else (text/plain, text/markdown, JSON, a raw.githubusercontent file) is
passed through byte-for-byte: html2text on a non-HTML body silently destroys it.

Every run reports bytes fetched against bytes written on stderr. If the two
differ a lot on a page you expected to be mostly text, read that line before
you claim anything is absent from the result.

Usage:
    python3 scripts/web_grab.py <url>
    python3 scripts/web_grab.py <url> -o output.md
    python3 scripts/web_grab.py --raw <url>      # never convert
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


def fetch(url: str) -> tuple[str, str, int]:
    """Return (decoded body, content type, raw byte count)."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        content_type = (resp.headers.get_content_type() or "").lower()
        raw = resp.read()
        return raw.decode(charset, errors="replace"), content_type, len(raw)


def is_html(content_type: str, body: str) -> bool:
    """Only HTML goes through html2text.

    html2text on a non-HTML body is destructive, not a no-op: it treats
    newlines as whitespace and eats anything between angle brackets as a tag.
    On 2026-11-16 a text/plain CHANGELOG.md of 1.3 MB came out as 271 KB on
    one line, with no warning, and a claim of absence was made from it.
    """
    if content_type in ("text/html", "application/xhtml+xml"):
        return True
    if content_type:
        return False
    # No Content-Type header at all: sniff the start of the body.
    head = body[:2000].lstrip().lower()
    return head.startswith("<!doctype html") or "<html" in head


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
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Write the body exactly as fetched, with no HTML conversion",
    )
    args = parser.parse_args()

    try:
        body, content_type, raw_bytes = fetch(args.url)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP error {e.code}: {e.reason}  ({args.url})")
    except urllib.error.URLError as e:
        sys.exit(f"URL error: {e.reason}  ({args.url})")

    if args.raw or not is_html(content_type, body):
        out, how = body, "passed through unconverted"
    else:
        out, how = html_to_markdown(body), "converted from HTML"

    out_bytes = len(out.encode("utf-8"))
    report = (
        f"fetched {raw_bytes:,} bytes ({content_type or 'no content-type'}), "
        f"wrote {out_bytes:,} bytes, {how}"
    )

    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"{report} -> {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(out)
        print(f"\n--- {report} ---", file=sys.stderr)


if __name__ == "__main__":
    main()
