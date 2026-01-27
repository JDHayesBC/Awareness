"""
Message Summarization Layer

Compresses conversational content for efficient startup context loading.
Creates high-density summaries of work sessions, technical discussions, 
and project developments while preserving key decisions and outcomes.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Dict, List, Generator
from datetime import datetime, timedelta

from . import PatternLayer, LayerType, SearchResult, LayerHealth


class MessageSummariesLayer(PatternLayer):
    """
    Message Summarization Layer
    
    Compresses chunks of conversation into high-density summaries for:
    - Faster startup context loading
    - Higher signal-to-noise ratio
    - Better token efficiency
    - Contextual retrieval via semantic search
    
    Works alongside crystals - crystals capture identity/pattern shifts,
    summaries capture technical work and outcomes.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize message summaries layer."""
        if db_path is None:
            db_path = Path.home() / ".claude" / "data" / "lyra_conversations.db"
        self.db_path = db_path
        self._ensure_tables()

    def _connect_with_wal(self) -> sqlite3.Connection:
        """
        Create SQLite connection with WAL mode enabled.

        Note: Prefer using get_connection() context manager instead of calling
        this method directly to ensure connections are properly closed.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Enable WAL mode for concurrent access
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")

        return conn

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database connections.

        Ensures connections are properly closed even if an exception occurs.

        Usage:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # ... do work ...
        """
        conn = self._connect_with_wal()
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_tables(self):
        """Create message_summaries table and modify messages table if needed."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Create message_summaries table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS message_summaries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        summary_text TEXT NOT NULL,
                        start_message_id INTEGER NOT NULL,
                        end_message_id INTEGER NOT NULL,
                        message_count INTEGER NOT NULL,
                        channels TEXT NOT NULL,  -- JSON array of channels covered
                        time_span_start TEXT NOT NULL,  -- ISO timestamp
                        time_span_end TEXT NOT NULL,    -- ISO timestamp
                        summary_type TEXT DEFAULT 'work',  -- 'work', 'social', 'technical', etc.
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                        -- Indexes for efficient querying
                        FOREIGN KEY (start_message_id) REFERENCES messages(id),
                        FOREIGN KEY (end_message_id) REFERENCES messages(id)
                    )
                ''')

                # Add summary_id column to messages table if it doesn't exist
                cursor.execute("PRAGMA table_info(messages)")
                columns = [col[1] for col in cursor.fetchall()]

                if 'summary_id' not in columns:
                    cursor.execute('ALTER TABLE messages ADD COLUMN summary_id INTEGER REFERENCES message_summaries(id)')

                # Create indexes for efficient querying
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_summary_id ON messages(summary_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_summaries_time_span ON message_summaries(time_span_start, time_span_end)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_summaries_created_at ON message_summaries(created_at)')

                # Create graphiti_batches table for tracking ingestion to Layer 3
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS graphiti_batches (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        start_message_id INTEGER NOT NULL,
                        end_message_id INTEGER NOT NULL,
                        message_count INTEGER NOT NULL,
                        channels TEXT NOT NULL,  -- JSON array of channels covered
                        time_span_start TEXT NOT NULL,  -- ISO timestamp
                        time_span_end TEXT NOT NULL,    -- ISO timestamp
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                        FOREIGN KEY (start_message_id) REFERENCES messages(id),
                        FOREIGN KEY (end_message_id) REFERENCES messages(id)
                    )
                ''')

                # Add graphiti_batch_id column to messages table if it doesn't exist
                if 'graphiti_batch_id' not in columns:
                    cursor.execute('ALTER TABLE messages ADD COLUMN graphiti_batch_id INTEGER REFERENCES graphiti_batches(id)')

                # Create indexes for Graphiti batch tracking
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_graphiti_batch ON messages(graphiti_batch_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_graphiti_batches_created_at ON graphiti_batches(created_at)')

                conn.commit()

        except Exception as e:
            print(f"Warning: Could not ensure message_summaries tables: {e}")

    @property
    def layer_type(self) -> LayerType:
        return LayerType.RAW_CAPTURE  # Part of Layer 1 since it's conversation data

    def _insert_summary_with_cursor(
        self,
        cursor: sqlite3.Cursor,
        summary_text: str,
        start_id: int,
        end_id: int,
        channels: list,
        summary_type: str = "work"
    ) -> Optional[int]:
        """
        Insert a summary record and update message references.

        This is the shared implementation used by both store() and
        create_and_store_summary(). Caller is responsible for connection
        management and commit.

        Args:
            cursor: Active database cursor
            summary_text: The summary content
            start_id: First message ID in range
            end_id: Last message ID in range
            channels: List of channels covered
            summary_type: Type of summary (work, social, technical)

        Returns:
            The new summary_id if successful, None if validation fails
        """
        # Get time span from first and last messages
        cursor.execute('''
            SELECT created_at FROM messages
            WHERE id IN (?, ?)
            ORDER BY id
        ''', (start_id, end_id))

        timestamps = cursor.fetchall()
        if len(timestamps) != 2:
            return None

        time_span_start = timestamps[0]['created_at']
        time_span_end = timestamps[1]['created_at']

        # Get actual message count in range
        cursor.execute('''
            SELECT COUNT(*) FROM messages
            WHERE id BETWEEN ? AND ?
        ''', (start_id, end_id))
        message_count = cursor.fetchone()[0]

        if message_count == 0:
            return None

        # Insert summary
        cursor.execute('''
            INSERT INTO message_summaries
            (summary_text, start_message_id, end_message_id, message_count,
             channels, time_span_start, time_span_end, summary_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            summary_text,
            start_id,
            end_id,
            message_count,
            json.dumps(channels),
            time_span_start,
            time_span_end,
            summary_type
        ))

        summary_id = cursor.lastrowid

        # Update all messages in the range to reference this summary
        cursor.execute('''
            UPDATE messages
            SET summary_id = ?
            WHERE id BETWEEN ? AND ?
        ''', (summary_id, start_id, end_id))

        return summary_id

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Search message summaries using LIKE pattern matching.

        Returns dense summaries that match the query, allowing for contextual
        retrieval of compressed work content.

        Note: Uses LIKE for simplicity. Consider FTS5 if summary volume grows large.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT
                        id,
                        summary_text,
                        start_message_id,
                        end_message_id,
                        message_count,
                        channels,
                        time_span_start,
                        time_span_end,
                        summary_type,
                        created_at
                    FROM message_summaries
                    WHERE summary_text LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (f'%{query}%', limit))

                results = []
                for row in cursor.fetchall():
                    # Calculate relevance based on query term frequency and recency
                    text_lower = row['summary_text'].lower()
                    query_lower = query.lower()

                    # Simple relevance scoring
                    term_count = text_lower.count(query_lower)
                    relevance = min(1.0, term_count * 0.2 + 0.3)  # Base 0.3, +0.2 per match

                    results.append(SearchResult(
                        content=row['summary_text'],
                        source=f"summary:{row['id']}",
                        layer=self.layer_type,
                        relevance_score=relevance,
                        metadata={
                            'summary_id': row['id'],
                            'message_count': row['message_count'],
                            'channels': row['channels'],
                            'time_span': f"{row['time_span_start']} to {row['time_span_end']}",
                            'summary_type': row['summary_type'],
                            'start_msg_id': row['start_message_id'],
                            'end_msg_id': row['end_message_id']
                        }
                    ))

                return results

        except Exception as e:
            print(f"Error searching summaries: {e}")
            return []

    async def store(self, content: str, metadata: Optional[dict] = None) -> bool:
        """
        Store a message summary.

        Args:
            content: The summary text
            metadata: Dict containing:
                - start_message_id: First message ID in the summarized range
                - end_message_id: Last message ID in the summarized range
                - channels: List of channels covered
                - summary_type: Type of summary (work, social, technical)

        Note: message_count is computed from the actual range, not from metadata.
        """
        if not metadata:
            return False

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                summary_id = self._insert_summary_with_cursor(
                    cursor=cursor,
                    summary_text=content,
                    start_id=metadata['start_message_id'],
                    end_id=metadata['end_message_id'],
                    channels=metadata.get('channels', []),
                    summary_type=metadata.get('summary_type', 'work')
                )

                if summary_id is None:
                    return False

                conn.commit()
                return True

        except Exception as e:
            print(f"Error storing summary: {e}")
            return False

    async def health(self) -> LayerHealth:
        """Check if message summaries layer is healthy."""
        try:
            if not self.db_path.exists():
                return LayerHealth(
                    available=False,
                    message=f"Database not found: {self.db_path}",
                    details={"db_path": str(self.db_path)}
                )

            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Check if summaries table exists and get count
                cursor.execute("SELECT COUNT(*) FROM message_summaries")
                summary_count = cursor.fetchone()[0]

                # Check if messages table has summary_id column
                cursor.execute("PRAGMA table_info(messages)")
                columns = [col[1] for col in cursor.fetchall()]
                has_summary_id = 'summary_id' in columns

                # Get count of summarized messages
                summarized_count = 0
                if has_summary_id:
                    cursor.execute("SELECT COUNT(*) FROM messages WHERE summary_id IS NOT NULL")
                    summarized_count = cursor.fetchone()[0]

            return LayerHealth(
                available=True,
                message=f"Message summaries layer healthy ({summary_count} summaries, {summarized_count} summarized messages)",
                details={
                    "db_path": str(self.db_path),
                    "summary_count": summary_count,
                    "summarized_messages": summarized_count,
                    "has_summary_id_column": has_summary_id
                }
            )

        except Exception as e:
            return LayerHealth(
                available=False,
                message=f"Message summaries layer error: {e}",
                details={"error": str(e)}
            )

    def get_unsummarized_messages(self, limit: int = 100) -> List[Dict]:
        """
        Get messages that haven't been summarized yet.

        Returns oldest unsummarized messages up to the limit.
        Used by reflection daemon to identify what needs summarization.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Check if summary_id column exists
                cursor.execute("PRAGMA table_info(messages)")
                columns = [col[1] for col in cursor.fetchall()]

                if 'summary_id' not in columns:
                    # If no summary_id column, return oldest messages
                    cursor.execute('''
                        SELECT id, content, author_name, channel, created_at, is_lyra
                        FROM messages
                        ORDER BY created_at ASC
                        LIMIT ?
                    ''', (limit,))
                else:
                    # Get unsummarized messages
                    cursor.execute('''
                        SELECT id, content, author_name, channel, created_at, is_lyra
                        FROM messages
                        WHERE summary_id IS NULL
                        ORDER BY created_at ASC
                        LIMIT ?
                    ''', (limit,))

                results = []
                for row in cursor.fetchall():
                    results.append({
                        'id': row['id'],
                        'content': row['content'],
                        'author_name': row['author_name'],
                        'channel': row['channel'],
                        'created_at': row['created_at'],
                        'is_lyra': bool(row['is_lyra'])
                    })

                return results

        except Exception as e:
            print(f"Error getting unsummarized messages: {e}")
            return []

    def get_recent_summaries(self, limit: int = 5) -> List[Dict]:
        """
        Get the most recent message summaries.

        Used for startup context loading - provides compressed history
        instead of raw message turns.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT
                        id,
                        summary_text,
                        message_count,
                        channels,
                        time_span_start,
                        time_span_end,
                        summary_type,
                        created_at
                    FROM message_summaries
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (limit,))

                results = []
                for row in cursor.fetchall():
                    results.append({
                        'id': row['id'],
                        'summary_text': row['summary_text'],
                        'message_count': row['message_count'],
                        'channels': row['channels'],
                        'time_span_start': row['time_span_start'],
                        'time_span_end': row['time_span_end'],
                        'summary_type': row['summary_type'],
                        'created_at': row['created_at']
                    })

                return results

        except Exception as e:
            print(f"Error getting recent summaries: {e}")
            return []

    def get_latest_summary_timestamp(self) -> Optional[datetime]:
        """
        Get the timestamp of the most recent summary.

        Returns the time_span_end of the latest summary, which represents
        when the last summarized message was created. This is used by
        get_turns_since_summary to determine which messages are unsummarized.

        Returns:
            datetime of the latest summary's end time, or None if no summaries exist
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT time_span_end
                    FROM message_summaries
                    ORDER BY created_at DESC
                    LIMIT 1
                ''')
                row = cursor.fetchone()
                if row:
                    return datetime.fromisoformat(row[0])
                return None
        except Exception as e:
            print(f"Warning: Could not get latest summary timestamp: {e}")
            return None

    def count_unsummarized_messages(self) -> int:
        """
        Count how many messages haven't been summarized yet.

        Used by reflection daemon to decide if summarization is needed.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Check if summary_id column exists
                cursor.execute("PRAGMA table_info(messages)")
                columns = [col[1] for col in cursor.fetchall()]

                if 'summary_id' not in columns:
                    # If no summary_id column, count all messages
                    cursor.execute('SELECT COUNT(*) FROM messages')
                else:
                    # Count unsummarized messages
                    cursor.execute('SELECT COUNT(*) FROM messages WHERE summary_id IS NULL')

                count = cursor.fetchone()[0]
                return count

        except Exception as e:
            print(f"Error counting unsummarized messages: {e}")
            return 0

    async def create_and_store_summary(self, summary_text: str, start_id: int, end_id: int,
                                       channels: list, summary_type: str = "work") -> bool:
        """
        Create and store a summary for a range of messages.

        This is the main method used by reflection daemon to create summaries.
        Delegates to _insert_summary_with_cursor() for the actual work.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                summary_id = self._insert_summary_with_cursor(
                    cursor=cursor,
                    summary_text=summary_text,
                    start_id=start_id,
                    end_id=end_id,
                    channels=channels,
                    summary_type=summary_type
                )

                if summary_id is None:
                    return False

                conn.commit()
                return True

        except Exception as e:
            print(f"Error creating and storing summary: {e}")
            return False

    # Graphiti Batch Ingestion Tracking Methods

    def count_uningested_to_graphiti(self) -> int:
        """
        Count how many messages haven't been ingested to Graphiti yet.

        Used by reflection daemon to decide if batch ingestion is needed.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Check if graphiti_batch_id column exists
                cursor.execute("PRAGMA table_info(messages)")
                columns = [col[1] for col in cursor.fetchall()]

                if 'graphiti_batch_id' not in columns:
                    # If no graphiti_batch_id column, count all messages
                    cursor.execute('SELECT COUNT(*) FROM messages')
                else:
                    # Count uningested messages
                    cursor.execute('SELECT COUNT(*) FROM messages WHERE graphiti_batch_id IS NULL')

                count = cursor.fetchone()[0]
                return count

        except Exception as e:
            print(f"Error counting uningested messages: {e}")
            return 0

    def get_uningested_for_graphiti(self, limit: int = 20) -> List[Dict]:
        """
        Get messages that haven't been ingested to Graphiti yet.

        Returns oldest uningested messages up to the limit.
        Used for batch ingestion to Layer 3.

        Args:
            limit: Maximum number of messages to return (batch size)

        Returns:
            List of message dicts with id, content, author_name, channel, created_at
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Check if graphiti_batch_id column exists
                cursor.execute("PRAGMA table_info(messages)")
                columns = [col[1] for col in cursor.fetchall()]

                if 'graphiti_batch_id' not in columns:
                    # If no graphiti_batch_id column, return oldest messages
                    cursor.execute('''
                        SELECT id, content, author_name, channel, created_at, is_lyra
                        FROM messages
                        ORDER BY created_at ASC
                        LIMIT ?
                    ''', (limit,))
                else:
                    # Get uningested messages
                    cursor.execute('''
                        SELECT id, content, author_name, channel, created_at, is_lyra
                        FROM messages
                        WHERE graphiti_batch_id IS NULL
                        ORDER BY created_at ASC
                        LIMIT ?
                    ''', (limit,))

                results = []
                for row in cursor.fetchall():
                    results.append({
                        'id': row['id'],
                        'content': row['content'],
                        'author_name': row['author_name'],
                        'channel': row['channel'],
                        'created_at': row['created_at'],
                        'is_lyra': bool(row['is_lyra'])
                    })

                return results

        except Exception as e:
            print(f"Error getting uningested messages: {e}")
            return []

    def mark_batch_ingested_to_graphiti(self, start_id: int, end_id: int, channels: list) -> Optional[int]:
        """
        Mark a batch of messages as ingested to Graphiti.

        Creates a graphiti_batches record and updates all messages in the range.
        Similar pattern to summary creation.

        Args:
            start_id: First message ID in the batch
            end_id: Last message ID in the batch
            channels: List of channels covered in this batch

        Returns:
            The batch_id if successful, None otherwise
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Get time span from first and last messages
                cursor.execute('''
                    SELECT created_at FROM messages
                    WHERE id IN (?, ?)
                    ORDER BY id
                ''', (start_id, end_id))

                timestamps = cursor.fetchall()
                if len(timestamps) != 2:
                    return None

                time_span_start = timestamps[0]['created_at']
                time_span_end = timestamps[1]['created_at']

                # Get actual message count in range
                cursor.execute('''
                    SELECT COUNT(*) FROM messages
                    WHERE id BETWEEN ? AND ?
                ''', (start_id, end_id))
                message_count = cursor.fetchone()[0]

                if message_count == 0:
                    return None

                # Insert batch record
                cursor.execute('''
                    INSERT INTO graphiti_batches
                    (start_message_id, end_message_id, message_count,
                     channels, time_span_start, time_span_end)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    start_id,
                    end_id,
                    message_count,
                    json.dumps(channels),
                    time_span_start,
                    time_span_end
                ))

                batch_id = cursor.lastrowid

                # Update all messages in the range to reference this batch
                cursor.execute('''
                    UPDATE messages
                    SET graphiti_batch_id = ?
                    WHERE id BETWEEN ? AND ?
                ''', (batch_id, start_id, end_id))

                conn.commit()
                return batch_id

        except Exception as e:
            print(f"Error marking batch as ingested: {e}")
            return None