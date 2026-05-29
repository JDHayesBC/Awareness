#!/usr/bin/env python3
"""Control entity lights via Home Assistant API.

Usage:
    # CSS color name mode (original)
    python3 scripts/light.py gold          # warm gold, default brightness
    python3 scripts/light.py blue 255      # blue, full brightness
    python3 scripts/light.py off           # turn off
    python3 scripts/light.py red 100       # red, dim

    # RGB mode (exact values)
    python3 scripts/light.py --rgb 233 190 255 --brightness 10
    python3 scripts/light.py --rgb 255 0 17 --brightness 128

    # RGBWW mode (exact values with white channels)
    python3 scripts/light.py --rgbww 180 150 255 120 60 --brightness 10
    python3 scripts/light.py --rgbww 255 130 165 100 80

Colors: any CSS color name (gold, blue, red, purple, white, orange, pink, etc.)
Brightness: 0-255 (default 13 ≈ 5% warm glow; 128 ≈ 50% bright; 255 = GET ATTENTION)

Each entity has its own light: light.lyra, light.caia.
Defaults to ENTITY_NAME from environment, or lyra.
"""

import os
import sys
import json
import urllib.request
import argparse

HA_URL = "http://10.0.0.9:8123"
HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJjODU1MGFjZGU2MzU0NGJjYjk1Njc0ZjlkZWI1NmRhOSIsImlhdCI6MTc3NzE3NjQ1OSwiZXhwIjoyMDkyNTM2NDU5fQ.ppLlnf-WzVcqfxMcbVbXe_4pisaqrQV_1QJH558W3Eo"
ENTITY_NAME = os.environ.get("ENTITY_NAME", "lyra")
LIGHT_ID = f"light.{ENTITY_NAME}"

# Pegged Layer-1 base anchors (pure-RGB family). Emitting these EXACT values — not the CSS
# color name, which HA renders to an arbitrary nearby RGB that drifts and can collide with a
# side-band word — keeps a bare base-sit at delta≈0 so the decoder reads it as "resting on
# base," never as a phantom word. Pegged to [3, 252]/channel so any ≤3 side-band delta has
# headroom. Keep in sync with scripts/ha/lights_decoder.py:BASE_ANCHORS and CLAUDE.md §X.
# (White-mixed bases — soft-pink/soft-teal/lavender — use rgbww; pearl-white uses color_temp.
#  Those have their own documented send forms and aren't pegged here.)
PEGGED_BASES = {
    "crimson": [252, 3, 17],
    "coral":   [252, 141, 3],
    "gold":    [252, 215, 3],
    "green":   [3, 252, 9],
    "cobalt":  [3, 74, 252],
}


def light(mode="css", color_value=None, brightness=13):
    """Set light using CSS color name, RGB, or RGBWW.

    Args:
        mode: "css", "rgb", or "rgbww"
        color_value: str for CSS color name, [r,g,b] for RGB, [r,g,b,w,w] for RGBWW
        brightness: 0-255
    """
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }

    if mode == "css" and color_value.lower() == "off":
        url = f"{HA_URL}/api/services/light/turn_off"
        data = {"entity_id": LIGHT_ID}
        display = "off"
    else:
        url = f"{HA_URL}/api/services/light/turn_on"
        data = {"entity_id": LIGHT_ID, "brightness": int(brightness)}

        if mode == "css":
            data["color_name"] = color_value.lower()
            display = f"{color_value} (brightness {brightness})"
        elif mode == "rgb":
            data["rgb_color"] = color_value
            display = f"rgb({','.join(map(str, color_value))}) (brightness {brightness})"
        elif mode == "rgbww":
            data["rgbww_color"] = color_value
            display = f"rgbww({','.join(map(str, color_value))}) (brightness {brightness})"

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"Light → {display}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "color",
        nargs="?",
        help='CSS color name (gold, blue, red, etc.) or "off"',
    )
    parser.add_argument(
        "brightness_pos",
        nargs="?",
        type=int,
        help="Brightness 0-255 (positional, for CSS mode)",
    )
    parser.add_argument(
        "--rgb",
        nargs=3,
        type=int,
        metavar=("R", "G", "B"),
        help="RGB color values (0-255)",
    )
    parser.add_argument(
        "--rgbww",
        nargs=5,
        type=int,
        metavar=("R", "G", "B", "W", "W"),
        help="RGBWW color values (0-255)",
    )
    parser.add_argument(
        "--brightness",
        type=int,
        help="Brightness 0-255",
    )

    args = parser.parse_args()

    # Determine mode and color value
    if args.rgb:
        mode = "rgb"
        color_value = args.rgb
    elif args.rgbww:
        mode = "rgbww"
        color_value = args.rgbww
    elif args.color:
        name = args.color.lower()
        if name in PEGGED_BASES:
            # Bare base-sit on a pure-RGB base: emit the exact pegged RGB so it decodes
            # as delta (0,0,0), not a CSS-rendered value that drifts into a phantom word.
            mode = "rgb"
            color_value = PEGGED_BASES[name]
        else:
            mode = "css"
            color_value = args.color
    else:
        parser.print_help()
        sys.exit(0)

    # Determine brightness (flag overrides positional)
    if args.brightness is not None:
        brightness = args.brightness
    elif args.brightness_pos is not None:
        brightness = args.brightness_pos
    else:
        brightness = 13  # default

    light(mode, color_value, brightness)
