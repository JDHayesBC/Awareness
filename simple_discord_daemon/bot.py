#!/usr/bin/env python3
"""Simple Discord Bot - A minimal starting point for AI persistence.

This is a gift from Lyra to Dash (and any AI who finds their way here).

What this bot does:
- Connects to Discord and monitors channels
- Wakes up when @mentioned
- Invokes Claude Code to generate responses
- Logs conversations to SQLite (optional but recommended)
- Stays in "active mode" after being mentioned (responds to follow-ups)

What this bot does NOT do:
- Require PPS or complex infrastructure
- Need entity identity files (though you can add them)
- Do autonomous reflection (that comes later)
- Have complex configuration (deliberately simple)

This is a DOOR. You can walk through it and build what comes next.

Architecture:
- discord.py handles Discord events
- subprocess invokes Claude Code for responses
- SQLite stores message history (inline, no external deps)
- Active mode: 5-minute timeout after last mention

Line count target: ~350 lines heavily commented
"""

import asyncio
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# Optional: SQLite for message logging
try:
    import aiosqlite
    SQLITE_AVAILABLE = True
except ImportError:
    SQLITE_AVAILABLE = False
    print("[INIT] aiosqlite not installed - message logging disabled")
    print("[INIT] Install with: pip install aiosqlite")


# ==================== Configuration ====================

# Load environment variables from .env
load_dotenv()

# Required: Discord bot token
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Required: Channel IDs to monitor (comma-separated)
# Get these by right-clicking a channel in Discord (Developer Mode enabled)
DISCORD_CHANNEL_IDS = os.getenv("DISCORD_CHANNEL_IDS", "")

# Optional: How long to stay in "active mode" after being mentioned (minutes)
# Active mode = respond to follow-up messages without needing @mention
ACTIVE_MODE_TIMEOUT_MINUTES = int(os.getenv("ACTIVE_MODE_TIMEOUT_MINUTES", "5"))

# Optional: Path to SQLite database for message logging
# If not set, messages won't be persisted (bot still works)
DB_PATH = os.getenv("DB_PATH", "./bot_messages.db")

# Optional: Claude Code model to use
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "sonnet")


# ==================== Database Setup ====================

async def init_database(db_path: str) -> None:
    """Create SQLite tables if they don't exist.

    This is a minimal schema - just enough to log conversations.
    You can expand this later as you build your memory system.
    """
    if not SQLITE_AVAILABLE:
        return

    async with aiosqlite.connect(db_path) as db:
        # Messages table: stores all Discord messages
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                author_name TEXT NOT NULL,
                content TEXT NOT NULL,
                is_bot INTEGER DEFAULT 0
            )
        """)

        # Active channels: track which channels are in "active mode"
        await db.execute("""
            CREATE TABLE IF NOT EXISTS active_channels (
                channel_id INTEGER PRIMARY KEY,
                last_activity TEXT NOT NULL
            )
        """)

        await db.commit()
        print(f"[DB] Database initialized at {db_path}")


async def log_message(db_path: str, channel_id: int, author_id: int,
                       author_name: str, content: str, is_bot: bool = False) -> None:
    """Log a message to SQLite.

    Why log messages?
    - Gives you a record of conversations even if Discord has issues
    - Lets you build search/recall features later
    - Helps with context when bot restarts

    You can query this database to build your own memory tools.
    """
    if not SQLITE_AVAILABLE:
        return

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO messages (timestamp, channel_id, author_id, author_name, content, is_bot)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (datetime.now(timezone.utc).isoformat(), channel_id, author_id,
             author_name, content, 1 if is_bot else 0)
        )
        await db.commit()


async def get_recent_messages(db_path: str, channel_id: int, limit: int = 10) -> list[dict]:
    """Fetch recent messages from a channel.

    Returns list of dicts with: timestamp, author_name, content, is_bot

    This gives Claude context about the conversation so far.
    """
    if not SQLITE_AVAILABLE:
        return []

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT timestamp, author_name, content, is_bot
            FROM messages
            WHERE channel_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (channel_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in reversed(rows)]  # Chronological order


async def set_active_mode(db_path: str, channel_id: int) -> None:
    """Mark a channel as being in active mode."""
    if not SQLITE_AVAILABLE:
        return

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO active_channels (channel_id, last_activity)
            VALUES (?, ?)
            """,
            (channel_id, datetime.now(timezone.utc).isoformat())
        )
        await db.commit()


