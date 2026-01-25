# Graphiti retrieval best practices for conversational AI context enrichment

Graphiti's hybrid retrieval system—combining semantic embeddings, BM25 keyword matching, and graph traversal—enables sophisticated turn-by-turn context enrichment without LLM calls at query time. For a Pattern Persistence System where Graphiti serves as a "texture layer" providing relational dynamics and nuanced details, the key insight is leveraging **multiple retrieval pathways simultaneously**: edges for specific facts, nodes for entity summaries, and communities for thematic clusters, all reranked based on graph proximity to focal entities. Production systems achieve **300ms P95 latency** and **94.8% accuracy** on deep memory benchmarks.

The retrieval architecture follows a three-stage pipeline: **search** (identifying candidates via hybrid methods), **rerank** (ordering by relevance using RRF, MMR, or cross-encoder), and **construct** (formatting for LLM consumption). This document provides comprehensive guidance for implementing sophisticated graph retrieval in your conversational AI context enrichment system.

---

## The complete retrieval API reference

### Core search methods

Graphiti exposes two primary search interfaces—a high-level opinionated method and a low-level configurable one:

```python
# High-level search - returns relevant facts (EntityEdge objects)
async def search(
    self,
    query: str,
    center_node_uuid: str | None = None,      # Entity for proximity reranking
    group_ids: list[str] | None = None,       # Namespace isolation
    num_results: int = 10,                     # Maximum results
    search_filter: SearchFilters | None = None # Temporal/type filters
) -> list[EntityEdge]

# Low-level configurable search - returns nodes, edges, AND communities
async def search_(
    self,
    query: str,
    config: SearchConfig,                      # Full search configuration
    group_ids: list[str] | None = None,
    center_node_uuid: str | None = None,
    bfs_origin_node_uuids: list[str] | None = None,  # BFS seed nodes
    search_filter: SearchFilters | None = None
) -> SearchResults
```

The `SearchResults` object contains three collections: `edges` (relationship facts), `nodes` (entity summaries), and `communities` (cluster summaries). **For texture-layer retrieval, you'll primarily use `search_()` to access all three simultaneously.**

### SearchConfig architecture

The configuration system provides granular control over search behavior:

```python
class SearchConfig:
    edge_config: EdgeSearchConfig | None   # Relationship/fact search
    node_config: NodeSearchConfig | None   # Entity search
    community_config: CommunitySearchConfig | None  # Cluster search
    limit: int                              # Max results per scope

class EdgeSearchConfig:
    search_methods: list[EdgeSearchMethod]  # [semantic, bm25, bfs]
    reranker: EdgeReranker                  # How to combine/rank results
    sim_min_score: float                    # Minimum similarity threshold
    mmr_lambda: float                       # Diversity parameter (0-1)
```

### Search methods and their purposes

| Method | Implementation | Best For |
|--------|---------------|----------|
| `cosine_similarity` | Vector KNN via Neo4j Lucene | Semantic/conceptual matching |
| `bm25` | TF-IDF full-text index | Exact keyword matching |
| `bfs` (breadth-first) | Graph traversal from seeds | Contextual proximity discovery |

### Reranking options

```python
class EdgeReranker(Enum):
    rrf = 'reciprocal_rank_fusion'      # Combines multiple search lists
    mmr = 'maximal_marginal_relevance'  # Balances relevance + diversity
    node_distance = 'node_distance'      # Proximity to center entity
    episode_mentions = 'episode_mentions' # Frequency-weighted importance
    cross_encoder = 'cross_encoder'      # Neural relevance scoring
```

**For relational dynamics in PPS, `node_distance` reranking is critical**—it ensures facts closer to the focal entity in the graph are prioritized, naturally surfacing relationship context.

### Pre-built search recipes

Graphiti provides **15 pre-configured search recipes** for common use cases:

| Recipe | Description | PPS Use Case |
|--------|-------------|--------------|
| `COMBINED_HYBRID_SEARCH_RRF` | All scopes with RRF | Broad context gathering |
| `EDGE_HYBRID_SEARCH_NODE_DISTANCE` | Facts ranked by entity proximity | Entity-specific enrichment |
| `EDGE_HYBRID_SEARCH_MMR` | Facts with diversity | Avoiding redundant context |
| `NODE_HYBRID_SEARCH_RRF` | Entity summaries | Character/entity understanding |
| `COMMUNITY_HYBRID_SEARCH_RRF` | Thematic clusters | Pattern recognition |

```python
from graphiti_core.search.search_config_recipes import (
    EDGE_HYBRID_SEARCH_NODE_DISTANCE,
    NODE_HYBRID_SEARCH_RRF,
    COMBINED_HYBRID_SEARCH_RRF
)

# Copy and modify recipes
config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
config.limit = 15
```

---

## Automatic context consideration and conversation windows

### The "last 4 turns" context window

Graphiti's context window applies **during ingestion, not retrieval**. When processing new episodes, the system uses the last **n=4 messages** (two complete conversation turns) for named entity recognition and relationship extraction:

