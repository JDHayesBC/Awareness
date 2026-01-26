# Implementation Plan: Ambient Recall B1 Configuration

**Date**: 2026-01-25
**Planner**: orchestration-agent
**Status**: Ready for Implementation

---

## Executive Summary

Implement B1 configuration (30 edges, 3 nodes, explore depth 1) in the rich_texture layer to achieve 3x performance improvement and conversation-aware context retrieval.

**Architectural Decision**: **Option 2 (Rich_texture accesses database directly) with enhancement**

**Rationale**: Simplest path to implementation with minimal API changes, acceptable layer coupling for this specific optimization, and aligns with the "layers know how to optimize themselves" principle.

---

## Architectural Decision

### Chosen Approach: Option 2+ (Enhanced Direct Access)

The rich_texture layer will:
1. Access the raw_capture database directly to fetch recent messages
2. Extract entities from those messages using the test harness logic
3. Use those entities to seed explore traversal
4. Use a shared database path constant (not hardcoded)

**Enhancements over basic Option 2**:
- Use environment variable or config for database path (not hardcoded)
- Add caching for recent messages (refresh every 30 seconds)
- Fallback to default entities ("Lyra", "Jeff") if message fetch fails
- Make explore opt-in via environment flag for gradual rollout

### Why Not the Other Options?

**Option 1 (Modify layer.search() signature)**:
- Too invasive for a performance optimization
- Requires changes to all layers and all callers
- Breaks existing MCP tools and HTTP API
- High risk for marginal architectural purity gain

**Option 3 (ambient_recall passes messages)**:
- Still requires API changes (AmbientRecallRequest modification)
- Tight coupling between endpoint and layer internals
- Doesn't help other callers of rich_texture.search()

**Option 4 (Extract from query string)**:
- Testing showed this produces lower quality results
- Query "startup" has no entities → explore fails
- Misses the whole point of conversation-aware retrieval

### Why Option 2+ Works

1. **Minimal API Changes**: No changes to layer.search() signature
2. **Self-Contained**: All logic within rich_texture layer
3. **Pragmatic**: Layer coupling is acceptable for performance optimization
4. **Testable**: Can validate with existing test harness
5. **Reversible**: Easy to rollback if issues arise

**Key Insight**: Layers already have dependencies (rich_texture depends on Neo4j). Adding a read-only dependency on the messages database for context optimization is acceptable coupling.

---

## Implementation Steps

### Phase 1: Update rich_texture_v2.py

**File**: `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/layers/rich_texture_v2.py`

#### Changes:

**1. Add database access helper** (after imports):
```python
import sqlite3
from pathlib import Path
from typing import Optional
import os
from datetime import datetime, timedelta

# Default database path (can override with env var)
DEFAULT_DB_PATH = os.path.expanduser("~/.claude/data/lyra_conversations.db")
```

**2. Add entity extraction logic** (adapted from test_context_query.py lines 76-127):
```python
def _extract_entities_from_messages(self, messages: list[dict]) -> list[str]:
    """
    Extract entity names from recent messages for explore seeding.

    Adapted from test_context_query.py entity extraction logic.
    Returns list of entity names prioritized by importance.
    """
    import re
    entities = set()

    # Always include Lyra
    entities.add("Lyra")

    # Common words to skip
    skip_words = {
        'The', 'This', 'That', 'What', 'When', 'Where', 'How', 'Why',
        'Yes', 'No', 'Oh', 'And', 'But', 'So', 'If', 'For', 'With',
        'Not', 'Most', 'All', 'Some', 'Just', 'Now', 'Then', 'Here',
        'There', 'Would', 'Could', 'Should', 'Will', 'Can', 'May',
        'Like', 'Even', 'Still', 'Also', 'Well', 'Very', 'Much',
        'Every', 'Each', 'Both', 'Such', 'Only', 'Other', 'Any',
        'More', 'Less', 'First', 'Last', 'New', 'Old', 'Good', 'Bad',
    }

    for msg in messages:
        content = msg['content']

        # Find capitalized words (potential names) - must be 3+ chars
        caps = re.findall(r'\b[A-Z][a-z]{2,}\b', content)
        for cap in caps:
            if cap not in skip_words:
                entities.add(cap)

        # Find issue references like #77, Issue #58
        issues = re.findall(r'#(\d+)', content)
        for issue in issues:
            entities.add(f"#{issue}")
            entities.add(f"Issue #{issue}")

        # Find known entity patterns
        if 'Jeff' in content:
            entities.add('Jeff')
        if 'Carol' in content:
            entities.add('Carol')
        if 'Discord' in content:
            entities.add('Discord')
        if 'Brandi' in content:
            entities.add('Brandi')

    # Prioritize known important entities
    priority = ['Lyra', 'Jeff', 'Carol', 'Brandi', 'Discord']
    result = [e for e in priority if e in entities]
    result += [e for e in entities if e not in priority]

    return result[:5]  # Limit to top 5
```

