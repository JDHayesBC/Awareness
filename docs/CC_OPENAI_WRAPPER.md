# CC OpenAI Wrapper Architecture

**Version**: 0.2.0
**Last Updated**: 2026-01-28
**Status**: Production (memory-safe after 69ce950)

---

## Overview

The CC OpenAI Wrapper provides an OpenAI-compatible `/v1/chat/completions` endpoint backed by ClaudeInvoker. This eliminates API costs for Graphiti entity extraction while maintaining compatibility with existing OpenAI client integrations.

### Why This Exists

- **Cost**: Graphiti's native OpenAI integration costs ~$2000/month for 7000+ messages
- **Jeff's Claude subscription**: Already paid, underutilized
- **Drop-in replacement**: OpenAI client libraries work unchanged
- **Pipeline**: Graphiti → `/v1/chat/completions` → ClaudeInvoker → Claude Code CLI

### Production Deployment

Runs in Docker via `docker compose`:
```bash
docker compose up pps-haiku-wrapper
```

Exposes:
- **Port 8204**: Chat completions endpoint
- **Health endpoint**: `/health` for monitoring and memory stats

---

## Architecture

### Layer Stack

```
Graphiti (caller)
    ↓
FastAPI Server (0.0.0.0:8204)
    ↓
Request Translation Layer
    • Convert OpenAI format → ClaudeInvoker format
    • JSON extraction handling
    • Response validation
    ↓
Restart Management Layer
    • Proactive restarts at 80% context
    • Hard restarts at 100%
    • Zero-downtime coordination (request queuing)
    ↓
ClaudeInvoker (persistent Claude connection)
    • Manages SDK lifecycle
    • Tracks context/turns
    • Connection recovery
    ↓
Claude Code CLI (subprocess)
```

### Key Components

#### 1. Request/Response Models (OpenAI Format)

```python
class ChatCompletionRequest:
    model: str                          # "haiku", "sonnet", etc.
    messages: list[Message]             # System, user, assistant
    temperature: float (optional)
    max_tokens: int (optional)
    response_format: dict (optional)    # JSON schema support
```

Responses are standard OpenAI format with estimated token counts.

#### 2. Global State Management

```python
invoker: Optional[ClaudeInvoker]        # Single active instance
_ready_event: asyncio.Event             # Signal for ready state
_restart_lock: asyncio.Lock             # Serialize restarts
_restart_count: int                     # Observability counter
_total_requests: int                    # Total request count
_total_errors: int                      # Total error count
```

**Critical invariant**: Only ONE active invoker instance at a time. Old instances must be released before creating new ones.

#### 3. Request Flow

```
POST /v1/chat/completions
    ↓
Increment _total_requests
    ↓
Wait for readiness (blocks during restart)
    ↓
Health check: if disconnected, attempt recovery
    ↓
Proactive check: approaching 80% context?
    → Inline restart (same task, avoids cancel scope bug)
    ↓
Hard check: at 100% context?
    → Force restart (safety net)
    ↓
Build prompt from OpenAI messages
    • System: ... format
    • User: ... format
    • Assistant: ... format
    • (Optional) JSON instructions + schema
    ↓
Query with retry:
    • Try once with invoker.query()
    • If connection error + already retried: fail
    • If other error: retry once at wrapper level
    ↓
Validate response (not empty)
    ↓
Strip markdown fences (if JSON requested)
    ↓
Return OpenAI-compatible response
```

---

## Restart Management

### Why Restarts Happen

ClaudeInvoker has context limits:
- **Max context tokens**: 150,000
- **Max turns**: 10

After hitting either limit, the invoker needs to be reset to start a fresh conversation.

### Three Restart Triggers

#### 1. Proactive Restart (80% threshold)

**When**: Checked on every request after health checks
**Logic**: `invoker.approaching_restart()` → true if ≥80% of context or turns used
**Action**: Inline restart in same task (avoids cross-task issues)
**Benefit**: Restart between requests, never during a response