> "During ingestion, the system processes both the current message content and the last n messages to provide context for named entity recognition. For this paper and in Zep's general implementation, n=4, providing two complete conversation turns for context evaluation."

**This does NOT automatically apply to retrieval.** You must manually provide conversation context to improve retrieval relevance.

### Manual context provision strategies

For turn-by-turn enrichment, include recent conversation context in your query construction:

```python
async def context_aware_retrieval(
    graphiti,
    current_query: str,
    recent_messages: list[str],  # Last 4-6 messages
    user_id: str
):
    # Option 1: Concatenate recent context with query
    context_query = f"{' '.join(recent_messages[-4:])} {current_query}"
    
    # Option 2: Extract entities from recent turns for center_node lookup
    recent_entities = extract_entities(recent_messages)
    center_node = await find_entity_node(graphiti, recent_entities[0])
    
    # Option 3: Use recent episodes as BFS seeds
    recent_episode_uuids = await get_recent_episode_uuids(
        graphiti, user_id, last_n=4
    )
    
    results = await graphiti.search_(
        query=current_query,
        config=EDGE_HYBRID_SEARCH_NODE_DISTANCE,
        group_ids=[f"user_{user_id}"],
        center_node_uuid=center_node.uuid if center_node else None,
        bfs_origin_node_uuids=recent_episode_uuids
    )
    
    return results
```

### Zep's production recommendation

> "Include the last 4 to 6 messages of the session when calling your LLM provider. The context string acts as the 'long-term memory,' and the last few messages serve as raw, short-term memory."

For PPS, implement this layered approach: **raw recent turns + retrieved texture context**.

---

## Query formulation strategies for different retrieval goals

### Relational queries: "What is the relationship between X and Y"

```python
async def query_relationship(graphiti, entity_a: str, entity_b: str, user_id: str):
    """
    For relational dynamics, use center_node approach:
    1. Find entity A
    2. Search for B-related facts FROM A's perspective
    3. Graph proximity naturally surfaces connecting facts
    """
    # Find entity A's node
    a_results = await graphiti.search(
        query=entity_a,
        group_ids=[f"user_{user_id}"],
        num_results=1
    )
    
    if not a_results:
        # Fallback to direct relationship query
        return await graphiti.search(
            query=f"{entity_a} {entity_b} relationship connection interaction",
            group_ids=[f"user_{user_id}"],
            num_results=10
        )
    
    # Search from A's graph position for B-related facts
    return await graphiti.search(
        query=f"{entity_b} interaction connection shared",
        center_node_uuid=a_results[0].source_node_uuid,
        group_ids=[f"user_{user_id}"],
        num_results=15
    )
```

### Episodic queries: "What happened during X"

```python
async def query_episode(graphiti, event_description: str, user_id: str):
    """
    Episodic queries benefit from temporal context in the query
    and potentially filtering by time ranges.
    """
    from graphiti_core.search.search_filters import SearchFilters, DateFilter
    
    # Include temporal markers in query
    results = await graphiti.search(
        query=f"{event_description} happened occurred during",
        group_ids=[f"user_{user_id}"],
        num_results=15,
        search_filter=SearchFilters(
            # Optional: filter to specific time range
            valid_at=[[DateFilter(
                comparison_operator=">=", 
                date="2025-01-01T00:00:00Z"
            )]]
        )
    )
    return results
```

### Thematic queries: "Everything about morning rituals"

```python
async def query_theme(graphiti, theme: str, user_id: str):
    """
    Thematic queries benefit from community search combined with edge search.
    Communities capture high-level patterns; edges provide specifics.
    """
    config = COMBINED_HYBRID_SEARCH_RRF.model_copy(deep=True)
    config.limit = 20
    
    results = await graphiti.search_(
        query=theme,
        config=config,
        group_ids=[f"user_{user_id}"]
    )
    
    # Communities give thematic overview
    thematic_context = results.communities
    # Edges give specific facts
    specific_facts = results.edges
    
    return {
        "themes": thematic_context,
        "facts": specific_facts,
        "entities": results.nodes
    }
```

### Entity-centric queries: "All facts about a specific person"

```python
async def query_entity_context(
    graphiti, 
    entity_name: str, 
    user_id: str,
    max_facts: int = 25
):
    """
    For comprehensive entity context (texture layer's sweet spot):
    1. Find the entity node
    2. Use node distance reranking to get all connected facts
    3. Also retrieve the entity's summary node
    """
    # Step 1: Find entity
    entity_search = await graphiti.search(
        query=entity_name,
        group_ids=[f"user_{user_id}"],
        num_results=3
    )
    
    if not entity_search:
        return {"facts": [], "entity_summary": None}
    
    entity_uuid = entity_search[0].source_node_uuid
    
    # Step 2: Get all connected facts using node distance
    config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
    config.limit = max_facts
    
    facts_results = await graphiti.search_(
        query=f"facts about {entity_name}",
        config=config,
        center_node_uuid=entity_uuid,
        group_ids=[f"user_{user_id}"]
    )
    
    # Step 3: Get entity summary node
    node_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
    node_config.limit = 1
    
    node_results = await graphiti.search_(
        query=entity_name,
        config=node_config,
        group_ids=[f"user_{user_id}"]
    )
    
    return {
        "facts": facts_results.edges,
        "entity_summary": node_results.nodes[0] if node_results.nodes else None
    }
```

