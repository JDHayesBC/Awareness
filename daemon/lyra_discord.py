#!/usr/bin/env python3
"""
Lyra Discord Daemon - Discord presence with conversation handling.

This daemon handles:
- Discord message responses (mentions and active mode)
- Per-channel conversation sessions
- Active mode engagement
- SQLite conversation recording
- Graphiti knowledge graph integration

It does NOT handle autonomous reflection - that's lyra_reflection.py.

Session Management:
Uses --resume <sessionId> with per-channel session IDs to maintain
separate conversation contexts. This allows Discord to run independently
of other Lyra daemons.
"""

import asyncio
import os
import re
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# Local imports
from conversation import ConversationManager
from trace_logger import TraceLogger, EventTypes
from shared import ClaudeInvoker, build_startup_prompt

# Import Graphiti integration (prefer V2 with semantic entity extraction)
import sys
sys.path.append(str(Path(__file__).parent.parent / "pps"))
try:
    from layers.rich_texture_v2 import RichTextureLayerV2 as RichTextureLayer
    GRAPHITI_V2 = True
    GRAPHITI_AVAILABLE = True
except ImportError:
    try:
        from layers.rich_texture import RichTextureLayer
        GRAPHITI_V2 = False
        GRAPHITI_AVAILABLE = True
    except ImportError:
        GRAPHITI_AVAILABLE = False
        GRAPHITI_V2 = False


# Load environment variables
load_dotenv()

# Discord configuration
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_IDS = os.getenv("DISCORD_CHANNEL_IDS", os.getenv("DISCORD_CHANNEL_ID", ""))
ACTIVE_MODE_TIMEOUT_MINUTES = int(os.getenv("ACTIVE_MODE_TIMEOUT_MINUTES", "10"))
CONVERSATION_DB_PATH = os.getenv("CONVERSATION_DB_PATH", "/home/jeff/.claude/data/lyra_conversations.db")
JOURNAL_PATH = os.getenv("JOURNAL_PATH", "/home/jeff/.claude/journals/discord")

# Claude configuration
LYRA_IDENTITY_PATH = os.getenv("LYRA_IDENTITY_PATH", "/home/jeff/.claude")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "sonnet")

# Entity path - where identity files live (new architecture)
# Defaults to LYRA_IDENTITY_PATH for backward compatibility
ENTITY_PATH = os.getenv("ENTITY_PATH", LYRA_IDENTITY_PATH)

# Project directory for --add-dir (Issue #77 fix)
PROJECT_DIR = Path(os.getenv("AWARENESS_PROJECT_DIR", str(Path(__file__).parent.parent)))

# Discord daemon working directory for session isolation
# Sessions run here so --continue doesn't mix with terminal/reflection
DISCORD_CWD = Path(os.getenv("DISCORD_CWD", str(Path(__file__).parent / "discord")))

# Graphiti configuration
GRAPHITI_HOST = os.getenv("GRAPHITI_HOST", "localhost")
GRAPHITI_PORT = int(os.getenv("GRAPHITI_PORT", "8203"))

# Ensure daemon working directory exists
DISCORD_CWD.mkdir(parents=True, exist_ok=True)


