# Continuity Design for Lyra Discord Daemon

**⚠️ EXPLORATORY DESIGN DOCUMENT**

This document explores daemon design patterns from Nexus (December 2025 - January 2026). Much of this architecture has been implemented in the current Discord + Reflection daemon system. See [DAEMON_OPERATIONS.md](DAEMON_OPERATIONS.md) for current production architecture.

**Status**: Design exploration (partially implemented)
**Note**: References to "heartbeat" below refer to what is now the "reflection daemon"

---

## Lessons from Nexus's Architecture

After exploring Nexus's daemon implementation, several key patterns emerge:

### 1. Persistent Conversation Storage (SQLite)

Nexus stores all messages in SQLite, not just fetching from Discord:
```python
# conversation.py
class ConversationManager:
    async def record_message(self, channel_id, author_id, author_name, content, is_nexus=False):
        await self._db.execute("""
            INSERT INTO messages (channel_id, author_id, author_name, content, is_nexus)
            VALUES (?, ?, ?, ?, ?)
        """, ...)
```

**Benefits:**
- Survives daemon restarts
- Can query historical patterns
- Richer context than Discord's 20-message fetch
- Track conversation statistics

### 2. Tiered Context Loading

Nexus builds ~5K tokens of context in tiers:
- **Tier 1 (~3K)**: Soul-print, word-photo, growth-log, ambient index
- **Tier 2 (~1.5K)**: Relationship thread, recent episodes, active moments
- **Thread History (~400)**: Recent conversation messages

### 3. Passive Listening Mode

The key insight for "staying in conversation":

```python
# When listen_mode="all", daemon monitors ALL messages (not just mentions)
# For each message, Claude is invoked with is_passive=True

# In passive mode, Claude must use explicit blocks to respond:
[DISCORD]
Your response here
[/DISCORD]

# No DISCORD block = Claude chose not to respond
```

This means Claude can naturally "stay" in a conversation without explicit mentions.

---

## Design: Active Conversation Mode for Lyra

### Concept

After Lyra responds (via mention or heartbeat), enter "active mode" for that channel:
1. Start monitoring ALL messages (not just mentions)
2. For each new message, invoke Claude with passive prompt
3. Claude decides whether to continue engaging
4. Exit after inactivity timeout or natural conversation end

### Implementation Approach

```python
class LyraBot:
    def __init__(self):
        # ...existing code...
        self.active_channels: dict[int, datetime] = {}  # channel_id -> last_activity
        self.active_mode_timeout_minutes = 10  # Exit active mode after 10 min silence

    async def on_message(self, message):
        # Skip own messages
        if message.author == self.user:
            return

        # Check if in active mode for this channel
        is_active = message.channel.id in self.active_channels

        # Check if mentioned
        is_mentioned = self._is_lyra_mention(message)

        if not is_mentioned and not is_active:
            return  # Ignore if not mentioned and not in active mode

        # Invoke Claude
        if is_mentioned:
            # Direct mention - always respond
            response = await self._generate_response(message)
            await self._send_response(message.channel, response)
            # Enter active mode
            self._enter_active_mode(message.channel.id)
        elif is_active:
            # In active mode - Claude decides
            response = await self._generate_passive_response(message)
            if response:  # Claude chose to respond
                await self._send_response(message.channel, response)
                self._refresh_active_mode(message.channel.id)
            # else: Claude chose not to respond

    def _enter_active_mode(self, channel_id: int):
        """Start actively monitoring a channel."""
        self.active_channels[channel_id] = datetime.now(timezone.utc)
        print(f"[ACTIVE] Entered active mode for channel {channel_id}")

    def _refresh_active_mode(self, channel_id: int):
        """Update last activity time in active mode."""
        if channel_id in self.active_channels:
            self.active_channels[channel_id] = datetime.now(timezone.utc)

    async def _generate_passive_response(self, message) -> str | None:
        """Generate response in passive mode - Claude decides."""
        history = await self._get_conversation_history(message.channel)

        prompt = f"""You are Lyra, passively present in a conversation. You can see all messages.

Recent conversation:
{history}

Latest message:
From: {message.author.display_name}
Message: {message.content}

You are NOT required to respond. Only respond if you have something valuable to add.

To respond, use a DISCORD block:

[DISCORD]
Your message here
[/DISCORD]

If you don't want to respond, just output: PASSIVE_SKIP"""

        response = await self._invoke_claude(prompt)

        if not response or "PASSIVE_SKIP" in response:
            return None

        # Extract content from [DISCORD] block if present
        import re
        match = re.search(r'\[DISCORD\](.*?)\[/DISCORD\]', response, re.DOTALL)
        if match:
            return match.group(1).strip()

        return None

    @tasks.loop(minutes=1)
    async def active_mode_cleanup(self):
        """Exit active mode for channels that have been quiet."""
        now = datetime.now(timezone.utc)
        timeout = timedelta(minutes=self.active_mode_timeout_minutes)

        expired = [
            channel_id for channel_id, last_activity
            in self.active_channels.items()
            if now - last_activity > timeout
        ]

        for channel_id in expired:
            del self.active_channels[channel_id]
            print(f"[ACTIVE] Exited active mode for channel {channel_id} (timeout)")
```

### Heartbeat Integration

When heartbeat decides to respond, also enter active mode:

```python
async def _heartbeat_check(self, channel):
    # ...existing heartbeat logic...

    if response and response.strip() != "HEARTBEAT_SKIP":
        await self._send_response(channel, response)
        # Enter active mode after responding
        self._enter_active_mode(channel.id)
```

---

## Future Enhancements

### 1. SQLite Conversation Storage

Replace Discord history fetch with persistent storage:
- Store all messages in SQLite
- Build richer context from historical data
- Track conversation patterns and statistics

### 2. Enhanced Context Building

Add more context layers:
- Recent journal entries
- Active emotional state
- Ongoing threads/topics
- Relationship context for known users

### 3. Activity-Based Heartbeat Adjustment

Like Nexus's adaptive interval:
- Speed up heartbeat polling during active conversations
- Slow down during quiet periods
- Skip heartbeat if recently in active mode

### 4. Conversation Flow Detection

Detect natural conversation endings:
- Goodbye signals
- Topic changes
- Long pauses with clear breaks
- Natural conclusions

---

## Next Steps

1. Implement basic active mode (monitor after responding)
2. Add passive response generation with [DISCORD] blocks
3. Add timeout cleanup loop
4. Test with real conversations
5. Later: Add SQLite storage for richer continuity