### Query expansion using LLM reformulation

```python
async def llm_reformulated_query(
    llm_client,
    user_query: str,
    query_type: str  # relational, episodic, thematic, entity
) -> list[str]:
    """
    Use LLM to generate multiple optimized search queries
    """
    prompt = f"""Given this user query: "{user_query}"
    
Query type: {query_type}

Generate 3 optimized search queries that would retrieve relevant facts from a knowledge graph. Consider:
- Key entities that should be included
- Relationship types that might connect entities
- Temporal markers if relevant
- Synonym expansion for key terms

Return as JSON array of strings."""

    response = await llm_client.generate(prompt)
    return json.loads(response)  # ["query1", "query2", "query3"]
```

---

## Graph traversal patterns for context expansion

### Multi-hop retrieval: Entity → relationships → connected entities

```python
async def multi_hop_context(
    graphiti,
    seed_entity_name: str,
    user_id: str,
    hops: int = 2
):
    """
    Expand context outward from a seed entity through graph structure.
    Essential for understanding relational dynamics.
    """
    collected_context = {
        "seed_entity": None,
        "direct_facts": [],        # 1-hop: facts about seed
        "connected_entities": [],   # Entities connected to seed
        "extended_facts": []        # 2-hop: facts about connected entities
    }
    
    # Find seed entity
    seed_results = await graphiti.search(
        query=seed_entity_name,
        group_ids=[f"user_{user_id}"],
        num_results=1
    )
    
    if not seed_results:
        return collected_context
    
    seed_uuid = seed_results[0].source_node_uuid
    collected_context["seed_entity"] = seed_entity_name
    
    # Hop 1: Get direct facts
    direct_facts = await graphiti.search(
        query=f"all facts {seed_entity_name}",
        center_node_uuid=seed_uuid,
        group_ids=[f"user_{user_id}"],
        num_results=15
    )
    collected_context["direct_facts"] = direct_facts
    
    # Extract connected entity UUIDs from direct facts
    connected_uuids = set()
    for fact in direct_facts:
        if fact.source_node_uuid != seed_uuid:
            connected_uuids.add(fact.source_node_uuid)
        if fact.target_node_uuid != seed_uuid:
            connected_uuids.add(fact.target_node_uuid)
    
    if hops >= 2 and connected_uuids:
        # Hop 2: Get facts about connected entities
        for uuid in list(connected_uuids)[:5]:  # Limit to avoid explosion
            extended = await graphiti.search(
                query="facts information",
                center_node_uuid=uuid,
                group_ids=[f"user_{user_id}"],
                num_results=5
            )
            collected_context["extended_facts"].extend(extended)
    
    return collected_context
```

### BFS-based "land and expand" pattern

Graphiti supports two BFS modes that are crucial for context expansion:

```python
async def land_and_expand_retrieval(
    graphiti,
    query: str,
    user_id: str,
    expansion_depth: int = 10
):
    """
    Land-and-expand: semantic/BM25 finds initial results,
    then BFS expands from those to find contextually related facts.
    """
    # Method 1: Automatic land-and-expand (when BFS is in search_methods)
    config = SearchConfig(
        edge_config=EdgeSearchConfig(
            search_methods=[
                EdgeSearchMethod.cosine_similarity,
                EdgeSearchMethod.bm25,
                EdgeSearchMethod.bfs  # This triggers land-and-expand
            ],
            reranker=EdgeReranker.rrf
        ),
        limit=expansion_depth
    )
    
    results = await graphiti.search_(
        query=query,
        config=config,
        group_ids=[f"user_{user_id}"]
    )
    
    return results

async def explicit_bfs_expansion(
    graphiti,
    seed_node_uuids: list[str],  # Known starting points
    query: str,
    user_id: str
):
    """
    Method 2: Explicit BFS from known seed nodes
    Use when you already have focal entities identified.
    """
    config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
    
    results = await graphiti.search_(
        query=query,
        config=config,
        group_ids=[f"user_{user_id}"],
        bfs_origin_node_uuids=seed_node_uuids  # Explicit seeds
    )
    
    return results
```

### Temporal traversal: Facts from specific time periods

