# Manifest Implementation Notes

**Date**: 2026-01-26
**Files Modified**:
- `pps/server.py` (MCP server)
- `pps/docker/server_http.py` (HTTP server)

---

## Changes Made

### 1. MCP Server (pps/server.py)

**Lines 966-973**: Initialize manifest_data dict at start of ambient_recall

**Lines 1036-1048**: Track layer results after sorting
- Crystals: LayerType.CRYSTALLIZATION
- Word-photos: LayerType.CORE_ANCHORS
- Rich texture: LayerType.RICH_TEXTURE

**Lines 1071-1072**: Track summaries as they're built

**Lines 1125-1126**: Track recent turns (unsummarized messages)

**Lines 1135-1143**: Build manifest string

**Lines 1145-1161**: Insert manifest into response (both return paths)

### 2. HTTP Server (pps/docker/server_http.py)

**Lines 413-420**: Initialize manifest_data dict

**Lines 449-459**: Track layer results during processing

**Lines 517-518**: Track summaries

**Lines 568-569**: Track recent turns

**Lines 579-588**: Build manifest dict (JSON structure, not string)

**Lines 663, 676**: Add manifest to return values

---

## Manifest Format

### MCP Server (Text)
```
=== AMBIENT RECALL MANIFEST ===
Crystals: 1234 chars (2 items)
Word-photos: 5678 chars (3 items)
Rich texture: 23456 chars (15 items)
Summaries: 12345 chars (5 items)
Recent turns: 34567 chars (42 items)
TOTAL: 77280 chars

```

### HTTP Server (JSON)
```json
{
  "manifest": {
    "crystals": {"chars": 1234, "count": 2},
    "word_photos": {"chars": 5678, "count": 3},
    "rich_texture": {"chars": 23456, "count": 15},
    "summaries": {"chars": 12345, "count": 5},
    "recent_turns": {"chars": 34567, "count": 42},
    "total_chars": 77280
  }
}
```

---

## Testing Strategy

### Unit Test
Create a test that:
1. Mocks layer responses with known content lengths
2. Calls ambient_recall
3. Verifies manifest counts match expectations

### Integration Test
1. Call real ambient_recall via MCP (terminal) and HTTP (curl)
2. Parse manifest from responses
3. Verify counts are reasonable (no negatives, total makes sense)
4. Spot-check a few sections manually

### Manual Verification
1. Terminal: Call ambient_recall on startup
2. Review manifest at top of output
3. Verify numbers seem plausible (crystals < word-photos, etc.)

---

## Deployment Required

**Yes** - server_http.py changes need Docker deployment:
1. Rebuild: `cd pps/docker && docker-compose build pps-server`
2. Deploy: `docker-compose up -d pps-server`
3. Verify: `docker-compose ps` (check healthy)
4. Test: curl http://localhost:8201/tools/ambient_recall

**No** - server.py changes work immediately (MCP runs from source)

---

## Edge Cases Handled

1. **Empty sections**: Show "0 chars (0 items)"
2. **Layer exceptions**: Already handled by return_exceptions=True
3. **Truncated content**: Track original length, not truncated
4. **Startup vs non-startup**: Both paths have manifest

---

## Future Enhancements

- Add timing breakdown per layer
- Add token count estimates
- Make manifest optional via parameter
- Export to structured log for analytics
- Dashboard visualization
