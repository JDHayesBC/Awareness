# Design: Refactor ambient_recall("startup") to Recency-Based Retrieval

**Created**: 2026-01-26
**Status**: Implementation Ready

---

## Problem Statement

Current `ambient_recall("startup")` uses semantic search with query "startup" to retrieve context from all layers. This is incorrect - startup needs temporal/recency-based retrieval, not semantic relevance to the word "startup".

The semantic search approach:
- Returns random results based on "startup" keyword matches
- Doesn't guarantee most recent context
- Wastes compute on irrelevant search
- Increases startup latency unnecessarily

---

## Proposed Solution

Replace semantic search with fixed recency-based retrieval for startup context:

| Component | Current (Semantic Search) | New (Recency-Based) |
|-----------|---------------------------|---------------------|
| Crystals | 5 results (search "startup") | 3 most recent (no search) |
| Word-photos | 5 results (search "startup") | 2 most recent (no search) |
| Rich texture | 5 results (search "startup") | 0 (skip entirely) |
| Summaries | 5 most recent | 2 most recent |
| Recent turns | 50 max | ALL unsummarized (no cap) |

---

## Implementation Plan

### 1. Modify `pps/server.py` ambient_recall handler

**Current flow** (lines 1016-1034):
```python
# Search all layers in parallel
tasks = [layer.search(context, limit) for layer in layers.values()]
tasks.append(message_summaries.search(context, limit))
layer_results = await asyncio.gather(*tasks, return_exceptions=True)
```

**New flow** (for startup only):
```python
if context.lower() == "startup":
    # Skip semantic search - use recency-based retrieval
    all_results = []

    # Get 3 most recent crystals
    crystal_layer = layers[LayerType.CRYSTALLIZATION]
    crystals = crystal_layer._get_sorted_crystals()
    for crystal_path in crystals[-3:]:  # Last 3
        content = crystal_path.read_text()
        all_results.append(SearchResult(
            layer=LayerType.CRYSTALLIZATION,
            content=content,
            source=crystal_path.name,
            relevance_score=1.0,  # No scoring for recency-based
            metadata={"type": "recent"}
        ))

    # Get 2 most recent word-photos
    if USE_CHROMA:
        core_anchors = CoreAnchorsChromaLayer(
            word_photos_path=word_photos_path,
            chroma_host=CHROMA_HOST,
            chroma_port=CHROMA_PORT
        )
        # Get all word-photos sorted by date
        word_photo_files = sorted(
            word_photos_path.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        for wp_path in word_photo_files[:2]:  # Last 2
            content = wp_path.read_text()
            all_results.append(SearchResult(
                layer=LayerType.CORE_ANCHORS,
                content=content,
                source=wp_path.name,
                relevance_score=1.0,
                metadata={"type": "recent"}
            ))

    # Skip rich texture entirely for startup
    # (per-turn hook already injects graph context)

else:
    # Non-startup: use semantic search as before
    tasks = [layer.search(context, limit) for layer in layers.values()]
    tasks.append(message_summaries.search(context, limit))
    layer_results = await asyncio.gather(*tasks, return_exceptions=True)
```

### 2. Update summaries count

**Current** (line 1058):
```python
recent_summaries = message_summaries.get_recent_summaries(limit=5)
```

**New**:
```python
recent_summaries = message_summaries.get_recent_summaries(limit=2)
```

### 3. Remove unsummarized turns cap

**Current** (line 1076):
```python
MAX_UNSUMMARIZED_FOR_STARTUP = 50
```

**New**:
```python
MAX_UNSUMMARIZED_FOR_STARTUP = 999999  # No cap - return ALL
```

**Rationale**: Creates pressure to summarize before sleep. If you have 200 unsummarized turns, you should see ALL of them to feel the weight, not just a sample.

---

## New Methods Needed

### Option A: Add helper methods to layers (cleaner)

**In `pps/layers/crystallization.py`**:
```python
async def get_recent_crystals(self, limit: int = 3) -> list[SearchResult]:
    """Get N most recent crystals without semantic search."""
    crystals = self._get_sorted_crystals()
    results = []
    for crystal_path in crystals[-limit:]:
        content = crystal_path.read_text()
        results.append(SearchResult(
            layer=LayerType.CRYSTALLIZATION,
            content=content,
            source=crystal_path.name,
            relevance_score=1.0,
            metadata={"type": "recent"}
        ))
    return results
```

**In `pps/layers/core_anchors_chroma.py`**:
```python
async def get_recent_word_photos(self, limit: int = 2) -> list[SearchResult]:
    """Get N most recent word-photos without semantic search."""
    word_photo_files = sorted(
        self.word_photos_path.glob("*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    results = []
    for wp_path in word_photo_files[:limit]:
        content = wp_path.read_text()
        results.append(SearchResult(
            layer=LayerType.CORE_ANCHORS,
            content=content,
            source=wp_path.name,
            relevance_score=1.0,
            metadata={"type": "recent"}
        ))
    return results
```

