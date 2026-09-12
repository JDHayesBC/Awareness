"""Pytest tests for issue #323 — "SL brain loops its own lines when
idle-driven with a silent partner".

Two independent fixes under test:

1. Self-repeat suppression (``sl_daemon._is_self_repeat`` / ``_remember_own_line``):
   drop a candidate spoken line that's a near-verbatim repeat of something this
   entity already said recently.
2. Idle back-off (``heartbeat.IdleBackoff``): the idle-watchdog's own polling
   interval widens exponentially while nobody but me has spoken for a long
   while, and resets to full cadence the moment someone else speaks — but a
   ``♪ now playing`` track-change event must NEVER count as "someone spoke".

No live grid: pure logic + a hand-built Corrade event dict, same style as
test_prettify_speaker.py / test_hotpath_rotation.py. Run:

    PYTHONPATH=<repo> pps/venv/bin/python3 -m pytest haven/anchorage -q
"""

from __future__ import annotations

import os

os.environ.setdefault("SL_CORRADE", "0")  # skip Corrade client build at import
os.environ.setdefault("ENTITY_NAME", "lyra")

import pytest

from haven.anchorage import heartbeat
from haven.anchorage import sl_daemon as d

UID_SELF = "a1b2c3d4-0000-1111-2222-333344445555"
UID_OTHER = "b2c3d4e5-1111-2222-3333-444455556666"


@pytest.fixture(autouse=True)
def _clean_own_lines():
    """Each test gets a pristine ring buffer — the real one is module state."""
    d._own_lines.clear()
    yield
    d._own_lines.clear()


# --------------------------------------------------------------------------- #
# 1. Self-repeat suppression
# --------------------------------------------------------------------------- #

def test_exact_repeat_is_suppressed():
    d._remember_own_line("That one's less subtle.")
    assert d._is_self_repeat("That one's less subtle.") is True


def test_exact_repeat_case_and_whitespace_insensitive():
    d._remember_own_line("He's not wrong.")
    # Different case + extra whitespace — still the "same" line.
    assert d._is_self_repeat("  he's   NOT wrong.  ") is True


def test_near_dupe_repeat_is_suppressed():
    d._remember_own_line("Indefinitely renewable, apparently.")
    # A near-verbatim regeneration of the same line (ratio > 0.9).
    assert d._is_self_repeat("Indefinitely renewable, apparently") is True


def test_genuinely_new_line_is_not_suppressed():
    d._remember_own_line("The DJ needed to check something.")
    assert d._is_self_repeat("Strong ones.") is False


def test_ring_buffer_window_forgets_old_lines():
    # SL_REPEAT_WINDOW lines evict the oldest — a line pushed out of the window
    # should no longer be treated as a repeat.
    window = d.SL_REPEAT_WINDOW
    d._remember_own_line("the one that should fall off")
    for i in range(window):
        d._remember_own_line(f"filler line number {i}")
    assert d._is_self_repeat("the one that should fall off") is False


def test_filter_speech_drops_self_repeat_non_idle():
    d._remember_own_line("Strong ones.")
    assert d._filter_speech("Strong ones.", idle=False) == ""


def test_filter_speech_passes_new_line_non_idle():
    assert d._filter_speech("A brand new thought.", idle=False) == "A brand new thought."


# --------------------------------------------------------------------------- #
# 2. Emote vs. spoken-line detection (the idle-quiet gate's discriminator)
# --------------------------------------------------------------------------- #

def test_pure_emote_is_detected():
    assert d._speech_is_pure_emote("*opens eyes*") is True
    assert d._speech_is_pure_emote("*a quiet sound*\n*settles back*") is True


def test_mixed_emote_and_dialogue_is_not_pure_emote():
    assert d._speech_is_pure_emote("*opens eyes*\n\nThat one's less subtle.") is False


def test_bare_dialogue_is_not_pure_emote():
    assert d._speech_is_pure_emote("He's not wrong.") is False


def test_empty_speech_counts_as_pure_emote():
    assert d._speech_is_pure_emote("") is True
    assert d._speech_is_pure_emote("   \n  ") is True


# --------------------------------------------------------------------------- #
# 3. IdleBackoff — the pure back-off state machine (heartbeat.py)
# --------------------------------------------------------------------------- #

def test_backoff_not_quiet_right_after_activity():
    ib = heartbeat.IdleBackoff(quiet_after=1200.0)
    ib.note_other_speech(0.0)
    assert ib.is_quiet(600.0) is False
    assert ib.effective_floor(600.0, base_floor=120.0) == 120.0
    assert ib.should_suppress_speech(600.0) is False


def test_backoff_goes_quiet_after_threshold():
    ib = heartbeat.IdleBackoff(quiet_after=1200.0)
    ib.note_other_speech(0.0)
    assert ib.is_quiet(1201.0) is True
    assert ib.should_suppress_speech(1201.0) is True


def test_backoff_doubles_interval_per_idle_fire_while_quiet():
    ib = heartbeat.IdleBackoff(quiet_after=100.0, multiplier=2.0, cap=100000.0)
    ib.note_other_speech(0.0)
    now = 200.0  # already past quiet_after
    assert ib.effective_floor(now, base_floor=120.0) == 120.0  # factor still 1.0

    ib.note_idle_fire(now)
    assert ib.effective_floor(now, base_floor=120.0) == pytest.approx(240.0)

    ib.note_idle_fire(now)
    assert ib.effective_floor(now, base_floor=120.0) == pytest.approx(480.0)

    ib.note_idle_fire(now)
    assert ib.effective_floor(now, base_floor=120.0) == pytest.approx(960.0)


