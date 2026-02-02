# Project: MCP/stdio Bug Fixes

**Completed**: 2026-01-26
**Duration**: 4 phases, ~5 minutes

## What Was Built

Fixed two Python variable scoping bugs in pps/server.py that prevented MCP tools from working correctly via stdio interface. The HTTP endpoints were unaffected - these bugs were specific to the MCP stdio server.

**Bugs Fixed**:
1. Removed redundant `from datetime import datetime` import at line 2028 that shadowed the module-level import
2. Fixed undefined variable `last_crystal_time` → `last_summary_time` in get_turns_since_summary handler

Both MCP tools now work correctly when invoked via stdio interface.

## Key Decisions

- **Direct implementation**: Orchestrator implemented fixes directly rather than spawning coder agent
  - Rationale: Simple variable scoping fixes didn't require specialized agent
  - Trade-off: Faster execution, but less delegation practice

- **Comprehensive testing**: Created test script that actually invokes MCP tools
  - Rationale: Syntax checking alone wouldn't catch runtime errors
  - Result: Both tools verified working end-to-end

## Files Changed

- `pps/server.py` - Removed redundant import (line 2028), fixed variable name (lines 1492-1496)

## Commit

- Hash: `b66449c501ce688ee516e67901daa583ceafa53f`
- PR: N/A (direct commit to master)

## Friction Summary

| Type | Count | Examples |
|------|-------|----------|
| TOOL_FAILURE | 1 | Attempted external CLI for agent spawning |

**Total time lost**: ~2 minutes
**High-friction areas**: Initial agent spawning confusion (tried external CLI instead of Task tool)
**Process improvement suggestions**: Clarify in orchestrator instructions that Task tool from SDK is the correct method, not external CLI commands

## Lessons Learned

- Variable scoping bugs in Python can be subtle (redundant imports inside blocks)
- MCP tool testing requires actual invocation, not just syntax checking
- Direct implementation by orchestrator is acceptable for trivial fixes
- Pipeline friction logging helps identify process gaps (e.g., agent spawning method)
