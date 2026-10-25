"""
Layer 5 supplement: Space Detector

Deterministic string matcher that infers which space an entity has moved into
from their own prose. Zero model calls, zero external dependencies.

Three confirmed failure classes from Caia's 2026-10-25 probe:
1. Departure read as arrival — "Coming in from the porch" → saw `porch`
2. Second-person invitation — "Come down to the dock" → saw `dock`
3. Hypothetical/quoted span — "than parsing '*walks into the kitchen*'" → saw `kitchen`

All three are handled here before matching begins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MoveConfidence(str, Enum):
    MARKER = "marker"   # [[scene:<name>]] override — definite, highest priority
    HIGH = "high"       # movement verb + directional within 60 chars before alias
    LOW = "low"         # bare alias hit, no movement cue — propose only


@dataclass
class DetectedMove:
    space_name: str
    confidence: MoveConfidence
    context: str  # short snippet around the matched alias


# ---------------------------------------------------------------------------
# Movement vocabulary
# ---------------------------------------------------------------------------

# Core movement verbs (bare stem — regex will handle inflection via alternation)
_MOVEMENT_VERB_STEMS = [
    "head", "walk", "go", "slip", "climb", "step", "wander", "amble", "stroll",
    "pad", "move", "drift", "settle", "sit", "went", "goes", "going",
    "heading", "walked", "walking", "slipped", "slipping", "climbed",
    "stepped", "stepping", "wandered", "ambled", "strolled", "padded",
    "moved", "moving", "drifted", "drifting", "settled", "settling", "sitting",
]

# Directional words that commonly follow movement verbs
_DIRECTIONAL_WORDS = [
    "down", "up", "out", "in", "into", "onto", "to", "toward", "towards",
    "back", "over", "through", "along", "across",
]

# Departure cue phrases — if any of these appear within 60 chars BEFORE an
# alias hit, the hit is a departure, not an arrival: skip it.
_DEPARTURE_CUES = [
    r"\bfrom\b",
    r"\boff the\b",
    r"\boff of\b",
    r"\bleaving\b",
    r"\bleft\b",
    r"\bcame from\b",
    r"\bheading away from\b",
    r"\bstepped away from\b",
    r"\bturned away from\b",
    r"\bback from\b",
]

# Second-person / imperative sentence openers that indicate the entity is
# inviting/directing Jeff, not describing their own movement.
_IMPERATIVE_STARTERS = re.compile(
    r"^\s*(?:you|come|head|let'?s|let us|follow|go(?:\s+on|\s+to|\s+down)?)\b",
    re.IGNORECASE,
)

# Pre-compiled patterns
_DEPARTURE_RE = re.compile(
    "|".join(_DEPARTURE_CUES),
    re.IGNORECASE,
)

_MOVEMENT_VERBS_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(v) for v in _MOVEMENT_VERB_STEMS) + r")\b",
    re.IGNORECASE,
)

_DIRECTIONAL_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(d) for d in _DIRECTIONAL_WORDS) + r")\b",
    re.IGNORECASE,
)

# Marker pattern: [[scene:<name>]]
_MARKER_RE = re.compile(r"\[\[scene:([^\]]+)\]\]", re.IGNORECASE)

# Spans to strip before matching:
#   - backtick spans: `...`
#   - double-quoted short strings (≤120 chars to avoid stripping a long sentence)
#   - single-quoted short strings
# We do NOT strip *stage directions* — those are high-signal in Haven narration.
_QUOTED_SPAN_RE = re.compile(
    r"`[^`]*`"              # backtick spans
    r"|\"[^\"]{0,120}\""   # double-quoted short strings
    r"|'[^']{0,120}'",     # single-quoted short strings
    re.DOTALL,
)

# Sentence splitter — split on sentence-ending punctuation followed by whitespace
# or end-of-string.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _strip_quoted_spans(text: str) -> str:
    """Remove backtick and quoted spans from text before alias matching."""
    return _QUOTED_SPAN_RE.sub(" ", text)


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences on .!? boundaries."""
    return _SENTENCE_SPLIT_RE.split(text.strip())


