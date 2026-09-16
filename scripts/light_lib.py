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
import sys
import json
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HA_URL = "http://10.0.0.50:8123"
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


def _journal(mode, values, brightness, entity, note=""):
    """Record to the light journal. Never raises — the bulb always wins."""
    try:
        from light_journal import record
        record(mode=mode, values=values, brightness=brightness,
               entity=entity or DEFAULT_ENTITY, source="light_lib.py", note=note)
    except Exception:
        pass


def set_light(color=None, rgb=None, brightness=None, transition=None, entity=None,
              journal=True, journal_note=""):
    """Set the entity's light state.

    color: CSS color name ("gold", "blue", etc.)
    rgb: (r, g, b) tuple 0-255 — takes precedence over color
    brightness: 0-255
    transition: fade duration in seconds (float)
    entity: light entity name (defaults to ENTITY_NAME env)
    journal: record this send to the light journal (default True)
    journal_note: free-text context stored with the entry

    On `journal` (2026-09-16): this is the SECOND send path — light.py and
    light_send.py are the others — and an unrecorded send is indistinguishable in the
    journal from no send at all. So it records by default. Callers pass journal=False
    only where the individual call is not an *utterance*: an animation frame is part of
    a statement, not a statement, and logging each one would bury the real reaches under
    thousands of tween steps. Those callers are expected to journal the statement ONCE
    themselves (see light_breathe.py).
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
    status = _post("/api/services/light/turn_on", data)
    if journal:
        if rgb is not None:
            _journal("rgb", list(rgb), brightness, entity, journal_note)
        elif color is not None:
            _journal("css", color.lower(), brightness, entity, journal_note)
    return status


def turn_off(transition=None, entity=None, journal=True, journal_note=""):
    """Turn the light off, optionally with fade. Off is a real signal, so it records."""
    data = {"entity_id": _light_id(entity)}
    if transition is not None:
        data["transition"] = float(transition)
    status = _post("/api/services/light/turn_off", data)
    if journal:
        _journal("off", None, None, entity, journal_note)
    return status
