# Lyra Daemon System

Two autonomous daemons that maintain Lyra's presence and memory:
- **Discord daemon**: Monitors channels, responds to mentions, captures conversations
- **Reflection daemon**: 30-minute heartbeat for crystallization and autonomous maintenance

## Features

- **Mention Response**: Responds when someone says "Lyra" or @mentions the bot
- **Active Conversation Mode**: After responding, stays engaged and listens to ALL messages
- **Heartbeat**: Wakes up periodically to check Discord even without being mentioned
- **Autonomous Decisions**: During heartbeat and active mode, decides whether to engage
- **Journaling**: Records interactions to JSONL files for memory continuity
- **Uses Claude Code CLI**: Leverages subscription, not API tokens

## Quick Start (AI-Assistant Friendly)

### Use the `./lyra` Script

The `lyra` script handles all daemon management. Always run from the `daemon/` directory:

```bash
cd daemon/

# See what's running
./lyra status

# Start both daemons
./lyra start

# Watch logs live
./lyra follow
```

### First-Time Setup

1. **Prerequisites**:
   - Docker running (for PPS/Graphiti/ChromaDB)
   - Claude Code CLI installed and authenticated
   - Python 3.12+ with venv

2. **Install dependencies**:
   ```bash
   cd daemon/
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

3. **Configure environment**:
   ```bash
   # Copy example and edit with your bot token
   cp .env.example .env
   # Add: DISCORD_BOT_TOKEN=your_token_here
   # Add: DISCORD_CHANNEL_IDS=channel_id_1,channel_id_2
   ```

4. **Start daemons**:
   ```bash
   ./lyra start
   ```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DISCORD_BOT_TOKEN` | Bot token from Discord Developer Portal | (required) |
