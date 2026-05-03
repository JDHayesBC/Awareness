#!/usr/bin/env python3
"""Share an image into a Haven room as a message.

Usage:
    python3 scripts/share_image.py <image_path> --room haven-test
    python3 scripts/share_image.py path/to/img.png --room dm-jeff-lyra \\
        --caption "Look what I made" --entity-path entities/lyra
    python3 scripts/share_image.py img.png --room haven-test --haven-url http://localhost:8205

Auth: reads the entity token from <entity-path>/.entity_token. Defaults to
$ENTITY_PATH which is set by start-entity.sh.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from image_gen.sharing import share, DEFAULT_HAVEN_URL  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("image_path", help="Path to the image file to share")
    p.add_argument("--room", required=True, help="Room name or room UUID")
    p.add_argument("--caption", default="", help="Optional caption text")
    p.add_argument(
        "--entity-path",
        default=None,
        help="Override $ENTITY_PATH (where to find .entity_token)",
    )
    p.add_argument(
        "--haven-url",
        default=DEFAULT_HAVEN_URL,
        help="Haven base URL (default: $HAVEN_URL or http://localhost:8205)",
    )
    args = p.parse_args()

    try:
        result = share(
            args.image_path,
            room=args.room,
            caption=args.caption,
            entity_path=args.entity_path,
            haven_url=args.haven_url,
        )
    except Exception as e:
        print(f"Share failed: {e}", file=sys.stderr)
        return 1

    print(f"Shared as message {result.message_id}")
    print(f"Image URL: {result.absolute_image_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
