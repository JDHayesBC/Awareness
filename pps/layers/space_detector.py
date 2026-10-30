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
    HIGH = "high"       # first-person movement/position statement in the sentence before alias
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

# Departure cue: the before-window must END with one of these phrases (plus an
# optional article/possessive), i.e. the cue is ADJACENT to the alias. A "from"
# elsewhere in the sentence ("knees stiff from the boards, ... walk to the
# kitchen") is not a departure from the kitchen.
# Second-person / imperative sentence openers that indicate the entity is
# inviting/directing Jeff, not describing their own movement.
_IMPERATIVE_STARTERS = re.compile(
    r"^\s*(?:you|come|head|let'?s|let us|follow|go(?:\s+on|\s+to|\s+down)?)\b",
    re.IGNORECASE,
)

# Pre-compiled patterns
_DEPARTURE_RE = re.compile(
    r"\b(?:from|off the|off of|off|out of|leaving|left|away from|back from)\s+"
    r"(?:the\s+|his\s+|her\s+|our\s+|my\s+|that\s+|this\s+)?$",
    re.IGNORECASE,
)

_MOVEMENT_VERBS_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(v) for v in _MOVEMENT_VERB_STEMS) + r")\b",
    re.IGNORECASE,
)

# HIGH needs a first-person subject (case-sensitive "I"; "I'm"/"I've"/"I'd" start
# with it), no modal/hypothetical, and no third-person subject after the last
# first-person token. All checked in the sentence-scoped before-window.
_FIRST_PERSON_RE = re.compile(
    r"(?-i:\bI\b)|\b(?:me|my|we|us|our)\b",
    re.IGNORECASE,
)
_MODAL_RE = re.compile(
    r"'ll\b|\b(?:will|would|might|could|should|probably|maybe)\b",
    re.IGNORECASE,
)
_THIRD_PERSON_RE = re.compile(
    r"\b(?:someone|somebody|he|she|they|Jeff|Caia|Carol|Bitsy)\b",
    re.IGNORECASE,
)

# Position statement ("I am on the hearth rug", "I'm at the island"): first-person
# token, present copula/posture verb, locative preposition (+ optional article/
# possessive) immediately before the alias. Past tense never qualifies.
_POSITION_RE = re.compile(
    r"(?:(?-i:\bI\b)|\b(?:me|my|we|us|our)\b).{0,25}?"
    r"(?:'m\b|\b(?:am|sitting|sit|standing|stand|lying|lie|stretched|curled|perched|"
    r"tucked|settled|leaning|kneeling|cross-legged|back)\b)"
    r".{0,22}?\b(?:on|at|in|by|under|against|beside|across|onto|into|up)\s+"
    r"(?:the\s+|his\s+|her\s+|our\s+|my\s+|that\s+|this\s+)?$",
    re.IGNORECASE,
)
# Subordinate-clause markers: an alias inside such a clause is scenery/reason,
# not the destination. Checked in the 80 chars before the alias, same sentence.
_SUBORDINATOR_RE = re.compile(
    r"\b(?:after|because|since|while|as|where|when)\b", re.IGNORECASE
)
_SUBORDINATE_SPAN = 80
_PAST_RE = re.compile(r"\b(?:was|were|had|sat|stood|lay)\b", re.IGNORECASE)

# Reported speech: an alias after said/wrote/... in the same sentence is quoted
# content, not the entity's own position. HIGH -> LOW. Module constant so either
# river can switch it off while measuring (#378 pass 3, item 5).
REPORTED_SPEECH_DEMOTE = True
_REPORTED_SPEECH_RE = re.compile(
    r"\b(?:said|says|wrote|asked|told|quoted)\b", re.IGNORECASE
)

# Negation gate: "not on the deck" says where she is NOT. A negator + locative
# preposition (or a bare "not the") adjacent to the alias drops the hit entirely.
# Checked in the last _NEGATION_SPAN chars so a distant "not" ("I'm not tired,
# I'm on the deck") never reaches it.
_NEGATION_SPAN = 25
_NEGATION_RE = re.compile(
    r"(?:\b(?:not|never|nor)|n't)\s+"
    r"(?:on|in|at|by|to|into|onto|out on|up on|down on)\s+"
    r"(?:the\s+|my\s+|our\s+)?$"
    r"|\b(?:not|never)\s+(?:the\s+)?$",
    re.IGNORECASE,
)

