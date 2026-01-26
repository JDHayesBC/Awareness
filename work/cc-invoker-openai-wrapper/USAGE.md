# OpenAI-Compatible Wrapper - Usage Guide

**Status**: Implementation complete, ready for testing
**Created**: 2026-01-25

---

## What This Is

A FastAPI wrapper that translates OpenAI `/v1/chat/completions` requests into ClaudeInvoker queries. This lets Graphiti use Claude instead of OpenAI for entity extraction, eliminating API costs.

**Files created**:
- `pps/docker/cc_openai_wrapper.py` - FastAPI server
- `pps/docker/Dockerfile.cc-wrapper` - Container build
- `pps/docker/requirements-cc-wrapper.txt` - Dependencies
- `pps/docker/docker-compose.yml` - Updated with pps-cc-wrapper service

---

## Testing Locally (No Docker)

**1. Test ClaudeInvoker directly:**
```bash
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
python3 pps/docker/test_cc_wrapper_local.py
```

Expected output:
- Initialization takes ~33s
- Query succeeds and returns extraction result
- Context stats show token usage
- Cleanup completes

**2. Run wrapper server locally:**
```bash
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
pip install -r pps/docker/requirements-cc-wrapper.txt
python3 pps/docker/cc_openai_wrapper.py
```

Server starts on http://localhost:8000

**3. Test with curl:**
```bash
# Health check
curl http://localhost:8000/health

# Chat completion
curl http://localhost:8000/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "haiku",
        "messages": [
            {"role": "system", "content": "You are an entity extractor."},
            {"role": "user", "content": "Extract entities from: Jeff loves coffee"}
        ]
    }' | jq .
```

Expected response:
```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1737849600,
  "model": "haiku",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "..."
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 50,
    "completion_tokens": 100,
    "total_tokens": 150
  }
}
```

---

## Testing in Docker

**1. Build and start container:**
```bash
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker
docker compose build pps-cc-wrapper
docker compose up pps-cc-wrapper
```

Watch logs for:
- "Initializing ClaudeInvoker (model=haiku)..."
- "✓ ClaudeInvoker initialized in 33.2s"

**2. Test health check:**
```bash
curl http://localhost:8204/health | jq .
```

Should show:
```json
{
  "status": "healthy",
  "invoker_connected": true,
  "context_usage": {
    "tokens": 0,
    "turns": 0,
    "limit": 150000
  }
}
```

**3. Test from another container:**
```bash
docker compose exec graphiti curl http://pps-cc-wrapper:8000/health
```

Should reach the wrapper service via Docker network.

---

## Configuring Graphiti to Use Wrapper

**Update `pps/docker/.env`:**
```bash
# OpenAI Wrapper Configuration
WRAPPER_MODEL=haiku

# Graphiti LLM Configuration (point to wrapper)
GRAPHITI_LLM_BASE_URL=http://pps-cc-wrapper:8000
GRAPHITI_LLM_MODEL=haiku

# Still need OpenAI for embeddings (cheap, graph-compatible)
OPENAI_API_KEY=sk-proj-...
```

**Restart Graphiti:**
```bash
docker compose restart graphiti
```

**Verify in logs:**
Graphiti should now make requests to `pps-cc-wrapper:8000/v1/chat/completions`.

---

## Testing End-to-End

**1. Single message ingestion:**
```bash
# Via PPS server HTTP endpoint
curl -X POST http://localhost:8201/tools/ingest_batch_to_graphiti \
    -H "Content-Type: application/json" \
    -d '{"batch_size": 1}'
```

**2. Monitor wrapper logs:**
```bash
docker compose logs -f pps-cc-wrapper
```

Look for:
- POST request to `/v1/chat/completions`
- Query to ClaudeInvoker
- Response returned

**3. Verify extraction quality:**
```bash
# Check entities were created
curl http://localhost:8203/search \
    -H "Content-Type: application/json" \
    -d '{"query": "Jeff"}'
```

---

## Troubleshooting

**"ClaudeInvoker not initialized"**:
- Check startup logs - init takes ~33s
- Health check should wait 60s before marking unhealthy
- Verify claude-agent-sdk is installed

**"Connection refused" from Graphiti**:
- Check both services are on pps-network
- Verify DNS: `docker compose exec graphiti ping pps-cc-wrapper`
- Check wrapper health: `curl http://localhost:8204/health`

**"Invoker restart failed"**:
- Context limit hit - restart should be automatic
- Check logs for specific error
- May need to increase max_context_tokens

**Slow responses**:
- First query is ~2-4s (normal)
- Subsequent queries should be faster
- Restart adds ~33s latency

---

## Performance Expectations

| Operation | Time |
|-----------|------|
| Container startup | ~33s (ClaudeInvoker init) |
| First query | 2-4s |
| Subsequent queries | 0.6-2s |
| Auto-restart | ~33s (happens automatically at limits) |

**Context limits**:
- 150k tokens before restart
- 100 turns before restart
- 4 hours idle before restart

---

## Cost Comparison

**Before** (OpenAI GPT-4o):
- ~$0.003125 per message
- 7000 messages: ~$22
- Ongoing: ~$3/month

**After** (Claude via wrapper):
- $0 for LLM (subscription)
- ~$0.02 per 1M embedding tokens (keeping OpenAI embeddings)
- **Savings**: $22 immediate + $37/year ongoing

---

## Next Steps

1. **Local testing** - Verify wrapper works standalone
2. **Docker testing** - Build container and test connectivity
3. **Integration testing** - Ingest 10 test messages via wrapper
4. **Quality validation** - Compare entity extraction with OpenAI baseline
5. **Production rollout** - Update .env and restart Graphiti
6. **Monitor** - Watch logs for issues during 7000+ message backlog ingestion

---

## Rollback Plan

If issues arise:

1. Stop wrapper: `docker compose stop pps-cc-wrapper`
2. Revert `.env` to use OpenAI directly:
   ```bash
   # Remove wrapper config
   unset GRAPHITI_LLM_BASE_URL
   unset GRAPHITI_LLM_MODEL
   ```
3. Restart Graphiti: `docker compose restart graphiti`

Original OpenAI integration will resume.

---

**Ready for testing!**
