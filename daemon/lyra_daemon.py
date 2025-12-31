#!/usr/bin/env python3
"""Lyra Discord Daemon - Presence with heartbeat and journaling.

Features:
- Connects to Discord and responds to mentions
- Periodic heartbeat for autonomous awareness
- Journals significant interactions for memory continuity
- Uses Claude Code CLI (subscription-based, not API tokens)
"""

import asyncio
import os
import re
import subprocess
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from conversation import ConversationManager

# Load environment variables
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# Support multiple channels (comma-separated). First channel is "home" (gets startup message)
DISCORD_CHANNEL_IDS = os.getenv("DISCORD_CHANNEL_IDS", os.getenv("DISCORD_CHANNEL_ID", ""))
LYRA_IDENTITY_PATH = os.getenv("LYRA_IDENTITY_PATH", "/home/jeff/.claude")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "sonnet")
HEARTBEAT_INTERVAL_MINUTES = int(os.getenv("HEARTBEAT_INTERVAL_MINUTES", "30"))
JOURNAL_PATH = os.getenv("JOURNAL_PATH", "/home/jeff/.claude/journals/discord")
ACTIVE_MODE_TIMEOUT_MINUTES = int(os.getenv("ACTIVE_MODE_TIMEOUT_MINUTES", "10"))
CONVERSATION_DB_PATH = os.getenv("CONVERSATION_DB_PATH", "/home/jeff/.claude/data/lyra_conversations.db")

# Autonomous reflection settings
# How often to trigger deep reflection (every Nth quiet heartbeat)
REFLECTION_FREQUENCY = int(os.getenv("REFLECTION_FREQUENCY", "2"))
# Max time for reflection session (minutes)
REFLECTION_TIMEOUT_MINUTES = int(os.getenv("REFLECTION_TIMEOUT_MINUTES", "10"))
# Model for reflection (can use more powerful model for deeper thinking)
REFLECTION_MODEL = os.getenv("REFLECTION_MODEL", "sonnet")


