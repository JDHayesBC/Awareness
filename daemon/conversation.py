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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

    # ==================== Context Manager ====================

    async def __aenter__(self) -> "ConversationManager":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