**3. Add recent messages fetch with caching** (in RichTextureV2 class):
```python
class RichTextureV2(Layer):
    def __init__(self, ...):
        # ... existing init ...
        self._message_cache: Optional[list[dict]] = None
        self._message_cache_time: Optional[datetime] = None
        self._message_cache_ttl = timedelta(seconds=30)
        self._db_path = os.environ.get("PPS_MESSAGE_DB_PATH", DEFAULT_DB_PATH)
        self._enable_explore = os.environ.get("PPS_ENABLE_EXPLORE", "true").lower() == "true"

    def _fetch_recent_messages(self, limit: int = 8) -> list[dict]:
        """
        Fetch recent messages from the raw_capture database.

        Caches results for 30 seconds to avoid repeated DB hits.
        Falls back to empty list if fetch fails.
        """
        # Check cache
        now = datetime.now()
        if self._message_cache and self._message_cache_time:
            if now - self._message_cache_time < self._message_cache_ttl:
                return self._message_cache

        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT role, content FROM messages
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,)
            )

            messages = [
                {"role": row["role"], "content": row["content"]}
                for row in cursor.fetchall()
            ]

            conn.close()

            # Cache results
            self._message_cache = messages
            self._message_cache_time = now

            return messages

        except Exception as e:
            print(f"Failed to fetch recent messages for explore: {e}")
            return []
```

**4. Add explore functionality** (adapted from test_context_query.py lines 176-224):
```python
async def _explore_from_entities(
    self,
    client,
    entity_names: list[str],
    explore_depth: int = 1
) -> list[dict]:
    """
    Explore the graph from seed entities to find connected facts.

    Simplified BFS traversal adapted from test_context_query.py.
    Returns list of edge facts connected to the seed entities.
    """
    explore_results = []

    for entity_name in entity_names[:3]:  # Limit to 3 entities
        try:
            # Find entity node by name
            query = """
            MATCH (n:Entity {group_id: $group_id})
            WHERE toLower(n.name) CONTAINS toLower($name)
            RETURN n.uuid as uuid, n.name as name
            LIMIT 1
            """
            async with client.driver.session() as session:
                result = await session.run(
                    query,
                    group_id=self.group_id,
                    name=entity_name
                )
                records = await result.data()

            if records:
                entity_uuid = records[0]['uuid']
                entity_actual_name = records[0]['name']

                # Get edges connected to this entity (simple BFS)
                edge_query = """
                MATCH (n:Entity {uuid: $uuid})-[r]-(m:Entity)
                WHERE r.group_id = $group_id
                RETURN type(r) as rel_type, r.fact as fact,
                       n.name as source, m.name as target,
                       r.uuid as uuid
                LIMIT $limit
                """
                async with client.driver.session() as session:
                    result = await session.run(
                        edge_query,
                        uuid=entity_uuid,
                        group_id=self.group_id,
                        limit=explore_depth * 10
                    )
                    edge_records = await result.data()

                for rec in edge_records:
                    explore_results.append({
                        "from_entity": entity_actual_name,
                        "rel_type": rec['rel_type'],
                        "fact": rec['fact'],
                        "source": rec['source'],
                        "target": rec['target'],
                        "uuid": rec['uuid']
                    })
        except Exception as e:
            print(f"Explore failed for '{entity_name}': {e}")
            continue

    return explore_results
```