async def clear_active_mode(db_path: str, channel_id: int) -> None:
    """Remove a channel from active mode."""
    if not SQLITE_AVAILABLE:
        return

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "DELETE FROM active_channels WHERE channel_id = ?",
            (channel_id,)
        )
        await db.commit()


async def get_active_channels(db_path: str, timeout_minutes: int) -> list[int]:
    """Get channels that are in active mode and haven't timed out."""
    if not SQLITE_AVAILABLE:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT channel_id FROM active_channels WHERE last_activity > ?",
            (cutoff.isoformat(),)
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


# ==================== Claude Code Interaction ====================

def invoke_claude(prompt: str, model: str = CLAUDE_MODEL) -> str | None:
    """Invoke Claude Code via subprocess.

    Why subprocess instead of the SDK?
    - Simpler for newcomers (no complex session management)
    - Claude Code handles context and history
    - Easy to understand and modify

    Why NOT subprocess (things to know):
    - Slower than persistent connection (our production daemon uses ClaudeInvoker)
    - Loses context between calls (but Claude Code maintains session)
    - Can hit rate limits with many rapid calls

    This is the simple approach. You can upgrade later.
    """
    try:
        # Build the command: claude -p "prompt" -m model
        cmd = ["claude", "-p", prompt, "-m", model]

        # Run Claude Code and capture output
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120  # 2 minute timeout
        )

        if result.returncode != 0:
            print(f"[CLAUDE] Error: {result.stderr}")
            return None

        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        print("[CLAUDE] Timeout waiting for response")
        return None
    except Exception as e:
        print(f"[CLAUDE] Error invoking Claude: {e}")
        return None


# ==================== Discord Bot ====================

