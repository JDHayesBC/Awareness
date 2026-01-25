# Design: Ambient Recall Optimization

**Author**: orchestration-agent
**Date**: 2026-01-25
**Status**: Draft

---

## Problem Statement

`ambient_recall()` is our primary memory interface, called on every Claude startup to provide context for identity continuity. It currently queries multiple layers (raw capture, core anchors, rich texture) using simple search methods.

The **rich_texture_v2.py** layer uses Graphiti's basic `client.search()` method, which returns only EntityEdge results with default hybrid search (semantic + BM25). This misses several powerful capabilities:

1. **Node search** - Entity summaries that provide background context
2. **Community search** - Thematic clusters/patterns
3. **Advanced reranking** - Graph proximity (node_distance), MMR diversity, episode mentions
4. **BFS traversal** - Contextual expansion from seed entities
5. **Center node proximity** - Ranking results by graph distance from focal entity

**Current performance**: Unknown (no latency tracking)
**Target benchmark**: 300ms P95 (Zep's production standard from Graphiti best practices)

**Key constraint**: ambient_recall is called synchronously on startup - we can't afford multi-second latency or complex multi-hop queries.

---

## Current Implementation Analysis

### What We Have (`pps/layers/rich_texture_v2.py` lines 360-443)

```python
async def _search_direct(self, query: str, limit: int) -> list[SearchResult]:
    edges = await client.search(
        query=query,
        group_ids=[self.group_id],
        num_results=limit,
    )
    # Filters out IS_DUPLICATE_OF edges
    # Fetches node names for display
    # Returns formatted SearchResult list
```

**What it does well:**
- Simple, fast edge-only search
- Filters out duplicate edges (Graphiti bug workaround)
- Fetches actual node names for readable output
- Works reliably

**What it misses:**
- No entity summaries (nodes) - we lose background context
- No thematic patterns (communities) - we lose high-level patterns
- No graph proximity ranking - results treat all facts equally regardless of relevance to focal entity
- No diversity control - can get redundant results
- No BFS expansion - can't discover contextual connections

### Ambient Recall Context (`pps/docker/server_http.py` lines 400-554)

The endpoint currently:
1. Queries all layers in parallel (raw, anchors, texture)
2. Merges results by relevance score
3. For "startup" context: adds summaries + unsummarized turns
4. Returns clock info + memory health

**Key insight**: The query string passed to rich_texture layer is just `request.context` (e.g., "startup"). This is too generic for entity-centric retrieval.

---

## Approaches Considered

### Option 1: Minimal Change - Add Node Search Only

**Description**: Keep current edge search, add parallel node search for entity summaries.

**Pros:**
- Simple, low risk
- Entity summaries add valuable context
- Minimal code change
- Fast (parallel queries)

**Cons:**
- Still no graph proximity ranking
- Still no communities
- Doesn't leverage entity-centric patterns
- Results still treat all facts equally

**Estimated impact**: +15% context quality (entity summaries help, but not transformative)

---

### Option 2: Entity-Centric with Center Node Proximity

**Description**: Find "Lyra" entity node, use node_distance reranking to prioritize facts close to Lyra in the graph.

```python
async def _search_direct(self, query: str, limit: int):
    # 1. Find Lyra entity node (or other focal entity)
    lyra_node = await self._find_entity_by_name(client, "Lyra", self.group_id)
    center_uuid = lyra_node.uuid if lyra_node else None

    # 2. Search edges with node distance reranking
    config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
    config.limit = limit

    edge_results = await client.search_(
        query=query,
        config=config,
        center_node_uuid=center_uuid,
        group_ids=[self.group_id]
    )

    # 3. Also get entity summaries
    node_results = await client.search_(query, config=NODE_HYBRID_SEARCH_RRF, ...)

    # Merge and format
```

**Pros:**
- **Leverages graph structure** - facts about Lyra or close to Lyra rank higher
- Uses pre-built recipe (well-tested)
- Semantic-aware entity-centric retrieval
- Still simple implementation
- Graphiti docs cite node_distance as "critical for relational dynamics"

**Cons:**
- Assumes "Lyra" is the focal entity (usually true, but not always)
- Need to cache Lyra node UUID (lookup on every query is expensive)
- Still no communities
- What if Lyra node doesn't exist yet (new graph)?

**Estimated impact**: +35% context quality (graph proximity is powerful for relational context)

**Concrete example**:

Query: "startup"

**Current results** (undifferentiated):
- Jeff subscribes to Anthropic News
- Lyra wears an oversized sweater
- Discord has a reflection channel
- Lyra cares for Jeff
- Neo4j is a graph database

**With node distance ranking** (Lyra-proximate facts first):
- Lyra cares for Jeff ⭐ (direct connection to Lyra)
- Lyra wears an oversized sweater ⭐ (direct Lyra fact)
- Jeff subscribes to Anthropic News (1 hop from Lyra via Jeff)
- Discord has a reflection channel (2 hops)
- Neo4j is a graph database (distant)

---

### Option 3: Multi-Scope Retrieval (Edges + Nodes + Communities)

**Description**: Use `COMBINED_HYBRID_SEARCH_RRF` to get all three scopes.

**Pros:**
- Gets all context types (facts, entities, themes)
- Single query (efficient)
- Balanced breadth and depth
- Thematic patterns from communities

**Cons:**
- No entity-centric ranking (treats all results equally)
- Community results might be too abstract for startup
- More complex result formatting
- Need to decide how to interleave different result types

**Estimated impact**: +30% context quality (breadth helps, but lacks focus)

---

### Option 4: Hybrid Approach (Center Node + Multi-Scope)

**Description**: Combine entity-centric ranking with multi-scope retrieval.

**Pros:**
- Best of all worlds: entity focus + breadth + themes
- Mimics Zep's production pattern
- Flexible budget allocation
- Rich context from multiple perspectives

**Cons:**
- Most complex implementation
- Three sequential queries (or need to parallelize)
- More code to maintain
- More failure modes

**Estimated impact**: +50% context quality (comprehensive, but complex)

---

### Option 5: Two-Stage Retrieval (Broad + Haiku Rerank)

**Description**: Get broader results (20-30 items), then use cheap Haiku call to rerank/compress.

**Pros:**
- LLM-based relevance (understands semantics better)
- Can compress/deduplicate intelligently
- Flexible - can adjust ranking criteria dynamically
- Still fast (Haiku is cheap and quick)

**Cons:**
- Adds LLM call latency (~200-500ms)
- Might exceed 300ms target
- More complex error handling
- Extra API cost (though Haiku is cheap)
- Adds dependency on LLM availability

**Estimated impact**: +40% context quality (semantic reranking helps, but latency cost)

---

## Chosen Approach

**Selected**: Option 2 (Entity-Centric with Center Node Proximity)

**Rationale**:
1. **Practical first try** - Uses pre-built recipes, minimal complexity
2. **Leverages graph structure** - Node distance ranking is purpose-built for relational context
3. **High impact** - Graph proximity is cited as "critical for relational dynamics" in Graphiti best practices
4. **Fast** - Single query with reranking, no LLM calls
5. **Low risk** - Falls back gracefully if Lyra node doesn't exist
6. **Clear upgrade path** - Can add communities later if this works well

**What makes this different from current implementation:**

**Current**: "Give me facts matching this query" (treats all facts equally)

**Proposed**: "Give me facts matching this query, ranked by how close they are to Lyra in the graph"

This means facts closer to Lyra in the graph naturally surface **relational context and identity-relevant information**.

---

## Implementation Plan

### Phase 1: Add Entity-Centric Edge Search (v1)

**File**: `pps/layers/rich_texture_v2.py`

**Changes**:

1. **Add Lyra UUID caching** (avoid lookup on every search):
```python
def __init__(self, ...):
    # ... existing init ...
    self._lyra_uuid_cache: Optional[str] = None
    self._lyra_uuid_cache_time: Optional[datetime] = None

async def _get_lyra_uuid(self) -> Optional[str]:
    """Get Lyra's entity node UUID, with caching."""
    # Cache for 1 hour to avoid repeated lookups
    now = datetime.now(timezone.utc)
    if self._lyra_uuid_cache and self._lyra_uuid_cache_time:
        if (now - self._lyra_uuid_cache_time).seconds < 3600:
            return self._lyra_uuid_cache

    # Find Lyra node
    client = await self._get_graphiti_client()
    if not client:
        return None

    lyra_node = await self._find_entity_by_name(client, "Lyra", self.group_id)
    if lyra_node:
        self._lyra_uuid_cache = lyra_node.uuid
        self._lyra_uuid_cache_time = now
        return lyra_node.uuid

    return None
```

2. **Update `_search_direct()` to use node distance reranking**:
```python
async def _search_direct(self, query: str, limit: int) -> list[SearchResult]:
    from graphiti_core.search.search_config_recipes import (
        EDGE_HYBRID_SEARCH_NODE_DISTANCE,
        NODE_HYBRID_SEARCH_RRF
    )

    try:
        client = await self._get_graphiti_client()
        if not client:
            return []

        # Get Lyra's node UUID for proximity ranking
        center_uuid = await self._get_lyra_uuid()

        # If center_uuid exists, use node distance reranking
        # Otherwise fall back to basic hybrid search
        if center_uuid:
            edge_config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
            edge_config.limit = limit

            edge_results = await client.search_(
                query=query,
                config=edge_config,
                center_node_uuid=center_uuid,
                group_ids=[self.group_id]
            )
            edges = edge_results.edges
        else:
            # Fallback: no center node found, use basic search
            edges = await client.search(
                query=query,
                group_ids=[self.group_id],
                num_results=limit,
            )

        # Filter IS_DUPLICATE_OF edges (existing logic)
        edges = [e for e in edges if e.name != "IS_DUPLICATE_OF"]

        # ... existing node name lookup and formatting ...

    except Exception as e:
        print(f"Direct search failed: {e}")
        return await self._search_http(query, limit)
```

3. **Add node search for entity summaries** (optional enhancement):
```python
# After edge search, add entity summaries
node_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
node_config.limit = max(2, limit // 5)  # 20% of results as entity summaries

node_results = await client.search_(
    query=query,
    config=node_config,
    group_ids=[self.group_id]
)

# Format nodes as SearchResult with metadata type="entity_summary"
for node in node_results.nodes:
    results.append(SearchResult(
        content=f"{node.name}: {node.summary}",
        source=str(node.uuid),
        layer=LayerType.RICH_TEXTURE,
        relevance_score=0.9,  # High relevance for entity context
        metadata={
            "type": "entity_summary",
            "entity": node.name,
            "labels": node.labels,
        }
    ))

# Merge edges + nodes, sorted by relevance
```

**Estimated LOC**: ~80 lines added/modified

**Risk**: Low - falls back to current behavior if Lyra node doesn't exist

### Phase 2: Add Latency Tracking

**File**: `pps/docker/server_http.py`

Add timing to ambient_recall endpoint:

```python
@app.post("/tools/ambient_recall")
async def ambient_recall(request: AmbientRecallRequest):
    import time
    start_time = time.time()

    # ... existing logic ...

    latency_ms = (time.time() - start_time) * 1000

    return {
        "clock": { ... },
        "results": all_results,
        "latency_ms": latency_ms,  # NEW
        ...
    }
```

**Goal**: Track whether we're hitting 300ms P95 target

### Phase 3: Testing and Validation

**Test queries**:
1. "startup" - General context (existing)
2. "Jeff and Lyra relationship" - Should surface relational facts
3. "Lyra's current projects" - Should prioritize Lyra-proximate work
4. "recent conversations" - Temporal relevance test

**Validation criteria**:
- ✅ Results include facts close to Lyra in graph
- ✅ Entity summaries provide background context
- ✅ Latency < 500ms (comfortable margin below 300ms target)
- ✅ Graceful fallback if Lyra node missing
- ✅ No regression in result quality for other queries

---

## Files Affected

- `pps/layers/rich_texture_v2.py` - Add `_get_lyra_uuid()` with caching, update `_search_direct()` to use node distance + nodes
- `pps/docker/server_http.py` - Add latency tracking to ambient_recall endpoint

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Lyra node doesn't exist (new graph) | Medium | Fall back to basic search without center_uuid |
| Multiple Lyra nodes (duplicates) | Medium | **Self-healing**: If multiple nodes found, merge them on-demand. Pick most connected as canonical, merge others into it, cache the canonical UUID. Latency hit only on first detection, then fast path. Graph gets cleaner through normal use. |
| Increased latency from search_() | Medium | Track latency, optimize if >300ms |
| Node lookup on every search | Low | Cache Lyra UUID for 1 hour |
| Complexity of handling nodes + edges | Low | Clear result type in metadata, structured formatting |
| Breaking existing callers | High | Keep response format compatible, add fields not replace |

---

## Open Questions

- [ ] Should we make the focal entity configurable (not hardcoded to "Lyra")?
- [ ] What's the right cache duration for Lyra UUID (1 hour vs 24 hours)?
- [ ] Should we add communities in v1 or save for v2?
- [ ] Do we need to expose node distance scores in the API response?

---

## Future Enhancements (Not in First Try)

**If Phase 1 succeeds, consider:**

1. **Add community search** (thematic patterns)
   - Budget: 10-15% of results
   - Use `COMMUNITY_HYBRID_SEARCH_RRF`
   - Surfaces recurring themes and clusters

2. **BFS expansion for contextual discovery**
   - Use recent episode UUIDs as BFS seeds
   - "Land and expand" pattern
   - Good for "what happened recently" queries

3. **Query-type detection**
   - "startup" → broad balanced retrieval
   - "relationship" → relational query pattern
   - "project" → entity-centric deep dive
   - Adapt retrieval strategy to query intent

4. **Cross-encoder reranking**
   - Use OpenAI's one-token trick for final ranking
   - Higher quality but adds latency
   - Only if we have latency headroom

5. **Temporal filters**
   - Use SearchFilters for time-bounded queries
   - "What happened this week?"
   - Requires date-aware query parsing

6. **Haiku compression layer**
   - If we consistently get great results but too many
   - Use Haiku to compress/deduplicate
   - Only if latency allows

---

## Success Metrics

**Must-have (v1)**:
- ✅ Entity-centric ranking working (facts close to Lyra rank higher)
- ✅ Entity summaries included in results
- ✅ Latency < 500ms for ambient_recall
- ✅ Graceful fallback if Lyra node doesn't exist
- ✅ No regressions in existing functionality

**Nice-to-have (v1)**:
- ⭐ Latency < 300ms (production target)
- ⭐ Subjective quality improvement in startup context
- ⭐ Graph proximity visible in result metadata

**Future (v2+)**:
- Community search integration
- Query-type adaptive retrieval
- BFS contextual expansion

---

## References

- `work/ambient-recall-optimization/Graphiti_Retrieval_best_practices.md` - Full Graphiti retrieval guide (43KB)
- Graphiti docs: Search API, SearchConfig, rerankers
- Zep production pattern: Lines 1016-1295 of best practices doc
- Current implementation: `pps/layers/rich_texture_v2.py` lines 360-443
- Ambient recall endpoint: `pps/docker/server_http.py` lines 400-554
