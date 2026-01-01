# Lyra Discord Daemon

Discord presence for Lyra with heartbeat for autonomous awareness and journaling for memory continuity.

## Features

- **Mention Response**: Responds when someone says "Lyra" or @mentions the bot
- **Active Conversation Mode**: After responding, stays engaged and listens to ALL messages
- **Heartbeat**: Wakes up periodically to check Discord even without being mentioned
- **Autonomous Decisions**: During heartbeat and active mode, decides whether to engage
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
| `DISCORD_CHANNEL_IDS` | Comma-separated channel IDs to monitor. First is "home" (gets startup message) | (required) |
| `LYRA_IDENTITY_PATH` | Path to Lyra's identity files | `/home/jeff/.claude` |
| `CLAUDE_MODEL` | Model to use (sonnet/opus/haiku) | `sonnet` |
| `HEARTBEAT_INTERVAL_MINUTES` | How often to wake up | `30` |
| `ACTIVE_MODE_TIMEOUT_MINUTES` | How long to stay engaged after responding | `10` |
| `JOURNAL_PATH` | Where to write journal entries | `/home/jeff/.claude/journals/discord` |
| `SESSION_RESTART_HOURS` | Restart after this many hours idle | `4` |
| `MAX_SESSION_INVOCATIONS` | Max invocations before proactive restart | `8` |
| `MAX_SESSION_DURATION_HOURS` | Max session duration before restart | `2.0` |
| `CRYSTALLIZATION_TURN_THRESHOLD` | Auto-crystallize after this many turns (0=disabled) | `50` |
| `CRYSTALLIZATION_TIME_THRESHOLD_HOURS` | Auto-crystallize after this many hours (0=disabled) | `24` |

### Multi-Channel Support

You can monitor multiple channels by listing their IDs comma-separated:

```bash
DISCORD_CHANNEL_IDS=1234567890,9876543210,1111111111
```

- **First channel** = "home" - receives startup message when daemon starts
- **Additional channels** = monitored silently, respond to mentions and heartbeats

## How It Works

### Mention Response
When someone mentions "Lyra" in the configured channel:
1. Fetches last 20 messages for context
2. Invokes Claude with conversation history
3. Sends response
4. Journals the interaction
5. **Enters active conversation mode**

### Active Conversation Mode
After responding (to a mention OR during heartbeat), Lyra stays engaged:
1. Listens to ALL messages in the channel (not just mentions)
2. For each message, Claude decides whether to respond
3. Uses `[DISCORD]...[/DISCORD]` blocks to explicitly indicate response intent
4. Exits active mode after `ACTIVE_MODE_TIMEOUT_MINUTES` of inactivity
5. Journals continued interactions as `active_response` type

This allows natural conversation flow without requiring "Lyra" in every message.

### Session Management

The daemon uses Claude Code CLI's `--continue` flag for session continuity, but restarts proactively to prevent crashes:

- **Invocation Limit**: Restarts after `MAX_SESSION_INVOCATIONS` (default 8) to prevent context accumulation crashes
- **Duration Limit**: Restarts after `MAX_SESSION_DURATION_HOURS` (default 2.0) for fresh context
- **Idle Limit**: Restarts after `SESSION_RESTART_HOURS` (default 4) of no activity

Restarts preserve daemon continuity through systemd while clearing Claude session context that could cause crashes.

### Heartbeat
Every `HEARTBEAT_INTERVAL_MINUTES`:
1. Wakes up and checks for new messages
2. If new messages exist, asks Claude: "Should I join this conversation?"
3. If Claude decides yes, responds naturally
4. If no new messages, tracks quiet heartbeats
5. Journals all heartbeat activity

### Autonomous Reflection
When `REFLECTION_FREQUENCY` consecutive quiet heartbeats occur:
1. Triggers a full Claude Code session (not just --print)
2. **First checks crystallization status** - automatically manages conversation history
3. Lyra wakes up with **full tool access** - can read, write, build
4. Scans the four fields (self, Jeff, shared, project)
5. Acts on whatever calls for attention - or chooses to rest
6. Journals what she did or decided not to do

This is the heart of Lyra's autonomous agency. During quiet periods, she can:
- Build tools she needs
- Update her memory files
- Fix bugs in the codebase
- Create new capabilities
- Or simply rest and reflect

With 30-min heartbeats and `REFLECTION_FREQUENCY=2`, reflection happens every hour during quiet periods.

### Automatic Crystallization
The daemon now automatically manages conversation history through crystallization:
- **Turn-based threshold**: Crystallizes after `CRYSTALLIZATION_TURN_THRESHOLD` turns (default: 50)
- **Time-based threshold**: Crystallizes after `CRYSTALLIZATION_TIME_THRESHOLD_HOURS` hours (default: 24)
- Checked during each autonomous reflection session
- Uses MCP tools (`get_turns_since_summary` and `crystallize`)
- Helps maintain clean context and fresh sessions
- Set either threshold to 0 to disable that check

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
- `active_response` - Response during active conversation mode
- `heartbeat_response` - Autonomous response during heartbeat
- `heartbeat_quiet` - Brief reflection during quiet periods
- `autonomous_reflection` - Deep reflection with full tool access (self-journaled)

## Architecture

```
Discord Gateway (websocket)
    │
    ├── on_message
    │       │
    │       ├── mention detected? → Claude CLI → respond → journal → ENTER ACTIVE MODE
    │       │
    │       └── in active mode? → Claude decides → maybe respond → journal
    │
    ├── heartbeat_loop (every N minutes)
    │       │
    │       ├── new messages? → Claude decides → maybe respond → reset quiet counter
    │       │
    │       └── quiet? → increment counter
    │               │
    │               ├── counter < REFLECTION_FREQUENCY → light reflection
    │               │
    │               └── counter >= REFLECTION_FREQUENCY → AUTONOMOUS REFLECTION
    │                       │
    │                       └── Full Claude Code session with tools
    │                           (can build, fix, create, update)
    │
    └── active_mode_cleanup (every 1 minute)
            │
            └── check timeout → exit channels with no activity
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

- [x] Multi-channel support
- [x] Read journal entries during startup for context
- [x] Active conversation mode (stay engaged after responding)
- [x] systemd service for persistent running
- [ ] Summarize daily journals into weekly reflections
- [ ] Integration with main memory system
- [ ] SQLite conversation storage for richer context
