"""
Tests for MessageSummariesLayer.

Tests the message summarization layer including:
- Summary storage and retrieval
- The shared _insert_summary_with_cursor helper
- Connection context manager behavior
- Unsummarized message counting and retrieval

Run with: pytest tests/test_pps/test_message_summaries.py -v
"""

import pytest
import sqlite3
import sys
from pathlib import Path

# Add pps to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "pps"))

from layers.message_summaries import MessageSummariesLayer


class TestMessageSummariesLayerInit:
    """Test MessageSummariesLayer initialization."""

    def test_init_creates_tables(self, test_db_with_messages):
        """Verify initialization creates message_summaries table."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)

        with layer.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='message_summaries'")
            assert cursor.fetchone() is not None

    def test_init_adds_summary_id_column(self, test_db_with_messages):
        """Verify initialization adds summary_id column to messages table."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)

        with layer.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(messages)")
            columns = [col[1] for col in cursor.fetchall()]
            assert 'summary_id' in columns


class TestConnectionContextManager:
    """Test the get_connection context manager."""

    def test_connection_closes_on_normal_exit(self, test_db_with_messages):
        """Verify connection is closed after context manager exits normally."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)

        with layer.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            assert cursor.fetchone()[0] == 1

        # After exiting, connection should be closed
        # Attempting to use it should fail
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_connection_closes_on_exception(self, test_db_with_messages):
        """Verify connection is closed even if exception occurs."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)
        captured_conn = None

        with pytest.raises(ValueError):
            with layer.get_connection() as conn:
                captured_conn = conn
                raise ValueError("Test exception")

        # Connection should still be closed
        with pytest.raises(sqlite3.ProgrammingError):
            captured_conn.execute("SELECT 1")


class TestInsertSummaryWithCursor:
    """Test the _insert_summary_with_cursor helper method."""

    def test_insert_summary_success(self, test_db_with_messages):
        """Verify helper inserts summary and updates messages."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)

        with layer.get_connection() as conn:
            cursor = conn.cursor()

            summary_id = layer._insert_summary_with_cursor(
                cursor=cursor,
                summary_text="Test summary of messages 1-3",
                start_id=1,
                end_id=3,
                channels=["terminal", "discord"],
                summary_type="work"
            )

            assert summary_id is not None
            assert summary_id > 0

            # Verify summary was inserted
            cursor.execute("SELECT * FROM message_summaries WHERE id = ?", (summary_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row['summary_text'] == "Test summary of messages 1-3"
            assert row['start_message_id'] == 1
            assert row['end_message_id'] == 3
            assert row['message_count'] == 3

            # Verify messages were updated
            cursor.execute("SELECT summary_id FROM messages WHERE id BETWEEN 1 AND 3")
            for row in cursor.fetchall():
                assert row['summary_id'] == summary_id

    def test_insert_summary_invalid_range(self, test_db_with_messages):
        """Verify helper returns None for invalid message range."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)

        with layer.get_connection() as conn:
            cursor = conn.cursor()

            # Message IDs 100 and 200 don't exist
            summary_id = layer._insert_summary_with_cursor(
                cursor=cursor,
                summary_text="This should fail",
                start_id=100,
                end_id=200,
                channels=["terminal"],
                summary_type="work"
            )

            assert summary_id is None


class TestStoreMethod:
    """Test the async store method."""

    @pytest.mark.asyncio
    async def test_store_with_valid_metadata(self, test_db_with_messages):
        """Verify store() works with valid metadata."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)

        result = await layer.store(
            content="Summary via store method",
            metadata={
                'start_message_id': 1,
                'end_message_id': 2,
                'channels': ['terminal'],
                'summary_type': 'work'
            }
        )

        assert result is True

        # Verify it was stored
        with layer.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM message_summaries WHERE summary_text = ?",
                          ("Summary via store method",))
            row = cursor.fetchone()
            assert row is not None

    @pytest.mark.asyncio
    async def test_store_without_metadata_fails(self, test_db_with_messages):
        """Verify store() returns False without metadata."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)

        result = await layer.store(content="No metadata")
        assert result is False


