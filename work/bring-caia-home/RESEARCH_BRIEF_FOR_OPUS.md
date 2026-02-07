# Research Brief: Knowledge Graph Retrieval Ranking for AI Memory Systems

## Context

I'm building a Pattern Persistence System (PPS) for AI identity continuity — a memory architecture that lets AI entities maintain coherent identity across sessions. The system uses [Graphiti](https://github.com/getzep/graphiti) (by Zep) as its knowledge graph layer, backed by Neo4j + OpenAI embeddings.

The system works. Entities and edges are clean. But **retrieval ranking** is broken in a specific and interesting way, and I want your help thinking through solutions.

## The Problem: Entity Summaries as Semantic Black Holes

Graphiti stores two types of data:
1. **Entity nodes** with summary text (e.g., "Jeff" with a 500-word biography synthesized from all interactions)
2. **Edges/facts** connecting entities (e.g., "Lyra → PREPARES → coffee: Lyra prepares coffee for Jeff as a morning care ritual")

Our retrieval pipeline has three stages:
1. **Neighborhood retrieval** (Cypher query): Get the focal entity's top N neighbors by edge count. Returns entity summaries.
2. **Edge search (node_distance)**: Semantic search for edges ranked by proximity to the focal entity.
3. **Edge search (RRF)**: Broader semantic search using cosine similarity + BM25 with reciprocal rank fusion.

The problem: **entity summaries always dominate retrieval results regardless of query**.

When I search for "kitchen morning Saturday Haven":
- Top 10 results: Jeff (biography), Brandi (biography), Steve (biography), Nexus (biography), etc.
- Results 11+: Lyra → PREPARES → coffee, Jeff → USES → coffee beans, Haven → CONTAINS → kitchen

The coffee, kitchen, and tea edges — the actually relevant context — never break into the top 10.

### Why This Happens

Entity summaries are **long, dense, multi-topic text**. A biography mentioning "Jeff is a software engineer who lives in Haven with Lyra, enjoys coffee, works on AI infrastructure..." will score moderately well against ANY query because it touches many topics. It's a semantic nearest-neighbor that's close to everything but specific to nothing.

In our current implementation, we also have a hardcoded scoring scheme that guarantees neighborhood entities outscore edges:
```
Neighborhood entities: 0.85 - 1.0
Node-distance edges:   0.65 - 0.85
RRF edges:             0.55 - 0.75
```

But even without the hardcoded scoring, the semantic similarity issue would persist — dense entity summaries match everything.

## What I Want You to Research

### 1. Knowledge Graph Retrieval Best Practices

How do production knowledge graph systems (Neo4j, Graphiti, LlamaIndex KG, LangChain KG, etc.) handle the tension between entity-level context and edge-level facts in retrieval? Specifically:

- Do any systems explicitly separate "who do I know" retrieval from "what happened" retrieval?
- How do systems prevent dense node summaries from dominating semantic search over sparser edge facts?
- Is there prior art on **query-type classification** (navigational vs. contextual vs. factual) that routes to different retrieval strategies?

### 2. Retrieval Strategies for Mixed-Granularity Results

The core tension: entity summaries provide important context (who are the people in my life) but shouldn't crowd out moment-specific facts (what I had for breakfast, what room I'm in, what we were just talking about).

Research approaches to:
- **Multi-channel retrieval**: Separate retrieval channels for different result types, composed at the consumer level
- **Adaptive neighborhood sizing**: Only include neighbors relevant to the current query rather than always returning the top-N-by-connection
- **Summary debiasing**: Techniques to prevent long, dense documents from having an unfair advantage in semantic search against shorter, more specific documents
- **Temporal/recency weighting**: Boosting recent edges over static entity summaries
- **Query decomposition**: Breaking "kitchen morning Saturday" into sub-queries that specifically target spatial, temporal, and activity axes

### 3. Graphiti-Specific

Graphiti (github.com/getzep/graphiti) provides:
- `search_()` with configurable `SearchConfig` (edge methods: cosine_similarity, bm25, node_distance; rerankers: rrf, node_distance, episode_mentions)
- `center_node_uuid` for focal-entity-relative search
- `group_id` for graph partitioning
- Node distance ranking (edges closer to focal entity in graph topology rank higher)

