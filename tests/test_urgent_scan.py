"""Tests for scripts/urgent_scan.py — the [urgent] klaxon.

These lock one thing: **the instruction must name the label the check actually honors.**

2026-09-17: the block said "park it (label + one line on why it's set down)" without
naming which label. I picked `status:blocked` by reasonable inference, wrote a real
parking reason on #331 — and the klaxon kept firing, because only `triage:parked`
silences it. An under-specified instruction gets filled in with a plausible guess, and
a plausible guess is indistinguishable from a correct one right up until the signal
fails to go quiet. If a refactor lets the text and the check drift apart again, this
is the alarm.
"""

import datetime as dt
import sys
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import urgent_scan  # noqa: E402


def _cache(n):
    return {
        "fetched_at": dt.datetime.now().astimezone().isoformat(),
        "issues": [
            {"number": 900 + i, "title": "a thing that needs a look", "priority": "high",
             "created_at": "2026-09-15T00:00:00Z", "updated_at": "2026-09-15T00:00:00Z"}
            for i in range(n)
        ],
    }


def _block(n):
    with mock.patch.object(urgent_scan, "load_cache", lambda: _cache(n)):
        return urgent_scan.format_urgent_block()


def test_single_issue_instruction_names_the_parking_label():
    out = _block(1)
    assert urgent_scan.PARKED_LABEL in out, out


def test_multi_issue_instruction_names_the_parking_label():
    out = _block(3)
    assert urgent_scan.PARKED_LABEL in out, out


def test_the_named_label_is_the_one_that_actually_parks():
    """The whole point: what the text tells you to do must be what silences the block."""
    assert urgent_scan._is_parked([{"name": urgent_scan.PARKED_LABEL}]) is True
    assert urgent_scan._is_parked([urgent_scan.PARKED_LABEL]) is True


def test_a_plausible_wrong_guess_does_not_park():
    """status:blocked reads like a park and is not one — that is the failure, kept honest."""
    for guess in ("status:blocked", "triage:park", "parked", "wontfix"):
        assert urgent_scan._is_parked([{"name": guess}]) is False, guess


def test_empty_board_is_silent():
    assert _block(0) == ""
