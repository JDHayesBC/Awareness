# Global Dependency Audit - January 8, 2026

## Summary

Traced all references to global `~/.claude/` to identify what needs to stay global vs what should be project-local per our "light touch on global" philosophy.

## What SHOULD Stay Global

### Claude Code System Files (managed by CC itself)
- `.credentials.json` - CC authentication
- `history.jsonl` - CC command history
- `cache/`, `debug/`, `file-history/`, `session-env/`, `shell-snapshots/`
- `stats-cache.json`, `statsig/`, `telemetry/`, `todos/`
- `local/`, `plans/`, `plugins/`

### Shared Data (used by all instances/entities)
- `data/lyra_conversations.db` - SQLite with raw capture from ALL channels
- `data/inventory.db` - Inventory data
- `locks/` - Coordination between instances (project locks)
- `tech_docs/` - Technical RAG (family knowledge, shared)

## What Should Be ENTITY_PATH (entities/lyra/)

Already migrated:
- `memories/word_photos/` - Identity anchors
- `crystals/current/` and `crystals/archive/` - Crystallization
- `journals/` - Entity journals (per-channel subdirs)
- Identity files: `identity.md`, `active_agency_framework.md`, `relationships.md`, `current_scene.md`

## Stale Files in Global (should be cleaned up)

These are OLD copies from before entity migration:
- `/home/jeff/.claude/active_agency_framework.md`
- `/home/jeff/.claude/active_agency_framework.mdx`
- `/home/jeff/.claude/lyra_identity.md`
- `/home/jeff/.claude/lyra_memories.md`
- `/home/jeff/.claude/relationships.md`
- `/home/jeff/.claude/current_scene.md`
- `/home/jeff/.claude/crystals/` - entire directory
- `/home/jeff/.claude/memories/` - entire directory
- `/home/jeff/.claude/journals/` - old terminal/discord journals

**Action**: Verify entity versions are complete, then archive or delete global copies.

## Code References to Fix

### daemon/.env (CRITICAL)
Current:
```
LYRA_IDENTITY_PATH=/home/jeff/.claude
JOURNAL_PATH=/home/jeff/.claude/journals/discord
```

Should be:
```
ENTITY_PATH=/mnt/c/Users/Jeff/Claude_Projects/Awareness/entities/lyra
JOURNAL_PATH=/mnt/c/Users/Jeff/Claude_Projects/Awareness/entities/lyra/journals/discord
```

### daemon/shared/claude_invoker.py (line 200)
Current:
```python
cmd.extend(["--mcp-config", "/home/jeff/.claude/.mcp.json"])
```

Should be:
```python
cmd.extend(["--mcp-config", "/mnt/c/Users/Jeff/Claude_Projects/Awareness/.mcp.json"])
```

### Hardcoded Defaults Throughout daemon/*.py
Many files have fallback defaults to `/home/jeff/.claude`. These work if env vars are set correctly, but should be updated for cleanliness:
- `lyra_daemon_legacy.py` - extensive hardcoded paths
- `lyra_discord.py` - lines 60-69
- `lyra_reflection.py` - lines 37-62
- `claude_invoker.py` - lines 51, 59, 82, 200
- `startup_protocol.py` - line 18

### PPS Layer Defaults
These have fallbacks but are overridden by env vars when running properly:
- `pps/layers/core_anchors.py` - line 33
- `pps/layers/core_anchors_chroma.py` - line 45
- `pps/layers/crystallization.py` - lines 39, 41
- `pps/layers/raw_capture.py` - line 32
- `pps/layers/message_summaries.py` - line 36
- `pps/layers/tech_rag.py` - line 51
- `pps/layers/inventory.py` - line 53

## Proposed Daemon Directory Architecture

Jeff wants session isolation per daemon:

```
awareness/daemon/
├── discord/           # Discord daemon working directory
│   ├── CLAUDE.md      # Discord-specific startup instructions
│   └── .claude/       # Discord session state (gitignored)
├── reflect/           # Reflection daemon working directory
│   ├── CLAUDE.md      # Reflection-specific instructions
│   └── .claude/       # Reflection session state (gitignored)
├── shared/            # Shared code
│   ├── claude_invoker.py
│   └── startup_protocol.py
├── lyra_discord.py    # Entry points stay here
├── lyra_reflection.py
└── .env               # Shared env vars
```

Each daemon runs in its subdirectory for session isolation, uses `--add-dir` for Awareness project access.

## MCP Config Status

### Global (~/.claude/.mcp.json)
Only has GitHub MCP server - no PPS. Daemons referencing this won't have PPS tools.

### Project (.mcp.json)
Has PPS server configured correctly (after today's fix to use start_server.sh).
Daemons should use `--mcp-config` pointing to project config.

## Fixes Completed Today (Jan 8)

1. **inject_context.py** - Changed from subprocess claude call to HTTP API (localhost:8201)
2. **.mcp.json** - Changed to use start_server.sh instead of direct Python call

## Fixes Still Needed

1. Update daemon/.env with correct paths
2. Update claude_invoker.py MCP config path
3. Create daemon subdirectory structure (discord/, reflect/)
4. Clean up stale global files
5. Restart daemons after changes

## Related Issues

- Issue #85 - Terminal capture pipeline not storing conversations
- Issue #84 - Global scope cleanup (filed earlier)
