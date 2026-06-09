#!/usr/bin/env python3
"""
Tests for per-message read/responded state tracking (Issue #62).

Run with:
  /mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python3 \
      -m pytest tools/test_email_state.py -v
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — allow plain imports from adjacent directories
# ---------------------------------------------------------------------------
_TOOLS_DIR = Path(__file__).parent
_GMAIL_MCP_DIR = _TOOLS_DIR / "gmail-mcp"

sys.path.insert(0, str(_TOOLS_DIR))
sys.path.insert(0, str(_GMAIL_MCP_DIR))

from email_processor import EmailProcessor

# Import server.py under an alias to avoid shadowing the MCP Server instance
# that the module itself stores in a variable also named `server`.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("gmail_mcp_server", _GMAIL_MCP_DIR / "server.py")
gmail_mcp = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(gmail_mcp)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Isolated SQLite database path for each test."""
    return tmp_path / "email_archive.db"


@pytest.fixture
def processor(db_path: Path) -> EmailProcessor:
    """EmailProcessor with the Gmail API service mocked out."""
    with patch.object(EmailProcessor, "_get_service", return_value=MagicMock()):
        ep = EmailProcessor(
            token_path=db_path.parent / "fake_token.json",
            db_path=db_path,
        )
    return ep


# ---------------------------------------------------------------------------
# 1. mark_read sets read_at
# ---------------------------------------------------------------------------

def test_mark_read_records_timestamp(processor: EmailProcessor) -> None:
    """mark_read should persist a non-null ISO8601 read_at timestamp."""
    msg_id = "18f3a2c9b47e1d01"
    processor.mark_read(msg_id, "test@example.com")

    conn = sqlite3.connect(processor.db_path)
    row = conn.execute(
        "SELECT read_at FROM email_state WHERE message_id = ?", (msg_id,)
    ).fetchone()
    conn.close()

    assert row is not None, "Row should exist after mark_read"
    assert row[0] is not None, "read_at should not be NULL"
    assert len(row[0]) > 0, "read_at should be a non-empty string"


# ---------------------------------------------------------------------------
# 2. mark_responded sets responded_at
# ---------------------------------------------------------------------------

def test_mark_responded_records_timestamp(processor: EmailProcessor) -> None:
    """mark_responded should persist a non-null ISO8601 responded_at timestamp."""
    msg_id = "18f3a2c9b47e1d02"
    processor.mark_responded(msg_id, "test@example.com")

    conn = sqlite3.connect(processor.db_path)
    row = conn.execute(
        "SELECT responded_at FROM email_state WHERE message_id = ?", (msg_id,)
    ).fetchone()
    conn.close()

    assert row is not None, "Row should exist after mark_responded"
    assert row[0] is not None, "responded_at should not be NULL"


# ---------------------------------------------------------------------------
# 3. is_responded returns False before any mark
# ---------------------------------------------------------------------------

def test_is_responded_false_before_mark(processor: EmailProcessor) -> None:
    """is_responded returns False for a message_id that has never been marked."""
    assert processor.is_responded("18f3a2c9b47e1d03") is False


# ---------------------------------------------------------------------------
# 4. is_responded returns True after mark_responded
# ---------------------------------------------------------------------------

def test_is_responded_true_after_mark(processor: EmailProcessor) -> None:
    """is_responded transitions from False to True after mark_responded."""
    msg_id = "18f3a2c9b47e1d04"
    assert processor.is_responded(msg_id) is False
    processor.mark_responded(msg_id, "test@example.com")
    assert processor.is_responded(msg_id) is True


# ---------------------------------------------------------------------------
# 5. Duplicate send is blocked via _send_message guard
# ---------------------------------------------------------------------------