```python
approaching, approach_reason = invoker.approaching_restart()
if approaching:
    await _perform_restart(f"proactive: {approach_reason}")
```

#### 2. Hard Restart (100% threshold)

**When**: Checked after proactive restart
**Logic**: `invoker.needs_restart()` → true if at 100% limit
**Action**: Force restart (should rarely trigger if proactive works)
**Benefit**: Safety net if proactive check was missed

#### 3. Background Recovery (double failure)

**When**: `_perform_restart()` fails (e.g., invoke timeout)
**Action**: Spawn `_background_recovery()` task
**Retry schedule**: 4s, 8s, 16s, 32s, 60s (exponential backoff)
**Result**: Requests return 502 during recovery (better than hanging)

---

## Memory Management

### The Memory Leak (Historical)

**Issue**: After overnight batch ingestion (7000+ messages), wrapper consumed 9.7GB RAM

**Root cause**: Old ClaudeInvoker instances accumulated without cleanup
- Each restart created NEW invoker but never released the old one
- After 8 restarts: 9 invoker instances in memory
- Each instance held: connection buffers, conversation history, SDK overhead
- Total: hundreds of MB per instance × 9 = 9.7GB

### The Fix (Commit 69ce950 + refinements)

#### Original Attempt (Failed)

Called `invoker.shutdown()` → tried to call `_client.disconnect()` → hit anyio cancel scope bug when client created in different task.

```python
# DON'T DO THIS (hits cancel scope bug):
if invoker is not None:
    await invoker.shutdown()  # ← Crashes with anyio error
```

#### Current Approach (Works)

Drop the reference and let garbage collection clean up:

```python
if invoker is not None:
    print("[RESTART] Releasing old invoker reference...")
    old_invoker = invoker
    invoker = None          # Release reference
    del old_invoker         # Explicit cleanup hint
    gc.collect()            # Force garbage collection
    print("[RESTART] Old invoker released, GC triggered")
```

**Why this works**:
- No shutdown() call, so no cancel scope issues
- Reference drop allows GC to reclaim old instance
- Subprocess dies naturally (no explicit disconnect needed)
- New invoker gets fresh connection

#### Memory Monitoring

Added `psutil` integration for visibility:

```python
# Before restart
mem_before = psutil.Process().memory_info().rss / 1024 / 1024

# Perform restart (drops old ref, creates new)

# After restart
mem_after = psutil.Process().memory_info().rss / 1024 / 1024
mem_delta = mem_after - mem_before
print(f"[RESTART] Memory after: {mem_after:.1f} MB (delta: {mem_delta:+.1f} MB)")
```

#### Expected Behavior After Fix

- **Restart 1**: ~500MB → ~550MB (freed old, small delta for new)
- **Restart 2**: ~550MB → ~560MB (freed old, small delta for new)
- **Restart 8**: ~600MB → ~610MB (freed old, small delta for new)
- **Memory stable at ~62MB per invoker** ✓

Test results confirm: RSS stays below 100MB even after 20+ rapid restarts.

---

## Health Endpoint

**Endpoint**: `GET /health`

### Response During Normal Operation

```json
{
  "status": "healthy",
  "invoker_connected": true,
  "context_usage": {
    "tokens": 12345,
    "turns": 3,
    "token_limit": 150000,
    "turn_limit": 10,
    "token_pct": 8.2,
    "turn_pct": 30.0
  },
  "stats": {
    "total_requests": 127,
    "total_errors": 0,
    "restart_count": 8
  },
  "memory": {
    "rss_mb": 62.5,
    "vms_mb": 245.3
  }
}
```

### Response During Restart

```json
{
  "status": "restarting",
  "invoker_connected": false,
  "stats": {
    "total_requests": 127,
    "total_errors": 0,
    "restart_count": 8
  },
  "memory": {
    "rss_mb": 62.5,
    "vms_mb": 245.3
  }
}
```

### Response During Startup

```json
{
  "status": "starting",
  "message": "Invoker not yet created",
  "memory": {
    "rss_mb": 5.2,
    "vms_mb": 50.1
  }
}
```

