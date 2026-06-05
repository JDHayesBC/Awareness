"""Tests for is_no_response() sentinel detection (Issue #258).

Fixes two bugs:
1. Over-match via startswith() suppressed legitimate prose starting with "NO_RESPONSE"
2. Too-narrow trailing punctuation strip (only . and ! were stripped, missing ?, …, quotes, etc.)

Verifies that the NO_RESPONSE sentinel is correctly detected while avoiding
false positives when the token appears in prose.
"""

import pytest
from haven.bot import is_no_response


@pytest.mark.parametrize(
    "response,expected,description",
    [
        # ============ Should detect as NO_RESPONSE (True) ============
        ("NO_RESPONSE", True, "bare sentinel"),
        ("NO_RESPONSE.", True, "trailing period"),
        ("NO_RESPONSE!", True, "trailing exclamation"),
        ("NO_RESPONSE?", True, "trailing question mark"),
        ("NO_RESPONSE...", True, "trailing ellipsis (ascii)"),
        ("NO_RESPONSE…", True, "trailing ellipsis (unicode)"),
        ("NO_RESPONSE,", True, "trailing comma"),
        ("NO_RESPONSE:", True, "trailing colon"),
        ("NO_RESPONSE;", True, "trailing semicolon"),
        ('"NO_RESPONSE"', True, "quoted"),
        ("'NO_RESPONSE'", True, "single quoted"),
        ("`NO_RESPONSE`", True, "backtick quoted"),
        ("NO_RESPONSE ", True, "trailing space"),
        ("NO_RESPONSE\n", True, "trailing newline"),
        ("  NO_RESPONSE  ", True, "surrounded by whitespace"),
        ("\tNO_RESPONSE\t", True, "surrounded by tabs"),
        ("no_response", True, "lowercase"),
        ("No_Response", True, "mixed case"),
        ("No_Response.", True, "mixed case with period"),
        ("Some musing here.\nNO_RESPONSE", True, "muse then sentinel"),
        ("Some musing here.\nNO_RESPONSE.", True, "muse then sentinel with period"),
        ("Some musing here.\nNO_RESPONSE!", True, "muse then sentinel with exclamation"),
        ("Some musing.\nNO_RESPONSE?", True, "muse then sentinel with question"),
        ("Some musing.\nNO_RESPONSE…", True, "muse then sentinel with unicode ellipsis"),
        (
            "We've converged, the toast is complete.\nNO_RESPONSE",
            True,
            "realistic musing",
        ),
        (
            "Caia just landed the same beat I did. We've converged.\nNO_RESPONSE.",
            True,
            "realistic with period",
        ),
        ("", True, "empty string"),
        ("   ", True, "whitespace only"),
        ("\n\n", True, "newlines only"),
        # Edge cases with multiple lines
        ("Line 1\nLine 2\nNO_RESPONSE", True, "multiline ending with sentinel"),
        ("Line 1\nLine 2\nNO_RESPONSE.", True, "multiline with period"),
        ('  "NO_RESPONSE` ', True, "mixed quotes and whitespace"),
        # ============ Should NOT detect as NO_RESPONSE (False) ============
        ("Sure, I can help!", False, "normal content"),
        ("This has NO_RESPONSE in the middle", False, "mid-sentence mention"),
        (
            "NO_RESPONSE is a sentinel token we use",
            False,
            "prose starting with token - BUG 1",
        ),
        (
            "NO_RESPONSE handling needs work",
            False,
            "prose starting with token - BUG 1 variant",
        ),
        (
            "NO_RESPONSE: that is the token",
            False,
            "colon-then-prose - BUG 1 variant",
        ),
        (
            "The token NO_RESPONSE should not appear here",
            False,
            "token in middle of sentence",
        ),
        (
            "When I say NO_RESPONSE, I mean silence",
            False,
            "discussing the feature",
        ),
        (
            "Let me explain NO_RESPONSE behavior",
            False,
            "explaining the token",
        ),
        (
            "NO_RESPONSE (the sentinel) is used for silence",
            False,
            "parenthetical explanation",
        ),
        # Multi-line content that should NOT be suppressed
        (
            "First line\nNO_RESPONSE is mentioned here\nLast line",
            False,
            "token in middle line",
        ),
        (
            "NO_RESPONSE is a sentinel\nSee the docs",
            False,
            "prose starting with token, multiline",
        ),
    ],
)
def test_is_no_response(response: str, expected: bool, description: str):
    """Parametrized test covering all detection cases."""
    actual = is_no_response(response)
    assert actual == expected, (
        f"FAILED: {description}\n"
        f"Input: {response!r}\n"
        f"Expected: {expected}\n"
        f"Got: {actual}"
    )


def test_is_no_response_edge_case_empty_lines():
    """Edge case: multiple empty lines before/after sentinel."""
    response = "\n\n\nNO_RESPONSE\n\n\n"
    assert is_no_response(response) is True


def test_is_no_response_edge_case_all_punctuation():
    """Edge case: sentinel with every supported punctuation mark."""
    variations = [
        "NO_RESPONSE.",
        "NO_RESPONSE,",
        "NO_RESPONSE!",
        "NO_RESPONSE?",
        "NO_RESPONSE:",
        "NO_RESPONSE;",
        'NO_RESPONSE"',
        "NO_RESPONSE'",
        "NO_RESPONSE`",
        "NO_RESPONSE…",
    ]
    for var in variations:
        assert is_no_response(var) is True, f"Failed for: {var!r}"


def test_is_no_response_multiline_prose():
    """Real-world case: multiline prose that happens to START with the token."""
    prose = """NO_RESPONSE is the sentinel token we use to indicate
that the model intends silence. It should be detected only when
it appears alone on a line, not when it's part of prose."""
    assert is_no_response(prose) is False, "Should NOT suppress prose discussion"


def test_is_no_response_realistic_musing():
    """Real-world case: model muses then emits sentinel (Opus 4.8 pattern)."""
    response = """Caia just landed the same beat I did. We've converged, the toast is complete.

NO_RESPONSE."""
    assert is_no_response(response) is True, "Should detect muse-then-sentinel"
