"""Read current household location written by the location_daemon.

Container-internal copy of scripts/ha/location.py. Copied into /app/ by the
Dockerfile alongside server_http.py. Reads from the bind-mounted path set by
HA_LOCATIONS_PATH env var (mounted at /app/host_data/ha/locations.json).
"""
import json, os
from pathlib import Path

LOCATIONS_PATH = Path(
    os.environ.get("HA_LOCATIONS_PATH", "/app/host_data/ha/locations.json")
)


def get_locations() -> dict:
    try:
        return json.loads(LOCATIONS_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def format_for_ambient() -> str:
    """One-line ambient string. Empty if no data — caller skips section."""
    locs = get_locations()
    if not locs:
        return ""
    parts = [
        f"{person.capitalize()}: {data.get('state', 'unknown')}"
        for person, data in sorted(locs.items())
    ]
    return ", ".join(parts)