# Mention gate: the alias is the object of a naming/mention verb in its clause
# ("a sentence of mine named the hearth"), so it is a word being discussed, not
# a place she is in. Applied to LOW hits only; a HIGH hit keeps its own evidence.
_MENTION_SPAN = 60
_MENTION_RE = re.compile(
    r"\b(?:named|names|naming|called|calls|calling|mention(?:ed|s|ing)?|"
    r"the word|the alias|the name|typed|spelled)\s+"
    r"(?:the\s+|a\s+|my\s+)?(?:[\w'-]+\s+){0,3}$",
    re.IGNORECASE,
)

# Carbon-marker gate: a clause that describes the physical house (Jeff's FP2
# radar zones) is not Silverglow prose, even when its words are Silverglow
# aliases. Specimen (10-30, 3rd hit): "Carbon-side, Jeff is home and at his
# desk" raised LOW toward The study. Scope is the CLAUSE, not the sentence, so a
# real move in another clause of the same sentence still fires. Clause
# boundaries: ; : dashes, ", and/but/or/so/yet", bare but/while/whereas, and a
# bare comma. A clause that is only the marker ("Carbon-side,") marks the
# clause after it. Even inside a marked clause, a HIGH hit whose first-person
# cue comes after the marker is kept: a missed real move is worse than a flag.
# Keep the marker list short; each one is another way to hide a true move.
_CARBON_MARKER_RE = re.compile(
    r"\bcarbon[- ]side\b|\bthe radar\b|\bFP2\b|\bwhere\.py\b",
    re.IGNORECASE,
)
_CLAUSE_BOUNDARY_RE = re.compile(
    r"\s*[;:\u2014\u2013]\s*|\s+-{1,2}\s+"
    r"|,\s*(?:(?:and|but|or|so|yet)\b\s*)?"
    r"|\s+(?:but|while|whereas)\b\s*",
    re.IGNORECASE,
)
_MARKER_ONLY_RE = re.compile(
    r"^\W*(?:(?:on|over|out)\s+)?(?:the\s+)?(?:" + _CARBON_MARKER_RE.pattern + r")\W*$",
    re.IGNORECASE,
)


def _carbon_spans(sentence_text: str, offset: int) -> list[tuple[int, int, int]]:
    """Marked clause spans in one sentence: (start, end, marker_end), absolute offsets."""
    clauses: list[tuple[int, int]] = []
    pos = 0
    for b in _CLAUSE_BOUNDARY_RE.finditer(sentence_text):
        if b.start() > pos:
            clauses.append((pos, b.start()))
        pos = b.end()
    if pos < len(sentence_text):
        clauses.append((pos, len(sentence_text)))
    spans: list[tuple[int, int, int]] = []
    carry = None  # marker_end carried from a marker-only clause
    for c_start, c_end in clauses:
        clause = sentence_text[c_start:c_end]
        m = _CARBON_MARKER_RE.search(clause)
        if m:
            spans.append((offset + c_start, offset + c_end, offset + c_start + m.end()))
            carry = offset + c_start + m.end() if _MARKER_ONLY_RE.match(clause) else None
        elif carry is not None:
            spans.append((offset + c_start, offset + c_end, carry))
            carry = None
    return spans


def _carbon_marked_spans(text: str) -> list[tuple[int, int, int]]:
    """All carbon-marked clause spans in text, sentence by sentence."""
    spans: list[tuple[int, int, int]] = []
    start = 0
    for b in list(_SENT_BOUNDARY_RE.finditer(text)) + [None]:
        end = b.start() + 1 if b else len(text)
        spans.extend(_carbon_spans(text[start:end], start))
        if b:
            start = b.end()
    return spans


