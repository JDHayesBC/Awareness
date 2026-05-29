"""Pure-function decoder for entity light state → side-band words.

Implements Layer 1 (base color anchors) and Layer 2 (shared dialect) parsing.
Euclidean nearest-neighbor in RGB space for snapping, delta computation for
dialect lookup.
"""

from pathlib import Path
from typing import Optional
import re
import math


# Canonical Layer-1 base anchors. This dict IS the source of truth — code owns the
# anchors, docs point here (work/bedroom-language/calibration/word-color-table.md and
# CLAUDE.md §X reference this dict, not the reverse). An earlier version scraped the prose
# calibration table, but that table puts base names parenthetically in the seed column and
# the ✓ in the *calibrated* column, so the scrape matched nothing and silently fell back to
# this dict on every run. Removed the parser (2026-05-29) rather than keep a load-bearing
# no-op that implied the docs drove the code. Keep this dict in sync with the table and
# CLAUDE.md §X by hand.
#
# Pure-RGB bases are PEGGED to [3, 252] per channel (Jeff, 2026-05-29). A human eye can't
# tell 255 from 252 or 0 from 3, but the 3-unit headroom lets any side-band delta (capped
# at ±3) ride any base without clamping at the 0/255 rails. light.py emits these exact
# values for bare base-sits (see PEGGED_BASES there), so a resting base decodes as delta
# (0,0,0). White-mixed bases (soft-pink/soft-teal/lavender) keep their HA-reported values:
# they don't carry side-band words (light_send.py strips the white channels via WW=0), and
# their bare base-sits still decode cleanly against these anchors.
BASE_ANCHORS = {
    'crimson': (252, 3, 17),
    'coral': (252, 141, 3),
    'gold': (252, 215, 3),
    'cobalt': (3, 74, 252),
    'green': (3, 252, 9),
    'soft-pink': (255, 147, 155),
    'soft-teal': (155, 255, 248),
    'lavender': (233, 190, 255),
    # pearl-white is color_temp mode, no RGB - skipped in Euclidean calcs
}

# A bare base-sit drifts by ~1 unit/channel of Zigbee gamut wobble (worst case the
# all-three-channel diagonal, magnitude ~1.73). Any delta within this radius of origin is a
# base-sit, NOT a word — even if it happens to land near a word in the dict. This dead-zone
# is what stops a resting bulb's wobble from phantom-decoding as a word. It sits just below
# the closest dialect word (curious-about-your-thread at magnitude 3.0 after the 2026-05-29
# bump from 2.0; the rest of the cloud is already ≥3.0), so every real word stays decodable.
BASE_SIT_RADIUS = 1.8


def snap_to_base(rgb: tuple[int, int, int]) -> str:
    """Euclidean nearest-neighbor in RGB space against base anchors.

    Args:
        rgb: (r, g, b) tuple with values 0-255

    Returns:
        Canonical base color name (e.g., 'lavender', 'crimson')
    """
    min_dist = float('inf')
    closest = None

    for name, anchor_rgb in BASE_ANCHORS.items():
        # Euclidean distance in RGB space
        dist = math.sqrt(
            (rgb[0] - anchor_rgb[0])**2 +
            (rgb[1] - anchor_rgb[1])**2 +
            (rgb[2] - anchor_rgb[2])**2
        )

        if dist < min_dist:
            min_dist = dist
            closest = name

    return closest


def compute_delta(rgb: tuple[int, int, int], base_name: str) -> tuple[int, int, int]:
    """Component-wise subtraction: rgb - base_anchor.

    Args:
        rgb: Current RGB tuple
        base_name: Name of base anchor to subtract

    Returns:
        (dr, dg, db) delta tuple
    """
    if base_name not in BASE_ANCHORS:
        raise ValueError(f"Unknown base anchor: {base_name}")

    base_rgb = BASE_ANCHORS[base_name]
    return (
        rgb[0] - base_rgb[0],
        rgb[1] - base_rgb[1],
        rgb[2] - base_rgb[2]
    )


