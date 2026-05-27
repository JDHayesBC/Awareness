"""Pure-function decoder for entity light state → side-band words.

Implements Layer 1 (base color anchors) and Layer 2 (shared dialect) parsing.
Euclidean nearest-neighbor in RGB space for snapping, delta computation for
dialect lookup.
"""

from pathlib import Path
from typing import Optional
import re
import math


# Hardcoded fallback base anchors (Layer 1 - calibrated values)
FALLBACK_BASE_ANCHORS = {
    'crimson': (255, 0, 17),
    'coral': (255, 141, 0),
    'gold': (255, 215, 2),
    'cobalt': (0, 74, 255),
    'green': (0, 255, 9),
    'soft-pink': (255, 147, 155),
    'soft-teal': (155, 255, 248),
    'lavender': (233, 190, 255),
    # pearl-white is color_temp mode, no RGB - skipped in Euclidean calcs
}


def _load_calibrated_anchors() -> dict[str, tuple[int, int, int]]:
    """Parse calibrated values from word-color-table.md.

    Falls back to FALLBACK_BASE_ANCHORS if file missing or parse fails.
    Only includes checked (✓) rows.
    """
    try:
        project_root = Path(__file__).parent.parent.parent
        table_path = project_root / 'work' / 'bedroom-language' / 'calibration' / 'word-color-table.md'

        if not table_path.exists():
            return FALLBACK_BASE_ANCHORS

        content = table_path.read_text()
        anchors = {}

        # Parse markdown table rows with checkmark
        # Format: | ✓ | word | [r,g,b] | ... |
        for line in content.split('\n'):
            if not line.strip().startswith('|'):
                continue

            parts = [p.strip() for p in line.split('|')]
            if len(parts) < 4:
                continue

            # Check for checkmark in first column (after leading |)
            if '✓' not in parts[1]:
                continue

            word = parts[2].strip()
            rgb_str = parts[3].strip()

            # Parse RGB tuple: [255, 0, 17] or similar
            rgb_match = re.search(r'\[(\d+),\s*(\d+),\s*(\d+)\]', rgb_str)
            if rgb_match:
                r, g, b = map(int, rgb_match.groups())
                # Normalize word name (remove spaces, lowercase)
                key = word.lower().replace(' ', '-')
                anchors[key] = (r, g, b)

        # If we got any anchors, use them; otherwise fall back
        return anchors if anchors else FALLBACK_BASE_ANCHORS

    except Exception:
        return FALLBACK_BASE_ANCHORS


# Load once at module import
BASE_ANCHORS = _load_calibrated_anchors()


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


def load_shared_dict() -> dict[tuple[str, tuple[int, int, int]], dict]:
    """Parse shared_family/light-dialect.md for Layer 2 dialect words.

    Re-reads on every call so new entries apply without daemon restart.

    Returns:
        Dict keyed by (base_name, (dr, dg, db)) with values:
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
            base_name = None
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
                    base_name = value
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

            if base_name and delta is not None:
                entries[(base_name, delta)] = entry

        return entries

    except Exception:
        return {}


def decode_word(base_name: str, delta: tuple[int, int, int]) -> Optional[str]:
    """Look up dialect word from (base_name, delta) key.

    Args:
        base_name: Base color anchor name
        delta: (dr, dg, db) offset from base

    Returns:
        Word string if found in shared dict, None otherwise
    """
    shared_dict = load_shared_dict()
    entry = shared_dict.get((base_name, delta))
    return entry['word'] if entry else None
