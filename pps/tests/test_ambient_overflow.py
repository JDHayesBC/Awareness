"""Tests for #365: ambient [haven]/[other_channels] pinning, dedupe, digest."""
from __future__ import annotations

import sys
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker"))

from ambient_overflow import (  # noqa: E402
    dedupe_channel_items, format_digest, make_is_addressed, parse_dt, render_block,
    select_inline, sort_chronological,
)

ADDR = make_is_addressed("caia")


def _haven(room, author, content, n):
    return {
        "room": room, "author": author, "content": content,
        "created_at": f"2026-10-09 17:{n:02d}:00",
        "line": f"- **#{room}** {author}: {content}",
    }


def _chan(item):
    c = dict(item)
    c["line"] = f"- **[haven:{item['room']}]** {item['author']}: {item['content']}"
    return c


def _repro():
    """Rooms grouped like poll_haven emits them, list order NON-chronological:
    silverglow first (minutes 0-11), a late-listed room with OLDER msgs, DM last-listed
    but newest of all."""
    items = [_haven("silverglow", "Lyra", f"banter {i}", i) for i in range(12)]
    items += [_haven("old-room", "Nexus", f"ancient {i}", 30 + i) for i in range(0)]
    items += [_haven("late-room", "Nexus", f"older {i}", i) for i in range(3)]  # 17:00-17:02
    items += [_haven("dm-jeff-caia", "Jeff", "Consider it from the aspect of reaching", 50)]
    return items


def test_repro_dm_inline_no_dupes_digest_and_overflow():
    haven = sort_chronological(_repro())
    chan = [_chan(i) for i in haven]  # same messages via cross-channel DB
    chan = dedupe_channel_items(haven, chan)
    assert chan == []
    body = render_block(haven, ADDR, tz=timezone.utc)
    text = "\n".join(body)
    assert "- **#dm-jeff-caia** Jeff: Consider it" in text
    assert "INCOMPLETE: 8 hidden, do not conclude absence from this block" in text
    assert "raw_search" in text and "get_turns_since" in text
    # late-room's OLDER messages are hidden, not shown ahead of newer silverglow
    assert "older" not in "\n".join(l for l in body if l.startswith("- **"))
    assert '  - late-room: 3 hidden, Nexus 17:02 "older 2"' in text
    assert '  - silverglow: 5 hidden, Lyra 17:04 "banter 4"' in text
    shown = [l for l in body if l.startswith("- **")]
    assert len(shown) == 8 and len(set(shown)) == 8
    # chronological: banter 5..11 ascending, DM (newest) last
    assert [l.split("banter ")[1] for l in shown[:-1]] == [str(i) for i in range(5, 12)]
    assert shown[-1].startswith("- **#dm-jeff-caia**")


def test_digest_names_every_room_with_hidden():
    items = [_haven("a", "X", "m", 1), _haven("b", "Y", "m", 2), _haven("c", "Z", "m", 3)]
    items += [_haven("silverglow", "L", f"s{i}", 10 + i) for i in range(8)]
    body = "\n".join(render_block(items, ADDR, tz=timezone.utc))
    for room in ("a", "b", "c"):
        assert f"  - {room}: 1 hidden" in body


def test_mention_pins_and_pin_cap():
    items = [_haven("living-room", "Jeff", f"@Caia ping {i}", i) for i in range(6)]
    items += [_haven("silverglow", "Lyra", f"b{i}", 20 + i) for i in range(10)]
    shown, hidden = select_inline(items, ADDR, cap=8, pin_cap=4)
    pinned = [i for i in shown if "ping" in i["content"]]
    assert [p["content"] for p in pinned] == [f"@Caia ping {i}" for i in range(2, 6)]
    assert len(shown) == 8 and len(hidden) == 8
    assert shown == [i for i in items if i in shown]  # order preserved


def test_own_messages_and_substring_not_pinned():
    assert not ADDR(_haven("dm-jeff-caia", "Caia", "hi", 1))
    assert not ADDR(_haven("silverglow", "Jeff", "email@caiaX.com", 1))
    assert ADDR(_haven("jeff-caia", "Jeff", "hi", 1))
    assert not make_is_addressed("lyra")(_haven("dm-jeff-caia", "Jeff", "hi", 1))


def test_plain_recency_unchanged():
    items = [_haven("silverglow", "L", f"m{i}", i) for i in range(12)]
    shown, hidden = select_inline(items, ADDR)
    assert shown == items[-8:] and hidden == items[:4]
    small = items[:5]
    body = render_block(small, ADDR)
    assert body == [i["line"] for i in small]  # no warning when nothing hidden