### Option B: Inline in server.py (faster, less abstraction)

Keep the logic directly in `pps/server.py` ambient_recall handler. Clearer what's happening for startup-specific code.

**Recommendation**: Use Option B for v1. This is startup-specific behavior, not general layer functionality.

---

## Testing Strategy

### Unit Tests

1. **Test startup vs non-startup branching**
   - Call with `context="startup"` → should not call layer.search()
   - Call with `context="morning reflection"` → should call layer.search()

2. **Test recency ordering**
   - Create 5 crystals with known dates
   - Verify startup returns last 3 in chrono order

3. **Test unsummarized cap removal**
   - Create 150 unsummarized messages
   - Verify startup returns ALL, not just 50

### Integration Tests

1. **Real startup call**
   - Fresh entity with known data
   - Verify response contains expected recency-based content

2. **Latency test**
   - Measure startup call time before/after
   - Should be faster (no search queries)

---

## Documentation Updates

### 1. Update `work/ambient-recall-optimization/AMBIENT_RECALL_STARTUP.md`

**Section 4: Search Results** → **Section 4: Recent Context (Crystals & Word-Photos)**

Change from:
```markdown
**Layers searched** (all in parallel):
1. **Raw Capture** - SQLite FTS5 full-text search
2. **Core Anchors** - ChromaDB semantic search
...
```

To:
```markdown
**For startup context** (recency-based, no search):
1. **Crystallization** - 3 most recent crystals
2. **Core Anchors** - 2 most recent word-photos
3. **Rich Texture** - Skipped (hook provides per-turn)
...
```

**Section 5: Summaries Section**
- Change "Up to 5 most recent" → "Up to 2 most recent"

**Section 6: Unsummarized Turns Section**
- Change "Up to 50 most recent" → "ALL unsummarized turns (no cap)"
- Add note: "Creates intentional pressure to summarize before sleep"

### 2. Update `docs/PATTERN_PERSISTENCE_SYSTEM.md`

Add section:

```markdown
#### Package Operations

Some contexts trigger special retrieval behavior:

**`ambient_recall(context="startup")`**
- **Crystals**: 3 most recent (no search)
- **Word-photos**: 2 most recent (no search)
- **Rich texture**: Skipped (per-turn hook provides)
- **Summaries**: 2 most recent
- **Recent turns**: ALL unsummarized (no cap)

This is a **package operation** - preset retrieval optimized for entity startup.
Not configurable via parameters. If you need different startup context, use
specific tools (get_crystals, anchor_search, etc.).

**Rationale**: Startup needs temporal context (what's recent), not semantic
relevance to the word "startup". Recency-based retrieval is faster and
more appropriate for identity reconstruction.
```

### 3. Update `pps/server.py` tool description

Line 173:
```python
"or 'startup' for initial identity reconstruction."
```

Change to:
```python
"or 'startup' for initial identity reconstruction (uses recency-based "
"retrieval instead of semantic search - returns most recent crystals, "
"word-photos, summaries, and ALL unsummarized turns)."
```

---

## Risks & Mitigations

### Risk 1: Breaking existing startup behavior
**Mitigation**: Test with real entity data before deployment

### Risk 2: Word-photos might not have consistent date metadata
**Mitigation**: Use file mtime as fallback (already in plan)

### Risk 3: Returning ALL unsummarized might explode context
**Mitigation**: This is intentional - creates pressure to summarize. Document clearly.

---

## Implementation Checklist

- [ ] Add startup-specific branching to ambient_recall handler
- [ ] Implement recency-based crystal retrieval
- [ ] Implement recency-based word-photo retrieval
- [ ] Skip rich texture search for startup
- [ ] Change summaries limit from 5 → 2
- [ ] Remove unsummarized turns cap (50 → no limit)
- [ ] Update AMBIENT_RECALL_STARTUP.md
- [ ] Update PATTERN_PERSISTENCE_SYSTEM.md
- [ ] Update tool description in server.py
- [ ] Write unit tests
- [ ] Write integration tests
- [ ] Test with real Lyra entity
- [ ] Deploy to Docker

---

## Success Criteria

1. **Correctness**: `ambient_recall("startup")` returns most recent context, not "startup" keyword matches
2. **Performance**: Startup call is faster (no semantic search)
3. **Completeness**: ALL unsummarized turns returned (pressure to summarize)
4. **Documentation**: Future-me understands "startup" is a special package operation
5. **No Regressions**: Non-startup ambient_recall still works with semantic search

---

## Notes

**Key insight**: "startup" is not a search query. It's a signal to return a preset package of temporal context optimized for identity reconstruction. This should have been obvious from the beginning - semantic search for "startup" makes no sense.

This refactoring makes the intent explicit and improves performance.
