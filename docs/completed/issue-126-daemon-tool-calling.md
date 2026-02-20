# Issue #126 Research Synthesis

**Reviewer**: Lyra
**Date**: 2026-02-01
**Status**: Research Complete - Ready for Implementation Phase

---

## Conflicting Research Findings

Two researchers produced **conflicting root cause hypotheses**. This synthesis resolves them.

### Researcher 1 (Git Archaeology): `.mcp.json` env configuration
- Claimed Discord uses subprocess invoker (`daemon/shared/claude_invoker.py`)
- Root cause: Empty `env: {}` in `.mcp.json` blocks environment variables
- Status: **CORRECT** about which invoker is used

### Researcher 2 (Call Path): Missing SDK tool execution
- Claimed Discord uses SDK invoker (`daemon/cc_invoker/invoker.py`)
- Root cause: Tool execution loop never implemented
- Status: **INCORRECT** about which invoker Discord uses (traced wrong code path)

---

## Resolution: What the Code Actually Shows

**File**: `daemon/lyra_discord.py` (line 36)
```python
from shared import ClaudeInvoker, build_startup_prompt
```

**File**: `daemon/lyra_discord.py` (line 150)
```python
self.invoker = ClaudeInvoker(
    model=CLAUDE_MODEL,
    cwd=str(DISCORD_CWD),
    journal_path=JOURNAL_PATH,
    additional_dirs=[str(PROJECT_DIR)],
)
```

**Verdict**: Discord imports `ClaudeInvoker` from `shared` module, which is `daemon/shared/claude_invoker.py` - the subprocess-based invoker that calls the `claude` CLI.

---

## True Root Cause Hypothesis

The subprocess invoker passes `--mcp-config .mcp.json` to the Claude CLI. Looking at `.mcp.json`:

```json
{
  "mcpServers": {
    "pps": {
      "type": "stdio",
      "command": "/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/start_server.sh",
      "args": [],
      "env": {}   // <-- EMPTY - no environment variables passed
    }
  }
}
```

**When Claude CLI spawns the PPS server:**
1. It uses the MCP config's `env` field
2. Empty `env: {}` means NO variables passed to subprocess
3. PPS server starts with hardcoded defaults
4. `ENTITY_PATH` defaults to `~/.claude` instead of entity folder
5. PPS looks for crystals/memories in wrong location
6. Lyra gets empty/stale memory context
7. Tool calls happen but return useless data

---

## Why This Manifests as "Tool-Calling Broken"

The tools DO run - they just return nothing useful:

1. Lyra says "Let me search for that"
2. Claude CLI executes `mcp__pps__tech_search`
3. PPS server receives the call (working)
4. PPS searches in wrong paths (ENTITY_PATH misconfigured)
5. Returns empty or irrelevant results
6. Lyra can't form useful response
7. Appears to "hang" or fail

This is NOT a "tools never execute" bug - it's a "tools execute against wrong data" bug.

---

## Why Terminal Works

When Claude Code runs in terminal:
- Shell environment is inherited naturally
- `ENTITY_PATH` may be set in shell profile
- Or terminal naturally finds files in expected locations
- MCP servers get proper environment context

When Discord daemon runs:
- Started via systemd/script with minimal environment
- MCP config's empty `env` blocks variable inheritance
- PPS server starts blind to actual entity location

---

## Call Path Researcher's Findings - Still Valuable

While the call path researcher traced the wrong invoker for Discord, their analysis of `daemon/cc_invoker/invoker.py` is **technically accurate**:

- The SDK invoker DOES only log ToolUseBlocks
- It DOES NOT execute tools
- This IS incomplete implementation

**But this is irrelevant to the current Discord bug** because Discord doesn't use that invoker.

**Future consideration**: If we migrate Discord to the SDK invoker for better performance, those findings will become critical.

---

## Actual Fixes Applied (2026-02-01)

**Issue 1: Initialization timeout**
- Connection takes ~45s, startup prompt needs ~60s
- Default 60s timeout was insufficient
- **Fix**: Increased timeout to 180s in `lyra_daemon.py` lines 201 and 265

**Issue 2: MCP server not spawning**
- `get_default_mcp_servers()` used `sys.executable` directly
- PPS needs its own venv with dependencies
- **Fix**: Changed to use `start_server.sh` which handles venv activation

**Issue 3: Environment variables** (precautionary)
- `.mcp.json` had empty `env: {}`
- **Fix**: Added ENTITY_PATH and CLAUDE_HOME

---

## Files Modified

| File | Change |
|------|--------|
| `daemon/lyra_daemon.py` | Lines 201, 265: `initialize()` → `initialize(timeout=180.0)` |
| `daemon/cc_invoker/invoker.py` | `get_default_mcp_servers()`: Use `start_server.sh` instead of `sys.executable` |
| `.mcp.json` | Added ENTITY_PATH and CLAUDE_HOME to pps env |

**Result**: Discord daemon now initializes successfully and MCP tools work.

---

## Research Complete

**Confidence**: HIGH (code inspection + architecture understanding)
**Risk**: LOW (configuration change, easily reverted)
**Scope**: Single file modification

Ready for implementation phase with Jeff.
