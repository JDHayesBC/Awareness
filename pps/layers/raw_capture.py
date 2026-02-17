"""
Layer 1: Raw Capture (SQLite)

Everything, unfiltered. The source of truth that can rebuild other layers if needed.
Currently reads from the Discord SQLite database; will expand to capture terminal sessions too.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Generator

from . import PatternLayer, LayerType, SearchResult, LayerHealth


class RawCaptureLayer(PatternLayer):
    """
    Layer 1: Raw Capture

    Stores everything in SQLite. Nothing is truly lost.
    Currently connects to the existing Discord message database.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the raw capture layer.

        Args:
            db_path: Path to SQLite database. Defaults to $ENTITY_PATH/data/conversations.db
        """
        if db_path is None:
            # Database now in entity directory (Issue #131 migration)
            entity_path = os.getenv("ENTITY_PATH", str(Path.home() / ".claude"))
            db_path = Path(entity_path) / "data" / "conversations.db"
        self.db_path = db_path

    def _connect_with_wal(self) -> sqlite3.Connection:
        """
        Create a SQLite connection with WAL mode enabled for better concurrency.

        WAL (Write-Ahead Logging) mode allows concurrent reads and writes,
        improving performance when multiple processes access the database.

        Note: Prefer using get_connection() context manager instead of calling
        this method directly to ensure connections are properly closed.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Enable WAL mode for concurrent access
        conn.execute("PRAGMA journal_mode=WAL")
        # 5 second busy timeout for better handling of concurrent access
        conn.execute("PRAGMA busy_timeout=5000")
        # NORMAL sync mode is safe with WAL and faster than FULL
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
            # Force WAL checkpoint on Docker bind mounts where .shm isn't shared
            # across the host/container boundary, causing writes to be invisible
            # from the host until the WAL is checkpointed to the main db file.
            if os.getenv("RUNNING_IN_DOCKER") or os.getenv("ENTITY_PATH", "").startswith("/app/"):
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:
                    pass  # Best effort - don't crash on checkpoint failure
            conn.close()

    @property
    def layer_type(self) -> LayerType:
        return LayerType.RAW_CAPTURE

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Search raw captured content using SQLite FTS5.

        Searches across all stored messages in the database.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # First check if FTS5 virtual table exists
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
                )
                fts_exists = cursor.fetchone() is not None

                if not fts_exists:
                    # Try to create FTS5 table if messages table exists
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
                    )
                    if cursor.fetchone():
                        # Create FTS5 virtual table
                        cursor.execute('''
                            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                                content,
                                author_name,
                                channel,
                                content='messages',
                                content_rowid='id'
                            )
                        ''')

                        # Populate FTS5 table
                        cursor.execute('''
                            INSERT INTO messages_fts(rowid, content, author_name, channel)
                            SELECT id, content, author_name, channel FROM messages
                        ''')
                        conn.commit()
                    else:
                        # No messages table, return empty
                        return []

                # Perform FTS5 search
                # Pass query directly - FTS5 supports rich syntax:
                #   word1 word2     → AND (both required)
                #   word1 OR word2  → OR (either)
                #   "exact phrase"  → phrase match
                #   word*           → prefix
                #   NOT word        → exclusion
                search_query = query

                cursor.execute('''
                    SELECT
                        m.id,
                        m.content,
                        m.author_name,
                        m.channel,
                        m.created_at,
                        m.is_lyra,
                        messages_fts.rank
                    FROM messages_fts
                    JOIN messages m ON messages_fts.rowid = m.id
                    WHERE messages_fts MATCH ?
                    ORDER BY messages_fts.rank, m.created_at DESC
                    LIMIT ?
                ''', (search_query, limit))

                results = []
                for row in cursor.fetchall():
                    # Calculate relevance score (FTS5 rank is negative, lower is better)
                    relevance = max(0.1, min(1.0, 1.0 / (abs(row['rank']) + 1)))

                    results.append(SearchResult(
                        content=row['content'],
                        source=f"{row['channel']}:{row['id']}",
                        layer=self.layer_type,
                        relevance_score=relevance,
                        metadata={
                            'id': row['id'],
                            'author': row['author_name'],
                            'channel': row['channel'],
                            'timestamp': row['created_at'],
                            'is_lyra': bool(row['is_lyra']),
                            'fts_rank': row['rank']
                        }
                    ))

                return results

        except Exception as e:
            # Return empty results on any error
            return []

    async def store(self, content: str, metadata: Optional[dict] = None) -> bool:
        """
        Store content in raw capture.

        Args:
            content: The message content to store
            metadata: Optional metadata dict with keys:
                - author_name: Name of message author
                - channel: Channel identifier (e.g. "discord:channel-name", "terminal")
                - is_lyra: Whether this message is from Lyra
                - discord_message_id: Original Discord message ID (if applicable)
        """
        try:
            # Extract metadata with defaults
            if metadata is None:
                metadata = {}

            author_name = metadata.get('author_name', 'Unknown')
            channel = metadata.get('channel', 'terminal')
            is_lyra = metadata.get('is_lyra', False)
            discord_message_id = metadata.get('discord_message_id')

            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Insert into messages table
                # Note: channel_id is required (NOT NULL) - use 0 for terminal sources
                cursor.execute('''
                    INSERT OR IGNORE INTO messages
                    (discord_message_id, channel_id, channel, author_id, author_name, content, is_lyra, is_bot, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ''', (
                    discord_message_id,
                    0,  # channel_id - use 0 for non-Discord sources
                    channel,
                    0,  # author_id - use 0 for non-Discord sources
                    author_name,
                    content,
                    is_lyra,
                    is_lyra  # is_bot - assume Lyra messages are bot messages
                ))

                # If we inserted a new row, also update FTS5 table if it exists
                if cursor.rowcount > 0:
                    row_id = cursor.lastrowid

                    # Check if FTS5 table exists
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
                    )
                    if cursor.fetchone():
                        # Update FTS5 table
                        cursor.execute('''
                            INSERT INTO messages_fts(rowid, content, author_name, channel)
                            VALUES (?, ?, ?, ?)
                        ''', (row_id, content, author_name, channel))

                conn.commit()
                return True

        except Exception as e:
            return False

    async def health(self) -> LayerHealth:
        """Check if SQLite database is accessible."""
        try:
            if not self.db_path.exists():
                return LayerHealth(
                    available=False,
                    message=f"Database not found: {self.db_path}",
                    details={"db_path": str(self.db_path)}
                )

            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
                table_count = cursor.fetchone()[0]

            return LayerHealth(
                available=True,
                message=f"SQLite connected ({table_count} tables)",
                details={"db_path": str(self.db_path), "table_count": table_count}
            )
        except Exception as e:
            return LayerHealth(
                available=False,
                message=f"SQLite error: {e}",
                details={"error": str(e)}
            )
