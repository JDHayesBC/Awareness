"""Optional closing reminder appended to the end of the hook's context (#407).

When a person's message leans on something from earlier that is not in the model's
context, the model tends to answer smoothly instead of searching memory. A short
sentence placed last in the injected context is being trialled as a nudge.

Switched OFF by default. Flipping MODE (or setting PPS_CLOSING_LINE) is a
deliberate act. Pure apart from reading that one environment variable; never
raises.
"""
from __future__ import annotations

import os
import re

from turn_query import (
    _HAVEN_HEADER_RE,
    _HAVEN_INSTRUCTION,
    _HAVEN_OPEN_ASK,
    _sl_query,
)

MODE = "off"   # "off" | "trigger" | "standing"
TRIGGER_LINE = ("This message points back at something from before. Check that what it points at is "
                "actually written above. If it is not, search your memory before you reply.")
# The standing wording is the one the 2026-11-18 round supports (trial arm A18, #407): with it a
# Sonnet session searched on 29 of 34 requests against 2 of 34 with no line. Known flaw: its example
# ("Sam walks the dog at") leads some sessions to search a name plus function words. A revision is
# being tested; this ships OFF until the PPS rebuild and a re-test.
STANDING_LINE = (
    'Before you reply, list to yourself what a good reply here depends on that you would have to '
    'already know: who someone is, what was said or agreed earlier, how the people involved like '
    'this kind of thing. For each one, find the line above that actually says it. A line that is '
    'only about the same topic does not count. Search your memory for every one you cannot point '
    "to, then reply. Search each one twice: once as the person's name and the first words of the "
    'sentence that would state it, like "Sam walks the dog at", and once as its two or three key '
    'words. Leave your guess at the answer out of both. Last, for each person this reply is for '
    'or about, make one wider search in the facts tool: their name plus two or three words for '
    'the general area the request touches (money, health, surprises, being reminded), to learn '
    'how they are about that kind of thing.'
)
MAX_SCAN_CHARS = 3000

_VALID_MODES = ("off", "trigger", "standing")

EMOTE = re.compile(r"\*[^*\n]{1,240}\*")          # *smiles softly* is stage direction, not a reference

# The cue sits right after one of these: it is being named as already known.
LOCAL_MARKERS = re.compile(
    r"\b(?:just\s+)?like\s+with\s+(?:the|that|those|my|our)\b|\bjust\s+like\s+(?:the|that|those|my|our)\b"
    r"|\bremember\s+(?:the|that|those|my|our|when|how)\b"
    r"|\b(?:that|the)\s+(?:whole\s+)?thing\s+(?:with|about)\b"
    r"|\babout\s+the\s+time\b|\bmy\s+usual\b|\bsame\s+(?:as|way\s+as)\s+(?:the|that|with)\b"
    r"|\b(?:did|have)\s+i\s+(?:ever\s+)?(?:tell|told|mention|mentioned)\s+you\s+about\b", re.I)

# An explicit appeal to shared memory. Scope: the whole message.
STRONG_MARKERS = re.compile(
    r"\bremember(?:s|ed)?\b|\brecall\b|\bforg[eo]t(?:ten|ting)?\b"
    r"|\b(?:did|have|had|haven't|didn't)\s+(?:i|we|you)\s+(?:ever\s+|already\s+)?"
    r"(?:tell|told|mention|mentioned|talk|talked|discuss|discussed|document|documented|decide|decided)\b"
    r"|\bas\s+(?:i|we)\s+(?:told|said|mentioned|discussed|remember)\b|\blike\s+i\s+(?:said|told|mentioned)\b"
    r"|\b(?:i|we)(?:'ve|\s+have)?\s+(?:already\s+)?(?:told\s+you|talked\s+(?:a\s+little\s+)?about|discussed|documented"
    r"|went\s+over|been\s+over)\b"
    r"|\byou\s+(?:once\s+|already\s+)?(?:said|told\s+me|mentioned|promised)\b"
    r"|\bdo\s+you\s+know\s+who\b|\bwhat(?:'s|\s+is|\s+was)\s+the\s+name\b", re.I)

