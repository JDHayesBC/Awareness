# Graph Curator - Usage Guide

Lyra's lightweight graph maintenance agent for the Pattern Persistence System (Layer 3).

## Overview

The Graph Curator runs automatically every reflection cycle to:
1. **Sample** the knowledge graph with diverse queries
2. **Identify** issues (duplicates, vague entities, malformed data)
3. **Clean** confirmed problems by deleting bad entries
4. **Report** findings and health status

## Quick Start

### Run a Curation Cycle

```bash
python3 work/graphiti-schema-redesign/graph_curator.py
```

This will:
- Execute 10 diverse sampling queries
- Analyze 80+ graph entries
- Generate a curation report
- Save results to `graph_curation_report.json`

### Check Graph Health

```python
import asyncio
from daemon.pps_http_client import PPSHttpClient

async def check_health():
    async with PPSHttpClient() as client:
        health = await client.pps_health()
        print(health)

asyncio.run(check_health())
```

## API Reference

### PPSHttpClient Methods

#### `texture_search(query, limit=10)`
Search the knowledge graph for entities and facts.

```python
results = await client.texture_search("Jeff", limit=15)
for result in results.get("results", []):
    print(f"UUID: {result['source']}")
    print(f"Content: {result['content']}")
    print(f"Type: {result['metadata']['type']}")
```

#### `texture_explore(entity_name, depth=2)`
Explore relationships from a specific entity.

```python
connections = await client.texture_explore("Lyra", depth=2)
for conn in connections.get("results", []):
    print(f"Related to Lyra: {conn['content']}")
```

#### `texture_delete(uuid)`
Delete a fact (edge) from the graph by UUID.

```python
result = await client.texture_delete(uuid)
if result["success"]:
    print(f"Deleted: {result['message']}")
```

#### `add_triplet(source, relationship, target, fact=None)`
Add a new fact to the graph.

```python
await client.add_triplet(
    source="Jeff",
    relationship="WORKS_ON",
    target="Awareness System",
    fact="Jeff actively develops the Awareness system",
    source_type="Person",
    target_type="Project"
)
```

## Issue Detection Rules

The curator automatically flags these issues:

### 1. Vague Entity Names
**Patterns detected:** "The", "A", "?", "Unknown", "thing", "stuff", etc.
**Action:** Delete (requires manual confirmation)
**Example:** "The" → relationships with vague entities → deleted

### 2. Duplicate Entries
**Detection:** Identical or near-identical content with different UUIDs
**Action:** Delete all but one copy
**Example:** Two facts saying "Jeff built Nexus" → keep one, delete duplicate

### 3. Malformed Data
**Patterns:** Missing UUIDs, empty content, invalid references
**Action:** Delete immediately
**Example:** Fact with UUID but empty content → deleted

### 4. Stale Facts
**Pattern:** Outdated information with newer counterparts
**Action:** Review and delete if confirmed obsolete
**Example:** Replaced workflow descriptions → mark for deletion

## Customization

### Modify Sampling Queries

Edit `graph_curator.py` to change sampled queries:

```python
SAMPLE_QUERIES = [
    "Jeff",
    "Lyra",
    "project",
    # Add your own queries:
    "your_entity",
    "your_topic",
]
```

### Adjust Vague Patterns

Add more patterns to detect:

```python
VAGUE_PATTERNS = {
    "The",
    "A",
    "?",
    "your_vague_pattern",  # Add custom patterns
}
```

### Change Deletion Behavior

Modify the curator to review instead of auto-delete:

```python
# In _cleanup() method:
issue.recommended_action = "review"  # Instead of "delete"
```

## Output Files

### `graph_curation_report.json`
Main report from the curator cycle. Contains:
- Statistics (queries, results, issues found)
- List of issues detected
- List of deletions executed

```json
{
  "timestamp": "2026-01-23T21:29:06.167217",
  "status": "complete",
  "statistics": {
    "total_searched": 10,
    "total_results": 126,
    "duplicates_found": 0,
    "vague_entities_found": 0,
    "malformed_facts_found": 0,
    "items_deleted": 0
  },
  "issues_found": [],
  "deletions": []
}
```

### `CURATION_REPORT.md`
Human-readable detailed report with:
- Executive summary
- Sampling results
- Key entity analysis
- Quality assessments
- Recommendations

## Integration with Reflection

The curator runs as a subprocess during reflection cycles:

```python
# In reflection.py
async def reflect():
    # ... other reflection steps ...

    # Maintain graph health
    curator = GraphCurator()
    report = await curator.curate()

    # Log report for analysis
    log_curator_report(report)
```

### Subprocess Safe

The curator uses HTTP-based APIs that work in subprocesses:
- No MCP tool dependency
- Direct HTTP calls to PPS server (localhost:8201)
- No environment-specific setup needed

## Monitoring

### Health Check Endpoints

```python
# Overall PPS health
health = await client.pps_health()

# Individual layer status
print(health['layers']['rich_texture'])
```

### Graph Statistics

Monitor from reports:
- Total entries per query
- Entity connection counts
- Relationship type distribution
- Data freshness

## Best Practices

1. **Run Regularly** - Execute curator every 24-48 hours
2. **Review Reports** - Read the markdown report for insights
3. **Conservative Deletion** - Only delete obvious duplicates/errors
4. **Backup Before Cleanup** - Export graph data before large deletions
5. **Monitor Metrics** - Track statistics over time for trends

## Troubleshooting

### "Cannot connect to Graphiti"
The PPS server isn't running. Start it:
```bash
cd pps && python3 docker/server_http.py
```

### No results from search
Graph may be empty or query doesn't match. Try:
```python
results = await client.texture_search("*", limit=5)
```

### Delete fails with 404
UUID not found. Check that UUID is from a recent search result.

## Architecture

```
Reflection Cycle
    ↓
Graph Curator (subprocess)
    ├─ Sample graph with diverse queries
    ├─ Analyze issues
    ├─ Delete confirmed problems
    └─ Generate report
    ↓
Report saved to disk
    ↓
Reflection continues
```

## Performance

Typical curation cycle:
- **Duration:** 5-10 seconds
- **Queries:** 10
- **Results analyzed:** 80-126
- **API calls:** 13-20
- **Network overhead:** Minimal (local HTTP)

## Advanced Usage

### Custom Issue Detection

Create subclass for custom logic:

```python
from graph_curator import GraphCurator, GraphIssue

class CustomCurator(GraphCurator):
    def _check_result(self, result):
        # Your custom logic
        super()._check_result(result)

        # Add domain-specific checks
        if "your_pattern" in result.get("content", ""):
            self.issues.append(GraphIssue(
                issue_type="custom",
                severity="medium",
                # ... rest of issue ...
            ))
```

### Scheduled Execution

With cron:

```bash
# Run curator every 24 hours at 2 AM
0 2 * * * /usr/bin/python3 /path/to/graph_curator.py >> /var/log/graph_curator.log
```

## Support

For issues or enhancements:
1. Check `CURATION_REPORT.md` for recent findings
2. Review `graph_curation_report.json` for detailed data
3. Run manual searches to understand graph structure
4. Consult PPS documentation for API details

---

**Curator Version:** 1.0
**Last Updated:** 2026-01-23
**Status:** Active and healthy
