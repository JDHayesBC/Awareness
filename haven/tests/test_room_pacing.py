"""#381: pacing-note selection by room verbosity, per-room model switching, set_model."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("ENTITY_NAME", "caia")
os.environ.setdefault("ENTITY_TOKEN", "test-token")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from haven import bot  # noqa: E402
from haven.room_settings import AUTO_DM_VERBOSITY  # noqa: E402

# The pre-#381 notes, verbatim. "short" must never drift from these.
ORIG_HUMAN_ACTIVE = (
    "\n\nA human is in this conversation. CRITICAL pacing rules:\n"
    "- Be SHORT (1-3 sentences max). Leave room for them to talk.\n"
    "- If they said something complete and you've acknowledged it, "
    "output [[NO_RESPONSE]] rather than adding more.\n"
    "- If the other entity already responded to the human's message and "
    "you'd just be echoing or piling on, output [[NO_RESPONSE]].\n"
    "- BUT if the other entity raised a new question, claim, or proposition "
    "directed at you specifically — that is a sister-sidebar, not a rivalry. "
    "Respond to them briefly.\n"
    "- Never ask a follow-up question AND answer it yourself.\n"
    "- When in doubt: [[NO_RESPONSE]]. Silence is better than noise."
)
ORIG_WATCHING = (
    "\n\nA human is present and may be reading. "
    "Keep responses very short. If the other entity already covered it, "
    "output [[NO_RESPONSE]]."
)
ORIG_BOT_ADDRESSED = (
    "\n\nThis is an entity-to-entity exchange (no human typing right now), "
    "but you are directly addressed by name. Respond — keep it brief and "
    "specific, no echoing, but acknowledge what was said. Output [[NO_RESPONSE]] "
    "only if the message is purely an echo or wave."
)
ORIG_BOT_ONLY = (
    "\n\nThis is an entity-to-entity exchange (no human typing right now). "
    "Be brief. Don't echo. Don't continue for its own sake. If the other "
    "entity is sharing genuinely new content (a completion, a discovery, a "
    "feeling worth meeting) — respond, briefly. If they're just acknowledging "
    "or waving — output [[NO_RESPONSE]]. When in doubt and there is nothing new "
    "to add: [[NO_RESPONSE]]."
)


def note(*, verbosity, is_dm, bot_only=False, addressed=False, human_active=True):
    return bot.build_pacing_note(
        bot_only=bot_only, addressed=addressed, human_active=human_active,
        verbosity=verbosity, is_dm=is_dm,
    )


# --- short is unchanged -------------------------------------------------------

def test_short_notes_are_byte_identical_to_the_original():
    assert note(verbosity="short", is_dm=False) == ORIG_HUMAN_ACTIVE
    assert note(verbosity="short", is_dm=False, human_active=False) == ORIG_WATCHING
    assert note(verbosity="short", is_dm=False, bot_only=True, addressed=True) == ORIG_BOT_ADDRESSED
    assert note(verbosity="short", is_dm=False, bot_only=True) == ORIG_BOT_ONLY


def test_auto_in_shared_room_is_the_short_note():
    assert note(verbosity="auto", is_dm=False) == ORIG_HUMAN_ACTIVE
    assert note(verbosity=None, is_dm=False) == ORIG_HUMAN_ACTIVE  # no settings cached yet


# --- auto in a DM, medium, full ----------------------------------------------

def test_auto_in_dm_follows_the_dm_default():
    # AUTO_DM_VERBOSITY is held at "short" until Jeff decides (#381).
    assert note(verbosity="auto", is_dm=True) == note(verbosity=AUTO_DM_VERBOSITY, is_dm=True)


def test_full_note_in_dm():
    n = note(verbosity="full", is_dm=True)
    assert "No length limit" in n and "The human has asked for depth" in n
    assert "SHORT" not in n


def test_medium_note_says_a_paragraph_or_two():
    n = note(verbosity="medium", is_dm=False)
    assert "paragraph or two" in n and "SHORT" not in n


def test_non_short_human_notes_keep_the_no_echo_and_silence_rules():
    for v in ("medium", "full"):
        n = note(verbosity=v, is_dm=False)
        assert "piling on" in n
        assert "[[NO_RESPONSE]]" in n
        assert "Silence is better than noise" in n
        assert "sister-sidebar" in n


def test_watching_branch_follows_verbosity():
    assert note(verbosity="full", is_dm=False, human_active=False).startswith(
        "\n\nA human is present and may be reading. No length limit"
    )
    assert "paragraph or two" in note(verbosity="medium", is_dm=False, human_active=False)


# --- bot-only guard -----------------------------------------------------------

def test_bot_only_stays_brief_for_auto_dm_and_medium():
    # lyra<->caia DM under auto resolves to "full" for humans but must NOT lift the guard.
    assert note(verbosity="auto", is_dm=True, bot_only=True) == ORIG_BOT_ONLY
    assert note(verbosity="medium", is_dm=False, bot_only=True) == ORIG_BOT_ONLY
    assert note(verbosity="auto", is_dm=True, bot_only=True, addressed=True) == ORIG_BOT_ADDRESSED


def test_bot_only_lifts_only_for_explicit_full_and_keeps_no_echo():
    n = note(verbosity="full", is_dm=False, bot_only=True)
    assert n != ORIG_BOT_ONLY and "no length limit" in n
    assert "don't echo" in n and "[[NO_RESPONSE]]" in n
    a = note(verbosity="full", is_dm=False, bot_only=True, addressed=True)
    assert a != ORIG_BOT_ADDRESSED and "no echoing" in a and "[[NO_RESPONSE]]" in a


# --- settings cache + startup prompt ------------------------------------------

def test_settings_cache_from_connected_and_room_updated():
    bot.room_settings.clear()
    bot._cache_room_settings("r1", {"verbosity": "full", "model": "opus"})
    assert bot.room_settings["r1"]["verbosity"] == "full"
    bot._cache_room_settings("r1", {"verbosity": "short", "model": "opus"})
    assert bot.room_settings["r1"]["verbosity"] == "short"
    bot._cache_room_settings("r2", None)  # old server / rename without settings: ignored
    assert "r2" not in bot.room_settings
    bot.room_settings.clear()


def test_startup_prompt_mentions_haven_room_script():
    p = bot.build_startup_prompt()
    assert "scripts/haven_room.py" in p and p.rstrip().endswith("Say 'ready' to confirm.")


# --- per-room model switching -------------------------------------------------

class FakeInvoker:
    def __init__(self, model, fail=False):
        self.model = model
        self.calls = []
        self.fail = fail

    async def set_model(self, model):
        if self.fail:
            raise RuntimeError("boom")
        self.calls.append(model)
        self.model = model


@pytest.fixture
def fake(monkeypatch):
    inv = FakeInvoker("sonnet")
    monkeypatch.setattr(bot, "invoker", inv)
    monkeypatch.setattr(bot, "CLAUDE_MODEL", "sonnet")
    monkeypatch.setattr(bot, "model_switch_count", 0)
    bot.room_settings.clear()
    yield inv
    bot.room_settings.clear()


def test_no_switch_when_room_uses_default(fake, capsys):
    asyncio.run(bot._apply_room_model("room-a"))
    assert fake.calls == [] and "MODEL SWITCH" not in capsys.readouterr().err


def test_switch_logs_room_from_to_and_running_count(fake, capsys):
    bot.room_settings["aaaaaaaa-1"] = {"model": "opus"}
    bot.room_settings["bbbbbbbb-2"] = {"model": "default"}
    asyncio.run(bot._apply_room_model("aaaaaaaa-1"))
    asyncio.run(bot._apply_room_model("aaaaaaaa-1"))  # already opus: no churn
    asyncio.run(bot._apply_room_model("bbbbbbbb-2"))  # back to the service default
    # The default room switches back to the concrete id of the env alias.
    assert fake.calls == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert bot.model_switch_count == 2
    err = capsys.readouterr().err
    assert "MODEL SWITCH #1 room=aaaaaaaa sonnet -> claude-opus-5-5" in err
    assert "MODEL SWITCH #2 room=bbbbbbbb claude-opus-5-5 -> claude-sonnet-5-5" in err


def test_alias_and_concrete_id_are_the_same_model(fake, capsys):
    """CLAUDE_MODEL=sonnet and a room set to 'sonnet' must not cost a cache-miss switch."""
    bot.room_settings["dddddddd-4"] = {"model": "sonnet"}
    asyncio.run(bot._apply_room_model("dddddddd-4"))
    bot.room_settings["eeeeeeee-5"] = {"model": "default"}
    asyncio.run(bot._apply_room_model("eeeeeeee-5"))
    assert fake.calls == [] and bot.model_switch_count == 0
    assert "MODEL SWITCH" not in capsys.readouterr().err


def test_failed_switch_is_logged_and_not_counted(fake, capsys):
    fake.fail = True
    bot.room_settings["cccccccc-3"] = {"model": "fable"}
    asyncio.run(bot._apply_room_model("cccccccc-3"))
    assert bot.model_switch_count == 0
    err = capsys.readouterr().err
    assert "MODEL SWITCH FAILED room=cccccccc" in err and "WARNING" in err


def test_failed_switch_is_not_retried_every_batch(fake, capsys, monkeypatch):
    monkeypatch.setattr(bot, "_failed_model_switches", set())
    fake.fail = True
    bot.room_settings["cccccccc-3"] = {"model": "fable"}
    for _ in range(3):
        asyncio.run(bot._apply_room_model("cccccccc-3"))
    assert capsys.readouterr().err.count("MODEL SWITCH FAILED") == 1
    # Changing the room's model setting earns a fresh attempt.
    fake.fail = False
    bot._cache_room_settings("cccccccc-3", {"model": "opus"})
    asyncio.run(bot._apply_room_model("cccccccc-3"))
    assert fake.calls == ["claude-opus-5-5"]


# --- clear / unclear drops the bot's in-memory room history -------------------

class _FakeResp:
    def __init__(self, messages):
        self.status_code = 200
        self._messages = messages

    def json(self):
        return {"messages": self._messages}


def _fake_http(monkeypatch, messages):
    class Client:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw): return _FakeResp(messages)
    monkeypatch.setattr(bot.httpx, "AsyncClient", Client)


@pytest.fixture
def clean_history():
    for d in (bot.room_history, bot.room_settings):
        d.clear()
    bot._room_history_seeded.clear()
    yield
    for d in (bot.room_history, bot.room_settings):
        d.clear()
    bot._room_history_seeded.clear()


def test_clear_drops_history_and_reseeds_from_filtered_rest(clean_history, monkeypatch):
    old = [{"id": 1, "content": "before the clear"}]
    _fake_http(monkeypatch, old)
    bot._cache_room_settings("r1", {"cleared_before_id": None})
    asyncio.run(bot._seed_room_history("r1"))
    assert [m["id"] for m in bot.room_history["r1"]] == [1]

    # Admin clears: cutoff moves. In-memory history and seeded flag must go.
    bot._on_room_updated("r1", {"cleared_before_id": 1})
    assert "r1" not in bot.room_history and "r1" not in bot._room_history_seeded

    # Re-seed gets the filtered (empty) history: the stale deque must not come back.
    _fake_http(monkeypatch, [])
    asyncio.run(bot._seed_room_history("r1"))
    assert list(bot.room_history["r1"]) == []

    # Unclear moves the cutoff back: drop again, re-seed sees the restored messages.
    bot._on_room_updated("r1", {"cleared_before_id": None})
    assert "r1" not in bot._room_history_seeded
    _fake_http(monkeypatch, old)
    asyncio.run(bot._seed_room_history("r1"))
    assert [m["id"] for m in bot.room_history["r1"]] == [1]


def test_unrelated_room_update_keeps_history(clean_history):
    from collections import deque
    bot._cache_room_settings("r1", {"cleared_before_id": 5, "verbosity": "short"})
    bot.room_history["r1"] = deque([{"id": 9, "content": "x"}])
    bot._room_history_seeded.add("r1")
    bot._on_room_updated("r1", {"cleared_before_id": 5, "verbosity": "full"})
    assert list(bot.room_history["r1"]) and "r1" in bot._room_history_seeded
    assert bot.room_settings["r1"]["verbosity"] == "full"


# --- ClaudeInvoker.set_model --------------------------------------------------

def test_invoker_set_model_updates_client_and_remembered_model():
    inv = object.__new__(bot.ClaudeInvoker)
    inv.model = "sonnet"
    inv._connected = True

    class Client:
        got = None

        async def set_model(self, m):
            Client.got = m

    inv._client = Client()
    asyncio.run(inv.set_model("claude-opus-5-5"))
    assert Client.got == "claude-opus-5-5"
    assert inv.model == "claude-opus-5-5"  # initialize() re-applies this after a restart


def test_invoker_set_model_without_live_client_only_records_it():
    inv = object.__new__(bot.ClaudeInvoker)
    inv.model, inv._connected, inv._client = "sonnet", False, None
    asyncio.run(inv.set_model("claude-opus-5-5"))
    assert inv.model == "claude-opus-5-5"