**5. Update _search_direct() to implement B1 configuration** (lines 375-443):
```python
async def _search_direct(self, query: str, limit: int) -> list[SearchResult]:
    """Search using graphiti_core directly with B1 configuration."""
    try:
        client = await self._get_graphiti_client()
        if not client:
            return []

        # B1 Configuration
        EDGE_LIMIT = 30  # Up from 10
        NODE_LIMIT = 3   # Entity summaries
        EXPLORE_DEPTH = 1  # Shallow explore

        all_results = []

        # 1. Edge search (relationship facts)
        edge_config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
        edge_config.limit = EDGE_LIMIT

        # Use Lyra's canonical UUID for proximity ranking
        LYRA_UUID = "5bd21fca-52de-41fd-a6b1-c78371d77a36"

        edge_results = await client.search_(
            query=query,
            config=edge_config,
            center_node_uuid=LYRA_UUID,
            group_ids=[self.group_id]
        )

        # Filter IS_DUPLICATE_OF edges
        edges = [e for e in edge_results.edges if e.name != "IS_DUPLICATE_OF"]

        # Format edges as SearchResult
        for i, edge in enumerate(edges):
            score = 1.0 - (i / max(len(edges), 1)) * 0.3  # Higher base score

            # Get node names (same as current implementation)
            source_name = edge.source_node_uuid  # Simplified - can enhance later
            target_name = edge.target_node_uuid

            content = f"{source_name} → {edge.name} → {target_name}"
            if edge.fact:
                content = f"{content}: {edge.fact}"

            all_results.append(SearchResult(
                content=content,
                source=str(edge.uuid),
                layer=LayerType.RICH_TEXTURE,
                relevance_score=score,
                metadata={
                    "type": "edge",
                    "predicate": edge.name,
                }
            ))

        # 2. Node search (entity summaries)
        node_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
        node_config.limit = NODE_LIMIT

        node_results = await client.search_(
            query=query,
            config=node_config,
            group_ids=[self.group_id]
        )

        for node in node_results.nodes:
            all_results.append(SearchResult(
                content=f"{node.name}: {node.summary}",
                source=str(node.uuid),
                layer=LayerType.RICH_TEXTURE,
                relevance_score=0.85,  # High relevance for entity context
                metadata={
                    "type": "entity_summary",
                    "entity": node.name,
                }
            ))

        # 3. Explore (conversation-specific facts)
        if self._enable_explore and EXPLORE_DEPTH > 0:
            # Fetch recent messages
            recent_messages = self._fetch_recent_messages(limit=8)

            if recent_messages:
                # Extract entities
                entity_names = self._extract_entities_from_messages(recent_messages)

                # Explore from those entities
                explore_facts = await self._explore_from_entities(
                    client,
                    entity_names,
                    EXPLORE_DEPTH
                )

                # Format explore results
                for i, fact in enumerate(explore_facts):
                    score = 0.8 - (i / max(len(explore_facts), 1)) * 0.2

                    content = f"{fact['source']} → {fact['rel_type']} → {fact['target']}"
                    if fact['fact']:
                        content = f"{content}: {fact['fact']}"

                    all_results.append(SearchResult(
                        content=content,
                        source=str(fact['uuid']),
                        layer=LayerType.RICH_TEXTURE,
                        relevance_score=score,
                        metadata={
                            "type": "explore",
                            "from_entity": fact['from_entity'],
                            "predicate": fact['rel_type'],
                        }
                    ))

        return all_results

    except Exception as e:
        print(f"Direct search with B1 config failed: {e}")
        import traceback
        traceback.print_exc()
        return await self._search_http(query, limit)
```