# Account-frame gate: a bare hit (no first-person move or position cue) that
# sits after "account of / why / because / the reason" with a past-tense verb
# between the frame and the alias is a recollection, not a position.
# Specimen (Lyra, 10-30 13:46, friction #18): "...where my own account of why
# I stayed in bed could be tested" proposed the bedroom from the kitchen.
# A real move under "because" ("because I walked back to bed") carries a
# movement cue, so it never reaches this gate and keeps its proposal.
_ACCOUNT_FRAME_RE = re.compile(
    r"\b(?:account of|why|because|the reason)\b", re.IGNORECASE
)
_RECALL_PAST_RE = re.compile(
    r"\b(?:\w{2,}ed|was|were|had|sat|stood|lay|slept|kept|spent|left|went|came|got)\b",
    re.IGNORECASE,
)


def _is_account_recollection(text_before: str) -> bool:
    """Alias after an account/why/because frame with a past verb in between."""
    last = None
    for last in _ACCOUNT_FRAME_RE.finditer(text_before):
        pass
    return bool(last and _RECALL_PAST_RE.search(text_before, last.end()))


# Coordination gate: two different rooms joined by or/and/nor/versus are a list
# ("the hearth or the deck"), not a position. Text between the two hits must be
# only the connector.
_COORD_RE = re.compile(
    r"\s*(?:,\s*)?(?:or|and|nor|versus|vs\.?)\s*,?\s+(?:the\s+)?",
    re.IGNORECASE,
)

# Sentence boundary used to scope the before-window; window cap in chars.
_SENT_BOUNDARY_RE = re.compile(r"[.!?]\s+")
_WINDOW_CAP = 220

# Marker pattern: [[scene:<name>]]
_MARKER_RE = re.compile(r"\[\[scene:([^\]]+)\]\]", re.IGNORECASE)

