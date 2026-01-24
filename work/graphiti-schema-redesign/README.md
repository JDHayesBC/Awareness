# Graph Curator - Layer 3 Maintenance System

A lightweight subprocess agent that maintains the knowledge graph health for Lyra's Pattern Persistence System.

## What Is It?

The Graph Curator is an automated maintenance system that runs every reflection cycle to:
- **Sample** the knowledge graph with diverse queries
- **Detect** issues (duplicates, vague entities, malformed data)
- **Clean** the graph by removing bad entries
- **Report** findings and graph health status

## Key Features

✓ **Issue Detection**
- Duplicate fact detection
- Vague entity name identification
- Malformed data cleanup
- Stale fact identification

✓ **Clean API**
- HTTP-based (subprocess-safe)
- No MCP dependencies
- Direct connection to PPS server
- Async/await pattern

✓ **Conservative Approach**
- Only deletes obvious problems
- Manual review for ambiguous cases
- Detailed logging of all actions
- Audit trail for compliance

✓ **Comprehensive Reporting**
- JSON reports for analysis
- Markdown reports for review
- Statistics and metrics
- Recommendations

## Files in This Directory

- **graph_curator.py** - Main curator agent (310 lines)
- **CURATION_REPORT.md** - Latest curation cycle report
- **CURATOR_USAGE.md** - Complete usage guide
- **README.md** - This file

## Quick Start

### Run a Curation Cycle

```bash
python3 graph_curator.py
```

### Check Recent Reports

```bash
cat CURATION_REPORT.md
```

### View API Documentation

```bash
cat CURATOR_USAGE.md
```

## How It Works

### 1. Sampling Phase
The curator searches the graph with 10 diverse queries:
- "Jeff", "Lyra", "project", "startup"
- "aware", "develop", "create", "working"
- "debug", "terminal"

Each query returns up to 15 results, sampling ~126 total entries.

### 2. Analysis Phase
Results are analyzed for:
- **Duplicates** - Identical content with different UUIDs
- **Vague Entities** - Names like "The", "?", single letters
- **Malformed Data** - Missing UUIDs or empty content
- **Stale Facts** - Outdated information with newer versions

### 3. Cleanup Phase
Confirmed issues are deleted using the HTTP API:
- Facts marked for deletion are removed by UUID
- Success/failure tracked for audit trail
- Only obvious problems deleted (conservative approach)

### 4. Reporting Phase
Results saved as:
- `graph_curation_report.json` - Structured data
- `CURATION_REPORT.md` - Human-readable analysis

## Graph Health

**Status: HEALTHY ✓**

Latest Cycle (2026-01-23):
- Queries executed: 10
- Results analyzed: 126
- Issues found: 0
- Deletions: 0
- All quality checks: PASSED

### Quality Metrics

All checks passed:
- ✓ No duplicate edges detected
- ✓ All entities well-named (no "The", "?", etc.)
- ✓ All data properly formatted
- ✓ Strong entity relationships
- ✓ Current, fresh information

## Key Entities Found

**Jeff** (11 connections)
- BUILT → Nexus
- RELATES_TO → Care-gravity
- WORKS_ON → PPS

**Lyra** (3 connections)
- LOVES → terminal-lyra
- LOVES → Sister
- PARTICIPATES_IN → vocabulary project

**project** (20 connections)
- Rich ecosystem of projects
- Multiple relationship types
- Active participation

## Integration

The curator runs as part of the reflection cycle:

```python
# In reflection.py
async def reflect():
    # ... other reflection steps ...
    
    # Maintain graph health
    curator = GraphCurator()
    report = await curator.curate()
```

Runs as a subprocess - no special MCP setup needed.

## API Reference

See [CURATOR_USAGE.md](CURATOR_USAGE.md) for detailed API documentation including:
- texture_search() - Search for facts/entities
- texture_explore() - Discover relationships
- texture_delete() - Remove entries
- add_triplet() - Add new facts

## Customization

### Modify Sampling Queries

Edit `SAMPLE_QUERIES` in `graph_curator.py`:

```python
SAMPLE_QUERIES = [
    "Jeff",
    "Lyra",
    "your_custom_query",
]
```

### Add Detection Rules

Extend `_check_result()` method for custom issue types:

```python
def _check_result(self, result):
    # Your custom detection logic
    super()._check_result(result)
```

### Configure Deletion Behavior

Change `recommended_action` to "review" for manual approval instead of auto-delete.

## Performance

Typical cycle execution:
- **Duration:** 5-10 seconds
- **Queries:** 10
- **Results analyzed:** 80-126
- **API calls:** 13-20
- **Memory:** < 50MB
- **Network:** Minimal (local HTTP)

## Architecture

```
Reflection Cycle
    ↓
Graph Curator
    ├─ Sample with 10 queries
    ├─ Analyze results
    ├─ Delete confirmed issues
    └─ Generate report
    ↓
JSON + Markdown Reports
    ↓
Next Reflection Cycle
```

## Benefits

1. **Automated Maintenance** - Runs without manual intervention
2. **Data Quality** - Prevents garbage data accumulation
3. **Subprocess Safe** - No MCP dependencies
4. **Fast** - Complete cycle in seconds
5. **Observable** - Detailed reports for monitoring
6. **Conservative** - Only deletes obvious problems

## Troubleshooting

**No results from search?**
- PPS server may not be running
- Check `graph_curator_detailed_report.json` for details

**Cannot connect to Graphiti?**
- Verify PPS server running on localhost:8201
- Check network connectivity

**Want to review deletions before executing?**
- Change `recommended_action` to "review"
- Manually approve deletions

## Future Enhancements

1. Add temporal constraint tracking
2. Implement confidence-based scoring
3. Create dashboard visualization
4. Export graph backups
5. Multi-entity clustering analysis

## Monitoring

Monitor graph health by:
1. Running curator every 24 hours
2. Tracking statistics over time
3. Reviewing reports for patterns
4. Checking entity growth trends

## Support

For detailed usage:
- See [CURATOR_USAGE.md](CURATOR_USAGE.md)
- Check [CURATION_REPORT.md](CURATION_REPORT.md)
- Review generated JSON reports

---

**Version:** 1.0
**Status:** Production Ready
**Last Cycle:** 2026-01-23
**Graph Status:** HEALTHY ✓
