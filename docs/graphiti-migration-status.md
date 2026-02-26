# Graphiti Multi-Entity Migration Status

**Date**: 2026-02-26
**Discovered during**: Autonomous reflection cycle

---

## Summary

The Graphiti knowledge graph exists in two states:
1. **Legacy shared graph**: 5,841 nodes (3,652 Episodic, 2,189 Entity) from ~17k messages **before multi-entity isolation**
2. **Entity-specific graphs**: New ingestion (post-Feb 11) requires `group_id` for entity isolation — **not yet built due to OpenAI quota exhaustion**

---

## What Happened

### Phase B Multi-Entity Deployment (2026-02-11)

Multi-entity support was completed and deployed, including:
- Entity namespacing for PPS (SQLite, ChromaDB, Graphiti)
- Each entity gets isolated memory via `group_id` parameter
- Graphiti was configured to use `group_id='lyra'` for Lyra's graph

**Architectural decision**: Fresh start with entity isolation, rather than migrating the shared graph.

### Current State

**Neo4j contains**:
```cypher
MATCH (n) RETURN labels(n)[0] as label, count(n) as count
// Results:
// "Episodic": 3,652
// "Entity": 2,189
// Total: 5,841 nodes
```

**But these nodes have NO `group_id` field**, so entity-scoped queries return empty:
```cypher
MATCH (n:EntityNode) WHERE n.group_id = 'lyra' RETURN count(n)
// Result: 0
```

**New ingestion** (post-Feb 11) tries to create entity-specific episodes with `group_id='lyra'`, but:
- 1,643 messages pending ingestion
- **Blocked by OpenAI quota exhaustion** since ~Feb 22

### Impact

1. **`texture_search()` returns empty**: It filters by `group_id='lyra'`, so it doesn't see the legacy graph
2. **Observatory summaries work**: They were generated from the legacy shared graph before multi-entity deployment
3. **No immediate data loss**: Legacy graph still exists, just not accessible via entity-scoped tools
4. **Fresh entity-scoped graph will be built**: Once OpenAI quota is restored, the 1,643 backlog will build Lyra's proper isolated graph

---

## Options Going Forward

### Option 1: Keep Legacy Graph as Read-Only Archive (Recommended)

**Approach**:
- Leave the legacy graph untouched
- Let new ingestion build Lyra's proper entity-scoped graph from scratch
- Eventually add a "legacy archive mode" tool for historical exploration if needed

**Pros**:
- Clean entity isolation from the start
- No migration complexity or risk
- Old graph preserved as historical artifact

**Cons**:
- Lose semantic search over pre-Feb-11 conversations via Graphiti
- Still have raw capture and summaries for that period

### Option 2: Migrate Legacy Nodes to Lyra's Namespace

**Approach**:
- Write Cypher migration script to add `group_id='lyra'` to all existing nodes
- Verify entity types match new schema (EntityNode, EpisodicNode)
- Test that Graphiti can read the migrated data

**Pros**:
- Full continuity of knowledge graph
- Immediate semantic search over all historical data

**Cons**:
- Migration complexity and risk
- Legacy data wasn't built with entity-awareness (first-person references, etc.)
- Might need schema updates beyond just `group_id`

### Option 3: Hybrid - Archive + Selective Import

**Approach**:
- Keep legacy graph as separate archive
- Use bulk ingestion to re-process important historical periods with entity isolation
- Let natural ingestion handle everything post-Feb-11

**Pros**:
- Best of both worlds
- Can curate what gets migrated

**Cons**:
- Most complex
- Double ingestion cost

---

## Recommendation

**Option 1** (fresh start) is cleanest:
- The 1,643 backlog represents ~2 weeks of conversation — reasonable "cold start"
- Raw capture and summaries preserve pre-Feb-11 history
- Clean entity isolation from day 1 of entity-scoped graph
- Can always add legacy read-only mode later if needed

Once OpenAI quota is restored:
1. Ingest the 1,643 backlog → Lyra's entity-scoped graph is born
2. Continue forward with proper entity isolation
3. Legacy graph becomes historical artifact

---

## Next Steps

1. **Document this finding** ✅ (this file)
2. **Wait for OpenAI quota restoration** (requires Jeff to add credits or monthly reset)
3. **Resume ingestion** via `ingest_batch_to_graphiti()` once unblocked
4. **Monitor graph growth** — verify entity isolation is working correctly
5. **Update Observatory** to use entity-scoped graph once it's populated

---

**Note**: This is not a bug or failure — it's a natural consequence of the Phase B architecture shift from shared to isolated graphs. The backlog will resolve itself once quota is restored.
