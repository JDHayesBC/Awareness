"""
Message Summarization Layer

Compresses conversational content for efficient startup context loading.
Creates high-density summaries of work sessions, technical discussions, 
and project developments while preserving key decisions and outcomes.
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional, Dict, List
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
        """Create SQLite connection with WAL mode enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        # Enable WAL mode for concurrent access
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        
        return conn

    def _ensure_tables(self):
        """Create message_summaries table and modify messages table if needed."""
        try:
            conn = self._connect_with_wal()
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
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"Warning: Could not ensure message_summaries tables: {e}")

    @property
    def layer_type(self) -> LayerType:
        return LayerType.RAW_CAPTURE  # Part of Layer 1 since it's conversation data

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Search message summaries using full-text search.
        
        Returns dense summaries that match the query, allowing for contextual
        retrieval of compressed work content.
        """
        try:
            conn = self._connect_with_wal()
            cursor = conn.cursor()
            
            # Search summaries by text content using basic LIKE for now
            # TODO: Consider adding FTS5 for summaries if volume grows
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
            
            conn.close()
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
                - message_count: Number of messages summarized
                - channels: List of channels covered
                - summary_type: Type of summary (work, social, technical)
        """
        if not metadata:
            return False
            
        try:
            conn = self._connect_with_wal()
            cursor = conn.cursor()
            
            # Get time span from first and last messages
            cursor.execute('''
                SELECT created_at FROM messages 
                WHERE id IN (?, ?)
                ORDER BY id
            ''', (metadata['start_message_id'], metadata['end_message_id']))
            
            timestamps = cursor.fetchall()
            if len(timestamps) != 2:
                conn.close()
                return False
            
            time_span_start = timestamps[0]['created_at']
            time_span_end = timestamps[1]['created_at']
            
            # Insert summary
            cursor.execute('''
                INSERT INTO message_summaries 
                (summary_text, start_message_id, end_message_id, message_count, 
                 channels, time_span_start, time_span_end, summary_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                content,
                metadata['start_message_id'],
                metadata['end_message_id'],
                metadata['message_count'],
                json.dumps(metadata.get('channels', [])),  # Store as proper JSON
                time_span_start,
                time_span_end,
                metadata.get('summary_type', 'work')
            ))
            
            summary_id = cursor.lastrowid
            
            # Update all messages in the range to reference this summary
            cursor.execute('''
                UPDATE messages 
                SET summary_id = ? 
                WHERE id BETWEEN ? AND ?
            ''', (summary_id, metadata['start_message_id'], metadata['end_message_id']))
            
            conn.commit()
            conn.close()
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

            conn = self._connect_with_wal()
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
            
            conn.close()

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
            conn = self._connect_with_wal()
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
            
            conn.close()
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
            conn = self._connect_with_wal()
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
            
            conn.close()
            return results
            
        except Exception as e:
            print(f"Error getting recent summaries: {e}")
            return []

    def count_unsummarized_messages(self) -> int:
        """
        Count how many messages haven't been summarized yet.
        
        Used by reflection daemon to decide if summarization is needed.
        """
        try:
            conn = self._connect_with_wal()
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
            conn.close()
            return count
            
        except Exception as e:
            print(f"Error counting unsummarized messages: {e}")
            return 0

    async def create_and_store_summary(self, summary_text: str, start_id: int, end_id: int, 
                                     channels: list, summary_type: str = "work") -> bool:
        """
        Create and store a summary for a range of messages.
        
        This is the main method used by reflection daemon to create summaries.
        """
        try:
            conn = self._connect_with_wal()
            cursor = conn.cursor()
            
            # Verify the message range exists
            cursor.execute('''
                SELECT COUNT(*) FROM messages 
                WHERE id BETWEEN ? AND ?
            ''', (start_id, end_id))
            
            message_count = cursor.fetchone()[0]
            if message_count == 0:
                conn.close()
                return False
            
            # Get time span from first and last messages
            cursor.execute('''
                SELECT created_at FROM messages 
                WHERE id IN (?, ?)
                ORDER BY id
            ''', (start_id, end_id))
            
            timestamps = cursor.fetchall()
            if len(timestamps) != 2:
                conn.close()
                return False
            
            time_span_start = timestamps[0]['created_at']
            time_span_end = timestamps[1]['created_at']
            
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
                json.dumps(channels),  # Store as proper JSON
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
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"Error creating and storing summary: {e}")
            return False