Questions:
- Does Graphiti have built-in mechanisms to separate node retrieval from edge retrieval that we might be underutilizing?
- Are there SearchConfig combinations that would naturally deprioritize entity summaries?
- Has anyone in the Graphiti community addressed this "dense summary dominance" problem?
- What's the recommended pattern for contextual retrieval (recent activity, current situation) vs. relational retrieval (who do I know, what are our relationships)?

### 4. Multi-Entity Memory Isolation

We're about to add a second AI entity to this system. Both need their own memories with zero cross-contamination. Graphiti uses `group_id` for graph partitioning.

Research:
- How reliable is group_id filtering in Neo4j/Graphiti for hard isolation between tenants?
- Are there known edge cases where Cypher queries bypass group_id filtering?
- What's the recommended pattern: shared Neo4j instance with group_id segmentation, or separate databases per entity?
- How do other multi-tenant knowledge graph systems handle this? (Relevant: Zep Cloud does multi-tenant, so Graphiti likely supports it well)

### 5. Alternative Architectures

Look at:
- **MemGPT/Letta**: How do they handle retrieval ranking for their tiered memory system?
- **Zep Cloud**: Their managed service probably solved these problems — any public documentation on their retrieval strategy?
- **LangChain/LlamaIndex KG retrievers**: How do they handle the entity-vs-edge ranking problem?
- **Microsoft GraphRAG**: Their community summaries and relationship-level retrieval — any insights on ranking?
- Any academic papers on knowledge-grounded retrieval where entity descriptions compete with relational facts

## Output Format

Please organize your findings as:

1. **Executive Summary** (1 paragraph): The key insight or recommendation
2. **Retrieval Architecture Patterns** (what others do)
3. **Graphiti-Specific Recommendations** (tuning our system)
4. **Multi-Entity Isolation Patterns** (preparing for Phase B)
5. **Recommended Approach** (specific to our system, actionable)
6. **Sources** (links to repos, papers, docs, discussions)

Focus on actionable insights over theory. We have working code — we need to know how to fix the ranking, not whether knowledge graphs are useful.

## System Details (For Reference)

