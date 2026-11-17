"""Pick the ambient_recall query for a UserPromptSubmit turn (#409).

In a terminal session the prompt is what the person typed, so it is the query.
In a brain session (a headless Claude driven by the Haven bot or the Second Life
daemon) the prompt is a constructed turn: headers, an ambient block, instructions,
and the spoken lines as a small part. Querying with all of that dilutes retrieval
with boilerplate that is the same every turn, so this module pulls out just the
spoken text.

Pure: no I/O, no imports beyond the stdlib. Never raises on odd input; when
nothing parses it returns the prompt unchanged.

Prompt shapes (read from the code that builds them):
  Haven  haven/bot.py, _process_batch (prompt assembly) and format_batch_line:
         "[Haven messages in #<room8>] (N messages arrived together)\\n"
         then one line per message; human lines are "[msg N] Display (user): text",
         bot lines are "Display (user): text" with no "[msg N]". Optional
         "\\n\\n[open ask] ..." note, then "\\n\\nRespond as yourself in chat. ...".
  SL     haven/brain/entity_brain.py, respond():
         "[sl message from <speaker>]\\n<speaker>: <text>\\n\\nRespond as yourself. ..."
         The other SL entry point, perceive(), lists free-form world events and has
         no spoken-line shape, so it is left on the unchanged fallback.
"""
from __future__ import annotations

import re

MAX_QUERY_CHARS = 800

_HAVEN_HEADER_RE = re.compile(r"^\[Haven messages in #[^\]\n]*\][^\n]*\n", re.MULTILINE)
_HAVEN_INSTRUCTION = "\n\nRespond as yourself in chat."
_HAVEN_OPEN_ASK = "\n\n[open ask] "
_MSG_START_RE = re.compile(r"^\[msg \d+\] ", re.MULTILINE)
_MSG_PREFIX_RE = re.compile(r"^\[msg \d+\] [^\n]*?\([^()\s]*\): ?")

_SL_HEADER_RE = re.compile(r"^\[sl message from ([^\n]*)\]\n", re.MULTILINE)
_SL_INSTRUCTION = "\n\nRespond as yourself."


def _squash(text: str) -> str:
    return " ".join(text.split())


def _cap(text: str, max_chars: int) -> str:
    return text[-max_chars:] if len(text) > max_chars else text


def _haven_query(prompt: str, max_chars: int) -> str:
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
    starts = [m.start() for m in _MSG_START_RE.finditer(body)]
    if not starts:
        return ""
    texts = []
    for i, st in enumerate(starts):
        chunk = body[st:starts[i + 1] if i + 1 < len(starts) else len(body)]
        chunk = _MSG_PREFIX_RE.sub("", chunk, count=1)
        chunk = _squash(chunk)
        if chunk:
            texts.append(chunk)
    return _cap("\n".join(texts), max_chars)


def _sl_query(prompt: str, max_chars: int) -> str:
    headers = list(_SL_HEADER_RE.finditer(prompt))
    if not headers:
        return ""
    last = headers[-1]
    speaker = last.group(1)
    body = prompt[last.end():]
    end = body.rfind(_SL_INSTRUCTION)
    if end != -1:
        body = body[:end]
    lead = f"{speaker}: "
    if body.startswith(lead):
        body = body[len(lead):]
    return _cap(_squash(body), max_chars)


def extract_turn_query(
    prompt: str,
    invoker_channel: str | None,
    max_chars: int = MAX_QUERY_CHARS,
) -> str:
    """Return the text to use as the ambient_recall query for this turn.

    Haven or SL brain prompts yield the spoken text (see module docstring).
    Anything else, or a prompt where nothing parses, comes back unchanged.
    """
    if not isinstance(prompt, str) or not invoker_channel:
        return prompt
    channel = invoker_channel.strip().lower()
    if channel == "haven":
        parsed = _haven_query(prompt, max_chars)
    elif channel == "sl":
        parsed = _sl_query(prompt, max_chars)
    else:
        return prompt
    return parsed or prompt
