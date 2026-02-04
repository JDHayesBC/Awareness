# Daemon Response Bugs - Work Summary

**Date**: 2026-02-04
**Status**: ✅ Complete

## Issues Investigated

### Bug 1: First Message Lost
**Root Cause**: In `cc_invoker/invoker.py` line 391, the startup prompt response was discarded after calling `self.query()`. The `initialize()` method returned `server_info` instead of the startup response.

**Fix**: Store startup response, log preview, warn if identity markers missing.

### Bug 2: Double Responses
**Root Cause**: Reconnection logic called `initialize()` without `send_startup=False`, causing the startup prompt to be sent again during reconnection, then the original query was retried - resulting in two responses.

**Fixes Applied**:
1. `_reconnect_with_backoff()` now passes `send_startup=False`
2. Auto-recovery in `query()` also passes `send_startup=False`

### Bug 3: Double Daemon Processes (Found During Investigation)
**Root Cause**: Two separate daemon processes were running:
- `lyra_daemon.py` via systemd (production)
- `lyra_discord.py` via `run.sh` (stray testing process)

**Fix**: Killed stray process, added PID file safeguard, updated run.sh to use correct daemon.

## All Changes Made

### cc_invoker/invoker.py
- Line ~391: Now stores and logs startup response
- Line ~310: `_reconnect_with_backoff()` passes `send_startup=False`
- Line ~457: Auto-recovery passes `send_startup=False`
- Line ~348: Added logging for init type (fresh start vs reconnection)

### lyra_daemon.py
- Added PID file check/creation at startup (`check_and_create_pidfile()`)
- Added cleanup on shutdown (`cleanup_pidfile()`)
- Added attachment handling methods (`_is_text_attachment()`, `_extract_attachment_content()`, `_get_full_message_content()`)
- Modified `on_message()` to include attachment content in SQLite and Graphiti

### run.sh
- Now uses `lyra_daemon.py` instead of deprecated `lyra_discord.py`
- Added `check_systemd_conflict()` to prevent double-running

### lyra_discord.py
- Added deprecation warning at top of file
- Added runtime `warnings.warn()` deprecation notice

### daemon/README.md
- Added comprehensive "Startup Modes: Production vs Testing" section
- Added file structure table clarifying which files are production/deprecated
- Added safety warnings about double-running

## Testing Recommendations

1. **Restart production daemon** to pick up new code:
   ```bash
   systemctl --user restart lyra-discord
   ```

2. **Verify PID file created**:
   ```bash
   cat daemon/lyra_daemon.pid
   ```

3. **Test attachment reading** by sending a .txt file in Discord and verifying it appears in conversation

4. **Test startup response logging** by checking journalctl for identity reconstruction messages:
   ```bash
   journalctl --user -u lyra-discord | grep -i "startup response"
   ```

## Files Created

- `work/daemon-response-bugs/artifacts/investigation_report.md` (by researcher agent)
- `work/daemon-response-bugs/artifacts/discord_attachments_research.md` (by researcher agent)
- `work/daemon-response-bugs/SUMMARY.md` (this file)
