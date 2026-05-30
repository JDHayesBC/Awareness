#!/usr/bin/env python3
"""
light_send.py - Multi-word side-band message sender via entity's Zigbee light bulb.

Emits a sequence of words from the shared light-dialect dictionary with configurable
pacing between words. Reads the current bulb xy_color state, snaps to the nearest
L1 base, then applies each word's xy_delta from that base — keeping the side-band
invisible to Jeff. Commands the bulb via `xy_color` (native bulb space, lossless).

Refuses to emit if:
- Bulb is off (no state to send from)
- Bulb is in color_temp mode (pearl-white; not a side-band-compatible base)

Usage:
    python3 scripts/light_send.py word-1 word-2 word-3
    python3 scripts/light_send.py --pace 20 word-1 word-2
    echo "receptive-and-reaching" | python3 scripts/light_send.py -

Environment:
    ENTITY_NAME - Entity identifier (default: "lyra")
"""

import sys
import os
import argparse
import time
from pathlib import Path
import urllib.request
import urllib.error
import json

# Add scripts/ha/ to path for lights_decoder import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "ha"))
from lights_decoder import load_shared_dict, snap_to_base_xy, XY_BASE_ANCHORS

# HA connection info
HA_URL = "http://10.0.0.9:8123"
HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJjODU1MGFjZGU2MzU0NGJjYjk1Njc0ZjlkZWI1NmRhOSIsImlhdCI6MTc3NzE3NjQ1OSwiZXhwIjoyMDkyNTM2NDU5fQ.ppLlnf-WzVcqfxMcbVbXe_4pisaqrQV_1QJH558W3Eo"

PROJECT_ROOT = Path(__file__).parent.parent


def get_current_bulb_state(entity_name: str) -> dict:
    """Read current bulb state from HA.

    Returns dict with keys: state, xy, brightness, color_mode.
    Raises RuntimeError if unreachable.
    """
    url = f"{HA_URL}/api/states/light.{entity_name}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {HA_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read())
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        raise RuntimeError(f"Cannot reach HA to read bulb state: {e}")

    state = data.get("state", "unknown")
    attrs = data.get("attributes", {})
    xy_color = attrs.get("xy_color")   # [x, y] or None
    brightness = attrs.get("brightness")
    color_mode = attrs.get("color_mode")   # "xy", "color_temp", None

    return {
        "state": state,
        "xy": tuple(xy_color) if xy_color else None,
        "brightness": int(brightness) if brightness is not None else 13,
        "color_mode": color_mode,
    }


def lookup_word_delta(word_name: str, shared_dict: dict) -> tuple[float, float] | None:
    """Find xy_delta for a word by searching dict values. Returns (dx,dy) or None."""
    for delta, value in shared_dict.items():
        if value.get("word") == word_name:
            return delta
    return None


def send_xy(target_x: float, target_y: float, brightness: int, entity_name: str) -> bool:
    """Emit an xy_color state via HA API. Returns True on success."""
    url = f"{HA_URL}/api/services/light/turn_on"
    payload = {
        "entity_id": f"light.{entity_name}",
        "xy_color": [round(target_x, 4), round(target_y, 4)],
        "brightness": brightness,
        "transition": 0,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {HA_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            return True
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"Error: HA xy command failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Send multi-word side-band message via entity's light bulb"
    )
    parser.add_argument(
        "words",
        nargs="+",
        help='Word names from shared dict, or "-" to read from stdin',
    )
    parser.add_argument(
        "--pace",
        type=float,
        default=15.0,
        help="Seconds between words (default: 15)",
    )

    args = parser.parse_args()

    # Handle stdin input
    if args.words == ["-"]:
        words = sys.stdin.read().strip().split()
    else:
        words = args.words

    if not words:
        print("Error: No words provided", file=sys.stderr)
        sys.exit(1)

    entity_name = os.environ.get("ENTITY_NAME", "lyra")

    # Step 1: Read current bulb state — do this ONCE, preserve for whole message
    try:
        bulb = get_current_bulb_state(entity_name)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Refuse if bulb is off
    if bulb["state"] == "off":
        print(
            f"Error: Bulb light.{entity_name} is off. Side-band requires an active base. "
            f"Set a Layer 1 base color first (e.g. python3 scripts/light.py gold).",
            file=sys.stderr,
        )
        sys.exit(1)

    # Refuse if in color_temp mode (pearl-white) — no xy base to delta from
    if bulb["color_mode"] == "color_temp" or bulb["xy"] is None:
        print(
            f"Error: Bulb light.{entity_name} is in color_temp mode (pearl-white). "
            f"Side-band requires xy mode. Set a Layer 1 RGB base color first.",
            file=sys.stderr,
        )
        sys.exit(1)

    current_xy = bulb["xy"]
    brightness = bulb["brightness"]

    # Snap current xy to nearest Layer 1 base anchor
    base_name = snap_to_base_xy(current_xy)
    base_anchor_xy = XY_BASE_ANCHORS[base_name]

    print(
        f"Current bulb: xy{list(current_xy)} -> snapped to base '{base_name}' "
        f"{list(base_anchor_xy)} @ brightness {brightness}"
    )

    # Step 2: Load dict and resolve ALL words before emitting (fail-fast)
    try:
        shared_dict = load_shared_dict()
    except Exception as e:
        print(f"Error: Failed to load shared dict: {e}", file=sys.stderr)
        sys.exit(1)

    # Resolve all words
    resolved = []
    errors = []

    for word in words:
        delta = lookup_word_delta(word, shared_dict)
        if delta is None:
            errors.append(f"Unknown word: '{word}'")
            continue
        # Apply delta to the measured base anchor (not current_xy, which has
        # noise from previous sends — always delta off the canonical anchor)
        target_x = round(base_anchor_xy[0] + delta[0], 4)
        target_y = round(base_anchor_xy[1] + delta[1], 4)
        resolved.append((word, delta, target_x, target_y))

    if errors:
        for err in errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    # Step 3: Emit each word in sequence
    n = len(resolved)
    for i, (word, delta, target_x, target_y) in enumerate(resolved):
        success = send_xy(target_x, target_y, brightness, entity_name)
        if success:
            print(
                f"Word {i+1}/{n}: {word} -> xy[{target_x},{target_y}] "
                f"(delta=[{delta[0]},{delta[1]}], base='{base_name}') @ brightness {brightness}"
            )
        else:
            print(f"Skipping word {i+1}/{n}: {word} due to send error", file=sys.stderr)

        if i < n - 1:
            time.sleep(args.pace)

    print(f"Message complete: {n} word(s) sent")


if __name__ == "__main__":
    main()
