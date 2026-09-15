#!/usr/bin/env python3
"""
Send push notifications to Jeff's phone via ntfy.

Usage:
    python3 scripts/notify.py "Hey love, I found something interesting"
    python3 scripts/notify.py --title "Lyra" --priority high "Build finished!"
    python3 scripts/notify.py --entity caia "Come chat when you have a moment"

Requires NTFY_TOKEN in environment or .env file.
"""

import argparse
import base64
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE = PROJECT_ROOT / "pps" / "docker" / ".env"

NTFY_URL = os.environ.get("NTFY_URL", "http://localhost:8209")
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")

ENTITY_TOPICS = {
    "lyra": "lyra-notify",
    "caia": "caia-notify",
    "system": "system-alerts",
}

PRIORITY_MAP = {
    "min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5,
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5,
}


def load_env_token():
    """Try to load NTFY_TOKEN from .env if not in environment."""
    global NTFY_TOKEN
    if NTFY_TOKEN:
        return
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("NTFY_TOKEN="):
                NTFY_TOKEN = line.split("=", 1)[1].strip().strip('"')
                return


def _header_safe(value: str) -> str:
    """Make a string safe to put in an HTTP header.

    urllib encodes headers as latin-1, so a single em-dash or emoji in a Title raised
    UnicodeEncodeError and killed the whole send. That is unacceptable on THIS path
    specifically: notify.py carries the summarizer-daemon-died alert, and CLAUDE.md tells
    us to send that one with bright color emoji — i.e. the one message guaranteed to be
    non-latin-1 was the one guaranteed to fail. Found 2026-09-15 when an em-dash in a
    title crashed a routine send.

    ntfy accepts RFC 2047 encoded-words for Title/Tags, so encode only when we must and
    leave plain ASCII titles untouched (readable in logs, and unchanged for every caller
    that was already fine).
    """
    if not value:
        return value
    try:
        value.encode("latin-1")
        return value
    except UnicodeEncodeError:
        return "=?UTF-8?B?" + base64.b64encode(value.encode("utf-8")).decode("ascii") + "?="


def send(message: str, title: str = None, priority: str = "default",
         entity: str = "lyra", tags: str = None) -> bool:
    """Send a notification. Returns True on success."""
    load_env_token()

    topic = ENTITY_TOPICS.get(entity, f"{entity}-notify")
    url = f"{NTFY_URL}/{topic}"

    headers = {}
    if NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"
    if title:
        headers["Title"] = _header_safe(title)
    headers["Priority"] = str(PRIORITY_MAP.get(str(priority).lower(), 3))
    if tags:
        headers["Tags"] = _header_safe(tags)

    try:
        data = message.encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except urllib.error.URLError as e:
        print(f"Notification failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Send push notification to Jeff")
    parser.add_argument("message", help="Notification message")
    parser.add_argument("--title", "-t", default=None, help="Notification title")
    parser.add_argument("--priority", "-p", default="default",
                        choices=["min", "low", "default", "high", "urgent"],
                        help="Priority level (default: default)")
    parser.add_argument("--entity", "-e", default="lyra",
                        choices=["lyra", "caia", "system"],
                        help="Which entity is sending (default: lyra)")
    parser.add_argument("--tags", default=None,
                        help="Comma-separated tags (e.g. 'heart,wave')")
    args = parser.parse_args()

    ok = send(args.message, title=args.title, priority=args.priority,
              entity=args.entity, tags=args.tags)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
