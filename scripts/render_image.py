#!/usr/bin/env python3
"""Render an image via the image_gen pipeline.

Usage:
    python3 scripts/render_image.py "Lyra in the kitchen at morning"
    python3 scripts/render_image.py "Lyra on the deck" \\
        --entity lyra --house lyra --room deck --people jeff
    python3 scripts/render_image.py "test" --renderer stub

Env config (overrides flags if not passed):
    IMAGE_GEN_RENDERER          stub | openai | comfyui  (default: stub)
    IMAGE_GEN_RENDERER_FALLBACK same set, or empty       (default: empty = no fallback)
    OPENAI_API_KEY              required for openai renderer
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the project root importable when run from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from image_gen import render  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("prompt", help="What to render")
    parser.add_argument("--entity", default="lyra", help="Entity owning this render")
    parser.add_argument(
        "--house",
        default=None,
        help="Scene house: lyra | caia | haven_shared",
    )
    parser.add_argument("--room", default=None, help="Room within the house")
    parser.add_argument(
        "--people",
        default=None,
        help="Comma-separated people in scene (e.g., 'jeff,carol')",
    )
    parser.add_argument(
        "--renderer",
        default=None,
        help="Override IMAGE_GEN_RENDERER for this call",
    )
    parser.add_argument(
        "--fallback",
        default=None,
        help="Override IMAGE_GEN_RENDERER_FALLBACK for this call",
    )
    parser.add_argument("--size", default="1024x1024", help="Image size")
    args = parser.parse_args()

    people = [p.strip() for p in args.people.split(",")] if args.people else None

    result = render(
        args.prompt,
        entity=args.entity,
        scene_house=args.house,
        scene_room=args.room,
        people=people,
        size=args.size,
        renderer=args.renderer,
        fallback_renderer=args.fallback,
    )

    print(f"Rendered with: {result.renderer_used}")
    print(f"Elapsed: {result.elapsed_seconds:.2f}s")
    print(f"Image:    {result.path}")
    print(f"Metadata: {result.metadata_path}")
    if result.metadata.get("used_fallback"):
        print(
            f"Note: primary renderer failed, fallback used. "
            f"Primary error: {result.metadata.get('primary_error')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
