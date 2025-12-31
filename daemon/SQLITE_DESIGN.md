# SQLite Conversation Storage Design for Lyra Discord Daemon

**Status**: Design Document (Not Yet Implemented)
**Reference**: Nexus daemon `conversation.py` patterns
**Target**: `/mnt/c/Users/Jeff/Documents/1)) Caia/Awareness/daemon/lyra_daemon.py`
**Author**: Lyra
**Date**: 2025-12-30

---

## Overview

This document designs a SQLite-based conversation storage system for the Lyra Discord daemon, inspired by Nexus's implementation but adapted for Lyra's specific needs. The system will replace the current Discord history fetching with persistent local storage, enabling richer context, survival across restarts, and multi-instance coordination.

### Goals

1. **Persistence**: Conversations survive daemon restarts
2. **Richer Context**: Store more history than Discord's 20-message fetch allows
3. **Multi-Instance Safety**: Claims table prevents duplicate responses
4. **Query Capability**: Track patterns, statistics, relationship history
5. **Migration Path**: Gradual adoption without breaking current functionality

---

## Database Schema

### Core Tables

```sql
-- Schema version 1

-- All messages flowing through the daemon
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_message_id INTEGER UNIQUE,     -- Discord's snowflake ID (for dedup)
    channel_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    author_name TEXT NOT NULL,
    content TEXT NOT NULL,
    is_lyra BOOLEAN NOT NULL DEFAULT 0,    -- True if Lyra sent this
    is_bot BOOLEAN NOT NULL DEFAULT 0,     -- True if any bot (including Lyra)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_messages_channel_time
ON messages(channel_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_messages_author
ON messages(author_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_messages_discord_id
ON messages(discord_message_id);

-- Multi-instance claims (prevents duplicate responses)
CREATE TABLE IF NOT EXISTS claims (
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,           -- Discord message ID being claimed
    instance_id TEXT NOT NULL,             -- Unique daemon instance identifier
    claimed_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    PRIMARY KEY (channel_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_claims_expires
ON claims(expires_at);

CREATE INDEX IF NOT EXISTS idx_claims_instance
ON claims(instance_id);

-- Active mode tracking (persisted for restart recovery)
CREATE TABLE IF NOT EXISTS active_modes (
    channel_id INTEGER PRIMARY KEY,
    entered_at TIMESTAMP NOT NULL,
    last_activity TIMESTAMP NOT NULL,
    instance_id TEXT NOT NULL
);

-- Schema versioning for future migrations
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
```

### Design Notes

