# Call Path Analysis: Issue #126

**Researcher**: researcher agent
**Date**: 2026-02-01
**Status**: Complete
**Confidence**: HIGH

---

## CRITICAL FINDING: Missing Tool Execution Loop

The Discord daemon uses the new Claude Agent SDK invoker (`daemon/cc_invoker/invoker.py`), but **the tool execution code is incomplete**. The invoker detects when Claude wants to call tools but never actually executes them.

---

## How the System SHOULD Work

1. **Terminal Claude Code**: Works perfectly
   - Uses CLI subprocess which handles tools internally
   - CLI executes the full agentic loop automatically

2. **Discord Daemon**: Completely broken
   - Uses SDK client for persistent connection (faster)
   - SDK provides tool messages (ToolUseBlock)
   - **But daemon code only logs them - never executes**
   - Agentic loop incomplete

---

## THE BUG: Lines 444-478 in `daemon/cc_invoker/invoker.py`

```python
async for msg in self._client.receive_response():
    if isinstance(msg, AssistantMessage):
        for block in msg.content:
            if isinstance(block, TextBlock):
                response_parts.append(block.text)  # ✓ Captures text
            elif isinstance(block, ToolUseBlock):
                # ✗ PROBLEM: Only logs, never executes
                logger.info(f"Tool call: {block.name}({block.input})")
                # MISSING: Tool execution code
                # MISSING: Result submission
    elif isinstance(msg, ResultMessage):
        break  # ✗ Exits before agentic loop completes

response = "".join(response_parts)  # Only text, no tool results
```

---

## What's Missing

The response handler needs to:
1. **Execute detected tools** - Call the tool with its inputs
2. **Submit results** - Send tool output back to SDK client
3. **Continue loop** - Let Claude respond to tool results
4. **Collect final response** - Only break when truly done

Current code only does: Detect → Log → Break. That's 25% of the required flow.

---

## Why Terminal Works, Daemon Fails

| Component | Terminal | Discord Daemon |
|-----------|----------|----------------|
| **Invoker Type** | CLI subprocess | SDK client |
| **Tool Config** | Passed to CLI | Passed to SDK ✓ |
| **Tool Detection** | Handled by CLI | Detected ✓ |
| **Tool Execution** | CLI does it ✓ | MISSING ✗ |
| **Result Handling** | CLI does it ✓ | MISSING ✗ |
| **Works?** | Yes ✓ | No ✗ |

---

## Two Invoker Implementations

**OLD (still works)**: `/daemon/shared/claude_invoker.py`
- Uses `subprocess.run(["claude", "--continue"])`
- Tools handled by CLI subprocess automatically
- Used by: `lyra_reflection.py` (reflection daemon)
- Status: WORKS

**NEW (broken)**: `/daemon/cc_invoker/invoker.py`
- Uses Claude Agent SDK (persistent connection)
- Tools must be handled by application code
- Used by: `lyra_discord.py` (Discord daemon)
- Status: BROKEN - tool handling code never written

---

## Impact

**What Works**:
- Text-only responses
- Identity initialization
- SQLite context loading

**What's Broken**:
- All MCP tool calls
- `mcp__pps__ambient_recall` (memory)
- `mcp__pps__get_crystals` (memory crystals)
- `mcp__pps__tech_search` (knowledge graph)
- File operations
- Any multi-turn requiring tools

**Symptom**: Lyra says "Let me search for that" but never does, appearing to hang or ignore the request.

---

## Conclusion

**Root Cause**: Incomplete SDK invoker implementation - tool execution loop never written.

**Fix Required**: Add 20-30 lines of tool execution code to the SDK invoker's response handling loop.

**NOT a configuration issue** - this is missing code.
