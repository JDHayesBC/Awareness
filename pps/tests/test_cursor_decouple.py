"""
Tests for issue #176: consumer_key/channel decouple in cursor lookup.

Covers:
- Two consumer_keys on the same channel get independent Haven cursors.
- Two consumer_keys on the same channel get independent cross-channel cursors.
- Missing consumer_key falls back to channel (backward compatibility).
- Cursor advance for one consumer doesn't affect another.
- Channel filter (excluding self-channel from results) still works correctly
  when consumer_key is set.

The cursor helpers live in pps/docker/server_http.py, which has heavy
import-time side effects (loads layers, waits for chromadb/neo4j). To test
the cursor logic in isolation, we extract the relevant function definitions
from the source file via AST and exec them in a controlled namespace with
mocked globals — this exercises the *actual production code* without
booting the full server.
"""

import ast
import asyncio
import json
import sqlite3
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Path to the production source we're testing.
SERVER_HTTP = (
    Path(__file__).resolve().parent.parent / "docker" / "server_http.py"
)


def _extract_functions(source: str, names: set[str]) -> str:
    """Parse `source` and return the concatenated source for top-level
    functions/async-functions whose names are in `names`."""
    tree = ast.parse(source)
    chunks: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            chunks.append(ast.get_source_segment(source, node))
    missing = names - {
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if missing:
        raise RuntimeError(f"Couldn't find functions in source: {missing}")
    return "\n\n".join(chunks)


@pytest.fixture
def cursor_helpers(tmp_path):
    """Compile the cursor helpers from server_http.py into an isolated
    namespace, with file paths redirected to tmp_path. Returns a dict with
    the callable helpers."""
    haven_file = tmp_path / "haven_last_seen.json"
    channel_file = tmp_path / "channel_last_seen.json"

    src = SERVER_HTTP.read_text()
    helper_src = _extract_functions(
        src,
        {
            "_load_haven_last_seen",
            "_save_haven_last_seen",
            "_load_channel_cursors",
            "_save_channel_cursors",
            "_advance_cursor_on_startup",
            "poll_other_channels",
            "poll_haven",
        },
    )

    # Build a namespace mimicking server_http's module globals (only the bits
    # the helpers reference). We swap out the on-disk paths and the entity
    # path so the helpers operate against tmp_path.
    ns: dict = {
        "__name__": "cursor_helpers_under_test",
        "json": json,
        "sys": __import__("sys"),
        "_haven_last_seen_file": haven_file,
        "_channel_cursor_file": channel_file,
        # ENTITY_PATH used by poll_other_channels to find conversations.db
        "ENTITY_PATH": tmp_path,
        # poll_haven won't actually run network calls in our tests because
        # we'll patch HAVEN_URL to "" — but if it's referenced we want it
        # defined.
        "HAVEN_URL": "",
        "ENTITY_TOKEN": "test-token",
        "ENTITY_NAME": "test_entity",
        # httpx is imported lazily in poll_haven; provide a stub.
        "httpx": MagicMock(),
    }
    exec(compile(helper_src, str(SERVER_HTTP), "exec"), ns)
    return ns


def _seed_messages_db(db_path: Path, rows: list[tuple]):
    """Create a minimal conversations.db with a `messages` table seeded with rows.

    Each row is (id, author_name, content, created_at, channel)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            author_name TEXT,
            content TEXT,
            created_at TEXT,
            channel TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO messages (id, author_name, content, created_at, channel) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


# ============================================================================
# poll_other_channels — cross-channel cursor logic
# ============================================================================


def test_two_consumer_keys_same_channel_independent_cursors(cursor_helpers, tmp_path):
    """Two consumer_keys on the same logical channel each get their own cursor.

    This is the core fix for #176: heartbeat-fired session and interactive
    session both call channel="terminal" — without the fix, whichever polls
    first eats the messages for the other. With consumer_key set, each gets
    an independent read position.
    """
    db_path = tmp_path / "data" / "conversations.db"
    _seed_messages_db(
        db_path,
        [
            (1, "Jeff", "msg from haven A", "2026-04-28T10:00:00Z", "haven"),
            (2, "Jeff", "msg from haven B", "2026-04-28T10:01:00Z", "haven"),
            (3, "Jeff", "msg from haven C", "2026-04-28T10:02:00Z", "haven"),
        ],
    )

    poll = cursor_helpers["poll_other_channels"]

    # Consumer A polls channel="terminal" — should see all 3 haven messages
    lines_a, remaining_a = poll(
        requesting_channel="terminal",
        limit=100,
        consumer_key="terminal:aaaaaaaa",
    )
    assert len(lines_a) == 3
    assert remaining_a == 0

    # Consumer B polls channel="terminal" with a *different* consumer_key —
    # cursor is independent, so B should also see all 3 messages.
    lines_b, remaining_b = poll(
        requesting_channel="terminal",
        limit=100,
        consumer_key="terminal:bbbbbbbb",
    )
    assert len(lines_b) == 3, (
        "Consumer B should see all 3 messages — its cursor is independent of A's"
    )
    assert remaining_b == 0


def test_consumer_key_advance_does_not_affect_other_consumer(cursor_helpers, tmp_path):
    """Advancing consumer A's cursor must not change what consumer B sees."""
    db_path = tmp_path / "data" / "conversations.db"
    _seed_messages_db(
        db_path,
        [
            (10, "Jeff", "msg 10", "2026-04-28T10:00:00Z", "haven"),
            (11, "Jeff", "msg 11", "2026-04-28T10:01:00Z", "haven"),
            (12, "Jeff", "msg 12", "2026-04-28T10:02:00Z", "haven"),
        ],
    )
    poll = cursor_helpers["poll_other_channels"]

    # A drains
    poll(requesting_channel="terminal", limit=100, consumer_key="terminal:aaaaaaaa")
    # A polls again: cursor at 12, nothing new
    lines_a2, _ = poll(
        requesting_channel="terminal", limit=100, consumer_key="terminal:aaaaaaaa"
    )
    assert lines_a2 == []

    # B has never polled — its cursor is at 0 — sees all 3
    lines_b, _ = poll(
        requesting_channel="terminal", limit=100, consumer_key="terminal:bbbbbbbb"
    )
    assert len(lines_b) == 3


def test_missing_consumer_key_falls_back_to_channel(cursor_helpers, tmp_path):
    """Backward compat: callers that don't pass consumer_key get the same
    behavior as before — cursor identity defaults to the channel."""
    db_path = tmp_path / "data" / "conversations.db"
    _seed_messages_db(
        db_path,
        [
            (1, "Jeff", "msg 1", "2026-04-28T10:00:00Z", "haven"),
            (2, "Jeff", "msg 2", "2026-04-28T10:01:00Z", "haven"),
        ],
    )
    poll = cursor_helpers["poll_other_channels"]

    # Caller A: legacy style — no consumer_key, just channel.
    lines_a, _ = poll(requesting_channel="terminal", limit=100)
    assert len(lines_a) == 2

    # Caller B: also no consumer_key, same channel — should hit the SAME
    # cursor as A (cursor key falls back to "terminal"). So sees nothing.
    lines_b, _ = poll(requesting_channel="terminal", limit=100)
    assert lines_b == [], (
        "Without consumer_key, cursor falls back to channel-keyed lookup — "
        "two callers with no consumer_key on the same channel share a cursor "
        "(this is the pre-fix behavior; preserved for backward compat)."
    )


def test_consumer_key_with_no_channel_uses_default_filter(cursor_helpers, tmp_path):
    """When channel is empty, consumer_key still drives the cursor — and the
    requesting-channel filter doesn't exclude any rows."""
    db_path = tmp_path / "data" / "conversations.db"
    _seed_messages_db(
        db_path,
        [
            (1, "Jeff", "msg 1", "2026-04-28T10:00:00Z", "haven"),
            (2, "Jeff", "msg 2", "2026-04-28T10:01:00Z", "discord"),
        ],
    )
    poll = cursor_helpers["poll_other_channels"]

    # consumer_key="reflection-job", no channel filter
    lines, _ = poll(requesting_channel="", limit=100, consumer_key="reflection-job")
    assert len(lines) == 2

    # Same consumer_key polls again — no new messages
    lines2, _ = poll(requesting_channel="", limit=100, consumer_key="reflection-job")
    assert lines2 == []

    # Different consumer_key, same call — should see all messages (independent
    # cursor)
    lines3, _ = poll(requesting_channel="", limit=100, consumer_key="other-job")
    assert len(lines3) == 2


def test_channel_filter_unaffected_by_consumer_key(cursor_helpers, tmp_path):
    """The channel filter (exclude messages from requesting_channel) is
    independent of consumer_key — only the cursor identity is decoupled."""
    db_path = tmp_path / "data" / "conversations.db"
    _seed_messages_db(
        db_path,
        [
            (1, "Jeff", "haven msg", "2026-04-28T10:00:00Z", "haven"),
            (2, "Jeff", "terminal msg", "2026-04-28T10:01:00Z", "terminal"),
            (3, "Jeff", "discord msg", "2026-04-28T10:02:00Z", "discord"),
        ],
    )
    poll = cursor_helpers["poll_other_channels"]

    # Consumer claiming "terminal" should NOT see "terminal" messages,
    # regardless of its consumer_key.
    lines, _ = poll(
        requesting_channel="terminal",
        limit=100,
        consumer_key="terminal:custom123",
    )
    contents = " ".join(lines)
    assert "haven msg" in contents
    assert "discord msg" in contents
    assert "terminal msg" not in contents, (
        "Channel filter must still exclude self-channel even with custom consumer_key"
    )


def test_cursor_persisted_to_disk_under_consumer_key(cursor_helpers, tmp_path):
    """After a poll, the channel cursor file must contain a top-level entry
    keyed by consumer_key (not channel) when consumer_key is supplied."""
    db_path = tmp_path / "data" / "conversations.db"
    _seed_messages_db(
        db_path,
        [(1, "Jeff", "x", "2026-04-28T10:00:00Z", "haven")],
    )
    poll = cursor_helpers["poll_other_channels"]
    poll(
        requesting_channel="terminal",
        limit=100,
        consumer_key="terminal:abc12345",
    )
    cursors = json.loads((tmp_path / "channel_last_seen.json").read_text())
    assert "terminal:abc12345" in cursors
    assert cursors["terminal:abc12345"] >= 1


# ============================================================================
# poll_haven — Haven cursor logic
# ============================================================================


def _patch_haven_client(cursor_helpers, room_id: str, messages: list[dict]):
    """Patch httpx.AsyncClient inside the cursor_helpers namespace so
    poll_haven sees a single room with the given messages."""
    rooms_response = MagicMock()
    rooms_response.status_code = 200
    rooms_response.json = lambda: {
        "rooms": [{"id": room_id, "display_name": "test-room"}]
    }
    msgs_response = MagicMock()
    msgs_response.status_code = 200
    msgs_response.json = lambda: {"messages": messages}

    client = MagicMock()
    client.get = AsyncMock(side_effect=[rooms_response, msgs_response])

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    cursor_helpers["httpx"].AsyncClient = MagicMock(return_value=ctx)
    cursor_helpers["HAVEN_URL"] = "http://test-haven"


def test_haven_two_consumer_keys_independent_cursors(cursor_helpers, tmp_path):
    """Two consumer_keys polling the same Haven room each track their own cursor."""
    room_id = "room-1"
    msgs = [
        {
            "username": "jeff",
            "display_name": "Jeff",
            "content": "first",
            "created_at": "2026-04-28T10:00:00Z",
        },
        {
            "username": "jeff",
            "display_name": "Jeff",
            "content": "second",
            "created_at": "2026-04-28T10:01:00Z",
        },
    ]

    # Pre-seed the cursor file with consumer_key A already at the second message.
    seed = {
        "terminal:aaaaaaaa": {room_id: "2026-04-28T10:01:00Z"},
    }
    (tmp_path / "haven_last_seen.json").write_text(json.dumps(seed))

    poll_haven = cursor_helpers["poll_haven"]

    # Consumer B polls the room for the first time — its cursor is unset, so
    # it should fall back to the legacy entry (none) and treat this as a
    # first poll (no lines, but advance cursor).
    _patch_haven_client(cursor_helpers, room_id, msgs)
    lines_b = asyncio.run(
        poll_haven(requesting_channel="terminal", consumer_key="terminal:bbbbbbbb")
    )
    # First poll for B: nothing returned (we don't dump backlog) but cursor advances.
    assert lines_b == []

    persisted = json.loads((tmp_path / "haven_last_seen.json").read_text())
    assert "terminal:bbbbbbbb" in persisted
    # Consumer A's cursor must NOT have been changed.
    assert persisted["terminal:aaaaaaaa"][room_id] == "2026-04-28T10:01:00Z"


def test_haven_missing_consumer_key_falls_back_to_channel(cursor_helpers, tmp_path):
    """Without consumer_key, cursor key falls back to requesting_channel
    (backward compat with pre-#176 callers)."""
    room_id = "room-1"
    msgs = [
        {
            "username": "jeff",
            "display_name": "Jeff",
            "content": "msg",
            "created_at": "2026-04-28T10:00:00Z",
        },
    ]

    poll_haven = cursor_helpers["poll_haven"]

    _patch_haven_client(cursor_helpers, room_id, msgs)
    lines = asyncio.run(poll_haven(requesting_channel="terminal"))  # no consumer_key
    assert lines == []  # first poll, no backlog dump

    persisted = json.loads((tmp_path / "haven_last_seen.json").read_text())
    assert "terminal" in persisted, (
        "Without consumer_key, cursor must persist under the channel name"
    )
    # consumer_key NOT used as cursor key — there should be no "terminal:..." entry
    assert not any(k.startswith("terminal:") for k in persisted)


def test_haven_legacy_flat_format_migrated(cursor_helpers, tmp_path):
    """A legacy flat haven_last_seen.json (raw room->timestamp map) migrates
    into the "_legacy" key on first read so existing consumers don't dump
    full backlog when they next poll."""
    room_id = "room-1"
    legacy_state = {room_id: "2026-04-28T09:00:00Z"}
    (tmp_path / "haven_last_seen.json").write_text(json.dumps(legacy_state))

    load = cursor_helpers["_load_haven_last_seen"]
    state = load()
    assert state == {"_legacy": legacy_state}


def test_consumer_key_takes_precedence_over_channel(cursor_helpers, tmp_path):
    """When BOTH consumer_key and channel are set, consumer_key wins for the
    cursor identity — channel only drives the filter."""
    db_path = tmp_path / "data" / "conversations.db"
    _seed_messages_db(
        db_path,
        [
            (1, "Jeff", "haven msg", "2026-04-28T10:00:00Z", "haven"),
            (2, "Jeff", "discord msg", "2026-04-28T10:01:00Z", "discord"),
        ],
    )
    poll = cursor_helpers["poll_other_channels"]

    # Pre-seed cursor file with channel="terminal" already at id=999 (would
    # exclude all messages if used).
    (tmp_path / "channel_last_seen.json").write_text(json.dumps({"terminal": 999}))

    # consumer_key is fresh — should NOT pick up the "terminal" cursor.
    lines, _ = poll(
        requesting_channel="terminal",
        limit=100,
        consumer_key="terminal:freshxxx",
    )
    assert len(lines) == 2, (
        "consumer_key must override channel as the cursor identity — fresh "
        "consumer_key means cursor starts at 0, sees both messages"
    )


# ============================================================================
# _advance_cursor_on_startup — issue #199: startup must not stomp other
# consumers' cursors. The pre-#199 implementation looped over every key in
# the cursor file and set them all to max_id, which meant any consumer's
# startup wiped out cross-channel awareness for every other running consumer.
# ============================================================================


def test_startup_advance_only_touches_requesting_consumer(cursor_helpers, tmp_path):
    """A startup advance for consumer A must NOT advance consumer B's cursor.

    This is the core regression for #199: a Haven-bot subprocess startup
    used to wipe out the terminal session's cursor past unread messages.
    """
    advance = cursor_helpers["_advance_cursor_on_startup"]

    # Pre-seed two consumers with distinct cursor positions.
    (tmp_path / "channel_last_seen.json").write_text(json.dumps({
        "terminal:aaaa1111": 100,  # interactive terminal session
        "terminal:bbbb2222": 200,  # haven-bot subprocess (different consumer)
    }))

    # Haven-bot startup advances ITS cursor to current max — must NOT touch
    # the terminal session's cursor.
    advance(consumer_key="terminal:bbbb2222", channel="terminal", max_id=999)

    state = json.loads((tmp_path / "channel_last_seen.json").read_text())
    assert state["terminal:aaaa1111"] == 100, (
        "Other consumer's cursor must be untouched by a different consumer's "
        "startup — that was the #199 bug"
    )
    assert state["terminal:bbbb2222"] == 999, (
        "Requesting consumer's cursor must be advanced to max_id"
    )


def test_startup_advance_consumer_key_takes_precedence_over_channel(
    cursor_helpers, tmp_path
):
    """When both consumer_key and channel are supplied, consumer_key wins.

    Mirrors the precedence rule used by poll_other_channels and poll_haven."""
    advance = cursor_helpers["_advance_cursor_on_startup"]

    # File starts empty.
    advanced_key = advance(
        consumer_key="terminal:abc12345",
        channel="terminal",
        max_id=500,
    )

    state = json.loads((tmp_path / "channel_last_seen.json").read_text())
    assert state == {"terminal:abc12345": 500}, (
        "consumer_key (specific) should be the key that gets written, not "
        "the more-generic channel name"
    )
    assert advanced_key == "terminal:abc12345"


def test_startup_advance_falls_back_to_channel_when_no_consumer_key(
    cursor_helpers, tmp_path
):
    """Backward compatibility: callers that don't pass consumer_key still get
    a per-channel cursor (matches the pre-#176 behavior)."""
    advance = cursor_helpers["_advance_cursor_on_startup"]

    advanced_key = advance(
        consumer_key=None,
        channel="discord",
        max_id=42,
    )

    state = json.loads((tmp_path / "channel_last_seen.json").read_text())
    assert state == {"discord": 42}
    assert advanced_key == "discord"


def test_startup_advance_falls_back_to_default_when_neither_supplied(
    cursor_helpers, tmp_path
):
    """If neither consumer_key nor channel is provided, the cursor lands
    under '_default' — same fallback used by poll_other_channels."""
    advance = cursor_helpers["_advance_cursor_on_startup"]

    advanced_key = advance(consumer_key=None, channel=None, max_id=7)

    state = json.loads((tmp_path / "channel_last_seen.json").read_text())
    assert state == {"_default": 7}
    assert advanced_key == "_default"


def test_startup_advance_preserves_unrelated_consumers(cursor_helpers, tmp_path):
    """Realistic mixed-consumer scenario: terminal session, haven-bot, and a
    discord daemon all coexist. A startup from any one of them must leave
    the other two's cursors alone."""
    advance = cursor_helpers["_advance_cursor_on_startup"]

    initial = {
        "terminal:lyra-terminal-aaaa": 10,
        "terminal:haven-bot-bbbb": 20,
        "discord:reflect-daemon": 30,
        "haven": 40,  # legacy keyed-by-channel cursor
    }
    (tmp_path / "channel_last_seen.json").write_text(json.dumps(initial))

    # Haven-bot startup.
    advance(
        consumer_key="terminal:haven-bot-bbbb",
        channel="terminal",
        max_id=500,
    )

    state = json.loads((tmp_path / "channel_last_seen.json").read_text())
    assert state["terminal:lyra-terminal-aaaa"] == 10, "terminal session untouched"
    assert state["discord:reflect-daemon"] == 30, "discord daemon untouched"
    assert state["haven"] == 40, "legacy haven cursor untouched"
    assert state["terminal:haven-bot-bbbb"] == 500, "haven-bot advanced"


def test_startup_advance_creates_cursor_file_if_missing(cursor_helpers, tmp_path):
    """First-ever startup on a fresh entity (no cursor file yet) should
    create the file with just the requesting consumer's cursor."""
    advance = cursor_helpers["_advance_cursor_on_startup"]

    # No file pre-existing.
    assert not (tmp_path / "channel_last_seen.json").exists()

    advance(
        consumer_key="terminal:fresh-session",
        channel="terminal",
        max_id=1234,
    )

    state = json.loads((tmp_path / "channel_last_seen.json").read_text())
    assert state == {"terminal:fresh-session": 1234}
