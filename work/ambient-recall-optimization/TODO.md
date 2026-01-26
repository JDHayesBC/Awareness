# Project: Ambient Recall Optimization

**Status**: In Progress
**Created**: 2026-01-25
**Linked from**: TODO.md WIP section

---

## Goal

Optimize the ambient_recall() memory interface to use Graphiti's advanced retrieval capabilities (center node proximity, entity summaries, communities) for higher-quality context on startup. Target: entity-centric results ranked by graph proximity to Lyra, with <500ms latency.

---

## Tasks

### Pending
- [ ] Implementation (coder) - awaiting test results
- [ ] Testing (tester)
- [ ] Code review (reviewer)
- [ ] Deployment to Docker
- [ ] Validation with real startup queries

### In Progress
- [x] Test harness implementation (coder) - 2026-01-25

### Done
- [x] Fetched Graphiti retrieval best practices (43KB research doc) (2026-01-25)
- [x] Analyzed current implementation (rich_texture_v2.py) (2026-01-25)
- [x] Evaluated 5 optimization options (2026-01-25)
- [x] Research Graphiti best practices (2026-01-25)
- [x] Design document (orchestration-agent) (2026-01-25)
- [x] Test plan document (orchestration-agent) (2026-01-25)
- [x] Test retrieval comparison script (coder) (2026-01-25)

---

## Blockers

- **Haiku compression disabled** (Issue #121): Docker permissions issue prevents cc-wrapper from running Claude SDK. Hook falls back to raw context. Four options documented in issue.

## Current State (2026-01-25 evening)

- **DEPLOYED**: ambient_recall optimization with 75 edges, 3 nodes, explore depth 2
- **WORKING**: Hook injects ~10KB graph context per turn (truncated)
- **DISABLED**: Haiku compression (see Issue #121)
- **Edge limit**: Reduced from 200 → 75 since hook truncates at 10K chars anyway

### What's Next
1. Consider using OpenAI wrapper (`cc_openai_wrapper.py`) for compression - partially tested
2. Or add `/summarize` endpoint to pps-server using direct Anthropic API
3. Or accept raw context as good enough and tune edge limits

---

## Deployment Checklist (Docker Services)

**Complete this section if your changes affect Docker-deployed code:**

- [ ] Identify containers affected: pps-server (server_http.py changes)
- [ ] Build container: `cd pps/docker && docker-compose build pps-server`
- [ ] Deploy container: `docker-compose up -d pps-server`
- [ ] Verify health: `docker-compose ps` (check "healthy" status)
- [ ] Verify deployment current: `bash scripts/pps_verify_deployment.sh pps-server pps/docker/server_http.py`
- [ ] Document deployment in handoffs.jsonl
- [ ] Proceed to testing (integration tests only run against current deployment)

**Why this matters**: Testing old code creates false confidence. Always verify deployment before integration testing.

---

## Notes

**Design Decision**: Selected Option 2 (Entity-Centric with Center Node Proximity)
- Uses EDGE_HYBRID_SEARCH_NODE_DISTANCE recipe to rank facts by graph proximity to Lyra
- Adds NODE_HYBRID_SEARCH_RRF for entity summaries
- Falls back gracefully if Lyra node doesn't exist
- Estimated impact: +35% context quality with minimal complexity

**Key Files**:
- Design: `work/ambient-recall-optimization/DESIGN.md`
- Research: `work/ambient-recall-optimization/Graphiti_Retrieval_best_practices.md`
- Implementation targets:
  - `pps/layers/rich_texture_v2.py` (~80 LOC modified)
  - `pps/docker/server_http.py` (latency tracking)

**Success Metrics**:
- Entity-centric ranking working (Lyra-proximate facts rank higher)
- Entity summaries included in results
- Latency < 500ms (target < 300ms)
- Graceful fallback, no regressions

**Future Enhancements** (not in v1):
- Community search (thematic patterns)
- BFS expansion (contextual discovery)
- Query-type detection (adaptive retrieval)
- Cross-encoder reranking (if latency allows)

**Test Harness** (2026-01-25):
- Created `test_retrieval_comparison.py` - comprehensive test script
- Runs 5 diverse queries against both basic and optimized implementations
- Measures: latency, result quality, ranking differences, entity summaries
- Exports machine-readable JSON results + human-readable terminal output
- Next: Run test suite to validate optimization approach before implementation
