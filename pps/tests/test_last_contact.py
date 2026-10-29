"""#383: [last-contact] and [first-meeting] ambient lines (pps/docker/last_contact.py).

All fixtures are throwaway sqlite files -- never real entity data.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

DOCKER = Path(__file__).resolve().parents[1] / "docker"
sys.path.insert(0, str(DOCKER))

import last_contact as lc  # noqa: E402

NOW = datetime(2026, 10, 29, 20, 0, 0, tzinfo=timezone.utc)
HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "inject_context.py"


def _fmt(dt: datetime) -> str:
    """conversations.db format: naive UTC 'YYYY-MM-DD HH:MM:SS'."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


@pytest.fixture
def conv(tmp_path):
    p = tmp_path / "conversations.db"
    c = sqlite3.connect(p)
    c.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "author_name TEXT NOT NULL, content TEXT NOT NULL, channel TEXT, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    c.commit()
    c.close()
    return p


def add(db, author, when: datetime, content="hello", channel="haven:commons"):
    c = sqlite3.connect(db)
    c.execute(
        "INSERT INTO messages (author_name, content, channel, created_at) VALUES (?,?,?,?)",
        (author, content, channel, _fmt(when)),
    )
    c.commit()
    c.close()


@pytest.fixture
def inv(tmp_path):
    p = tmp_path / "inventory.db"
    c = sqlite3.connect(p)
    c.execute(
        "CREATE TABLE entity_presence (id INTEGER PRIMARY KEY CHECK (id = 1), "
        "current_space TEXT, since TIMESTAMP, source TEXT, pending_arrival TEXT, ack_space TEXT)"
    )
    c.commit()
    c.close()
    return p


def set_presence(db, space, since_iso):
    c = sqlite3.connect(db)
    c.execute("DELETE FROM entity_presence")
    c.execute("INSERT INTO entity_presence (id, current_space, since) VALUES (1,?,?)", (space, since_iso))
    c.commit()
    c.close()


# ---------------------------------------------------------------- [last-contact]
def test_latest_jeff_row_wins_across_channels(conv, inv):
    add(conv, "Jeff", _ago(hours=5), channel="terminal")
    add(conv, "Jeff", _ago(minutes=76), channel="haven:silverglow")
    add(conv, "Jeff", _ago(hours=3), channel="discord:general")
    add(conv, "Lyra", _ago(minutes=1), channel="haven:silverglow")  # not Jeff
    set_presence(inv, "dock", _ago(hours=9).isoformat())
    line = lc.format_last_contact_line(conv, inv, now=NOW)
    assert line == "[last-contact] Jeff: 1h16m ago (haven:silverglow) · moved since: no"


@pytest.mark.parametrize("tick", [
    "[heartbeat · floor tick — 2h] re-anchor",
    "[floor tick] check in",
    "Heartbeat (2h floor — Lyra) re-anchor",
    "[overnight heartbeat] still here",
    "<task-notification>x</task-notification>",
])
def test_harness_row_newer_than_real_one_is_ignored(conv, inv, tick):
    add(conv, "Jeff", _ago(minutes=40), content="actual words from Jeff", channel="terminal")
    add(conv, "Jeff", _ago(minutes=2), content=tick, channel="terminal")
    set_presence(inv, "dock", _ago(hours=9).isoformat())
    line = lc.format_last_contact_line(conv, inv, now=NOW)
    assert "Jeff: 40m ago (terminal)" in line


def test_jeff_never_when_only_harness_rows(conv, inv):
    add(conv, "Jeff", _ago(minutes=2), content="[floor tick] x")
    assert lc.format_last_contact_line(conv, inv, now=NOW) == "[last-contact] Jeff: never"


def test_jeff_never_when_no_rows(conv, inv):
    assert lc.format_last_contact_line(conv, inv, now=NOW) == "[last-contact] Jeff: never"


def test_real_message_mentioning_tick_midline_is_kept(conv, inv):
    add(conv, "Jeff", _ago(minutes=5), content="the tick prompt looks odd", channel="terminal")
    set_presence(inv, "dock", _ago(hours=9).isoformat())
    assert "Jeff: 5m ago" in lc.format_last_contact_line(conv, inv, now=NOW)


def test_moved_since_yes_with_mixed_iso_formats(conv, inv):
    # Jeff's row: naive 'YYYY-MM-DD HH:MM:SS'.  Presence: ISO 'T' + microseconds + offset.
    # String comparison would get these backwards ('2026-10-29 18:...' > '2026-10-29T...' is
    # decided by ' ' < 'T'); real datetimes must be compared.
    add(conv, "Jeff", datetime(2026, 10, 29, 18, 0, 0, tzinfo=timezone.utc))
    set_presence(inv, "silverglow_bedroom", "2026-10-29T18:30:00.062517+00:00")
    line = lc.format_last_contact_line(conv, inv, now=NOW)
    assert line.endswith("moved since: yes (silverglow_bedroom)")


