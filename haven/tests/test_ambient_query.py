"""build_ambient_query: the text sent to ambient_recall for a Haven turn (#409)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("ENTITY_NAME", "lyra")
os.environ.setdefault("ENTITY_TOKEN", "test-token")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from haven.bot import AMBIENT_QUERY_MAX_CHARS, build_ambient_query  # noqa: E402

BOTS = {"lyra", "caia"}


def _m(user: str, text: str, mid: int | None = None) -> dict:
    d = {"username": user, "display_name": user.title(), "content": text}
    if mid is not None:
        d["id"] = mid
    return d


def q(messages):
    return build_ambient_query(messages, BOTS, "lyra")


def test_humans_only_oldest_first():
    msgs = [_m("pat", "the kettle is on", 1), _m("sam", "tea sounds good", 2)]
    assert q(msgs) == "the kettle is on\ntea sounds good"


def test_mixed_human_and_bot_keeps_only_humans():
    msgs = [
        _m("pat", "how was the garden", 1),
        _m("caia", "lovely out there"),
        _m("lyra", "my own earlier reply"),
        _m("pat", "any tomatoes yet", 2),
    ]
    assert q(msgs) == "how was the garden\nany tomatoes yet"


def test_bot_only_uses_latest_message():
    msgs = [_m("caia", "first thought"), _m("caia", "second thought")]
    assert q(msgs) == "second thought"


def test_empty_batch():
    assert q([]) == ""
    assert q([_m("pat", "   "), _m("caia", "")]) == ""


def test_over_long_keeps_recent_end():
    old = "a" * 700
    new = "z" * 700
    out = q([_m("pat", old, 1), _m("pat", new, 2)])
    assert len(out) == AMBIENT_QUERY_MAX_CHARS
    assert out.endswith("z" * 700)
    assert out.startswith("a")  # 100 trailing chars of the older line + newline survive


def test_whitespace_and_newlines_normalised():
    out = q([_m("pat", "  two\n\nlines \t and   gaps  ", 1)])
    assert out == "two lines and gaps"


def test_formatting_prefixes_stripped():
    msgs = [
        _m("pat", "[msg 12] what time is it", 1),
        _m("sam", "[ATTACHED IMAGE - call Read('/x/y.jpg') first] look at this", 2),
        _m("caia", "[from terminal-caia] hello"),
    ]
    assert q(msgs) == "what time is it\nlook at this"
    assert q([_m("caia", "[from terminal-caia] hello there")]) == "hello there"
