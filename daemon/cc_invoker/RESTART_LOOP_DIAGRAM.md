# Restart Loop Bug - Before and After

## BEFORE (Buggy Behavior)

```
Session Start
├─ initialize()
│  ├─ Reset counters to 0
│  │  _prompt_tokens = 0
│  │  _response_tokens = 0
│  │  _turn_count = 0
│  │
│  └─ Send startup prompt
│     query("Reconstruct identity...")  ← BUG: This counts toward context!
│     _prompt_tokens += 250
│     _response_tokens += 300
│     _turn_count = 1
│
├─ Context after init: 550 tokens, 1 turn
│  (Already used 550/1000 of limit!)
│
├─ User query #1
│  query("What's the time?")
│  Context: 700 tokens, 2 turns
│
├─ User query #2
│  query("What are we working on?")
│  Context: 1050 tokens, 3 turns  ← Triggers restart!
│
├─ restart()
│  ├─ shutdown()
│  └─ initialize()
│     ├─ Reset counters to 0
│     └─ Send startup prompt
│        query("Reconstruct identity...")  ← BUG: Counts again!
│        Context: 550 tokens, 1 turn
│
├─ Context after restart: 550 tokens
│  (Immediately high again!)
│
├─ User query #3
│  query("Let's continue...")
│  Context: 700 tokens, 2 turns
│
├─ User query #4
│  query("What's next?")
│  Context: 1050 tokens, 3 turns  ← Triggers restart AGAIN!
│
└─ INFINITE LOOP! 🔥
```

## AFTER (Fixed Behavior)

```
Session Start
├─ initialize()
│  ├─ Reset counters to 0
│  │  _prompt_tokens = 0
│  │  _response_tokens = 0
│  │  _turn_count = 0
│  │
│  └─ Send startup prompt
│     query("Reconstruct identity...", count_tokens=False)  ← FIX!
│     (Tokens NOT counted toward context limit)
│
├─ Context after init: 0 tokens, 0 turns ✓
│  (Fresh session, full capacity!)
│
├─ User query #1
│  query("What's the time?")
│  Context: 150 tokens, 1 turn
│
├─ User query #2
│  query("What are we working on?")
│  Context: 500 tokens, 2 turns
│
├─ ... many more queries ...
│
├─ User query #7
│  query("...")
│  Context: 1050 tokens, 7 turns  ← Triggers restart
│
├─ restart()
│  ├─ shutdown()
│  └─ initialize()
│     ├─ Reset counters to 0
│     └─ Send startup prompt
│        query("Reconstruct identity...", count_tokens=False)  ← FIX!
│
├─ Context after restart: 0 tokens, 0 turns ✓
│  (Clean restart, no loop!)
│
├─ User query #8
│  query("Let's continue...")
│  Context: 150 tokens, 1 turn
│
└─ Normal operation continues... ✓
```

## Key Difference

### BEFORE (Bug)
- Startup prompt: **COUNTED** toward context limit
- After restart: Context = 550 tokens (already elevated)
- Only 450 tokens left for conversation
- Could restart again after just 1-2 queries
- **Result**: Infinite restart loop

### AFTER (Fix)
- Startup prompt: **NOT COUNTED** toward context limit
- After restart: Context = 0 tokens (truly fresh)
- Full 1000 tokens available for conversation
- Restart only after many queries
- **Result**: Normal operation

## Implementation

```python
# The fix: Add count_tokens parameter
async def query(
    self,
    prompt: str,
    count_tokens: bool = True  # Defaults to True for normal queries
) -> str:
    # Only count if flag is True
    if count_tokens:
        self._prompt_tokens += prompt_tokens
        self._response_tokens += response_tokens
        self._turn_count += 1

# Usage in initialize()
async def initialize(self):
    # ... setup ...

    # Send startup prompt WITHOUT counting toward context
    if self.startup_prompt:
        await self.query(self.startup_prompt, count_tokens=False)
```

## Why This Works

1. **Startup prompt establishes identity** - The prompt is still sent and gets a response
2. **But doesn't consume conversation budget** - Token counters remain at zero
3. **Restart truly resets** - After restart, session starts completely fresh
4. **No false triggers** - Only actual conversation queries count toward limit
5. **Backward compatible** - Default behavior unchanged, only internal calls use `count_tokens=False`

## Semantic Correctness

The fix also makes semantic sense:

- **Conversation context** = user queries + responses (what counts toward limit)
- **System overhead** = startup prompts, health checks (infrastructure, not conversation)

These are fundamentally different types of queries and should be tracked separately.
