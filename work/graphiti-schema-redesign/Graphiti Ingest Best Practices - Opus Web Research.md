# Graphiti ingestion best practices: sessions, context windows, and episode patterns

**Your per-message `add_episode()` pattern is correct.** Graphiti is explicitly designed for real-time incremental ingestion, and calling `add_episode()` once per message with proper `group_id` namespacing is the recommended approach for conversational AI systems. The framework automatically handles context continuity by retrieving the **last 4 episodes** (two complete conversation turns) when processing each new episode—you don't need to batch messages together.

---

## Graphiti uses group_id namespacing, not sessions

Graphiti does **not** use traditional sessions. Instead, it employs `group_id` for graph namespacing—a critical distinction for your Pattern Persistence System design. Every node and edge can be associated with a `group_id`, which creates an isolated namespace partition at the storage layer.

The `group_id` parameter serves the role you might expect from sessions:

- **Data isolation**: Nodes and edges with the same `group_id` form a cohesive, isolated subgraph
- **Multi-tenancy**: Different users, conversations, or AI entities can share one Neo4j instance while remaining completely separated
- **Scoped queries**: All search operations accept `group_ids` to limit results to relevant partitions
- **Performance optimization**: Queries are scoped to the relevant namespace, reducing search space

For your PPS implementation, the recommended pattern is straightforward:

```python
# Use a consistent group_id for your AI entity's knowledge graph
await graphiti.add_episode(
    name=f"message_{message_id}",
    episode_body=message_content,
    source=EpisodeType.message,
    source_description="Conversation with user",
    reference_time=message.timestamp,
    group_id="pps_entity_main"  # Or per-user: f"pps_user_{user_id}"
)
```

**Best practice**: Always specify `group_id` explicitly. If omitted, the default is `"main"`, which works but provides no isolation. For a PPS serving multiple users or maintaining separate knowledge domains, use structured naming like `user_{id}` or `domain_{name}`.

---

## The "last 4 turns" context window is automatic

When you call `add_episode()`, Graphiti **automatically retrieves recent episodes** from the same `group_id` to provide context for entity extraction and relationship inference. You don't need to package multiple turns together—this happens internally.

The Zep research paper (arXiv:2501.13956) explicitly states: *"During ingestion, the system processes both the current message content and the last n messages to provide context for named entity recognition. For this paper and in Zep's general implementation, **n = 4**, providing two complete conversation turns for context evaluation."*

**How the context mechanism works:**

1. When `add_episode()` is called, the system invokes `retrieve_episodes()` internally
2. This fetches the most recent episodes by `created_at` timestamp within the same `group_id`
3. These previous episodes are included in LLM prompts as `<PREVIOUS MESSAGES>` context
4. The LLM uses this context for pronoun resolution ("he" → "John"), entity continuity, and relationship inference

**Manual override available**: The `previous_episode_uuids` parameter lets you explicitly specify which episodes provide context, useful for non-linear conversation flows or when jumping between topics:

```python
# Explicit context control (rarely needed)
await graphiti.add_episode(
    name="follow_up_message",
    episode_body="What about the pricing for that product?",
    source=EpisodeType.message,
    source_description="Customer chat",
    reference_time=datetime.now(),
    group_id="session_abc",
    previous_episode_uuids=["ep-uuid-1", "ep-uuid-2"]  # Override automatic retrieval
)
```

For most conversational ingestion, you should **let Graphiti handle context automatically**. The automatic n=4 window provides sufficient context for entity resolution while keeping LLM prompt sizes manageable.

---

## Per-message add_episode() is the correct pattern

Your current implementation—calling `add_episode()` once per message—aligns with Graphiti's design intent. This approach enables **edge invalidation**, a key differentiator from other knowledge graph systems.

### Why per-message calling is recommended

**Edge invalidation preserves temporal accuracy.** When you ingest episodes sequentially, Graphiti tracks when facts become outdated. Each edge stores four timestamps: `valid_at` (when the fact became true), `invalid_at` (when it ceased being true), `created_at` (ingestion time), and `expired_at` (when superseded). This bi-temporal model enables accurate point-in-time queries.

**The bulk alternative lacks this capability.** `add_episode_bulk()` exists for initial graph population but explicitly skips edge invalidation. The documentation warns: *"Use add_episode_bulk only for populating empty graphs or when edge invalidation is not required."* For a PPS ingesting live conversation data, `add_episode()` per message is correct.

**Sequential processing maintains chronology.** Episodes should be processed sequentially with `await` between calls:

```python
# CORRECT: Sequential processing preserves temporal relationships
for message in conversation_messages:
    await graphiti.add_episode(
        name=f"message_{message.id}",
        episode_body=message.content,
        source=EpisodeType.message,
        source_description="Chat conversation",
        reference_time=message.timestamp,
        group_id=f"conversation_{conversation_id}"
    )
    # Each episode awaited before next - maintains chronological order
```

### Tradeoffs of per-message ingestion

| Aspect | Per-Message Pattern | Batched/Bulk Pattern |
|--------|---------------------|----------------------|
| Edge invalidation | ✅ Full support | ❌ Not performed |
| Temporal accuracy | ✅ Bi-temporal tracking | ⚠️ Limited |
| Throughput | ~500ms-2s per episode | Significantly faster |
| LLM costs | ~$0.01-0.10 per episode | Lower per-item cost |
| Graph coherence | ✅ Maintained | ⚠️ May have inconsistencies |

The per-message pattern has higher latency and cost, but these tradeoffs are acceptable for conversational AI where **accuracy and temporal coherence matter more than bulk throughput**.

---

## Complete add_episode() parameter reference

