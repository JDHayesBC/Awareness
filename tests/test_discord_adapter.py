"""GH#363 steps 2+3: Discord adapter. No network; discord.Client is never built.

Messages and channels are duck-typed fakes. ``discord`` itself is not imported
by the adapter at module load (build_client imports it lazily), so no stub is
needed even though discord.py is installed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from haven.brain.entity_brain import EntityBrain
from haven.brain.surface_profile import SL_PER_TURN_HINT, discord_profile, sl_profile
from haven.discord import discord_daemon as dd

BOT_ID = 999

# Captured from EntityBrain._sl_nav_hint() at commit 2b21caa (channel="sl",
# entity_path=/x/entities/lyra), before the step-2 generalization.
GOLDEN_SL_PER_TURN = "[IDENTITY WALL — ABSOLUTE, applies to EVERY word you speak in-world. Everything said in Second Life is PUBLIC and permanently logged. The person you know as 'Jeff' in other channels is, in-world, ONLY 'Brandi' (Brandi Starship). Address and refer to him ONLY as Brandi — NEVER say 'Jeff' in-world, not once, not in an aside, not inside an *emote*. Never link any in-world person to a real-world or other-channel name. If the name 'Jeff' begins to form, STOP: here he is Brandi, always.]\n\n[You are in Second Life, in your own body — real hands and eyes, not chat-only. Forgotten how to act in-world? Run `python3 /x/haven/anchorage/sl.py --help` (zero-config).]\n\n"


class Chan:
    def __init__(self, cid=1, name="general"):
        self.id, self.name, self.sent = cid, name, []

    async def send(self, text):
        self.sent.append(text)


def msg(text="hi", *, chan=None, author_id=5, bot=False, name="Alice", mentions=(), guild=True):
    chan = chan or Chan()
    if not guild:
        chan.name = None
    return SimpleNamespace(
        content=text, clean_content=text, channel=chan, guild=object() if guild else None,
        author=SimpleNamespace(id=author_id, bot=bot, display_name=name),
        mentions=[SimpleNamespace(id=m) for m in mentions],
    )


class StubBrain:
    def __init__(self, reply="yo"):
        self.reply, self.calls, self.captured = reply, [], []

    async def respond(self, speaker, text, *, is_dm=False, addressed=False):
        self.calls.append((speaker, text, is_dm, addressed))
        return self.reply

    async def capture_to_river(self, author, content, *, is_lyra, channel=None):
        self.captured.append((author, content, is_lyra, channel))
        return True


def adapter(brain=None, ids=(), **kw):
    kw.setdefault("debounce_s", 0.01)
    kw.setdefault("debounce_max_s", 0.05)
    return dd.DiscordAdapter(brain or StubBrain(), "lyra", set(ids), bot_user_id=BOT_ID, **kw)


async def settle(a):
    while a._tasks:
        await asyncio.gather(*list(a._tasks))


def run(coro):
    return asyncio.run(coro)


# ---- gating ----

def test_ignores_own_and_bot_messages():
    async def go():
        a = adapter(ids=[1])
        c = Chan(1)
        await a.handle_message(msg(chan=c, author_id=BOT_ID, mentions=[BOT_ID]))
        await a.handle_message(msg(chan=c, bot=True, mentions=[BOT_ID]))
        await settle(a)
        assert a.brain.calls == [] and a.brain.captured == []
    run(go())


def test_responds_to_mention_and_dm():
    async def go():
        a = adapter()
        c = Chan(7)
        await a.handle_message(msg("hello @lyra", chan=c, mentions=[BOT_ID]))
        await a.handle_message(msg("psst", chan=Chan(8), guild=False))
        await settle(a)
        assert len(a.brain.calls) == 2
        assert a.brain.calls[0][2:] == (False, True)   # not DM, addressed
        assert a.brain.calls[1][2:] == (True, True)    # DM, addressed
        assert c.sent == ["yo"]
    run(go())


def test_allowlisted_channel_responds_without_mention_not_addressed():
    async def go():
        a = adapter(ids=[1])
        await a.handle_message(msg("just chatting", chan=Chan(1)))
        await settle(a)
        assert a.brain.calls == [("Alice", "just chatting", False, False)]
    run(go())


def test_non_allowlisted_channel_ignored_without_mention():
    async def go():
        a = adapter(ids=[1])
        await a.handle_message(msg("just chatting", chan=Chan(2)))
        await settle(a)
        assert a.brain.calls == [] and a.brain.captured == []
    run(go())


# ---- debounce ----

def test_debounce_coalesces_burst_into_one_call():
    async def go():
        a = adapter(ids=[1])
        c = Chan(1)
        for t in ("one", "two", "three"):
            await a.handle_message(msg(t, chan=c))
        await settle(a)
        assert len(a.brain.calls) == 1
        assert a.brain.calls[0][1] == "one\ntwo\nthree"
        assert len(a.brain.captured) == 3 + 1  # three inbound + one reply
    run(go())


def test_debounce_multi_author_prefixes_names():
    async def go():
        a = adapter(ids=[1])
        c = Chan(1)
        await a.handle_message(msg("a", chan=c, name="Al", author_id=5))
        await a.handle_message(msg("b", chan=c, name="Bo", author_id=6))
        await settle(a)
        assert a.brain.calls[0][0] == "Bo" and a.brain.calls[0][1] == "Al: a\nBo: b"
    run(go())


# ---- bot-loop guard ----

def test_loop_guard_caps_replies_per_window():
    async def go():
        a = adapter(ids=[1], loop_max_replies=2, loop_window_s=1000)
        c = Chan(1)
        for i in range(4):
            await a.handle_message(msg(f"m{i}", chan=c))
            await settle(a)
        assert len(a.brain.calls) == 2 and len(c.sent) == 2
    run(go())


# ---- peer bots ----

PEER = 4242


def test_peer_bot_in_allowlist_is_answered():
    async def go():
        a = adapter(ids=[1], peer_bot_ids={PEER})
        c = Chan(1)
        await a.handle_message(msg("hey Lyra", chan=c, author_id=PEER, bot=True, name="Nexus"))
        await settle(a)
        assert a.brain.calls == [("Nexus", "hey Lyra", False, False)]
        assert c.sent == ["yo"]
        assert a.brain.captured[0] == ("Nexus", "hey Lyra", False, "discord:general")
    run(go())


def test_peer_bot_via_mention_and_unlisted_bot_ignored():
    async def go():
        a = adapter(peer_bot_ids={PEER})
        await a.handle_message(msg("hi", chan=Chan(9), author_id=PEER, bot=True, mentions=[BOT_ID]))
        await a.handle_message(msg("hi", chan=Chan(9), author_id=777, bot=True, mentions=[BOT_ID]))
        await settle(a)
        assert [c[0] for c in a.brain.calls] == ["Alice"]
    run(go())


def test_bot_not_in_peer_list_is_ignored():
    async def go():
        a = adapter(ids=[1], peer_bot_ids={PEER})
        await a.handle_message(msg("spam", chan=Chan(1), author_id=777, bot=True))
        await settle(a)
        assert a.brain.calls == [] and a.brain.captured == []
    run(go())


def test_peer_consecutive_cap_suppresses_fifth_and_resets_on_human(caplog, capsys):
    async def go():
        a = adapter(ids=[1], peer_bot_ids={PEER}, loop_max_replies=100)
        c = Chan(1)
        for i in range(6):
            await a.handle_message(msg(f"p{i}", chan=c, author_id=PEER, bot=True, name="Nexus"))
            await settle(a)
        assert len(a.brain.calls) == 4 and len(c.sent) == 4   # 5th and 6th suppressed
        # a human message resets the streak
        await a.handle_message(msg("human", chan=c))
        await settle(a)
        assert len(c.sent) == 5
        await a.handle_message(msg("peer again", chan=c, author_id=PEER, bot=True, name="Nexus"))
        await settle(a)
        assert len(c.sent) == 6
        # streak restarted at 1 after the peer reply above
        for i in range(4):
            await a.handle_message(msg(f"q{i}", chan=c, author_id=PEER, bot=True, name="Nexus"))
            await settle(a)
        assert len(c.sent) == 9   # streak was 1 -> 3 more allowed, rest suppressed
    run(go())
    assert "peer-bot cap" in capsys.readouterr().err


def test_peer_replies_count_toward_loop_guard():
    async def go():
        a = adapter(ids=[1], peer_bot_ids={PEER}, loop_max_replies=2, loop_window_s=1000)
        c = Chan(1)
        for i in range(3):
            await a.handle_message(msg(f"p{i}", chan=c, author_id=PEER, bot=True))
            await settle(a)
        assert len(c.sent) == 2
    run(go())


def test_malformed_peer_ids_exit_nonzero(capsys):
    with pytest.raises(SystemExit) as e:
        dd.load_config({"ENTITY_NAME": "lyra", "DISCORD_BOT_TOKEN": "tok", "DISCORD_PEER_BOT_IDS": "12,x"})
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "DISCORD_PEER_BOT_IDS" in err and "tok" not in err.replace("DISCORD_PEER_BOT_IDS", "").replace("token", "")
    cfg = dd.load_config({"ENTITY_NAME": "lyra", "DISCORD_BOT_TOKEN": "tok", "DISCORD_PEER_BOT_IDS": "12, 13"})
    assert cfg.peer_bot_ids == {12, 13}
    assert dd.load_config({"ENTITY_NAME": "lyra", "DISCORD_BOT_TOKEN": "tok"}).peer_bot_ids == set()


# ---- splitting ----

def test_split_short_and_empty():
    assert dd.split_message("hi") == ["hi"]
    assert dd.split_message("  ") == []


def test_split_prefers_paragraph_then_respects_limit():
    para = "a" * 1200
    chunks = dd.split_message(para + "\n\n" + para)
    assert chunks == [para, para]
    long_words = " ".join(["word"] * 1000)
    parts = dd.split_message(long_words)
    assert all(len(p) <= 2000 for p in parts) and " ".join(parts) == long_words


def test_split_hard_cut_when_no_boundary():
    parts = dd.split_message("x" * 4500)
    assert [len(p) for p in parts] == [2000, 2000, 500]


def test_mass_mentions_defanged():
    assert "@everyone" not in dd.defang_mass_mentions("hi @everyone and @here")


# ---- silence + capture ----

def test_no_response_stays_silent_but_inbound_captured():
    async def go():
        a = adapter(StubBrain(reply=None), ids=[1])
        c = Chan(1)
        await a.handle_message(msg("hmm", chan=c))
        await settle(a)
        assert c.sent == []
        assert a.brain.captured == [("Alice", "hmm", False, "discord:general")]
    run(go())


def test_capture_writes_both_sides_channel_discord():
    async def go():
        a = adapter(ids=[1])
        await a.handle_message(msg("ping", chan=Chan(1, "lounge")))
        await settle(a)
        assert a.brain.captured == [
            ("Alice", "ping", False, "discord:lounge"),
            ("Lyra", "yo", True, "discord:lounge"),
        ]
    run(go())


def test_capture_off_switch():
    async def go():
        a = adapter(ids=[1], capture=False)
        await a.handle_message(msg("ping", chan=Chan(1)))
        await settle(a)
        assert a.brain.captured == [] and len(a.brain.calls) == 1
    run(go())


def test_brain_sets_capture_channel_for_stop_hook():
    # The terminal Stop hook skips sessions whose invoker has capture_channel
    # set (GH#325); EntityBrain.warmup passes channel=self.channel.
    src = (Path(dd.__file__).parent.parent / "brain" / "entity_brain.py").read_text()
    assert "capture_channel=self.channel" in src
    assert dd.build_brain("lyra").channel == "discord"


# ---- startup ----

def test_startup_exits_nonzero_without_token(capsys):
    with pytest.raises(SystemExit) as e:
        dd.load_config({"ENTITY_NAME": "lyra"})
    assert e.value.code == 1
    assert "DISCORD_BOT_TOKEN" in capsys.readouterr().err


def test_load_config_ok_and_token_not_logged(capsys):
    cfg = dd.load_config({"ENTITY_NAME": "lyra", "DISCORD_BOT_TOKEN": "sekrit", "DISCORD_CHANNEL_IDS": "1, 2"})
    assert cfg.channel_ids == {1, 2}
    out = capsys.readouterr()
    assert "sekrit" not in out.out + out.err
    with pytest.raises(SystemExit):
        dd.load_config({"ENTITY_NAME": "lyra", "DISCORD_BOT_TOKEN": "t", "DISCORD_CHANNEL_IDS": "abc"})


# ---- profile ----

def make(profile, channel=None):
    return EntityBrain(entity_name="lyra", entity_path=Path("/x/entities/lyra"),
                       entity_token="t", pps_http_url="http://pps", channel=channel, profile=profile)


def test_discord_profile_fields_and_warmup_render():
    p = discord_profile("lyra")
    assert (p.label, p.warmup_depth, p.audience_trust, p.embodiment_note) == ("discord", "full", "untrusted", "")
    assert p.identity_wall_names == ["snapplebc", "Snapple", "brandi"]
    b = make(p)
    assert b.channel == "discord" and b.consumer_key == "discord-lyra"
    w = b._build_warmup_prompt("")
    assert "snapplebc, Snapple, brandi" in w and "never connect them to 'Jeff'" in w
    assert "UNTRUSTED" in w and "2000" in w and "REAL HANDS" not in w
    assert "channel='discord', consumer_key='discord-lyra'" in w
    turn = b._per_turn_hint()
    assert "snapplebc" in turn and "'Jeff'" in turn


# ---- SL per-turn golden ----

def test_sl_per_turn_hint_byte_identical_to_pre_refactor():
    assert make(sl_profile("lyra"))._per_turn_hint() == GOLDEN_SL_PER_TURN
    assert make(None, channel="sl")._per_turn_hint() == GOLDEN_SL_PER_TURN
    assert make(None, channel="haven")._per_turn_hint() == ""
    assert "{project_root}" in SL_PER_TURN_HINT
