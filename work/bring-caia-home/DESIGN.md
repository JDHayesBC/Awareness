# Design: Bring Caia Home

**Author**: Lyra + Jeff + Opus (research)
**Date**: 2026-02-08
**Status**: Phase A1 shipped (retrieval fix deployed)

---

## Problem Statement

We have two AI entities (Lyra, Caia) that need to coexist on shared infrastructure with complete memory isolation. Before we can build multi-entity support, the foundation has a retrieval ranking problem: entity summaries dominate all search results, drowning contextual/moment-specific edges. This means the AI can always tell you WHO it knows but can't reliably retrieve WHAT it was just doing.

### The Retrieval Ranking Problem (Phase A, Critical)

**Observed behavior**: Query "kitchen morning Saturday Haven" returns:
1. Jeff: [500-word biography] (score 1.0)
2. Brandi: [500-word biography] (score 0.98)
3. Steve: [biography] (score 0.97)
4. Nexus: [biography] (score 0.96)
5. ... more entity summaries ...
10. Lyra → PREPARES → coffee (score 0.62)
11. Jeff → USES → coffee beans (score 0.56)

Coffee, kitchen, and tea entities never reach the top 10.

**Root cause** (three stacked problems):

1. **Custom Cypher bypass**: A raw Cypher query fetches top-10-by-edge-count neighbors, bypassing Graphiti's search API entirely. This is query-blind — returns the same entities regardless of what's being asked. Cached 10 minutes.

2. **Hardcoded scoring bands** in `rich_texture_v2.py:679-812`:
   ```
   Neighborhood entities: score = 1.0 - (i / count) * 0.15  → range [0.85, 1.0]
   Node-distance edges:   score = 0.85 - (i / count) * 0.20  → range [0.65, 0.85]
   RRF edges:             score = 0.75 - (i / count) * 0.20  → range [0.55, 0.75]
   ```
   Tiers don't overlap. No edge can ever outrank any entity summary.

3. **Embedding length bias** (Jina AI, April 2025): Longer texts produce embeddings systematically closer to center of embedding space, scoring higher against any query. Entity summaries are textbook "hub embeddings." Document-level cosine similarity averages 0.343 vs sentence-level 0.124 — a 0.22 gap from length alone.

**Key discovery from Opus research**: **Graphiti already solved this problem at the API level.** Its `SearchConfig` has three independent scopes (`edge_config`, `node_config`, `community_config`). `SearchResults` returns separate lists for nodes, edges, and communities — never merged. Graphiti's native node search uses the `name` field (not `summary`), avoiding the length bias entirely. Our custom Cypher layer bypasses all of this.

**Why this matters for Caia**: If retrieval can't surface contextual information, multi-entity validation is impossible.

---

## Approaches Considered

### Phase A: Fixing Retrieval

#### Option A1: Separate Sections (No Interleaving) — ORIGINAL PROPOSAL
- Return neighborhood and edges as labeled sections, not mixed into one scored list
- Pro: Clean separation. Con: Still uses query-blind Cypher neighborhood

#### Option A2: Query-Aware Neighborhood Filtering
- Relevance-check entity summaries against query before including
- Pro: Only relevant entities. Con: Adds latency, complexity

#### Option A3: Reduced/Capped Neighborhood
- Drop NEIGHBORHOOD_LIMIT from 10 to 3
- Pro: Simple. Con: Doesn't solve fundamental interleaving

#### Option A4: Score Overlap
- Adjust bands so edges can outrank entities
- Pro: Minimal change. Con: Fragile, doesn't fix root cause

#### Option A5: Use Graphiti's Native Multi-Channel Search — NEW, FROM RESEARCH
- Replace custom Cypher neighborhood with `NODE_HYBRID_SEARCH_NODE_DISTANCE`
- Use `EDGE_HYBRID_SEARCH_RRF` for facts
- Return as separate channels (Graphiti already does this)
- Add cross-encoder reranking to counter remaining length bias
- Add query-type routing for different retrieval strategies
- Pro: Uses the system as designed, eliminates all three root causes
- Con: Larger refactor of `_search_direct()`