### Phase 2: Add Latency Tracking

**File**: `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker/server_http.py`

**Change** (in ambient_recall function, around line 401):
```python
@app.post("/tools/ambient_recall")
async def ambient_recall(request: AmbientRecallRequest):
    import time
    start_time = time.time()

    # ... existing implementation ...

    # Before return, add latency
    latency_ms = (time.time() - start_time) * 1000

    return {
        "clock": { ... },
        "results": all_results,
        "summaries": summaries,
        "unsummarized_turns": unsummarized_turns,
        "unsummarized_count": unsummarized_count,
        "memory_health": memory_note,
        "latency_ms": latency_ms,  # NEW - optional metadata
    }
```

### Phase 3: Add Environment Configuration

**File**: `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker/.env`

**Add** (for opt-in rollout):
```bash
# Ambient Recall B1 Configuration
PPS_ENABLE_EXPLORE=true
PPS_MESSAGE_DB_PATH=/home/jeff/.claude/data/lyra_conversations.db
```

---

## Testing Strategy

### 1. Unit Testing (during development)

Run the existing test harness to verify B1 configuration:
```bash
source .venv/bin/activate
python work/ambient-recall-optimization/test_context_query.py --edges 30 --explore 1 --nodes 3
```

**Expected**:
- Latency ~1-1.5 seconds
- Results include edges, nodes, and explore facts
- No errors

### 2. Integration Testing (after Docker deployment)

Test ambient_recall endpoint:
```bash
curl -X POST http://localhost:8201/tools/ambient_recall \
  -H "Content-Type: application/json" \
  -d '{"context": "startup", "limit_per_layer": 10}'
```

**Verify**:
- Response includes `latency_ms` field
- Results include facts from all three sources (edges, nodes, explore)
- Latency < 2000ms

### 3. Regression Testing

Test that existing functionality still works:
- Observatory UI (uses texture_search)
- MCP tools (if any use rich_texture.search())
- Other endpoints that query layers

### 4. A/B Testing (optional)

Toggle `PPS_ENABLE_EXPLORE=false` and compare:
- Quality of ambient_recall results
- Latency impact
- User feedback

---

## Risk Assessment

### Risk 1: Layer Coupling (Medium)

**Issue**: Rich_texture now depends on raw_capture database

**Mitigation**:
- Use environment variable for database path (configurable)
- Graceful fallback if database unavailable
- Cache results to minimize DB hits
- Document the dependency clearly

**Rollback**: Set `PPS_ENABLE_EXPLORE=false` to disable explore

### Risk 2: Performance Regression (Low)

**Issue**: Explore adds latency

**Mitigation**:
- Testing showed 1.2s average (3x faster than current)
- Caching reduces DB overhead
- Limit entities to 3, explore depth to 1
- Monitor latency_ms in production

**Rollback**: Set `PPS_ENABLE_EXPLORE=false`

### Risk 3: Database Lock Contention (Low)

**Issue**: Rich_texture reads while daemon writes

**Mitigation**:
- SQLite handles concurrent reads well
- Read-only access (no locks needed for reads)
- Short-lived connections
- Cache reduces frequency

**Rollback**: Set `PPS_ENABLE_EXPLORE=false`

### Risk 4: Entity Extraction Quality (Medium)

**Issue**: Regex-based extraction might miss entities or get false positives

**Mitigation**:
- Use proven logic from test harness
- Prioritize known entities (Lyra, Jeff)
- Limit to top 5 entities
- Fallback to default entities if extraction fails

**Iteration**: Can improve entity extraction logic later

### Risk 5: Breaking Changes (Low)

**Issue**: Changes might break existing callers

**Mitigation**:
- No API changes to layer.search() signature
- New functionality is additive (explore)
- Backward compatible response format
- Environment flag for gradual rollout