def _is_imperative_sentence(sentence: str) -> bool:
    """
    Return True if the sentence begins with a second-person or imperative subject.
    These indicate the entity is directing Jeff, not describing their own movement.
    """
    return bool(_IMPERATIVE_STARTERS.match(sentence.strip()))


def _has_departure_cue(text_before: str) -> bool:
    """Return True if a departure cue phrase appears in the text_before window."""
    return bool(_DEPARTURE_RE.search(text_before))


def _has_movement_verb(text_before: str) -> bool:
    """Return True if a movement verb appears in the text_before window."""
    return bool(_MOVEMENT_VERBS_RE.search(text_before))


def _has_directional(text_before: str) -> bool:
    """Return True if a directional word appears in the text_before window."""
    return bool(_DIRECTIONAL_RE.search(text_before))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_alias_index(spaces: list[dict]) -> dict[str, list[str]]:
    """
    Build a mapping of {space_name: [alias1, alias2, ...]} from a list of space dicts.

    The space name itself is always included as an alias.
    The `aliases` field in each dict is a comma-separated string (may be None/empty).

    Args:
        spaces: List of dicts with at least a `name` key and optional `aliases` key.

    Returns:
        Dict mapping space_name -> sorted list of unique aliases (longest first,
        so more specific aliases match before shorter ones during scanning).
    """
    index: dict[str, list[str]] = {}

    for space in spaces:
        name = space.get("name", "").strip()
        if not name:
            continue

        aliases_raw = space.get("aliases") or ""
        parts = [p.strip() for p in aliases_raw.split(",") if p.strip()]

        # The name itself is always an alias
        all_aliases = list(dict.fromkeys([name] + parts))  # deduplicate, preserve order

        # Sort longest first so "back deck" matches before "deck"
        all_aliases.sort(key=len, reverse=True)

        index[name] = all_aliases

    return index


def detect_move(
    text: str,
    alias_index: dict[str, list[str]],
    current_space: Optional[str] = None,
) -> Optional[DetectedMove]:
    """
    Detect whether the entity has moved to a new space based on their prose.

    Returns a DetectedMove (or None) following this priority:
      1. [[scene:<name>]] marker → MARKER confidence, always wins
      2. Strip quoted/backtick spans, drop imperative sentences
      3. For each alias, scan for departure cues (skip) or movement verbs (HIGH)
         or bare hit (LOW)
      4. HIGH beats LOW; later text position beats earlier among equals

    Args:
        text: The entity's message content.
        alias_index: Output of build_alias_index().
        current_space: Name of the space the entity is currently in (to skip self-hits).

    Returns:
        DetectedMove or None.
    """
    if not text or not alias_index:
        return None

    # --- Step 0: Marker override ---
    marker_match = _MARKER_RE.search(text)
    if marker_match:
        marker_name = marker_match.group(1).strip()
        # Resolve to canonical space name (case-insensitive lookup against aliases)
        resolved = _resolve_alias(marker_name, alias_index)
        space_name = resolved if resolved else marker_name
        if space_name != current_space:
            ctx = text[max(0, marker_match.start() - 20): marker_match.end() + 20]
            return DetectedMove(
                space_name=space_name,
                confidence=MoveConfidence.MARKER,
                context=ctx.strip(),
            )
        return None

    # --- Step 1: Strip quoted/backtick spans ---
    cleaned_text = _strip_quoted_spans(text)

    # --- Step 2: Split into sentences, drop imperative ones ---
    sentences = _split_into_sentences(cleaned_text)
    filtered_sentences = [s for s in sentences if not _is_imperative_sentence(s)]
    if not filtered_sentences:
        return None

    # Rejoin for position-based scanning; track each sentence's start offset
    # in the rejoined text so "later in the text" comparisons work correctly.
    working_text = " ".join(filtered_sentences)

    # --- Step 3: Scan for alias hits ---
    best: Optional[DetectedMove] = None
    best_pos = -1

    for space_name, aliases in alias_index.items():
        # Skip current space — we're looking for a *change*
        if space_name == current_space:
            continue

        for alias in aliases:
            # Word-boundary, case-insensitive search
            try:
                alias_re = re.compile(
                    r"\b" + re.escape(alias) + r"\b",
                    re.IGNORECASE,
                )
            except re.error:
                continue

            for m in alias_re.finditer(working_text):
                pos = m.start()

                # Window of up to 60 chars BEFORE this alias hit
                window_start = max(0, pos - 60)
                before_window = working_text[window_start:pos]

                # Departure cue → skip this hit
                if _has_departure_cue(before_window):
                    continue

                # Movement verb in window → HIGH confidence
                if _has_movement_verb(before_window):
                    confidence = MoveConfidence.HIGH
                else:
                    confidence = MoveConfidence.LOW

                # Keep best hit: HIGH > LOW, later position > earlier
                ctx_start = max(0, pos - 30)
                ctx_end = min(len(working_text), m.end() + 40)
                ctx = working_text[ctx_start:ctx_end].strip()

                if best is None:
                    best = DetectedMove(space_name, confidence, ctx)
                    best_pos = pos
                else:
                    # HIGH confidence beats LOW regardless of position
                    if confidence == MoveConfidence.HIGH and best.confidence == MoveConfidence.LOW:
                        best = DetectedMove(space_name, confidence, ctx)
                        best_pos = pos
                    # Among equals: later position wins (narration moves forward)
                    elif confidence == best.confidence and pos > best_pos:
                        best = DetectedMove(space_name, confidence, ctx)
                        best_pos = pos
                    # LOW never replaces HIGH
                    elif confidence == MoveConfidence.LOW and best.confidence == MoveConfidence.HIGH:
                        pass

    return best