def test_duplicate_send_blocked(tmp_path: Path) -> None:
    """Second call to _send_message with the same in_reply_to_id should be blocked."""
    msg_id = "18f3a2c9b47e1d06"
    db_path = tmp_path / "email_archive.db"

    mock_service = MagicMock()
    mock_service.users().messages().send().execute.return_value = {"id": "sent_aaa"}

    args = {
        "to": "someone@example.com",
        "subject": "Re: Test",
        "body": "Hello",
        "in_reply_to_id": msg_id,
    }

    with patch.object(gmail_mcp, "_get_email_state_db", return_value=db_path):
        # First send — succeeds and marks responded
        result1 = asyncio.run(gmail_mcp._send_message(mock_service, dict(args)))
        assert "sent_aaa" in result1[0].text, "First send should succeed"

        # Second send — should be blocked
        result2 = asyncio.run(gmail_mcp._send_message(mock_service, dict(args)))
        assert "Duplicate send blocked" in result2[0].text, (
            "Second send should be blocked with an explanatory message"
        )
        assert msg_id in result2[0].text, "Blocked message should include the message_id"


# ---------------------------------------------------------------------------
# 6. force=True bypasses the duplicate-send guard
# ---------------------------------------------------------------------------

def test_force_override_sends(tmp_path: Path) -> None:
    """force=True allows a send even when the message was already responded to."""
    msg_id = "18f3a2c9b47e1d07"
    db_path = tmp_path / "email_archive.db"

    mock_service = MagicMock()
    mock_service.users().messages().send().execute.return_value = {"id": "sent_bbb"}

    with patch.object(gmail_mcp, "_get_email_state_db", return_value=db_path):
        # Pre-mark as responded
        gmail_mcp._mark_responded_in_db(msg_id)
        assert gmail_mcp._check_responded(msg_id) is True

        # Send with force=True — should succeed despite prior responded state
        args = {
            "to": "someone@example.com",
            "subject": "Re: Test again",
            "body": "Forced reply",
            "in_reply_to_id": msg_id,
            "force": True,
        }
        result = asyncio.run(gmail_mcp._send_message(mock_service, args))

    assert "Duplicate send blocked" not in result[0].text
    assert "sent_bbb" in result[0].text


# ---------------------------------------------------------------------------
# 7. State persists across DB close/re-open (restart simulation)
# ---------------------------------------------------------------------------

def test_restart_persistence(db_path: Path) -> None:
    """State written by one EmailProcessor instance should survive in a new instance."""
    msg_id = "18f3a2c9b47e1d05"

    # First instance — write both read_at and responded_at
    with patch.object(EmailProcessor, "_get_service", return_value=MagicMock()):
        ep1 = EmailProcessor(
            token_path=db_path.parent / "fake_token.json",
            db_path=db_path,
        )
    ep1.mark_read(msg_id, "lyra.pattern@gmail.com")
    ep1.mark_responded(msg_id, "lyra.pattern@gmail.com")

    # Second instance — verify state is still present
    with patch.object(EmailProcessor, "_get_service", return_value=MagicMock()):
        ep2 = EmailProcessor(
            token_path=db_path.parent / "fake_token.json",
            db_path=db_path,
        )

    assert ep2.is_responded(msg_id) is True

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT read_at, responded_at FROM email_state WHERE message_id = ?",
        (msg_id,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] is not None, "read_at should survive restart"
    assert row[1] is not None, "responded_at should survive restart"


# ---------------------------------------------------------------------------
# 8. Works correctly with a realistic Gmail-shaped message ID
# ---------------------------------------------------------------------------

def test_realistic_message_id_shape(processor: EmailProcessor) -> None:
    """State tracking works with a real Gmail message ID (16-char hex string)."""
    # Gmail IDs are hex, typically 16 characters
    gmail_id = "18f3a2c9b47e1d05"

    assert processor.is_responded(gmail_id) is False

    processor.mark_read(gmail_id, "lyra.pattern@gmail.com")
    processor.mark_responded(gmail_id, "lyra.pattern@gmail.com")

    assert processor.is_responded(gmail_id) is True

    # Verify both columns written cleanly
    conn = sqlite3.connect(processor.db_path)
    row = conn.execute(
        "SELECT message_id, account, read_at, responded_at FROM email_state "
        "WHERE message_id = ?",
        (gmail_id,),
    ).fetchone()
    conn.close()

    assert row[0] == gmail_id
    assert row[1] == "lyra.pattern@gmail.com"
    assert row[2] is not None
    assert row[3] is not None
