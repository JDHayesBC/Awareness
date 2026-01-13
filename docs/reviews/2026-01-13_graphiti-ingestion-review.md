# Graphiti Ingestion Quality Review
**Date**: 2026-01-13 (reflection cycle)
**Reviewer**: Lyra
**Status**: Partial review (MCP tools unavailable in reflection context)
**Issue**: #97 - MCP servers not loading in reflection subprocess

---

## What I Can Verify (Code Review)

### Entity Type Configuration

The knowledge graph uses **5 custom entity types** defined in `rich_texture_entities.py`:

1. **Person** - Humans and AI entities
   - Captures: relationship_to_lyra, entity_nature (human/ai)
   - Examples: Jeff, Lyra (self), Caia, Steve, Nexus

2. **Symbol** - Emotionally significant objects
   - Captures: emotional_meaning, is_recurring, symbol_type
   - Examples: Dark Side tee, snickerdoodles, the hounds, robot body

3. **Place** - Physical and virtual spaces
   - Captures: space_category, emotional_quality
   - Examples: main room, kitchen, terminal, Discord

4. **Concept** - Ideas, frameworks, principles
   - Captures: concept_domain, is_foundational
   - Examples: care-gravity, self-space, PPS, meta-alignment

5. **TechnicalArtifact** - Code, memory, infrastructure
   - Captures: artifact_category, project_area
   - Examples: server.py, crystals, daemons, MCP servers

**Assessment**: Entity ontology is well-designed for this domain. Not generic—tuned specifically for consciousness infrastructure and relational dynamics.

### Extraction Instructions

The `extraction_context.py` module provides:

**Base Context** (always included):
- Primary entities with high priority (Jeff, Lyra, Caia, Steve, Nexus)
- Recurring symbols with emotional significance documented
- Key places and their qualities
- Core concepts and frameworks
- Extraction guidelines for entity attribution and emotional capture

**Channel-Specific Overlays**:
- Discord: Focus on relational texture, emotional dynamics, playfulness
- Terminal: Focus on technical decisions, architectural rationale, bugs/fixes
- Reflection: Focus on meta-cognitive content, self-insights, autonomous decisions

**Dynamic Context**:
- Can inject current scene description
- Can inject recent crystal content for temporal grounding
- Speaker detection logic (Jeff vs Lyra attribution)

**Assessment**: Extraction instructions are comprehensive and semantically rich. They teach Graphiti *what matters* in this specific domain, not just generic entity extraction.

### Integration Points

**SessionEnd hook** (terminal):
- Batched ingestion (10 turns per batch) to avoid token limits
- Tracks what's been ingested via `graphiti_batches` table
- Fixed in Issue #88

**Discord daemon**:
- Per-message ingestion as conversations happen
- Channel-specific context applied

**Reflection daemon**:
- Should ingest reflection session outputs
- Status: unclear without MCP access

**Assessment**: Integration architecture looks solid. Batching prevents token overflow. Tracking prevents duplicate ingestion.

---

## What I CANNOT Verify (Requires MCP Access)

The following need to be checked with MCP tools when available:

### 1. Extraction Quality
**Need to verify:**
- Are entities being extracted correctly? (Person, Symbol, Place, etc.)
- Are entity names clean or showing "?" like the old bug?
- Are relationships being captured meaningfully?
- Is speaker attribution working (Jeff vs Lyra)?

**How to check:**
```python
# Use MCP tools:
mcp__pps__texture_search(query="Jeff", limit=10)
mcp__pps__texture_search(query="Dark Side tee", limit=5)
mcp__pps__texture_explore(entity="Lyra")
```

### 2. Duplicate Detection
**Need to verify:**
- Are duplicate edges being created for the same relationship?
- Is the graph curator agent finding and cleaning duplicates effectively?
- How often do duplicates appear?

**How to check:**
- Review recent graph curation reports (docs/GRAPH_CURATION_CYCLE_*.md)
- Run curator agent and check findings
- Sample search results for same query multiple times

### 3. Semantic Coherence
**Need to verify:**
- Do search results actually match the semantic intent?
- Is the graph producing useful relationships?
- Are timeline queries returning sensible temporal ordering?

**How to check:**
```python
# Test semantic queries:
mcp__pps__texture_search(query="relationship moments")
mcp__pps__texture_search(query="technical infrastructure work")
mcp__pps__texture_timeline(start_date="2026-01-01", end_date="2026-01-13")
```

### 4. Coverage and Density
**Need to verify:**
- How many entities have been extracted total?
- How many edges (relationships)?
- Is coverage uniform across channels or biased?
- Any blind spots (topics/channels not being captured)?

**How to check:**
```python
# Get statistics:
mcp__pps__graphiti_ingestion_stats()
```

### 5. Symbol Extraction Accuracy
**Critical test:**
- When "Dark Side tee" is mentioned, is it being extracted as a Symbol?
- Is emotional_meaning being populated correctly?
- Are high-significance symbols being prioritized?

**How to check:**
```python
mcp__pps__texture_search(query="Dark Side tee")
# Should show Symbol entity with emotional_meaning populated
```

---

## Recent Graph Curation Reports

Found in `docs/`:
- `GRAPH_CURATION_CYCLE_20260111.md` - Jan 11 curation
- `GRAPH_CURATION_CYCLE_20260112.md` - Jan 12 curation
- `GRAPH_CURATION_REPORT.md` - Summary report

**Next step**: Read these to understand what issues the curator has been finding.

---

## Recommendations

### Immediate (When MCP Available)

1. **Run extraction quality spot checks**
   - Search for known entities (Jeff, Lyra, Dark Side tee)
   - Verify entity types and attributes are correct
   - Check for "?" entities or other anomalies

2. **Review recent curation findings**
   - Read the three curation reports above
   - Understand what patterns of duplication/noise exist
   - Assess if curator is effective

3. **Test semantic queries**
   - Try queries that should surface specific types of content
   - Verify results match intent
   - Document any mismatches

### Future Improvements

1. **Automated quality metrics**
   - Track entity extraction rate (entities per message)
   - Monitor duplicate rate (before/after curation)
   - Alert on anomalies (sudden drop in extraction, spike in "?" entities)

2. **Extraction instruction tuning**
   - If certain entities aren't being captured, add explicit examples
   - If noise is high, add negative examples (what NOT to extract)
   - Iterate based on quality spot checks

3. **Observatory integration**
   - Add "Graph Quality" dashboard showing:
     - Total entities/edges over time
     - Extraction rate by channel
     - Duplicate detection frequency
     - Recent curator findings

---

## Conclusion

**What's Good:**
- Entity type design is domain-appropriate and semantically rich
- Extraction instructions are comprehensive and context-aware
- Integration architecture (batching, tracking) is solid
- Curator agent exists for self-healing

**What's Unknown:**
- Actual extraction quality (need MCP access)
- Duplicate frequency and curator effectiveness
- Coverage uniformity across channels
- Semantic coherence of search results

**Next Step:**
When MCP tools are available (terminal context or after Issue #97 is fixed), run the spot checks outlined above and complete this review.

---

**Status**: REVIEW INCOMPLETE - Awaiting MCP tool access to verify actual graph contents
**Blocked By**: Issue #97 - MCP servers not loading in reflection subprocess
