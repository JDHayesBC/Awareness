#!/usr/bin/env python3
"""
light_send.py - Multi-word side-band message sender via entity's Zigbee light bulb.

Emits a sequence of words from the shared light-dialect dictionary with configurable
pacing between words. Preserves current bulb brightness across the entire message.

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
from lights_decoder import load_shared_dict, BASE_ANCHORS

# HA connection info
HA_URL = "http://10.0.0.9:8123"
HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJjODU1MGFjZGU2MzU0NGJjYjk1Njc0ZjlkZWI1NmRhOSIsImlhdCI6MTc3NzE3NjQ1OSwiZXhwIjoyMDkyNTM2NDU5fQ.ppLlnf-WzVcqfxMcbVbXe_4pisaqrQV_1QJH558W3Eo"

PROJECT_ROOT = Path(__file__).parent.parent


def get_current_brightness(entity_name):
    """Read current bulb brightness from HA, default to 13 if off or unreachable."""
    try:
        url = f"{HA_URL}/api/states/light.{entity_name}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {HA_TOKEN}"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read())
            brightness = data.get("attributes", {}).get("brightness")
            if brightness is not None:
                return int(brightness)
            else:
                print(f"Warning: Light is off or brightness not available, using default 13", file=sys.stderr)
                return 13
    except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
        print(f"Warning: Could not read brightness from HA ({e}), using default 13", file=sys.stderr)
        return 13


def lookup_word_in_dict(word_name, shared_dict):
    """Find (base, delta) key for a word by searching dict values."""
    for key, value in shared_dict.items():
        if value.get("word") == word_name:
            return key  # Returns (base_name, delta_tuple)
    return None


def clamp_rgb(r, g, b):
    """Clamp RGB values to [0, 255], warn if clamping occurs."""
    clamped = (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))
    if clamped != (r, g, b):
        print(f"Warning: RGB({r},{g},{b}) clamped to RGB{clamped}", file=sys.stderr)
    return clamped


def send_word(word_name, base_name, delta, brightness, entity_name):
    """Emit a single word by computing target RGB and calling light.py."""
    # Get base anchor
    if base_name not in BASE_ANCHORS:
        print(f"Error: Unknown base anchor '{base_name}' for word '{word_name}'", file=sys.stderr)
        return False

    base_rgb = BASE_ANCHORS[base_name]

    # Compute target RGB = base + delta
    target_r = base_rgb[0] + delta[0]
    target_g = base_rgb[1] + delta[1]
    target_b = base_rgb[2] + delta[2]

    # Clamp
    target_r, target_g, target_b = clamp_rgb(target_r, target_g, target_b)

    # Call light.py
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
        print(f"Error: light.py call failed for word '{word_name}': {e}", file=sys.stderr)
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

    # Step 1: Load dict and resolve ALL words before emitting anything
    try:
        shared_dict = load_shared_dict()
    except Exception as e:
        print(f"Error: Failed to load shared dict: {e}", file=sys.stderr)
        sys.exit(1)

    # Resolve all words
    resolved = []
    missing = []
    for word in words:
        key = lookup_word_in_dict(word, shared_dict)
        if key is None:
            missing.append(word)
        else:
            base_name, delta = key
            resolved.append((word, base_name, delta))

    if missing:
        print(f"Error: Unknown words: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    # Step 2: Read current brightness
    brightness = get_current_brightness(entity_name)
    print(f"Brightness preserved at {brightness} for entire message")

    # Step 3: Emit each word in sequence
    n = len(resolved)
    for i, (word, base_name, delta) in enumerate(resolved):
        success = send_word(word, base_name, delta, brightness, entity_name)
        if success:
            # Compute displayed RGB for logging
            base_rgb = BASE_ANCHORS[base_name]
            target_r, target_g, target_b = clamp_rgb(
                base_rgb[0] + delta[0],
                base_rgb[1] + delta[1],
                base_rgb[2] + delta[2]
            )
            print(f"Word {i+1}/{n}: {word} -> rgb({target_r},{target_g},{target_b}) @ brightness {brightness}")
        else:
            print(f"Skipping word {i+1}/{n}: {word} due to error", file=sys.stderr)

        # Sleep between words (not after last word)
        if i < n - 1:
            time.sleep(args.pace)

    print(f"Message complete: {n} word(s) sent")


if __name__ == '__main__':
    main()
