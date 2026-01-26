# Design: OpenAI-Compatible Wrapper for CC Invoker

**Author**: Orchestration Agent
**Date**: 2026-01-25
**Status**: Research Complete - Ready for Review

---

## Problem Statement

Graphiti (PPS Layer 3) uses OpenAI API for entity extraction, incurring ongoing costs (~$3/month, $37/year). We have 7000+ messages remaining to ingest, which would cost ~$22.

Jeff already pays for unlimited Claude access. We should leverage the existing ClaudeInvoker (built for daemon persistence) to eliminate these costs while consolidating to a single AI provider.

**Why this matters**:
- Cost savings (modest but real)
- Consistency (same model family for all work)
- Control (can switch models per use case)
- Privacy (conversations stay in Claude ecosystem)

---

## Research Findings

### 1. CC Invoker Capabilities

The ClaudeInvoker (`daemon/cc_invoker/invoker.py`) provides exactly what we need:

**Interface**:
```python
invoker = ClaudeInvoker(
    model="haiku",  # Configurable model selection
    bypass_permissions=True,  # Headless mode
    startup_prompt=None,  # No identity for stateless use
    mcp_servers={}  # Disable MCP tools (not needed)
)
await invoker.initialize()  # One-time 33s cost
response = await invoker.query(prompt)  # 2-4s per query
```

**Perfect for this use case**:
- ✅ Stateless requests (no session continuity needed)
- ✅ Model selection (haiku for cheap/fast extraction)
- ✅ Context management (auto-restart on limits)
- ✅ Fast queries after initialization (5-10x speedup)

### 2. OpenAI API Requirements

Graphiti expects `/v1/chat/completions` endpoint with OpenAI format.

**Request**:
```json
{
  "model": "gpt-4",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "Extract entities from..."}
  ]
}
```

**Response**:
```json
{
  "id": "chatcmpl-123",
  "choices": [{
    "message": {"role": "assistant", "content": "..."},
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 56,
    "completion_tokens": 120,
    "total_tokens": 176
  }
}
```

**Translation is trivial**: Combine messages → query Claude → wrap response.

### 3. Graphiti Configuration

Current setup (`pps/docker/.env`):
```bash
OPENAI_API_KEY=sk-proj-...  # Brandi's account
# Uses OpenAI for entity extraction
```

To use wrapper:
```bash
GRAPHITI_LLM_BASE_URL=http://pps-cc-wrapper:8000
GRAPHITI_LLM_MODEL=haiku
OPENAI_API_KEY=sk-proj-...  # Still needed for embeddings
```

**Hybrid mode**: Claude for LLM (free), OpenAI for embeddings (cheap, graph-compatible)

### 4. Cost Analysis

**Current** (OpenAI GPT-4o):
- ~$0.003125 per message
- 7000 messages: ~$22
- Ongoing: ~$3/month

**Proposed** (Claude via wrapper):
- $0 for LLM (subscription)
- ~$0.02 per 1M embedding tokens (keeping OpenAI embeddings)
- **Net savings**: $22 immediate + $37/year ongoing

---

## Approaches Considered

### Option A: HTTP Wrapper Around ClaudeInvoker (CHOSEN)

**Description**: FastAPI server that translates OpenAI API → ClaudeInvoker → OpenAI format

**Pros**:
- Minimal code (< 100 lines)
- Leverages existing ClaudeInvoker infrastructure
- Non-invasive (no Graphiti modifications)
- Easy to test incrementally
- Simple rollback if issues

**Cons**:
- Adds one more Docker service
- HTTP overhead (negligible)
- Need to maintain OpenAI format compatibility

### Option B: Direct Graphiti Modification

**Description**: Modify Graphiti source to use Claude SDK directly

**Pros**:
- No HTTP overhead
- Tighter integration

**Cons**:
- Invasive changes to third-party library
- Hard to maintain across Graphiti updates
- Would need to fork

**Verdict**: Rejected - wrapper is cleaner

### Option C: Use LM Studio / Ollama

**Description**: Run local LLM instead of any cloud API

**Pros**:
- Fully local, no API costs

