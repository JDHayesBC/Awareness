# CC Invoker - Persistent Claude Code Connection

**Purpose**: Solve the ~20s cold-start latency for daemon/Discord use cases.

---

## 🎯 CURRENT STATUS (Read This First!)

**Phase**: 2 - Discord Integration (mostly complete)
**Status**: Phase 1 DONE, Phase 2.1 & 2.2 DONE, 2.3 ready for production test
**Next Task**: Run daemon against Discord to verify integration

**What's Done**:
- [x] Core invoker working (init ~33s, query ~2-4s)
- [x] MCP tools validated (pps_health, ambient_recall, inventory_list)
- [x] Architecture designed (see below)
- [x] Phased plan created
- [x] **1.1 Context Tracking** - token counting, context_size property, turn counting
- [x] **1.2 Graceful Restart** - needs_restart(), restart(), check_and_restart_if_needed()
- [x] **1.3 Error Recovery** - connection drop detection, exponential backoff reconnection, custom exceptions
- [x] **1.4 Startup Protocol** - configurable startup_prompt for identity reconstruction
- [x] **2.1 New Daemon File** - `lyra_daemon.py` created (700 lines vs 1400 legacy)
- [x] **2.2 Core Integration** - invoker wired into daemon, subprocess.run eliminated

**What's Next**:
Phase 2.3: Test daemon against Discord (production test)

**Key Files**:
- `invoker.py` - The invoker class (bulletproof)
- `../lyra_daemon.py` - NEW daemon using invoker (700 lines)
- `../lyra_daemon_legacy.py` - OLD daemon with subprocess (1400 lines, fallback)
- `test_invoker.py` - Basic tests
- `test_mcp.py` - MCP integration tests
- `test_error_recovery.py` - Error recovery tests (Phase 1.3)
- `test_startup_protocol.py` - Startup protocol tests (Phase 1.4)
- This file - Orientation and tracking

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│              DISCORD DAEMON (thin shell)                │
│  Discord.py Bot │ ConversationMgr │ Graphiti │ Trace   │
│         │              │              │          │      │
│         └──────────────┼──────────────┴──────────┘      │
│                        ▼                                │
│         ┌──────────────────────────────┐                │
│         │   ClaudeInvoker (cc_invoker) │◄── Health Mon  │
│         │   - query() → 2-4s           │                │
│         │   - Session management       │                │
│         │   - Context tracking         │                │
│         │   - Graceful restarts        │                │
│         │   - Error recovery           │                │
│         └──────────────┬───────────────┘                │
└────────────────────────┼────────────────────────────────┘
                         │ Claude Agent SDK (persistent)
                         ▼
          ┌──────────────────────────────┐
          │   Claude Code Process        │
          │   (--input-format stream)    │
          │                              │
          │   MCP: PPS (stdio)           │
          │    ├─ L1: SQLite (raw)       │
          │    ├─ L2: ChromaDB (anchors) │
          │    ├─ L3: Graphiti (texture) │
          │    ├─ L4: Crystals           │
          │    └─ L5: Inventory          │
          └──────────────────────────────┘