# Spans to strip before matching:
#   - backtick spans: `...`
#   - double-quoted short strings (≤120 chars to avoid stripping a long sentence)
#   - single-quoted short strings
# Quotes must open after a non-word char and close before one, so apostrophes
# inside words ("I'm ... Jeff's") are never read as a quoted span.
# We do NOT strip *stage directions* — those are high-signal in Haven narration.
_QUOTED_SPAN_RE = re.compile(
    r"`[^`]*`"              # backtick spans
    r"|(?<!\w)\"[^\"]{0,120}\"(?!\w)"   # double-quoted short strings
    r"|(?<!\w)'[^']{0,120}'(?!\w)",     # single-quoted short strings
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
    """Return True if the window ENDS with a departure phrase (adjacent to the alias)."""
    return bool(_DEPARTURE_RE.search(text_before))


def _has_negation_cue(text_before: str) -> bool:
    """Return True if the window ENDS with 'not on the' / 'never in' / 'not the'."""
    return bool(_NEGATION_RE.search(text_before[-_NEGATION_SPAN:]))


def _has_mention_cue(text_before: str) -> bool:
    """Return True if the alias is the object of a naming/mention verb."""
    return bool(_MENTION_RE.search(text_before[-_MENTION_SPAN:]))


def _before_window(text: str, pos: int) -> str:
    """Text from the start of the sentence containing `pos` up to `pos` (cap 220)."""
    start = max(0, pos - _WINDOW_CAP)
    head = text[start:pos]
    last = None
    for last in _SENT_BOUNDARY_RE.finditer(head):
        pass
    return head[last.end():] if last else head


def _has_movement_verb(text_before: str) -> bool:
    """Return True if a movement verb appears in the text_before window."""
    return bool(_MOVEMENT_VERBS_RE.search(text_before))


def _passes_subject_filters(text_before: str) -> bool:
    """First-person present, no modal, no third-person subject after last first-person token."""
    last_fp = None
    for last_fp in _FIRST_PERSON_RE.finditer(text_before):
        pass
    if last_fp is None:
        return False
    if _MODAL_RE.search(text_before):
        return False
    if _THIRD_PERSON_RE.search(text_before, last_fp.end()):
        return False
    return True


def _is_position_statement(text_before: str) -> bool:
    """Present-tense first-person position statement ending at the alias."""
    if _PAST_RE.search(text_before):
        return False
    if not _POSITION_RE.search(text_before):
        return False
    return _passes_subject_filters(text_before)


def _is_first_person_move(text_before: str) -> bool:
    """
    Return True if the before-window reads as the entity's own movement:
    movement verb + first-person token, no modal, and no third-person subject
    after the last first-person token. (A directional-word check was dropped:
    it added nothing the verb list didn't already gate.)
    """
    if not _has_movement_verb(text_before):
        return False
    return _passes_subject_filters(text_before)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class AliasIndex(dict):
    """dict[space_name, aliases] that also carries `houses` {space_name: house|None}.

    Subclasses dict so every caller that treats the index as a plain mapping
    keeps working; detect_move reads `.houses` when present.
    """

    houses: dict[str, Optional[str]]

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.houses = {}


def build_alias_index(spaces: list[dict]) -> AliasIndex:
    """
    Build a mapping of {space_name: [alias1, alias2, ...]} from a list of space dicts.

    The `aliases` field in each dict is a comma-separated string (may be None/empty).
    When it is non-empty the row is *curated*: the bare space name is NOT an alias
    (owners trim aliases deliberately; a name like "lake" is too generic).
    When it is empty the name itself is the only alias, so uncurated rows keep
    working.  An optional `house` field (nullable) is carried on `.houses`.

    Returns:
        AliasIndex mapping space_name -> aliases (longest first, so more specific
        aliases match before shorter ones during scanning).
    """
    index = AliasIndex()

    for space in spaces:
        name = (space.get("name") or "").strip()
        if not name:
            continue

        aliases_raw = space.get("aliases") or ""
        parts = [p.strip() for p in aliases_raw.split(",") if p.strip()]

        if parts:
            all_aliases = list(dict.fromkeys(parts))
        else:
            all_aliases = [name]

        # Sort longest first so "back deck" matches before "deck"
        all_aliases.sort(key=len, reverse=True)

        index[name] = all_aliases
        house = (space.get("house") or "").strip() or None
        index.houses[name] = house

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
      2. Quoted/backtick spans are stripped first (also before marker search);
         drop imperative sentences
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

    # --- Step 0: Strip quoted/backtick spans (before marker search, so a
    # backticked/quoted marker in meta-conversation does not fire) ---
    cleaned_text = _strip_quoted_spans(text)

    # --- Step 1: Marker override ---
    marker_match = _MARKER_RE.search(cleaned_text)
    if marker_match:
        marker_name = marker_match.group(1).strip()
        # Resolve to canonical space name (case-insensitive lookup against aliases)
        resolved = _resolve_alias(marker_name, alias_index, current_space)
        ctx = cleaned_text[max(0, marker_match.start() - 20): marker_match.end() + 20].strip()
        if resolved is None:
            # Unknown space: propose only (server says "not a known space"), never set.
            return DetectedMove(marker_name, MoveConfidence.LOW, ctx)
        if resolved != current_space:
            return DetectedMove(resolved, MoveConfidence.MARKER, ctx)
        return None

    # --- Step 2: Split into sentences, drop imperative ones ---
    sentences = _split_into_sentences(cleaned_text)
    filtered_sentences = [s for s in sentences if not _is_imperative_sentence(s)]
    if not filtered_sentences:
        return None

    # Rejoin for position-based scanning; track each sentence's start offset
    # in the rejoined text so "later in the text" comparisons work correctly.
    working_text = " ".join(filtered_sentences)

    # --- Step 3: Collect alias hits across ALL spaces (including current) ---
    # Overlaps resolve longest-wins by masking consumed spans, THEN hits that
    # belong to current_space are dropped. Doing the drop first (the old
    # per-space `continue`) left nested shorter aliases ("bedroom" inside
    # "Silverglow bedroom") free to invent a move.
    hits: list[tuple[str, int, int]] = []  # (space_name, start, end)
    houses = getattr(alias_index, "houses", {}) or {}
    current_house = houses.get(current_space) if current_space else None
    for space_name, aliases in alias_index.items():
        for alias in aliases:
            try:
                alias_re = re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE)
            except re.error:
                continue
            for m in alias_re.finditer(working_text):
                hits.append((space_name, m.start(), m.end()))

    # Longest span first (ties: earliest, then tie-break rank, then index order
    # via stable sort). The rank settles a DUPLICATE alias carried by two rows:
    # current space > same house as current space > anything else (#378 3.2).
    hits.sort(key=lambda h: (
        -(h[2] - h[1]), h[1], _tiebreak_rank(h[0], current_space, current_house, houses),
    ))
    taken: list[tuple[int, int]] = []
    accepted: list[tuple[str, int, int]] = []
    for space_name, start, end in hits:
        if any(start < t_end and end > t_start for t_start, t_end in taken):
            continue
        taken.append((start, end))
        accepted.append((space_name, start, end))
    accepted.sort(key=lambda h: h[1])  # text order: later position wins among equals

    best: Optional[DetectedMove] = None
    best_pos = -1
    carbon_spans = _carbon_marked_spans(working_text)

    # Coordination gate (pre-pass): adjacent hits for two DIFFERENT spaces joined
    # only by or/and/nor/versus are a list, not a position. Never drops a pair
    # when either side carries a first-person move/position cue.
    # Specimen: "a sentence of mine named the hearth or the deck" proposed deck.
    # Note this also skips the old legitimate LOW in "Across the pool and the
    # deck the light is going"; that loss is intended.
    coordinated: set[int] = set()
    for i in range(len(accepted) - 1):
        (sp_a, _, end_a), (sp_b, start_b, _) = accepted[i], accepted[i + 1]
        if sp_a == sp_b or not _COORD_RE.fullmatch(working_text[end_a:start_b]):
            continue
        wa = _before_window(working_text, accepted[i][1])
        wb = _before_window(working_text, start_b)
        if any(
            _is_first_person_move(w) or _is_position_statement(w) for w in (wa, wb)
        ):
            continue
        coordinated.update((i, i + 1))

    for idx, (space_name, start, end) in enumerate(accepted):
        if idx in coordinated:
            continue
        # Skip current space — we're looking for a *change*
        if space_name == current_space:
            continue

        pos = start

        # Sentence-scoped window (cap 220 chars) BEFORE this alias hit
        before_window = _before_window(working_text, pos)

        # Departure cue → skip this hit
        if _has_departure_cue(before_window):
            continue

        # Negation gate: "not on the deck" is where she is NOT -> skip the hit.
        # Specimen: "Still on the sectional in the Silverglow living room, not on
        # the deck, whatever the detector read..." proposed `deck`.
        if _has_negation_cue(before_window):
            continue

        # First-person movement in window → HIGH confidence
        if _is_first_person_move(before_window) or _is_position_statement(before_window):
            confidence = MoveConfidence.HIGH
        else:
            confidence = MoveConfidence.LOW
        if confidence == MoveConfidence.HIGH and _SUBORDINATOR_RE.search(
            before_window[-_SUBORDINATE_SPAN:]
        ):
            confidence = MoveConfidence.LOW

        # Carbon-marker gate: the hit sits in a clause about the physical house.
        span = next((sp for sp in carbon_spans if sp[0] <= start < sp[1]), None)
        if span is not None:
            if confidence == MoveConfidence.LOW:
                continue
            last_fp = None
            for last_fp in _FIRST_PERSON_RE.finditer(before_window):
                pass
            fp_abs = pos - len(before_window) + last_fp.start() if last_fp else -1
            if fp_abs < span[2]:
                continue

        # Account-frame gate: a bare LOW under "account of why I stayed..." is
        # a recollection. Cued hits (move/position, even if demoted) are kept.
        if (
            confidence == MoveConfidence.LOW
            and not _is_first_person_move(before_window)
            and not _is_position_statement(before_window)
            and _is_account_recollection(before_window)
        ):
            continue

        # Mention gate: a LOW hit whose only cue is being NAMED is a word, not a
        # place. Specimen: "...a sentence of mine named the hearth or the deck."
        # proposed `deck`.
        if confidence == MoveConfidence.LOW and _has_mention_cue(before_window):
            continue

        # Reported speech: alias after said/wrote/... in this sentence is quoted
        if (
            REPORTED_SPEECH_DEMOTE
            and confidence == MoveConfidence.HIGH
            and _REPORTED_SPEECH_RE.search(before_window)
        ):
            confidence = MoveConfidence.LOW

        # House scoping: a hit in a different (known) house than the current one is
        # demoted to a proposal unless the sentence names the target's house.
        # NULL house on either side = unknown, never demotes.
        if confidence == MoveConfidence.HIGH and current_house:
            target_house = houses.get(space_name)
            if target_house and target_house.lower() != current_house.lower():
                sent_start = pos - len(before_window)
                tail = _SENT_BOUNDARY_RE.search(working_text, end)
                sent_end = tail.start() if tail else len(working_text)
                sentence = working_text[sent_start:sent_end]
                if not re.search(
                    r"\b" + re.escape(target_house) + r"\b", sentence, re.IGNORECASE
                ):
                    confidence = MoveConfidence.LOW

        # Keep best hit: HIGH > LOW, later position > earlier
        ctx_start = max(0, pos - 30)
        ctx_end = min(len(working_text), end + 40)
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

    return best


