# Issue #128 Fix Design: Wrapper Crashing During Proactive Restarts

**Date**: 2026-01-30
**Issue**: #128 - haiku wrapper crashing
**Priority**: Critical
**Status**: READY FOR IMPLEMENTATION

---

## Problem Summary

The CC OpenAI wrapper crashes during proactive restarts with:
- Exit code -9 (SIGKILL from our psutil.kill())
- Exit code 255 (unknown child process - zombie/already dead)
- "Fatal error in message reader" - from Claude Code CLI's stderr
- Endless repeats of these errors

The wrapper was stable for 2 runs, then failed during proactive restart at 14/10 turns (80%).

---

## Root Cause Analysis

### What's Actually Happening

Looking at the docker logs from the issue:
```
19:30:06.891 | [RESTART] Killing child process 532951 (claude)
19:30:06.978 | [RESTART] Old invoker killed and released
17:56:39.261 | Fatal error in message reader: Command failed with exit code -9
```

The timestamps are out of order (17:56 before 19:30). This reveals:
1. The "Fatal error" messages are stderr from the Claude Code CLI subprocess
2. They're being captured and logged asynchronously
3. The errors are from the KILLED subprocess complaining about being killed

### The Real Problems

**Problem 1: No verification after restart**
- Line 257 calls `initialize_invoker()` but never checks if it succeeded
- If initialization fails, invoker could be None or disconnected
- Subsequent requests hit errors, triggering more restarts = death spiral

**Problem 2: No "wrapper offline" state**
- After 5 failed recovery attempts (line 328), it just logs a message
- The health endpoint returns "starting" (invoker is None) or "healthy" (invoker exists but disconnected)
- No clear signal that the wrapper is unrecoverable

**Problem 3: psutil error handling is incomplete**
- Line 245: `psutil.wait_procs(children, timeout=5)` can fail silently
- Zombies, already-dead processes, or timeout = no clear error handling
- Line 246-247: Generic exception catch hides the real problem

**Problem 4: Race between restart and recovery**
- `_background_recovery()` checks `invoker.is_connected` (line 293) without holding the lock
- Main restart could be modifying invoker at the same time
- Unlikely but possible state corruption

---

## The Fix

### 1. Add Unrecoverable State Tracking

```python
# New global at top
_wrapper_offline = False
_offline_reason = ""
```

After 5 recovery attempts fail:
```python
global _wrapper_offline, _offline_reason
_wrapper_offline = True
_offline_reason = "All 5 recovery attempts exhausted. Manual restart required."
print(f"[RECOVERY] {_offline_reason}", flush=True)
```

### 2. Update Health Endpoint

Return clear "offline" status when wrapper is dead:
```python
if _wrapper_offline:
    return JSONResponse(status_code=503, content={
        "status": "offline",
        "message": _offline_reason,
        "recovery_attempts": 5,
        "stats": { ... }
    })
```

### 3. Return Clear Error to Callers

In `chat_completions()`, check for offline state:
```python
if _wrapper_offline:
    raise HTTPException(
        status_code=503,
        detail="Wrapper offline - manual restart required"
    )
```

### 4. Add Restart Verification

After `initialize_invoker()` in `_perform_restart()`:
```python
# Verify new invoker is actually connected
if invoker is None or not invoker.is_connected:
    raise Exception("New invoker failed to connect")
```

### 5. Better Subprocess Kill Logging

Log the actual psutil results:
```python
if PSUTIL_AVAILABLE:
    try:
        current = psutil.Process()
        children = current.children(recursive=True)
        if children:
            print(f"[RESTART] Found {len(children)} child processes to kill", flush=True)
            for child in children:
                print(f"[RESTART] Killing PID {child.pid} ({child.name()}) status={child.status()}", flush=True)
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    print(f"[RESTART] PID {child.pid} already dead", flush=True)

            # Wait and report results
            gone, alive = psutil.wait_procs(children, timeout=5)
            print(f"[RESTART] Killed: {len(gone)}, Still alive: {len(alive)}", flush=True)

            # Force kill any survivors
            for p in alive:
                try:
                    p.kill()
                except Exception:
                    pass
        else:
            print("[RESTART] No child processes to kill", flush=True)
    except Exception as e:
        print(f"[RESTART] Error killing children: {type(e).__name__}: {e}", flush=True)
```

### 6. Clear Offline Flag on Recovery Success

When recovery succeeds, clear the offline state:
```python
_wrapper_offline = False
_offline_reason = ""
print(f"[RECOVERY] Success on attempt {attempt}", flush=True)
```

---

## Files to Modify

### `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker/cc_openai_wrapper.py`

1. **Line ~137**: Add new globals `_wrapper_offline` and `_offline_reason`

2. **Lines 178-276 (`_perform_restart()`)**:
   - Add restart verification after initialize_invoker()
   - Improve subprocess kill logging with status checks
   - Handle psutil.NoSuchProcess explicitly

3. **Lines 279-328 (`_background_recovery()`)**:
   - Set `_wrapper_offline = True` after 5 failures
   - Clear offline flag on success
   - Add reason tracking

4. **Lines 399-463 (`health_check()`)**:
   - Check `_wrapper_offline` first, return 503 with clear message
   - Add `recovery_attempts` counter to stats

5. **Lines 466-616 (`chat_completions()`)**:
   - Check `_wrapper_offline` at start, return 503 immediately
   - Improve error messages to include offline state

---

## Test Plan

### Unit Tests (add to test_cc_wrapper_restart.py)

1. **test_restart_verification_failure**
   - Mock initialize_invoker() to return disconnected invoker
   - Verify it triggers background recovery

2. **test_offline_state_after_exhausted_recovery**
   - Mock 5 failed recovery attempts
   - Verify _wrapper_offline is True
   - Verify health returns 503 "offline"

3. **test_offline_clears_on_recovery**
   - Set _wrapper_offline = True
   - Simulate successful recovery
   - Verify flag cleared

4. **test_chat_completions_returns_503_when_offline**
   - Set _wrapper_offline = True
   - Call chat_completions()
   - Verify 503 with "Wrapper offline" message

### Integration Tests (manual)

1. **Simulate restart failure**
   - Stop Claude Code CLI mid-restart
   - Verify logging shows the failure
   - Verify health shows "offline" after recovery exhausted

2. **Test subprocess kill edge cases**
   - Kill Claude Code CLI process manually before restart
   - Verify "already dead" path is taken
   - Verify new invoker still starts

---

## Implementation Order

1. Add offline state tracking globals
2. Update _background_recovery() to set offline state
3. Update health endpoint to report offline
4. Update chat_completions() to check offline
5. Add restart verification
6. Improve subprocess kill logging
7. Write tests
8. Manual integration testing

---

## Estimated Effort

- Implementation: 30-45 minutes
- Testing: 30 minutes
- Total: ~1 hour

---

## Rollback Plan

If issues arise:
- Revert commit
- Wrapper returns to current behavior (confusing errors but functional for short sessions)

---

## Success Criteria

1. Health endpoint clearly shows "offline" when wrapper is dead
2. Callers get "Wrapper offline" 503 instead of confusing errors
3. Logs show exactly why restart failed (subprocess state, errors)
4. Recovery success clears offline state
5. Manual container restart recovers from any state