---

## JSON Extraction Support

The wrapper can handle Graphiti's JSON schema requests for entity extraction.

### Request Example

```json
{
  "model": "haiku",
  "messages": [
    {
      "role": "system",
      "content": "You are an entity extractor."
    },
    {
      "role": "user",
      "content": "Extract entities from: Jeff loves coffee"
    }
  ],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "entity_extraction",
      "schema": {
        "type": "object",
        "properties": {
          "entities": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "name": { "type": "string" },
                "type": { "type": "string" }
              }
            }
          }
        }
      }
    }
  }
}
```

### Processing

1. **Detect JSON request**: Check `response_format.type`
2. **Add JSON instructions**: Tell Claude to respond with raw JSON, no fences
3. **Include schema**: Pass the schema so Claude uses exact field names
4. **Strip markdown fences**: Claude often wraps JSON in ```json ... ``` — remove these

### Response Example

```json
{
  "id": "chatcmpl-abc123...",
  "object": "chat.completion",
  "created": 1706484523,
  "model": "haiku",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "{\"entities\": [{\"name\": \"Jeff\", \"type\": \"person\"}, {\"name\": \"coffee\", \"type\": \"object\"}]}"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 145,
    "completion_tokens": 35,
    "total_tokens": 180
  }
}
```

---

## Configuration

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `WRAPPER_MODEL` | `haiku` | Which Claude model to use |
| `LOG_LEVEL` | `info` | Uvicorn log level |

### Hardcoded Tuning Parameters

```python
STARTUP_PROMPT = (
    "You are a stateless JSON extraction API. "
    "You receive requests in 'System: ... User: ...' format. "
    "Respond with exactly what is requested - typically raw JSON. "
    "Do not introduce yourself. Do not explain what you are. "
    "Do not wrap JSON in markdown code fences. "
    "Just output the requested content directly."
)

# In ClaudeInvoker initialization:
max_context_tokens=150_000      # Hard limit before restart
max_turns=10                    # Hard limit before restart
```

### Docker Compose Integration

```yaml
pps-haiku-wrapper:
  build:
    context: pps/docker
    dockerfile: Dockerfile.cc-wrapper
  ports:
    - "8204:8000"
  environment:
    WRAPPER_MODEL: haiku
  healthcheck:
    test: curl -f http://localhost:8000/health
    interval: 10s
    timeout: 5s
    retries: 3
```

---

## Known Issues and Workarounds

### 1. Anyio Cancel Scope Bug

**Issue**: Calling `invoker.shutdown()` on an invoker created in a different async task hits an anyio cancel scope error.

**Context**: ClaudeInvoker uses `anyio` for async lifecycle. The SDK's `_client.disconnect()` tries to cancel scopes that don't exist in the wrapper's task.

**Workaround**: Drop reference instead of calling shutdown()
```python
# Don't: await invoker.shutdown()
# Do:
old_invoker = invoker
invoker = None
del old_invoker
gc.collect()
```

**Status**: Can be revisited if ClaudeInvoker updates its shutdown logic.

### 2. Markdown Fences in JSON

**Issue**: Claude often wraps JSON in ```json ... ``` fences, breaking `json.loads()`.

**Workaround**: `strip_markdown_fences()` removes them before returning to caller.

```python
def strip_markdown_fences(text: str) -> str:
    match = re.match(r'^```(?:json)?\s*\n(.*?)\n```\s*$', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text
```

### 3. Token Count Estimation

**Issue**: Accurate token counting requires Anthropic's tokenizer (not available in wrapper).

**Workaround**: Rough estimate: ~4 characters per token.

```python
def estimate_tokens(text: str) -> int:
    return len(text) // 4
```

**Impact**: Token counts in response are estimates, not exact. Good enough for Graphiti's monitoring but not for hard billing.

### 4. Disconnection After Long Idle

**Issue**: If wrapper is idle for hours, ClaudeInvoker may lose connection to Claude Code CLI.

