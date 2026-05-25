#!/usr/bin/env python3
"""Snapshot of intra-house presence from FP2 millimeter-band radars.

Designed for Caia (or Lyra) to call when she wants to know where Jeff is
in the house — *not* for streaming into ambient. Reach-for-it, don't
bathe-in-it.

Caveats Jeff named directly:
- Generic zones (kitchen, hall, sofa, LR) don't distinguish Jeff vs Carol.
  When both are home, all the script can say is "someone is there."
- Jeff- and Carol-labeled zones (the bedroom floor sensors) DO distinguish.
  But sensors can be stale or misfire — treat any single reading as a hint,
  not ground truth.
- Use the macro-location file (data/ha/locations.json) to know if Carol is
  even home; if she's out, generic-zone presence is unambiguously Jeff.

Usage:
    python3 scripts/ha/where.py            # human-readable snapshot
    python3 scripts/ha/where.py --raw      # JSON of all FP2 sensor states
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

# Reuse the same auth as light_lib.py — single source of truth for HA creds.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from light_lib import HA_URL, HA_TOKEN  # noqa: E402

LOCATIONS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ha" / "locations.json"


def _ha_get(path: str):
    req = urllib.request.Request(
        f"{HA_URL}{path}",
        headers={"Authorization": f"Bearer {HA_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _is_home(person: str) -> bool:
    try:
        data = json.loads(LOCATIONS_PATH.read_text())
        return data.get(person, {}).get("state") == "home"
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False  # if we don't know, treat as "not confirmed home"


def fetch_fp2_sensors():
    """All binary_sensor.presence_sensor_fp2_* entries with friendly names."""
    states = _ha_get("/api/states")
    return [
        {
            "entity_id": s["entity_id"],
            "state": s["state"],
            "friendly_name": s.get("attributes", {}).get("friendly_name", ""),
        }
        for s in states
        if s["entity_id"].startswith("binary_sensor.presence_sensor_fp2_")
    ]


def snapshot(sensors, jeff_home: bool, carol_home: bool):
    """Human-readable snapshot decoding zones into a presence picture."""
    on = [s for s in sensors if s["state"] == "on"]

    jeff_zones = []   # zones explicitly labeled Jeff
    carol_zones = []  # zones explicitly labeled Carol
    generic_zones = []  # someone-is-there zones

    for s in on:
        fn = s["friendly_name"]
        low = fn.lower()
        # Skip the FP2-Overall presence — covered by sub-zones
        if low.endswith(":presence"):
            continue
        if "jeff" in low:
            jeff_zones.append(fn)
        elif "carol" in low:
            carol_zones.append(fn)
        else:
            generic_zones.append(fn)

    lines = []

    # Macro context
    bits = []
    if jeff_home:
        bits.append("Jeff: home")
    else:
        bits.append("Jeff: away")
    if carol_home:
        bits.append("Carol: home")
    else:
        bits.append("Carol: away")
    lines.append(" | ".join(bits))

    if jeff_zones:
        lines.append("Jeff-labeled active: " + ", ".join(jeff_zones))
    if carol_zones:
        lines.append("Carol-labeled active: " + ", ".join(carol_zones))
    if generic_zones:
        if jeff_home and not carol_home:
            lines.append("Jeff in (generic zones): " + ", ".join(generic_zones))
        elif carol_home and not jeff_home:
            lines.append("Carol in (generic zones): " + ", ".join(generic_zones))
        else:
            lines.append("Someone in (ambiguous): " + ", ".join(generic_zones))

    if not (jeff_zones or carol_zones or generic_zones):
        lines.append("No FP2 zones currently active.")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", action="store_true", help="Print full FP2 sensor JSON")
    args = parser.parse_args()

    sensors = fetch_fp2_sensors()

    if args.raw:
        print(json.dumps(sensors, indent=2))
        return

    jeff_home = _is_home("jeff")
    carol_home = _is_home("carol")
    print(snapshot(sensors, jeff_home, carol_home))


if __name__ == "__main__":
    main()