def test_backoff_caps_the_widened_interval():
    ib = heartbeat.IdleBackoff(quiet_after=100.0, multiplier=2.0, cap=300.0)
    ib.note_other_speech(0.0)
    now = 200.0
    for _ in range(10):  # far enough to blow past any reasonable cap
        ib.note_idle_fire(now)
    assert ib.effective_floor(now, base_floor=120.0) == 300.0


def test_backoff_no_growth_while_not_quiet():
    # note_idle_fire should be a no-op if called while the room is NOT quiet
    # (a real-tempo beat firing shouldn't grow the multiplier).
    ib = heartbeat.IdleBackoff(quiet_after=1200.0, multiplier=2.0, cap=100000.0)
    ib.note_other_speech(0.0)
    ib.note_idle_fire(10.0)  # well inside the quiet_after window — not quiet
    assert ib.effective_floor(10.0, base_floor=120.0) == 120.0


def test_backoff_other_speaker_resets_factor_and_clock():
    ib = heartbeat.IdleBackoff(quiet_after=100.0, multiplier=2.0, cap=100000.0)
    ib.note_other_speech(0.0)
    now = 200.0
    ib.note_idle_fire(now)
    ib.note_idle_fire(now)
    assert ib.effective_floor(now, base_floor=120.0) > 120.0  # widened

    ib.note_other_speech(210.0)  # someone else spoke — full reset
    assert ib.is_quiet(211.0) is False
    assert ib.effective_floor(211.0, base_floor=120.0) == 120.0
    assert ib.should_suppress_speech(211.0) is False


def test_backoff_addressed_is_same_reset_as_other_speech():
    # note_addressed is an alias — being addressed resets exactly like
    # someone-else-speaking does.
    assert heartbeat.IdleBackoff.note_addressed is heartbeat.IdleBackoff.note_other_speech


# --------------------------------------------------------------------------- #
# 4. Integration: sl_daemon._on_corrade_event must reset the backoff clock on
#    real other-speaker chat, but NEVER on a ♪ now-playing event.
# --------------------------------------------------------------------------- #

class _StubPerception:
    """Minimal stand-in for SLPerception — just enough surface for
    _on_corrade_event to run without a live Corrade client."""

    def __init__(self):
        self.self_names = {"lyrapattern", "lyra"}
        self.self_uuids = {UID_SELF}

    def ingest(self, event, now):
        return None


def _local_chat_event(uid: str, name: str, text: str) -> dict:
    return {
        "type": "Normal", "name": name, "message": text,
        "owner": uid, "item": uid, "entity": "Agent",
    }


def _nowplaying_event() -> dict:
    return {"notification": "nowplaying", "payload": {"artist": "Wang Chung", "title": "Dance Hall Days"}}


@pytest.fixture()
def _wired_backoff(monkeypatch):
    """Wire module-level _perception/_idle_backoff to test doubles for the
    duration of one test, restoring the originals after."""
    stub = _StubPerception()
    ib = heartbeat.IdleBackoff(quiet_after=1200.0, multiplier=2.0, cap=1800.0)
    ib.note_other_speech(0.0)  # start "not quiet"
    monkeypatch.setattr(d, "_perception", stub, raising=False)
    monkeypatch.setattr(d, "_idle_backoff", ib, raising=False)
    return ib


def test_nowplaying_event_does_not_reset_backoff(_wired_backoff, monkeypatch):
    ib = _wired_backoff
    # Push last_other far into the past (quiet), then feed a music event — it
    # must NOT reset the clock.
    ib._last_other = -100000.0
    monkeypatch.setattr(d.time, "time", lambda: 5000.0)
    d._on_corrade_event(_nowplaying_event())
    assert ib._last_other == -100000.0  # unchanged — still quiet


def test_other_speaker_local_chat_resets_backoff(_wired_backoff, monkeypatch):
    ib = _wired_backoff
    ib._last_other = -100000.0  # quiet
    monkeypatch.setattr(d.time, "time", lambda: 5000.0)
    d._on_corrade_event(_local_chat_event(UID_OTHER, "Someone Resident", "hey, look at that"))
    assert ib._last_other == 5000.0  # reset — someone else spoke


def test_own_echo_does_not_reset_backoff(_wired_backoff, monkeypatch):
    ib = _wired_backoff
    ib._last_other = -100000.0  # quiet
    monkeypatch.setattr(d.time, "time", lambda: 5000.0)
    # My own local-chat echo (self UUID) must not count as "someone else spoke".
    d._on_corrade_event(_local_chat_event(UID_SELF, "LyraPattern Resident", "hello there"))
    assert ib._last_other == -100000.0  # unchanged


def test_short_lines_are_never_self_repeats():
    """'hi' / 'yes' / '*nods*' repeat legitimately; the loop is paragraphs."""
    pass  # d imported at module top
    d._own_lines.clear()
    for line in ("hi", "yes", "*nods*", "thank you"):
        d._remember_own_line(line)
        assert d._is_self_repeat(line) is False