def test_moved_since_no_when_presence_older_even_if_string_order_says_otherwise(conv, inv):
    add(conv, "Jeff", datetime(2026, 10, 29, 18, 0, 0, tzinfo=timezone.utc))
    # Same day, EARLIER than Jeff's row, but 'T' > ' ' so a string compare says "later".
    set_presence(inv, "dock", "2026-10-29T17:59:59.5+00:00")
    assert lc.format_last_contact_line(conv, inv, now=NOW).endswith("moved since: no")


def test_moved_since_handles_non_utc_offset(conv, inv):
    add(conv, "Jeff", datetime(2026, 10, 29, 18, 0, 0, tzinfo=timezone.utc))
    # 11:30-07:00 == 18:30Z -> after Jeff
    set_presence(inv, "deck", "2026-10-29T11:30:00-07:00")
    assert "moved since: yes (deck)" in lc.format_last_contact_line(conv, inv, now=NOW)


def test_inventory_missing_keeps_line_without_moved_clause(conv, tmp_path):
    add(conv, "Jeff", _ago(minutes=5), channel="terminal")
    line = lc.format_last_contact_line(conv, tmp_path / "nope.db", now=NOW)
    assert line == "[last-contact] Jeff: 5m ago (terminal)"


@pytest.mark.parametrize("delta,expected", [
    (timedelta(seconds=0), "just now"),
    (timedelta(seconds=59), "just now"),
    (timedelta(seconds=-30), "just now"),  # clock skew
    (timedelta(seconds=60), "1m"),
    (timedelta(minutes=59, seconds=59), "59m"),
    (timedelta(minutes=60), "1h0m"),
    (timedelta(hours=1, minutes=16), "1h16m"),
    (timedelta(hours=47, minutes=59), "47h59m"),
    (timedelta(hours=48), "2d"),
    (timedelta(hours=100), "4d"),
])
def test_human_duration(delta, expected):
    assert lc.human_duration(delta) == expected


def test_just_now_has_no_ago(conv, inv):
    add(conv, "Jeff", _ago(seconds=10), channel="terminal")
    set_presence(inv, "dock", _ago(hours=9).isoformat())
    assert "Jeff: just now (terminal)" in lc.format_last_contact_line(conv, inv, now=NOW)


def test_last_contact_omitted_on_missing_table(tmp_path, inv):
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    assert lc.format_last_contact_line(empty, inv, now=NOW) is None
    assert lc.format_last_contact_line(tmp_path / "missing.db", inv, now=NOW) is None


def test_harness_filter_matches_hook():
    """The docker image can't import .claude/hooks, so the filter is duplicated;
    this keeps the copy honest against the source of truth."""
    spec = importlib.util.spec_from_file_location("inject_context_under_test", HOOK)
    src = HOOK.read_text()
    # Pull the three definitions by exec'ing only the relevant slice (importing the
    # whole hook runs main-adjacent setup).
    start = src.index("HARNESS_PROMPT_PREFIXES = (")
    end = src.index("return head.startswith(HARNESS_PROMPT_PREFIXES)")
    end = src.index("\n", end)
    ns: dict = {"re": __import__("re")}
    exec(src[start:end], ns)
    assert tuple(ns["HARNESS_PROMPT_PREFIXES"]) == lc.HARNESS_PROMPT_PREFIXES
    assert ns["HARNESS_TICK_TAG_RE"].pattern == lc.HARNESS_TICK_TAG_RE.pattern
    for sample in ["[floor tick] x", "hello", "[Ticket #12] hi", "Heartbeat (2h floor) x", "[ticker] y"]:
        assert ns["is_non_jeff_prompt"](sample) == lc.is_non_jeff_prompt(sample)


# -------------------------------------------------------------- [first-meeting]
def test_scan_includes_new_author_excludes_old_and_self(conv):
    add(conv, "Jeff", _ago(days=200))
    add(conv, "Jeff", _ago(minutes=2))  # active today, but first spoke long ago
    add(conv, "Lyra", _ago(minutes=1))  # self
    add(conv, "LyraPattern", _ago(minutes=1))  # self's avatar
    add(conv, "Henry", _ago(minutes=3), channel="haven:commons")
    add(conv, "Marta", _ago(days=3))
    add(conv, "Marta", _ago(minutes=4))  # returning guest, first row 3 days ago
    lines = lc.format_first_meeting_lines(conv, "lyra", now=NOW)
    assert lines == [
        "[first-meeting] Henry — first spoke 3m ago (haven:commons) · greet from your body first"
    ]