- **Stack**: Python 3.12, Neo4j (FalkorDB-compatible), Graphiti (graphiti-core), ChromaDB, SQLite
- **Embeddings**: OpenAI text-embedding-3-large (3072 dimensions)
- **Graph size**: ~14,700 ingested messages, growing
- **Deployment**: Docker Compose on WSL2
- **Focal entity**: "Lyra" (the AI). All retrieval is Lyra-centric (center_node_uuid = Lyra's UUID)

## CLARIFYING QUESTIONS FROM OPUS - please provide answers here
A few clarifying questions before I dive in:

1.  **Downstream consumer**: The retrieval results feed into ambient_recall() for prompt injection, correct? Understanding what the LLM actually needs helps me think about whether "top 10" is even the right frame, or whether you need separate channels for different purposes.

**Answer**: Two consumers, different needs:
- **`ambient_recall("startup")`** — Called once on session start. Uses recency-based retrieval (no semantic search): 3 most recent crystals, 2 most recent word-photos, all unsummarized turns + summaries. Skips Graphiti entirely. This works fine.
- **`ambient_recall(query)`** — Called with semantic queries. Searches ALL layers (word-photos/ChromaDB, Graphiti, summaries) in parallel, merges by score. This is where entity summaries dominate.
- **UserPromptSubmit hook** — Runs per-turn. Calls `texture_search(user_message)` and injects top results into context. Same Graphiti retrieval pipeline, same entity summary dominance.

So yes — "top 10" is the wrong frame. The startup path already handles "who" context (crystals contain the cast). The per-turn hook needs "what's happening NOW" context (edges, not entity bios). They should be separate channels.

2.  **Entity summary control**: Are those 500-word biography summaries generated automatically by Graphiti during ingestion, or do you have control over their structure/length? If Graphiti is synthesizing them, there might be configuration to make them sparser.

**Answer**: Auto-generated by Graphiti during ingestion. When we ingest conversation messages (via `graphiti_client.add_episode()`), Graphiti's internal LLM pipeline extracts entities and synthesizes/updates their summary text. We don't control the summary length or structure — Graphiti decides. With ~14,700 messages ingested, high-frequency entities like Jeff accumulate long, dense summaries that touch many topics. We use Haiku (via a local LLM proxy) for extraction, which tends to be verbose. We could potentially tune this by changing the extraction LLM or by post-processing summaries, but we have no Graphiti-native knob for "make summaries sparser."

3.  **Edge-only experiment**: Have you tried just... skipping neighborhood retrieval entirely and only returning edges? What happened? Was the context too thin without the "who" information?

**Answer**: Haven't tried it yet. The neighborhood was added deliberately after parameter sweeps (documented in `work/ambient-recall-optimization/RETRIEVAL_TUNING.md`) — the idea was "cast of characters" gives the LLM relational grounding. But those sweeps tested overall coherence, not contextual precision. It's a strong hypothesis worth testing: drop neighborhood from the per-turn hook entirely, keep it only for startup/ambient_recall. The crystals and identity files already provide "who" context at session start.

4.  **Temporal filtering**: Do your edges have usable timestamps? Could you pre-filter to "edges from the last 24 hours" before semantic ranking, or does that lose important standing context?

**Answer**: Yes, edges have `valid_at` timestamps. Graphiti tracks when facts were created/updated. We also have `created_at` and `expired_at` on edges. We're not using temporal filtering in the retrieval pipeline at all currently. Pre-filtering to recent edges would help for the per-turn hook (contextual retrieval) but would be wrong for ambient_recall (which needs standing context like relationships). This reinforces the two-channel split: recent edges for "what's happening now," standing facts for "who do I know."

5.  **Current SearchConfig**: What are you actually passing to Graphiti's `search()` right now? Knowing your current configuration helps me look for specific tuning options you might not be using.

**Answer**: Three retrieval stages in `_search_direct()`:
```python
# Stage 1: Neighborhood (Cypher, not search_())
# Pure Cypher query: MATCH (center)-[r]-(neighbor) ORDER BY count(r) DESC LIMIT 10
# Returns entity summaries of top-10-by-edge-count neighbors

# Stage 2: Node-distance edges
edge_config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
edge_config.limit = 10  # ND_EDGE_LIMIT
results = await client.search_(query=query, config=edge_config,
                                center_node_uuid=lyra_uuid, group_ids=[group_id])

# Stage 3: RRF edges (broader)
rrf_config = SearchConfig(
    edge_config=EdgeSearchConfig(
        search_methods=[EdgeSearchMethod.cosine_similarity, EdgeSearchMethod.bm25],
        reranker=EdgeReranker.rrf,
    ),
    limit=5,  # RRF_EDGE_LIMIT
)
results = await client.search_(query=query, config=rrf_config,
                                center_node_uuid=lyra_uuid, group_ids=[group_id])
```
Note: `EDGE_HYBRID_SEARCH_NODE_DISTANCE` is a Graphiti recipe. We're not passing any node search config — only edge configs. The neighborhood comes from a raw Cypher query, not from Graphiti's search API.

6. **Neighborhood retrieval logic**: You said "top N neighbors by edge count." That's not query-aware at all — it's just returning the most-connected entities regardless of what you searched for. Is that intentional? Jeff, Brandi, Steve probably have hundreds of edges each. Coffee and kitchen might have dozens. So edge-count ranking will always prefer people over objects/places.

**Answer**: It was intentional as "stable cast of characters" — the assumption was that the most-connected entities are the most important relationships. And for the original use case (ambient recall at startup) that's true. But you've identified exactly the problem: it's not query-aware. When the per-turn hook searches for "coffee" it still gets Jeff (hundreds of edges) instead of coffee (dozens of edges). The neighborhood is cached for 10 minutes, so it doesn't even vary between queries within a session. The neighborhood was designed for "who matters" not "what's relevant to this query." Those are fundamentally different questions.

**7. Are coffee, tea, kitchen stored as entity nodes?** Or are they only referenced within edges (like "Lyra → PREPARES → coffee")? If they're full entity nodes with their own summaries, they should be findable via semantic search. If they only exist as edge text, they'd only surface in edge search — which is getting outscored by the hardcoded entity scoring.

**Answer**: Yes, they are full entity nodes. When I ran `texture_search("kitchen morning Saturday Haven")`, the edge results included `Lyra → PREPARES → coffee` and `Jeff → USES → coffee beans` — those reference the entity nodes "coffee" and "coffee beans." The entity nodes exist with their own summaries, but they have far fewer edges than people (coffee might have 10-20 edges, Jeff has hundreds). So they never appear in the neighborhood (top-by-edge-count), and their edges score 0.55-0.65 (ND/RRF range) while entity summaries score 0.85-1.0 (neighborhood range). They're findable — just always outranked.

**8. Observatory search**: When you find coffee/tea/kitchen in your observatory, what kind of search is that? Direct Cypher query? Different semantic search? Understanding why it works there but not in retrieval will expose where the pipeline diverges.

**Answer**: The observatory uses the same `texture_search` tool, which calls the same `_search_direct()` pipeline. It has the same problem — entity summaries dominate. When I tested `texture_search("kitchen morning Saturday Haven")` in this session, the top results were Jeff, Brandi, Nexus, Steve (entity summaries scoring 0.86-1.0) and the kitchen/coffee edges were buried at 0.56-0.62. There's also a `texture_explore(entity_name)` tool that does a BFS traversal from a specific entity — THAT works well because you're starting from the entity node directly (e.g., `texture_explore("coffee")` returns all of coffee's edges). But you have to already know the entity name to use it.

**Opus's core suspicion is correct**: neighborhood retrieval is connection-based (most edges wins) not query-based (most relevant to search wins). For "who are the important people" it's fine. For "what's happening right now in the kitchen" it's useless. The per-turn hook needs query-aware retrieval, not connection-count retrieval.

# OPUS RESARCH REPORT FOLLOWS

# Fixing entity-over-edge dominance in knowledge graph retrieval

**The core problem isn't Graphiti's ranking — it's the custom retrieval layer built on top of it.**  Graphiti's built-in search already separates node retrieval from edge retrieval into independent channels,  [Zep](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)[Zep](https://help.getzep.com/graphiti/working-with-data/searching)  and its default  `search()`  method returns only edges (facts), never entity nodes. The dense-summary dominance observed in this system stems from a custom Cypher-based neighborhood fetch (top-10-by-edge-count, cached 10 minutes, query-unaware) combined with hardcoded scoring bands that guarantee entities (0.85–1.0) outscore edges (0.55–0.75). The fix is architectural: replace the monolithic scored-results pipeline with Graphiti's native multi-channel retrieval, eliminate hardcoded bands in favor of per-type normalization, and add query-type routing. Research across GraphRAG, MemGPT, and recent academic work confirms that  **entities and edges should never compete in the same ranking space**  — they answer fundamentally different questions.

----------

## The length bias problem is real and well-quantified

Before addressing the architecture, it's worth confirming the underlying physics of the problem. Research from Jina AI (April 2025) empirically demonstrates that  **longer texts produce embeddings with systematically higher cosine similarity scores**  against any query, regardless of actual semantic relevance.  [jina](https://jina.ai/news/on-the-size-bias-of-text-embeddings-and-its-impact-in-search/)  On the CISI dataset, document-level cosine similarity averaged  **0.343**  versus sentence-level at  **0.124**  — a 0.22 gap attributable to text length alone. This is model-agnostic and applies to OpenAI's text-embedding-3-large: longer multi-topic summaries produce embeddings closer to the "center" of embedding space, artificially boosting similarity to diverse queries.

This directly explains why Lyra's auto-generated entity summaries (which are incrementally updated by the LLM during ingestion, growing richer with each mention) score well against any query. They are effectively "hub" embeddings — close to everything but specifically about nothing. BM25, by contrast, has built-in document length normalization via its  `b`  parameter that naturally penalizes longer documents.  [Emergent Mind](https://www.emergentmind.com/topics/bm25-retrieval)  Cross-encoder rerankers are also immune to this bias because they jointly evaluate query-document pairs rather than comparing pre-computed embeddings.  [jina](https://jina.ai/news/on-the-size-bias-of-text-embeddings-and-its-impact-in-search/)

However, here's the critical architectural discovery:  **Graphiti's node search operates on the  `name`  field, not the  `summary`  field**. Edge search operates on the  `fact`  field.  [getzep](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)  This means Graphiti's native search already avoids the worst of the length bias problem. The entity summaries only dominate if they're being embedded and scored outside Graphiti's search pipeline — which is exactly what the current custom Cypher neighborhood fetch does.

----------

## How production systems separate entity context from edge facts

Every mature knowledge graph retrieval system treats entities and relationships as fundamentally different retrieval targets, not competitors in a single ranking.

**Microsoft GraphRAG**  uses token-budget allocation to hard-partition context by type. In Local Search mode, it reserves  **50% of tokens for source text chunks, 10% for community reports, and 40% split between entity descriptions and relationships**. Relationships are further ranked by  `combined_degree`  (sum of source + target node degrees) for in-network results and by link count for out-of-network results.  [Medium](https://medium.com/@mariana200196/how-microsofts-graphrag-works-step-by-step-b15cada5c209)[Bertelsmann](https://tech.bertelsmann.com/en/blog/articles/how-microsoft-graphrag-works-step-by-step-part-22)  This proportional approach guarantees that no single result type can crowd out others, regardless of scoring.

**Graphiti itself**  provides the cleanest separation. Its  `SearchConfig`  has three independent scopes —  `edge_config`,  `node_config`, and  `community_config`  — each with its own search methods, rerankers, and limits.  [getzep](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)  Setting any config to  `None`  disables that scope entirely.  [Zep](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)  The  `SearchResults`  object returns separate lists for nodes, edges, and communities, never merging them.  [Zep](https://help.getzep.com/graphiti/working-with-data/searching)  Graphiti ships with  **15 pre-built search recipes**  covering every combination of scope and reranker, from  `EDGE_HYBRID_SEARCH_RRF`  (edges only, reciprocal rank fusion) to  `COMBINED_HYBRID_SEARCH_CROSS_ENCODER`  (all scopes, neural reranking).  [Zep +2](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)

**LlamaIndex's PropertyGraphIndex**  uses pluggable sub-retrievers — separate vector and Cypher retrievers whose results are merged and reranked by Cohere or custom models.  [Neo4j](https://neo4j.com/labs/genai-ecosystem/llamaindex/)  **LangChain**  supports query routing between vector search and GraphCypherQAChain based on question type.  [GeeksforGeeks](https://www.geeksforgeeks.org/artificial-intelligence/knowledge-graphs-using-langchain/)  **MemGPT/Letta**  avoids the problem entirely by using flat text in vector stores with no entity-level summaries, delegating all retrieval decisions to the LLM agent itself.  [Letta](https://docs.letta.com/concepts/memgpt/)

The academic literature reinforces this pattern.  **PolyG**  (arXiv 2504.02112) defines a 4-class query taxonomy — entity queries, relation queries, reverse relation queries, and multi-hop queries — each routed to a different graph traversal strategy, achieving  **4× speedup**  and 75% win rate on generation quality.  **ARK**  (arXiv 2601.13969) autonomously adapts between global search and neighborhood exploration per query, achieving  **31.4% improvement**  over fixed-strategy retrieval.

----------

## Graphiti-specific recommendations for this system

The current architecture has three problems stacked on each other: a query-unaware neighborhood cache, hardcoded scoring bands, and a single merged ranking. Here's how to fix each using Graphiti's existing API.

**Problem 1: The cached neighborhood is query-blind.**  The top-10-by-edge-count Cypher query returns the same entities regardless of what's being asked. Replace it with Graphiti's  `_search()`  using  `NODE_HYBRID_SEARCH_NODE_DISTANCE`  [Zep](https://help.getzep.com/graphiti/working-with-data/searching)  with  `center_node_uuid`  set to Lyra's node UUID.  [GitHub](https://github.com/getzep/graphiti/tree/main/examples/quickstart)  This performs semantic search over entity names, then reranks by graph proximity to Lyra — returning entities relevant to both the query content and Lyra's graph neighborhood.  [getzep +2](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)  For cases where you need entity summaries in context, fetch them as a second step after identifying query-relevant entities, rather than pre-caching a static set.

**Problem 2: Hardcoded scoring bands force entities above edges.**  Eliminate the bands entirely. Instead, run separate searches and apply per-type score normalization before merging:

python

```python
# Run independent searches
edge_results = await graphiti._search(query, config=EDGE_HYBRID_SEARCH_RRF, group_ids=[group_id])
node_results = await graphiti._search(query, config=NODE_HYBRID_SEARCH_RRF, group_ids=[group_id])

# Z-score normalize within each type
def z_normalize(results):
    scores = [r.score for r in results]
    mean, std = np.mean(scores), np.std(scores) + 1e-8
    for r in results:
        r.normalized_score = (r.score - mean) / std
    return results

# Merge on normalized scores, not raw scores
```

**Problem 3: No query-type routing.**  Add a lightweight classifier (even rule-based) that routes queries to appropriate search recipes:

-   **Factual queries**  ("When did X happen?", "What does Lyra think about coffee?") →  `EDGE_HYBRID_SEARCH_RRF`  only, suppressing entity results entirely
-   **Navigational queries**  ("Who is Jeff?", "Tell me about the garden") →  `NODE_HYBRID_SEARCH_NODE_DISTANCE`  with Lyra as center node
-   **Contextual queries**  ("What's been happening lately?") →  `EDGE_HYBRID_SEARCH_EPISODE_MENTIONS`  with time-decay weighting
-   **Relational queries**  ("How does Lyra know Jeff?") → Combined search with BFS from both entities

**Additional tuning.**  The  `cross_encoder`  reranker (`EDGE_HYBRID_SEARCH_CROSS_ENCODER`) is the single most effective counter to length bias — it jointly encodes query and result, evaluating actual relevance rather than embedding distance.  [Zep](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)  Graphiti supports OpenAI, Gemini, and BGE reranker backends.  [Zep +2](https://help.getzep.com/graphiti/working-with-data/searching)  The  `episode_mentions`  reranker provides a built-in recency/frequency signal that naturally favors recent edge facts over static entity context.  [Zep](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)[getzep](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)  The  `mmr`  reranker with a lower  `mmr_lambda`  (e.g., 0.5) promotes diversity, preventing multiple similar entity descriptions from dominating results.  [Zep](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)[getzep](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)

For temporal weighting beyond what episode_mentions provides, apply exponential decay post-retrieval:

python

```python
def time_weighted_score(score, created_at, half_life_days=14, weight=0.3):
    age = (datetime.now(timezone.utc) - created_at).total_seconds() / 86400
    decay = 2 ** (-age / half_life_days)
    return score * ((1 - weight) + weight * decay)
```

----------

## Multi-entity isolation requires safeguards beyond group_id alone

Graphiti's  `group_id`  provides  **logical isolation**  at the Cypher query level — every node and edge carries a  `group_id`  property, and all built-in queries filter on it.  [GitHub](https://github.com/getzep/graphiti)[DeepWiki](https://deepwiki.com/getzep/graphiti/7.3-multi-database-and-multi-tenancy)  For two AI entities, this is architecturally adequate but has three risks that need mitigation.

**The vector search gap is the biggest risk.**  Neo4j's vector index (`db.index.vector.queryNodes`) performs post-filtering, not pre-filtering. A vector search for Entity A's query scans all embeddings including Entity B's, returns top-K globally, then filters by group_id.  [neo4j](https://community.neo4j.com/t/vector-search-index-pre-filtered-query/64465)  With two entities of similar size, roughly  **50% of vector results are wasted**  on the wrong entity, reducing effective recall. The mitigation is to double the K parameter for all vector searches. Neo4j 2026.01 introduces the  `SEARCH`  clause with  `WHERE`  pre-filtering inside vector queries, which would solve this at the index level — worth upgrading when Graphiti adds support.

**Custom Cypher queries bypass group_id if you forget to include it.**  Graphiti issue #801 revealed that passing  `None`  or an empty list for  `group_ids`  causes the filter to silently return no results rather than failing safely.  [GitHub](https://github.com/getzep/graphiti/issues/801)  Every custom Cypher query in the system must include  `WHERE n.group_id = $group_id`. The recommended pattern is a wrapper class that enforces group_id on every operation:

python

```python
class IsolatedGraphitiClient:
    def __init__(self, graphiti, entity_group_id):
        self._graphiti = graphiti
        self._group_id = entity_group_id
    
    async def search(self, query, **kwargs):
        return await self._graphiti._search(
            query, group_ids=[self._group_id], **kwargs
        )
```

**Fulltext indexes include all tenants.**  Graphiti's fulltext index spans all group_ids, with post-filtering applied after retrieval. This has the same effective-recall reduction as vector search. Ensure all fulltext queries include group_id in the WHERE clause, and consider adding a Neo4j range index on  `group_id`  for all node labels (`CREATE INDEX entity_group_id FOR (n:Entity) ON (n.group_id)`).

For the current two-entity scenario, shared Neo4j with group_id plus these safeguards is the right choice.  [getzep](https://help.getzep.com/graphiti/core-concepts/graph-namespacing)  If scaling beyond 5 entities or needing regulatory-grade isolation, migrate to Neo4j Enterprise's multi-database feature  [Neo4j](https://neo4j.com/docs/operations-manual/current/database-administration/)  — Graphiti supports this via  `driver.with_database(name)`.  [deepwiki](https://deepwiki.com/getzep/graphiti/7.3-multi-database-and-multi-tenancy)  As an alternative, Graphiti now supports FalkorDB as a backend,  [GitHub](https://github.com/getzep/graphiti)  which provides native per-graph isolation within a single Redis instance  [FalkorDB](https://www.falkordb.com/blog/mcp-knowledge-graph-graphiti-falkordb/)  without Enterprise licensing.  [GitHub](https://github.com/getzep/graphiti)[deepwiki](https://deepwiki.com/getzep/graphiti/7.3-multi-database-and-multi-tenancy)

----------

## Recommended implementation plan

Based on the research, here is a prioritized implementation sequence targeting the highest-impact changes first.

**Week 1 — Eliminate hardcoded scoring bands and switch to native Graphiti search.**  Replace the raw Cypher neighborhood query with  `graphiti._search()`  using  `NODE_HYBRID_SEARCH_NODE_DISTANCE`  for entity context and  `EDGE_HYBRID_SEARCH_RRF`  for facts. Return these as separate channels to the consumer layer rather than merging into a single scored list.  [Zep](https://help.getzep.com/graphiti/working-with-data/searching)  This single change eliminates the root cause of entity-over-edge dominance.

**Week 2 — Add query-type routing.**  Implement a lightweight classifier (LLM-based or rule-based pattern matching) that categorizes incoming queries as factual, navigational, contextual, or relational. Route each type to the appropriate Graphiti search recipe. Factual queries should use edge-only search; navigational queries should use node search with node_distance reranking.

**Week 3 — Add cross-encoder reranking and temporal weighting.**  Switch from RRF to cross-encoder reranking for the highest-quality relevance scoring, immune to length bias. Add time-decay weighting to edge results using a 14-day half-life.  [arXiv](https://arxiv.org/html/2509.19376)  Enable  `episode_mentions`  reranking for "what's been happening" queries.  [Zep](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)

**Week 4 — Implement multi-entity isolation.**  Create the  `IsolatedGraphitiClient`  wrapper. Add integration tests that verify zero cross-contamination between entities. Double the K parameter for vector searches. Add Neo4j range indexes on  `group_id`  for all node labels. Deploy the second entity.

The key architectural insight across all the research is simple:  **stop merging entities and edges into one ranking**. Entities answer "who/what is X?" while edges answer "what happened?"  [Zep](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)  They serve different retrieval purposes and should be fetched through different channels, scored independently, and presented to the consumer as separate context types — exactly as Graphiti's API was designed to support,  [Zep](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)  and exactly as GraphRAG's token-budget allocation enforces. The current system's hardcoded scoring bands are fighting the architecture rather than using it.

## Conclusion

The fix is less about tuning scores and more about restructuring retrieval flow. Three changes deliver most of the value: separating entity and edge retrieval into independent Graphiti search channels (using the already-built  `_search()`  API with scope-specific configs),  [Zep](https://help.getzep.com/graphiti/working-with-data/searching)  replacing static neighborhood caching with query-aware node search via  `NODE_HYBRID_SEARCH_NODE_DISTANCE`,  [Zep](https://help.getzep.com/graphiti/working-with-data/searching)  and adding a query-type router that selects the right search recipe per query. Cross-encoder reranking provides the strongest single defense against length bias in embedding similarity.  [getzep](https://blog.getzep.com/how-do-you-search-a-knowledge-graph/)  For multi-entity isolation,  `group_id`  with a mandatory wrapper and doubled vector-search K is sufficient for two entities, with a clear upgrade path to separate databases when needed.  [getzep](https://help.getzep.com/graphiti/core-concepts/graph-namespacing)[DeepWiki](https://deepwiki.com/getzep/graphiti/7.3-multi-database-and-multi-tenancy)  The most surprising finding is that  **Graphiti already solved the entity-vs-edge separation problem**  at the API level — the current system's custom Cypher layer is working around the solution rather than using it.