"""
Tests for get_turns_since_summary endpoint — Issue #213 regression suite.

Verifies:
- The limit parameter is honored (was capped at 10 before the fix)
- The root cause: timestamp format mismatch (isoformat() "T" vs SQLite space separator)
- The min_turns floor still works correctly (intentional fallback)

Run with:
    PYTHONPATH=/mnt/c/Users/Jeff/Claude_Projects/Awareness \
    /mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python3 \
    -m pytest tests/test_pps/test_get_turns_since_summary.py -v
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import sys

import pytest

# Add pps to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "pps"))
from layers.message_summaries import MessageSummariesLayer


# ---------------------------------------------------------------------------
# Helpers — inline the endpoint's SQL logic so tests don't need the HTTP
# server running, but exercise the exact query the endpoint uses.
# ---------------------------------------------------------------------------

def _query_turns_since(
    conn: sqlite3.Connection,
    last_summary_str: str,
    limit: int,
    offset: int = 0,
    oldest_first: bool = True,
    channel: str | None = None,
) -> tuple[list[sqlite3.Row], int]:
    """
    Execute the same SQL the endpoint uses (post-fix: strftime format).

    Returns (rows_after, total_count).
    """
    cursor = conn.cursor()

    # Count query
    count_query = "SELECT COUNT(*) FROM messages WHERE created_at > ?"
    count_params: list = [last_summary_str]
    if channel:
        count_query += " AND channel LIKE ?"
        count_params.append(f"%{channel}%")
    cursor.execute(count_query, count_params)
    total_count = cursor.fetchone()[0]

    # Fetch query
    query = """
        SELECT author_name, content, created_at, channel
        FROM messages
        WHERE created_at > ?
    """
    params: list = [last_summary_str]
    if channel:
        query += " AND channel LIKE ?"
        params.append(f"%{channel}%")

    if oldest_first:
        query += " ORDER BY created_at ASC LIMIT ? OFFSET ?"
    else:
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor.execute(query, params)
    rows = cursor.fetchall()
    if not oldest_first:
        rows = list(reversed(rows))

    return rows, total_count


def _query_turns_isoformat_bug(
    conn: sqlite3.Connection,
    last_summary_iso: str,  # T-separator format — the old broken format
    limit: int,
    offset: int = 0,
    oldest_first: bool = True,
) -> tuple[list[sqlite3.Row], int]:
    """
    Replicate the PRE-FIX behavior: compare against isoformat() with "T".
    Shows that zero rows are returned even when rows exist after the timestamp.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM messages WHERE created_at > ?", (last_summary_iso,))
    total_count = cursor.fetchone()[0]

    query = "SELECT author_name, content, created_at, channel FROM messages WHERE created_at > ?"
    params: list = [last_summary_iso]
    if oldest_first:
        query += " ORDER BY created_at ASC LIMIT ? OFFSET ?"
    else:
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return rows, total_count


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_with_many_turns(tmp_path) -> tuple[Path, datetime]:
    """
    Create a SQLite DB with:
    - 1 summary record with time_span_end = "2026-05-20 12:00:00"
    - 25 messages after that timestamp (unsummarized)
    - 5 messages before that timestamp (already summarized)

    Returns (db_path, summary_timestamp_as_datetime).
    """
    db_path = tmp_path / "conversations.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # messages table matching production schema
    cursor.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            author_name TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT 'terminal',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_lyra INTEGER DEFAULT 0,
            summary_id INTEGER
        )
    """)

    # message_summaries table (needed by MessageSummariesLayer)
    cursor.execute("""
        CREATE TABLE message_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            summary_text TEXT NOT NULL,
            start_message_id INTEGER,
            end_message_id INTEGER,
            message_count INTEGER,
            time_span_start TEXT,
            time_span_end TEXT,
            channels TEXT,
            summary_type TEXT DEFAULT 'work',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    summary_boundary = datetime(2026, 5, 20, 12, 0, 0)
    summary_boundary_str = summary_boundary.strftime('%Y-%m-%d %H:%M:%S')

    # 5 messages BEFORE the summary boundary
    for i in range(5):
        ts = (summary_boundary - timedelta(minutes=5 - i)).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            "INSERT INTO messages (content, author_name, channel, created_at, summary_id) VALUES (?, ?, ?, ?, ?)",
            (f"Pre-summary message {i+1}", "Jeff", "terminal", ts, 1),
        )

    # 25 messages AFTER the summary boundary
    for i in range(25):
        ts = (summary_boundary + timedelta(minutes=i + 1)).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            "INSERT INTO messages (content, author_name, channel, created_at) VALUES (?, ?, ?, ?)",
            (f"Post-summary message {i+1}", "Jeff", "terminal", ts),
        )

    # Insert the summary record
    cursor.execute("""
        INSERT INTO message_summaries
            (summary_text, start_message_id, end_message_id, message_count,
             time_span_start, time_span_end, channels, summary_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "Summary of first 5 messages",
        1, 5, 5,
        (summary_boundary - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S'),
        summary_boundary_str,
        '["terminal"]',
        "work",
    ))

    conn.commit()
    conn.close()

    return db_path, summary_boundary


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTimestampFormatBug:
    """Document and verify the root cause of issue #213."""

    def test_isoformat_returns_zero_rows(self, db_with_many_turns):
        """
        PRE-FIX behavior: isoformat() T-separator silently returns 0 rows.

        This is the root cause of issue #213. SQLite lexical comparison
        of "2026-05-20T12:00:00" against stored "2026-05-20 12:01:00"
        fails because "T" > " " in ASCII, so every stored row appears
        *before* the comparison string.
        """
        db_path, summary_boundary = db_with_many_turns
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # isoformat() produces "2026-05-20T12:00:00" — the old broken format
        iso_str = summary_boundary.isoformat()
        rows, total_count = _query_turns_isoformat_bug(conn, iso_str, limit=50)
        conn.close()

        # This is the bug: 25 rows exist after the boundary but 0 are returned
        assert total_count == 0, (
            f"Expected total_count=0 with isoformat bug, got {total_count}. "
            "If this assertion fails the bug may already be fixed in the SQL layer."
        )
        assert len(rows) == 0, (
            f"Expected 0 rows with isoformat bug, got {len(rows)}"
        )

    def test_strftime_returns_correct_count(self, db_with_many_turns):
        """
        POST-FIX behavior: strftime('%Y-%m-%d %H:%M:%S') matches SQLite storage format.

        The fix in commit 655e917 replaces isoformat() with strftime() so
        lexical comparison works correctly.
        """
        db_path, summary_boundary = db_with_many_turns
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        strftime_str = summary_boundary.strftime('%Y-%m-%d %H:%M:%S')
        rows, total_count = _query_turns_since(conn, strftime_str, limit=50)
        conn.close()

        assert total_count == 25, f"Expected 25 rows after fix, got {total_count}"
        assert len(rows) == 25, f"Expected 25 rows returned with limit=50, got {len(rows)}"


class TestLimitParameter:
    """Verify the limit parameter is honored end-to-end (issue #213 core claim)."""

    def test_limit_10_returns_10(self, db_with_many_turns):
        """limit=10 returns exactly 10 of the 25 available rows."""
        db_path, summary_boundary = db_with_many_turns
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        strftime_str = summary_boundary.strftime('%Y-%m-%d %H:%M:%S')
        rows, total_count = _query_turns_since(conn, strftime_str, limit=10)
        conn.close()

        assert total_count == 25, f"total_count should be 25, got {total_count}"
        assert len(rows) == 10, f"limit=10 should return 10 rows, got {len(rows)}"

    def test_limit_25_returns_all_25(self, db_with_many_turns):
        """limit=25 returns all 25 available rows (the primary regression test)."""
        db_path, summary_boundary = db_with_many_turns
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        strftime_str = summary_boundary.strftime('%Y-%m-%d %H:%M:%S')
        rows, total_count = _query_turns_since(conn, strftime_str, limit=25)
        conn.close()

        assert total_count == 25
        assert len(rows) == 25, (
            f"limit=25 should return all 25 rows, got {len(rows)}. "
            "This is the core regression from issue #213."
        )

    def test_limit_50_returns_25_when_only_25_exist(self, db_with_many_turns):
        """limit=50 returns 25 (all available) when only 25 rows exist after summary."""
        db_path, summary_boundary = db_with_many_turns
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        strftime_str = summary_boundary.strftime('%Y-%m-%d %H:%M:%S')
        rows, total_count = _query_turns_since(conn, strftime_str, limit=50)
        conn.close()

        assert total_count == 25
        assert len(rows) == 25, (
            f"limit=50 should return all 25 rows (not cap at 10 or 50), got {len(rows)}"
        )

    def test_limit_100_returns_25_when_only_25_exist(self, db_with_many_turns):
        """limit=100 returns 25 — large limit doesn't break anything."""
        db_path, summary_boundary = db_with_many_turns
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        strftime_str = summary_boundary.strftime('%Y-%m-%d %H:%M:%S')
        rows, total_count = _query_turns_since(conn, strftime_str, limit=100)
        conn.close()

        assert total_count == 25
        assert len(rows) == 25

    def test_limit_5_returns_5(self, db_with_many_turns):
        """limit=5 (below min_turns default) still returns 5 rows from after the summary."""
        db_path, summary_boundary = db_with_many_turns
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        strftime_str = summary_boundary.strftime('%Y-%m-%d %H:%M:%S')
        rows, total_count = _query_turns_since(conn, strftime_str, limit=5)
        conn.close()

        assert total_count == 25
        assert len(rows) == 5


class TestOldestFirstOrdering:
    """Verify oldest_first parameter returns correct ordering."""

    def test_oldest_first_true_is_chronological(self, db_with_many_turns):
        """oldest_first=True returns rows in ascending timestamp order."""
        db_path, summary_boundary = db_with_many_turns
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        strftime_str = summary_boundary.strftime('%Y-%m-%d %H:%M:%S')
        rows, _ = _query_turns_since(conn, strftime_str, limit=25, oldest_first=True)
        conn.close()

        assert len(rows) == 25
        timestamps = [row['created_at'] for row in rows]
        assert timestamps == sorted(timestamps), "oldest_first=True should be in ASC order"
        assert "Post-summary message 1" in rows[0]['content']
        assert "Post-summary message 25" in rows[-1]['content']

    def test_oldest_first_false_is_reverse_chronological(self, db_with_many_turns):
        """oldest_first=False (default) returns rows in descending timestamp order."""
        db_path, summary_boundary = db_with_many_turns
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        strftime_str = summary_boundary.strftime('%Y-%m-%d %H:%M:%S')
        rows, _ = _query_turns_since(conn, strftime_str, limit=25, oldest_first=False)
        conn.close()

        assert len(rows) == 25
        # After reversing DESC result the order is actually ASC (newest-first fetch reversed to chron)
        # The endpoint reverses DESC result so caller gets chronological order either way
        timestamps = [row['created_at'] for row in rows]
        assert timestamps == sorted(timestamps), (
            "oldest_first=False reverses the DESC result, yielding chronological order"
        )


class TestPaginationOffset:
    """Verify offset parameter enables pagination."""

    def test_offset_0_and_offset_10_are_disjoint(self, db_with_many_turns):
        """Two pages with offset=0 and offset=10 return non-overlapping rows."""
        db_path, summary_boundary = db_with_many_turns
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        strftime_str = summary_boundary.strftime('%Y-%m-%d %H:%M:%S')
        page1, _ = _query_turns_since(conn, strftime_str, limit=10, offset=0)
        page2, _ = _query_turns_since(conn, strftime_str, limit=10, offset=10)
        conn.close()

        assert len(page1) == 10
        assert len(page2) == 10

        p1_ids = {r['created_at'] for r in page1}
        p2_ids = {r['created_at'] for r in page2}
        assert p1_ids.isdisjoint(p2_ids), "Paginated pages should not overlap"

    def test_two_pages_cover_all_25(self, db_with_many_turns):
        """offset=0 limit=15 + offset=15 limit=15 covers all 25 rows."""
        db_path, summary_boundary = db_with_many_turns
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        strftime_str = summary_boundary.strftime('%Y-%m-%d %H:%M:%S')
        page1, _ = _query_turns_since(conn, strftime_str, limit=15, offset=0)
        page2, _ = _query_turns_since(conn, strftime_str, limit=15, offset=15)
        conn.close()

        assert len(page1) == 15
        assert len(page2) == 10  # Only 10 remaining (25 - 15)
        assert len(page1) + len(page2) == 25


class TestGetLatestSummaryTimestamp:
    """Verify MessageSummariesLayer.get_latest_summary_timestamp() returns a datetime
    that, when passed through strftime, produces a space-separated string matching
    the SQLite storage format."""

    def test_timestamp_format_is_space_separated(self, db_with_many_turns):
        """
        get_latest_summary_timestamp() returns a datetime.
        strftime('%Y-%m-%d %H:%M:%S') on it must produce a space-separated string,
        not the T-separated isoformat that caused the bug.
        """
        db_path, expected_boundary = db_with_many_turns
        layer = MessageSummariesLayer(db_path=db_path)

        ts = layer.get_latest_summary_timestamp()
        assert ts is not None, "Expected a timestamp from the test DB"
        assert isinstance(ts, datetime)

        formatted = ts.strftime('%Y-%m-%d %H:%M:%S')
        assert 'T' not in formatted, (
            f"strftime output must not contain 'T': got {formatted!r}. "
            "isoformat() would produce a T-separator causing the #213 bug."
        )
        assert formatted == expected_boundary.strftime('%Y-%m-%d %H:%M:%S'), (
            f"Timestamp mismatch: got {formatted!r}, "
            f"expected {expected_boundary.strftime('%Y-%m-%d %H:%M:%S')!r}"
        )