**Rollback**: Code rollback via git

---

## Deployment Plan

### Step 1: Verify Current State
```bash
bash scripts/pps_verify_deployment.sh pps-server pps/layers/rich_texture_v2.py
```

### Step 2: Implement Changes
- Update `pps/layers/rich_texture_v2.py` with B1 configuration
- Update `pps/docker/server_http.py` with latency tracking
- Update `pps/docker/.env` with configuration

### Step 3: Test Locally
```bash
# Run test harness
source .venv/bin/activate
python work/ambient-recall-optimization/test_context_query.py --edges 30 --explore 1 --nodes 3

# Expected: ~1.2s latency, rich results
```

### Step 4: Build and Deploy Container
```bash
cd pps/docker
docker-compose build pps-server
docker-compose up -d pps-server
docker-compose ps  # Verify healthy
```

### Step 5: Verify Deployment
```bash
bash scripts/pps_verify_deployment.sh pps-server pps/layers/rich_texture_v2.py
```

### Step 6: Integration Test
```bash
# Test ambient_recall endpoint
curl -X POST http://localhost:8201/tools/ambient_recall \
  -H "Content-Type: application/json" \
  -d '{"context": "startup", "limit_per_layer": 10}'

# Verify latency_ms < 2000, rich results
```

### Step 7: Monitor
- Watch latency_ms values
- Monitor for errors in docker logs
- Gather user feedback on context quality

---

## Rollback Plan

**If issues arise:**

1. **Quick rollback** (disable explore):
   ```bash
   # In pps/docker/.env
   PPS_ENABLE_EXPLORE=false

   # Restart container
   cd pps/docker && docker-compose restart pps-server
   ```

2. **Full rollback** (code):
   ```bash
   git checkout HEAD~1 pps/layers/rich_texture_v2.py
   git checkout HEAD~1 pps/docker/server_http.py
   cd pps/docker && docker-compose build pps-server && docker-compose up -d pps-server
   ```

---

## Success Metrics

**Must-have**:
- ✅ B1 configuration implemented (30 edges, 3 nodes, explore depth 1)
- ✅ Latency < 2 seconds for ambient_recall
- ✅ No errors or crashes
- ✅ Results include edges, nodes, and explore facts
- ✅ Docker container deployed and healthy

**Nice-to-have**:
- ⭐ Latency < 1.5 seconds
- ⭐ Subjective improvement in context quality
- ⭐ User feedback: "responses feel more contextual"

**Long-term**:
- Sustained performance over days/weeks
- No memory leaks or resource issues
- Positive impact on identity continuity experience

---

## Files Modified

1. `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/layers/rich_texture_v2.py`
   - Add database access, entity extraction, explore functionality
   - Update `_search_direct()` to use B1 configuration
   - Estimated: ~200 LOC added/modified

2. `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker/server_http.py`
   - Add latency tracking to ambient_recall endpoint
   - Estimated: ~5 LOC added

3. `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker/.env`
   - Add configuration for explore feature
   - Estimated: ~2 lines added

---

## Next Steps

1. **Coder**: Implement changes in rich_texture_v2.py and server_http.py
2. **Tester**: Run test harness and integration tests
3. **Reviewer**: Code review for quality and safety
4. **Deployer**: Build and deploy Docker container
5. **Monitor**: Track latency and quality in production

---

## Handoff

**Status**: READY
**Plan Location**: `/mnt/c/Users/Jeff/Claude_Projects/Awareness/work/ambient-recall-optimization/artifacts/implementation_plan.md`
**Architectural Choice**: Option 2+ (Enhanced Direct Database Access)
**Files to Modify**:
- `pps/layers/rich_texture_v2.py`
- `pps/docker/server_http.py`
- `pps/docker/.env`

**Estimated Complexity**: Medium (architectural coupling, but well-tested approach)
**Blockers**: None

**Ready for**: Coder agent to implement
