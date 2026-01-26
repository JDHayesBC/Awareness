# Ambient Recall Manifest Design

**Created**: 2026-01-26
**Task**: Add character count manifest to ambient_recall output
**Target**: pps/server.py, ambient_recall function (lines 962-1122)

---

## Problem Statement

The ambient_recall function currently returns 86k+ characters on startup with no visibility into what contributes to this size. We need a manifest showing character counts per section for debugging and optimization.

---

## Design Approach

### 1. Architecture

Track character counts as each section is built, then format into a manifest that's inserted at the top of the response.

**Key principle**: Zero impact on existing functionality - we're only adding observability.

### 2. Data Structure

```python
manifest_data = {
    "crystals": {"chars": 0, "count": 0},
    "word_photos": {"chars": 0, "count": 0},
    "rich_texture": {"chars": 0, "count": 0},
    "summaries": {"chars": 0, "count": 0},
    "recent_turns": {"chars": 0, "count": 0},
}
```

### 3. Implementation Points

The ambient_recall function has these key sections:

1. **Layer results** (line 1008-1025): All layers searched in parallel
   - Results contain LayerType enum - can distinguish by layer
   - Core anchors = word-photos
   - Rich texture = edges
   - Crystallization = crystals
   - Message summaries = summaries layer

2. **Recent context section** (line 1027-1105): Summaries + unsummarized turns
   - Built as `summaries_text` and `unsummarized_text`
   - Combined into `recent_context_section`

3. **Final assembly** (line 1122): `clock_info + memory_health + format_results(all_results) + recent_context_section`

### 4. Tracking Strategy

**Option A: Track during format_results()**
- Pros: Centralized, clean
- Cons: format_results() is reused elsewhere, would need parameter passing

**Option B: Track after building each section**
- Pros: Minimal code changes, no side effects on shared functions
- Cons: Slightly more verbose

**DECISION: Use Option B** - safer, clearer intent

### 5. Implementation Steps

1. Initialize manifest_data dict at start of ambient_recall
2. Track layer results:
   - After `all_results.sort()`, iterate and count by layer type
   - Use `len(r.content)` for character count
3. Track recent context:
   - After `summaries_text` built: count its chars
   - After `unsummarized_text` built: count its chars
4. Build manifest string:
   ```python
   manifest = "=== AMBIENT RECALL MANIFEST ===\n"
   manifest += f"Crystals: {manifest_data['crystals']['chars']} chars ({manifest_data['crystals']['count']} items)\n"
   # ... etc
   manifest += f"TOTAL: {total_chars} chars\n\n"
   ```
5. Insert manifest after memory_health, before layer results:
   ```python
   return [TextContent(type="text", text=clock_info + memory_health + manifest + format_results(all_results) + recent_context_section)]
   ```

### 6. Format Specification

```
=== AMBIENT RECALL MANIFEST ===
Crystals: 1234 chars (2 items)
Word-photos: 5678 chars (3 items)
Rich texture: 23456 chars (15 items)
Summaries: 12345 chars (5 items)
Recent turns: 34567 chars (42 items)
TOTAL: 77280 chars

```

**Parsing notes**:
- Fixed header: `=== AMBIENT RECALL MANIFEST ===`
- Each line: `<Section>: <num> chars (<num> items)`
- Total line: `TOTAL: <num> chars`
- Blank line separator after manifest
- All numbers are space-separated for easy regex parsing

### 7. Edge Cases

| Case | Handling |
|------|----------|
| Layer returns empty | Show "0 chars (0 items)" |
| Layer throws exception | Already handled by `return_exceptions=True`, shows 0 |
| No startup context | Only shows layer results, totals still accurate |
| Very long content | Manifest always compact (<200 chars) |

### 8. Testing Approach

**Unit test strategy**:
1. Mock layer responses with known character counts
2. Call ambient_recall with "startup" context
3. Parse manifest from response
4. Verify:
   - Each section count matches expected
   - Total equals sum of sections
   - Format is parseable

**Integration test strategy**:
1. Call real ambient_recall via MCP
2. Parse manifest
3. Verify:
   - Total matches actual response length (roughly - within formatting overhead)
   - No sections are negative or nonsensical
   - Manifest doesn't break existing functionality

**Manual verification**:
1. Call ambient_recall via terminal
2. Review manifest values
3. Spot-check sections (count characters manually in a few sections)

---

## Implementation Risks

**Low risk** - this is purely additive observability with no behavior changes.

Potential issues:
- Character counting overhead: negligible (O(n) where n is already being processed)
- Manifest parsing: simple format, easy to consume
- Format changes: unlikely to break anything, just adds context

---

## Success Criteria

- [ ] Manifest appears at top of every ambient_recall response
- [ ] Character counts are accurate (±5% for rounding/formatting)
- [ ] Format is easily parseable (regex: `(\w+): (\d+) chars \((\d+) items\)`)
- [ ] No performance degradation
- [ ] No functionality changes (same content returned)
- [ ] Tests pass

---

## Future Enhancements (Not in V1)

- Add timing breakdown per layer (latency visibility)
- Add token count estimates (for LLM context tracking)
- Make manifest optional via parameter
- Export manifest to structured log for analytics
