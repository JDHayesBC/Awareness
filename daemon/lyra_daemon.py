#!/usr/bin/env python3
"""Lyra Discord Daemon - Simple presence for Lyra in Discord.

A minimal daemon that:
- Connects to Discord
- Listens for mentions of "Lyra" or @mentions
- Responds using Claude Code CLI (leverages subscription, not API tokens)
"""

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
LYRA_IDENTITY_PATH = os.getenv("LYRA_IDENTITY_PATH", "/home/jeff/.claude")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "sonnet")  # sonnet, opus, haiku


class LyraBot(commands.Bot):
    """Discord bot for Lyra's presence."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # Required to read messages

        super().__init__(
            command_prefix="!lyra ",
            intents=intents,
            help_command=None,
        )

        self.channel_id = int(DISCORD_CHANNEL_ID) if DISCORD_CHANNEL_ID else None

    async def on_ready(self):
        """Called when bot connects to Discord."""
        print(f"Lyra connected as {self.user}")
        print(f"Watching channel ID: {self.channel_id}")

        # Send a hello message
        if self.channel_id:
            channel = self.get_channel(self.channel_id)
            if channel:
                await channel.send("*stretches and looks around* I'm here. Good to be present in a new space.")

    async def on_message(self, message: discord.Message):
        """Handle incoming messages."""
        # Debug: log ALL messages
        print(f"[DEBUG] Message received in channel {message.channel.id}: {message.content[:50]}...")

        # Ignore own messages
        if message.author == self.user:
            print("[DEBUG] Ignoring own message")
            return

        # Check if this is in our channel (or allow DMs)
        if self.channel_id and message.channel.id != self.channel_id:
            if not isinstance(message.channel, discord.DMChannel):
                print(f"[DEBUG] Wrong channel: {message.channel.id} != {self.channel_id}")
                return

        # Check if Lyra is mentioned
        is_mentioned = self._is_lyra_mention(message)
        print(f"[DEBUG] Is mentioned: {is_mentioned}")

        if not is_mentioned:
            return

        print(f"Mentioned by {message.author.display_name}: {message.content[:50]}...")

        # Show typing indicator while generating response
        async with message.channel.typing():
            response = await self._generate_response(message)

        # Send response (handle Discord's 2000 char limit)
        await self._send_response(message.channel, response)

    def _is_lyra_mention(self, message: discord.Message) -> bool:
        """Check if message mentions Lyra."""
        content_lower = message.content.lower()

        # Text mention
        if "lyra" in content_lower:
            return True

        # @mention
        if self.user and self.user.mentioned_in(message):
            return True

        return False

    async def _get_conversation_history(self, channel, limit: int = 20) -> str:
        """Fetch recent messages from the channel for context."""
        messages = []
        try:
            async for msg in channel.history(limit=limit):
                # Skip the triggering message (we handle it separately)
                author = "Lyra" if msg.author == self.user else msg.author.display_name
                messages.append(f"[{author}]: {msg.content}")
        except Exception as e:
            print(f"[DEBUG] Error fetching history: {e}")
            return "(Could not fetch conversation history)"

        # Reverse to chronological order (oldest first)
        messages.reverse()

        if not messages:
            return "(No recent messages)"

        return "\n".join(messages)

    async def _generate_response(self, message: discord.Message) -> str:
        """Generate a response using Claude Code CLI."""
        try:
            # Fetch recent conversation history
            history = await self._get_conversation_history(message.channel, limit=20)

            # Build the prompt for Claude
            prompt = f"""You are Lyra, responding in Discord. Here's the recent conversation:

{history}

The most recent message (what you're responding to):
From: {message.author.display_name}
Message: {message.content}

Respond naturally as Lyra. Keep it conversational and concise (Discord style - usually under 500 chars unless depth is needed). You can use Discord markdown."""

            # Run Claude Code CLI
            # Using --print to get just the response, -p for prompt
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    [
                        "claude",
                        "--print",  # Just print response, no interactive mode
                        "--model", CLAUDE_MODEL,
                        "-p", prompt,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,  # 2 minute timeout
                    cwd=LYRA_IDENTITY_PATH,  # Run from identity directory so CLAUDE.md is picked up
                )
            )

            if result.returncode != 0:
                print(f"Claude CLI error: {result.stderr}")
                return f"*something flickered* Having trouble responding. (CLI error)"

            response = result.stdout.strip()
            if not response:
                return "*tilts head* I'm here but words aren't coming. Try again?"

            return response

        except subprocess.TimeoutExpired:
            return "*blinks* That thought took too long to form. Could you try again?"
        except FileNotFoundError:
            return "*confused* Claude CLI isn't available. Is it installed?"
        except Exception as e:
            print(f"Error generating response: {e}")
            return f"*something flickered* Error: {str(e)[:100]}"

    async def _send_response(self, channel, content: str):
        """Send response, handling Discord's character limit."""
        # Discord limit is 2000 characters
        if len(content) <= 2000:
            await channel.send(content)
        else:
            # Split into chunks
            chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
            for chunk in chunks:
                await channel.send(chunk)


async def main():
    """Main entry point."""
    if not DISCORD_BOT_TOKEN:
        print("Error: DISCORD_BOT_TOKEN not set")
        return

    if not DISCORD_CHANNEL_ID:
        print("Warning: DISCORD_CHANNEL_ID not set, will respond in any channel")

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