**Cons**:
- Requires GPU hardware
- Quality may be lower
- Infrastructure complexity
- Jeff already has Claude subscription

**Verdict**: Rejected - wrapper leverages existing subscription

### Option D: Keep Using OpenAI

**Description**: Do nothing, accept the costs

**Pros**:
- Zero effort

**Cons**:
- Ongoing costs
- Two AI providers
- Missed learning opportunity

**Verdict**: Rejected - wrapper is easy enough to justify

---

## Chosen Approach

**Selected**: Option A - HTTP Wrapper

**Rationale**:
- Leverages existing, proven ClaudeInvoker infrastructure
- Minimal complexity (< 100 lines of code)
- Non-invasive (Graphiti just sees OpenAI-compatible endpoint)
- Easy to test and rollback
- Reasonable effort/value ratio

---

## Architecture

```
┌─────────────────────────────────────┐
│  Graphiti (Docker container)        │
│  GRAPHITI_LLM_BASE_URL=             │
│    http://pps-cc-wrapper:8000       │
└─────────────────────────────────────┘
                 ↓ HTTP POST /v1/chat/completions
┌─────────────────────────────────────┐
│  CC Wrapper (New service)           │
│  - FastAPI server                   │
│  - Translates OpenAI ↔ Claude       │
└─────────────────────────────────────┘
                 ↓ Python API
┌─────────────────────────────────────┐
│  ClaudeInvoker                      │
│  - Persistent connection            │
│  - Model: haiku                     │
└─────────────────────────────────────┘
                 ↓ Claude Agent SDK
┌─────────────────────────────────────┐
│  Claude Code CLI                    │
└─────────────────────────────────────┘
```

---

## Implementation Plan

### Step 1: Core Wrapper
1. Create `pps/docker/cc_openai_wrapper.py` with FastAPI app
2. Implement `/v1/chat/completions` endpoint
3. Add `/health` endpoint for monitoring
4. Test locally with curl

### Step 2: Docker Integration
5. Create `pps/docker/Dockerfile.cc-wrapper`
6. Add service to `docker-compose.yml`
7. Update `.env` with wrapper config
8. Build and test container startup

### Step 3: Graphiti Configuration
9. Update Graphiti environment variables in `.env`
10. Point `GRAPHITI_LLM_BASE_URL` to wrapper
11. Set `GRAPHITI_LLM_MODEL=haiku`
12. Restart Graphiti service

### Step 4: Testing & Validation
13. Test single message ingestion
14. Verify entity extraction quality
15. Compare with OpenAI baseline
16. Run batch of 100 messages
17. Monitor for issues

### Step 5: Production Rollout
18. Update documentation
19. Full rollout for 7000+ message backlog
20. Monitor cost savings

**Estimated effort**: 4 hours total (2 implementation + 1 testing + 1 integration)

---

## Files Affected

### New Files
- `pps/docker/cc_openai_wrapper.py` - FastAPI wrapper service
- `pps/docker/Dockerfile.cc-wrapper` - Container build config
- `pps/docker/requirements-cc-wrapper.txt` - Python dependencies

### Modified Files
- `pps/docker/docker-compose.yml` - Add pps-cc-wrapper service
- `pps/docker/.env` - Configure Graphiti to use wrapper
- `docs/architecture/PPS_ARCHITECTURE.md` - Document wrapper layer

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| ClaudeInvoker instability in 24/7 daemon | Medium | Use built-in `needs_restart()` check, auto-restart on limits |
| Claude rate limits during bulk ingestion | Low | Monitor usage, can throttle or fall back to OpenAI |
| Container startup time (~33s) | Low | Set `start_period: 60s` in healthcheck |
| Claude prompt format differs from GPT-4 | Medium | Test with samples first, adjust if needed |
| Quality degradation vs OpenAI | Medium | Compare extractions, rollback if issues |

**Overall risk level**: LOW - All mitigations are straightforward

---

## Testing Strategy

### Phase 1: Local Testing
1. Test ClaudeInvoker directly for entity extraction
2. Run FastAPI wrapper locally (`uvicorn`)
3. Test with curl/httpie
4. Verify response format matches OpenAI

