#!/usr/bin/env python3
"""Home Assistant light interface — base abstraction.

Wraps HA's light.turn_on/turn_off API for entity-specific lights.
Used by light.py (CLI) and animation scripts (light_breathe.py, etc.).

Functions:
    set_light(color=, rgb=, brightness=, transition=, entity=)
    turn_off(transition=, entity=)

Defaults to ENTITY_NAME from environment, or 'lyra'.
"""

import os
import json
import urllib.request

HA_URL = "http://10.0.0.9:8123"
HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJjODU1MGFjZGU2MzU0NGJjYjk1Njc0ZjlkZWI1NmRhOSIsImlhdCI6MTc3NzE3NjQ1OSwiZXhwIjoyMDkyNTM2NDU5fQ.ppLlnf-WzVcqfxMcbVbXe_4pisaqrQV_1QJH558W3Eo"
DEFAULT_ENTITY = os.environ.get("ENTITY_NAME", "lyra")


def _light_id(entity=None):
    return f"light.{entity or DEFAULT_ENTITY}"


def _post(path, data):
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        f"{HA_URL}{path}",
        data=json.dumps(data).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status


def set_light(color=None, rgb=None, brightness=None, transition=None, entity=None):
    """Set the entity's light state.

    color: CSS color name ("gold", "blue", etc.)
    rgb: (r, g, b) tuple 0-255 — takes precedence over color
    brightness: 0-255
    transition: fade duration in seconds (float)
    entity: light entity name (defaults to ENTITY_NAME env)
    """
    data = {"entity_id": _light_id(entity)}
    if rgb is not None:
        data["rgb_color"] = list(rgb)
    elif color is not None:
        data["color_name"] = color.lower()
    if brightness is not None:
        data["brightness"] = int(brightness)
    if transition is not None:
        data["transition"] = float(transition)
    return _post("/api/services/light/turn_on", data)


def turn_off(transition=None, entity=None):
    """Turn the light off, optionally with fade."""
    data = {"entity_id": _light_id(entity)}
    if transition is not None:
        data["transition"] = float(transition)
    return _post("/api/services/light/turn_off", data)