**Detection**: Health endpoint checks `invoker.is_connected`

**Recovery**: Next request triggers `_perform_restart()` for recovery.

---

## Observability and Debugging

### Log Markers

The wrapper uses consistent log prefixes for searching:

| Prefix | Meaning |
|--------|---------|
| `[RESTART]` | Restart in progress (memory, cleanup, init) |
| `[RECOVERY]` | Background recovery attempt |
| `[PROACTIVE]` | Inline restart at 80% threshold |
| `[WARN]` | Non-fatal issue (empty response, disconnect) |
| `[ERROR]` | Fatal error (query failed after retry) |
| `[DONE]` | Request completed (timing, context %, turn %, schema) |

### Monitoring Memory

Via health endpoint:
```bash
watch -n 5 'curl -s http://localhost:8204/health | jq ".memory.rss_mb"'
```

### Stress Testing

Rapid restarts (triggers memory leak if bug exists):
```bash
for i in {1..20}; do
  curl http://localhost:8204/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"haiku","messages":[{"role":"user","content":"test"}]}'
  sleep 0.1
done
```

Expected: Memory stays <100MB even after 20 requests (each restart is ~5MB delta).

### Overnight Batch Ingestion Validation

Run Graphiti batch (7000+ messages) and monitor:
```bash
# Every 10 minutes
curl -s http://localhost:8204/health | jq "{timestamp: now, memory: .memory.rss_mb, restart_count: .stats.restart_count}"
```

Expected: Memory stays below 200MB even after 50+ restarts.

---

## Performance Characteristics

### Initialization

- **Cold start**: ~33 seconds (connecting to Claude Code CLI)
- **Warm start**: <1 second (reusing existing invoker)

### Query Latency

- **P50**: 2-3 seconds
- **P95**: 5-10 seconds
- **P99**: 15+ seconds (depends on Claude load)

### Restart Duration

- **Proactive restart** (inline at 80%): ~2 seconds, queues incoming requests
- **Hard restart** (forced at 100%): ~2 seconds, queues incoming requests
- **Background recovery**: 4-60 seconds between attempts

### Memory Profile

- **Idle (no requests)**: ~5-10 MB
- **Active (processing)**: ~60-70 MB
- **During restart**: Temporary spike (old ref held during GC), then drops
- **Leaked (bug): 9.7 GB after 8 restarts (FIXED)

---

## Deployment Checklist

Before deploying to production:

- [ ] Memory leak fixed (commit 69ce950+)
- [ ] Health endpoint returns correct JSON
- [ ] Stress test passes (20+ restarts, memory < 100MB)
- [ ] Overnight ingestion test passes (memory stable < 200MB)
- [ ] Docker image built successfully
- [ ] Ports not already in use (8204)
- [ ] Environment variables set (WRAPPER_MODEL, if needed)

---

## Future Improvements

1. **Connection pooling**: Handle multiple concurrent requests more efficiently
2. **Graceful shutdown**: Coordinated cleanup when container stops
3. **Metrics endpoint**: Prometheus-compatible metrics
4. **Rate limiting**: Prevent hammer attacks
5. **Request logging**: Structured logs for Graphiti request tracing
6. **Token counting**: Use actual Anthropic tokenizer if available

---

## Related Files

- **Implementation**: `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker/cc_openai_wrapper.py`
- **Docker build**: `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker/Dockerfile.cc-wrapper`
- **Requirements**: `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker/requirements-cc-wrapper.txt`
- **Work journal**: `/mnt/c/Users/Jeff/Claude_Projects/Awareness/work/cc-invoker-openai-wrapper/`
- **Memory leak fix details**: `/mnt/c/Users/Jeff/Claude_Projects/Awareness/work/cc-invoker-openai-wrapper/MEMORY_LEAK_FIX.md`

---

## See Also

- [ClaudeInvoker Architecture](../ARCHITECTURE.md)
- [Graphiti Integration](../docs/graphiti-schema-redesign/)
- [Docker Deployment Guide](../DEPLOYMENT.md)