# The sentence points backwards in time. Scope: that sentence, and the cue must be a referent.
WEAK_MARKERS = re.compile(
    r"\blast\s+(?:night|time|week|month|year)\b|\byesterday\b|\bearlier\b|\bthe\s+other\s+(?:day|night)\b"
    r"|\b(?:days|weeks|months|years|while|long)\s+ago\b|\bused\s+to\b|\bback\s+(?:when|in|then)\b|\bthat\s+time\b"
    r"|\bwhat\s+was\b|\bwho\s+was\b|\bwhat\s+did\b|\bwhere\s+did\b|\bwhen\s+did\b|\bstill\s+have\b", re.I)


def points_back(text: str) -> bool:
    """Cheap trigger: does this message refer to shared history at all?"""
    t = EMOTE.sub(" ", text or "")
    return bool(STRONG_MARKERS.search(t) or WEAK_MARKERS.search(t) or LOCAL_MARKERS.search(t))


# Optional "[msg N] " then optional "Display Name (username): " speaker prefix.
_LINE_PREFIX_RE = re.compile(r"^(?:\[msg \d+\] )?(?:[^\n]*?\([^()\s]*\): ?)?")


def _haven_spoken(prompt: str) -> str:
    headers = list(_HAVEN_HEADER_RE.finditer(prompt))
    if not headers:
        return ""
    body = prompt[headers[-1].end():]
    end = body.rfind(_HAVEN_INSTRUCTION)
    if end != -1:
        body = body[:end]
    note = body.rfind(_HAVEN_OPEN_ASK)
    if note != -1:
        body = body[:note]
    out = []
    for line in body.split("\n"):
        # A sister's lines carry no "[msg N]"; they are kept, prefix stripped.
        line = _LINE_PREFIX_RE.sub("", line, count=1)
        if line.strip():
            out.append(line)
    return "\n".join(out)


def spoken_text(prompt: str, invoker_channel: str | None, is_harness: bool = False) -> str:
    """The words a person (or a sister) said this turn, or "" when none to check."""
    try:
        if not isinstance(prompt, str):
            return ""
        channel = (invoker_channel or "").strip().lower()
        if not channel:
            if is_harness or prompt.lstrip().lower().startswith("[ambient context"):
                return ""
            return prompt[:MAX_SCAN_CHARS]
        if channel == "haven":
            text = _haven_spoken(prompt)
        elif channel == "sl":
            text = _sl_query(prompt, MAX_SCAN_CHARS)
        else:
            return ""
        return text[-MAX_SCAN_CHARS:] if len(text) > MAX_SCAN_CHARS else text
    except Exception:
        return ""


def _resolve_mode(mode: str | None) -> str:
    chosen = MODE if mode is None else mode
    env = (os.environ.get("PPS_CLOSING_LINE") or "").strip().lower()
    if env in _VALID_MODES:
        chosen = env
    chosen = (chosen or "").strip().lower() if isinstance(chosen, str) else "off"
    return chosen if chosen in _VALID_MODES else "off"


def closing_line(
    prompt: str,
    invoker_channel: str | None,
    is_harness: bool = False,
    mode: str | None = None,
) -> tuple[str, str]:
    """Return (text, kind); kind is "none", "trigger" or "standing"."""
    try:
        chosen = _resolve_mode(mode)
        if chosen == "off":
            return ("", "none")
        spoken = spoken_text(prompt, invoker_channel, is_harness)
        if not spoken:
            return ("", "none")
        if chosen == "trigger":
            return (TRIGGER_LINE, "trigger") if points_back(spoken) else ("", "none")
        return (STANDING_LINE, "standing")
    except Exception:
        return ("", "none")
