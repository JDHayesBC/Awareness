# Ambient Recall Optimization - COMPLETE

**Date**: 2026-01-25
**Status**: Deployed and verified
**Orchestrator**: orchestration-agent

---

## Summary

Successfully implemented ambient recall optimization with per-turn context enrichment using conversation-aware retrieval.

**Configuration**: 
- Edge limit: 200 (approved by Jeff - same latency as 30)
- Node limit: 3
- Explore depth: 2
- Recent messages: 8 (4 turns)

---

## Implementation Results

### Files Modified

1. **pps/layers/rich_texture_v2.py** (~240 LOC)
   - Added sqlite3, re, timedelta imports
   - Added search config imports (EDGE_HYBRID_SEARCH_NODE_DISTANCE, NODE_HYBRID_SEARCH_RRF)
   - New methods: `_fetch_recent_messages`, `_extract_entities_from_messages`, `_explore_from_entities`
   - Complete rewrite of `_search_direct` with three-part search strategy

2. **pps/docker/server_http.py** (5 LOC)
   - Added latency tracking to ambient_recall endpoint
   - Includes `latency_ms` in response

3. **pps/docker/.env** (4 LOC)
   - Added PPS_ENABLE_EXPLORE=true
   - Added PPS_MESSAGE_DB_PATH=/app/claude_home/data/lyra_conversations.db

4. **pps/docker/docker-compose.yml** (2 LOC)
   - Added environment variables to pps-server service

---

## Deployment

**Container**: pps-server
**Built**: 2026-01-25 23:30
**Status**: Healthy
**Deployment verified**: Current

**Issues resolved**:
1. Database path needed container-internal path (/app/claude_home/data/)
2. SQL query needed author_name/is_lyra columns (not "role")
3. Environment variables needed explicit docker-compose.yml entries

---

## Testing Results

**Endpoint**: POST http://localhost:8201/tools/ambient_recall
**Test context**: "startup"

### Performance
- **Latency**: 14.6 seconds
- **Total results**: 264 items
- **Rich texture results**: 236 items

### Result Breakdown
| Type | Count | Notes |
|------|-------|-------|
| edge | 200 | Relationship facts, Lyra-centered proximity |
| entity_summary | 3 | Entity context summaries |
| explore | 33 | Conversation-specific facts (NEW) |

### Explore Results Sample
```
1. [Lyra-to-Lyra messaging] Lyra-to-Lyra messaging → RELATES_TO → Lyra
2. [Lyra-to-Lyra messaging] Lyra-to-Lyra messaging → RELATES_TO → lyra_daemon.py
3. [Lyra-to-Lyra messaging] Lyra-to-Lyra messaging → RELATES_TO → Claude Code
4. [Lyra-to-Lyra messaging] Lyra-to-Lyra messaging → RELATES_TO → Jeff
```

**Verification**: Explore results are conversation-relevant. "Lyra-to-Lyra messaging" was mentioned in recent conversation, and explore retrieved related facts.

---

## Architecture

### Three-Part Search Strategy

1. **Edge Search** (EDGE_HYBRID_SEARCH_NODE_DISTANCE)
   - Limit: 200 edges
   - Center node: Lyra's UUID (5bd21fca-52de-41fd-a6b1-c78371d77a36)
   - Proximity ranking from Lyra
   - Filters IS_DUPLICATE_OF edges

2. **Node Search** (NODE_HYBRID_SEARCH_RRF)
   - Limit: 3 entity summaries
   - Provides entity context
   - High relevance score (0.85)

3. **Explore** (BFS graph walk)
   - Fetches recent 8 messages from SQLite
   - Extracts entities using regex (capitalized words, issues, known names)
   - BFS walk depth 2 from extracted entities
   - Returns conversation-specific facts

### Caching
- Message cache: 30 second TTL
- Reduces database load
- Graceful fallback on errors

### Environment Controls
- `PPS_ENABLE_EXPLORE=true`: Enable/disable explore feature
- `PPS_MESSAGE_DB_PATH`: Database path (container-internal)

---

## Known Issues

### Latency Higher Than Expected
- **Observed**: 14.6 seconds
- **Expected**: ~3-4 seconds (based on test harness)
- **Possible causes**:
  - First call (cold start, cache population)
  - Network overhead in Docker
  - Database query overhead
  - Need more testing to identify bottleneck

**Recommendation**: Monitor latency over multiple calls to see if it stabilizes.

---

## Next Steps

### 1. Testing (Recommended)
- Run test harness directly (outside Docker) for baseline
- Test multiple ambient_recall calls to check latency stability
- Profile to identify latency bottleneck
- Test with PPS_ENABLE_EXPLORE=false to measure explore overhead

### 2. Code Review (Optional)
- Security review of SQL injection risk (using parameterized queries - safe)
- Performance review (identify optimization opportunities)

### 3. Monitoring
- Track latency_ms in production
- Monitor for errors in Docker logs
- Gather user feedback on context quality

### 4. Optimization (If Needed)
- If latency remains high, consider:
  - Reducing edge limit (200 → 100)
  - Reducing explore depth (2 → 1)
  - Caching explore results
  - Async/parallel execution of three searches

