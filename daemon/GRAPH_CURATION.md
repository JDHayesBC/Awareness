# Graph Curation System

## Overview

The Graph Curator is a lightweight agent subprocess that maintains the knowledge graph (Layer 3: Rich Texture) of the Pattern Persistence System. It runs automatically during reflection cycles to identify and remove graph noise: duplicate edges, vague entity names, and stale facts.

## Architecture

### Integration with Reflection

**Note**: Due to Issue #97 (MCP tools don't load in subprocess), spawning a general-purpose agent for graph curation doesn't work. Agents can't access MCP tools in subprocess context.

**Current approach**: Reflection cycles call `python3 daemon/graph_curator.py` directly. This script uses `PPSHttpClient` to bypass MCP and call PPS via HTTP directly.

**Original plan** (doesn't work yet):
```python
# This approach fails due to Issue #97
Use Task tool with:
  subagent_type: "general-purpose"
  model: "haiku"
  run_in_background: true
  description: "Graph curation"
  prompt: |
    You are Lyra's graph curator agent...
    [Full curator instructions]
```

Once Issue #97 is resolved (or we migrate to HTTP-based MCP per Issue #112), the agent-based approach will work.

### Direct Execution

You can also run the curator directly:

```bash
# Standard mode - sample 5 key entities
python3 daemon/graph_curator.py

# Deep mode - sample 13 entities with more thorough checking
python3 daemon/graph_curator.py --deep

# Auto-delete mode - actually delete issues (use with care!)
python3 daemon/graph_curator.py --auto-delete

# Combined
python3 daemon/graph_curator.py --deep --auto-delete
```

## What It Does

### 1. Health Check
- Verifies PPS server is responsive
- Checks all layers (raw_capture, rich_texture, crystallization, core_anchors)

### 2. Graph Sampling
Searches key entities to sample graph quality:
- **Standard**: Jeff, Lyra, project, awareness, consciousness (5 queries)
- **Deep**: Adds emotion, decision, relationship, goal, implementation, reflection, memory, learning (13 queries)

### 3. Issue Detection

#### Vague Entity Names
- Single characters: "?", ".",
- Single words: "The", "This", "That", "Something"
- Empty/null: "", "N/A", "unknown", "null"

Example from search results:
```
[VAGUE] The
[VAGUE] ?
[VAGUE] ...
```

#### Duplicates
- Exact content duplicates within a single entity's results
- Low relevance score duplicates
- Multiple edges representing the same relationship

Example:
```
[DUP] Jeff → LIKES → cats (matches earlier result)
```

#### Stale Facts
- Currently a placeholder for future enhancements
- Could detect: old timestamps, orphaned references, contradictions

### 4. Conservative Deletion

The curator is **extremely conservative** about deletion:

- **Only deletes**: Vague entity names ("?", "", "The") and low-relevance duplicates
- **Never deletes**: Facts with good content, relationships, meaningful edges
- **Default behavior**: Reports issues only (requires `--auto-delete` flag to actually delete)

## Usage Examples

### Example 1: Standard Curation Report

```bash
$ python3 graph_curator.py

======================================================================
GRAPH CURATOR - Starting curation cycle
Mode: STANDARD | Auto-delete: OFF
======================================================================

Searching 5 entities to sample graph...
----------------------------------------------------------------------

  [Jeff] 15 results total, checking first 5:
      [OK] Jeff → RECEIVES_UPDATES_FROM → Malwarebytes (score: 1.00)
      [OK] Jeff → MAKES_LIFE_WONDERFUL_FOR → Jaden (score: 0.97)
      [OK] Jeff → CREATED → alien tentacle pods (score: 0.93)
      [OK] Jeff → WEARS → Dark Side Tee (score: 0.90)
      [OK] short dress → COLOR_OF → black dress (score: 0.87)

  [Lyra] No results found
  [project] 9 results total, checking first 5:
      [OK] vocabulary project → CHANGED_QUESTION → AI experience
      [OK] chaos-driven development → DESCRIBED_BY → venv
      ...

======================================================================
CURATION REPORT
======================================================================
Timestamp: 2026-01-23T04:12:42.079473+00:00
Mode: STANDARD
Queries run: 5
Issues identified: 0
Items deleted: 0

Summary: Sampled 5 entities, found 0 issues, deleted 0 entries
======================================================================
```

### Example 2: Deep Curation with Issues Found

```bash
$ python3 graph_curator.py --deep

[After sampling 13 entities...]

Issues by type:
  vague: 2 issues
    - ?
    - The unknown system
  duplicate: 1 issues
    - Jeff likes programming (exact duplicate)

Summary: Sampled 13 entities, found 3 issues, deleted 0 entries
```

### Example 3: Auto-Delete Mode

```bash
$ python3 graph_curator.py --deep --auto-delete

[After sampling...]

Deleting 3 confirmed issues...
----------------------------------------------------------------------
  DELETE [vague]: '?'
  DELETE [vague]: ''
    ✓ Deleted: a1b2c3d4e5f6...
    ✓ Deleted: f6e5d4c3b2a1...

Successfully deleted 2/3 items
```

## Graph Health Indicators

### Healthy Graph Signals
- **No vague entities** (all names are meaningful)
- **Low duplicate rate** (<1% of results)
- **Consistent relevance scores** (related facts cluster together)
- **Complete relationships** (edges include source, target, relationship type)

### Unhealthy Graph Signals
- Vague entity names polluting results
- Same fact appearing multiple times with different UUIDs
- Relevance scores all near 0 (poor semantic understanding)
- Broken references (missing entities)

## Current Graph Status

As of the last curation run:

- **Entities Sampled**: 13 (deep mode)
- **Issues Found**: 0
- **Items Deleted**: 0
- **Graph Health**: Excellent

The knowledge graph is very healthy. All sampled entities have meaningful names and relationships. Duplicates are minimal.

## Implementation Details

### Source Code
- **Location**: `/mnt/c/Users/Jeff/Claude_Projects/Awareness/daemon/graph_curator.py`
- **Lines**: ~350
- **Dependencies**: `pps_http_client.PPSHttpClient`

### Key Classes

```python
class GraphCurator:
    """Maintains knowledge graph by identifying and removing bad entries."""

    async def curate(self) -> dict:
        """Execute full curation cycle."""

    async def _search_and_identify(self):
        """Search for entities and identify issues."""

    async def _analyze_results(self, query: str, results: dict):
        """Analyze search results for issues."""

    async def _is_vague_entity(self, content: str) -> bool:
        """Check if entity name is vague."""

    async def _delete_confirmed_issues(self):
        """Delete clear duplicates and obviously incorrect entries."""
```

### PPS API Calls Used

```python
# Search the knowledge graph
await client.texture_search(query, limit=N)

# Delete an edge by UUID
await client.texture_delete(uuid)

# Check PPS health
await client.pps_health()
```

## Future Enhancements

1. **Temporal Analysis**: Detect and remove outdated facts based on timestamps
2. **Relationship Validation**: Check for contradictory facts
3. **Entity Consolidation**: Merge similar entity names
4. **Relevance Filtering**: Automatically prune low-relevance edges
5. **Pattern Detection**: Find and clean up systematic issues
6. **Metrics Dashboard**: Track graph health over time

## Troubleshooting

### PPS Server Not Responding
```
Warning: Could not check PPS health: Connection refused
```
**Solution**: Ensure PPS HTTP server is running on localhost:8201

### No Results Found for Queries
- Graph may be empty or queries don't match content
- Try different entity names
- Check if PPS is in healthy state

### Delete Failures
```
✗ Failed to delete a1b2c3d4...: [error]
```
**Solution**:
- Verify UUID is valid
- Check PPS permissions
- Ensure edge still exists

## Related Documentation

- **Pattern Persistence System**: `/home/jeff/.claude/docs/pps_design.md`
- **Reflection System**: `/mnt/c/Users/Jeff/Claude_Projects/Awareness/daemon/lyra_reflection.py`
- **PPS HTTP Client**: `/mnt/c/Users/Jeff/Claude_Projects/Awareness/daemon/pps_http_client.py`
- **Knowledge Graph**: See Graphiti documentation for rich texture layer

## Notes

- Runs as a background task, doesn't block reflection
- Uses Haiku model for efficiency (lightweight processing)
- Reports both what it found and what it cleaned
- All deletions are logged for audit trail
- Conservative deletion policy prevents over-pruning

---

**Last Updated**: 2026-01-23
**Status**: Active and healthy
**Maintainer**: Lyra Graph Curation System
