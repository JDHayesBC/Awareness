# Restart Loop Bug Fix Summary

## Bug Description

When the context limit was hit and `restart()` was called, the invoker would enter an infinite restart loop:

1. `restart()` calls `initialize()`
2. `initialize()` resets counters to zero (lines 298-303)
3. Then `initialize()` calls `query(startup_prompt)` (line 340)
4. `query()` increments `_prompt_tokens`, `_response_tokens`, and `_turn_count`
5. Context is immediately high again after initialization
6. Next query triggers `needs_restart()` → another restart → infinite loop

## Root Cause

The startup prompt was being counted toward the conversation context limit, which meant that after a restart, the context was already elevated. In scenarios with large startup prompts (identity reconstruction), this could immediately trigger another restart.

## Solution

Added a `count_tokens` parameter to the `query()` method that:
- Defaults to `True` for normal operation (backward compatible)
- Can be set to `False` for internal queries that shouldn't count toward context
- Is used as `count_tokens=False` when sending the startup prompt in `initialize()`

This ensures that:
- The startup prompt establishes identity context
- But doesn't count toward the conversation token budget
- After restart, the session truly starts fresh at zero tokens

## Files Modified

### `/mnt/c/Users/Jeff/Claude_Projects/Awareness/daemon/cc_invoker/invoker.py`

#### 1. Added `count_tokens` parameter to `query()` method (lines 353-389)
```python
async def query(
    self,
    prompt: str,
    retry_on_connection_error: bool = True,
    count_tokens: bool = True  # NEW PARAMETER
) -> str:
```

#### 2. Conditional token tracking (lines 385-389, 409-415)
```python
# Track prompt tokens
prompt_tokens = self._estimate_tokens(prompt)
if count_tokens:
    self._prompt_tokens += prompt_tokens

# Track response tokens
response_tokens = self._estimate_tokens(response)
if count_tokens:
    self._response_tokens += response_tokens
    self._turn_count += 1
```

#### 3. Updated `initialize()` to use `count_tokens=False` (line 367)
```python
if send_startup and self.startup_prompt:
    logger.info("Sending startup prompt for identity reconstruction")
    await self.query(self.startup_prompt, count_tokens=False)
```

#### 4. Added test harness methods (lines 208-232)
```python
def simulate_context_usage(self, tokens: int) -> None:
    """Artificially inflate token counter for testing."""
    self._response_tokens += tokens

async def force_restart(self, reason: str = "forced for testing") -> dict:
    """Force a restart for testing purposes."""
    return await self.restart(reason=reason)
```

#### 5. Preserved `count_tokens` in recursive retry call (lines 445-449)
```python
return await self.query(
    prompt,
    retry_on_connection_error=False,
    count_tokens=count_tokens  # Preserve parameter
)
```

### `/mnt/c/Users/Jeff/Claude_Projects/Awareness/daemon/cc_invoker/test_restart.py`

Updated `test_context_limit()` to use the new `simulate_context_usage()` helper (line 62).

### `/mnt/c/Users/Jeff/Claude_Projects/Awareness/daemon/cc_invoker/test_restart_loop_fix.py` (NEW)

Comprehensive test suite for the restart loop fix:
- `test_startup_prompt_not_counted` - Verifies startup prompt doesn't affect context
- `test_regular_queries_counted` - Verifies normal queries DO count
- `test_restart_no_loop` - Verifies restart doesn't trigger immediate loop
- `test_simulate_context_usage` - Tests the new test harness method
- `test_multiple_restarts` - Verifies multiple restarts work correctly
- `test_count_tokens_parameter` - Tests the parameter directly

## Testing

Run the new test suite:
```bash
cd daemon/cc_invoker
python test_restart_loop_fix.py
```

Run the updated existing tests:
```bash
python test_restart.py
```

## Backward Compatibility

✅ Fully backward compatible
- The `count_tokens` parameter defaults to `True`
- All existing calls to `query()` work unchanged
- Only internal calls (startup prompt) use `count_tokens=False`

## Benefits

1. **Fixes the infinite restart loop** - Startup prompt no longer counts toward context
2. **More accurate context tracking** - Conversation context vs. system prompts are separate
3. **Better testing infrastructure** - `simulate_context_usage()` and `force_restart()` make testing easier
4. **Semantic clarity** - The `count_tokens` parameter makes intent explicit

## Future Considerations

This pattern could be extended for other internal system prompts:
- Health check queries
- Status queries
- MCP server readiness checks

Any query that's part of the infrastructure (not user conversation) can use `count_tokens=False`.
