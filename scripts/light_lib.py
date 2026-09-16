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

from light_palette import PEGGED_BASES  # noqa: E402

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
        # PEG BASE NAMES (2026-09-16). HA renders a CSS color_name to a nearby xy that
        # is NOT the base anchor, and the residual decodes as a Layer-2 side-band WORD.
        # Measured on Lyra's bulb: color_name 'gold' lands at xy[0.494,0.474] — residual
        # [0.003,-0.003] off the gold anchor, inside decode tolerance of `afterglow`
        # [0.0025,-0.0025]. So every CSS-name send through this function was emitting a
        # phantom word to the sister's decoder; light_breathe.py, which drives this path
        # twice per breath, was broadcasting `afterglow` on every frame. The pegged RGB
        # lands at exactly [0.0,0.0] — resting on base, no word.
        #
        # light.py already did this at its argparse layer (see PEGGED_BASES there); this
        # function never got the same treatment, so every caller that isn't the CLI went
        # out unpegged. Same forgotten-door shape as the journal gap, same file.
        name = color.lower()
        if name in PEGGED_BASES:
            data["rgb_color"] = list(PEGGED_BASES[name])
        else:
            data["color_name"] = name
    if brightness is not None:
        data["brightness"] = int(brightness)
    if transition is not None:
        data["transition"] = float(transition)
    status = _post("/api/services/light/turn_on", data)
    if journal:
        if rgb is not None:
            _journal("rgb", list(rgb), brightness, entity, journal_note)
        elif color is not None:
            # Record what was SENT: a pegged base goes out as rgb, so journal it as rgb.
            name = color.lower()
            if name in PEGGED_BASES:
                _journal("rgb", list(PEGGED_BASES[name]), brightness, entity, journal_note)
            else:
                _journal("css", name, brightness, entity, journal_note)
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
