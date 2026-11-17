"""Tests for the rotation seed (#404): a rotated session gets the recent room
conversation inside the SAME warmup prompt as identity.

Run: PYTHONPATH=<repo> pps/venv/bin/python3 -m pytest haven/anchorage/test_room_seed.py -q
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time

os.environ.setdefault("SL_CORRADE", "0")
os.environ.setdefault("ENTITY_NAME", "lyra")

import pytest

from haven.anchorage import sl_daemon as d
from haven.brain.entity_brain import EntityBrain

NOW = 1_800_000_000.0


def L(age_s, who, text, own=False):
    return (NOW - age_s, who, text, own)


# ---------------- selection ----------------

def test_window_and_cap_drop_oldest(monkeypatch):
    monkeypatch.setattr(d, "SL_SEED_MAX_LINES", 5)
    lines = [L(300 - i * 10, "Ann", f"m{i}") for i in range(20)]
    picked = d._select_seed_lines(lines, NOW)
    assert [p[2] for p in picked] == [f"m{i}" for i in range(15, 20)]


def test_old_lines_outside_window_dropped_when_no_exchange_pull(monkeypatch):
    lines = [L(5000, "Bob", "ancient"), L(30, "Ann", "recent")]
    picked = d._select_seed_lines(lines, NOW)
    # Ann is the last speaker; Bob's old line is neither in window nor hers.
    assert [p[2] for p in picked] == ["recent"]


def test_latest_exchange_kept_outside_window(monkeypatch):
    monkeypatch.setattr(d, "SL_SEED_EXCHANGE_LINES", 3)
    lines = [
        L(3500, "Zed", "noise"),
        L(2000, "Ann", "hello Lyra"),
        L(1990, "Lyra", "hi Ann", own=True),
        L(1980, "Ann", "who is Carol?"),
    ]
    picked = d._select_seed_lines(lines, NOW)
    assert [p[2] for p in picked] == ["hello Lyra", "hi Ann", "who is Carol?"]


def test_exchange_survives_cap(monkeypatch):
    monkeypatch.setattr(d, "SL_SEED_MAX_LINES", 3)
    monkeypatch.setattr(d, "SL_SEED_EXCHANGE_LINES", 2)
    lines = [L(5000, "Ann", "old q"), L(4990, "Lyra", "old a", own=True)]
    lines += [L(100 - i, "Bob", f"b{i}") for i in range(10)]   # Bob is last speaker
    picked = d._select_seed_lines(lines, NOW)
    assert len(picked) == 3
    assert picked[-1][2] == "b9"


def test_empty():
    assert d._select_seed_lines([], NOW) == []


# ---------------- ring recording ----------------

@pytest.fixture
def ring(monkeypatch):
    from collections import deque
    r = deque(maxlen=200)
    monkeypatch.setattr(d, "_room_ring", r)
    # an old process by default: the ring has had time to cover the whole window
    monkeypatch.setattr(d, "_room_ring_started_at", time.time() - 10_000)
    return r


def test_own_line_recorded_even_when_capture_disabled_or_dropped(ring, monkeypatch):
    monkeypatch.setattr(d, "SL_CAPTURE", False)
    asyncio.run(d._capture(object(), d.DISPLAY_NAME, "I said this", is_lyra=True))
    assert [(x[1], x[2], x[3]) for x in ring] == [(d.DISPLAY_NAME, "I said this", True)]


def test_inbound_not_double_recorded_by_capture(ring, monkeypatch):
    monkeypatch.setattr(d, "SL_CAPTURE", False)
    asyncio.run(d._capture(object(), "Ann", "hi", is_lyra=False))
    assert not ring


def test_local_chat_recorded_at_ingest_even_if_quiet(ring, monkeypatch):
    from haven.anchorage import perception
    perc = perception.SLPerception({"lyrapattern"}, {"lyra"}, perception.SalienceConfig())
    monkeypatch.setattr(d, "_perception", perc)
    monkeypatch.setattr(d, "_hb", None)
    monkeypatch.setattr(d, "_idle_backoff", None)
    ev = {"type": "Normal", "firstname": "Ann", "lastname": "Resident",
          "agent": "c06d8847-53af-4983-97f7-99dc20566583", "message": "the weather is nice"}
    d._on_corrade_event(ev)
    assert [(x[1], x[2], x[3]) for x in ring] == [("Ann Resident", "the weather is nice", False)]
    d._on_corrade_event({**ev, "firstname": "LyraPattern", "lastname": "Resident",
                         "message": "my own echo"})
    assert len(ring) == 1


# ---------------- seed rendering / backfill / logging ----------------

def test_seed_from_ring_has_block_and_logs_count_only(ring, monkeypatch):
    logs = []
    monkeypatch.setattr(d, "log", lambda m: logs.append(m))
    now = time.time()
    ring.append((now - 20, "Ann", "SECRET-TOPIC about Carol", False))
    ring.append((now - 10, d.DISPLAY_NAME, "own reply here", True))
    seed = d._build_room_seed()
    assert "Ann: SECRET-TOPIC about Carol" in seed
    assert f"{d.DISPLAY_NAME} (you): own reply here" in seed
    assert "possibly" not in seed and "may be missing" not in seed
    assert any("2 line(s) from ring buffer" in m for m in logs)
    assert not any("SECRET-TOPIC" in m or "own reply" in m for m in logs)


def test_empty_ring_uses_labelled_river_backfill(ring, monkeypatch, tmp_path):
    monkeypatch.setenv("ENTITY_PATH", str(tmp_path))
    (tmp_path / "data").mkdir()
    con = sqlite3.connect(tmp_path / "data" / "conversations.db")
    con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, author_name TEXT, "
                "content TEXT, is_lyra INTEGER, created_at TEXT, channel TEXT)")
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    con.execute("INSERT INTO messages VALUES (1,'Ann','from the river',0,?,?)", (stamp, d.SL_CHANNEL))
    con.execute("INSERT INTO messages VALUES (2,'X','other channel',0,?,'discord')", (stamp,))
    con.commit(); con.close()
    logs = []
    monkeypatch.setattr(d, "log", lambda m: logs.append(m))
    seed = d._build_room_seed()
    assert "Ann: from the river" in seed and "other channel" not in seed
    assert "may be missing some lines" in seed
    assert any("river backfill" in m for m in logs)
    assert not any("from the river" in m for m in logs)


def test_ring_present_means_no_db_read(ring, monkeypatch):
    ring.append((time.time(), "Ann", "x", False))
    monkeypatch.setattr(d, "_load_room_lines_from_db",
                        lambda: pytest.fail("river read while ring non-empty"))
    assert d._build_room_seed()


def test_nothing_to_seed_returns_none(ring, monkeypatch):
    monkeypatch.setattr(d, "_load_room_lines_from_db", lambda: [])
    assert d._build_room_seed() is None


# ---------------- brain: same-step delivery, Haven unchanged ----------------

class FakeInvoker:
    def __init__(self):
        self.prompts = []
        self.context_size = 0
        self.turn_count = 0

    def approaching_restart(self, threshold=0.8):
        return (True, "test")

    async def restart(self, reason=""):
        pass

    async def query(self, prompt, **kw):
        self.prompts.append(prompt)
        return "warmed up"


def _brain(monkeypatch):
    b = EntityBrain(entity_name="test", channel="sl")
    b.invoker = FakeInvoker()

    async def _no_boot():
        return ""
    monkeypatch.setattr(b, "_fetch_boot_context", _no_boot)
    return b


def test_prompt_without_room_context_identical(monkeypatch):
    b = _brain(monkeypatch)
    base = b._build_warmup_prompt("boot")
    assert b._build_warmup_prompt("boot", None) == base
    assert b._build_warmup_prompt("boot", "") == base
    with_room = b._build_warmup_prompt("boot", "[ROOM]\nline")
    assert "[ROOM]\nline" in with_room
    assert with_room.replace("\n[ROOM]\nline\n\n", "") == base


def test_rotation_delivers_seed_in_single_warmup_query(monkeypatch):
    b = _brain(monkeypatch)
    calls = []
    asyncio.run(b.rotate_if_approaching(room_context=lambda: calls.append(1) or "[ROOM]\nhello"))
    assert len(b.invoker.prompts) == 1          # one query: identity + room together
    assert "[IDENTITY WARMUP]" in b.invoker.prompts[0] and "[ROOM]\nhello" in b.invoker.prompts[0]
    assert calls == [1]                          # evaluated once, at warmup time


def test_rotation_default_has_no_room_and_bad_provider_is_safe(monkeypatch):
    b = _brain(monkeypatch)
    asyncio.run(b.restart_session())
    assert "[ROOM]" not in b.invoker.prompts[0]

    def boom():
        raise RuntimeError("x")
    asyncio.run(b.restart_session(room_context=boom))
    assert len(b.invoker.prompts) == 2 and b.invoker.prompts[1] == b.invoker.prompts[0]


def test_stale_exchange_is_not_kept(monkeypatch):
    """An exchange older than SL_SEED_EXCHANGE_MAX_AGE_S is not 'the conversation
    we were in': a quiet ring or a river backfill must not seed yesterday's lines."""
    monkeypatch.setattr(d, "SL_SEED_EXCHANGE_MAX_AGE_S", 3600.0)
    lines = [L(7300, "Ann", "old one"), L(7250, "me", "old reply", own=True),
             L(7200, "Ann", "old two")]
    assert d._select_seed_lines(lines, NOW) == []


def test_exchange_inside_age_limit_but_outside_window_is_kept(monkeypatch):
    monkeypatch.setattr(d, "SL_SEED_EXCHANGE_MAX_AGE_S", 3600.0)
    lines = [L(1300, "Ann", "twenty minutes ago"), L(1250, "me", "reply", own=True)]
    assert [ln[2] for ln in d._select_seed_lines(lines, NOW)] == ["twenty minutes ago", "reply"]


def test_young_process_prepends_river_lines_older_than_the_ring(ring, monkeypatch):
    """First live restart, 2026-11-16: one line heard during warmup made the ring
    non-empty, the backfill was skipped, and the session was seeded with one line."""
    now = time.time()
    monkeypatch.setattr(d, "_room_ring_started_at", now - 60)       # 1 min old
    ring.append((now - 20.4, "Ann", "heard after restart", False))
    river = [
        (now - 300, "Ann", "before restart one", False),
        (now - 280, d.DISPLAY_NAME, "before restart reply", True),
        (now - 21.0, "Ann", "heard after restart", False),          # river copy of the ring line
    ]
    monkeypatch.setattr(d, "_load_room_lines_from_db", lambda: list(river))
    logs = []
    monkeypatch.setattr(d, "log", lambda m: logs.append(m))
    seed = d._build_room_seed()
    assert seed.index("before restart one") < seed.index("before restart reply") < seed.index("heard after restart")
    assert seed.count("heard after restart") == 1
    assert "may be missing some lines" in seed
    assert any("3 line(s), 2 of them from river backfill" in m for m in logs)
    assert not any("before restart" in m for m in logs)
