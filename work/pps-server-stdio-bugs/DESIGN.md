# Design: Fix MCP/stdio Tool Bugs in pps/server.py

**Author**: orchestration-agent
**Date**: 2026-01-26
**Status**: Approved

---

## Problem Statement

Two Python variable scoping bugs in pps/server.py prevent MCP tools from working via stdio interface:
1. `ambient_recall` (via get_turns_since tool) fails with datetime scoping error
2. `get_turns_since_summary` fails with undefined variable error

HTTP endpoints work fine - these bugs are specific to the stdio MCP server.

---

## Root Cause Analysis

### Bug 1: datetime scoping error
**Location**: Line 2028 in `get_turns_since` handler
**Error**: "cannot access local variable 'datetime' where it is not associated with a value"
**Cause**: Redundant `from datetime import datetime` inside try block (line 2028) shadows module-level import (line 17). Creates scoping conflict.

### Bug 2: undefined variable error
**Location**: Lines 1492-1496 in `get_turns_since_summary` handler
**Error**: "name 'last_crystal_time' is not defined"
**Cause**: Variable name typo. Function defines `last_summary_time` but references non-existent `last_crystal_time`.

---

## Implementation Plan

1. Remove redundant datetime import at line 2028
2. Replace `last_crystal_time` with `last_summary_time` at lines 1492, 1494, 1496
3. Test both tools via MCP stdio interface (NOT HTTP)

---

## Files Affected

- `pps/server.py` - Remove line 2028, fix variable names on lines 1492-1496

---

## Testing Strategy

**MCP Tool Testing** (not HTTP endpoints):
1. Invoke `get_turns_since` via MCP stdio to verify datetime fix
2. Invoke `get_turns_since_summary` via MCP stdio to verify variable name fix
3. Verify both return data without errors

Use MCP inspector or direct stdio invocation, NOT curl.

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking HTTP server | High | Only touch pps/server.py, not server_http.py |
| Introducing new bugs | Medium | Simple variable fixes, thorough testing |
