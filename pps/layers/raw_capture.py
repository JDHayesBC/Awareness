"""
Layer 1: Raw Capture (SQLite)

Everything, unfiltered. The source of truth that can rebuild other layers if needed.
Currently reads from the Discord SQLite database; will expand to capture terminal sessions too.
"""

import sqlite3
from pathlib import Path
from typing import Optional

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
            db_path: Path to SQLite database. Defaults to ~/.claude/data/lyra_memory.db
        """
        if db_path is None:
            db_path = Path.home() / ".claude" / "data" / "lyra_conversations.db"
        self.db_path = db_path

    def _connect_with_wal(self) -> sqlite3.Connection:
        """
        Create a SQLite connection with WAL mode enabled for better concurrency.
        
        WAL (Write-Ahead Logging) mode allows concurrent reads and writes,
        improving performance when multiple processes access the database.
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

    @property
    def layer_type(self) -> LayerType:
        return LayerType.RAW_CAPTURE

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Search raw captured content using SQLite FTS5.

        Searches across all stored messages in the database.
        """
        try:
            # Connect to database with WAL mode
            conn = self._connect_with_wal()
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
                    conn.close()
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
            
            conn.close()
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
            
            # Connect to database with WAL mode
            conn = self._connect_with_wal()
            cursor = conn.cursor()
            
            # Insert into messages table
            cursor.execute('''
                INSERT OR IGNORE INTO messages 
                (discord_message_id, channel, author_id, author_name, content, is_lyra, is_bot, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ''', (
                discord_message_id,
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
            conn.close()
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

            # Try to connect with WAL mode and run a simple query
            conn = self._connect_with_wal()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            table_count = cursor.fetchone()[0]
            conn.close()

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
