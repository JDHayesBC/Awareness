"""Pytest tests for issue #394 — the output-boundary gate splits long clean
PROMPTED replies instead of refusing them, drops desync-stale replies, and
records what the room actually heard (#346). No live grid; Corrade is stubbed.

    PYTHONPATH=<repo> pps/venv/bin/python3 -m pytest haven/anchorage -q
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("SL_CORRADE", "0")
os.environ.setdefault("ENTITY_NAME", "lyra")

import pytest

from haven.anchorage import sl_daemon as d

UID_A = "a1b2c3d4-0000-1111-2222-333344445555"
UID_B = "b2c3d4e5-1111-2222-3333-444455556666"


def _sentences(n_chars: int) -> str:
    base = ("The harbour lamps came on one by one. Somebody was grilling fish "
            "down the pier! Does the tide table say anything about tomorrow? ")
    out = ""
    while len(out) < n_chars:
        out += base
    return out[:n_chars].rsplit(" ", 1)[0] + "."


def _norm(s: str) -> str:
    return "".join(s.split())


class FakeCorrade:
    def __init__(self):
        self.said: list[str] = []
        self.ims: list[tuple[str, str]] = []
        self.fail_on: int | None = None

    def _maybe_fail(self):
        if self.fail_on is not None and len(self.said) + len(self.ims) >= self.fail_on:
            raise RuntimeError("boom")

    def say(self, text):
        self._maybe_fail()
        self.said.append(text)

    def im(self, text, agent=None):
        self._maybe_fail()
        self.ims.append((agent, text))


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    fake = FakeCorrade()
    monkeypatch.setattr(d, "_corrade_client", fake)
    monkeypatch.setattr(d, "_prims", {})
    monkeypatch.setattr(d, "_BOUNDARY_CHUNK_PAUSE_S", 0)
    monkeypatch.setattr(d, "_boundary_refusals_path", lambda: tmp_path / "r.jsonl")
    d._boundary_last_notice.clear()
    d._pending_refusal_notice = None
    d._own_lines.clear()
    yield fake
    d._boundary_last_notice.clear()
    d._pending_refusal_notice = None
    d._own_lines.clear()


def run(coro):
    return asyncio.run(coro)


def test_377_char_prompted_splits_without_loss(env):
    text = _sentences(377)
    assert len(text) <= 377 and len(text) > 250
    heard = run(d._deliver_speech(text, prompted=True))
    assert len(env.said) >= 2
    assert all(len(c) <= 250 for c in env.said)
    assert _norm("".join(env.said)) == _norm(text)
    assert _norm(heard) == _norm(text)


def test_251_char_prompted_splits_not_refused(env):
    # 41 six-letter words + 41 spaces would be 287; build exactly 251 chars.
    text = " ".join(["lantern"] * 31)[:251].rstrip()   # 31*7 + 30 = 247
    text = text + " ok." if len(text) < 251 else text
    text = text + "x" * (251 - len(text))
    assert len(text) == 251
    heard = run(d._deliver_speech(text, prompted=True))
    assert len(env.said) == 2
    assert d._BOUNDARY_REFUSAL_LINE not in env.said
    assert all(len(c) <= 250 for c in env.said)
    assert _norm(heard) == _norm(text)


def test_unprompted_long_is_refused_silently(env):
    text = _sentences(377)
    assert run(d._deliver_speech(text)) is None
    assert env.said == [] and env.ims == []
    assert d._pending_refusal_notice and "not delivered" in d._pending_refusal_notice


def test_over_hard_cap_refused_canned_once_then_cooldown(env):
    text = _sentences(700)
    assert run(d._deliver_speech(text, prompted=True)) == d._BOUNDARY_REFUSAL_LINE
    assert env.said == [d._BOUNDARY_REFUSAL_LINE]
    assert run(d._deliver_speech(text, prompted=True)) is None
    assert env.said == [d._BOUNDARY_REFUSAL_LINE]
    # a different audience still gets its apology
    assert run(d._deliver_speech(text, im_to=UID_A, prompted=True)) == d._BOUNDARY_REFUSAL_LINE
    assert env.ims == [(UID_A, d._BOUNDARY_REFUSAL_LINE)]


@pytest.mark.parametrize("prompted", [True, False])
def test_short_marker_refused(env, prompted):
    run(d._deliver_speech("hello [clock] there", prompted=prompted))
    assert "hello [clock] there" not in env.said
    assert all("[clock]" not in s for s in env.said)


def test_marker_in_long_prompted_refuses_whole(env):
    text = _sentences(400) + " Carrying in: something private."
    heard = run(d._deliver_speech(text, prompted=True))
    assert heard == d._BOUNDARY_REFUSAL_LINE
    assert env.said == [d._BOUNDARY_REFUSAL_LINE]   # no partial send


def test_unpunctuated_sentence_splits_at_whitespace(env):
    words = [f"word{i}" for i in range(60)]
    text = " ".join(words)
    assert 250 < len(text) <= 600
    run(d._deliver_speech(text, prompted=True))
    assert len(env.said) >= 2 and all(len(c) <= 250 for c in env.said)
    got = " ".join(env.said).split()
    assert got == words        # whole words only, none cut or lost


def test_emote_stays_with_following_text():
    chunks = d._split_for_chat("*waves a hand.* " + _sentences(300))
    assert chunks[0].startswith("*waves a hand.* The")


def test_comma_split_for_long_sentence():
    text = ", ".join(f"clause number {i} goes here" for i in range(15)) + "."
    chunks = d._split_for_chat(text)
    assert all(len(c) <= 250 for c in chunks)
    assert all(c.endswith(",") for c in chunks[:-1])
    assert _norm("".join(chunks)) == _norm(text)


def test_unsplittable_giant_word_refused():
    assert d._boundary_plan("a" * 300, prompted=True) is None


def test_boundary_ok_unchanged():
    assert d._boundary_ok("short") is True
    assert d._boundary_ok("x" * 251) is False
    assert d._boundary_ok("[urgency] hi") is False


def test_refusal_is_logged_to_jsonl(env, tmp_path):
    run(d._deliver_speech("nothing [smoke] here", prompted=True))
    import json
    row = json.loads((tmp_path / "r.jsonl").read_text().splitlines()[0])
    assert row["len"] == 20 and row["prompted"] is True and row["im"] is False
    assert row["text"] == "nothing [smoke] here" and "marker" in row["reason"]


def test_refusal_log_failure_never_raises(env, monkeypatch, tmp_path):
    monkeypatch.setattr(d, "_boundary_refusals_path", lambda: tmp_path / "f" / "g")
    (tmp_path / "f").write_text("a file, so mkdir fails")
    run(d._deliver_speech("x [smoke]", prompted=True))   # must not raise


def test_send_failure_stops_and_reports_partial(env):
    env.fail_on = 1
    text = _sentences(450)
    heard = run(d._deliver_speech(text, prompted=True))
    assert len(env.said) == 1
    assert heard == env.said[0]


# ---- call sites: desync drop + capture-after-delivery ------------------------

class FakeInvoker:
    def __init__(self, desync):
        self.desync_suspected = desync
        self.context_size = 1
        self.turn_count = 1


class FakeBrain:
    def __init__(self, reply, desync=False):
        self.reply = reply
        self.invoker = FakeInvoker(desync)
        self.captured: list[tuple[str, str]] = []
        self.seen_events: list[list[str]] = []

    async def capture_to_river(self, author, content, *, is_lyra, channel):
        self.captured.append((author, content))

    async def respond(self, speaker, text, *, is_dm, addressed):
        return self.reply

    async def perceive(self, scene, events, **kw):
        self.seen_events.append(list(events))
        return self.reply


class Payload:
    def __init__(self, addressed=True, idle=False):
        self.addressed = addressed
        self.idle = idle
        self.text = ""
        self.speaker = ""
        self.deltas = ["- a gull lands"]
        self.trigger = "t"
        self.reply_to_uuid = ""
        self.reply_via = "local"
        self.idle_prompt = None


@pytest.fixture
def wire(monkeypatch):
    async def _noop(*a, **k):
        return None

    async def _scene():
        return "scene"
    monkeypatch.setattr(d, "_push_status", _noop)
    monkeypatch.setattr(d, "_live_scene", _scene)
    monkeypatch.setattr(d, "SL_CAPTURE", True)
    monkeypatch.setattr(d, "_perception", None)
    monkeypatch.setattr(d, "_hb", None)

    def install(brain):
        monkeypatch.setattr(d, "_get_brain", lambda: brain)
    return install


@pytest.mark.parametrize("path", ["inbound", "perception"])
def test_desync_reply_not_delivered_or_captured(env, wire, path):
    brain = FakeBrain("An answer to some other question entirely.", desync=True)
    wire(brain)
    if path == "inbound":
        run(d._handle_inbound("Pat", "hi", is_dm=False, addressed=True))
        assert brain.captured == [("Pat", "hi")]       # only the inbound turn
    else:
        run(d._handle_perception(Payload(addressed=False)))
        assert brain.captured == []
    assert env.said == [] and env.ims == []


def test_desync_reply_to_someone_waiting_gets_the_canned_line(env, wire):
    stale = "An answer to some other question entirely."
    brain = FakeBrain(stale, desync=True)
    wire(brain)
    run(d._handle_perception(Payload(addressed=True)))
    # The stale text is never spoken or recorded; the fixed line is, once.
    assert env.said == [d._BOUNDARY_REFUSAL_LINE] and env.ims == []
    assert [c[1] for c in brain.captured] == [d._BOUNDARY_REFUSAL_LINE]
    # Same audience inside the cooldown: silence, not a second apology.
    run(d._handle_perception(Payload(addressed=True)))
    assert env.said == [d._BOUNDARY_REFUSAL_LINE]
    assert all(stale not in c[1] for c in brain.captured)


def test_desync_on_an_idle_beat_says_nothing(env, wire):
    brain = FakeBrain("Stale interior text nobody asked for.", desync=True)
    wire(brain)
    run(d._handle_perception(Payload(addressed=True, idle=True)))
    assert env.said == [] and env.ims == [] and brain.captured == []


def test_capture_gets_delivered_text_after_split(env, wire):
    text = _sentences(400)
    brain = FakeBrain(text)
    wire(brain)
    run(d._handle_perception(Payload(addressed=True)))
    assert len(env.said) >= 2
    assert len(brain.captured) == 1
    assert _norm(brain.captured[0][1]) == _norm(text)


def test_silent_refusal_not_captured_and_brain_is_told(env, wire):
    brain = FakeBrain(_sentences(400))
    wire(brain)
    run(d._handle_perception(Payload(addressed=False)))   # unprompted
    assert env.said == [] and brain.captured == []
    brain.reply = None
    run(d._handle_perception(Payload(addressed=False)))
    assert any("not delivered" in e for e in brain.seen_events[-1])
    run(d._handle_perception(Payload(addressed=False)))
    assert not any("not delivered" in e for e in brain.seen_events[-1])  # once only


def test_canned_line_is_what_gets_captured(env, wire):
    brain = FakeBrain(_sentences(700))
    wire(brain)
    run(d._handle_inbound("Pat", "q?", is_dm=False, addressed=True))
    assert brain.captured[-1] == (d.DISPLAY_NAME, d._BOUNDARY_REFUSAL_LINE)