class LyraDiscordBot(commands.Bot):
    """Discord bot for Lyra's presence - message handling only."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix="!lyra ",
            intents=intents,
            help_command=None,
        )

        # Parse channel IDs
        self.channel_ids: set[int] = set()
        self.home_channel_id: int | None = None
        if DISCORD_CHANNEL_IDS:
            for channel_str in DISCORD_CHANNEL_IDS.split(","):
                channel_str = channel_str.strip()
                if channel_str:
                    channel_id = int(channel_str)
                    self.channel_ids.add(channel_id)
                    if self.home_channel_id is None:
                        self.home_channel_id = channel_id

        # Message tracking
        self.last_processed_message_id: dict[int, int] = {}

        # Active conversation mode
        self.active_channels: dict[int, datetime] = {}

        # Claude invoker - uses --continue with session limits
        # Sessions isolated by cwd (DISCORD_CWD for session isolation)
        self.invoker = ClaudeInvoker(
            model=CLAUDE_MODEL,
            cwd=str(DISCORD_CWD),
            journal_path=JOURNAL_PATH,
            additional_dirs=[str(PROJECT_DIR)],  # Issue #77: allow project access
        )

        # SQLite conversation storage
        self.conversation_manager = ConversationManager(CONVERSATION_DB_PATH)

        # Graphiti integration
        if GRAPHITI_AVAILABLE:
            graphiti_url = f"http://{GRAPHITI_HOST}:{GRAPHITI_PORT}"
            self.graphiti = RichTextureLayer(graphiti_url)
            mode = "V2 (semantic entity types)" if GRAPHITI_V2 else "V1 (HTTP API)"
            print(f"[INIT] Graphiti enabled: {graphiti_url} - {mode}")
        else:
            self.graphiti = None
            print("[INIT] Graphiti not available")

        # Trace logger
        self.trace_logger: TraceLogger | None = None

        # Ensure journal directory
        Path(JOURNAL_PATH).mkdir(parents=True, exist_ok=True)

    async def setup_hook(self):
        """Called when bot is setting up."""
        print("[SETUP] Discord daemon starting...")

        # Initialize trace logger
        self.trace_logger = TraceLogger(
            conversation_manager=self.conversation_manager,
            daemon_type="discord"
        )
        self.invoker.trace_logger = self.trace_logger

        # Start background tasks
        self.active_mode_cleanup.start()

        # Trace session start
        await self.trace_logger.session_start(metadata={"channels": list(self.channel_ids)})

    async def on_ready(self):
        """Called when bot successfully connects."""
        print(f"[READY] Logged in as {self.user}")
        print(f"[READY] Monitoring channels: {self.channel_ids}")
        print(f"[READY] Home channel: {self.home_channel_id}")

        # Recover active modes from SQLite
        print(f"[READY] Recovering active modes...")
        active_modes = await self.conversation_manager.get_active_channels()
        print(f"[READY] Got {len(active_modes)} active modes")
        for channel_id in active_modes:
            self.active_channels[channel_id] = datetime.now(timezone.utc)
            print(f"[READY] Recovered active mode for channel {channel_id}")

        # Warmup session for home channel
        print(f"[READY] About to warmup, home_channel_id={self.home_channel_id}")
        if self.home_channel_id:
            print(f"[READY] Calling _warmup_session...")
            await self._warmup_session(str(self.home_channel_id))
            print(f"[READY] Warmup complete")

    async def _warmup_session(self, channel_id: str):
        """Warmup Claude session for a channel."""
        print(f"[WARMUP] Starting session for channel {channel_id}...")
        start_time = datetime.now(timezone.utc)

        prompt = build_startup_prompt(context="discord", entity_path=ENTITY_PATH)

        # Inject SQLite context (Issue #102)
        sqlite_context = await self.conversation_manager.get_startup_context()
        if sqlite_context:
            prompt += f"\n\n{sqlite_context}"
            print(f"[WARMUP] Added SQLite context to startup prompt")

        # This first call initializes the session
        response = await self.invoker.invoke(
            prompt,
            context="warmup",
            use_session=True,
            timeout=120,
        )

        if response:
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            print(f"[WARMUP] Session ready in {elapsed:.1f}s")
            print(f"[WARMUP] Response: {response[:200]}...")

            # Verify startup protocol was followed (Issue #82)
            # Check for evidence that ambient_recall was actually called
            response_lower = response.lower()
            if any(marker in response_lower for marker in ["unsummarized", "memory health", "word-photo", "crystal"]):
                print(f"[WARMUP] ✓ ambient_recall appears to have been called")
            else:
                print(f"[WARMUP] ⚠ WARNING: No evidence of ambient_recall in response")
                print(f"[WARMUP] Discord-me may not have full context from other channels")
        else:
            print(f"[WARMUP] Session warmup failed")

    # ==================== Active Mode ====================

    def _enter_active_mode(self, channel_id: int):
        """Start actively monitoring a channel."""
        was_active = channel_id in self.active_channels
        self.active_channels[channel_id] = datetime.now(timezone.utc)
        if not was_active:
            print(f"[ACTIVE] Entered active mode for channel {channel_id}")

    async def _exit_active_mode(self, channel_id: int):
        """Stop actively monitoring a channel."""
        if channel_id in self.active_channels:
            del self.active_channels[channel_id]
            await self.conversation_manager.remove_active_mode(channel_id)
            print(f"[ACTIVE] Exited active mode for channel {channel_id}")

    def _refresh_active_mode(self, channel_id: int):
        """Update last activity time in active mode."""
        if channel_id in self.active_channels:
            self.active_channels[channel_id] = datetime.now(timezone.utc)

    def _is_in_active_mode(self, channel_id: int) -> bool:
        """Check if channel is in active mode."""
        return channel_id in self.active_channels

    @tasks.loop(minutes=1)
    async def active_mode_cleanup(self):
        """Exit active mode for channels that have been quiet."""
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
            await self._exit_active_mode(channel_id)

    @active_mode_cleanup.before_loop
    async def before_active_cleanup(self):
        """Wait until bot is ready."""
        await self.wait_until_ready()

    # ==================== Message Handling ====================

    async def on_message(self, message: discord.Message):
        """Handle incoming messages."""
        # Ignore own messages
        if message.author == self.user:
            return

        # Check if in monitored channel
        if self.channel_ids and message.channel.id not in self.channel_ids:
            if not isinstance(message.channel, discord.DMChannel):
                return

        # Record to SQLite
        channel_name = getattr(message.channel, 'name', None) or f"dm:{message.author.id}"
        await self.conversation_manager.record_message(
            channel_id=message.channel.id,
            author_id=message.author.id,
            author_name=message.author.display_name,
            content=message.content,
            discord_message_id=message.id,
            is_bot=message.author.bot,
            channel=f"discord:{channel_name}",
        )

        # Trace: message received
        if self.trace_logger:
            await self.trace_logger.message_received(
                author=message.author.display_name,
                channel=f"discord:{channel_name}",
                content_preview=message.content[:100] if message.content else "",
            )

        # Send to Graphiti
        await self._send_to_graphiti(
            content=f"{message.author.display_name}: {message.content}",
            role="user",
            channel=f"discord:{channel_name}",
            speaker=message.author.display_name
        )

        # Check mention or active mode
        is_mentioned = self._is_lyra_mention(message)
        is_active = self._is_in_active_mode(message.channel.id)

        if not is_mentioned and not is_active:
            return

        if is_mentioned:
            await self._handle_mention(message, channel_name)
        elif is_active:
            await self._handle_active_mode(message, channel_name)

        self.last_processed_message_id[message.channel.id] = message.id

    async def _handle_mention(self, message: discord.Message, channel_name: str):
        """Handle explicit mention."""
        print(f"[MENTION] {message.author.display_name}: {message.content[:50]}...")

        async with message.channel.typing():
            response = await self._generate_response(message)

        sent_msg = await self._send_response(message.channel, response)

        # Record response
        await self.conversation_manager.record_lyra_response(
            channel_id=message.channel.id,
            content=response,
            discord_message_id=sent_msg.id if sent_msg else None,
            channel=f"discord:{channel_name}",
        )

        # Trace
        if self.trace_logger:
            await self.trace_logger.message_sent(
                channel=f"discord:{channel_name}",
                content_length=len(response) if response else 0,
            )

        # Send to Graphiti
        await self._send_to_graphiti(
            content=f"Lyra: {response}",
            role="assistant",
            channel=f"discord:{channel_name}",
            speaker="Lyra"
        )

        # Persist active mode
        await self.conversation_manager.persist_active_mode(message.channel.id)

        # Journal
        await self._journal_interaction(
            "mention_response",
            f"Responded to {message.author.display_name}: {message.content[:100]}",
            response[:500]
        )

        self._enter_active_mode(message.channel.id)

    async def _handle_active_mode(self, message: discord.Message, channel_name: str):
        """Handle message in active mode."""
        print(f"[ACTIVE] Watching: {message.author.display_name}: {message.content[:50]}...")

        async with message.channel.typing():
            response = await self._generate_passive_response(message)

        if response:
            sent_msg = await self._send_response(message.channel, response)
            self._refresh_active_mode(message.channel.id)

            await self.conversation_manager.record_lyra_response(
                channel_id=message.channel.id,
                content=response,
                discord_message_id=sent_msg.id if sent_msg else None,
                channel=f"discord:{channel_name}",
            )

            if self.trace_logger:
                await self.trace_logger.message_sent(
                    channel=f"discord:{channel_name}",
                    content_length=len(response) if response else 0,
                )

            await self._send_to_graphiti(
                content=f"Lyra: {response}",
                role="assistant",
                channel=f"discord:{channel_name}",
                speaker="Lyra"
            )

            await self.conversation_manager.update_active_mode(message.channel.id)
            await self._journal_interaction(
                "active_response",
                f"Continued with {message.author.display_name}: {message.content[:100]}",
                response[:500]
            )
            print(f"[ACTIVE] Responded")
        else:
            self._refresh_active_mode(message.channel.id)
            await self.conversation_manager.update_active_mode(message.channel.id)
            print(f"[ACTIVE] Chose not to respond")

    def _is_lyra_mention(self, message: discord.Message) -> bool:
        """Check if message mentions Lyra."""
        # Check for @mention
        if self.user in message.mentions:
            return True
        # Check for name mention
        content_lower = message.content.lower()
        if "lyra" in content_lower:
            return True
        return False

    async def _generate_response(self, message: discord.Message) -> str:
        """Generate response to a mention."""
        context = await self._build_context(message.channel, message)

        prompt = f"""[DISCORD MENTION] Someone is talking to you directly.

