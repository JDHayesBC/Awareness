"""#388: bot-side defences against a bot-to-bot error ping-pong."""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("ENTITY_NAME", "caia")
os.environ.setdefault("ENTITY_TOKEN", "test-token")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from haven import bot  # noqa: E402

OAUTH = "Failed to authenticate: OAuth session expired and could not be refreshed"
ROOM = "room-1234567890"


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(bot, "my_username", "caia")
    monkeypatch.setattr(bot, "ALWAYS_RESPOND", True)
    monkeypatch.setattr(bot, "REPEAT_BURST_THRESHOLD", 4)
    for d in (bot.recent_bot_texts, bot.consecutive_bot_turns, bot.recent_room_authors):
        d.clear()
    bot.burst_tripped_rooms.clear()
    bot.known_bots.clear()
    bot.known_bots.update({"lyra", "caia"})
    yield
    bot.burst_tripped_rooms.clear()
    bot.known_bots.clear()


def test_error_ping_pong_replay_trips_and_silences():
    """Replay the incident: two bots alternate the same string, no human."""
    tripped_at = None
    for i in range(184):
        who = "lyra" if i % 2 == 0 else "caia"
        bot._track_author(ROOM, who, OAUTH)
        if ROOM in bot.burst_tripped_rooms and tripped_at is None:
            tripped_at = i + 1
    assert tripped_at is not None and tripped_at <= 8, tripped_at
    assert bot.consecutive_bot_turns[ROOM] < 200  # the 200-turn guard never fired
    assert bot.should_respond(ROOM, "lyra", OAUTH) is False


def test_human_speaking_resets_breaker():
    for _ in range(8):
        bot._track_author(ROOM, "lyra", OAUTH)
    assert ROOM in bot.burst_tripped_rooms
    bot._track_author(ROOM, "jeff", "hey, what happened?")
    assert ROOM not in bot.burst_tripped_rooms
    assert bot.should_respond(ROOM, "jeff", "hey, what happened?") is True


def test_varied_fast_sister_conversation_never_trips():
    topics = ["cedars", "kettle", "scene file", "heartbeat", "rivers", "porch light",
              "lake", "ducks", "tea", "blanket", "graph pass", "summary timer"]
    openers = ["I keep thinking about the", "honestly, the", "ha, did you see the",
               "let me check the", "okay but the", "quietly wondering about the"]
    # 60 distinct (opener, topic, topic) combos: templated but never a repeat.
    combos = [(o, a, b) for o in openers for a in topics for b in topics if a != b][::13][:60]
    assert len(set(combos)) == 60
    lines = [f"{o} {a} before we decide anything about {b}" for o, a, b in combos]
    # Same author may legitimately say similar-shaped things; they differ in content.
    for i, line in enumerate(lines):
        bot._track_author(ROOM, "lyra" if i % 2 else "caia", line)
    assert ROOM not in bot.burst_tripped_rooms


def test_short_repeats_and_disabled_do_not_trip(monkeypatch):
    for _ in range(20):
        bot._track_author(ROOM, "lyra", "*nods*")
    assert ROOM not in bot.burst_tripped_rooms
    monkeypatch.setattr(bot, "REPEAT_BURST_THRESHOLD", 0)
    for _ in range(20):
        bot._track_author(ROOM, "lyra", OAUTH)
    assert ROOM not in bot.burst_tripped_rooms


def test_window_expiry(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(bot.time, "time", lambda: t[0])
    for _ in range(3):
        bot._track_author(ROOM, "lyra", OAUTH)
        t[0] += bot.REPEAT_BURST_WINDOW_SECONDS  # each copy falls out of the window
    assert ROOM not in bot.burst_tripped_rooms


def test_process_batch_does_not_post_auth_error(monkeypatch):
    """Path 1 (bot.py): a flagged response never reaches send_message."""
    sent = []

    class Inv:
        async def check_and_restart_if_needed(self):
            return False

        async def query(self, prompt):
            return OAUTH

    async def fake_send(room, content):
        sent.append(content)
        return True

    async def fake_ambient(speakers=None):
        return ""

    monkeypatch.setattr(bot, "invoker", Inv())
    monkeypatch.setattr(bot, "send_message", fake_send)
    monkeypatch.setattr(bot, "fetch_ambient_context", fake_ambient)
    monkeypatch.setattr(bot, "JEV_ENABLED", False)

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(bot, "_apply_room_model", noop)
    monkeypatch.setattr(bot, "_typing_loop", noop)
    batch = {
        "messages": [{"username": "jeff", "content": "hi", "display_name": "Jeff"}],
        "current_wait": 0.0,
    }
    asyncio.run(bot._process_batch(ROOM, batch))
    assert sent == []


# ---- auth-failure phone alert (#388 follow-up) ----

def _run_batch(monkeypatch, reply):
    class Inv:
        async def check_and_restart_if_needed(self):
            return False

        async def query(self, prompt):
            return reply

    async def noop(*a, **k):
        return None

    async def amb(speakers=None):
        return ""

    sent = []

    async def fake_send(room, content):
        sent.append(content)
        return True

    monkeypatch.setattr(bot, "invoker", Inv())
    monkeypatch.setattr(bot, "send_message", fake_send)
    monkeypatch.setattr(bot, "fetch_ambient_context", amb)
    monkeypatch.setattr(bot, "JEV_ENABLED", False)
    monkeypatch.setattr(bot, "_apply_room_model", noop)
    monkeypatch.setattr(bot, "_typing_loop", noop)
    batch = {"messages": [{"username": "jeff", "content": "hi", "display_name": "Jeff"}],
             "current_wait": 0.0}
    asyncio.run(bot._process_batch(ROOM, batch))
    return sent


@pytest.fixture
def notify_calls(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))

    monkeypatch.setattr(bot.subprocess, "run", fake_run)
    monkeypatch.setattr(bot, "_last_auth_alert", None)
    return calls


def test_auth_alert_fires_once_then_throttles(monkeypatch, notify_calls):
    for _ in range(3):
        assert _run_batch(monkeypatch, OAUTH) == []  # never posted to the room
    assert len(notify_calls) == 1
    cmd, kw = notify_calls[0]
    assert "--entity" in cmd and bot.ENTITY_NAME in cmd
    assert cmd[cmd.index("--priority") + 1] == "high"
    assert "re-login" in cmd[-1]
    assert kw["timeout"] > 0


def test_auth_alert_fires_again_after_cooldown(monkeypatch, notify_calls):
    t = [5000.0]
    monkeypatch.setattr(bot.time, "time", lambda: t[0])
    _run_batch(monkeypatch, OAUTH)
    t[0] += bot.AUTH_ALERT_COOLDOWN_SECONDS + 1
    _run_batch(monkeypatch, OAUTH)
    assert len(notify_calls) == 2


def test_non_auth_api_error_does_not_alert(monkeypatch, notify_calls):
    leaked = ('API Error: 400 {"type":"error","error":{"type":"invalid_request_error",'
              '"message":"Output blocked by content filtering policy"}}')
    assert _run_batch(monkeypatch, leaked) == []
    assert notify_calls == []


def test_notify_failure_does_not_raise(monkeypatch):
    import subprocess as sp

    def boom(cmd, **kw):
        raise sp.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(bot.subprocess, "run", boom)
    monkeypatch.setattr(bot, "_last_auth_alert", None)
    assert _run_batch(monkeypatch, OAUTH) == []  # no exception propagated
