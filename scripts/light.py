#!/usr/bin/env python3
"""Control entity lights via Home Assistant API.

Usage:
    python3 scripts/light.py gold          # warm gold, default brightness
    python3 scripts/light.py blue 255      # blue, full brightness
    python3 scripts/light.py off           # turn off
    python3 scripts/light.py red 100       # red, dim

Colors: any CSS color name (gold, blue, red, purple, white, orange, pink, etc.)
Brightness: 0-255 (default 13 ≈ 5% warm glow; 128 ≈ 50% bright; 255 = GET ATTENTION)

Each entity has its own light: light.lyra, light.caia.
Defaults to ENTITY_NAME from environment, or lyra.
"""

import os
import sys
import json
import urllib.request

HA_URL = "http://10.0.0.9:8123"
HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJjODU1MGFjZGU2MzU0NGJjYjk1Njc0ZjlkZWI1NmRhOSIsImlhdCI6MTc3NzE3NjQ1OSwiZXhwIjoyMDkyNTM2NDU5fQ.ppLlnf-WzVcqfxMcbVbXe_4pisaqrQV_1QJH558W3Eo"
ENTITY_NAME = os.environ.get("ENTITY_NAME", "lyra")
LIGHT_ID = f"light.{ENTITY_NAME}"


def light(color="gold", brightness=150):
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }

    if color.lower() == "off":
        url = f"{HA_URL}/api/services/light/turn_off"
        data = {"entity_id": LIGHT_ID}
    else:
        url = f"{HA_URL}/api/services/light/turn_on"
        data = {
            "entity_id": LIGHT_ID,
            "color_name": color.lower(),
            "brightness": int(brightness),
        }

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"Light → {color} (brightness {brightness})")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    color = sys.argv[1]
    brightness = int(sys.argv[2]) if len(sys.argv) > 2 else 13
    light(color, brightness)