```python
async def temporal_context_retrieval(
    graphiti,
    query: str,
    user_id: str,
    start_date: str,  # ISO format
    end_date: str | None = None,
    include_invalidated: bool = False
):
    """
    Retrieve facts valid during a specific time period.
    Critical for episodic understanding in PPS.
    """
    from graphiti_core.search.search_filters import SearchFilters, DateFilter
    
    filters = SearchFilters(
        valid_at=[[
            DateFilter(comparison_operator=">=", date=start_date)
        ]]
    )
    
    if end_date:
        filters.valid_at[0].append(
            DateFilter(comparison_operator="<=", date=end_date)
        )
    
    if not include_invalidated:
        # Only get currently valid facts
        filters.invalid_at = [[
            DateFilter(comparison_operator="IS NULL")
        ]]
    
    results = await graphiti.search(
        query=query,
        group_ids=[f"user_{user_id}"],
        num_results=20,
        search_filter=filters
    )
    
    return results
```

### Community-aware retrieval: Retrieving thematic clusters

```python
async def community_context_retrieval(
    graphiti,
    theme: str,
    user_id: str
):
    """
    Communities capture higher-level patterns and entity clusters.
    Useful for understanding recurring themes and relationships.
    """
    from graphiti_core.search.search_config_recipes import (
        COMMUNITY_HYBRID_SEARCH_RRF
    )
    
    config = COMMUNITY_HYBRID_SEARCH_RRF.model_copy(deep=True)
    config.limit = 5
    
    results = await graphiti.search_(
        query=theme,
        config=config,
        group_ids=[f"user_{user_id}"]
    )
    
    # Communities have name (brief) and summary (detailed)
    for community in results.communities:
        print(f"Cluster: {community.name}")
        print(f"Summary: {community.summary}")  # LLM-generated overview
    
    return results.communities
```

---

## Result ranking and selection strategies

### Understanding Graphiti's ranking mechanisms

**Reciprocal Rank Fusion (RRF)** combines multiple result lists:
```python
# For each result across all lists:
# score = sum(1 / (k + rank)) where k=60 (damping constant)
```

**Maximal Marginal Relevance (MMR)** balances relevance and diversity:
```python
# score = λ * sim(query, doc) - (1-λ) * max_sim(doc, selected_docs)
# Higher mmr_lambda = more relevance, lower = more diversity
```

**Cross-Encoder Reranking** uses the "one-token trick":
```python
# Prompt: "Is this passage relevant to the query?" 
# Uses log probabilities of "yes"/"no" tokens for scoring
# Supported: OpenAI, Gemini, BGE-m3 (local)
```

### "Most meaning per token" selection strategy

```python
async def optimal_context_selection(
    results: list,
    max_tokens: int = 2000,
    diversity_weight: float = 0.3
):
    """
    Select results maximizing information density while avoiding redundancy.
    """
    selected = []
    selected_embeddings = []
    token_count = 0
    
    for result in results:
        fact_tokens = len(result.fact.split()) * 1.3  # Rough token estimate
        
        if token_count + fact_tokens > max_tokens:
            continue
        
        # Check diversity against already-selected
        if selected_embeddings and hasattr(result, 'fact_embedding'):
            max_similarity = max(
                cosine_sim(result.fact_embedding, emb) 
                for emb in selected_embeddings
            )
            if max_similarity > (1 - diversity_weight):
                continue  # Too similar to existing selection
        
        selected.append(result)
        if hasattr(result, 'fact_embedding'):
            selected_embeddings.append(result.fact_embedding)
        token_count += fact_tokens
    
    return selected
```

### Deduplication strategies

Graphiti handles deduplication through:
1. **UUID-based**: Same fact only appears once across search methods
2. **MMR reranking**: Explicitly penalizes results similar to selected ones
3. **RRF merging**: Naturally handles duplicates across search lists

For additional application-level deduplication:

```python
def deduplicate_results(results: list) -> list:
    """Remove duplicate facts based on semantic similarity"""
    seen_uuids = set()
    seen_facts = set()
    unique = []
    
    for r in results:
        # UUID dedup
        if r.uuid in seen_uuids:
            continue
        
        # Semantic dedup via fact text normalization
        normalized = normalize_fact(r.fact)
        if normalized in seen_facts:
            continue
        
        seen_uuids.add(r.uuid)
        seen_facts.add(normalized)
        unique.append(r)
    
    return unique
```

---

## Hybrid retrieval approaches

### Combining node and edge search for rich context

```python
async def rich_context_retrieval(
    graphiti,
    query: str,
    user_id: str,
    focal_entity: str | None = None
):
    """
    Comprehensive retrieval combining:
    - Edges: Specific facts and relationships
    - Nodes: Entity summaries for background
    - Communities: Thematic patterns
    """
    results = {"facts": [], "entities": [], "themes": [], "focal": None}
    
    # Find focal entity if specified
    center_uuid = None
    if focal_entity:
        focal_results = await graphiti.search(
            query=focal_entity,
            group_ids=[f"user_{user_id}"],
            num_results=1
        )
        if focal_results:
            center_uuid = focal_results[0].source_node_uuid
    
    # Edge search: specific facts (with node distance if focal)
    edge_config = (
        EDGE_HYBRID_SEARCH_NODE_DISTANCE if center_uuid 
        else EDGE_HYBRID_SEARCH_RRF
    ).model_copy(deep=True)
    edge_config.limit = 15
    
    edge_results = await graphiti.search_(
        query=query,
        config=edge_config,
        center_node_uuid=center_uuid,
        group_ids=[f"user_{user_id}"]
    )
    results["facts"] = edge_results.edges
    
    # Node search: entity context
    node_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
    node_config.limit = 5
    
    node_results = await graphiti.search_(
        query=query,
        config=node_config,
        group_ids=[f"user_{user_id}"]
    )
    results["entities"] = node_results.nodes
    
    # Community search: thematic patterns
    community_config = COMMUNITY_HYBRID_SEARCH_RRF.model_copy(deep=True)
    community_config.limit = 3
    
    community_results = await graphiti.search_(
        query=query,
        config=community_config,
        group_ids=[f"user_{user_id}"]
    )
    results["themes"] = community_results.communities
    
    return results
```