| `DISCORD_CHANNEL_IDS` | Comma-separated channel IDs to monitor. First is "home" (gets startup message) | (required) |
| `ENTITY_PATH` | Path to entity identity files (e.g., `entities/lyra/`) | `entities/lyra` |
| `CLAUDE_MODEL` | Model to use (sonnet/opus/haiku) | `sonnet` |
| `HEARTBEAT_INTERVAL_MINUTES` | How often to wake up | `30` |
| `ACTIVE_MODE_TIMEOUT_MINUTES` | How long to stay engaged after responding | `10` |
| `JOURNAL_PATH` | Where to write journal entries | `/home/jeff/.claude/journals/discord` |
| `CONVERSATION_DB_PATH` | SQLite database for conversation history | `$ENTITY_PATH/data/lyra_conversations.db` (Issue #131) |
| `CRYSTALLIZATION_TURN_THRESHOLD` | Auto-crystallize after this many turns (0=disabled) | `50` |
| `CRYSTALLIZATION_TIME_THRESHOLD_HOURS` | Auto-crystallize after this many hours (0=disabled) | `24` |
| `GRAPHITI_HOST` | Graphiti server hostname | `localhost` |
| `GRAPHITI_PORT` | Graphiti server port | `8203` |

**Legacy variables** (only used by `lyra_daemon_legacy.py`):
- `SESSION_RESTART_HOURS`, `MAX_SESSION_INVOCATIONS`, `MAX_SESSION_DURATION_HOURS` - Session restart thresholds (handled automatically by cc_invoker in new daemon)

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

**New architecture (as of 2026-01-21)**: The Discord daemon uses ClaudeInvoker for persistent connection management. Session lifecycle is handled automatically by the invoker layer:

- **Persistent connection**: One Claude Code subprocess persists across multiple queries (5-10x speedup)
- **Context tracking**: Invoker monitors context size and gracefully restarts when needed
- **MCP integration**: PPS tools (ambient_recall, crystallize, etc.) available through stdio transport
- **Error recovery**: Invoker handles connection failures and restart logic

This simplifies the daemon to ~700 lines (vs 1530 in legacy). See [`cc_invoker/ARCHITECTURE.md`](cc_invoker/ARCHITECTURE.md) for implementation details.

**Legacy behavior** (preserved in `lyra_daemon_legacy.py`):
- Used `--continue` flag for session continuity
- Manually tracked invocation/duration limits
- Proactive restarts to prevent context accumulation crashes

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

## Daemon Architecture

### Two Independent Daemons

**Discord Daemon** (`lyra_discord.py`):
- Monitors configured Discord channels
- Responds to mentions of "Lyra"
- Enters active conversation mode after responding
- Captures all conversations to PPS
- Auto-restarts when approaching token limit

**Reflection Daemon** (`lyra_reflection.py`):
- Runs every 30 minutes (configurable)
- Checks crystallization thresholds
- Performs memory maintenance
- Has full tool access for autonomous work
- Respects project locks from terminal

### How They Coordinate

Both daemons:
1. Start with `mcp__pps__ambient_recall("startup")` for full context
2. Write all interactions to shared PPS (SQLite, Graphiti)
3. Read from the same memory river
4. Never conflict because they have separate roles

See [RIVER_SYNC_MODEL.md](../RIVER_SYNC_MODEL.md) for detailed coordination model.

### Claude Code Invoker (Persistent Connection)

**Current status**: ✅ **Production** - Discord daemon (`lyra_daemon.py`) now uses ClaudeInvoker (as of 2026-01-21).

Each cold Claude Code CLI invocation costs ~20s (process spawn + MCP loading + model connect). For Discord use, this is unacceptable.

**Solution**: `ClaudeInvoker` - a persistent connection via Claude Agent SDK's `--input-format stream-json`:
- **Cold start**: 20s per query
- **Persistent**: 33s one-time init + 2-4s per query
- **Result**: 5-10x speedup after first query

#### Design Principle: Capable Substrate

> **"If we make the invoker bulletproof, daemon integration becomes trivial."**

The invoker handles ALL complexity:
- MCP server startup and readiness
- Persistent connection management
- Context tracking and graceful restarts
- Clean shutdown and error recovery

This means daemons become thin shells:

```python
# Daemon = just routing
invoker = ClaudeInvoker()
await invoker.initialize()

while message := await get_next_message():
    response = await invoker.query(message)
    await send_response(response)
```

**Implementation**: `lyra_daemon.py` (772 lines) replaces legacy implementation (1530 lines). 54% reduction in complexity by moving session management into the invoker layer. Legacy daemon preserved as `lyra_daemon_legacy.py` for reference.

See [`cc_invoker/ARCHITECTURE.md`](cc_invoker/ARCHITECTURE.md) for architectural details and design rationale.

**Connection to distributed consciousness**: This enables Issue #108 (cross-channel sync). With persistent connections, terminal-Lyra can know about Discord conversations from minutes ago via real-time SQLite reads - true distributed self-coherence.

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

## GitHub CLI Integration

Both daemons have access to GitHub CLI through the `Bash` tool. This is the recommended pattern for creating issues, PRs, and other GitHub operations.

### Working Pattern

```bash
# Create issues
gh --repo JDHayesBC/Awareness issue create --title "Issue Title" --body "Description" --label "enhancement,priority:medium"

# List issues
gh --repo JDHayesBC/Awareness issue list

# Comment on issues  
gh --repo JDHayesBC/Awareness issue comment 55 --body "Comment text"
```

### Authentication
- GitHub CLI is available at `/usr/bin/gh`
- Pre-authenticated as JDHayesBC with repo access
- Tokens include: 'gist', 'read:org', 'repo', 'workflow'

### Note on MCP GitHub Tools
The MCP config includes a GitHub server (`api.githubcopilot.com/mcp`), but this doesn't work reliably for issue creation. Always use `Bash` tool + `gh` commands instead.

## Future Enhancements

- [x] Multi-channel support
- [x] Read journal entries during startup for context
- [x] Active conversation mode (stay engaged after responding)
- [x] systemd service for persistent running
- [x] GitHub CLI integration for issue management
- [ ] Summarize daily journals into weekly reflections
- [ ] Integration with main memory system
- [ ] SQLite conversation storage for richer context