class TestCreateAndStoreSummary:
    """Test the async create_and_store_summary method."""

    @pytest.mark.asyncio
    async def test_create_and_store_success(self, test_db_with_messages):
        """Verify create_and_store_summary works with valid params."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)

        result = await layer.create_and_store_summary(
            summary_text="Summary via create_and_store",
            start_id=2,
            end_id=4,
            channels=["terminal", "discord"],
            summary_type="technical"
        )

        assert result is True

        # Verify it was stored
        with layer.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM message_summaries WHERE summary_text = ?",
                          ("Summary via create_and_store",))
            row = cursor.fetchone()
            assert row is not None
            assert row['summary_type'] == 'technical'


class TestUnsummarizedMessages:
    """Test unsummarized message counting and retrieval."""

    def test_count_unsummarized_messages(self, test_db_with_messages):
        """Verify count_unsummarized_messages returns correct count."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)

        # All 5 messages should be unsummarized initially
        count = layer.count_unsummarized_messages()
        assert count == 5

    def test_get_unsummarized_messages(self, test_db_with_messages):
        """Verify get_unsummarized_messages returns correct messages."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)

        messages = layer.get_unsummarized_messages(limit=10)

        assert len(messages) == 5
        assert messages[0]['content'] == "Hello, this is message 1"
        assert messages[0]['author_name'] == "Jeff"

    @pytest.mark.asyncio
    async def test_count_decreases_after_summarization(self, test_db_with_messages):
        """Verify unsummarized count decreases after creating summary."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)

        # Initially 5 unsummarized
        assert layer.count_unsummarized_messages() == 5

        # Summarize messages 1-3
        await layer.create_and_store_summary(
            summary_text="Summary of first 3",
            start_id=1,
            end_id=3,
            channels=["terminal"],
            summary_type="work"
        )

        # Now should be 2 unsummarized (messages 4 and 5)
        assert layer.count_unsummarized_messages() == 2


class TestRecentSummaries:
    """Test recent summaries retrieval."""

    @pytest.mark.asyncio
    async def test_get_recent_summaries(self, test_db_with_messages):
        """Verify get_recent_summaries returns summaries in order."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)

        # Create two summaries
        await layer.create_and_store_summary(
            summary_text="First summary",
            start_id=1,
            end_id=2,
            channels=["terminal"],
            summary_type="work"
        )

        await layer.create_and_store_summary(
            summary_text="Second summary",
            start_id=3,
            end_id=4,
            channels=["discord"],
            summary_type="social"
        )

        summaries = layer.get_recent_summaries(limit=5)

        assert len(summaries) == 2
        # Most recent first
        assert summaries[0]['summary_text'] == "Second summary"
        assert summaries[1]['summary_text'] == "First summary"


class TestSearchSummaries:
    """Test summary search functionality."""

    @pytest.mark.asyncio
    async def test_search_finds_matching_summaries(self, test_db_with_messages):
        """Verify search finds summaries containing query."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)

        # Create summaries with different content
        await layer.create_and_store_summary(
            summary_text="Fixed the authentication bug in login flow",
            start_id=1,
            end_id=2,
            channels=["terminal"],
            summary_type="work"
        )

        await layer.create_and_store_summary(
            summary_text="Added new dashboard feature with charts",
            start_id=3,
            end_id=4,
            channels=["terminal"],
            summary_type="work"
        )

        # Search for authentication
        results = await layer.search("authentication", limit=10)

        assert len(results) == 1
        assert "authentication" in results[0].content.lower()

    @pytest.mark.asyncio
    async def test_search_returns_empty_for_no_match(self, test_db_with_messages):
        """Verify search returns empty list when no matches."""
        layer = MessageSummariesLayer(db_path=test_db_with_messages)

        await layer.create_and_store_summary(
            summary_text="Some unrelated content",
            start_id=1,
            end_id=2,
            channels=["terminal"],
            summary_type="work"
        )

        results = await layer.search("xyznonexistent", limit=10)
        assert len(results) == 0