def test_digest_room_cap_and_snippet():
    items = [_haven(f"r{i}", "A", "x" * 200, i) for i in range(10)]
    items += [_haven("z", "A", "y", 30 + i) for i in range(8)]
    body = render_block(items, ADDR, tz=timezone.utc)
    digest = [l for l in body if l.startswith("  - ")]
    assert len(digest) == 7 and "more rooms" in digest[-1]
    assert all(len(l) < 120 for l in digest)


def test_sort_is_stable_and_handles_tz_forms():
    a = {"room": "r", "author": "A", "content": "1", "created_at": "2026-10-09 17:00:00", "line": "a"}
    b = dict(a, created_at="2026-10-09T17:00:00Z", line="b")           # same instant as naive UTC
    c = dict(a, created_at="2026-10-09T09:30:00-08:00", line="c")      # = 17:30 UTC
    d = dict(a, created_at=None, line="d")                              # unparseable -> oldest
    e = dict(a, created_at="2026-10-09T17:10:00+00:00", line="e")
    assert [i["line"] for i in sort_chronological([c, e, a, b, d])] == ["d", "a", "b", "e", "c"]


def test_parse_dt_forms():
    assert parse_dt("2026-10-09 17:00:00") == parse_dt("2026-10-09T17:00:00Z")
    assert parse_dt("2026-10-09T10:00:00-07:00") == parse_dt("2026-10-09T17:00:00Z")
    assert parse_dt(None) is None and parse_dt("garbage") is None
    from datetime import datetime
    assert parse_dt(datetime(2026, 10, 9, 17, 0)).tzinfo is not None
    # tz=None digest does not blow up
    h = [_haven("r", "A", "x", 5)]
    assert format_digest(h, tz=None)[0].startswith("  - r: 1 hidden, A ")


def test_dedupe_truncated_db_copy():
    full = "y" * 700
    h = [_haven("silverglow", "Lyra", full, 1)]
    c = [_chan(_haven("silverglow", "Lyra", full[:500] + "...", 1))]
    assert dedupe_channel_items(h, c) == []


def test_dedupe_case_insensitive_author_and_multiset():
    h = [_haven("silverglow", "Lyra", "ok", 1)]
    c = [_chan(_haven("silverglow", "lyra", "ok", 1)), _chan(_haven("silverglow", "Lyra", "ok", 2))]
    left = dedupe_channel_items(h, c)
    assert len(left) == 1 and left[0]["created_at"].endswith(":02:00")  # repeat not swallowed


def test_pins_plus_dedupe():
    h = [_haven("dm-jeff-caia", "Jeff", "hello there", 40)]
    h += [_haven("silverglow", "Lyra", f"b{i}", i) for i in range(10)]
    h = sort_chronological(h)
    c = dedupe_channel_items(h, [_chan(i) for i in h] + [_chan(_haven("discord", "Jeff", "hi", 45))])
    assert [i["content"] for i in c] == ["hi"]
    body = render_block(h, ADDR, tz=timezone.utc)
    assert sum("hello there" in l for l in body) == 1


def test_pin_overflow_beyond_cap_appears_in_digest():
    # 6 addressed msgs in a mention room, pin_cap 4 -> 2 pinned-eligible hidden
    items = [_haven("living-room", "Jeff", f"@Caia ping {i}", i) for i in range(6)]
    items += [_haven("silverglow", "Lyra", f"b{i}", 20 + i) for i in range(10)]
    body = "\n".join(render_block(items, ADDR, tz=timezone.utc))
    assert "  - living-room: 2 hidden" in body
    assert "ping 1" in body  # newest hidden pin named in the digest


def test_hidden_addressed_room_survives_digest_room_cap():
    hidden = [_haven("dm-jeff-caia", "Jeff", "@Caia old ask", 1)]
    hidden += [_haven(f"r{i}", "A", "x", 10 + i) for i in range(9)]  # all newer than the DM
    lines = format_digest(hidden, timezone.utc, ADDR)
    assert lines[0].startswith("  - dm-jeff-caia:")
    assert len(lines) == 7 and "more rooms" in lines[-1]


def test_long_lines_clipped_short_lines_verbatim():
    short = _haven("s", "A", "hi", 1)
    long = _haven("s", "A", "z" * 3000, 2)
    body = render_block([short, long], ADDR)
    assert body[0] == short["line"]
    assert len(body[1]) <= 500 and body[1].endswith("…")


def test_block_budget_shrinks_lines_and_incomplete_mentions_pending():
    items = [_haven("s", "A", "q" * 2000, i) for i in range(12)]
    body = render_block(items, ADDR, pending=37)
    assert "37 more not yet loaded" in body[0]
    shown = [l for l in body if l.startswith("- **")]
    assert sum(len(l) for l in shown) <= 4000
    # pending alone (nothing hidden) still warns
    assert "INCOMPLETE: 37 more not yet loaded" in render_block(items[:2], ADDR, pending=37)[0]