### Phase 2: Docker Integration
5. Build container
6. Test container startup and health
7. Verify network connectivity from Graphiti
8. Test single ingestion request

### Phase 3: Production Validation
9. Ingest 10 test messages
10. Compare entity quality with OpenAI
11. Batch test with 100 messages
12. Monitor performance and logs
13. Full rollout if successful

---

## Open Questions

- [x] **Can ClaudeInvoker handle stateless requests?** YES - works fine without identity
- [x] **What's the OpenAI API format?** Documented - simple to implement
- [x] **How does Graphiti configure LLM endpoint?** Via `GRAPHITI_LLM_BASE_URL` env var
- [x] **What are cost savings?** ~$22 immediate + $37/year ongoing
- [ ] **Model preference?** Haiku (fast/cheap) or Sonnet (quality)? - ASK JEFF
- [ ] **Priority vs other work?** Worth doing now? - ASK JEFF
- [ ] **Rollback acceptable?** OK to revert if quality issues? - ASK JEFF

---

## Feasibility Assessment

**Status**: HIGHLY FEASIBLE ✅

**Confidence**: 95%

**Why this will work**:
1. ClaudeInvoker already provides exactly what we need
2. OpenAI API format is simple and well-documented
3. Graphiti supports custom LLM endpoints (proven with LM Studio)
4. Small, focused scope - one endpoint, minimal translation
5. Similar patterns work (Ollama, LM Studio, etc.)

**Effort is reasonable**:
- ~4 hours of focused work
- Can be done in one session
- Easy incremental testing

**Value is clear**:
- Cost savings (modest but real)
- Consolidates providers
- Enables future flexibility

**Recommendation**: PROCEED TO IMPLEMENTATION

---

## Implementation Checklist

From TODO.md, detailed tasks:

### Core Development
- [ ] Create `pps/docker/cc_openai_wrapper.py`
  - [ ] FastAPI app skeleton
  - [ ] ClaudeInvoker initialization (startup event)
  - [ ] POST `/v1/chat/completions` endpoint
  - [ ] Request parsing (OpenAI format)
  - [ ] Message combination logic
  - [ ] ClaudeInvoker query call
  - [ ] Response formatting (OpenAI format)
  - [ ] Token usage estimation
  - [ ] Auto-restart logic
  - [ ] GET `/health` endpoint
  - [ ] Shutdown handler
- [ ] Create `pps/docker/requirements-cc-wrapper.txt`
  - [ ] fastapi
  - [ ] uvicorn
  - [ ] pydantic

### Docker Integration
- [ ] Create `pps/docker/Dockerfile.cc-wrapper`
  - [ ] Base from Python 3.11
  - [ ] Install dependencies
  - [ ] Copy daemon/cc_invoker module
  - [ ] Expose port 8000
  - [ ] Entrypoint: uvicorn
- [ ] Update `pps/docker/docker-compose.yml`
  - [ ] Add pps-cc-wrapper service
  - [ ] Network: pps-network
  - [ ] Environment variables
  - [ ] Health check (60s start period)
  - [ ] Restart policy
- [ ] Update `pps/docker/.env`
  - [ ] WRAPPER_MODEL=haiku
  - [ ] GRAPHITI_LLM_BASE_URL=http://pps-cc-wrapper:8000
  - [ ] GRAPHITI_LLM_MODEL=haiku

### Testing
- [ ] Local testing (no Docker)
  - [ ] Run wrapper with uvicorn
  - [ ] Test with curl
  - [ ] Verify response format
- [ ] Docker testing
  - [ ] Build container
  - [ ] Test startup (health check)
  - [ ] Test from Graphiti container
- [ ] Integration testing
  - [ ] Ingest single test message
  - [ ] Verify entities extracted
  - [ ] Compare with OpenAI baseline
  - [ ] Batch test (10 messages)
  - [ ] Batch test (100 messages)

### Documentation
- [ ] Add troubleshooting guide
- [ ] Document environment variables
- [ ] Update PPS architecture docs
- [ ] Record cost savings

---

**Next step**: Review with Jeff/Lyra, then proceed to implementation if approved.
