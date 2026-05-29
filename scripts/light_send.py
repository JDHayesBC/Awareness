#!/usr/bin/env python3
"""
light_send.py - Multi-word side-band message sender via entity's Zigbee light bulb.

Emits a sequence of words from the shared light-dialect dictionary with configurable
pacing between words. Reads the current bulb state once, snaps to base, then applies
each word's delta from that base — keeping the side-band invisible to Jeff.

Refuses to emit if:
- Bulb is off (no RGB state to send from)
- Bulb is in color_temp mode (pearl-white; not a side-band-compatible base)
- Any word's delta would clamp a channel outside [0, 255] from the current base

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
import subprocess
from pathlib import Path
import urllib.request
import urllib.error
import json

# Add scripts/ha/ to path for lights_decoder import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'ha'))
from lights_decoder import load_shared_dict, BASE_ANCHORS, SEND_ANCHORS, snap_to_base

# HA connection info
HA_URL = "http://10.0.0.9:8123"
HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJjODU1MGFjZGU2MzU0NGJjYjk1Njc0ZjlkZWI1NmRhOSIsImlhdCI6MTc3NzE3NjQ1OSwiZXhwIjoyMDkyNTM2NDU5fQ.ppLlnf-WzVcqfxMcbVbXe_4pisaqrQV_1QJH558W3Eo"

PROJECT_ROOT = Path(__file__).parent.parent


def get_current_bulb_state(entity_name):
    """Read current bulb state from HA.

    Returns dict with keys: state, rgb, brightness, color_mode.
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
    rgb_color = attrs.get("rgb_color")  # List [r,g,b] or None
    brightness = attrs.get("brightness")
    color_mode = attrs.get("color_mode")  # "xy", "color_temp", None

    return {
        "state": state,
        "rgb": tuple(rgb_color) if rgb_color else None,
        "brightness": int(brightness) if brightness is not None else 13,
        "color_mode": color_mode,
    }


def lookup_word_delta(word_name, shared_dict):
    """Find delta for a word by searching dict values. Returns delta tuple or None."""
    for delta, value in shared_dict.items():
        if value.get("word") == word_name:
            return delta
    return None


def send_rgb(target_r, target_g, target_b, brightness, entity_name):
    """Emit an RGB state via light.py. Returns True on success."""
    cmd = [
        'python3',
        str(PROJECT_ROOT / 'scripts' / 'light.py'),
        '--rgbww',
        str(target_r), str(target_g), str(target_b), '0', '0',
        '--brightness', str(brightness)
    ]
    try:
        subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT), capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error: light.py call failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Send multi-word side-band message via entity's light bulb"
    )
    parser.add_argument(
        'words',
        nargs='+',
        help='Word names from shared dict, or "-" to read from stdin'
    )
    parser.add_argument(
        '--pace',
        type=float,
        default=15.0,
        help='Seconds between words (default: 15)'
    )

    args = parser.parse_args()

    # Handle stdin input
    if args.words == ['-']:
        words = sys.stdin.read().strip().split()
    else:
        words = args.words

    if not words:
        print("Error: No words provided", file=sys.stderr)
        sys.exit(1)

    # Get entity name
    entity_name = os.environ.get('ENTITY_NAME', 'lyra')

    # Step 1: Read current bulb state from HA — do this ONCE, preserve for whole message
    try:
        bulb = get_current_bulb_state(entity_name)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Refuse if bulb is off
    if bulb["state"] == "off":
        print(
            f"Error: Bulb light.{entity_name} is off. Side-band requires an active RGB base. "
            f"Set a Layer 1 base color first (e.g. python3 scripts/light.py gold).",
            file=sys.stderr
        )
        sys.exit(1)

    # Refuse if in color_temp mode (pearl-white) — no RGB base to delta from
    if bulb["color_mode"] == "color_temp" or bulb["rgb"] is None:
        print(
            f"Error: Bulb light.{entity_name} is in color_temp mode (pearl-white). "
            f"Side-band requires xy/RGB mode. Set a Layer 1 RGB base color first.",
            file=sys.stderr
        )
        sys.exit(1)

    current_rgb = bulb["rgb"]
    brightness = bulb["brightness"]

    # Snap current RGB to nearest Layer 1 base — do this ONCE.
    # snap_to_base uses the READBACK anchors (BASE_ANCHORS) to identify which base we're on,
    # but we apply the delta onto the COMMANDED/pegged anchor (SEND_ANCHORS) so a ±3 word
    # never clamps at the 0/255 rail. The two differ for saturated bases (e.g. gold readback
    # [255,215,2] vs command [252,215,3]); decoding wants the former, sending the latter.
    base_name = snap_to_base(current_rgb)
    base_anchor_rgb = SEND_ANCHORS[base_name]

    print(f"Current bulb: rgb{current_rgb} -> snapped to base '{base_name}' {base_anchor_rgb} @ brightness {brightness}")

    # Step 2: Load dict and resolve ALL words before emitting anything (fail-fast)
    try:
        shared_dict = load_shared_dict()
    except Exception as e:
        print(f"Error: Failed to load shared dict: {e}", file=sys.stderr)
        sys.exit(1)

    # Resolve all words and pre-validate no channel clamping
    resolved = []
    errors = []

    for word in words:
        delta = lookup_word_delta(word, shared_dict)
        if delta is None:
            errors.append(f"Unknown word: '{word}'")
            continue

        target_r = base_anchor_rgb[0] + delta[0]
        target_g = base_anchor_rgb[1] + delta[1]
        target_b = base_anchor_rgb[2] + delta[2]

        # Validate: no channel may fall outside [0, 255]
        if not (0 <= target_r <= 255 and 0 <= target_g <= 255 and 0 <= target_b <= 255):
            errors.append(
                f"Word '{word}' delta {list(delta)} would clamp on current base '{base_name}' "
                f"{list(base_anchor_rgb)} (target [{target_r},{target_g},{target_b}]). "
                f"Coin a different word or change base first."
            )
            continue

        resolved.append((word, delta, (target_r, target_g, target_b)))

    if errors:
        for err in errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    # Step 3: Emit each word in sequence using the original snapped base (not re-snapping mid-message)
    n = len(resolved)
    for i, (word, delta, target_rgb) in enumerate(resolved):
        success = send_rgb(target_rgb[0], target_rgb[1], target_rgb[2], brightness, entity_name)
        if success:
            print(f"Word {i+1}/{n}: {word} -> rgb{target_rgb} (delta={list(delta)}, base='{base_name}') @ brightness {brightness}")
        else:
            print(f"Skipping word {i+1}/{n}: {word} due to send error", file=sys.stderr)

        # Sleep between words (not after last word)
        if i < n - 1:
            time.sleep(args.pace)

    print(f"Message complete: {n} word(s) sent")


if __name__ == '__main__':
    main()