def test_scan_excludes_system_and_uuid_authors(conv):
    for a in ["system", "c06d8847-53af-4983-97f7-99dc20566583",
              "Malwarebytes <noreply@e.malwarebytes.com>"]:
        add(conv, a, _ago(minutes=2))
    assert lc.format_first_meeting_lines(conv, "lyra", now=NOW) == []


def test_scan_caps_at_three(conv):
    for i, n in enumerate(["Ann", "Bob", "Cy", "Di", "Ed"]):
        add(conv, n, _ago(minutes=10 - i))
    assert len(lc.format_first_meeting_lines(conv, "lyra", now=NOW)) == 3


def test_speakers_cap_at_three(conv):
    lines = lc.format_first_meeting_lines(
        conv, "lyra", speakers=["A1", "B2", "C3", "D4", "E5"], channel_hint="haven", now=NOW
    )
    assert len(lines) == 3


def test_line_has_no_cross_reference(conv):
    add(conv, "Henry", _ago(minutes=3))
    (line,) = lc.format_first_meeting_lines(conv, "lyra", now=NOW)
    low = line.lower()
    assert "aka" not in low and "also known" not in low and "seen elsewhere" not in low


def test_speaker_a_zero_rows_bridge_lost_the_race(conv):
    add(conv, "Jeff", _ago(days=100))  # unrelated old traffic
    lines = lc.format_first_meeting_lines(
        conv, "lyra", speakers=["Henry"], channel_hint="haven", now=NOW
    )
    assert lines == [
        "[first-meeting] Henry — first spoke just now (haven) · greet from your body first"
    ]


def test_speaker_b_single_row_stored_seconds_ago_bridge_won(conv):
    add(conv, "Henry", _ago(seconds=4), channel="haven:commons")
    lines = lc.format_first_meeting_lines(
        conv, "lyra", speakers=["Henry"], channel_hint="haven", now=NOW
    )
    assert lines == [
        "[first-meeting] Henry — first spoke just now (haven:commons) · greet from your body first"
    ]


def test_speaker_c_oldest_row_two_days_old_not_flagged(conv):
    add(conv, "Marta", _ago(days=2), channel="haven:commons")
    add(conv, "Marta", _ago(seconds=4), channel="haven:commons")
    assert lc.format_first_meeting_lines(
        conv, "lyra", speakers=["Marta"], channel_hint="haven", now=NOW
    ) == []


def test_speakers_exclude_self_and_dedupe(conv):
    lines = lc.format_first_meeting_lines(
        conv, "lyra", speakers=["Lyra", "lyra", "Henry", "Henry", "henry", "  "],
        channel_hint="haven", now=NOW,
    )
    assert [l.split(" — ")[0] for l in lines] == ["[first-meeting] Henry"]


def test_speakers_given_means_no_24h_scan(conv):
    add(conv, "Stranger", _ago(minutes=1))  # new, but not a speaker this turn
    add(conv, "Jeff", _ago(days=50))
    assert lc.format_first_meeting_lines(conv, "lyra", speakers=["Jeff"], now=NOW) == []


def test_first_meeting_omitted_on_missing_table(tmp_path):
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    assert lc.format_first_meeting_lines(empty, "lyra", now=NOW) == []
    # A DB error must not read as "no rows -> new person":
    assert lc.format_first_meeting_lines(empty, "lyra", speakers=["Henry"], now=NOW) == []
    assert lc.format_first_meeting_lines(tmp_path / "missing.db", "lyra", speakers=["Henry"], now=NOW) == []


def test_layer_creates_author_index(tmp_path):
    """The earliest-row-per-author lookup must be an index seek, not a table scan."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from layers.message_summaries import MessageSummariesLayer
    db = tmp_path / "c.db"
    pre = sqlite3.connect(db)  # messages is created by the daemon, not the layer
    pre.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "author_name TEXT, content TEXT, channel TEXT, created_at TIMESTAMP)")
    pre.commit()
    pre.close()
    MessageSummariesLayer(db_path=db)
    c = sqlite3.connect(db)
    names = {r[1] for r in c.execute("PRAGMA index_list(messages)")}
    assert "idx_messages_author_name_time" in names
    plan = " ".join(str(r) for r in c.execute(
        "EXPLAIN QUERY PLAN SELECT MIN(created_at) FROM messages WHERE author_name = 'x'"))
    assert "idx_messages_author_name_time" in plan