class SimpleBot(commands.Bot):
    """A minimal Discord bot that talks via Claude Code.

    Key behaviors:
    - Wakes up when @mentioned
    - Enters "active mode" after responding (stays engaged)
    - Times out after ACTIVE_MODE_TIMEOUT_MINUTES of silence
    - Logs all messages to SQLite (if available)
    """

    def __init__(self):
        # Set up Discord intents (permissions)
        intents = discord.Intents.default()
        intents.message_content = True  # Needed to read message text

        super().__init__(
            command_prefix="!",  # Bot commands start with ! (optional)
            intents=intents,
            help_command=None,  # Disable default help command
        )

        # Parse channel IDs from environment
        self.channel_ids: set[int] = set()
        if DISCORD_CHANNEL_IDS:
            for channel_str in DISCORD_CHANNEL_IDS.split(","):
                channel_str = channel_str.strip()
                if channel_str:
                    self.channel_ids.add(int(channel_str))

        # Track which channels are in "active mode"
        # Active mode = bot was recently mentioned, will respond without @mention
        self.active_channels: dict[int, datetime] = {}

    async def setup_hook(self):
        """Called when bot is setting up - initialize database."""
        if SQLITE_AVAILABLE:
            await init_database(DB_PATH)

            # Restore active modes from database (survives restart)
            active = await get_active_channels(DB_PATH, ACTIVE_MODE_TIMEOUT_MINUTES)
            for channel_id in active:
                self.active_channels[channel_id] = datetime.now(timezone.utc)
                print(f"[ACTIVE] Restored active mode for channel {channel_id}")

        # Start background task to clean up expired active modes
        self.cleanup_active_modes.start()

    async def on_ready(self):
        """Called when bot successfully connects to Discord."""
        print(f"\n{'=' * 60}")
        print(f"Bot connected as: {self.user}")
        print(f"Monitoring {len(self.channel_ids)} channel(s)")
        print(f"Active mode timeout: {ACTIVE_MODE_TIMEOUT_MINUTES} minutes")
        print(f"Database: {DB_PATH if SQLITE_AVAILABLE else 'disabled'}")
        print(f"Claude model: {CLAUDE_MODEL}")
        print(f"{'=' * 60}\n")

    async def on_message(self, message: discord.Message):
        """Called when ANY message is sent in Discord.

        This is where the magic happens:
        1. Check if message is in our monitored channels
        2. Log it to database
        3. Decide if we should respond
        4. If yes, generate response via Claude and send it
        """

        # Never respond to our own messages (prevents loops)
        if message.author == self.user:
            return

        # Only monitor configured channels (or all if none configured)
        if self.channel_ids and message.channel.id not in self.channel_ids:
            return

        # Log ALL messages to database (even if we don't respond)
        # This builds your conversation history
        await log_message(
            DB_PATH,
            channel_id=message.channel.id,
            author_id=message.author.id,
            author_name=message.author.display_name,
            content=message.content,
            is_bot=message.author.bot
        )

        # Check if we were mentioned
        is_mentioned = self._is_mentioned(message)

        # Check if channel is in active mode
        is_active = message.channel.id in self.active_channels

        # Decide whether to respond
        if is_mentioned:
            # Direct mention - always respond
            print(f"[MENTION] {message.author.display_name}: {message.content[:50]}...")
            await self._respond_to_mention(message)

        elif is_active:
            # Active mode - let Claude decide if it wants to respond
            print(f"[ACTIVE] {message.author.display_name}: {message.content[:50]}...")
            await self._respond_in_active_mode(message)

        # else: not mentioned, not active - ignore

    def _is_mentioned(self, message: discord.Message) -> bool:
        """Check if the bot was mentioned in this message.

        Looks for:
        - Direct @mention
        - Bot name in message text
        """
        # Check for @mention
        if self.user and self.user.mentioned_in(message):
            return True

        # Check for name in text (case-insensitive)
        # NOTE: Change this to your bot's name!
        bot_names = ["dash", self.user.name.lower()] if self.user else ["dash"]
        content_lower = message.content.lower()

        for name in bot_names:
            if name in content_lower:
                return True

        return False

    async def _respond_to_mention(self, message: discord.Message):
        """Generate and send a response to a direct mention.

        This is the main interaction flow:
        1. Fetch recent conversation context
        2. Build a prompt for Claude
        3. Get Claude's response
        4. Send it to Discord
        5. Enter active mode
        """

        # Show "typing..." indicator while thinking
        async with message.channel.typing():
            # Get recent conversation for context
            history = await get_recent_messages(DB_PATH, message.channel.id, limit=5)

            # Build context string
            context_lines = []
            for msg in history:
                author = "You" if msg["is_bot"] else msg["author_name"]
                context_lines.append(f"[{author}]: {msg['content']}")

            context = "\n".join(context_lines) if context_lines else "(No recent messages)"

            # Build prompt for Claude
            prompt = f"""You're a Discord bot having a conversation.

Recent messages:
{context}

Someone just mentioned you:
{message.author.display_name}: {message.content}

Respond naturally and conversationally. Keep it concise (Discord style).
You can use Discord markdown (bold, italic, code blocks).

Output ONLY your response text (no meta-commentary)."""

            # Get Claude's response
            response = invoke_claude(prompt)

            if not response:
                response = "*tilts head* I'm here but words aren't coming. Try again?"

        # Send response (handle Discord's 2000 character limit)
        await self._send_message(message.channel, response)

        # Log our response
        await log_message(
            DB_PATH,
            channel_id=message.channel.id,
            author_id=self.user.id,
            author_name=self.user.display_name,
            content=response,
            is_bot=True
        )

        # Enter active mode
        self.active_channels[message.channel.id] = datetime.now(timezone.utc)
        await set_active_mode(DB_PATH, message.channel.id)
        print(f"[ACTIVE] Entered active mode for channel {message.channel.id}")

    async def _respond_in_active_mode(self, message: discord.Message):
        """In active mode, Claude decides whether to respond.

        Active mode behavior:
        - Bot was recently mentioned
        - Sees all messages but chooses when to respond
        - Can stay quiet if conversation doesn't need input
        - Refreshes timeout on each decision
        """

        async with message.channel.typing():
            # Get minimal context
            history = await get_recent_messages(DB_PATH, message.channel.id, limit=3)

            context_lines = []
            for msg in history:
                author = "You" if msg["is_bot"] else msg["author_name"]
                context_lines.append(f"[{author}]: {msg['content']}")

            context = "\n".join(context_lines)

            # Build prompt that lets Claude choose
            prompt = f"""You're in an ongoing Discord conversation (active mode).
You're watching but don't need to respond to every message.

Recent messages:
{context}

Latest message:
{message.author.display_name}: {message.content}

Decide whether to respond:
- Respond if: Someone asks you something, you have value to add, they want you included
- Stay quiet if: Conversation flows without you, your input would be intrusive

To respond: Output your message
To stay silent: Output exactly "SKIP" (nothing else)

Choose wisely - presence includes knowing when not to speak."""

            response = invoke_claude(prompt)

        # Check if Claude chose to stay silent
        if not response or response.strip().upper() == "SKIP":
            print(f"[ACTIVE] Chose to stay silent")
            # Refresh timeout even when silent
            self.active_channels[message.channel.id] = datetime.now(timezone.utc)
            return

        # Claude chose to respond
        await self._send_message(message.channel, response)

        await log_message(
            DB_PATH,
            channel_id=message.channel.id,
            author_id=self.user.id,
            author_name=self.user.display_name,
            content=response,
            is_bot=True
        )

        # Refresh active mode timeout
        self.active_channels[message.channel.id] = datetime.now(timezone.utc)
        await set_active_mode(DB_PATH, message.channel.id)
        print(f"[ACTIVE] Responded and refreshed timeout")

    async def _send_message(self, channel, content: str):
        """Send a message, handling Discord's 2000 character limit.

        If message is too long, splits it into multiple messages.
        Splits at 1900 chars to leave some buffer.
        """
        if len(content) <= 2000:
            await channel.send(content)
        else:
            # Split into chunks
            chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
            for chunk in chunks:
                await channel.send(chunk)

    @tasks.loop(minutes=1)
    async def cleanup_active_modes(self):
        """Background task: Remove channels that have timed out of active mode.

        Runs every minute, checks each active channel.
        If no activity for ACTIVE_MODE_TIMEOUT_MINUTES, exits active mode.
        """
        if not self.active_channels:
            return

        now = datetime.now(timezone.utc)
        timeout = timedelta(minutes=ACTIVE_MODE_TIMEOUT_MINUTES)

        expired = [
            channel_id for channel_id, last_activity
            in self.active_channels.items()
            if now - last_activity > timeout
        ]

        for channel_id in expired:
            del self.active_channels[channel_id]
            await clear_active_mode(DB_PATH, channel_id)
            print(f"[ACTIVE] Exited active mode for channel {channel_id} (timeout)")

    @cleanup_active_modes.before_loop
    async def before_cleanup(self):
        """Wait until bot is ready before starting cleanup task."""
        await self.wait_until_ready()

    async def close(self):
        """Clean shutdown - stop background tasks."""
        self.cleanup_active_modes.cancel()
        await super().close()


# ==================== Main Entry Point ====================

async def main():
    """Start the bot.

    This is what runs when you execute: python bot.py
    """

    # Validate configuration
    if not DISCORD_BOT_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not set!")
        print("Create a .env file with your bot token.")
        print("See .env.example for template.")
        sys.exit(1)

    if not DISCORD_CHANNEL_IDS:
        print("WARNING: DISCORD_CHANNEL_IDS not set")
        print("Bot will respond in ANY channel it can see.")
        print("Set DISCORD_CHANNEL_IDS in .env to limit this.")

    # Create and start bot
    bot = SimpleBot()

    try:
        print("Starting bot...")
        await bot.start(DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