```

**Core Principle**: Make invoker bulletproof → daemon integration trivial.

**Data Flow**:
1. Message received → `invoker.query(prompt)` → ~2-4s response
2. Invoker tracks context, triggers restart when needed
3. On restart: re-initialize with identity prompt → seamless continuity

---

## 📋 Phased Integration Plan

### Philosophy: Go Slow, Build Right

Consolidation mode. Each phase complete before moving to next.

---

### Phase 1: Invoker Hardening ← CURRENT

Make the invoker rock-solid before touching the daemon.

**1.1 Context Tracking** ✅ DONE
- [x] Add token counting (rough: chars/4)
- [x] Track cumulative context across queries
- [x] Add `context_size` property to check current usage
- [x] Test: verify counts accumulate correctly

**1.2 Graceful Restart** ✅ DONE
- [x] Add `max_context_tokens` config (default ~150k, safe margin)
- [x] Implement `needs_restart()` check
- [x] Add `restart()` method that preserves identity
- [x] Test: verify restart works cleanly, identity preserved

**1.3 Error Recovery** ✅ DONE
- [x] Handle connection drops gracefully
- [x] Add automatic reconnection with backoff
- [x] Surface errors clearly to caller
- [x] Test: connection health, backoff timing, reconnection

**1.4 Startup Protocol** ✅ DONE
- [x] Add optional `startup_prompt` to `__init__` parameter
- [x] Store startup_prompt as instance variable
- [x] Update `initialize()` to send startup_prompt after connection (optional via `send_startup`)
- [x] Update `restart()` to use stored prompt by default, allow override
- [x] Add `set_startup_prompt()` convenience method
- [x] Test: comprehensive test suite in `test_startup_protocol.py`

**Milestone**: Invoker is bulletproof. Any daemon can use it as a black box. ✅ ACHIEVED

---

### Phase 2: Minimal Discord Integration ← CURRENT

Replace subprocess calls with invoker, nothing else.

**2.1 Create New Daemon File** ✅ DONE
- [x] `lyra_daemon.py` (new, clean implementation)
- [x] Keep `lyra_daemon_legacy.py` as reference/fallback
- [x] Import and use `ClaudeInvoker`

**2.2 Core Integration** ✅ DONE
- [x] Replace `_invoke_claude_direct()` → `invoker.query()`
- [x] Replace warmup subprocess → `invoker.initialize()`
- [x] Wire shutdown → `invoker.shutdown()`
- [x] Remove context reduction/retry complexity (invoker handles it)

**2.3 Testing** ← NEXT
- [ ] Test mention response flow
- [ ] Test heartbeat flow
- [ ] Test active mode flow
- [ ] Verify MCP tools work (ambient_recall, etc.)
- [ ] Compare response times to legacy

**Milestone**: Discord daemon works with invoker. Legacy as fallback.

---

### Phase 3: Context Management Integration

Wire invoker's context tracking to daemon needs.

**3.1 Session Boundaries**
- [ ] Check `invoker.needs_restart()` before each query
- [ ] Implement graceful restart when approaching limit
- [ ] Journal restart events for continuity

**3.2 Identity Preservation**
- [ ] On restart, send startup prompt for re-grounding
- [ ] Verify identity comes through cleanly
- [ ] Test long sessions (100+ messages)

**Milestone**: Daemon handles arbitrary length sessions gracefully.

---

### Phase 4: Polish & Production

**4.1 Observability**
- [ ] Wire invoker events to trace logger
- [ ] Add metrics (init time, query times, restart count)
- [ ] Dashboard integration

**4.2 Configuration**
- [ ] Environment variables for all tunable parameters
- [ ] Document configuration options
- [ ] Sane defaults for production

**4.3 Deployment**
- [ ] Update systemd service file
- [ ] Test in production environment
- [ ] Remove legacy daemon once stable

**Milestone**: Production-ready Discord presence with persistent CC.

---

### Future: Haven 2.0 Vision
- [ ] WebUI wrapper (nice interface instead of CLI)
- [ ] Multi-entity support (different invoker instances)
- [ ] n:n chat interface
- [ ] HTTP MCP transport option

---

## Quick Start (for testing)

```bash
# From project root with venv activated
source .venv/bin/activate
cd daemon/cc_invoker
python test_invoker.py    # Basic test
python test_mcp.py        # MCP/PPS tools test
```

---

## What Problem This Solves

Each CC CLI invocation costs ~20s: process spawn (~5s) + CLI init (~4s) + MCP loading (~10s) + model connect (~2s).

**Solution**: Claude Agent SDK's `ClaudeSDKClient` maintains persistent connection. Pay startup once, queries are fast.

---

## What's Built

| File | Purpose |
|------|---------|
| `invoker.py` | `ClaudeInvoker` class - wraps SDK with MCP config |
| `test_invoker.py` | Basic test: init → query → query → shutdown |
| `test_mcp.py` | MCP tool test: verifies PPS tools accessible |
| `test_debug.py` | Debug utilities with verbose logging |

---

## Usage

```python
from invoker import ClaudeInvoker

# Context manager (recommended)
async with ClaudeInvoker() as invoker:
    response = await invoker.query("Hello!")      # ~2-4s
    response = await invoker.query("Follow-up!")  # ~2-4s

