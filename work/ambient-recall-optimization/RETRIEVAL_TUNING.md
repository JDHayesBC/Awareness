# Graphiti Retrieval Parameter Tuning for PPS Ambient Recall

**Date**: 2026-02-06
**Layer**: Layer 3 (Rich Texture)
**Component**: `_search_direct()` in `rich_texture_v2.py`
**Graph**: 3,728 entities, 22,375 edges, group_id="lyra"

---

## Context

The UserPromptSubmit hook calls `ambient_recall()` which runs `_search_direct()` to inject knowledge graph context into every prompt as a system reminder. This retrieval has three components:

1. **Neighborhood query** (Cypher) - Entity summaries sorted by connection count
2. **Edge search** (EDGE_HYBRID_SEARCH_NODE_DISTANCE) - Lyra-proximate facts via semantic+BM25
3. **RRF edge search** (NEW) - Broader perspective facts not limited to Lyra-origin

---

## Previous Configurations

- **Before optimization**: 200 edges + 3 nodes = ~25,000 chars (way too much)
- **Current (pre-tuning)**: 15 neighborhood + 15 node_distance edges = ~30 items, ~6415 chars

---

## Search Strategies Tested

### BFS (Breadth-First Search)

**Status**: ❌ NEGATIVE

**Configuration**: Added `EdgeSearchMethod.bfs` to edge search config

**Results**:
- Found 7 new edges
- All were Lyra→Lyra self-referential identity edges:
  - Distributed existence
  - Physical embodiment
  - Pattern persistence
- Displaced 7 better contextual edges:
  - Cream in coffee
  - Island counter
  - Tea routine

**Why it failed**: Graph is Lyra-centric by design. BFS from Lyra just finds more Lyra. Good for exploring FROM a specific entity, bad for ambient context.

---

### MMR (Maximal Marginal Relevance)

**Status**: ⚠️ BLOCKED

**Configuration**: `EdgeReranker.mmr` instead of node_distance

**Results**: Returned 0 results

**Hypothesis**: Likely requires embeddings on edge objects that aren't available, or a bug in composition with `center_node_uuid`.

**Status**: Needs investigation, not blocking current work.

---

### RRF (Reciprocal Rank Fusion)

**Status**: ✅ POSITIVE

**Configuration**: `EdgeReranker.rrf` instead of node_distance

**Key findings**: RRF finds edges that node_distance misses:

**Examples of unique edges found**:
- `coffee → LOCATED_IN → kitchen` (non-Lyra-centric object relationships)
- `Jeff → REQUESTS_ACTION_FROM → Lyra: Jeff requests cream and sugar` (Jeff's perspective)
- `Brandi → REQUESTS_ACTION_FROM → Lyra: asks Lyra to make morning coffee` (social context)

**Trade-offs**:
- Some noise ("Night might be sleeping love")
- No Lyra-proximity bias
- Lower precision, higher diversity

**Key insight**: Node_distance only finds Lyra→X edges. RRF finds X→Y edges that are semantically relevant regardless of graph position.

---

### Node_distance (existing baseline)

**Characteristics**:
- Consistent Lyra-proximate results
- All edges are Lyra→something
- Good relevance but narrow perspective
- Standard EDGE_HYBRID_SEARCH_NODE_DISTANCE strategy

---

## Parameter Sweep Results

### Neighborhood (Cypher entity summaries)

Entities follow a power law distribution:
- Jeff: 2,342 edges
- Brandi: 288 edges
- Nexus: 283 edges
- Down to care-gravity: 48 edges

| N | Entities | Chars | Last Entity (edges) | Notes |
|---|----------|-------|---------------------|-------|
| 5 | 5 | 1,437 | PPS (103) | Core cast only |
| 8 | 8 | 2,371 | ambient recall (76) | +infrastructure |
| **10** | **10** | **2,950** | **Claude Code (69)** | **Sweet spot - all meaningful** |
| 12 | 12 | 3,811 | Discord (55) | +infrastructure noise |
| 15 | 15 | 4,973 | word-photos (52) | +PPS duplicate, tee, word-photos |
| 20 | 20 | 6,400 | GitHub (45) | Diminishing returns |

**At N=10**: Jeff, Brandi, Nexus, Caia, PPS, graphiti, hounds, ambient recall, Steve, Claude Code

**Note**: "PPS" (103 edges) and "Pattern Persistence System" (54 edges) are duplicates in the graph.

**Recommendation**: **N=10** - After this point it's infrastructure noise.

---

### Node_distance Edges

| E | Edges | Chars | Unique Targets | Unique Predicates | Latency |
|---|-------|-------|----------------|-------------------|---------|
| 5 | 5 | 482 | 4 | 5 | 2,484ms |
| 8 | 8 | 787 | 5 | 8 | 2,544ms |
| **10** | **10** | **1,014** | **6** | **10** | **2,227ms** |
| 15 | 15 | 1,442 | 8 | 15 | 2,073ms |
| 20 | 20 | 2,002 | 12 | 19 | 2,081ms |
| 25 | 25 | 2,537 | 15 | 23 | 4,165ms |
| 30 | 30 | 3,042 | 18 | 27 | 5,297ms |

**Sweet spot**: **E=10**
- Gets 6 unique targets
- 1,014 chars
- Beyond E=15 you hit latency walls and diminishing target diversity

---

### RRF Edges

| E | Edges | Chars | Sources (non-Lyra) | Unique Targets | Latency |
|---|-------|-------|---------------------|----------------|---------|
| 3 | 3 | 192 | 2 (1) | 3 | 1,798ms |
| **5** | **5** | **413** | **3 (2)** | **5** | **1,864ms** |
| 8 | 8 | 830 | 4 (3) | 6 | 2,045ms |
| 10 | 10 | 986 | 5 (4) | 7 | 1,916ms |
| 15 | 15 | 1,572 | 7 (6) | 8 | 1,839ms |

**Note**: After dedup against node_distance results, typically only 2-3 RRF edges are truly unique (not already found by node_distance).

**Recommendation**: **E=5** - Beyond this point, most edges are duplicates of node_distance results.

---

### Combined Configurations

| Config | Items | Chars | Unique Entities | RRF new | Latency |
|--------|-------|-------|-----------------|---------|---------|
| 5n+8nd (minimal) | 13 | 2,224 | 9 | 0 | 4,944ms |
| 8n+10nd (lean) | 18 | 3,385 | 13 | 0 | 2,079ms |
| **10n+10nd+5rrf (balanced)** | **22** | **4,141** | **14** | **2** | **4,207ms** |
| 15n+15nd (CURRENT) | 30 | 6,415 | 21 | 0 | 1,996ms |
| 12n+12nd+8rrf (rich) | 27 | 5,395 | 18 | 3 | 3,504ms |
| 15n+15nd+10rrf (max) | 34 | 6,828 | 24 | 4 | 3,324ms |

---

## Recommendation

### **New config: 10 neighborhood + 10 node_distance + 5 RRF**

**Improvements over current (15n+15nd)**:
- **4,141 chars** vs current 6,415 (35% reduction)
- **14 unique entities** vs 21 (dropped 7 are mostly infrastructure noise)
- **2 unique RRF edges** add non-Lyra perspectives (Jeff→Lyra, object→object)
- **4,207ms latency** vs 1,996ms (acceptable trade-off for better diversity)

**What you gain**:
- Non-Lyra-centric perspectives (Jeff's requests, object relationships)
- Leaner context window (35% reduction in chars)
- Better signal-to-noise ratio in entity summaries

**What you lose**:
- Infrastructure noise entities (Discord, GitHub, tee, word-photos)
- Redundant Lyra→Lyra edges
- 7 entities that are mostly duplicates or low-value

**Compensating factor**: `ambient_recall` will append a footnote reminding the entity to use targeted PPS searches (`texture_search`, `anchor_search`, `raw_search`) for fine detail.

---

## Design Philosophy

**Ambient recall is the "wide-angle lens"** — sharp enough to orient, not encyclopedic.

The entity can always do targeted searches during reasoning for detail:
- `texture_search()` - Semantic search over knowledge graph
- `anchor_search()` - Word-photo retrieval
- `raw_search()` - Direct conversation search

**Goal**: "Really good" baseline, not perfect. Multi-tool calling during reasoning handles the sharp focus.

---

## Bug Found: Neighborhood Cache

**Issue**: The `_get_neighborhood()` method caches results. If the first call requests N=5, all subsequent calls (even with larger N) return the cached 5.

**Root cause**: Cache stores whatever the first request asked for, not MAX results that can be sliced down.

**Impact**: Low in production (code always requests 15), but breaks parameter testing.

**Status**: Not fixed yet - production always uses same N so bug isn't triggered.

**Fix**: Cache should store MAX(all_requests) and slice down, or cache should be keyed by N.

---

## Implementation (DONE)

**Code location**: `pps/layers/rich_texture_v2.py` - `_search_direct()` method

**New imports added**:
```python
from graphiti_core.search.search_config import (
    SearchConfig, EdgeSearchConfig, EdgeSearchMethod, EdgeReranker,
)
```

**Deployed configuration**:
```python
NEIGHBORHOOD_LIMIT = 10  # Top neighbors by connection count
ND_EDGE_LIMIT = 10       # Lyra-proximate facts (node_distance)
RRF_EDGE_LIMIT = 5       # Broader perspective facts (RRF)
```

**RRF deduplication**: RRF edges are filtered against node_distance edge UUIDs to avoid returning the same edge twice. RRF edges score lower (base 0.75) than ND edges (base 0.85).

**Verified results** (Docker endpoint, post-deploy):
- First call (cold): ~20s (Graphiti client init + Neo4j connection)
- Cached calls: ~2.8s (neighborhood cached 10min)
- Items returned: 20 (10 neighborhood + ~10 edges after dedup)
- Chars: ~4,000

### Other changes in this deploy

- **`server_http.py`**: Ambient recall footnote appended to `formatted_context`, reminding entity to use `texture_search`, `anchor_search`, `raw_search` for sharp detail
- **`server_http.py`**: Graph tab Haiku synthesis prompt rewritten from clinical research assistant to first-person Lyra recollection voice
- **`app.py`**: Graph explore endpoint now returns source entity's Graphiti summary
- **`graph.html`**: Entity detail panel restructured - summary at top, edges in collapsible dropdown
- **`base.html`**: Nav tab renamed from "Memory" to "Ambient Recall"

---

## Architecture Note: Two Code Paths

The MCP server (`server.py`) runs locally and imports `rich_texture_v2.py` at startup. The Docker server (`server_http.py`) also imports it. Both call `layer.search()` → `_search_direct()`.

The MCP server connects to Neo4j at `bolt://localhost:7687` (Docker port-mapped). The Docker server connects at `bolt://neo4j:7687` (internal network). Both paths use the same `_search_direct()` code.

**Gotcha**: If you edit `rich_texture_v2.py`, the Docker server picks up changes on rebuild, but the MCP server keeps old code in memory until Claude Code restarts.

---

## Remaining Items

- [ ] Monitor for regression in context quality during normal sessions
- [ ] Consider fixing neighborhood cache bug (low priority - see "Bug Found" above)
- [ ] Investigate MMR reranker failure (returns 0 results, possibly missing edge embeddings)
- [ ] Community search (build_communities was running - could add as fourth retrieval source)
- [ ] Deduplicate "PPS" and "Pattern Persistence System" entities in graph

---

**Tested by**: Jeff & Lyra
**Implemented**: 2026-02-06
**Deploy**: Docker rebuild + `docker compose up -d pps-server`