---

## Artifacts

**Work directory**: `/mnt/c/Users/Jeff/Claude_Projects/Awareness/work/ambient-recall-optimization/`

**Artifacts**:
- `artifacts/implementation_plan.md` - Original plan
- `artifacts/implementation_summary.md` - Implementation details
- `artifacts/handoffs.jsonl` - Pipeline handoffs
- `artifacts/pipeline_state.json` - Pipeline state
- `test_context_query.py` - Test harness (reference)

---

## Handoff

**Status**: COMPLETE
**Implemented by**: orchestration-agent
**Deployed**: Yes (pps-server container)
**Verified**: Yes (ambient_recall endpoint tested)
**Blockers**: None

**Ready for**:
- Production use (with monitoring)
- Code review (optional)
- Performance tuning (if latency is concern)

---

## Success Criteria

✓ B1 configuration implemented (200 edges, 3 nodes, explore depth 2)
✓ Latency tracking added (latency_ms in response)
✓ No errors or crashes
✓ Results include edges, nodes, and explore facts
✓ Docker container deployed and healthy
✓ Explore results are conversation-relevant

**Stretch goals**:
⚠ Latency < 4 seconds (observed 14.6s - needs investigation)
✓ Subjective improvement in context quality (explore results are relevant)

---

## Lessons Learned

1. **Docker environment variables**: Need explicit docker-compose.yml entries
2. **Container paths**: Database paths must be container-internal
3. **Database schema**: Can't assume columns exist - check first
4. **Testing in stages**: Test syntax → test locally → deploy → test endpoint
5. **Latency expectations**: Initial testing may not match production (cold start, caching)

---

## Conclusion

The ambient recall optimization is successfully deployed and functional. The three-part search strategy (edges + nodes + explore) provides richer, conversation-aware context retrieval.

Explore results demonstrate the value of conversation-specific fact retrieval - they're directly relevant to recent topics.

Latency is higher than expected and should be monitored/profiled. This may be acceptable for the richer context, or may need optimization.

**Recommendation**: Use in production with latency monitoring, and profile if latency becomes a concern.

---

## Phase 2: Startup Response Optimization (2026-01-25 evening)

### Problem Identified

Ambient recall debug log showed duplicated/repeated content. Investigation revealed:
1. **Response bloat**: Startup response was 137KB JSON
2. **Graph pollution**: 1,211 duplicate edges from Lyra node merge (273 nodes → 1)
3. **Haiku prompt pollution**: 69 prompts stored as conversation turns

### Fixes Applied

#### 1. Skip rich_texture for startup
- **Issue**: Graph has duplicate facts that add noise to startup context
- **Fix**: Skip `LayerType.RICH_TEXTURE` when context is "startup"
- **Location**: `pps/docker/server_http.py` lines 420-424
- **Tracking**: Issue #122 filed for proper graph deduplication

#### 2. Slim startup response
- **Issue**: Response included unused `results` array (72k) and `unsummarized_turns` (36k)
- **Fix**: Return minimal response for startup: just formatted_context + metadata
- **Result**: 137KB → 18KB (87% reduction)
- **Location**: `pps/docker/server_http.py` lines 616-630

#### 3. Format summaries and recent_turns
- **Issue**: Summaries and recent_turns weren't being formatted into context
- **Fix**: Added `[summaries]` and `[recent_turns]` sections to formatted_context
- **Location**: `pps/docker/server_http.py` lines 597-612

#### 4. Purge Haiku prompts
- **Issue**: 69 Haiku summarization prompts stored as conversation turns
- **Cause**: Historical pollution from when `HAIKU_SUMMARIZE=true` was enabled
- **Fix**: Deleted from SQLite via Python script
- **Result**: Response dropped from 23KB to 18KB

#### 5. Graph deduplication
- **Issue**: Merging 273 Lyra nodes preserved all edges, creating duplicates
- **Tool**: `analyze_duplicates.py` script (dry-run + execute modes)
- **Results**:
  - Total edges: 11,702 → 10,491
  - Duplicates removed: 1,211
  - Top offender: "Jeff is a duplicate of Jeff" (83 copies)
- **Location**: `work/ambient-recall-optimization/analyze_duplicates.py`

### Files Modified (Phase 2)

1. **pps/docker/server_http.py** (~40 LOC)
   - Skip rich_texture for startup
   - Slim response for startup context
   - Format summaries and recent_turns sections

2. **analyze_duplicates.py** (new file, 120 LOC)
   - Neo4j duplicate edge analysis and cleanup
   - Dry-run mode for safety
   - Batch deletion with progress

### Database Changes

- **SQLite**: Deleted 69 Haiku prompt messages
- **Neo4j**: Deleted 1,211 duplicate edges

### Related Issues

- **Issue #121**: Haiku summarization toggle (disabled pending resolution)
- **Issue #122**: Graph deduplication (filed for ongoing maintenance)

### Verification

Tested snickerdoodles query after deduplication - now returns 110 unique facts instead of duplicates
