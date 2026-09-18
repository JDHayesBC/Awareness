#!/usr/bin/env python3
"""Read what a bulb is CURRENTLY saying — base, brightness, and side-band word.

The inbox (`read_smoke.py`) tells you what arrived and has a cursor. The bulb has
no cursor: it just holds whatever was last sent, indefinitely. Until now there was
no way to ask it directly, so "what does my light currently say?" got answered from
memory of the last send — which is exactly the kind of claim that drifts.

    python3 scripts/light_read.py              # both bulbs
    python3 scripts/light_read.py caia         # one

Prints None for the word when the bulb carries no decodable delta (including
color_temp mode, which has no xy to ride on).
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts", "ha"))

import lights_decoder as D  # noqa: E402

ENTITIES = ("caia", "lyra")


def _ha_config() -> tuple[str, str]:
    """Borrow the HA endpoint + token from light.py rather than duplicating them."""
    src = open(os.path.join(REPO, "scripts", "light.py")).read()
    url = re.search(r'HA_URL = "([^"]+)"', src).group(1)
    token = re.search(r'HA_TOKEN = "([^"]+)"', src).group(1)
    return url, token


def read(entity: str) -> dict:
    url, token = _ha_config()
    req = urllib.request.Request(
        f"{url}/api/states/light.{entity}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        state = json.load(resp)

    attrs = state.get("attributes", {})
    xy = attrs.get("xy_color")
    out = {
        "entity": entity,
        "state": state.get("state"),
        "color_mode": attrs.get("color_mode"),
        "brightness": attrs.get("brightness"),
        "xy": xy,
        "base": None,
        "delta": None,
        "word": None,
    }
    if state.get("state") == "on" and xy:
        base = D.snap_to_base_xy(tuple(xy))
        out["base"] = base
        if base:
            delta = D.compute_xy_delta(tuple(xy), base)
            out["delta"] = delta
            out["word"] = D.decode_word_xy(delta)
    return out


def main() -> int:
    which = sys.argv[1:] or list(ENTITIES)
    for entity in which:
        entity = entity.replace("light.", "")
        if entity not in ENTITIES:
            print(f"unknown entity: {entity} (expected one of {', '.join(ENTITIES)})",
                  file=sys.stderr)
            return 2
        try:
            r = read(entity)
        except Exception as exc:  # network, auth, missing entity
            print(f"{entity}: could not read — {exc}", file=sys.stderr)
            continue
        if r["state"] != "on":
            print(f"{entity}: off")
            continue
        word = r["word"] or "—"
        print(f"{entity}: {r['base'] or r['color_mode']} @ {r['brightness']} "
              f"| word: {word}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