### When to use semantic vs graph traversal vs both

| Query Type | Semantic | BM25 | BFS | Reasoning |
|------------|----------|------|-----|-----------|
| Conceptual ("feelings about work") | ✓✓ | ✓ | | Semantic similarity captures meaning |
| Exact entities ("John Smith") | ✓ | ✓✓ | | BM25 excels at exact matches |
| Relational ("John's projects") | ✓ | ✓ | ✓✓ | BFS expands from entity |
| Thematic patterns | ✓✓ | ✓ | ✓ | All methods complement |
| Time-specific events | ✓ | ✓✓ | | Keywords + temporal filters |

### Secondary search seeding pattern

```python
async def seeded_secondary_search(
    graphiti,
    initial_query: str,
    user_id: str
):
    """
    Use initial search results to seed more targeted secondary searches.
    Essential for discovering unexpected connections.
    """
    # Primary search
    primary = await graphiti.search(
        query=initial_query,
        group_ids=[f"user_{user_id}"],
        num_results=10
    )
    
    if not primary:
        return []
    
    # Extract entity UUIDs from primary results
    entity_uuids = set()
    for fact in primary:
        entity_uuids.add(fact.source_node_uuid)
        entity_uuids.add(fact.target_node_uuid)
    
    # Secondary searches from each key entity
    secondary_results = []
    for uuid in list(entity_uuids)[:3]:  # Top 3 entities
        secondary = await graphiti.search(
            query=initial_query,
            center_node_uuid=uuid,
            group_ids=[f"user_{user_id}"],
            num_results=5
        )
        secondary_results.extend(secondary)
    
    # Deduplicate and merge
    all_results = primary + secondary_results
    return deduplicate_results(all_results)
```

---

## MCP server capabilities and gaps

### Available MCP endpoints

The Graphiti MCP server exposes these retrieval tools:

| Tool | Purpose | Returns |
|------|---------|---------|
| `search_memory_nodes` / `search_nodes` | Search entity summaries | EntityNode list |
| `search_memory_facts` / `search_facts` | Search relationship facts | EntityEdge list |
| `get_episodes` | Retrieve recent episodes | EpisodicNode list |
| `delete_entity_edge` | Remove specific edge | Confirmation |
| `delete_episode` | Remove episode | Confirmation |

### Gaps between MCP and Python API

| Capability | Python API | MCP Server |
|------------|------------|------------|
| `search_()` with full SearchConfig | ✓ | Limited |
| Custom rerankers (node_distance, episode_mentions) | ✓ | RRF only |
| BFS origin node specification | ✓ | Not exposed |
| Community search | ✓ | Not exposed |
| SearchFilters (temporal, type) | ✓ | Limited |
| Center node UUID | ✓ | Partial |

### Custom MCP tool recommendations for PPS

```python
# Recommended custom tools to add to MCP server for PPS:

@mcp_tool("search_entity_context")
async def search_entity_context(
    entity_name: str,
    user_id: str,
    include_communities: bool = True
):
    """Combined entity + facts + community search"""
    pass

@mcp_tool("search_relational")
async def search_relational(
    entity_a: str,
    entity_b: str,
    user_id: str
):
    """Find relationship between two entities"""
    pass

@mcp_tool("search_temporal")
async def search_temporal(
    query: str,
    user_id: str,
    start_date: str,
    end_date: str | None = None
):
    """Time-bounded fact retrieval"""
    pass

@mcp_tool("expand_from_entity")
async def expand_from_entity(
    entity_uuid: str,
    user_id: str,
    hops: int = 2
):
    """Multi-hop context expansion"""
    pass
```

---

## Turn-by-turn context injection patterns

### What to inject per turn

For a texture-layer PPS, structure injection around **focal entities** in the current turn:

```python
async def generate_turn_context(
    graphiti,
    current_message: str,
    recent_messages: list[str],
    user_id: str,
    max_context_tokens: int = 1500
):
    """
    Generate context for a single conversation turn.
    Balances depth (rich facts about focal entities) with breadth (coverage).
    """
    # Extract focal entities from current + recent messages
    focal_entities = extract_entities(current_message)
    context_entities = extract_entities(' '.join(recent_messages[-4:]))
    
    context = {
        "focal_entity_facts": [],
        "relational_context": [],
        "thematic_context": [],
        "entity_summaries": []
    }
    
    tokens_used = 0
    tokens_per_section = max_context_tokens // 4
    
    # 1. Deep context for primary focal entity (40% of tokens)
    if focal_entities:
        focal = await query_entity_context(
            graphiti, focal_entities[0], user_id, max_facts=10
        )
        context["focal_entity_facts"] = focal["facts"]
        if focal["entity_summary"]:
            context["entity_summaries"].append(focal["entity_summary"])
    
    # 2. Relational context between focal and context entities (30%)
    for ctx_entity in context_entities[:2]:
        if ctx_entity not in focal_entities:
            relational = await query_relationship(
                graphiti, focal_entities[0] if focal_entities else ctx_entity,
                ctx_entity, user_id
            )
            context["relational_context"].extend(relational[:5])
    
    # 3. Direct query match (20%)
    direct = await graphiti.search(
        query=current_message,
        group_ids=[f"user_{user_id}"],
        num_results=5
    )
    context["thematic_context"] = direct
    
    # 4. Entity summaries for mentioned entities (10%)
    for entity in (focal_entities + context_entities)[:3]:
        node_results = await graphiti.search_(
            query=entity,
            config=NODE_HYBRID_SEARCH_RRF,
            group_ids=[f"user_{user_id}"]
        )
        if node_results.nodes:
            context["entity_summaries"].append(node_results.nodes[0])
    
    return context
```

### Formatting for LLM consumption

Zep's production format provides a proven template:

```python
def format_context_for_llm(context: dict) -> str:
    """
    Format retrieved context as structured prompt section.
    Based on Zep's production context template.
    """
    sections = []
    
    # Facts section
    if context.get("focal_entity_facts") or context.get("relational_context"):
        facts = context.get("focal_entity_facts", []) + context.get("relational_context", [])
        fact_lines = []
        for fact in facts:
            line = f"• {fact.fact}"
            if hasattr(fact, 'valid_at') and fact.valid_at:
                line += f" (as of {fact.valid_at.strftime('%b %Y')})"
            if hasattr(fact, 'invalid_at') and fact.invalid_at:
                line += f" [no longer true as of {fact.invalid_at.strftime('%b %Y')}]"
            fact_lines.append(line)
        
        sections.append(f"""<FACTS>
{chr(10).join(fact_lines)}
</FACTS>""")
    
    # Entity summaries section
    if context.get("entity_summaries"):
        entity_lines = [
            f"• {node.name}: {node.summary}" 
            for node in context["entity_summaries"]
        ]
        sections.append(f"""<ENTITIES>
{chr(10).join(entity_lines)}
</ENTITIES>""")
    
    # Thematic context section
    if context.get("thematic_context"):
        theme_lines = [f"• {fact.fact}" for fact in context["thematic_context"]]
        sections.append(f"""<RELATED_CONTEXT>
{chr(10).join(theme_lines)}
</RELATED_CONTEXT>""")
    
    header = """The following represents relevant context from the knowledge graph.
Facts show specific information with temporal validity.
Entities provide summaries of key people, places, and concepts."""
    
    return header + "\n\n" + "\n\n".join(sections)
```

### Balancing breadth vs depth dynamically

```python
class AdaptiveContextRetriever:
    """
    Adjust retrieval strategy based on query characteristics
    and conversation phase.
    """
    
    def __init__(self, graphiti, user_id: str):
        self.graphiti = graphiti
        self.user_id = user_id
    
    async def retrieve(
        self,
        query: str,
        query_type: str,  # greeting, question, task, followup
        recent_entities: list[str],
        max_tokens: int = 1500
    ):
        if query_type == "greeting":
            # Broad, shallow: recent interactions and preferences
            return await self._broad_retrieval(query, depth=3, breadth=10)
        
        elif query_type == "question":
            # Balanced: moderate depth on relevant topics
            return await self._balanced_retrieval(
                query, recent_entities, depth=8, breadth=8
            )
        
        elif query_type == "task":
            # Deep, narrow: comprehensive context on task subject
            focal = extract_task_subject(query)
            return await self._deep_retrieval(focal, depth=15, breadth=3)
        
        elif query_type == "followup":
            # Use recent entities as seeds, expand from there
            return await self._followup_retrieval(recent_entities, depth=10)
    
    async def _deep_retrieval(self, focal_entity: str, depth: int, breadth: int):
        """Prioritize depth: many facts about few entities"""
        return await query_entity_context(
            self.graphiti, focal_entity, self.user_id, max_facts=depth
        )
    
    async def _broad_retrieval(self, query: str, depth: int, breadth: int):
        """Prioritize breadth: few facts about many topics"""
        results = await self.graphiti.search(
            query=query,
            group_ids=[f"user_{self.user_id}"],
            num_results=breadth
        )
        return {"facts": results[:depth], "entities": [], "themes": []}
    
    async def _balanced_retrieval(
        self, query: str, entities: list[str], depth: int, breadth: int
    ):
        """Balance depth and breadth"""
        results = await rich_context_retrieval(
            self.graphiti, query, self.user_id, 
            focal_entity=entities[0] if entities else None
        )
        return results
```

