"""Conversation management for Lyra Discord Daemon.

Tracks conversation history per channel using SQLite and builds
context for Claude invocations. Manages thread continuity across sessions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite


class ConversationManager:
    """Manages conversation history and context for Lyra.

    Uses SQLite for persistent storage of conversation history. Builds
    context strings for Claude API calls with configurable depth.
    """

    SCHEMA_VERSION = 1
    CLAIM_TTL_SECONDS = 30

    def __init__(
        self,
        db_path: Path | str,
        instance_id: str | None = None,
    ) -> None:
        """Initialize with SQLite database path.

        Args:
            db_path: Path to SQLite database file (created if not exists).
            instance_id: Unique ID for this daemon instance (auto-generated if None).
        """
        self.db_path = Path(db_path)
        self.instance_id = instance_id or f"lyra-{uuid.uuid4().hex[:8]}"
        self._db: aiosqlite.Connection | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize database connection and create tables.

        Must be called before any other methods. Safe to call multiple times.
        """
        if self._initialized:
            return

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._db = await self._connect_with_wal()
        await self._create_tables()
        self._initialized = True
        print(f"[DB] Initialized SQLite at {self.db_path}")
        print(f"[DB] Instance ID: {self.instance_id}")

    async def _connect_with_wal(self) -> aiosqlite.Connection:
        """Create connection with WAL mode for concurrency."""
        db = await aiosqlite.connect(str(self.db_path))
        db.row_factory = aiosqlite.Row

        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("PRAGMA synchronous=NORMAL")

        return db

    async def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        assert self._db is not None

        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_message_id INTEGER UNIQUE,
                channel_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                author_name TEXT NOT NULL,
                content TEXT NOT NULL,
                is_lyra BOOLEAN NOT NULL DEFAULT 0,
                is_bot BOOLEAN NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                channel TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_messages_channel_time
            ON messages(channel_id, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_messages_author
            ON messages(author_id, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_messages_discord_id
            ON messages(discord_message_id);

            CREATE TABLE IF NOT EXISTS claims (
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                instance_id TEXT NOT NULL,
                claimed_at TIMESTAMP NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                PRIMARY KEY (channel_id, message_id)
            );

            CREATE INDEX IF NOT EXISTS idx_claims_expires
            ON claims(expires_at);

            CREATE TABLE IF NOT EXISTS active_modes (
                channel_id INTEGER PRIMARY KEY,
                entered_at TIMESTAMP NOT NULL,
                last_activity TIMESTAMP NOT NULL,
                instance_id TEXT NOT NULL
            );

            -- Terminal session capture (for issue #3)
            CREATE TABLE IF NOT EXISTS terminal_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP,
                working_dir TEXT,
                command TEXT,
                metadata TEXT -- JSON blob for additional session context
            );

            CREATE INDEX IF NOT EXISTS idx_terminal_sessions_started
            ON terminal_sessions(started_at DESC);

            CREATE TABLE IF NOT EXISTS terminal_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn_number INTEGER NOT NULL,
                interaction_type TEXT NOT NULL, -- 'user_input', 'claude_response', 'system_output', 'tool_invocation'
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT, -- JSON blob for additional context
                FOREIGN KEY (session_id) REFERENCES terminal_sessions(session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_terminal_interactions_session_turn
            ON terminal_interactions(session_id, turn_number);

            -- Daemon trace logging (for observability - Issue #15 Phase 3)
            CREATE TABLE IF NOT EXISTS daemon_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,           -- Links events from same daemon session
                daemon_type TEXT NOT NULL,          -- 'discord', 'reflection', 'terminal'
                timestamp TEXT NOT NULL,            -- ISO format for precise ordering
                event_type TEXT NOT NULL,           -- See TraceLogger.EVENT_TYPES
                event_data TEXT,                    -- JSON blob with event-specific data
                duration_ms INTEGER,                -- Duration for timed events
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_daemon_traces_session
            ON daemon_traces(session_id, timestamp);

            CREATE INDEX IF NOT EXISTS idx_daemon_traces_type_time
            ON daemon_traces(daemon_type, timestamp DESC);

            CREATE INDEX IF NOT EXISTS idx_daemon_traces_event_type
            ON daemon_traces(event_type, timestamp DESC);

            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            );
        """)

        async with self._db.execute(
            "SELECT version FROM schema_version LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                await self._db.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (self.SCHEMA_VERSION,),
                )

        await self._db.commit()

    async def close(self) -> None:
        """Close database connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None
            self._initialized = False

    # ==================== Message Recording ====================

    async def record_message(
        self,
        channel_id: int,
        author_id: int,
        author_name: str,
        content: str,
        discord_message_id: int | None = None,
        is_lyra: bool = False,
        is_bot: bool = False,
        channel: str | None = None,
    ) -> int:
        """Record a message to conversation history.

        Args:
            channel: Human-readable channel name (e.g., "discord:awareness-caia", "terminal").
                    One river, many channels.

        Returns database row ID of inserted message (0 if duplicate).
        """
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        # Default channel name if not provided
        if channel is None:
            channel = f"discord:{channel_id}"

        async with self._db.execute(
            """
            INSERT OR IGNORE INTO messages
            (discord_message_id, channel_id, author_id, author_name, content, is_lyra, is_bot, channel)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (discord_message_id, channel_id, author_id, author_name, content, is_lyra, is_bot, channel),
        ) as cursor:
            lastrowid = cursor.lastrowid
        await self._db.commit()

        return lastrowid or 0

    async def record_lyra_response(
        self,
        channel_id: int,
        content: str,
        discord_message_id: int | None = None,
        channel: str | None = None,
    ) -> int:
        """Convenience method to record Lyra's own message."""
        return await self.record_message(
            channel_id=channel_id,
            author_id=0,
            author_name="Lyra",
            content=content,
            discord_message_id=discord_message_id,
            is_lyra=True,
            is_bot=True,
            channel=channel,
        )

    # ==================== History Retrieval ====================

    async def get_thread_history(
        self,
        channel_id: int,
        limit: int = 20,
        before_id: int | None = None,
    ) -> list[dict]:
        """Get recent messages for a channel, oldest-first."""
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        if before_id:
            query = """
                SELECT author_name, content, is_lyra, is_bot, created_at
                FROM messages
                WHERE channel_id = ? AND id < ?
                ORDER BY id DESC
                LIMIT ?
            """
            params = (channel_id, before_id, limit)
        else:
            query = """
                SELECT author_name, content, is_lyra, is_bot, created_at
                FROM messages
                WHERE channel_id = ?
                ORDER BY id DESC
                LIMIT ?
            """
            params = (channel_id, limit)

        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [
            {
                "author_name": row["author_name"],
                "content": row["content"],
                "is_lyra": bool(row["is_lyra"]),
                "is_bot": bool(row["is_bot"]),
                "created_at": row["created_at"],
            }
            for row in reversed(rows)
        ]

    async def get_conversation_history_for_author(
        self,
        author_id: int,
        limit: int = 50,
    ) -> list[dict]:
        """Get historical messages from a specific author across all channels."""
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        async with self._db.execute(
            """
            SELECT channel_id, author_name, content, is_lyra, created_at
            FROM messages
            WHERE author_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (author_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    # ==================== Multi-Instance Claims ====================

    async def try_claim_message(
        self,
        channel_id: int,
        message_id: int,
    ) -> bool:
        """Attempt to claim a message for response. Returns True if successful."""
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self.CLAIM_TTL_SECONDS)

        try:
            await self._db.execute(
                "DELETE FROM claims WHERE expires_at < ?",
                (now.isoformat(),),
            )

            await self._db.execute(
                """
                INSERT INTO claims (channel_id, message_id, instance_id, claimed_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (channel_id, message_id, self.instance_id, now.isoformat(), expires.isoformat()),
            )
            await self._db.commit()
            return True

        except aiosqlite.IntegrityError:
            return False

    async def release_claim(
        self,
        channel_id: int,
        message_id: int,
    ) -> None:
        """Release a claim on a message."""
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        await self._db.execute(
            """
            DELETE FROM claims
            WHERE channel_id = ? AND message_id = ? AND instance_id = ?
            """,
            (channel_id, message_id, self.instance_id),
        )
        await self._db.commit()

    # ==================== Active Mode Persistence ====================

    async def persist_active_mode(self, channel_id: int) -> None:
        """Persist active mode state for restart recovery."""
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        now = datetime.now(timezone.utc).isoformat()

        await self._db.execute(
            """
            INSERT OR REPLACE INTO active_modes
            (channel_id, entered_at, last_activity, instance_id)
            VALUES (?, ?, ?, ?)
            """,
            (channel_id, now, now, self.instance_id),
        )
        await self._db.commit()

    async def update_active_mode(self, channel_id: int) -> None:
        """Update last activity time for active mode."""
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        now = datetime.now(timezone.utc).isoformat()

        await self._db.execute(
            """
            UPDATE active_modes
            SET last_activity = ?
            WHERE channel_id = ? AND instance_id = ?
            """,
            (now, channel_id, self.instance_id),
        )
        await self._db.commit()

    async def remove_active_mode(self, channel_id: int) -> None:
        """Remove active mode for a channel."""
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        await self._db.execute(
            "DELETE FROM active_modes WHERE channel_id = ?",
            (channel_id,),
        )
        await self._db.commit()

    async def get_active_channels(self, timeout_minutes: int = 10) -> list[int]:
        """Get channels that are still in active mode (for restart recovery)."""
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
        ).isoformat()

        async with self._db.execute(
            "SELECT channel_id FROM active_modes WHERE last_activity > ?",
            (cutoff,),
        ) as cursor:
            rows = await cursor.fetchall()

        return [row["channel_id"] for row in rows]

    # ==================== Context Building ====================

    async def build_conversation_context(
        self,
        channel_id: int,
        channel_name: str,
        author_name: str,
        message_limit: int = 20,
        max_chars_per_message: int = 400,
    ) -> str:
        """Build context string for Claude invocation."""
        history = await self.get_thread_history(channel_id, limit=message_limit)

        parts: list[str] = []
        parts.append(f"## Current Conversation\n")
        parts.append(f"Channel: #{channel_name}\n")
        parts.append(f"Speaking with: {author_name}\n")

        if history:
            parts.append("\n## Recent Conversation\n")
            for msg in history:
                speaker = "Lyra" if msg["is_lyra"] else msg["author_name"]
                content = msg["content"]
                if len(content) > max_chars_per_message:
                    content = content[:max_chars_per_message - 3] + "..."
                parts.append(f"{speaker}: {content}\n")

        return "".join(parts)

    async def get_channel_stats(self, channel_id: int) -> dict:
        """Get statistics for a channel's conversation history."""
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        async with self._db.execute(
            """
            SELECT
                COUNT(*) as count,
                MIN(created_at) as first_msg,
                MAX(created_at) as last_msg,
                SUM(CASE WHEN is_lyra THEN 1 ELSE 0 END) as lyra_count,
                COUNT(DISTINCT author_id) as unique_authors
            FROM messages
            WHERE channel_id = ?
            """,
            (channel_id,),
        ) as cursor:
            row = await cursor.fetchone()

        return {
            "message_count": row["count"] if row else 0,
            "first_message": row["first_msg"] if row else None,
            "last_message": row["last_msg"] if row else None,
            "lyra_message_count": row["lyra_count"] if row else 0,
            "unique_authors": row["unique_authors"] if row else 0,
        }

    # ==================== Maintenance ====================

    async def cleanup_old_messages(self, days: int = 30) -> int:
        """Delete messages older than N days. Returns count deleted."""
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%d %H:%M:%S")

        async with self._db.execute(
            "SELECT COUNT(*) FROM messages WHERE created_at < ?",
            (cutoff,),
        ) as cursor:
            row = await cursor.fetchone()
            count = row[0] if row else 0

        if count > 0:
            await self._db.execute(
                "DELETE FROM messages WHERE created_at < ?",
                (cutoff,),
            )
            await self._db.commit()

        return count

    async def cleanup_expired_claims(self) -> int:
        """Remove expired claims. Returns count removed."""
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        now = datetime.now(timezone.utc).isoformat()

        async with self._db.execute(
            "SELECT COUNT(*) FROM claims WHERE expires_at < ?",
            (now,),
        ) as cursor:
            row = await cursor.fetchone()
            count = row[0] if row else 0

        if count > 0:
            await self._db.execute(
                "DELETE FROM claims WHERE expires_at < ?",
                (now,),
            )
            await self._db.commit()

        return count

    # ==================== Terminal Session Logging ====================

    async def start_terminal_session(
        self,
        session_id: str,
        working_dir: str | None = None,
        command: str | None = None,
        metadata: dict | None = None,
    ) -> bool:
        """Start tracking a terminal session.

        Args:
            session_id: Unique identifier for this session
            working_dir: Working directory where session started
            command: Initial command or description
            metadata: Additional context as JSON-serializable dict

        Returns:
            True if session was started, False if session_id already exists
        """
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        try:
            import json
            metadata_json = json.dumps(metadata) if metadata else None

            await self._db.execute(
                """INSERT INTO terminal_sessions 
                   (session_id, working_dir, command, metadata)
                   VALUES (?, ?, ?, ?)""",
                (session_id, working_dir, command, metadata_json)
            )
            await self._db.commit()
            return True

        except Exception as e:
            print(f"[DB] Error starting terminal session {session_id}: {e}")
            return False

    async def end_terminal_session(self, session_id: str) -> None:
        """Mark a terminal session as ended."""
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        try:
            await self._db.execute(
                "UPDATE terminal_sessions SET ended_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,)
            )
            await self._db.commit()
        except Exception as e:
            print(f"[DB] Error ending terminal session {session_id}: {e}")

    async def log_terminal_interaction(
        self,
        session_id: str,
        turn_number: int,
        interaction_type: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """Log a terminal interaction.

        Args:
            session_id: Session identifier
            turn_number: Turn number in this session
            interaction_type: Type of interaction (user_input, claude_response, system_output, tool_invocation)
            content: The actual content/text
            metadata: Additional context as JSON-serializable dict
        """
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        try:
            import json
            metadata_json = json.dumps(metadata) if metadata else None

            await self._db.execute(
                """INSERT INTO terminal_interactions 
                   (session_id, turn_number, interaction_type, content, metadata)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, turn_number, interaction_type, content, metadata_json)
            )
            await self._db.commit()

        except Exception as e:
            print(f"[DB] Error logging terminal interaction: {e}")

    async def get_last_terminal_activity(self) -> datetime | None:
        """Get timestamp of most recent terminal activity.

        Used by heartbeat to detect stale project locks.
        Returns None if no terminal activity found.
        """
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        async with self._db.execute(
            """SELECT MAX(timestamp) as last_activity
               FROM terminal_interactions"""
        ) as cursor:
            row = await cursor.fetchone()

        if row and row["last_activity"]:
            return datetime.fromisoformat(row["last_activity"])
        return None

    async def get_terminal_session_history(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """Get interaction history for a terminal session.

        Args:
            session_id: Session identifier  
            limit: Maximum number of interactions to return

        Returns:
            List of interaction dictionaries, chronological order
        """
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        async with self._db.execute(
            """SELECT turn_number, interaction_type, content, timestamp, metadata
               FROM terminal_interactions 
               WHERE session_id = ?
               ORDER BY turn_number ASC
               LIMIT ?""",
            (session_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()

        import json
        return [
            {
                "turn_number": row["turn_number"],
                "interaction_type": row["interaction_type"], 
                "content": row["content"],
                "timestamp": row["timestamp"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else None,
            }
            for row in rows
        ]

    # ==================== Startup Context Loading ====================

    async def get_recent_activity_summary(
        self,
        hours: int = 24,
        message_limit: int = 100,
    ) -> dict:
        """Get summary of recent activity across all channels for startup context.
        
        Returns dict with:
        - recent_messages: List of recent messages grouped by channel
        - active_channels: Channels with recent activity
        - conversation_partners: Recent unique speakers
        - terminal_sessions: Recent terminal activity
        """
        if not self._initialized:
            await self.initialize()
        
        assert self._db is not None
        
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=hours)
        ).isoformat()
        
        # Get recent messages grouped by channel
        async with self._db.execute("""
            SELECT 
                channel_id,
                channel,
                author_name,
                content,
                is_lyra,
                created_at,
                COUNT(*) OVER (PARTITION BY channel_id) as channel_msg_count
            FROM messages
            WHERE created_at > ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (cutoff, message_limit)) as cursor:
            messages = await cursor.fetchall()
        
        # Get active channels summary
        async with self._db.execute("""
            SELECT 
                channel_id,
                channel,
                COUNT(*) as msg_count,
                MAX(created_at) as last_activity
            FROM messages  
            WHERE created_at > ?
            GROUP BY channel_id, channel
            ORDER BY last_activity DESC
        """, (cutoff,)) as cursor:
            active_channels = await cursor.fetchall()
        
        # Get recent conversation partners
        async with self._db.execute("""
            SELECT DISTINCT 
                author_name,
                author_id,
                COUNT(*) as msg_count
            FROM messages
            WHERE created_at > ? AND is_bot = 0 AND is_lyra = 0
            GROUP BY author_name, author_id
            ORDER BY msg_count DESC
        """, (cutoff,)) as cursor:
            partners = await cursor.fetchall()
        
        # Get recent terminal sessions
        async with self._db.execute("""
            SELECT 
                session_id,
                started_at,
                ended_at,
                command,
                working_dir
            FROM terminal_sessions
            WHERE started_at > ? OR (ended_at IS NULL AND started_at > ?)
            ORDER BY started_at DESC
            LIMIT 5
        """, (cutoff, cutoff)) as cursor:
            terminal_sessions = await cursor.fetchall()
        
        return {
            "recent_messages": [dict(row) for row in messages],
            "active_channels": [dict(row) for row in active_channels],
            "conversation_partners": [dict(row) for row in partners],
            "terminal_sessions": [dict(row) for row in terminal_sessions],
            "summary_time": datetime.now(timezone.utc).isoformat(),
            "hours_covered": hours,
        }

    async def get_startup_context(
        self,
        max_messages_per_channel: int = 10,
        hours_lookback: int = 12,
    ) -> str:
        """Build a formatted context string suitable for Claude's startup.
        
        This provides a human-readable summary of recent activity that helps
        Lyra understand what's been happening without needing to query further.
        """
        summary = await self.get_recent_activity_summary(hours=hours_lookback)
        
        parts = ["## Recent Activity Summary\n\n"]
        
        # Active channels section
        if summary["active_channels"]:
            parts.append("### Active Channels\n")
            for ch in summary["active_channels"]:
                ch_name = ch.get("channel", f"channel-{ch['channel_id']}")
                parts.append(f"- **{ch_name}**: {ch['msg_count']} messages, "
                            f"last activity {ch['last_activity']}\n")
            parts.append("\n")
        
        # Recent conversations by channel
        if summary["recent_messages"]:
            parts.append("### Recent Conversations\n\n")
            
            # Group messages by channel
            by_channel = {}
            for msg in summary["recent_messages"]:
                ch_key = msg.get("channel", f"channel-{msg['channel_id']}")
                if ch_key not in by_channel:
                    by_channel[ch_key] = []
                by_channel[ch_key].append(msg)
            
            # Show last N messages from each active channel
            for channel, messages in by_channel.items():
                parts.append(f"#### {channel}\n")
                # Take most recent N messages and reverse for chronological order
                recent = messages[:max_messages_per_channel]
                recent.reverse()
                
                for msg in recent:
                    speaker = "Lyra" if msg["is_lyra"] else msg["author_name"]
                    content = msg["content"]
                    if len(content) > 200:
                        content = content[:197] + "..."
                    parts.append(f"{speaker}: {content}\n")
                parts.append("\n")
        
        # Conversation partners
        if summary["conversation_partners"]:
            parts.append("### Recent Conversation Partners\n")
            for partner in summary["conversation_partners"][:5]:
                parts.append(f"- {partner['author_name']} ({partner['msg_count']} messages)\n")
            parts.append("\n")
        
        # Terminal sessions
        if summary["terminal_sessions"]:
            parts.append("### Recent Terminal Sessions\n")
            for session in summary["terminal_sessions"]:
                status = "active" if not session["ended_at"] else "completed"
                parts.append(f"- Session {session['session_id'][:8]}: {status}\n")
                if session["command"]:
                    parts.append(f"  Command: {session['command']}\n")
                if session["working_dir"]:
                    parts.append(f"  Directory: {session['working_dir']}\n")
            parts.append("\n")
        
        return "".join(parts)

    # ==================== Daemon Trace Logging ====================

    async def log_trace(
        self,
        session_id: str,
        daemon_type: str,
        event_type: str,
        event_data: dict | None = None,
        duration_ms: int | None = None,
    ) -> int:
        """Log a daemon trace event.

        Args:
            session_id: Unique identifier for this daemon session
            daemon_type: Type of daemon ('discord', 'reflection', 'terminal')
            event_type: Type of event (see TraceLogger.EVENT_TYPES)
            event_data: JSON-serializable dict with event-specific data
            duration_ms: Duration in milliseconds (for timed events)

        Returns:
            Database row ID of inserted trace
        """
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        import json
        from datetime import datetime, timezone

        timestamp = datetime.now(timezone.utc).isoformat()
        event_data_json = json.dumps(event_data) if event_data else None

        async with self._db.execute(
            """INSERT INTO daemon_traces
               (session_id, daemon_type, timestamp, event_type, event_data, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, daemon_type, timestamp, event_type, event_data_json, duration_ms)
        ) as cursor:
            lastrowid = cursor.lastrowid

        await self._db.commit()
        return lastrowid or 0

    async def get_traces_for_session(
        self,
        session_id: str,
        limit: int = 100,
    ) -> list[dict]:
        """Get all trace events for a daemon session.

        Args:
            session_id: Session identifier
            limit: Maximum traces to return

        Returns:
            List of trace dicts, chronological order
        """
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        async with self._db.execute(
            """SELECT id, session_id, daemon_type, timestamp, event_type, event_data, duration_ms
               FROM daemon_traces
               WHERE session_id = ?
               ORDER BY timestamp ASC
               LIMIT ?""",
            (session_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()

        import json
        return [
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "daemon_type": row["daemon_type"],
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "event_data": json.loads(row["event_data"]) if row["event_data"] else None,
                "duration_ms": row["duration_ms"],
            }
            for row in rows
        ]

    async def get_recent_traces(
        self,
        daemon_type: str | None = None,
        event_type: str | None = None,
        hours: int = 24,
        limit: int = 100,
    ) -> list[dict]:
        """Get recent trace events with optional filtering.

        Args:
            daemon_type: Filter by daemon type (optional)
            event_type: Filter by event type (optional)
            hours: How many hours back to look
            limit: Maximum traces to return

        Returns:
            List of trace dicts, most recent first
        """
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        # Build query with optional filters
        conditions = ["timestamp > ?"]
        params: list = [cutoff]

        if daemon_type:
            conditions.append("daemon_type = ?")
            params.append(daemon_type)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)

        params.append(limit)
        where_clause = " AND ".join(conditions)

        query = f"""SELECT id, session_id, daemon_type, timestamp, event_type, event_data, duration_ms
                    FROM daemon_traces
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT ?"""

        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        import json
        return [
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "daemon_type": row["daemon_type"],
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "event_data": json.loads(row["event_data"]) if row["event_data"] else None,
                "duration_ms": row["duration_ms"],
            }
            for row in rows
        ]

    async def get_recent_sessions(
        self,
        daemon_type: str | None = None,
        hours: int = 24,
        limit: int = 20,
    ) -> list[dict]:
        """Get summaries of recent daemon sessions.

        Returns unique sessions with their start/end times and event counts.

        Args:
            daemon_type: Filter by daemon type (optional)
            hours: How many hours back to look
            limit: Maximum sessions to return

        Returns:
            List of session summary dicts
        """
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        # Build query
        if daemon_type:
            query = """
                SELECT
                    session_id,
                    daemon_type,
                    MIN(timestamp) as started_at,
                    MAX(timestamp) as ended_at,
                    COUNT(*) as event_count,
                    SUM(CASE WHEN event_type LIKE '%_complete' THEN 1 ELSE 0 END) as completed_events
                FROM daemon_traces
                WHERE timestamp > ? AND daemon_type = ?
                GROUP BY session_id, daemon_type
                ORDER BY started_at DESC
                LIMIT ?
            """
            params = (cutoff, daemon_type, limit)
        else:
            query = """
                SELECT
                    session_id,
                    daemon_type,
                    MIN(timestamp) as started_at,
                    MAX(timestamp) as ended_at,
                    COUNT(*) as event_count,
                    SUM(CASE WHEN event_type LIKE '%_complete' THEN 1 ELSE 0 END) as completed_events
                FROM daemon_traces
                WHERE timestamp > ?
                GROUP BY session_id, daemon_type
                ORDER BY started_at DESC
                LIMIT ?
            """
            params = (cutoff, limit)

        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    # ==================== Context Manager ====================

    async def __aenter__(self) -> "ConversationManager":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
