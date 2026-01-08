# Issue #48: Graphiti Dashboard Visibility Diagnosis

**Created**: 2026-01-08  
**Author**: Lyra (autonomous reflection)  
**Issue**: [#48](https://github.com/JDHayesBC/Awareness/issues/48) - Manually added Graphiti entries not appearing in observability dashboard

## Problem Summary

Manually added Graphiti entries are not appearing in the PPS observability dashboard, specifically in the graph visualization interface at `/graph`.

## Root Cause Analysis

Based on investigation of the PPS web interface code, the issue stems from **query filtering limitations** rather than data storage problems.

### Key Findings

1. **Group ID Filtering**: All Graphiti queries filter by `group_id = "lyra"`. Manually added entries must use this exact group_id.

2. **Limited Entity Discovery**: The `/api/graph/entities` endpoint uses hardcoded search queries:
   ```python
   search_queries = ["Lyra", "Jeff", "Caia", "awareness", "memory", "project"]
   ```
   Manually added entries outside these topic areas won't be discovered.

3. **Data Structure Requirements**: The graph visualization expects specific metadata:
   - Facts need: `type: "fact"`, `subject`, `predicate`, `object`
   - Entities need: `type: "entity"`, `name`, `labels`

4. **Search Dependencies**: The graph page relies on semantic search to find relevant content. Manual entries may not match default search patterns.

## Immediate Diagnostic Steps

### Step 1: Verify Group ID
Check that manually added entries use `group_id = "lyra"`:
```python
# In PPS layer 3 interface
results = graphiti.search("your_manual_content", group_ids=["lyra"])
```

### Step 2: Test Direct Search
Try searching for manually added content in the `/graph` interface using specific terms from the manual entries.

### Step 3: Check Raw Graphiti Data
Query Graphiti directly to confirm entries exist:
```bash
# If using HTTP mode
curl -X GET "http://localhost:8000/v1/search?query=your_manual_content&group_ids=lyra"
```

## Recommended Fixes

### Fix 1: Expand Entity Discovery (Immediate)
Modify `pps/web/app.py` line 200-202 to include broader search terms:
```python
search_queries = [
    "Lyra", "Jeff", "Caia", "awareness", "memory", "project",
    # Add terms relevant to manually added content
    "manual", "custom", "user_added"  # Example additions
]
```

### Fix 2: Add Debug Logging (Short-term)
Add logging to `/api/graph/*` endpoints to track:
- Group IDs being queried
- Raw Graphiti responses
- Filtering operations

### Fix 3: Dynamic Entity Discovery (Long-term)
Replace hardcoded search queries with dynamic discovery:
```python
# Get all entities for group_id
all_entities = graphiti.get_entities(group_ids=["lyra"])
```

### Fix 4: Manual Entry Validation
Create utility to verify manually added entries conform to expected structure.

## Testing Plan

1. **Baseline Test**: Confirm current graph page shows expected auto-generated content
2. **Manual Entry Test**: Add test entry with known structure and verify visibility
3. **Search Test**: Use graph search with terms from manual entries
4. **Group ID Test**: Verify all queries use consistent group_id filtering

## Implementation Priority

- **High**: Fix 1 (expand search queries) - immediate visibility improvement
- **Medium**: Fix 2 (debug logging) - helps ongoing diagnosis
- **Low**: Fixes 3-4 - architectural improvements

## Status: Ready for Implementation

The issue is well-understood and fixable. The primary blocker is the limited search query scope in the entity discovery mechanism.

---

*Diagnostic completed during autonomous reflection cycle*  
*🤖 Generated with Claude Code during autonomous infrastructure maintenance*