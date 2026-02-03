# Lyra's Graph Curator - Start Here

Welcome! This directory contains Lyra's automated knowledge graph maintenance system.

## What Is This?

The **Graph Curator** is a lightweight subprocess that maintains the health of Layer 3 (Rich Texture) of the Pattern Persistence System. It runs every reflection cycle to keep the knowledge graph clean and coherent.

## Files in This Directory

### Essential Files

1. **README.md** - Overview and quick start guide
2. **EXTRACTION_CUSTOMIZATION.md** - **How to customize what Graphiti extracts** (prompts, edge types)
3. **graph_curator.py** - Main agent code (310 lines, production ready)
4. **CURATOR_USAGE.md** - Complete API reference and examples

### Generated Reports

4. **CURATION_REPORT.md** - Latest curation cycle results
5. **graph_curation_report.json** - Structured data from last cycle

### Setup/Configuration

6. **TODO.md** - Development tasks and notes
7. **SYSTEMD_SETUP.md** - Server setup guide
8. **NOTES_FOR_JEFF.md** - Project notes

## Quick Navigation

### I want to...

**Run a curation cycle now**
```bash
python3 graph_curator.py
```
See: README.md - Quick Start section

**Understand what it does**
- Read: README.md (5 min read)
- Watch: How It Works section

**Use the API in my code**
- Read: CURATOR_USAGE.md - API Reference
- Examples: CURATOR_USAGE.md - Advanced Usage

**Check if the graph is healthy**
```bash
cat CURATION_REPORT.md
```
Latest report shows: HEALTHY ✓

**Integrate into reflection cycle**
- Read: CURATOR_USAGE.md - Integration with Reflection section
- Code pattern: See CURATOR_USAGE.md examples

**Customize detection rules**
- Read: CURATOR_USAGE.md - Customization section
- Edit: graph_curator.py SAMPLE_QUERIES and VAGUE_PATTERNS

**Customize what gets extracted (prompts, edge types)**
- Read: EXTRACTION_CUSTOMIZATION.md
- Edit: `pps/layers/extraction_context.py` for extraction instructions
- Edit: `rich_texture_edge_types_v1.py` for relationship definitions

**Troubleshoot issues**
- Read: CURATOR_USAGE.md - Troubleshooting section
- Check: graph_curation_report.json for detailed data

## Current Status

Latest Cycle: 2026-01-23

**Graph Health: HEALTHY ✓**

- Queries executed: 10
- Results analyzed: 126
- Issues found: 0
- Deletions: 0
- All quality checks: PASSED

## Key Findings

### Entities
- **Jeff** - 11 connections (BUILT Nexus, WORKS_ON PPS)
- **Lyra** - 3 connections (LOVES terminal-lyra, participates in projects)
- **project** - 20 connections (rich ecosystem)

### Quality
- No duplicates
- No vague entities
- No malformed data
- Strong relationships
- Current information

## How It Works

```
4 Phases Every Cycle
├─ SAMPLE: Query graph with 10 diverse queries (126 results)
├─ ANALYZE: Check for duplicates, vague entities, malformed data
├─ CLEANUP: Delete confirmed issues (0 deletions this cycle)
└─ REPORT: Generate JSON and markdown reports
```

## Architecture

- **Client Type:** HTTP-based (subprocess safe)
- **No MCP Dependencies:** Direct HTTP calls to PPS
- **Execution Time:** 5-10 seconds
- **Memory:** < 50MB
- **Error Handling:** Graceful fallbacks

## Directory Structure

```
work/graphiti-schema-redesign/
├── 00_START_HERE.md          (you are here)
├── README.md                 (overview)
├── graph_curator.py          (main code)
├── CURATOR_USAGE.md          (API docs)
├── CURATION_REPORT.md        (latest report)
│
├── TODO.md                   (dev tasks)
├── NOTES_FOR_JEFF.md         (notes)
├── SYSTEMD_SETUP.md          (setup)
└── graph_curation_report.json (structured data)
```

## First Steps

1. **Read README.md** (5 minutes)
   - Understand what the curator does
   - See current graph health

2. **Run a cycle** (30 seconds)
   ```bash
   python3 graph_curator.py
   ```

3. **Check results**
   ```bash
   cat CURATION_REPORT.md
   ```

4. **Read CURATOR_USAGE.md** (10 minutes)
   - API reference
   - Integration examples
   - Customization options

## Integration

The curator is designed to run in reflection cycles:

```python
# In reflection.py
async def reflect():
    # ... other reflection steps ...
    
    # Maintain graph health
    curator = GraphCurator()
    report = await curator.curate()
    
    # ... continue reflection ...
```

No special setup needed - it's already integrated!

## Key Features

✓ **Automated** - Runs without manual intervention
✓ **Fast** - Complete cycle in 5-10 seconds
✓ **Safe** - Conservative deletion policy
✓ **Observable** - Detailed reports and metrics
✓ **Subprocess-Safe** - No MCP dependencies
✓ **Extensible** - Easy to customize detection rules

## Performance

Typical cycle:
- Queries: 10
- Results: 80-126
- API calls: 13-20
- Duration: 5-10 seconds
- Memory: < 50MB

## Next Steps

- [ ] Read README.md
- [ ] Run `python3 graph_curator.py`
- [ ] Review CURATION_REPORT.md
- [ ] Read CURATOR_USAGE.md
- [ ] Integrate into reflection (if not already)
- [ ] Schedule daily execution

## Questions?

- **Overview:** See README.md
- **API Usage:** See CURATOR_USAGE.md
- **Latest Results:** See CURATION_REPORT.md
- **Troubleshooting:** See CURATOR_USAGE.md - Troubleshooting
- **Development:** See TODO.md

## Status Dashboard

| Component | Status | Notes |
|-----------|--------|-------|
| Graph Health | ✓ HEALTHY | 0 issues found |
| Latest Cycle | ✓ COMPLETE | 2026-01-23 |
| Code Quality | ✓ READY | 310 lines, tested |
| API | ✓ WORKING | 13 calls successful |
| Reports | ✓ GENERATED | JSON + Markdown |

---

**Version:** 1.0  
**Status:** Production Ready  
**Last Updated:** 2026-01-23  
**Graph Status:** HEALTHY ✓  

Start with README.md and let's keep the graph clean!