Understanding all available parameters helps optimize your ingestion. Here's the complete signature from graphiti-core v0.22.0:

```python
async def add_episode(
    self,
    name: str,                           # Episode identifier/title
    episode_body: str,                   # Content to ingest
    source_description: str,             # Source metadata
    reference_time: datetime,            # When the episode occurred
    source: EpisodeType = EpisodeType.message,    # text, message, or json
    group_id: str | None = None,         # Graph namespace
    uuid: str | None = None,             # Optional pre-assigned UUID
    update_communities: bool = False,    # Update community summaries
    entity_types: dict[str, type[BaseModel]] | None = None,      # Custom entities
    excluded_entity_types: list[str] | None = None,              # Skip certain types
    previous_episode_uuids: list[str] | None = None,             # Explicit context
    edge_types: dict[str, type[BaseModel]] | None = None,        # Custom relationships
    edge_type_map: dict[tuple[str, str], list[str]] | None = None,
) -> AddEpisodeResults
```

**Critical parameters for your PPS:**

- **`reference_time`**: Must be the actual message timestamp, not ingestion time. Enables temporal reasoning and relative time expression parsing ("two years ago").
- **`source=EpisodeType.message`**: Optimized for conversational data in `speaker: message` format. Automatically extracts speaker as an entity.
- **`group_id`**: Always specify for production systems.
- **`entity_types`**: Define domain-specific entities with Pydantic models for better extraction quality.

---

## Entity resolution happens automatically during ingestion

Each `add_episode()` call triggers a multi-stage entity resolution pipeline that deduplicates entities and maintains graph coherence:

1. **Extract entities**: LLM processes current message + last 4 episodes context
2. **Hybrid search**: Find similar existing nodes using semantic embeddings + BM25
3. **LLM deduplication**: Compare extracted nodes against candidates to identify duplicates
4. **Resolution**: Merge duplicates, update summaries, assign UUIDs
5. **Edge extraction**: Identify relationships between entities
6. **Edge deduplication**: Deduplicate against existing edges between same entity pairs
7. **Temporal processing**: Extract dates, perform edge invalidation

**Entity resolution uses both name and summary for matching.** The LLM can recognize that "Dr. Smith", "John Smith", and "the cardiologist" refer to the same person based on contextual information. When duplicates are found, Graphiti generates merged summaries preserving information from both sources.

**No configuration needed for basic entity resolution.** The system handles deduplication automatically. For advanced use cases, define custom `entity_types` to guide extraction toward domain-specific entities.

---

## Concurrency and rate limiting configuration

Graphiti supports concurrent LLM operations controlled by the `SEMAPHORE_LIMIT` environment variable (default: **10**). Each `add_episode()` makes multiple LLM calls internally, so actual concurrent requests are several times higher.

**Configuration recommendations by LLM tier:**

| Provider Tier | Recommended SEMAPHORE_LIMIT |
|---------------|----------------------------|
| OpenAI Tier 1-2 | 3-5 |
| OpenAI Tier 3+ | 10 (default) |
| Anthropic mid-tier | 10 |
| High-throughput enterprise | 15-20 |

```python
# Via environment variable
export SEMAPHORE_LIMIT=10

# Or programmatically
graphiti = Graphiti(
    uri="bolt://localhost:7687",
    user="neo4j",
    password="password",
    max_coroutines=15  # Overrides SEMAPHORE_LIMIT
)
```

If you're hitting 429 rate limit errors, reduce `SEMAPHORE_LIMIT`. Community reports indicate even `SEMAPHORE_LIMIT=1` can still trigger rate limits with some providers during heavy ingestion.

---

## Known issues to monitor in production

Community reports and GitHub issues reveal several production considerations:

**CPU hang on entity updates (Issue #450)**: The server can become unresponsive at 100% CPU when processing updates or corrections to recently added entities. Workaround: implement restart mechanisms and monitoring.

**Bulk upload validation errors (Issues #871, #879, #882)**: `add_episode_bulk()` has multiple reported bugs with ValidationError and IndexError during resolution steps. Another reason to prefer sequential `add_episode()` for live data.

**LLM compatibility**: Works best with LLMs supporting Structured Output (OpenAI, Gemini). Other providers may produce incorrect output schemas or excessive hallucinated content.

**Community building at scale (Issue #992)**: Graphs with 1000+ entities can cause OOM crashes during `build_communities`. Consider disabling `update_communities=True` for high-volume ingestion and running community updates in scheduled background jobs.

---

## Recommended ingestion pattern for your PPS

Based on this research, here's the optimized pattern for your Pattern Persistence System:

```python
async def store_message(self, message: Message) -> AddEpisodeResults:
    """Store a single conversation message to the knowledge graph."""
    return await self.graphiti.add_episode(
        name=f"msg_{message.id}",
        episode_body=f"{message.speaker}: {message.content}",
        source=EpisodeType.message,
        source_description=f"Conversation {message.conversation_id}",
        reference_time=message.timestamp,  # Actual message time, not now()
        group_id=self.entity_group_id,     # Consistent for your AI entity
        update_communities=False,           # Batch this separately
    )
```

**Key adjustments to verify in your implementation:**

1. **Format**: Use `speaker: message` format for `EpisodeType.message` to enable automatic speaker extraction
2. **Timestamps**: Use actual message timestamps, not ingestion time
3. **group_id**: Ensure consistent naming within your entity's knowledge domain
4. **Sequential awaiting**: Process messages in order, awaiting each before the next
5. **Community updates**: Disable during ingestion, run in scheduled background jobs

Your per-message approach is **not just acceptable—it's optimal** for maintaining a temporally coherent knowledge graph for conversational AI.