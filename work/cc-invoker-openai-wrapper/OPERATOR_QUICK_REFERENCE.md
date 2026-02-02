# CC OpenAI Wrapper - Operator Quick Reference

**For**: DevOps, SREs, and anyone running/monitoring the wrapper in production

---

## Deployment

```bash
# Start the wrapper
docker compose up pps-haiku-wrapper

# Check status
curl http://localhost:8204/health | jq .

# Logs
docker compose logs -f pps-haiku-wrapper
```

---

## Health Checks

### Quick Status

```bash
curl -s http://localhost:8204/health | jq .
```

**Expect**: `"status": "healthy"` and `"invoker_connected": true`

### Memory Monitoring

```bash
# One-time check
curl -s http://localhost:8204/health | jq ".memory.rss_mb"

# Continuous monitoring (every 5 seconds)
watch -n 5 'curl -s http://localhost:8204/health | jq ".memory.rss_mb"'

# Dashboard with multiple stats
watch -n 5 'curl -s http://localhost:8204/health | jq "{status: .status, memory: .memory.rss_mb, restart_count: .stats.restart_count, errors: .stats.total_errors}"'
```

**Healthy range**: 50-100 MB for idle, up to 200 MB during batch ingestion

**Red flag**: Growing continuously or > 500 MB

### Context Usage

```bash
curl -s http://localhost:8204/health | jq ".context_usage"

# Example output:
# {
#   "tokens": 12345,
#   "turns": 3,
#   "token_limit": 150000,
#   "turn_limit": 10,
#   "token_pct": 8.2,
#   "turn_pct": 30.0
# }
```

**Note**: Proactive restarts trigger at 80%, hard restarts at 100%

---

## Restart Behavior

### Proactive Restart (Normal)

Wrapper automatically restarts when reaching 80% context or turn limit. **This is expected and healthy.**

**In logs**: `[PROACTIVE] Inline restart: ...`

**No action needed**: Wrapper queues incoming requests during restart.

### Hard Restart (Safety Net)

If proactive check somehow missed, wrapper force-restarts at 100%.

**In logs**: `[RESTART] Starting: ...` (numbered in restart_count)

**Expected**: Rarely happens if proactive works

### Background Recovery (Double Failure)

If restart itself fails, background recovery retries with exponential backoff.

**In logs**: `[RECOVERY] Attempt N/5 in ...s`

**What to do**:
- Check Docker resources (CPU, memory, disk)
- Check Claude Code CLI is running
- Review recent errors in logs

---

## Common Issues and Fixes

### Memory Growing

**Symptom**: RSS memory climbing over time

**Check**:
```bash
# Get memory trend
for i in {1..10}; do
  curl -s http://localhost:8204/health | jq "{now: $(date +%s), rss_mb: .memory.rss_mb}"
  sleep 10
done
```

**If growing after every request**: Possible memory leak (should not happen after 69ce950)
- Check wrapper version (should be latest)
- Restart wrapper: `docker compose restart pps-haiku-wrapper`
- Monitor after restart

**If stable**: Expected behavior, not a problem

### High Error Count

**Check**: `curl -s http://localhost:8204/health | jq ".stats.total_errors"`

**Causes**:
1. Claude Code CLI crashed (check daemon logs)
2. Network timeout (check connectivity)
3. Query timeout (Claude slow or overloaded)

**Fix**:
```bash
# Try a simple health check
curl http://localhost:8204/health

# If that works, try a simple query
curl http://localhost:8204/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"haiku","messages":[{"role":"user","content":"say hello"}]}'

# If that fails, restart wrapper
docker compose restart pps-haiku-wrapper
```

### Slow Responses

**Expected**: 2-3 seconds for typical requests, up to 15+ seconds during high load

**If stuck > 30 seconds**: Likely timeout
- Check health endpoint: `curl http://localhost:8204/health`
- If health endpoint responds: Query is just slow (Claude side)
- If health endpoint times out: Wrapper is hung (restart needed)

**Restart**:
```bash
docker compose restart pps-haiku-wrapper
```

### Memory Spike During Restart

**Expected**: Memory temporarily goes up during cleanup/init

**Normal**: Spike should be < 20 MB and settle within 2 seconds

**Example log**:
```
[RESTART] Memory before: 62.0 MB
[RESTART] Memory after: 68.5 MB (delta: +6.5 MB)
```

This is normal and indicates memory is being properly reclaimed.

---

## Stress Testing

Use this to validate wrapper health:

```bash
#!/bin/bash
# Rapid fire 20 requests to trigger restarts
for i in {1..20}; do
  echo "Request $i..."
  curl -s http://localhost:8204/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"haiku","messages":[{"role":"user","content":"test"}]}' > /dev/null
  sleep 0.1
done

# Check memory didn't leak
curl -s http://localhost:8204/health | jq "{rss_mb: .memory.rss_mb, restart_count: .stats.restart_count}"
```