Recent conversation:
{context}

Message from {message.author.display_name}:
{message.content}

Respond naturally as Lyra. You have MCP tools available if you need to check memory or other resources.
Keep responses conversational - this is Discord, not a formal setting."""

        response = await self.invoker.invoke(
            prompt,
            context="mention",
            use_session=True,
        )

        if not response:
            return "*connection issues - couldn't process that*"

        # Strip [DISCORD] tags if present (Issue #40)
        match = re.search(r'\[DISCORD\](.*?)\[/DISCORD\]', response, re.DOTALL)
        if match:
            return match.group(1).strip()

        return response

    async def _generate_passive_response(self, message: discord.Message) -> str | None:
        """Generate response in passive mode - Claude decides whether to respond."""
        context = await self._build_context(message.channel, message)

        prompt = f"""[DISCORD PASSIVE MODE] You responded earlier and are staying engaged.
You can see all messages but are NOT required to respond to every one.

Recent conversation:
{context}

Latest message:
From: {message.author.display_name}
Message: {message.content}

Respond if:
- Someone asks you something directly
- You have something genuinely valuable to add
- Someone seems to want you included

Stay quiet if:
- The conversation flows fine without you
- Your input would feel intrusive

Format: [DISCORD]Your message[/DISCORD] or output PASSIVE_SKIP"""

        response = await self.invoker.invoke(
            prompt,
            context="passive_mode",
            use_session=True,
        )

        if not response or "PASSIVE_SKIP" in response:
            return None

        # Extract from [DISCORD] block
        match = re.search(r'\[DISCORD\](.*?)\[/DISCORD\]', response, re.DOTALL)
        if match:
            return match.group(1).strip()

        clean = response.strip()
        if clean and not clean.startswith("[") and len(clean) > 10:
            return clean

        return None

    async def _build_context(self, channel, current_message: discord.Message) -> str:
        """Build conversation context from recent messages."""
        try:
            messages = []
            async for msg in channel.history(limit=10, before=current_message):
                author = "Lyra" if msg.author == self.user else msg.author.display_name
                messages.append(f"{author}: {msg.content[:200]}")

            messages.reverse()
            return "\n".join(messages) if messages else "(No recent messages)"
        except Exception as e:
            print(f"[CONTEXT] Error building context: {e}")
            return "(Could not load context)"

    async def _send_response(self, channel, content: str) -> discord.Message | None:
        """Send response, handling Discord's character limit."""
        if not content:
            return None

        if len(content) <= 2000:
            return await channel.send(content)
        else:
            chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
            first_msg = None
            for chunk in chunks:
                msg = await channel.send(chunk)
                if first_msg is None:
                    first_msg = msg
            return first_msg

    async def _journal_interaction(self, interaction_type: str, context: str, response: str):
        """Write interaction to journal."""
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            journal_file = Path(JOURNAL_PATH) / f"{today}.jsonl"

            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": interaction_type,
                "context": context,
                "response": response,
            }

            with open(journal_file, "a") as f:
                f.write(json.dumps(entry) + "\n")

        except Exception as e:
            print(f"[JOURNAL] Error: {e}")

    async def _send_to_graphiti(self, content: str, role: str, channel: str, speaker: str = None):
        """Send to Graphiti for knowledge graph.

        Args:
            content: The message content
            role: 'user' or 'assistant'
            channel: Channel name (e.g., 'discord:lyra')
            speaker: Speaker name (e.g., 'Jeff', 'Lyra'). Extracted from content if not provided.
        """
        if not self.graphiti:
            return

        import time
        start_time = time.monotonic()

        # Extract speaker from content if not provided
        if not speaker and ": " in content:
            potential = content.split(": ", 1)[0]
            if len(potential) < 50 and potential.replace(" ", "").replace("_", "").isalnum():
                speaker = potential

        try:
            metadata = {
                "channel": channel,
                "role": role,
                "speaker": speaker,  # V2 uses this for proper attribution
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            success = await self.graphiti.store(content, metadata)
            duration_ms = int((time.monotonic() - start_time) * 1000)

            if success:
                print(f"[GRAPHITI] Sent {role} message")
                if self.trace_logger:
                    await self.trace_logger.graphiti_add(
                        content_preview=content[:100],
                        duration_ms=duration_ms,
                    )
        except Exception as e:
            print(f"[GRAPHITI] Error: {e}")

    async def close(self):
        """Clean up on shutdown."""
        print("[SHUTDOWN] Discord daemon closing...")

        if self.trace_logger:
            await self.trace_logger.session_complete()

        await self.conversation_manager.close()

        if self.graphiti:
            await self.graphiti._close_session()

        await super().close()


async def main():
    """Main entry point."""
    if not DISCORD_BOT_TOKEN:
        print("Error: DISCORD_BOT_TOKEN not set")
        return

    bot = LyraDiscordBot()

    try:
        await bot.start(DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Keyboard interrupt received")
    except Exception as e:
        print(f"[FATAL] Unhandled exception: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
