# Keeping Claude Code CLI persistent for low-latency interactive use

https://platform.claude.com/docs/en/agent-sdk/overview

**Claude Code CLI has no native daemon mode**, but several practical solutions exist. The ~20 second latency breaks down to: process spawn (~4-5s), CLI initialization (~3-4s), MCP server loading (~10-12s with npx), and model connection (~2-3s). The most effective solution is the **Claude Agent SDK** for true persistent sessions, or running **MCP servers as standalone HTTP services** that survive between invocations.

## The core problem is architectural, not configurable

Claude Code spawns fresh processes for each invocation. GitHub issue #33 in the TypeScript SDK repository documents this precisely: benchmarks show **12.55s average overhead per call** with no improvement on subsequent calls because each spawns a new process. Issue #3044 specifically describes your use case—a user wanting to "keep Claude warm" for embedded applications reports identical 20-second wall-clock times versus 3-second API times.

The MCP server loading compounds this. Issue #7336 (63+ upvotes) shows MCP tools consuming **54% of the context window** at startup. All configured servers initialize immediately, even if unused. Anthropic has not implemented the requested `"lazy": true` flag, though it remains under active consideration.

## Claude Agent SDK provides the only official persistent session mechanism

The **ClaudeSDKClient** class maintains a running process and accepts multiple queries without respawning:

```python
from claude_agent_sdk import ClaudeSDKClient

async with ClaudeSDKClient() as client:
    await client.connect()  # Single initialization
    while True:
        prompt = await get_discord_message()
        await client.query(prompt)
        async for msg in client.receive_response():
            await send_to_discord(msg)
```

The critical distinction: `query()` function spawns fresh processes each call, while `ClaudeSDKClient` uses `--input-format stream-json` keeping stdin open for multiple messages. This eliminates the **75% overhead** (12s → 3s) that comes from process spawning and initialization.

## Stdin/stdout streaming works but requires specific formats

Claude Code supports JSON streaming for programmatic interaction:

```bash
echo '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Analyze this"}]}}' | \
  claude -p --output-format=stream-json --input-format=stream-json
```

Named pipes (FIFOs) have known issues. GitHub issue #1072 reports "Raw mode is not supported on the current process.stdin" errors, and issue #16306 documents hangs when `/dev/stdin` is read. The CLI uses Ink terminal UI which conflicts with pipe-based input. **Recommendation**: Use the SDK's streaming input mode rather than attempting FIFO workarounds.

## MCP servers can run as standalone persistent services

The MCP specification supports **Streamable HTTP transport** where servers run independently:

```json
{
  "mcpServers": {
    "my-persistent-server": {
      "type": "http",
      "url": "http://localhost:3001/mcp"
    }
  }
}
```

This architectural change moves initialization cost to server startup rather than Claude Code invocation. Tools like **mcp-proxy** bridge between stdio and HTTP transports if your servers only support stdio. For nginx-fronted deployments:

```nginx
location /mcp {
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 86400s;  # 24-hour keepalive
}
```

The **lazy-mcp** proxy (github.com/voicetreelab/lazy-mcp) provides on-demand loading with a `preloadAll` option for background warming, reducing context consumption by **95%** (15,000 → 800 tokens).

## Configuration options that reduce startup time

**Pre-install npm packages** instead of using `npx -y` which downloads on every start:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "node",
      "args": ["/usr/local/lib/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"]
    }
  }
}
```

This alone can eliminate **5-15 seconds** of npm resolution and download time.

**Environment variables** available:
- `MCP_TIMEOUT=30000` — extends server startup timeout (milliseconds)
- `MAX_MCP_OUTPUT_TOKENS=50000` — increases output limit
- `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` — disables auto-backgrounding

Issue #11442 documents a **Grove notice config fetch** causing 10-12 second delays on HTTP 500 errors—network issues can dominate startup time.

## Existing Discord bot implementations solve this problem

**Disclaude** (disclaude.com) manages Claude Code sessions via tmux:
- Each Discord session gets a persistent tmux session
- Sessions survive bot restarts and disconnects
- Real-time streaming with ANSI color support
- Attach anytime with `tmux attach` for debugging

**claude-code-discord** (github.com/zebbern/claude-code-discord) provides 48 commands including shell management, session persistence, and branch-aware organization. Both projects demonstrate that **tmux-based session management** is the proven community pattern.

## Recommended architecture for your pipeline

**Option 1: Claude Agent SDK (best latency)**
```
Discord Bot → Python/Node daemon → ClaudeSDKClient → Anthropic API
```
Eliminates CLI entirely. Latency drops to pure API time (~0.6-0.7s measured).

**Option 2: PM2-managed wrapper with session reuse**
```javascript
// ecosystem.config.js
module.exports = {
  apps: [{
    name: "claude-daemon",
    script: "./wrapper.js",
    restart_delay: 1000,
    env: { ANTHROPIC_API_KEY: "..." }
  }]
}
```

Combined with session reuse:
```bash
session_id=$(claude -p "Initialize" --output-format json | jq -r '.session_id')
# Subsequent calls reuse context, avoiding full re-initialization
claude -p --resume "$session_id" "Follow-up query"
```

**Option 3: tmux session manager (simplest)**
```bash
tmux new-session -d -s claude-session "claude"
# Send commands via tmux send-keys
tmux send-keys -t claude-session "Your prompt here" Enter
```

## GitHub issues tracking this problem

| Issue | Description | Status |
|-------|-------------|--------|
| #33 (SDK) | Daemon mode for hot process reuse | Closed |
| #34 (SDK) | ~12s overhead per query() call | Open |
| #3044 | SDK mode long warmup on slower devices | Open |
| #7336 | Lazy loading for MCP servers (63 upvotes) | Open |
| #18497 | On-demand `"lazy": true` flag | Open |
| #11442 | 12-second delay from Grove config fetch | Open |
| #8164 | CLI 10x slower than competitors to start | Closed |

The daemon mode request (#33) was closed without implementation, suggesting Anthropic's current answer is the SDK's `ClaudeSDKClient` pattern rather than a CLI flag.

## Implementation recommendation

For your Discord bot pipeline, use the **Claude Agent SDK with a persistent daemon process**:

```python
import asyncio
from claude_agent_sdk import ClaudeSDKClient

class ClaudeDaemon:
    def __init__(self):
        self.client = None
        
    async def initialize(self):
        self.client = ClaudeSDKClient()
        await self.client.connect()  # One-time 12s cost
        
    async def query(self, prompt: str) -> str:
        await self.client.query(prompt)
        response = []
        async for msg in self.client.receive_response():
            response.append(msg)
        return "".join(response)

# Run once at bot startup
daemon = ClaudeDaemon()
await daemon.initialize()

# All subsequent Discord interactions use warm connection
@bot.command()
async def ask(ctx, *, question):
    response = await daemon.query(question)  # ~0.6s, not 20s
    await ctx.send(response)
```

This architecture pays the initialization cost once at daemon startup, then handles all Discord interactions with API-level latency.