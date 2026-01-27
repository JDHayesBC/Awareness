# Bug Location: ambient_recall datetime scoping issue

## File
`/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker/server_http.py`

## Problem
Variable shadowing in `get_turns_since()` and `get_turns_around()` functions.

## Root Cause
The module imports `from datetime import datetime` at line 17 (top of file).

However, in two functions there are redundant local imports that create scoping issues:

### Location 1: `get_turns_since()` (lines 2005-2023)
- Line 2007: `from datetime import datetime` (inside try block)
- Line 2008: Uses `datetime.fromisoformat()`
- Line 2022: **Another** `from datetime import datetime` (inside nested try block)
- Line 2023: Uses `datetime.fromisoformat()`

Python sees the import on line 2022 and treats `datetime` as a local variable in that scope. But line 2008 tries to reference it before line 2022 defines it.

### Location 2: `get_turns_around()` (lines 2084-2088)
- Line 2086: `from datetime import datetime` (inside try block)
- Line 2087: Uses `datetime.fromisoformat()`

Same pattern - redundant import.

## Fix
Remove ALL the redundant `from datetime import datetime` statements inside the functions. The module-level import on line 17 is sufficient.

**Lines to delete:**
- Line 2007
- Line 2022
- Line 2086

The `datetime` import at the top of the file (line 17) will handle all uses.

## Why This Broke
Likely these functions were copy-pasted or refactored, and someone added the local imports "to be safe" without realizing:
1. The module already imports datetime
2. Duplicate imports inside functions create scoping issues

## Testing
After fix, call `mcp__pps__ambient_recall` with context "startup" and verify it completes without error.
