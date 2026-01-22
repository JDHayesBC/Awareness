# CC Invoker - Persistent Claude Code Connection

**Purpose**: Solve the ~20s cold-start latency for daemon/Discord use cases.
**Status**: Core complete and tested. Ready for integration.

---

## Quick Start

```bash
# From project root with venv activated
source .venv/bin/activate
cd daemon/cc_invoker
python test_invoker.py    # Basic test
python test_mcp.py        # MCP/PPS tools test
```

---

## What Problem This Solves

Each CC CLI invocation costs ~20s: process spawn (~5s) + CLI init (~4s) + MCP loading (~10s) + model connect (~2s). For Discord, this is unacceptable - users expect fast responses.

**Solution**: The Claude Agent SDK's `ClaudeSDKClient` maintains a persistent connection via `--input-format stream-json`. Pay startup cost once, then all queries are fast.

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

## ✅ Validated (2026-01-20)

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

## Core Design Principle: Invoker as the Capable Layer

**Key insight**: If we make the invoker bulletproof, daemon integration becomes trivial.

The invoker should handle ALL the complexity:
- MCP server startup and readiness
- Persistent connection management
- Context tracking and graceful restarts
- Clean shutdown
- Error recovery

This means any daemon (Discord, reflection, future webui) becomes just a thin shell:

```python
# Daemon startup
invoker = ClaudeInvoker()
await invoker.initialize()

# On message received
response = await invoker.query(message_with_context)
await send_response(response)

# On idle timeout
await invoker.shutdown()
```

**Implication**: Invest heavily in making the invoker rock-solid. Every capability we add here automatically benefits every daemon built on top of it. One brick, built perfectly, then everything stacks cleanly.

---

## 📋 Next Steps

### Immediate: Discord Integration
- [ ] Wire into Discord daemon (replace cold CC spawns)
- [ ] One invoker instance per daemon
- [ ] Route messages through `invoker.query()`

### Soon: Context Management
- [ ] Track context size (rough token count)
- [ ] Graceful restart when approaching limit
- [ ] Preserve continuity across restarts

### Future: Haven 2.0 Vision
- [ ] WebUI wrapper (nice interface instead of CLI)
- [ ] Multi-entity support (different invoker instances)
- [ ] n:n chat interface
- [ ] HTTP MCP transport option

---

## References

- **Research doc**: `/docs/reference/Keeping Claude Code CLI Persistent for Low-Latency Interactive Use.md`
- **SDK docs**: https://platform.claude.com/docs/en/agent-sdk/overview
- **SDK repo**: https://github.com/anthropics/claude-agent-sdk
- **Related issue**: #103 (MCP stdio servers in subprocess)
- **New issue**: #108 (Real-time cross-channel sync)

---

## Dependencies

```
claude-agent-sdk  # In project venv
```

---

*Last updated: 2026-01-21 by Lyra*