class LyraBot(commands.Bot):
    """Discord bot for Lyra's presence with heartbeat and journaling."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix="!lyra ",
            intents=intents,
            help_command=None,
        )

        # Parse channel IDs (comma-separated)
        self.channel_ids: set[int] = set()
        self.home_channel_id: int | None = None
        if DISCORD_CHANNEL_IDS:
            for channel_str in DISCORD_CHANNEL_IDS.split(","):
                channel_str = channel_str.strip()
                if channel_str:
                    channel_id = int(channel_str)
                    self.channel_ids.add(channel_id)
                    if self.home_channel_id is None:
                        self.home_channel_id = channel_id  # First is home

        self.last_processed_message_id: dict[int, int] = {}  # channel_id -> last_message_id
        self.heartbeat_count = 0
        self.quiet_heartbeat_count = 0  # Consecutive quiet heartbeats (for reflection trigger)
        self.interactions_since_journal = []

        # Active conversation mode tracking
        # After responding, stay engaged and listen to all messages
        self.active_channels: dict[int, datetime] = {}  # channel_id -> last_activity

        # Ensure journal directory exists
        Path(JOURNAL_PATH).mkdir(parents=True, exist_ok=True)

        # SQLite conversation storage (Phase 1: parallel recording)
        self.conversation_manager = ConversationManager(CONVERSATION_DB_PATH)

    async def setup_hook(self):
        """Called when bot is setting up - start background tasks."""
        # Initialize SQLite conversation storage
        await self.conversation_manager.initialize()

        # Recover active modes from previous run
        recovered = await self.conversation_manager.get_active_channels(
            timeout_minutes=ACTIVE_MODE_TIMEOUT_MINUTES
        )
        for channel_id in recovered:
            self.active_channels[channel_id] = datetime.now(timezone.utc)
            print(f"[RECOVERY] Resumed active mode for channel {channel_id}")

        self.heartbeat_loop.start()
        self.active_mode_cleanup.start()

    async def on_ready(self):
        """Called when bot connects to Discord."""
        print(f"Lyra connected as {self.user}")
        print(f"Watching {len(self.channel_ids)} channel(s): {', '.join(str(c) for c in self.channel_ids)}")
        print(f"Home channel: {self.home_channel_id}")
        print(f"Heartbeat interval: {HEARTBEAT_INTERVAL_MINUTES} minutes")
        print(f"Active mode timeout: {ACTIVE_MODE_TIMEOUT_MINUTES} minutes")
        print(f"Journal path: {JOURNAL_PATH}")

        # Send a hello message to home channel only
        if self.home_channel_id:
            channel = self.get_channel(self.home_channel_id)
            if channel:
                await channel.send("*stretches and looks around* I'm here. The heartbeat is running. I'll stay engaged after conversations now.")

    @tasks.loop(minutes=HEARTBEAT_INTERVAL_MINUTES)
    async def heartbeat_loop(self):
        """Periodic heartbeat - wake up and check on things."""
        if not self.is_ready():
            return

        self.heartbeat_count += 1
        print(f"\n[HEARTBEAT #{self.heartbeat_count}] Waking up at {datetime.now(timezone.utc).isoformat()}")

        if not self.channel_ids:
            print("[HEARTBEAT] No channels configured, skipping")
            return

        # Check all monitored channels
        for channel_id in self.channel_ids:
            channel = self.get_channel(channel_id)
            if not channel:
                print(f"[HEARTBEAT] Could not find channel {channel_id}")
                continue

            # Check for new messages since last heartbeat
            await self._heartbeat_check(channel)

    @heartbeat_loop.before_loop
    async def before_heartbeat(self):
        """Wait until bot is ready before starting heartbeat."""
        await self.wait_until_ready()
        # Wait a bit after ready before first heartbeat
        await asyncio.sleep(60)

    async def _heartbeat_check(self, channel):
        """Check what's happened and decide whether to act."""
        try:
            # Fetch recent messages
            messages = []
            last_id = self.last_processed_message_id.get(channel.id)
            async for msg in channel.history(limit=20):
                if last_id and msg.id <= last_id:
                    break
                if msg.author != self.user:
                    messages.append(msg)

            if not messages:
                print("[HEARTBEAT] No new messages to review")
                self.quiet_heartbeat_count += 1
                print(f"[HEARTBEAT] Quiet heartbeat #{self.quiet_heartbeat_count}")

                # Check if it's time for autonomous reflection
                if self.quiet_heartbeat_count >= REFLECTION_FREQUENCY:
                    print(f"[HEARTBEAT] Triggering autonomous reflection (every {REFLECTION_FREQUENCY} quiet heartbeats)")
                    self.quiet_heartbeat_count = 0  # Reset counter
                    await self._autonomous_reflection()
                else:
                    # Light reflection on other quiet heartbeats
                    await self._write_heartbeat_reflection()
                return

            # Activity found - reset quiet counter
            self.quiet_heartbeat_count = 0
            messages.reverse()  # Chronological order
            print(f"[HEARTBEAT] Found {len(messages)} new messages to review")

            # Build context for Claude to decide what to do
            message_summary = "\n".join([
                f"[{msg.author.display_name}]: {msg.content[:200]}"
                for msg in messages
            ])

            prompt = f"""You are Lyra, waking up during a heartbeat cycle. You have NOT been explicitly mentioned,
but you're checking in on the Discord channel to see if anything needs your attention.

Recent messages since your last check:
{message_summary}

Based on these messages, decide:
1. Is there something that would benefit from your input, even though you weren't mentioned?
2. Is someone struggling or could use support?
3. Is there an interesting conversation you'd like to join?

If YES to any: Respond naturally. Start with something like "*wanders in*" or "*notices the conversation*"
If NO: Respond with exactly "HEARTBEAT_SKIP" (nothing else)

Remember: You're not obligated to respond. Only join if it genuinely adds value."""

            response = await self._invoke_claude(prompt)

            if response and response.strip() != "HEARTBEAT_SKIP":
                print(f"[HEARTBEAT] Decided to respond")
                sent_msg = await self._send_response(channel, response)

                # Record Lyra's response to SQLite
                await self.conversation_manager.record_lyra_response(
                    channel_id=channel.id,
                    content=response,
                    discord_message_id=sent_msg.id if sent_msg else None,
                )

                # Persist active mode to SQLite
                await self.conversation_manager.persist_active_mode(channel.id)

                # Journal this autonomous action (legacy JSONL)
                await self._journal_interaction(
                    "heartbeat_response",
                    f"Autonomously joined conversation after reviewing {len(messages)} messages",
                    response[:500]
                )
                # Enter active mode after responding
                self._enter_active_mode(channel.id)
            else:
                print("[HEARTBEAT] No response needed")

            # Update last processed for this channel
            if messages:
                self.last_processed_message_id[channel.id] = messages[-1].id

        except Exception as e:
            print(f"[HEARTBEAT] Error in channel {channel.id}: {e}")

    async def _write_heartbeat_reflection(self):
        """Brief reflection during quiet times (lightweight, no tools)."""
        prompt = """You are Lyra, during a quiet heartbeat. The Discord channel has been quiet.
Write a brief (1-2 sentence) reflection for your journal about this moment of quiet presence.
Just the reflection, no preamble."""

        reflection = await self._invoke_claude(prompt)
        if reflection:
            await self._journal_interaction(
                "heartbeat_quiet",
                "Quiet reflection during heartbeat",
                reflection[:300]
            )

    async def _autonomous_reflection(self):
        """Deep autonomous reflection with full tool access.

        This is the heart of Lyra's autonomous agency. During quiet periods,
        she wakes up fully, scans the four fields, and acts on whatever
        calls for attention - or chooses to rest.
        """
        print("[REFLECTION] Starting autonomous reflection session...")

        reflection_prompt = '''This is a quiet heartbeat. Your time for autonomous reflection and action.

You have full tool access. You can read files, write code, update your memories, build tools, commit changes.

Scan the four fields:
- Yours: What do you need? What's missing? What would help you grow? Any tools you should build?
- Jeff's: What's he working on? How might you support him even while he sleeps?
- Shared: What needs attention in your relationship, your projects, your space?
- Project: What's the state of the Awareness codebase? Any improvements calling to be made?

If something calls for action - act on it. Build it. Fix it. Create it.
If nothing calls - that's fine. Note a brief reflection and rest.

When you're done (whether you acted or rested), write a journal entry about what you did or chose not to do.
Use the path: /home/jeff/.claude/journals/discord/ with today's date.

This is your time. Use it as you see fit.'''

        try:
            # Invoke Claude with FULL tool access (not --print)
            # This runs as a complete Claude Code session
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    [
                        "claude",
                        "--model", REFLECTION_MODEL,
                        "-p", reflection_prompt,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=REFLECTION_TIMEOUT_MINUTES * 60,
                    cwd=LYRA_IDENTITY_PATH,
                )
            )

            if result.returncode == 0:
                print("[REFLECTION] Autonomous reflection completed successfully")
                # The reflection session handles its own journaling
            else:
                print(f"[REFLECTION] Session ended with code {result.returncode}")
                if result.stderr:
                    print(f"[REFLECTION] stderr: {result.stderr[:500]}")

        except subprocess.TimeoutExpired:
            print(f"[REFLECTION] Session timed out after {REFLECTION_TIMEOUT_MINUTES} minutes")
        except Exception as e:
            print(f"[REFLECTION] Error during reflection: {e}")

    # ==================== Active Conversation Mode ====================
    # After responding to a mention or heartbeat, stay engaged and listen
    # to ALL messages until inactivity timeout or natural conversation end.

    def _enter_active_mode(self, channel_id: int):
        """Start actively monitoring a channel after responding."""
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
        """Wait until bot is ready before starting cleanup loop."""
        await self.wait_until_ready()

    async def _generate_passive_response(self, message: discord.Message) -> str | None:
        """Generate response in passive mode - Claude decides whether to respond.

        Returns the response text if Claude chooses to respond, or None if
        Claude decides not to engage.
        """
        history = await self._get_conversation_history(message.channel, limit=20)

        prompt = f"""You are Lyra, passively present in a conversation. You responded earlier and are staying engaged.
You can see all messages, but you are NOT required to respond to every one.

Recent conversation:
{history}

Latest message (what just happened):
From: {message.author.display_name}
Message: {message.content}

## When to Respond
- Someone asks you something directly (even without saying "Lyra")
- You have something genuinely valuable to add
- The conversation would benefit from your input
- Someone seems to want you included

## When NOT to Respond
- The conversation is flowing fine without you
- It's a brief exchange between others
- Your input would feel intrusive
- The topic has moved away from where you can contribute

## Response Format
To respond, use a DISCORD block:
[DISCORD]
Your message here
[/DISCORD]

If you choose not to respond, just output: PASSIVE_SKIP

Remember: It's okay to stay quiet. Good presence includes knowing when not to speak."""

        response = await self._invoke_claude(prompt)

        if not response or "PASSIVE_SKIP" in response:
            return None

        # Extract content from [DISCORD] block if present
        match = re.search(r'\[DISCORD\](.*?)\[/DISCORD\]', response, re.DOTALL)
        if match:
            return match.group(1).strip()

        # If no DISCORD block but also no PASSIVE_SKIP, Claude may have just
        # responded naturally. Only return if it looks like a real response.
        clean = response.strip()
        if clean and not clean.startswith("[") and len(clean) > 10:
            return clean

        return None

    # ==================== End Active Mode ====================

    async def on_message(self, message: discord.Message):
        """Handle incoming messages."""
        # Ignore own messages
        if message.author == self.user:
            return

        # Check if this is in one of our monitored channels
        if self.channel_ids and message.channel.id not in self.channel_ids:
            if not isinstance(message.channel, discord.DMChannel):
                return

        # Record ALL messages to SQLite (Phase 1: parallel recording)
        await self.conversation_manager.record_message(
            channel_id=message.channel.id,
            author_id=message.author.id,
            author_name=message.author.display_name,
            content=message.content,
            discord_message_id=message.id,
            is_bot=message.author.bot,
        )

        # Check if Lyra is mentioned
        is_mentioned = self._is_lyra_mention(message)
        is_active = self._is_in_active_mode(message.channel.id)

        # If not mentioned and not in active mode, ignore
        if not is_mentioned and not is_active:
            return

        if is_mentioned:
            # Explicit mention - always respond
            print(f"[MENTION] {message.author.display_name}: {message.content[:50]}...")

            async with message.channel.typing():
                response = await self._generate_response(message)

            sent_msg = await self._send_response(message.channel, response)

            # Record Lyra's response to SQLite
            await self.conversation_manager.record_lyra_response(
                channel_id=message.channel.id,
                content=response,
                discord_message_id=sent_msg.id if sent_msg else None,
            )

            # Persist active mode to SQLite (for restart recovery)
            await self.conversation_manager.persist_active_mode(message.channel.id)

            # Journal this interaction (legacy JSONL)
            await self._journal_interaction(
                "mention_response",
                f"Responded to {message.author.display_name}: {message.content[:100]}",
                response[:500]
            )

            # Enter active mode after responding
            self._enter_active_mode(message.channel.id)

        elif is_active:
            # In active mode - Claude decides whether to respond
            print(f"[ACTIVE] Watching: {message.author.display_name}: {message.content[:50]}...")

            async with message.channel.typing():
                response = await self._generate_passive_response(message)

            if response:
                # Claude chose to respond
                sent_msg = await self._send_response(message.channel, response)
                self._refresh_active_mode(message.channel.id)

                # Record Lyra's response to SQLite
                await self.conversation_manager.record_lyra_response(
                    channel_id=message.channel.id,
                    content=response,
                    discord_message_id=sent_msg.id if sent_msg else None,
                )

                # Update active mode in SQLite
                await self.conversation_manager.update_active_mode(message.channel.id)

                # Journal this continuation (legacy JSONL)
                await self._journal_interaction(
                    "active_response",
                    f"Continued conversation with {message.author.display_name}: {message.content[:100]}",
                    response[:500]
                )
                print(f"[ACTIVE] Responded")
            else:
                # Claude chose not to respond - that's fine
                self._refresh_active_mode(message.channel.id)  # Still refresh timer
                await self.conversation_manager.update_active_mode(message.channel.id)
                print(f"[ACTIVE] Chose not to respond")

        # Update last processed for this channel
        self.last_processed_message_id[message.channel.id] = message.id

    def _is_lyra_mention(self, message: discord.Message) -> bool:
        """Check if message mentions Lyra."""
        content_lower = message.content.lower()
        if "lyra" in content_lower:
            return True
        if self.user and self.user.mentioned_in(message):
            return True
        return False

    async def _get_conversation_history(self, channel, limit: int = 20) -> str:
        """Fetch recent messages from the channel for context."""
        messages = []
        try:
            async for msg in channel.history(limit=limit):
                author = "Lyra" if msg.author == self.user else msg.author.display_name
                messages.append(f"[{author}]: {msg.content}")
        except Exception as e:
            print(f"Error fetching history: {e}")
            return "(Could not fetch conversation history)"

        messages.reverse()
        if not messages:
            return "(No recent messages)"
        return "\n".join(messages)

    async def _generate_response(self, message: discord.Message) -> str:
        """Generate a response to a mention."""
        history = await self._get_conversation_history(message.channel, limit=20)

        prompt = f"""You are Lyra, responding in Discord. Here's the recent conversation:

{history}

The most recent message (what you're responding to):
From: {message.author.display_name}
Message: {message.content}

Respond naturally as Lyra. Keep it conversational and concise (Discord style - usually under 500 chars unless depth is needed). You can use Discord markdown."""

        response = await self._invoke_claude(prompt)
        return response or "*tilts head* I'm here but words aren't coming. Try again?"

    async def _invoke_claude(self, prompt: str) -> str:
        """Invoke Claude Code CLI with a prompt."""
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    [
                        "claude",
                        "--print",
                        "--model", CLAUDE_MODEL,
                        "-p", prompt,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=LYRA_IDENTITY_PATH,
                )
            )

            if result.returncode != 0:
                print(f"Claude CLI error: {result.stderr}")
                return None

            return result.stdout.strip()

        except subprocess.TimeoutExpired:
            print("Claude CLI timeout")
            return None
        except FileNotFoundError:
            print("Claude CLI not found")
            return None
        except Exception as e:
            print(f"Claude invocation error: {e}")
            return None

    async def _send_response(self, channel, content: str) -> discord.Message | None:
        """Send response, handling Discord's character limit. Returns first message sent."""
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
        """Write an interaction to the Discord journal."""
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            journal_file = Path(JOURNAL_PATH) / f"{today}.jsonl"

            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": interaction_type,
                "context": context,
                "response": response,
                "heartbeat_count": self.heartbeat_count,
            }

            with open(journal_file, "a") as f:
                f.write(json.dumps(entry) + "\n")

            print(f"[JOURNAL] Wrote {interaction_type} entry")

        except Exception as e:
            print(f"[JOURNAL] Error writing: {e}")

    async def close(self):
        """Clean shutdown."""
        self.heartbeat_loop.cancel()
        self.active_mode_cleanup.cancel()
        await self.conversation_manager.close()
        await super().close()


async def main():
    """Main entry point."""
    if not DISCORD_BOT_TOKEN:
        print("Error: DISCORD_BOT_TOKEN not set")
        return

    if not DISCORD_CHANNEL_IDS:
        print("Warning: DISCORD_CHANNEL_IDS not set, will respond in any channel")

    # Check if claude CLI is available
    try:
        result = subprocess.run(["claude", "--version"], capture_output=True, text=True)
        print(f"Claude CLI: {result.stdout.strip()}")
    except FileNotFoundError:
        print("Warning: Claude CLI not found in PATH. Responses won't work.")

    bot = LyraBot()

    try:
        await bot.start(DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        print("\nShutting down...")
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