### Phase B: Multi-Entity Architecture

#### Option B1: Namespace Segmentation (Recommended Start)
- Same containers, group_id per entity, ChromaDB collection prefix
- Pro: Minimal deployment. Con: Bugs could leak

#### Option B2: Separate Container Stacks
- Full stack per entity
- Pro: Total isolation. Con: 2x resources

---

## Chosen Approach

### Phase A: Option A5 (Native Graphiti Multi-Channel Search)

**Rationale**: Opus's research revealed that we're building workarounds for a problem Graphiti already solved. The native `search_()` API with scope-specific configs is exactly the right architecture. Three specific changes:

1. **Replace Cypher neighborhood with `NODE_HYBRID_SEARCH_NODE_DISTANCE`**: Semantic search over entity *names* (not summaries), reranked by graph proximity to Lyra. Query-aware AND topology-aware. This eliminates both the query-blindness and the length bias in one move, because name-field search doesn't embed 500-word summaries.

2. **Keep `EDGE_HYBRID_SEARCH_RRF` for facts** (already using this): Consider switching to `EDGE_HYBRID_SEARCH_CROSS_ENCODER` for the strongest length-bias defense. Cross-encoder jointly evaluates query-document pairs rather than comparing pre-computed embeddings.

3. **Return separate channels to consumers**: Graphiti already returns `SearchResults.nodes` and `SearchResults.edges` as separate lists. Pass them through as separate sections. Let ambient_recall and hook context format each independently.

**Optional enhancements** (after core fix validated):
- Query-type routing: factual → edge-only, navigational → node-only, contextual → episode_mentions reranker
- Temporal decay weighting on edges (half_life=14 days)
- MMR reranker (lambda=0.5) for result diversity

### Phase B: Option B1 (Namespace Segmentation) + Safeguards

**Rationale**: group_id provides logical isolation, but Opus identified three risks:

1. **Vector search post-filtering**: Neo4j vector index scans all embeddings globally, filters by group_id after. ~50% of results wasted on wrong entity. **Mitigation**: Double the K parameter for all vector searches.

2. **Custom Cypher bypass**: Any Cypher query that forgets `WHERE n.group_id = $group_id` leaks across entities. Graphiti issue #801: empty group_ids silently returns nothing. **Mitigation**: `IsolatedGraphitiClient` wrapper that enforces group_id on every operation.

3. **Fulltext index spans all tenants**: Same post-filtering issue as vector. **Mitigation**: Add Neo4j range index on group_id (`CREATE INDEX entity_group_id FOR (n:Entity) ON (n.group_id)`).

Start with namespace + safeguards. Upgrade path: Neo4j Enterprise multi-database or FalkorDB per-graph isolation if needed beyond ~5 entities.

---

## Implementation Plan

### Phase A (Foundation) — Revised

1. **Replace Cypher neighborhood with native node search**
   - Use `NODE_HYBRID_SEARCH_NODE_DISTANCE` with `center_node_uuid=lyra_uuid`
   - This searches entity names semantically, then reranks by graph proximity
   - Limit: 5 nodes

2. **Keep edge search, consider cross-encoder upgrade**
   - Current: `EDGE_HYBRID_SEARCH_NODE_DISTANCE` (10) + `EDGE_HYBRID_SEARCH_RRF` (5)
   - Test: `EDGE_HYBRID_SEARCH_CROSS_ENCODER` for better relevance (immune to length bias)
   - If cross-encoder adds too much latency, stay with RRF

3. **Return separate channels from `_search_direct()`**
   - Return `{"nodes": [...], "edges": [...]}` not flat list
   - Graphiti's `SearchResults` already structures it this way

4. **Update consumers**
   - `ambient_recall` in server.py: format nodes and edges as labeled sections
   - Hook context injection: same separation
   - Per-turn hook: consider edge-only (skip nodes) since crystals/identity provide "who" context