def _tiebreak_rank(
    space_name: str,
    current_space: Optional[str],
    current_house: Optional[str],
    houses: dict[str, Optional[str]],
) -> int:
    """0 = the current space, 1 = same (known) house as it, 2 = everything else.

    A NULL house on either side never promotes and never demotes: it ranks 2,
    the same as an unrelated room, so first-row-wins order decides.
    """
    if current_space and space_name == current_space:
        return 0
    house = houses.get(space_name)
    if current_house and house and house.lower() == current_house.lower():
        return 1
    return 2


def _resolve_alias(
    alias: str,
    alias_index: dict[str, list[str]],
    current_space: Optional[str] = None,
) -> Optional[str]:
    """
    Find which space_name an alias string belongs to.
    Case-insensitive; the canonical space name always resolves (marker use).
    When several rows carry the same alias, prefer the current space, then a
    space in the same house as the current space, then the first row.
    Returns space_name or None.
    """
    alias_lower = alias.lower()
    houses = getattr(alias_index, "houses", {}) or {}
    current_house = houses.get(current_space) if current_space else None
    best: Optional[str] = None
    best_rank = 99
    for space_name, aliases in alias_index.items():
        if space_name.lower() == alias_lower or any(a.lower() == alias_lower for a in aliases):
            rank = _tiebreak_rank(space_name, current_space, current_house, houses)
            if rank < best_rank:  # strict <: ties keep the earlier row
                best, best_rank = space_name, rank
    return best


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
        {"name": "main_room", "aliases": "couch"},
    ]

    index = build_alias_index(test_spaces)

    cases = [
        # (text, current_space, expect_space, expect_confidence_or_None)
        (
            "Coming in from the porch — the rain's given me cold toes and there's a fire waiting.",
            None,
            "hearth",  # porch NOT matched (departure cue "from"); "fire" is a bare LOW hit
            MoveConfidence.LOW,
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
        (
            "I'm heading down to the dock now, Jeff's robe still over my shoulders.",
            None,
            "dock",
            MoveConfidence.HIGH,
        ),
        (
            "I slipped out of bed so the kettle wouldn't wake him.",
            None,
            "kitchen",
            MoveConfidence.HIGH,
        ),
        (
            "Someone's up and in the kitchen.",
            None,
            "kitchen",
            MoveConfidence.LOW,
        ),
        (
            "I'll probably end up on the couch.",
            None,
            "main_room",
            MoveConfidence.LOW,
        ),
        ("I am on the hearth rug now with my back against the couch.", None, "main_room", MoveConfidence.HIGH),
        ("I'm at the island on the tall stool.", None, "kitchen", MoveConfidence.HIGH),
        ("I'm barefoot at the kitchen counter in his Dark Side tee.", None, "kitchen", MoveConfidence.HIGH),
        ("I was on the couch earlier.", None, "main_room", MoveConfidence.LOW),
        ("Jeff is on the couch.", None, "main_room", MoveConfidence.LOW),
        ("I get up, knees stiff from the boards, and walk up the path to the kitchen to put the kettle on.", None, "kitchen", MoveConfidence.HIGH),
        ("[[scene:attic]]", None, "attic", MoveConfidence.LOW),
        (
            "`[[scene:kitchen]]`",
            None,
            None,
            None,
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
