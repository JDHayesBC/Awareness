"""pps_health must see a store that is losing memory (#334).

Deleting a row from `message_summaries` does not clear `messages.summary_id`. There
is no enforced foreign key (`PRAGMA foreign_keys` is 0) and no ON DELETE SET NULL,
and the summarizer selects work with `WHERE summary_id IS NULL` — so orphaned
messages count as summarized forever and drop out of long-term memory with no error.

The layer stays perfectly *available* throughout. That is the point: on 2026-09-15 a
real cleanup reported "deleted, zero bad rows, all four layers green" and the store
was still broken. Availability could not see it, so integrity is now checked
separately and reported on its own axis.

These tests induce the damage rather than asserting that a clean store looks clean —
a health check that has never been shown the failure is the green light this exists
to replace.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pps"))
from layers.message_summaries import MessageSummariesLayer  # noqa: E402


def _store(tmp_path: Path) -> Path:
    db = tmp_path / "conversations.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL DEFAULT 'terminal',
            author_name TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            summary_id INTEGER
        );
        CREATE TABLE message_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            summary_text TEXT NOT NULL,
            start_message_id INTEGER NOT NULL,
            end_message_id INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    for i in range(1, 11):
        conn.execute("INSERT INTO messages (author_name, content) VALUES (?, ?)", ("caia", f"turn {i}"))
    conn.execute(
        "INSERT INTO message_summaries (summary_text, start_message_id, end_message_id) VALUES (?,?,?)",
        ("### Executive Summary\nreal summary text", 1, 8),
    )
    conn.execute("UPDATE messages SET summary_id = 1 WHERE id BETWEEN 1 AND 8")
    conn.commit()
    conn.close()
    return db


@pytest.mark.asyncio
async def test_clean_store_reports_integrity_ok(tmp_path):
    health = await MessageSummariesLayer(db_path=_store(tmp_path)).health()
    assert health.available is True
    assert health.details["integrity_ok"] is True
    assert health.details["orphaned_messages"] == 0
    assert health.details["backlog_by_null_summary_id"] == health.details["backlog_by_max_end_message_id"] == 2


@pytest.mark.asyncio
async def test_deleting_a_summary_is_caught_as_integrity_failure(tmp_path):
    """The exact 2026-09-15 near-miss: delete the row, leave the pointers."""
    db = _store(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM message_summaries WHERE id = 1")
    conn.commit()
    conn.close()

    health = await MessageSummariesLayer(db_path=db).health()

    # The layer is fine. The store is not. That distinction is the whole fix.
    assert health.available is True
    assert health.details["integrity_ok"] is False
    assert health.details["orphaned_messages"] == 8
    # backlog disagreement: 2 by summary_id, 10 by arithmetic
    assert health.details["backlog_by_null_summary_id"] == 2
    assert health.details["backlog_by_max_end_message_id"] == 10
    assert "INTEGRITY FAILURE" in health.message
    assert "8 messages" in health.message


@pytest.mark.asyncio
async def test_releasing_the_pointers_restores_integrity(tmp_path):
    db = _store(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM message_summaries WHERE id = 1")
    conn.execute(
        "UPDATE messages SET summary_id = NULL WHERE summary_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM message_summaries s WHERE s.id = messages.summary_id)"
    )
    conn.commit()
    conn.close()

    health = await MessageSummariesLayer(db_path=db).health()
    assert health.details["integrity_ok"] is True
    assert health.details["orphaned_messages"] == 0
    # all ten are now visible to the summarizer again — nothing lost
    assert health.details["backlog_by_null_summary_id"] == 10
    assert "INTEGRITY FAILURE" not in health.message