def load_shared_dict() -> dict[tuple[int, int, int], dict]:
    """Parse shared_family/light-dialect.md for Layer 2 dialect words.

    Re-reads on every call so new entries apply without daemon restart.

    Word identity is the delta pattern only — not a (base, delta) pair.
    The base field in individual entries is ignored if present (backward compat).

    Returns:
        Dict keyed by (dr, dg, db) delta tuple with values:
        {"word": str, "notes": str|None, "declared": str|None, "coined_by": str|None}
        Returns {} if file missing or unparseable.
    """
    try:
        project_root = Path(__file__).parent.parent.parent
        dict_path = project_root / 'shared_family' / 'light-dialect.md'

        if not dict_path.exists():
            return {}

        content = dict_path.read_text()
        entries = {}

        # Split into sections by ## headings
        sections = re.split(r'^## ', content, flags=re.MULTILINE)

        for section in sections[1:]:  # Skip preamble before first ##
            lines = section.split('\n')
            word = lines[0].strip()

            # Find yaml code block
            yaml_start = None
            yaml_end = None
            for i, line in enumerate(lines):
                if line.strip().startswith('```yaml'):
                    yaml_start = i + 1
                elif yaml_start is not None and line.strip() == '```':
                    yaml_end = i
                    break

            if yaml_start is None or yaml_end is None:
                continue

            # Parse yaml manually (simple key: value parsing)
            yaml_lines = lines[yaml_start:yaml_end]
            entry = {"word": word, "notes": None, "declared": None, "coined_by": None}
            delta = None

            for line in yaml_lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                if ':' not in line:
                    continue

                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()

                if key == 'base':
                    pass  # Ignored — word identity is delta only (backward compat strip)
                elif key == 'delta':
                    # Parse [dr, dg, db]
                    delta_match = re.search(r'\[(-?\d+),\s*(-?\d+),\s*(-?\d+)\]', value)
                    if delta_match:
                        delta = tuple(map(int, delta_match.groups()))
                elif key == 'notes':
                    entry['notes'] = value if value else None
                elif key == 'declared':
                    entry['declared'] = value if value else None
                elif key == 'coined_by':
                    entry['coined_by'] = value if value else None

            if delta is not None:
                entries[delta] = entry

        return entries

    except Exception:
        return {}


def decode_word(delta: tuple[int, int, int]) -> Optional[str]:
    """Find the dialect word whose stored delta is closest to `delta` in Euclidean distance.

    Uses nearest-neighbor with tolerance ≤ 2.0 to absorb Zigbee gamut drift (~1 unit
    per channel). Does not require the sender's base color — word identity is delta only.

    Args:
        delta: (dr, dg, db) offset from snapped base

    Returns:
        Word string if a dict entry is within tolerance, None otherwise.
        Returns None for delta (0,0,0) — that is a pure base-color emit, not a word.
    """
    # (0,0,0) is never a word — it's a base-color state change, filtered upstream
    if delta == (0, 0, 0):
        return None

    dict_data = load_shared_dict()
    if not dict_data:
        return None

    best_distance = float('inf')
    best_word = None

    for stored_delta, entry in dict_data.items():
        distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(delta, stored_delta)))
        if distance < best_distance:
            best_distance = distance
            best_word = entry["word"]

    # Tolerance: ≤ 2 in Euclidean distance (covers ~1 unit drift per channel)
    return best_word if best_distance <= 2.0 else None


def classify(delta: tuple[int, int, int]) -> tuple[str, Optional[str]]:
    """Classify a delta into one of three kinds. This is the entry point callers should
    use — decode_word alone collapses base-sit, wobble, and genuine garbage into None.

    - ("base_sit", None)       — within BASE_SIT_RADIUS of origin: the bulb is resting on
                                 its bare Layer-1 base (delta 0 plus Zigbee wobble). Not a
                                 word; callers treat this as noise, like off.
    - ("word", <word>)         — outside the dead-zone and within decode tolerance of a
                                 dialect word.
    - ("indecipherable", None) — outside the dead-zone and matching no word: a genuine
                                 off-anchor oddity worth a human's eye.

    Base-sit takes priority inside the radius: a wobble that happens to land near a
    close-to-origin word still reads as a base-sit, not that word. Resolving the
    base-sit / small-word ambiguity in favor of "resting" is the whole point of the
    dead-zone — it's why the vocabulary keeps every word out at magnitude ≥ 3.0.
    """
    magnitude = math.sqrt(sum(d * d for d in delta))
    if magnitude <= BASE_SIT_RADIUS:
        return ("base_sit", None)
    word = decode_word(delta)
    if word is not None:
        return ("word", word)
    return ("indecipherable", None)