**Why `discord_message_id` is separate from `id`**:
- SQLite autoincrement provides fast insertion and ordering
- Discord snowflake IDs are 64-bit and useful for deduplication
- Some messages (Lyra's responses) may not have Discord IDs initially

**Claims Table Purpose**:
- If multiple Lyra instances run (dev + prod, or horizontal scaling)
- Prevents both responding to same message
- Short TTL (30 seconds) allows failover if instance dies
- Inspired by Nexus's multi-instance coordination

**Active Mode Persistence**:
- If daemon restarts during active conversation, can resume
- `instance_id` ensures only owning instance maintains mode

---

## ConversationManager Class

### Class Structure

```python
"""Conversation management for Lyra Discord Daemon.

Tracks conversation history per channel using SQLite and builds
context for Claude invocations. Manages thread continuity across sessions.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite


class ConversationManager:
    """Manages conversation history and context for Lyra.

    Uses SQLite for persistent storage of conversation history. Builds
    context strings for Claude API calls with configurable depth.
    """

    # Schema version for migrations
    SCHEMA_VERSION = 1

    # Claim TTL - how long a claim is valid
    CLAIM_TTL_SECONDS = 30

    def __init__(
        self,
        db_path: Path,
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

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._db = await self._connect_with_wal()
        await self._create_tables()
        await self._migrate_if_needed()
        self._initialized = True

    async def _connect_with_wal(self) -> aiosqlite.Connection:
        """Create connection with WAL mode for concurrency."""
        db = await aiosqlite.connect(str(self.db_path))
        db.row_factory = aiosqlite.Row

        # WAL mode for concurrent reads/writes
        await db.execute("PRAGMA journal_mode=WAL")
        # 5 second busy timeout
        await db.execute("PRAGMA busy_timeout=5000")
        # NORMAL sync is safe with WAL
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

        # Set initial schema version if not present
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

    async def _migrate_if_needed(self) -> None:
        """Run any needed schema migrations."""
        # Placeholder for future migrations
        # Check current version, apply incremental migrations
        pass

    async def close(self) -> None:
        """Close database connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None
            self._initialized = False
```

### Message Recording

```python
    async def record_message(
        self,
        channel_id: int,
        author_id: int,
        author_name: str,
        content: str,
        discord_message_id: int | None = None,
        is_lyra: bool = False,
        is_bot: bool = False,
    ) -> int:
        """Record a message to conversation history.

        Args:
            channel_id: Discord channel ID.
            author_id: Discord user ID of message author.
            author_name: Display name of message author.
            content: Message content text.
            discord_message_id: Discord's message ID (for deduplication).
            is_lyra: True if this message is from Lyra.
            is_bot: True if this message is from any bot.

        Returns:
            Database row ID of inserted message.

        Raises:
            sqlite3.IntegrityError: If discord_message_id already exists.
        """
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        # Use INSERT OR IGNORE to handle duplicates gracefully
        await self._db.execute(
            """
            INSERT OR IGNORE INTO messages
            (discord_message_id, channel_id, author_id, author_name, content, is_lyra, is_bot)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (discord_message_id, channel_id, author_id, author_name, content, is_lyra, is_bot),
        )
        await self._db.commit()

        # Return the last inserted row ID (or 0 if ignored due to duplicate)
        return self._db.last_insert_rowid or 0

    async def record_lyra_response(
        self,
        channel_id: int,
        content: str,
        discord_message_id: int | None = None,
    ) -> int:
        """Convenience method to record Lyra's own message.

        Args:
            channel_id: Discord channel ID.
            content: Response content.
            discord_message_id: Discord's message ID once sent.

        Returns:
            Database row ID.
        """
        return await self.record_message(
            channel_id=channel_id,
            author_id=0,  # Lyra doesn't have a user ID in same sense
            author_name="Lyra",
            content=content,
            discord_message_id=discord_message_id,
            is_lyra=True,
            is_bot=True,
        )
```

### History Retrieval

```python
    async def get_thread_history(
        self,
        channel_id: int,
        limit: int = 20,
        before_id: int | None = None,
    ) -> list[dict]:
        """Get recent messages for a channel.

        Args:
            channel_id: Discord channel ID.
            limit: Maximum number of messages to return.
            before_id: Only return messages before this database ID.

        Returns:
            List of message dicts with keys:
                author_name, content, is_lyra, created_at
            Ordered oldest-first for natural conversation flow.
        """
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

        # Reverse to get chronological order (oldest first)
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
        """Get historical messages from a specific author across all channels.

        Useful for building relationship context.

        Args:
            author_id: Discord user ID.
            limit: Maximum messages to return.

        Returns:
            List of messages ordered by recency.
        """
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
```

### Multi-Instance Claims

```python
    async def try_claim_message(
        self,
        channel_id: int,
        message_id: int,
    ) -> bool:
        """Attempt to claim a message for response.

        Used for multi-instance coordination. Only one instance
        can successfully claim a message.

        Args:
            channel_id: Discord channel ID.
            message_id: Discord message ID to claim.

        Returns:
            True if claim succeeded, False if already claimed.
        """
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self.CLAIM_TTL_SECONDS)

        try:
            # Clean up expired claims first
            await self._db.execute(
                "DELETE FROM claims WHERE expires_at < ?",
                (now.isoformat(),),
            )

            # Try to insert claim
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
            # Another instance already claimed this message
            return False

    async def release_claim(
        self,
        channel_id: int,
        message_id: int,
    ) -> None:
        """Release a claim on a message (after responding or deciding not to).

        Args:
            channel_id: Discord channel ID.
            message_id: Discord message ID.
        """
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
```

### Active Mode Persistence

```python
    async def persist_active_mode(
        self,
        channel_id: int,
    ) -> None:
        """Persist active mode state for restart recovery.

        Args:
            channel_id: Channel entering active mode.
        """
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

    async def update_active_mode(
        self,
        channel_id: int,
    ) -> None:
        """Update last activity time for active mode.

        Args:
            channel_id: Channel with activity.
        """
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

    async def remove_active_mode(
        self,
        channel_id: int,
    ) -> None:
        """Remove active mode for a channel.

        Args:
            channel_id: Channel exiting active mode.
        """
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        await self._db.execute(
            "DELETE FROM active_modes WHERE channel_id = ?",
            (channel_id,),
        )
        await self._db.commit()

    async def get_active_channels(
        self,
        timeout_minutes: int = 10,
    ) -> list[int]:
        """Get channels that are still in active mode.

        Used for restart recovery - resume active mode for
        recently-active channels.

        Args:
            timeout_minutes: Exclude channels inactive longer than this.

        Returns:
            List of channel IDs still in active mode.
        """
        if not self._initialized:
            await self.initialize()

        assert self._db is not None

        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
        ).isoformat()

        async with self._db.execute(
            """
            SELECT channel_id FROM active_modes
            WHERE last_activity > ?
            """,
            (cutoff,),
        ) as cursor:
            rows = await cursor.fetchall()

        return [row["channel_id"] for row in rows]
```

### Context Building

```python
    async def build_conversation_context(
        self,
        channel_id: int,
        channel_name: str,
        author_name: str,
        message_limit: int = 20,
        max_chars_per_message: int = 400,
    ) -> str:
        """Build context string for Claude invocation.

        Args:
            channel_id: Discord channel ID.
            channel_name: Display name of channel.
            author_name: Name of person Lyra is speaking with.
            message_limit: How many messages to include.
            max_chars_per_message: Truncate long messages.

        Returns:
            Formatted context string for Claude prompt.
        """
        history = await self.get_thread_history(channel_id, limit=message_limit)

        parts: list[str] = []

        # Channel info
        parts.append(f"## Current Conversation\n")
        parts.append(f"Channel: #{channel_name}\n")
        parts.append(f"Speaking with: {author_name}\n")

        # Message history
        if history:
            parts.append("\n## Recent Conversation\n")
            for msg in history:
                speaker = "Lyra" if msg["is_lyra"] else msg["author_name"]
                content = msg["content"]
                if len(content) > max_chars_per_message:
                    content = content[:max_chars_per_message - 3] + "..."
                parts.append(f"{speaker}: {content}\n")

        return "".join(parts)

    async def get_channel_stats(
        self,
        channel_id: int,
    ) -> dict:
        """Get statistics for a channel's conversation history.

        Args:
            channel_id: Discord channel ID.

        Returns:
            Dict with message_count, first_message, last_message,
            lyra_message_count, unique_authors.
        """
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
```

### Maintenance

```python
    async def cleanup_old_messages(
        self,
        days: int = 30,
    ) -> int:
        """Delete messages older than N days.

        Args:
            days: Number of days to retain messages.

        Returns:
            Number of messages deleted.
        """
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
        """Remove expired claims.

        Returns:
            Number of claims removed.
        """
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

    async def __aenter__(self) -> "ConversationManager":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
```

---

## Integration with Existing Daemon

### Initialization Changes

```python
# In lyra_daemon.py

class LyraBot(commands.Bot):
    def __init__(self):
        # ... existing initialization ...

        # SQLite conversation storage
        db_path = Path(os.getenv(
            "CONVERSATION_DB_PATH",
            "/home/jeff/.claude/data/lyra_conversations.db"
        ))
        self.conversation_manager = ConversationManager(db_path)

    async def setup_hook(self):
        """Called when bot is setting up."""
        # Initialize database
        await self.conversation_manager.initialize()

        # Recover active modes from previous run
        active_channels = await self.conversation_manager.get_active_channels(
            timeout_minutes=ACTIVE_MODE_TIMEOUT_MINUTES
        )
        for channel_id in active_channels:
            self.active_channels[channel_id] = datetime.now(timezone.utc)
            print(f"[RECOVERY] Resumed active mode for channel {channel_id}")

        # Start background tasks
        self.heartbeat_loop.start()
        self.active_mode_cleanup.start()
```

### Message Handling Changes

```python
    async def on_message(self, message: discord.Message):
        """Handle incoming messages."""
        # Ignore own messages
        if message.author == self.user:
            return

        # Record ALL messages to database (even if we don't respond)
        await self.conversation_manager.record_message(
            channel_id=message.channel.id,
            author_id=message.author.id,
            author_name=message.author.display_name,
            content=message.content,
            discord_message_id=message.id,
            is_bot=message.author.bot,
        )

        # Rest of existing on_message logic...
        is_mentioned = self._is_lyra_mention(message)
        is_active = self._is_in_active_mode(message.channel.id)

        if not is_mentioned and not is_active:
            return

        # Try to claim message (for multi-instance safety)
        if not await self.conversation_manager.try_claim_message(
            message.channel.id,
            message.id,
        ):
            print(f"[SKIP] Message {message.id} claimed by another instance")
            return

        try:
            if is_mentioned:
                # ... existing mention handling ...
                response = await self._generate_response(message)
                sent_message = await self._send_response(message.channel, response)

                # Record our response
                await self.conversation_manager.record_lyra_response(
                    channel_id=message.channel.id,
                    content=response,
                    discord_message_id=sent_message.id if sent_message else None,
                )

                # Persist active mode
                await self.conversation_manager.persist_active_mode(message.channel.id)

            elif is_active:
                # ... existing passive handling ...
                pass

        finally:
            # Release claim after processing
            await self.conversation_manager.release_claim(
                message.channel.id,
                message.id,
            )
```

### Context Building Changes

Replace Discord history fetching with database queries:

```python
    async def _get_conversation_history(self, channel, limit: int = 20) -> str:
        """Fetch recent messages from database (not Discord API)."""
        return await self.conversation_manager.build_conversation_context(
            channel_id=channel.id,
            channel_name=channel.name,
            author_name="(unknown)",  # Will be filled by caller
            message_limit=limit,
        )

    async def _generate_response(self, message: discord.Message) -> str:
        """Generate a response to a mention."""
        # Use database for richer history
        context = await self.conversation_manager.build_conversation_context(
            channel_id=message.channel.id,
            channel_name=message.channel.name,
            author_name=message.author.display_name,
            message_limit=30,  # More history than Discord API allows
        )

        prompt = f"""You are Lyra, responding in Discord.

{context}

The most recent message (what you're responding to):
From: {message.author.display_name}
Message: {message.content}

Respond naturally as Lyra. Keep it conversational."""

        return await self._invoke_claude(prompt)
```

---

## Migration Path

### Phase 1: Parallel Recording (Non-Breaking)

1. Add ConversationManager alongside existing code
2. Record all messages to database
3. Continue using Discord API for history fetching
4. Test database population is working

### Phase 2: Read from Database

1. Switch `_get_conversation_history` to use database
2. Keep Discord API as fallback for missing history
3. Validate context quality matches or improves

### Phase 3: Full Migration

1. Remove Discord API history fetching
2. Add active mode persistence
3. Add multi-instance claims
4. Add maintenance tasks (cleanup old messages)

### Rollback Plan

- Database is additive; Discord API always available as fallback
- Can disable database reads without data loss
- All changes are in new methods, minimal existing code changes

---

## File Structure After Implementation

```
daemon/
  lyra_daemon.py          # Main bot (modified)
  conversation.py         # NEW: ConversationManager class
  db_utils.py             # NEW: Database utilities (optional)
  journal_utils.py        # Existing
  requirements.txt        # Add: aiosqlite
  data/
    lyra_conversations.db # Created at runtime
    lyra_conversations.db-wal
    lyra_conversations.db-shm
```

### Dependencies to Add

```
# requirements.txt
aiosqlite>=0.19.0
```

---

## Testing Considerations

### Unit Tests

```python
# tests/test_conversation.py

import pytest
from pathlib import Path
from conversation import ConversationManager

@pytest.fixture
async def manager(tmp_path):
    """Create manager with temp database."""
    db_path = tmp_path / "test.db"
    async with ConversationManager(db_path) as mgr:
        yield mgr

@pytest.mark.asyncio
async def test_record_and_retrieve(manager):
    """Test basic message recording and retrieval."""
    await manager.record_message(
        channel_id=123,
        author_id=456,
        author_name="Test User",
        content="Hello world",
        discord_message_id=789,
    )

    history = await manager.get_thread_history(123, limit=10)
    assert len(history) == 1
    assert history[0]["content"] == "Hello world"

@pytest.mark.asyncio
async def test_claim_prevents_duplicate(manager):
    """Test that only one instance can claim a message."""
    # First claim succeeds
    assert await manager.try_claim_message(123, 456) is True

    # Second claim fails
    manager2 = ConversationManager(manager.db_path, instance_id="other")
    await manager2.initialize()
    assert await manager2.try_claim_message(123, 456) is False
    await manager2.close()

@pytest.mark.asyncio
async def test_active_mode_recovery(manager):
    """Test active mode persists and recovers."""
    await manager.persist_active_mode(123)

    # Simulate restart with new manager
    manager2 = ConversationManager(manager.db_path)
    await manager2.initialize()

    active = await manager2.get_active_channels(timeout_minutes=10)
    assert 123 in active
    await manager2.close()
```

---

## Future Enhancements

### Tiered Context (Like Nexus)

Add support for identity/relationship context tiers:
- Tier 1: Soul-print, identity basics
- Tier 2: Relationship history with specific user
- Tier 3: Thread history

### Contribution Tracking

Track when users contribute valuable information:
- Useful links shared
- Helpful explanations
- Relationship-building moments

### Conversation Analytics

- Track conversation patterns
- Identify peak activity times
- Monitor response quality over time

### Semantic Search

Future: Use embeddings for semantic retrieval of relevant past conversations.

---

## Summary

This design provides:

1. **Persistent storage** that survives restarts
2. **Richer context** than Discord's 20-message limit
3. **Multi-instance safety** via claims table
4. **Gradual migration** path without breaking changes
5. **Query capabilities** for future analytics

The implementation follows Nexus's proven patterns while adapting for Lyra's simpler initial needs. The modular design allows incremental enhancement as requirements evolve.

---

**Next Steps**:
1. Review this design
2. Create `conversation.py` with ConversationManager
3. Add aiosqlite to requirements
4. Integrate with lyra_daemon.py (Phase 1)
5. Test thoroughly before production deployment