**Expected outcome**: Memory < 100 MB, restart_count increased by ~5 (since each test hits restart at ~80%)

---

## Log Markers (For Grep)

Use these to search logs for specific events:

| Marker | Meaning | Example |
|--------|---------|---------|
| `[RESTART]` | Restart event | `[RESTART] Starting: proactive: ...` |
| `[RECOVERY]` | Background recovery | `[RECOVERY] Attempt 1/5 in 4s...` |
| `[PROACTIVE]` | Inline restart (80%) | `[PROACTIVE] Inline restart: turn_pct=80` |
| `[WARN]` | Non-fatal issue | `[WARN] Empty response, retrying...` |
| `[ERROR]` | Fatal error | `[ERROR] Query failed after retry: ...` |
| `[DONE]` | Request completed | `[DONE] 2.3s \| ctx=12345/150000...` |

```bash
# Find all restarts
docker compose logs pps-haiku-wrapper | grep "\[RESTART\]"

# Find all errors
docker compose logs pps-haiku-wrapper | grep "\[ERROR\]"

# Find memory patterns
docker compose logs pps-haiku-wrapper | grep "Memory"
```

---

## Monitoring Integration

### Prometheus Scrape (Not Yet Implemented)

Future: `/metrics` endpoint for Prometheus

For now, poll health endpoint:

```bash
# Every 30 seconds, log memory
watch -n 30 'curl -s http://localhost:8204/health | jq ".memory.rss_mb" >> memory.log'
```

### Graphiti Integration

Graphiti queries this wrapper for entity extraction. If batch ingestion is slow:

1. Check wrapper health: `curl http://localhost:8204/health`
2. Check memory: should be < 200 MB during batch
3. Check restart count: should grow smoothly, not spike

---

## Runbooks

### "Wrapper is stuck / not responding"

1. Health check: `curl http://localhost:8204/health` (30s timeout)
2. If timeout or hangs: Restart
   ```bash
   docker compose restart pps-haiku-wrapper
   ```
3. Wait 60 seconds
4. Verify: `curl http://localhost:8204/health`
5. If still broken: Check Claude Code CLI daemon is running

### "Memory is growing"

1. Get trend:
   ```bash
   curl -s http://localhost:8204/health | jq ".memory.rss_mb"
   ```
2. Wait 1 minute, check again
3. If still growing: Likely active leak (escalate to developer)
4. Temporary fix: Restart wrapper
   ```bash
   docker compose restart pps-haiku-wrapper
   ```

### "Error rate is high"

1. Check what's failing:
   ```bash
   docker compose logs pps-haiku-wrapper | grep "\[ERROR\]" | tail -20
   ```
2. Common causes:
   - Claude Code CLI crashed → restart daemon
   - Network timeout → check connectivity
   - Query timeout → check Claude load
3. Simple test:
   ```bash
   curl http://localhost:8204/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model":"haiku","messages":[{"role":"user","content":"test"}]}'
   ```

---

## Performance Baseline

Keep these in mind for detecting anomalies:

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| RSS Memory | 50-100 MB | 150-200 MB | > 300 MB |
| Response Time | 2-5 sec | 5-15 sec | > 30 sec timeout |
| Error Rate | 0-1% | 1-5% | > 5% |
| Restart Count | Grows ~50/hour during batch | N/A | Stuck (not growing) |

---

## When to Escalate

**Escalate to developer if**:
1. Memory constantly growing (> 200 MB and still rising)
2. Error rate stays high after restart
3. Restart loop happening (recovering endlessly)
4. Health endpoint unreachable for > 1 minute

**Information to provide**:
1. When did the issue start?
2. What was running? (Graphiti batch size, test name, etc.)
3. Current health endpoint output
4. Last 50 lines of wrapper logs
5. Memory trend (if applicable)

---

## Documentation References

- **Full architecture**: `docs/CC_OPENAI_WRAPPER.md` (complete, detailed)
- **Memory leak details**: `work/cc-invoker-openai-wrapper/MEMORY_LEAK_FIX.md`
- **Code**: `pps/docker/cc_openai_wrapper.py`
- **Docker**: `pps/docker/Dockerfile.cc-wrapper`

---

## Quick Checklist: Is Wrapper Healthy?

```bash
# Run this script
curl -s http://localhost:8204/health | jq '{
  status: .status,
  connected: .invoker_connected,
  memory_mb: .memory.rss_mb,
  error_count: .stats.total_errors,
  restart_count: .stats.restart_count,
  context_pct: .context_usage.token_pct,
  turn_pct: .context_usage.turn_pct
}'

# All should be:
# - status: "healthy" or "restarting"
# - connected: true (unless "restarting")
# - memory_mb: 50-200
# - error_count: low (< 10)
# - restart_count: growing (expected)
# - context_pct: varies (0-100%)
# - turn_pct: varies (0-100%)
```

If anything looks wrong, start with `docker compose restart pps-haiku-wrapper`.