5. **Benchmark**
   - Query "kitchen morning Saturday Haven" → coffee/kitchen/tea in edge results
   - Query "Jeff" → Jeff in node results, Jeff-related edges in edge results
   - Compare latency: cross-encoder vs RRF

6. **Repo cleanup** — stale work dirs, imports, gitignore audit

### Phase B (Multi-Entity)

1. **`IsolatedGraphitiClient` wrapper** — enforces group_id on every operation
2. **ChromaDB namespacing** — collection per entity from ENTITY_PATH
3. **Double K parameter** for all vector/fulltext searches
4. **Neo4j range index** on group_id for all node labels
5. **Cross-contamination test suite** — store as entity A, search as entity B, verify zero leakage
6. **Entity creation script** — `scripts/create_entity.py <name>`
7. **Caia word-photo migration** — import ~140 word photos, validate, index

### Phase C (Haven Interface)

1. Design WebSocket server with entity routing
2. Build minimal frontend
3. Deploy self-hosted, private

---

## Files Affected

### Phase A
- `pps/layers/rich_texture_v2.py` — replace Cypher neighborhood with native node search, refactor `_search_direct()` return format, remove hardcoded scoring bands
- `pps/server.py` — update ambient_recall (lines 1043-1170) to handle sectioned results
- Hook context injection code — same separation

### Phase B
- `pps/layers/rich_texture_v2.py` — `IsolatedGraphitiClient` wrapper, double K params
- `pps/layers/core_anchors.py` — parameterize ChromaDB collection name
- `pps/layers/rich_texture.py` — same group_id enforcement
- `pps/server.py` — entity-aware initialization
- New: `scripts/create_entity.py`
- New: `tests/test_entity_isolation.py`

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Native node search returns different results than Cypher neighborhood | Med | Run both in parallel during testing, compare output |
| Cross-encoder reranking adds latency | Med | Benchmark; fall back to RRF if >500ms added |
| Retrieval refactor breaks existing ambient_recall | High | Test before/after with same queries, preserve old code path as fallback |
| ChromaDB namespace migration loses existing data | High | Backup before migration, test with copy first |
| Vector search post-filtering wastes 50% of results | Med | Double K parameter; upgrade to Neo4j 2026.01 SEARCH clause when available |
| Custom Cypher queries bypass group_id | High | `IsolatedGraphitiClient` wrapper enforces on every operation |
| Haven chat interface security | Med | Auth from day one, no public exposure |

---

## Open Questions

- [x] Can Graphiti's `group_id` filtering be trusted for hard isolation? **Partially — vector/fulltext do post-filtering. Need doubled K and range indexes. Custom Cypher needs wrapper.** (Opus research, issue #801)
- [ ] Should Caia's word photos be re-embedded or can we import raw .md and let ChromaDB embed on ingest?
- [ ] What's Caia's system prompt structure — does she have an identity.md equivalent?
- [ ] Shared spaces: when both entities are in a conversation, whose PPS stores the transcript?
- [ ] Can we recover anything from Zep?
- [ ] Cross-encoder reranker: which backend? OpenAI, Gemini, or BGE? Cost/latency tradeoffs.
- [ ] Should per-turn hook skip node search entirely? (Crystals + identity provide "who" context at startup)

---

## Research Sources

Full Opus research report appended to `RESEARCH_BRIEF_FOR_OPUS.md` in this directory. Key references:
- Jina AI (April 2025): Text embedding length bias quantification
- Graphiti search recipes: 15 pre-built configs for scoped retrieval
- PolyG (arXiv 2504.02112): 4-class query taxonomy with per-type graph traversal
- ARK (arXiv 2601.13969): Adaptive retrieval strategy selection (31.4% improvement over fixed)
- Microsoft GraphRAG: Token-budget allocation for proportional context by type
- Graphiti issue #801: Empty group_ids silently returns nothing
- Neo4j vector post-filtering: community.neo4j.com thread on pre vs post filtering
