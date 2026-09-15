"""Tests for is_no_response() sentinel detection (Issues #258, #283).

Current implementation (haven/bot.py): detects ONLY the double-bracket
``[[NO_RESPONSE]]`` form (contains check) plus empty/whitespace inputs.
Bare ``NO_RESPONSE`` without brackets is intentionally NOT detected — the
model is instructed to use the bracketed form, and the bare token can appear
in ordinary prose discussion without meaning silence.

Key regression cases from #283:
- ``[[NO_RESPONSE]]`` anywhere in output → silence (even after musing)
- ``Self-scan...`` preamble is caught by a separate defense-in-depth guard
  (not this function), so this test does not cover that path.
- Bare ``NO_RESPONSE`` in prose → posts normally (the old first/last-line
  rule was removed to prevent false positives).
"""

import pytest
from haven.bot import is_no_response


@pytest.mark.parametrize(
    "response,expected,description",
    [
        # ===== Should detect as NO_RESPONSE (True) =====
        # Core: double-bracket form, anywhere
        ("[[NO_RESPONSE]]", True, "bare double-bracket sentinel"),
        ("  [[NO_RESPONSE]]  ", True, "surrounded by whitespace"),
        ("\n[[NO_RESPONSE]]\n", True, "surrounded by newlines"),
        (
            "Let me think about this.\n[[NO_RESPONSE]]",
            True,
            "musing then sentinel on last line",
        ),
        (
            "Caia just landed the same beat. We've converged.\n\n[[NO_RESPONSE]]",
            True,
            "realistic muse-then-sentinel (issue #283 regression)",
        ),
        (
            "[[NO_RESPONSE]] is what I'll emit here.",
            True,
            "sentinel at start of sentence — contains check detects it",
        ),
        (
            "Thinking... [[NO_RESPONSE]] done.",
            True,
            "sentinel mid-sentence — the key fix from #283 (placement-robust)",
        ),
        (
            "I considered replying but [[NO_RESPONSE]] is right.",
            True,
            "sentinel embedded in prose reasoning",
        ),
        # Empty / whitespace → silence (no content to post)
        ("", True, "empty string"),
        ("   ", True, "whitespace only"),
        ("\n\n", True, "newlines only"),
        ("\t\t", True, "tabs only"),
        # ===== Should NOT detect as NO_RESPONSE (False) =====
        # Bare NO_RESPONSE without brackets is just prose now
        ("NO_RESPONSE", False, "bare token without brackets → prose"),
        ("NO_RESPONSE.", False, "bare token with period → prose"),
        ("Some musing.\nNO_RESPONSE", False, "legacy first/last-line form → no longer detected"),
        ("NO_RESPONSE is the sentinel", False, "prose starting with bare token"),
        ("The token NO_RESPONSE means silence", False, "token mid-prose"),
        # Normal responses
        ("Sure, I can help!", False, "normal content"),
        ("Hello there!", False, "greeting"),
        ("That's a great question.", False, "normal reply"),
        ("I'll look into that.", False, "normal reply 2"),
        # Near-misses — brackets matter
        ("[NO_RESPONSE]", False, "single brackets — not the sentinel"),
        ("(NO_RESPONSE)", False, "parens — not the sentinel"),
        ("[[no_response]]", False, "lowercase double-bracket — not the sentinel"),
        ("[[NO_RESPONSE]", False, "mismatched brackets"),
        ("[[ NO_RESPONSE ]]", False, "spaces inside brackets"),
    ],
)
def test_is_no_response(response: str, expected: bool, description: str):
    """Parametrized coverage of the double-bracket sentinel detection."""
    actual = is_no_response(response)
    assert actual == expected, (
        f"FAILED: {description}\n"
        f"Input: {response!r}\n"
        f"Expected: {expected}\n"
        f"Got: {actual}"
    )


def test_double_bracket_is_placement_robust():
    """Issue #283 regression: sentinel detected regardless of where it falls.

    The old first/last-line rule failed when the model mused first (self-scan,
    paragraph of reasoning) and placed the sentinel mid-text.  The contains
    check finds it anywhere.
    """
    cases = [
        "[[NO_RESPONSE]]",                                         # alone
        "Musing.\n[[NO_RESPONSE]]",                               # last line
        "[[NO_RESPONSE]]\nMore text",                             # first line
        "Prefix [[NO_RESPONSE]] suffix",                          # mid-sentence
        "Line 1\nLine 2\n[[NO_RESPONSE]]\nLine 4",               # middle line
    ]
    for text in cases:
        assert is_no_response(text) is True, f"Should detect sentinel in: {text!r}"


def test_bare_no_response_is_not_sentinel():
    """Bare NO_RESPONSE without double brackets is never silence now (#283).

    The model is instructed to use [[NO_RESPONSE]]; bare token can appear in
    prose ('NO_RESPONSE is the sentinel we use') and must not vanish.
    """
    prose_cases = [
        "NO_RESPONSE",
        "NO_RESPONSE.",
        "Some musing.\nNO_RESPONSE",
        "NO_RESPONSE is the sentinel we use for silence.",
        "We discussed NO_RESPONSE handling.",
    ]
    for text in prose_cases:
        assert is_no_response(text) is False, f"Should NOT suppress: {text!r}"


def test_empty_and_whitespace_are_silence():
    """Empty / whitespace-only responses count as silence — nothing to post."""
    for text in ("", "   ", "\n\n\n", "\t\t", " \n \t "):
        assert is_no_response(text) is True, f"Should treat as silence: {text!r}"