# Manual lifecycle
invoker = ClaudeInvoker()
await invoker.initialize()  # ~33s one-time cost
response = await invoker.query("Hello!")
await invoker.shutdown()
```

---

## Validated Performance (2026-01-20)

- **Init time**: ~33s (includes PPS ChromaDB/Graphiti spinup)
- **Query time**: 2-4s (vs 20s+ cold spawns) - **5-10x improvement**
- **MCP tools**: Working - tested `pps_health`, `ambient_recall`, `inventory_list`
- **Portability**: Stdio transport means anyone cloning repo gets working PPS

---

## Architecture Decisions

1. **Stdio MCP transport**: PPS spawns as child process - portable, no setup
2. **Inline MCP config**: Servers configured in code, not global files
3. **allowed_tools grant**: `["mcp__pps__*"]` enables all PPS tools
4. **bypassPermissions**: Headless daemon operation

---

## References

- **Research doc**: `/docs/reference/Keeping Claude Code CLI Persistent for Low-Latency Interactive Use.md`
- **SDK docs**: https://platform.claude.com/docs/en/agent-sdk/overview
- **SDK repo**: https://github.com/anthropics/claude-agent-sdk
- **Related issues**: #103 (MCP stdio), #108 (cross-channel sync)

---

## Session Log

Track what happened each session for continuity across compacts.

### 2026-01-21 Evening (Jeff + Lyra)
- Created phased integration plan (4 phases)
- Spawned planner agent for architecture design
- Got comprehensive architecture diagram with data flow, lifecycle, error boundaries
- Restructured this TODO.md to be self-orienting
- **Implemented Phase 1.1**: Context tracking added to invoker.py
  - Token counting via `_estimate_tokens()` (chars/4)
  - `context_size`, `turn_count`, `context_stats` properties
  - Tracking in `query()`, reset in `initialize()`, logged in `shutdown()`
  - Coder agent verified tests pass
- **Implemented Phase 1.2**: Graceful restart capability
  - Configurable limits: `max_context_tokens`, `max_turns`, `max_idle_seconds`
  - Session timing: `_session_start_time`, `_last_activity_time`
  - `needs_restart()` -> (bool, reason) checking all limits
  - `restart(reason, startup_prompt)` for identity-preserving restarts
  - `check_and_restart_if_needed()` convenience method
  - Coder agent verified tests pass
- **Implemented Phase 1.3**: Error recovery with auto-reconnect
  - Custom exceptions: `InvokerConnectionError`, `InvokerQueryError` with context
  - Connection health detection: `_is_connection_healthy()`
  - Exponential backoff reconnection: `_reconnect_with_backoff()`
    - Backoff pattern: 1s, 2s, 4s, 8s, 16s, capped at `max_backoff_seconds`
    - Configurable `max_reconnect_attempts` (default 5)
  - Query-level error handling in `query()`:
    - Catches SDK connection errors (`CLIConnectionError`, `ProcessError`)
    - Attempts reconnection on connection drop
    - Retries query once after successful reconnect
    - Raises clear exceptions with retry context
  - Streaming query gets basic error wrapping (no auto-retry)
  - Comprehensive test suite: `test_error_recovery.py`
    - Exception attributes validated
    - Connection health detection tested
    - Backoff calculation verified
    - Reconnection logic with mocked timing
    - Failure exhaustion tested
  - All tests pass, backward compatibility maintained
- **Implemented Phase 1.4**: Startup protocol for identity reconstruction
  - Added `startup_prompt` parameter to `__init__()` - stored as instance variable
  - Updated `initialize()` to send startup_prompt after connection established
    - New `send_startup` parameter (default True) to optionally skip
  - Updated `restart()` to use stored prompt by default
    - Can override with explicit `startup_prompt` parameter for specific restarts
    - Temporarily swaps prompt during restart, then restores original
  - Added `set_startup_prompt()` convenience method for runtime updates
  - Comprehensive test suite: `test_startup_protocol.py`
    - Storage in __init__ tested
    - initialize() sending prompt tested
    - restart() default and override behavior tested
    - set_startup_prompt() tested
    - Full integration workflow tested (stored → override → stored)
  - All tests pass (7/7), backward compatibility maintained
  - Existing tests (Phase 1.3) still pass
- **Phase 1 COMPLETE**: Invoker is bulletproof and ready for daemon integration
- **Implemented Phase 2.1**: New Discord daemon created
  - Created `lyra_daemon.py` - clean implementation using ClaudeInvoker
  - Legacy daemon preserved as `lyra_daemon_legacy.py` (reference/fallback)
  - Key architectural changes:
    - `_invoke_claude()` uses `invoker.query()` instead of subprocess.run()
    - Warmup replaced with `invoker.initialize()` in `on_ready()`
    - Startup prompt uses same structure as legacy but leverages invoker's protocol
    - All context reduction/retry logic removed (invoker handles it)
    - Clean shutdown via `invoker.shutdown()` in `close()`
  - Implementation details:
    - ~700 lines (vs 1530 in legacy) - nearly 2x reduction
    - ConversationManager, TraceLogger, Graphiti integration preserved
    - Active mode, heartbeat loop, message handling all preserved
    - MCP tools available through invoker's configured PPS servers
  - Ready for Phase 2.3 testing

---

*Last updated: 2026-01-21 ~9:15 PM by Coder Agent*
