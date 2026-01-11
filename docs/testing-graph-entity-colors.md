# Testing Guide: Entity Type Color-Coding in Graph Visualization

**Issue**: #90
**Date**: 2026-01-09
**Status**: Implemented, awaiting human review

## What Was Changed

Added entity type color-coding to the knowledge graph visualization in PPS Observatory.

### Files Modified
- `pps/web/templates/graph.html`

### Changes Made

1. **Added `getEntityTypeColor()` function** (lines 94-119)
   - Maps entity types to specific colors
   - Falls back to relevance-based coloring for unknown types
   - Takes `labels` array and `relevance` score as parameters

2. **Updated Cytoscape node styling** (lines 233-241)
   - Modified `background-color` style function
   - Preserves existing behavior: source nodes stay blue
   - Uses entity type color for all other nodes
   - Size remains based on relevance score

### Color Palette

| Entity Type | Color | Hex Code |
|-------------|-------|----------|
| Person | Blue | #3b82f6 |
| Place | Green | #10b981 |
| Symbol | Purple | #a855f7 |
| Concept | Orange | #f97316 |
| TechnicalArtifact | Gray | #6b7280 |
| Unknown/Default | Grayscale | rgb(100-255) based on relevance |

## Manual Testing Steps

### Prerequisites
1. PPS web server must be running
2. Graphiti layer must have data with various entity types
3. Browser with developer tools

### Test Cases

#### Test 1: Basic Color Mapping
1. Navigate to `http://localhost:5001/graph`
2. Search for a query that returns mixed entity types (e.g., "Jeff")
3. **Expected**: Nodes display different colors based on type
   - Person entities → blue
   - Place entities → green
   - Symbol entities → purple
   - Concept entities → orange
   - TechnicalArtifact entities → gray

#### Test 2: Source Node Behavior
1. Perform a search that highlights a source node
2. **Expected**: Source node remains blue (#3b82f6) regardless of entity type
3. **Reason**: Source highlighting takes precedence for UX clarity

#### Test 3: Unknown Entity Types
1. If entities exist without recognized type labels
2. **Expected**: Fall back to relevance-based grayscale coloring
3. **Reason**: Maintains backward compatibility

#### Test 4: Entity Selection Info Panel
1. Click on nodes of different types
2. Check the info panel on the right
3. **Expected**: "Types" field shows the entity labels
4. **Verify**: Color matches the type shown

#### Test 5: Layout Changes
1. Change graph layout (Force-Directed, Hierarchical, Circular, Concentric)
2. **Expected**: Colors persist across layout changes
3. **Expected**: No JavaScript errors in console

#### Test 6: Explore Entity Function
1. Double-click a node to explore connections
2. **Expected**: New graph loads with type-based colors
3. **Expected**: Connected entities maintain their type colors

#### Test 7: Multiple Labels
1. Find entity with multiple labels (e.g., ["Person", "Symbol"])
2. **Expected**: Uses first/primary label for color (Person → blue)
3. **Verify**: Info panel shows all labels

### Browser Console Testing

Open browser DevTools console and verify:

```javascript
// Test the color function directly
getEntityTypeColor(['Person'], 0.8)  // Should return '#3b82f6'
getEntityTypeColor(['Place'], 0.5)   // Should return '#10b981'
getEntityTypeColor(['Symbol'], 0.7)  // Should return '#a855f7'
getEntityTypeColor(['Concept'], 0.6) // Should return '#f97316'
getEntityTypeColor(['TechnicalArtifact'], 0.9) // Should return '#6b7280'
getEntityTypeColor([], 0.5)          // Should return 'rgb(177, 177, 177)'
getEntityTypeColor(['Unknown'], 0.7) // Should return 'rgb(209, 209, 209)'
```

### Performance Testing

1. Load a large graph (50+ nodes)
2. **Expected**: No noticeable lag
3. **Expected**: Layout animation remains smooth
4. Check browser performance metrics

### Visual QA

1. **Contrast**: Verify all colors are visible on dark background (#1f2937)
2. **Accessibility**: Text labels remain readable on colored nodes
3. **Consistency**: Same entity type always has same color across searches

## Potential Issues to Watch For

1. **JavaScript errors**: Check console for any runtime errors
2. **Color conflicts**: Verify colors don't clash with selection highlighting
3. **Missing labels**: Entities without labels should gracefully fall back
4. **Null handling**: Nodes with null/undefined labels handled correctly

## Rollback Plan

If issues are found:

```bash
git checkout HEAD -- pps/web/templates/graph.html
```

Or manually revert the two sections:
1. Remove `getEntityTypeColor()` function
2. Restore original `background-color` style function

## Next Steps

- [ ] Human review and testing
- [ ] Decide if color palette needs adjustment
- [ ] Consider adding legend to UI (future enhancement)
- [ ] Commit if approved

## Notes

- No automated frontend tests exist for the web UI
- Testing requires manual verification
- Colors chosen for visibility and semantic meaning
- Implementation maintains backward compatibility
