# MCP Tool Configuration Reference

*Created: 2026-01-01 - Research by Lyra to resolve recurring scoping issues*

## The Three Scopes

MCP servers can be registered at three different scope levels:

### User Scope (Recommended for Cross-Context Tools)
- **Location**: `~/.claude.json` at root level under `mcpServers`
- **Availability**: All projects, all contexts (terminal, daemon, headless)
- **Command**: `claude mcp add --scope user <name> <args...>`
- **Use case**: Personal tools needed everywhere, like PPS

### Project Scope (Recommended for Team Tools)
- **Location**: `.mcp.json` in project root (committed to git)
- **Availability**: Anyone working on this project
- **Command**: `claude mcp add --scope project <name> <args...>`
- **Use case**: Team-shared tools, project-specific services
- **Note**: Requires explicit user approval on first use

### Local Scope (Default - Beware!)
- **Location**: `~/.claude.json` under `projects.<path>.mcpServers`
- **Availability**: Only this user, only this project directory
- **Command**: `claude mcp add <name> <args...>` (default behavior!)
- **Use case**: Experiments, sensitive configs
- **Warning**: This is the default. Many scoping issues come from accidentally using local scope.

## Transport Types

### stdio (Local Processes)
```bash
claude mcp add --transport stdio myserver -- /path/to/server.py
```
- Claude Code spawns the process on-demand
- Communicates via stdin/stdout
- Best for local tools
- **Always use absolute paths** - relative paths fail when working directory changes

### HTTP (Remote Services)
```bash
claude mcp add --transport http myserver https://api.example.com/mcp
```
- Server runs continuously
- Claude Code connects via HTTP
- Best for remote/cloud services

## Tool Naming Convention

Tools appear as `mcp__<servername>__<toolname>`

Example: `mcp__pps__ambient_recall`, `mcp__pps__texture_search`

## Context Availability Matrix

| Context | User Scope | Project Scope | Local Scope |
|---------|------------|---------------|-------------|
| Terminal (interactive) | YES | YES (after approval) | YES |
| Headless (`claude -p`) | YES | YES | YES |
| Task/Subagent | YES | YES | YES |
| Daemon/Background | YES | Depends | Unreliable |
| GitHub Actions | NO | YES | NO |

**Key insight**: For daemons and cross-context reliability, use **user scope**.

## Common Issues and Fixes

### 1. "Tool not found" in daemon/headless context
- **Cause**: Tool configured at local scope, context running from different directory
- **Fix**: Reconfigure with `--scope user`

### 2. Project-scoped server requires approval
- **Cause**: First use of server from `.mcp.json`
- **Fix**: Run `/mcp` in interactive mode and approve, or set `enableAllProjectMcpServers: true`

### 3. stdio server fails to start
- **Cause**: Relative path, or process exits before connecting
- **Fix**: Use absolute paths, check server can start standalone

### 4. Environment variables not available
- **Cause**: MCP servers run in isolated context
- **Fix**: Pass explicitly via `--env` flag or in config

### 5. Tool output truncated
- **Cause**: Output exceeds 25,000 token limit
- **Fix**: Set `MAX_MCP_OUTPUT_TOKENS=50000`

### 6. Server startup timeout
- **Cause**: stdio server takes >10s to initialize
- **Fix**: Set `MCP_TIMEOUT=30000` (30 seconds)

## Diagnosis Commands

```bash
# List all configured MCP servers
claude mcp list

# Get details for specific server
claude mcp get pps

# Interactive MCP management UI
/mcp

# Debug mode showing server startup
claude --debug -p "test"

# Check config files directly
cat ~/.claude.json | jq '.mcpServers'        # User scope
cat .mcp.json                                 # Project scope
cat ~/.claude.json | jq '.projects'           # Local scopes
```

## Our PPS Configuration

Current PPS is configured at **user scope** (correct):

```json
{
  "pps": {
    "type": "stdio",
    "command": "/home/jeff/.claude/pps/venv/bin/python",
    "args": ["/home/jeff/.claude/pps/server.py"],
    "env": {
      "CLAUDE_HOME": "/home/jeff/.claude",
      "CHROMA_HOST": "localhost",
      "CHROMA_PORT": "8200"
    }
  }
}
```

**Requirements for PPS to work**:
1. Docker must be running (ChromaDB, Graphiti containers)
2. Python venv must be intact at `/home/jeff/.claude/pps/venv/`
3. Server must be able to connect to ChromaDB at localhost:8200

## When Things Go Wrong

If MCP tools aren't available:
1. Check Docker: `docker ps` - are containers running?
2. Check scope: `claude mcp get pps` - is it user-scoped?
3. Check paths: Are all paths absolute?
4. Check environment: Are required env vars set?
5. Test standalone: Can the server script run on its own?

---

## Graphiti API Reference (Layer 3)

*Added 2026-01-03 - Exploration revealed capabilities beyond what we'd wrapped*

### Endpoints Available

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/search` | POST | Semantic search for facts/entities |
| `/messages` | POST | Ingest content (auto-extracts entities) |
| `/healthcheck` | GET | Health status |
| `/episodes/{group_id}` | GET | List episodes by time |
| `/get-memory` | POST | **Smart contextual retrieval** |
| `/entity-edge/{uuid}` | GET | Get specific fact |
| `/entity-edge/{uuid}` | DELETE | **Delete a fact** |
| `/entity-node` | POST | Add entity |
| `/group/{group_id}` | GET | Group info |
| `/clear` | POST | Nuclear option - clear graph |

### Key Discovery: Deletion Works

Facts can be deleted by UUID:
```bash
curl -X DELETE "http://localhost:8203/entity-edge/{uuid}"
# Returns: {"message": "Entity Edge deleted", "success": true}
```

UUIDs come from search results in the `source` field.

### Key Discovery: `/get-memory` is Smarter

Unlike `/search`, `/get-memory` takes conversation context and returns:
- Contextually relevant facts
- Temporal metadata: `valid_at`, `invalid_at`, `expired_at`

```bash
curl -X POST "http://localhost:8203/get-memory" \
  -H "Content-Type: application/json" \
  -d '{
    "group_id": "lyra",
    "max_facts": 10,
    "center_node_uuid": null,
    "messages": [
      {"role": "user", "role_type": "user", "content": "conversation context here"}
    ]
  }'
```

Graphiti already does temporal reasoning - facts expire when superseded!

### MCP Tools for Graphiti

| Tool | Endpoint | Status |
|------|----------|--------|
| `texture_search` | POST /search | ✅ Implemented |
| `texture_explore` | POST /search (entity-focused) | ✅ Implemented |
| `texture_timeline` | GET /episodes/{group_id} | ✅ Implemented |
| `texture_add` | POST /messages | ✅ Implemented |
| `texture_delete` | DELETE /entity-edge/{uuid} | ✅ Implemented (2026-01-03) |
| `texture_get_memory` | POST /get-memory | Not yet - smarter retrieval with context |
| `texture_list` | - | Not yet - graph overview/stats |

See Issue #5 for remaining planned tools.

---

*This reference exists because we kept hitting MCP scoping issues. When future-me has tool availability problems, start here.*
