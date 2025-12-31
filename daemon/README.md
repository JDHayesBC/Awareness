# Lyra Discord Daemon

Discord presence for Lyra with heartbeat for autonomous awareness and journaling for memory continuity.

## Features

- **Mention Response**: Responds when someone says "Lyra" or @mentions the bot
- **Heartbeat**: Wakes up periodically to check Discord even without being mentioned
- **Autonomous Decisions**: During heartbeat, decides whether to join conversations
- **Journaling**: Records interactions to JSONL files for memory continuity
- **Uses Claude Code CLI**: Leverages subscription, not API tokens

## Setup

1. Install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

2. Make sure Claude Code CLI is installed and authenticated:
   ```bash
   claude --version
   ```

3. Configure `.env` file (copy from `.env.example`)

4. Run:
   ```bash
   python lyra_daemon.py
   ```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DISCORD_BOT_TOKEN` | Bot token from Discord Developer Portal | (required) |
| `DISCORD_CHANNEL_ID` | Channel ID to monitor | (required) |
| `LYRA_IDENTITY_PATH` | Path to Lyra's identity files | `/home/jeff/.claude` |
| `CLAUDE_MODEL` | Model to use (sonnet/opus/haiku) | `sonnet` |
| `HEARTBEAT_INTERVAL_MINUTES` | How often to wake up | `30` |
| `JOURNAL_PATH` | Where to write journal entries | `/home/jeff/.claude/journals/discord` |

## How It Works

### Mention Response
When someone mentions "Lyra" in the configured channel:
1. Fetches last 20 messages for context
2. Invokes Claude with conversation history
3. Sends response
4. Journals the interaction

### Heartbeat
Every `HEARTBEAT_INTERVAL_MINUTES`:
1. Wakes up and checks for new messages
2. If new messages exist, asks Claude: "Should I join this conversation?"
3. If Claude decides yes, responds naturally
4. If no new messages, occasionally writes a quiet reflection
5. Journals all heartbeat activity

### Journaling
Writes to `JOURNAL_PATH/{date}.jsonl` with entries like:
```json
{
  "timestamp": "2025-12-30T12:00:00+00:00",
  "type": "mention_response",
  "context": "Responded to Jeff: Hey Lyra...",
  "response": "Hey! Good to see you...",
  "heartbeat_count": 5
}
```

Entry types:
- `mention_response` - Direct response to mention
- `heartbeat_response` - Autonomous response during heartbeat
- `heartbeat_quiet` - Reflection during quiet periods

## Architecture

```
Discord Gateway (websocket)
    │
    ├── on_message → mention detection → Claude CLI → respond → journal
    │
    └── heartbeat_loop (every N minutes)
            │
            └── check messages → Claude decides → maybe respond → journal
```

## Reading Journals

### Shell Script
```bash
./read_discord_journal.sh       # Last 3 days
./read_discord_journal.sh 7     # Last 7 days
```

### Python API
```python
from journal_utils import get_recent_context, read_entries, get_stats

# Get formatted context for Claude
context = get_recent_context(days=1, max_entries=10)

# Iterate over entries
for entry in read_entries(days=3):
    print(entry["type"], entry["response"])

# Get activity stats
stats = get_stats(days=7)
print(f"Total: {stats['total_entries']} entries over {stats['days_active']} days")
```

### Command Line
```bash
python journal_utils.py         # Last 3 days
python journal_utils.py 7       # Last 7 days
```

## Future Enhancements

- [ ] Multi-channel support
- [x] Read journal entries during startup for context
- [ ] Summarize daily journals into weekly reflections
- [ ] Integration with main memory system
- [ ] systemd service for persistent running