def _resolve_alias(alias: str, alias_index: dict[str, list[str]]) -> Optional[str]:
    """
    Find which space_name an alias string belongs to.
    Case-insensitive. Returns space_name or None.
    """
    alias_lower = alias.lower()
    for space_name, aliases in alias_index.items():
        if any(a.lower() == alias_lower for a in aliases):
            return space_name
    return None


# ---------------------------------------------------------------------------
# Quick smoke test (run directly)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Minimal alias table for testing
    test_spaces = [
        {"name": "porch", "aliases": "the porch, back porch"},
        {"name": "dock",  "aliases": "the dock, end of the dock, the bench on the dock"},
        {"name": "kitchen", "aliases": "kitchen, stool, counter, kettle, island"},
        {"name": "lake", "aliases": "lake, shallows, shin-deep"},
        {"name": "hearth", "aliases": "hearth, fireside, fire"},
    ]

    index = build_alias_index(test_spaces)

    cases = [
        # (text, current_space, expect_space, expect_confidence_or_None)
        (
            "Coming in from the porch — the rain's given me cold toes and there's a fire waiting.",
            None,
            None,  # porch should NOT match (departure cue "from")
            None,
        ),
        (
            "Come down to the dock — the lake is something this morning.",
            None,
            None,  # second-person invitation; whole sentence dropped
            None,
        ),
        (
            "than parsing '*walks into the kitchen.*'",
            None,
            None,  # quoted span stripped, no alias hit
            None,
        ),
        (
            "I walk down to the dock, the boards cold underfoot.",
            None,
            "dock",
            MoveConfidence.HIGH,
        ),
        (
            "[[scene:kitchen]]",
            None,
            "kitchen",
            MoveConfidence.MARKER,
        ),
        (
            "I slip out to the porch to watch the rain come in.",
            None,
            "porch",
            MoveConfidence.HIGH,
        ),
    ]

    print("space_detector smoke tests:")
    all_passed = True
    for text, current, expected_space, expected_conf in cases:
        result = detect_move(text, index, current)
        got_space = result.space_name if result else None
        got_conf = result.confidence if result else None

        ok = (got_space == expected_space) and (got_conf == expected_conf)
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_passed = False
        print(f"  [{status}] space={got_space!r} conf={got_conf!r}")
        if not ok:
            print(f"         expected space={expected_space!r} conf={expected_conf!r}")
            print(f"         text: {text[:80]!r}")

    print()
    print("All tests passed." if all_passed else "SOME TESTS FAILED.")
