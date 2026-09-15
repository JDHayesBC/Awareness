"""The summarizer prompt must actually contain the conversation (#332 regression).

Commit 8b039c2 rewrote the prompt to carry epistemic-status instructions and, in the
same edit, deleted the tail that interpolated `{conversation_text}`. The code still
built and truncated `conversation_text` — it just never used it. Every call then asked
the model to summarize nothing, and the model answered by restating the instructions
and asking for the content ("Please provide the conversation history"). Nothing failed
loudly: the endpoint returned 200 and wrote the non-summary into long-term memory.

Measured 2026-09-15 with a k=3 A/B over 20 real ranges: 58 of 60 calls on the patched
prompt produced a non-summary, versus 0 of 60 on the previous prompt; mean output fell
from 4518 to 834 characters.

These are source-level invariants, which is a real limit — they assert the prompt
*names* the conversation, not that the model received it. They are here because the
defect was exactly a missing name, and because the endpoint is a long async handler
with no seam to call the prompt construction on its own.
"""
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "pps" / "docker" / "server_http.py"


@pytest.fixture(scope="module")
def prompt_body() -> str:
    src = SRC.read_text(encoding="utf-8")
    start = src.index('prompt = f"""')
    return src[start + len('prompt = f"""'):src.index('"""', start + 13)]


def test_prompt_interpolates_the_conversation(prompt_body):
    assert "{conversation_text}" in prompt_body, (
        "the summarizer prompt does not reference {conversation_text} — the model is "
        "being asked to summarize nothing (regression of 8b039c2)"
    )


def test_conversation_text_reaches_the_prompt_not_just_its_own_truncation():
    """The general shape of the bug: built, truncated, never handed to the model.

    Checking merely that the variable is "read somewhere" is too weak — the
    length-guard on the line after the assignment reads it, so that check passes
    on the broken code. What matters is a use at or after the prompt statement.
    """
    src = SRC.read_text(encoding="utf-8")
    lines = src.splitlines()
    prompt_line = next(i for i, ln in enumerate(lines) if 'prompt = f"""' in ln)
    later = [
        i for i, ln in enumerate(lines)
        if i >= prompt_line and "conversation_text" in ln
    ]
    assert later, (
        "conversation_text is built and truncated but never used at or after the "
        "prompt construction — it never reaches the model"
    )


@pytest.mark.parametrize("placeholder", ["{len(messages)}", "{', '.join(channels)}"])
def test_prompt_keeps_its_provenance_header(prompt_body, placeholder):
    """How many messages, and from which channels, is part of what the summary means."""
    assert placeholder in prompt_body


def test_epistemic_instructions_survived_the_fix(prompt_body):
    """The #332 content must still be there — the fix restores the tail, not the old prompt."""
    for phrase in ("Epistemic status must survive summarization",
                   "ASSERTED but never checked",
                   "fogging genuinely verified work"):
        assert phrase in prompt_body, f"lost #332 content: {phrase!r}"
