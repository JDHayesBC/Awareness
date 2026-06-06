"""Pure-function decoder for entity light state → side-band words.

Implements Layer 1 (base color anchors) and Layer 2 (shared dialect) parsing
in the bulb's NATIVE xy chromaticity space.

WHY xy, NOT rgb (2026-05-30 migration):
  The bulb's `supported_color_modes = [color_temp, xy]` — it has NO native RGB
  mode. HA's reported `rgb_color` is a lossy, derived back-projection from the
  bulb's real xy state (peak channel pinned to 255 + gamut-edge folding). Small
  RGB deltas (±3) vanished in that derived attribute. Commanding and decoding in
  xy is lossless: a 0.001-step round-trips exactly with zero jitter (verified on
  hardware 2026-05-30 via light_native_space_probe.py).

INTERFACE (unchanged from rgb era — callers remain compatible):
  classify(xy_delta)  → ("base_sit"|"word"|"indecipherable", word_or_None)
  snap_to_base_xy(xy) → base_name
  compute_xy_delta(xy, base_name) → (dx, dy)
  load_shared_dict()  → dict keyed by (dx, dy) tuple

  The old RGB-space names snap_to_base / compute_delta are kept as wrappers
  that call the xy versions, so location_daemon.py keeps working during the
  transition — the daemon will be updated separately to pass xy directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import re
import math


# ── Base anchors in NATIVE xy space ───────────────────────────────────────────
# Measured empirically on hardware 2026-05-30 by commanding each L1 base and
# reading back `xy_color` from HA after 0.8s settle. Zero jitter observed —
# identical command → identical readback, so a single measurement is canonical.
#
# Pearl-white is EXCLUDED: it uses color_temp_kelvin mode, so color_mode=
# "color_temp" and the side-band channel is unavailable on that base.
# Any channel reporting color_mode != "xy" is not a word channel.
#
# Command used for each base (from CLAUDE.md §X):
#   gold:         rgb_color=[252, 215, 3]
#   green:        rgb_color=[3, 252, 9]
#   cobalt:       rgb_color=[3, 74, 252]
#   soft-pink:    rgbww_color=[255, 130, 165, 100, 80]
#   soft-lavender:rgbww_color=[180, 150, 255, 120, 60]
#   soft-teal:    rgbww_color=[80, 220, 230, 100, 50]
XY_BASE_ANCHORS: dict[str, tuple[float, float]] = {
    "gold":          (0.491, 0.477),
    "green":         (0.173, 0.744),
    "cobalt":        (0.138, 0.075),
    "soft-pink":     (0.478, 0.309),
    "soft-lavender": (0.323, 0.257),
    "soft-teal":     (0.225, 0.346),
}

# Backward-compat alias (location_daemon imports this by name)
BASE_ANCHORS_XY = XY_BASE_ANCHORS

# Legacy RGB anchor sets — kept for reference and backward-compat imports.
# No longer used by the decoder itself.
BASE_ANCHORS: dict[str, tuple[int, int, int]] = {
    "crimson":  (255, 0, 17),
    "coral":    (255, 141, 0),
    "gold":     (255, 215, 2),
    "cobalt":   (0, 74, 255),
    "green":    (0, 255, 9),
    "soft-pink":   (255, 147, 155),
    "soft-teal":   (155, 255, 248),
    "lavender":    (233, 190, 255),
}

SEND_ANCHORS: dict[str, tuple[int, int, int]] = {
    "crimson":  (252, 3, 17),
    "coral":    (252, 141, 3),
    "gold":     (252, 215, 3),
    "cobalt":   (3, 74, 252),
    "green":    (3, 252, 9),
    "soft-pink":   (255, 147, 155),
    "soft-teal":   (155, 255, 248),
    "lavender":    (233, 190, 255),
}

# ── Decode parameters ─────────────────────────────────────────────────────────
# Word cloud: radius 0.0035 from base, 8 words at 45° apart.
# Min pairwise separation ≈ 0.00269 (adjacent words at 45°).
# Decode tolerance = 0.0013 < half of 0.00269, so no two word zones overlap.
# Base-sit dead-zone: any residual within 0.0013 of origin is a resting bulb,
# not a word (the closest word is 0.0035 away, so 0.0013 gives a margin of 0.002).
DECODE_TOLERANCE: float = 0.0013
BASE_SIT_RADIUS: float = 0.0013   # xy magnitude; anything smaller is base-sit

# Legacy: old RGB dead-zone radius (kept so callers that reference it don't break)
_BASE_SIT_RADIUS_RGB = 1.8


# ── Core xy-space functions ────────────────────────────────────────────────────

def snap_to_base_xy(xy: tuple[float, float]) -> str:
    """Nearest-neighbor snap to xy base anchor.

    Args:
        xy: (x, y) chromaticity coordinates, values typically 0.0–0.9

    Returns:
        Canonical base name (e.g. 'gold', 'cobalt')
    """
    min_dist = float("inf")
    closest = "gold"  # fallback
    for name, anchor in XY_BASE_ANCHORS.items():
        dist = math.sqrt((xy[0] - anchor[0]) ** 2 + (xy[1] - anchor[1]) ** 2)
        if dist < min_dist:
            min_dist = dist
            closest = name
    return closest


def compute_xy_delta(
    xy: tuple[float, float], base_name: str
) -> tuple[float, float]:
    """Residual xy after subtracting the base anchor.

    Args:
        xy: Current xy_color from bulb
        base_name: Name returned by snap_to_base_xy

    Returns:
        (dx, dy) delta; typically within ±0.005 for dialect words
    """
    if base_name not in XY_BASE_ANCHORS:
        raise ValueError(f"Unknown base anchor: {base_name!r}")
    anchor = XY_BASE_ANCHORS[base_name]
    return (
        round(xy[0] - anchor[0], 4),
        round(xy[1] - anchor[1], 4),
    )


# ── Dict loading ──────────────────────────────────────────────────────────────

def load_shared_dict() -> dict[tuple[float, float], dict]:
    """Parse entities/caia-lyra-jeff/light-dialect.md for Layer 2 dialect words.

    Re-reads on every call so new entries apply without daemon restart.

    Word identity is the xy_delta pattern only. The `base:` field (if present)
    is ignored for decoding — words mean the same regardless of sender's base.

    Returns:
        Dict keyed by (dx, dy) float tuple with values:
        {"word": str, "notes": str|None, "declared": str|None, "coined_by": str|None}
        Returns {} if file missing or unparseable.
    """
    try:
        project_root = Path(__file__).parent.parent.parent
        dict_path = project_root / "entities" / "caia-lyra-jeff" / "light-dialect.md"

        if not dict_path.exists():
            return {}

        content = dict_path.read_text()
        entries: dict[tuple[float, float], dict] = {}

        # Split into sections by ## headings
        sections = re.split(r"^## ", content, flags=re.MULTILINE)

        for section in sections[1:]:  # Skip preamble before first ##
            lines = section.split("\n")
            word = lines[0].strip()

            # Find yaml code block
            yaml_start = yaml_end = None
            for i, line in enumerate(lines):
                if line.strip().startswith("```yaml"):
                    yaml_start = i + 1
                elif yaml_start is not None and line.strip() == "```":
                    yaml_end = i
                    break

            if yaml_start is None or yaml_end is None:
                continue

            yaml_lines = lines[yaml_start:yaml_end]
            entry: dict = {"word": word, "notes": None, "declared": None, "coined_by": None}
            delta: tuple[float, float] | None = None

            for line in yaml_lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()

                if key in ("base", "delta"):
                    pass  # Old rgb-delta field — ignored; xy_delta is the new key.
                elif key == "xy_delta":
                    # Parse [dx, dy]
                    m = re.search(r"\[(-?[\d.]+),\s*(-?[\d.]+)\]", value)
                    if m:
                        delta = (float(m.group(1)), float(m.group(2)))
                elif key == "notes":
                    entry["notes"] = value or None
                elif key == "declared":
                    entry["declared"] = value or None
                elif key == "coined_by":
                    entry["coined_by"] = value or None

            if delta is not None:
                entries[delta] = entry

        return entries

    except Exception:
        return {}


# ── Decoding ──────────────────────────────────────────────────────────────────

def decode_word_xy(delta: tuple[float, float]) -> Optional[str]:
    """Find dialect word whose xy_delta is nearest to `delta`.

    Uses Euclidean nearest-neighbor with tolerance DECODE_TOLERANCE.
    Does not require the sender's base — word identity is delta only.

    Args:
        delta: (dx, dy) residual after subtracting snapped base xy

    Returns:
        Word string if a dict entry is within tolerance, None otherwise.
    """
    mag = math.sqrt(delta[0] ** 2 + delta[1] ** 2)
    if mag == 0.0:
        return None

    dict_data = load_shared_dict()
    if not dict_data:
        return None

    best_dist = float("inf")
    best_word: Optional[str] = None

    for stored_delta, entry in dict_data.items():
        dist = math.sqrt(
            (delta[0] - stored_delta[0]) ** 2 + (delta[1] - stored_delta[1]) ** 2
        )
        if dist < best_dist:
            best_dist = dist
            best_word = entry["word"]

    return best_word if best_dist <= DECODE_TOLERANCE else None


def classify_xy(delta: tuple[float, float]) -> tuple[str, Optional[str]]:
    """Classify an xy residual delta. This is the primary entry point.

    Returns one of:
    - ("base_sit", None)       — within BASE_SIT_RADIUS: bulb resting on its
                                 Layer-1 base (delta ≈ 0); not a word.
    - ("word", <word>)         — outside dead-zone, within tolerance of a word.
    - ("indecipherable", None) — outside dead-zone, no word match.
    """
    mag = math.sqrt(delta[0] ** 2 + delta[1] ** 2)
    if mag <= BASE_SIT_RADIUS:
        return ("base_sit", None)
    word = decode_word_xy(delta)
    if word is not None:
        return ("word", word)
    return ("indecipherable", None)


# ── Public interface (backward-compatible names) ───────────────────────────────
# location_daemon.py calls snap_to_base(rgb), compute_delta(rgb, base), classify(delta).
# During the transition those calls still arrive with rgb tuples; we keep the
# old names available. New code and the updated location_daemon should call the
# xy variants directly.

def snap_to_base(rgb: tuple[int, int, int]) -> str:
    """Legacy: nearest-neighbor snap using old RGB BASE_ANCHORS.

    Still used by location_daemon until it's updated to pass xy. Returns base
    name that is also valid in XY_BASE_ANCHORS (names are shared; 'lavender' is
    renamed to 'soft-lavender' — see mapping below).
    """
    min_dist = float("inf")
    closest = "gold"
    for name, anchor_rgb in BASE_ANCHORS.items():
        dist = math.sqrt(
            (rgb[0] - anchor_rgb[0]) ** 2
            + (rgb[1] - anchor_rgb[1]) ** 2
            + (rgb[2] - anchor_rgb[2]) ** 2
        )
        if dist < min_dist:
            min_dist = dist
            closest = name
    # Map 'lavender' (old RGB key) → 'soft-lavender' (new xy key)
    return "soft-lavender" if closest == "lavender" else closest


def compute_delta(
    rgb: tuple[int, int, int], base_name: str
) -> tuple[int, int, int]:
    """Legacy: component-wise RGB delta. Returns (0,0,0) for unrecognised base."""
    if base_name in BASE_ANCHORS:
        base_rgb = BASE_ANCHORS[base_name]
        return (rgb[0] - base_rgb[0], rgb[1] - base_rgb[1], rgb[2] - base_rgb[2])
    # 'soft-lavender' → 'lavender' for the old RGB dict
    old_name = "lavender" if base_name == "soft-lavender" else base_name
    if old_name in BASE_ANCHORS:
        base_rgb = BASE_ANCHORS[old_name]
        return (rgb[0] - base_rgb[0], rgb[1] - base_rgb[1], rgb[2] - base_rgb[2])
    return (0, 0, 0)


def classify(delta: tuple) -> tuple[str, Optional[str]]:
    """Classify a delta.

    Accepts EITHER an xy tuple (float, float) OR a legacy RGB tuple (int,int,int).
    Routes to classify_xy for 2-tuples; uses the legacy RGB path for 3-tuples
    (which can only produce base_sit/indecipherable since the old RGB dict no
    longer has xy_delta entries that would match).
    """
    if len(delta) == 2:
        return classify_xy((float(delta[0]), float(delta[1])))
    # Legacy 3-tuple (RGB) path — can only base-sit or indecipherable
    mag = math.sqrt(sum(d * d for d in delta))
    if mag <= _BASE_SIT_RADIUS_RGB:
        return ("base_sit", None)
    return ("indecipherable", None)