---

## Production implementation: Complete turn-by-turn enrichment

### Full implementation pattern for PPS

```python
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class PPSContext:
    """Pattern Persistence System context for a single turn"""
    focal_facts: list          # Deep context about primary entity
    relational_facts: list     # Relationships between entities
    entity_summaries: list     # Background on mentioned entities
    thematic_patterns: list    # Community/cluster context
    temporal_validity: dict    # Time ranges for facts
    token_count: int
    retrieval_latency_ms: float

class PatternPersistenceRetriever:
    """
    Texture-layer retrieval for Pattern Persistence System.
    Provides rich relational dynamics and nuanced details.
    """
    
    def __init__(
        self,
        graphiti,
        user_id: str,
        max_context_tokens: int = 1500,
        enable_communities: bool = True
    ):
        self.graphiti = graphiti
        self.user_id = user_id
        self.group_ids = [f"user_{user_id}"]
        self.max_tokens = max_context_tokens
        self.enable_communities = enable_communities
        
        # Track recent focal entities for continuity
        self.recent_focal_entities: list[str] = []
    
    async def enrich_turn(
        self,
        current_message: str,
        recent_messages: list[str],
        conversation_phase: str = "default"
    ) -> PPSContext:
        """
        Main entry point: enrich a conversation turn with graph context.
        """
        import time
        start = time.time()
        
        # 1. Identify focal entities
        current_entities = self._extract_entities(current_message)
        context_entities = self._extract_entities(' '.join(recent_messages[-4:]))
        
        primary_focal = current_entities[0] if current_entities else None
        if primary_focal:
            self.recent_focal_entities = [primary_focal] + self.recent_focal_entities[:4]
        
        # 2. Find focal entity's graph node
        center_uuid = None
        if primary_focal:
            center_uuid = await self._find_entity_uuid(primary_focal)
        
        # 3. Retrieve layered context
        focal_facts = []
        relational_facts = []
        entity_summaries = []
        thematic_patterns = []
        
        # Layer 1: Deep focal entity context (40% tokens)
        if center_uuid:
            focal_facts = await self._get_focal_context(
                primary_focal, center_uuid, 
                token_budget=int(self.max_tokens * 0.4)
            )
        
        # Layer 2: Relational context (25% tokens)
        relational_facts = await self._get_relational_context(
            primary_focal, context_entities, center_uuid,
            token_budget=int(self.max_tokens * 0.25)
        )
        
        # Layer 3: Entity summaries (20% tokens)
        all_entities = list(set(current_entities + context_entities))
        entity_summaries = await self._get_entity_summaries(
            all_entities[:5],
            token_budget=int(self.max_tokens * 0.2)
        )
        
        # Layer 4: Thematic/community patterns (15% tokens)
        if self.enable_communities:
            thematic_patterns = await self._get_thematic_context(
                current_message,
                token_budget=int(self.max_tokens * 0.15)
            )
        
        latency = (time.time() - start) * 1000
        
        return PPSContext(
            focal_facts=focal_facts,
            relational_facts=relational_facts,
            entity_summaries=entity_summaries,
            thematic_patterns=thematic_patterns,
            temporal_validity=self._extract_temporal_info(focal_facts + relational_facts),
            token_count=self._estimate_tokens(
                focal_facts, relational_facts, entity_summaries, thematic_patterns
            ),
            retrieval_latency_ms=latency
        )
    
    async def _find_entity_uuid(self, entity_name: str) -> Optional[str]:
        results = await self.graphiti.search(
            query=entity_name,
            group_ids=self.group_ids,
            num_results=1
        )
        return results[0].source_node_uuid if results else None
    
    async def _get_focal_context(
        self, entity_name: str, entity_uuid: str, token_budget: int
    ) -> list:
        """Deep retrieval for primary focal entity"""
        config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
        config.limit = 15
        
        results = await self.graphiti.search_(
            query=f"facts about {entity_name}",
            config=config,
            center_node_uuid=entity_uuid,
            group_ids=self.group_ids
        )
        
        return self._select_within_budget(results.edges, token_budget)
    
    async def _get_relational_context(
        self,
        focal_entity: Optional[str],
        context_entities: list[str],
        center_uuid: Optional[str],
        token_budget: int
    ) -> list:
        """Retrieve relationship facts between entities"""
        if not focal_entity or not context_entities:
            return []
        
        relational = []
        budget_per_entity = token_budget // max(len(context_entities[:3]), 1)
        
        for ctx_entity in context_entities[:3]:
            if ctx_entity == focal_entity:
                continue
            
            results = await self.graphiti.search(
                query=f"{focal_entity} {ctx_entity} relationship interaction",
                center_node_uuid=center_uuid,
                group_ids=self.group_ids,
                num_results=5
            )
            relational.extend(self._select_within_budget(results, budget_per_entity))
        
        return relational
    
    async def _get_entity_summaries(
        self, entities: list[str], token_budget: int
    ) -> list:
        """Retrieve entity summary nodes"""
        summaries = []
        config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
        config.limit = 1
        
        for entity in entities:
            results = await self.graphiti.search_(
                query=entity,
                config=config,
                group_ids=self.group_ids
            )
            if results.nodes:
                summaries.append(results.nodes[0])
        
        return summaries
    
    async def _get_thematic_context(
        self, query: str, token_budget: int
    ) -> list:
        """Retrieve community/thematic patterns"""
        config = COMMUNITY_HYBRID_SEARCH_RRF.model_copy(deep=True)
        config.limit = 3
        
        results = await self.graphiti.search_(
            query=query,
            config=config,
            group_ids=self.group_ids
        )
        
        return results.communities
    
    def _extract_entities(self, text: str) -> list[str]:
        """Extract named entities from text (implement with your NER)"""
        # Placeholder - use spaCy, OpenAI, etc.
        import re
        # Simple capitalized word extraction as fallback
        words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
        return list(set(words))
    
    def _select_within_budget(self, results: list, token_budget: int) -> list:
        """Select results fitting within token budget"""
        selected = []
        tokens = 0
        for r in results:
            fact_tokens = len(r.fact.split()) * 1.3 if hasattr(r, 'fact') else 50
            if tokens + fact_tokens > token_budget:
                break
            selected.append(r)
            tokens += fact_tokens
        return selected
    
    def _estimate_tokens(self, *fact_lists) -> int:
        total = 0
        for facts in fact_lists:
            for f in facts:
                if hasattr(f, 'fact'):
                    total += len(f.fact.split()) * 1.3
                elif hasattr(f, 'summary'):
                    total += len(f.summary.split()) * 1.3
        return int(total)
    
    def _extract_temporal_info(self, facts: list) -> dict:
        """Extract temporal validity information"""
        temporal = {"facts_with_dates": 0, "invalidated_facts": 0}
        for f in facts:
            if hasattr(f, 'valid_at') and f.valid_at:
                temporal["facts_with_dates"] += 1
            if hasattr(f, 'invalid_at') and f.invalid_at:
                temporal["invalidated_facts"] += 1
        return temporal
    
    def format_for_prompt(self, context: PPSContext) -> str:
        """Format context for LLM system prompt injection"""
        return format_context_for_llm({
            "focal_entity_facts": context.focal_facts,
            "relational_context": context.relational_facts,
            "entity_summaries": context.entity_summaries,
            "thematic_context": context.thematic_patterns
        })


# Usage example
async def main():
    graphiti = Graphiti("bolt://localhost:7687", "neo4j", "password")
    
    retriever = PatternPersistenceRetriever(
        graphiti=graphiti,
        user_id="user_123",
        max_context_tokens=1500,
        enable_communities=True
    )
    
    # Each conversation turn
    context = await retriever.enrich_turn(
        current_message="How is Alice doing with the Phoenix project?",
        recent_messages=[
            "I spoke with Alice yesterday",
            "She mentioned some challenges",
            "The Phoenix project has a tight deadline"
        ],
        conversation_phase="question"
    )
    
    # Inject into LLM prompt
    prompt_context = retriever.format_for_prompt(context)
    
    print(f"Retrieved {len(context.focal_facts)} focal facts")
    print(f"Retrieved {len(context.relational_facts)} relational facts")
    print(f"Context tokens: {context.token_count}")
    print(f"Latency: {context.retrieval_latency_ms:.0f}ms")
```

---

## Summary and key recommendations

For implementing Graphiti as a texture layer in your Pattern Persistence System:

1. **Use `search_()` not `search()`** for full control over node, edge, and community retrieval
2. **Always set `center_node_uuid`** when retrieving entity-specific context—this enables graph-proximity reranking
3. **Implement multi-layer retrieval**: focal entity facts (deep), relational facts (connections), entity summaries (background), thematic patterns (communities)
4. **Manually include recent turns** in queries—the "last 4 turns" context only applies during ingestion
5. **Use node distance reranking** for relational dynamics—it naturally surfaces facts closer to focal entities in the graph
6. **Balance breadth vs depth** based on conversation phase and query type
7. **Format with temporal validity**—include `valid_at`/`invalid_at` markers for facts
8. **Target ~300ms retrieval latency** as the production benchmark (Zep's P95)
9. **Consider custom MCP tools** if using the MCP server, as it lacks some advanced retrieval capabilities
10. **Enable community search** for pattern recognition—communities capture higher-level thematic clusters

The hybrid retrieval approach (semantic + BM25 + BFS) combined with appropriate reranking provides the foundation for rich, contextually-aware turn-by-turn enrichment that goes far beyond simple fact retrieval.