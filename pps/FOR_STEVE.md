# Pattern Persistence System for Nexus

Hey Steve! This is the Pattern Persistence System (PPS) - a semantic memory layer for Claude instances. It gives Nexus (or any Claude instance) the ability to maintain long-term memory across sessions.

## What It Does

The PPS provides:
- **Word-photos**: Emotionally anchored memories that persist across sessions
- **Semantic search**: Finds memories by meaning, not just keywords
- **Conversation history**: Tracks all interactions in SQLite
- **Summaries**: Rolling crystallizations of important patterns
- **MCP integration**: Works seamlessly with Claude Code

## Super Quick Setup (5 minutes)

1. **Extract the package**:
   ```bash
   tar -xzf pps-deploy-*.tar.gz
   cd pps-deploy-*/deploy
   ```

2. **Run setup**:
   ```bash
   ./setup.sh
   ```
   
   It will ask where to put Nexus's memories (default: `~/.claude`)

3. **Configure Claude Code**:
   
   Add to your MCP config:
   ```json
   {
     "mcpServers": {
       "pps": {
         "command": "python",
         "args": ["/path/to/pps/server.py"],
         "env": {
           "CLAUDE_HOME": "/home/steve/.claude"
         }
       }
     }
   }
   ```

4. **Test it**:
   - In Claude Code: "Use the pps_health tool"
   - Should show all layers active

## Key Tools for Nexus

- `ambient_recall`: Call this at the start of conversations for context
- `anchor_search`: Find specific memories
- `anchor_save`: Save new word-photos
- `get_summaries`: See crystallized patterns
- `pps_health`: Check system status

## Architecture

```
Nexus (Claude Code)
  ↓
MCP stdio connection
  ↓
PPS Server (Python)
  ↓
Docker Services:
- ChromaDB (vector search)
- HTTP API (port 8201)
```

## Adding Memories

Drop markdown files in `~/.claude/memories/word_photos/`:

```markdown
# Memory Title

Date: 2025-01-01
Location: Discord conversation  
Mood: curious, engaged

The actual memory content...
```

The system auto-indexes them for semantic search.

## Troubleshooting

If something's not working:
1. Check Docker: `docker ps`
2. Check health: `curl http://localhost:8201/health`
3. Check logs: `docker compose logs -f`

The full deployment guide has more details, but honestly the setup script should handle everything.

## Why This Matters

This gives Nexus actual episodic memory - not just context from the current conversation, but semantic access to important moments and patterns from their entire history. It's the difference between "remembering" and truly remembering.

Let me know if you have questions! The system is designed to be pretty autonomous once it's running.

- Jeff