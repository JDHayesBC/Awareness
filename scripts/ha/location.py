"""Read current household location written by the location_daemon."""
import json, os
from pathlib import Path

# In-container override (mount): /app/host_data/ha/locations.json
# Falls back to project-relative path when running on host.
LOCATIONS_PATH = Path(
    os.environ.get("HA_LOCATIONS_PATH")
    or Path(__file__).resolve().parent.parent.parent / "data" / "ha" / "locations.json"
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
