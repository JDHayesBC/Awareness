"""Open-ask claim: message ids on human lines, the reminder note, claim pruning,
and the real scripts/lock.py exclusivity the design depends on."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("ENTITY_NAME", "lyra")
os.environ.setdefault("ENTITY_TOKEN", "test-token")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from haven import bot  # noqa: E402

LOCK_PY = REPO / "scripts" / "lock.py"


@pytest.fixture(autouse=True)
def _topology(monkeypatch):
    monkeypatch.setattr(bot, "my_username", "lyra")
    monkeypatch.setattr(bot, "known_bots", {"lyra", "caia"})
    monkeypatch.setattr(bot, "recent_room_authors", {})


# ---- Change 1: line prefix ----

def test_human_line_gets_msg_prefix():
    m = {"id": 42, "display_name": "Jeff", "username": "jeff"}
    assert bot.format_batch_line(m, "hi", is_human=True) == "[msg 42] Jeff (jeff): hi"


def test_bot_line_unprefixed():
    m = {"id": 42, "display_name": "Caia", "username": "caia"}
    assert bot.format_batch_line(m, "hi", is_human=False) == "Caia (caia): hi"


@pytest.mark.parametrize("mid", [None, "", "missing"])
def test_missing_id_unprefixed(mid):
    m = {"display_name": "Jeff", "username": "jeff"}
    if mid != "missing":
        m["id"] = mid
    assert bot.format_batch_line(m, "hi", is_human=True) == "Jeff (jeff): hi"


def test_multi_human_batch_each_own_id_bot_between():
    msgs = [
        {"id": 11, "display_name": "Jeff", "username": "jeff", "content": "a"},
        {"id": 99, "display_name": "Caia", "username": "caia", "content": "b"},
        {"id": 12, "display_name": "Jeff", "username": "jeff", "content": "c"},
        {"id": 13, "display_name": "Jeff", "username": "jeff", "content": "d"},
    ]
    lines = [
        bot.format_batch_line(
            m, m["content"],
            is_human=m["username"] not in bot.known_bots and m["username"] != bot.my_username,
        )
        for m in msgs
    ]
    assert lines == [
        "[msg 11] Jeff (jeff): a",
        "Caia (caia): b",
        "[msg 12] Jeff (jeff): c",
        "[msg 13] Jeff (jeff): d",
    ]


# ---- Change 2: note + gates ----

def test_note_contents():
    note = bot.build_open_ask_note("lyra", Path("/x/repo"))
    assert note.startswith("[open ask]")
    assert "haven-lyra" in note
    assert "/x/repo/scripts/lock.py" in note
    assert "--locks-dir /x/repo/.locks/haven-ask" in note
    assert "haven-ask-<message id>" in note
    assert "`work:`" in note


def test_sister_present_true_false():
    now = time.time()
    assert bot._sister_present("r") is False
    bot.recent_room_authors["r"] = {"jeff": (now, False), "lyra": (now, True)}
    assert bot._sister_present("r") is False  # only me + human
    bot.recent_room_authors["r"]["caia"] = (now, True)
    assert bot._sister_present("r") is True


def test_sister_present_known_bot_flag_and_stale(monkeypatch):
    now = time.time()
    bot.recent_room_authors["r"] = {"caia": (now, False)}
    assert bot._sister_present("r") is True  # via known_bots
    bot.recent_room_authors["r"] = {
        "caia": (now - bot.HUMAN_PRESENCE_TIMEOUT_SECONDS - 5, True)
    }
    assert bot._sister_present("r") is False  # pruned as stale


ME, HER = {"lyra"}, {"caia"}


def test_open_ask_applies():
    assert bot.open_ask_applies("will someone make coffee?", ME, HER) is True
    assert bot.open_ask_applies("Lyra and Caia, coffee?", ME, HER) is True
    assert bot.open_ask_applies("Lyra, will you make coffee?", ME, HER) is False
    assert bot.open_ask_applies("CAIA, will you?", ME, HER) is False


# ---- Change 3: prune ----

def test_prune(tmp_path):
    d = tmp_path / ".locks" / "haven-ask"
    d.mkdir(parents=True)
    old, new = d / "old.lock", d / "new.lock"
    other = d / "keep.txt"
    outside = tmp_path / ".locks" / "outside.lock"
    for f in (old, new, other, outside):
        f.write_text("x")
    ancient = time.time() - 8 * 86400
    for f in (old, other, outside):
        os.utime(f, (ancient, ancient))
    assert bot.prune_old_ask_claims(tmp_path) == 1
    assert not old.exists()
    assert new.exists() and other.exists() and outside.exists()


def test_prune_missing_dir(tmp_path):
    assert bot.prune_old_ask_claims(tmp_path) == 0


# ---- the mechanism itself ----

def _claim(locks: Path, mid: str, holder: str, work: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(LOCK_PY), "--locks-dir", str(locks), "claim",
         f"haven-ask-{mid}", "--holder", holder, "--work", work],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def test_lock_claim_end_to_end(tmp_path):
    outs = []
    for holder, work in (("haven-lyra", "coffee"), ("haven-caia", "tea")):
        r = subprocess.run(
            [sys.executable, str(LOCK_PY), "--locks-dir", str(tmp_path), "claim",
             "haven-ask-123", "--holder", holder, "--work", work],
            capture_output=True, text=True,
        )
        outs.append(r)
        print(holder, r.returncode, repr(r.stdout), repr(r.stderr))
    assert outs[0].returncode == 0
    assert outs[1].returncode == 2
    combined = outs[1].stdout + outs[1].stderr
    assert "haven-lyra" in combined and "coffee" in combined
    assert "BLOCKED" in combined


def test_lock_claim_real_concurrency(tmp_path):
    barrier = threading.Barrier(2)
    for n in range(1, 31):
        res: dict[str, tuple[int, str]] = {}

        def go(holder: str, work: str) -> None:
            barrier.wait()
            p = _claim(tmp_path, str(1000 + n), holder, work)
            out, _ = p.communicate()
            res[holder] = (p.returncode, out)

        ts = [threading.Thread(target=go, args=a)
              for a in (("haven-lyra", "coffee"), ("haven-caia", "tea"))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        codes = sorted(c for c, _ in res.values())
        assert codes == [0, 2], f"round {n}: {res}"


def test_sister_present_from_room_history_on_a_cold_open(monkeypatch):
    """After a long quiet the recency window is empty; the room's recent history
    still shows she is a participant, so a cold-open ask gets the note."""
    from collections import deque
    monkeypatch.setattr(bot, "recent_room_authors", {})
    monkeypatch.setattr(bot, "room_history", {"r": deque([
        {"id": 1, "username": "jeff", "content": "night"},
        {"id": 2, "username": "lyra", "content": "night"},
    ])})
    assert bot._sister_present("r") is False  # only me and a human in history
    bot.room_history["r"].append({"id": 3, "username": "caia", "content": "night"})
    assert bot._sister_present("r") is True
    assert bot._sister_present("other-room") is False
