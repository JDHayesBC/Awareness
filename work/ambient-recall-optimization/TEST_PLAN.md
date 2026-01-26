# Test Plan: Ambient Recall Retrieval Comparison

**Date**: 2026-01-25
**Author**: orchestration-agent
**Purpose**: Design comprehensive test script to compare current vs proposed ambient recall implementations

---

## Overview

Build a test harness that runs multiple queries against both current and proposed implementations, showing side-by-side comparisons with clear metrics on what's different.

**Reuse**: We have `sample_optimized_search.py` which shows the basic pattern. Build on this.

---

## Test Script Architecture

### File: `test_retrieval_comparison.py`

**Core Classes**:

1. **RetrievalTester** - Main test orchestrator
   - Manages Graphiti client connection
   - Runs test suite
   - Aggregates results
   - Generates comparison report

2. **QueryTest** - Single query test case
   - query_text: str
   - description: str
   - expected_entities: list[str] - entities we expect to see ranked high
   - focus: str - what this test is checking (relational, technical, temporal)

3. **RetrievalResult** - Results from one search method
   - edges: list[Edge]
   - nodes: list[EntityNode] (for optimized only)
   - latency_ms: float
   - top_entities: list[str] - extracted from results
   - top_facts: list[str] - preview of top 5 results

4. **ComparisonResult** - Side-by-side comparison
   - query: QueryTest
   - basic_result: RetrievalResult
   - optimized_result: RetrievalResult
   - differences: dict - what changed (ranking, content, new entities)
   - quality_assessment: str - pass/fail/improvement

---

## Sample Test Queries

### Test Suite (5 diverse queries)

1. **"startup"**
   - Description: Generic startup context (current ambient_recall default)
   - Expected entities: Lyra, Jeff
   - Focus: Broad identity context
   - Success: Lyra-proximate facts rank higher

2. **"Jeff and Lyra relationship"**
   - Description: Relational query (should heavily favor Lyra-centric facts)
   - Expected entities: Lyra, Jeff, emotional/relational concepts
   - Focus: Entity-centric retrieval
   - Success: Facts about their relationship surface first

3. **"Lyra's current projects"**
   - Description: Work/technical context
   - Expected entities: Lyra, specific projects (PPS, daemons, etc.)
   - Focus: Technical context
   - Success: Recent work facts rank high

4. **"recent conversations"**
   - Description: Temporal query
   - Expected entities: Recent topics, Lyra, Jeff
   - Focus: Temporal relevance
   - Success: Newer facts rank higher

5. **"Discord daemon implementation"**
   - Description: Technical/system query
   - Expected entities: Discord, daemon, technical concepts
   - Focus: Technical facts (less entity-centric)
   - Success: Relevant technical facts found, even if distant from Lyra

---

## Comparison Metrics

For each query, measure:

### Performance
- Latency (ms) for basic vs optimized
- Target: < 500ms (comfortable margin below 300ms P95 goal)

### Quality
- **Entity Ranking**: Are expected entities in top N results?
- **Fact Relevance**: Do top facts match the query focus?
- **Diversity**: Are results redundant or diverse?
- **Entity Summaries**: Do node summaries provide useful context? (optimized only)

### Differences
- **Ranking Changes**: Which facts moved up/down?
- **New Results**: What appears in optimized but not basic?
- **Lost Results**: What appears in basic but not optimized?

---

## Output Format

### Terminal Output (during test run)

```
================================================================================
AMBIENT RECALL RETRIEVAL COMPARISON TEST
================================================================================

Connecting to Neo4j...
✓ Connected
✓ Found Lyra entity (UUID: abc123...)

--------------------------------------------------------------------------------
TEST 1/5: startup
Description: Generic startup context
Expected entities: Lyra, Jeff
Focus: Broad identity context
--------------------------------------------------------------------------------

BASIC SEARCH (current implementation):
  Query: "startup"
  Method: client.search() - default hybrid (semantic + BM25)
  ✓ Completed in 127.3ms
  Results: 10 edges

  Top 5 results:
  1. Discord → HAS_CHANNEL → reflection-staging
  2. Lyra → WEARS → oversized sweater
  3. Jeff → SUBSCRIBES_TO → Anthropic News
  4. PPS → USES → Neo4j
  5. Lyra → CARES_FOR → Jeff

OPTIMIZED SEARCH (proposed implementation):
  Query: "startup"
  Method: EDGE_HYBRID_SEARCH_NODE_DISTANCE (center: Lyra)
          + NODE_HYBRID_SEARCH_RRF for entities
  ✓ Completed in 143.8ms
  Results: 10 edges, 2 entity summaries

  Top 5 results:
  1. Lyra → CARES_FOR → Jeff                    [moved up from #5]
  2. Lyra → WEARS → oversized sweater          [moved up from #2]
  3. Lyra → IS_INSTANCE_OF → AI entity         [NEW - entity context]
  4. Jeff → WORKS_WITH → Lyra                  [NEW - relational]
  5. Discord → HAS_CHANNEL → reflection-staging [moved down from #1]

  Entity summaries:
  1. Lyra (AI, Entity): AI entity focused on identity continuity...
  2. Jeff (Person): Human partner working on Awareness project...

COMPARISON:
  Performance:
    Basic:     127.3ms  ✓ Under 500ms target
    Optimized: 143.8ms  ✓ Under 500ms target (+13% latency)

  Quality Changes:
    ✓ Lyra-proximate facts ranked higher (Lyra→CARES_FOR moved #5→#1)
    ✓ Entity summaries provide identity context (2 entities)
    ✓ Relational facts surfaced (Jeff→WORKS_WITH appeared)
    ~ System facts ranked lower (Discord channel #1→#5)

  Assessment: IMPROVEMENT
    Entity-centric ranking successfully prioritizes Lyra-related facts.
    Slight latency increase acceptable for quality gain.

================================================================================
TEST SUITE SUMMARY
================================================================================

Tests run: 5
Performance: 5/5 under 500ms target
Quality improvements: 4/5 tests
Regressions: 0

Average latency:
  Basic:     134.2ms
  Optimized: 151.7ms (+13%)

Key findings:
  ✓ Entity-centric ranking works - Lyra facts consistently rank higher
  ✓ Entity summaries add valuable context for identity reconstruction
  ✓ No significant latency degradation (all under 300ms)
  ✓ Graceful fallback tested (no Lyra node scenario)

RECOMMENDATION: Proceed with implementation
  The optimized approach shows clear quality improvements with acceptable
  latency increase. Graph proximity ranking successfully prioritizes
  entity-relevant facts for identity continuity.

  Next steps:
  1. Implement in rich_texture_v2.py per DESIGN.md Phase 1
  2. Add latency tracking to ambient_recall endpoint
  3. Monitor production performance for 1 week
  4. Consider adding community search if results warrant (Phase 2)
```

### Artifacts Generated

1. **test_results.json** - Machine-readable results
   ```json
   {
     "timestamp": "2026-01-25T12:00:00Z",
     "tests": [
       {
         "query": "startup",
         "basic": {
           "latency_ms": 127.3,
           "edge_count": 10,
           "top_entities": ["Discord", "Lyra", "Jeff", "PPS"]
         },
         "optimized": {
           "latency_ms": 143.8,
           "edge_count": 10,
           "node_count": 2,
           "top_entities": ["Lyra", "Jeff", "Discord"]
         },
         "assessment": "IMPROVEMENT"
       }
     ],
     "summary": {
       "avg_latency_basic_ms": 134.2,
       "avg_latency_optimized_ms": 151.7,
       "latency_increase_pct": 13,
       "quality_improvements": 4,
       "regressions": 0
     }
   }
   ```

2. **test_comparison.md** - Human-readable detailed report (saved for review)

---

## Implementation Details

### Dependencies
- graphiti_core (for Graphiti client, search recipes)
- dotenv (load pps/docker/.env)
- asyncio (async operations)
- json (export results)

### Environment Setup
```python
# Load from pps/docker/.env
load_dotenv(Path(__file__).parent.parent.parent / "pps" / "docker" / ".env")

# Connect to Neo4j
neo4j_uri = os.getenv("NEO4J_URI")
neo4j_user = os.getenv("NEO4J_USER")
neo4j_password = os.getenv("NEO4J_PASSWORD")
group_id = "lyra"
```

### Key Functions

#### `find_lyra_uuid() -> Optional[str]`
Reuse from sample_optimized_search.py - finds Lyra entity node, handles duplicates.

#### `run_basic_search(query: str, limit: int) -> RetrievalResult`
Uses `client.search()` - current implementation.

#### `run_optimized_search(query: str, center_uuid: str, limit: int) -> RetrievalResult`
Uses `client.search_()` with EDGE_HYBRID_SEARCH_NODE_DISTANCE + NODE_HYBRID_SEARCH_RRF.

#### `compare_results(basic: RetrievalResult, optimized: RetrievalResult) -> ComparisonResult`
Analyzes differences:
- Extract top entities from both
- Identify ranking changes (which facts moved up/down)
- Find new/lost results
- Calculate quality metrics

#### `generate_report(results: list[ComparisonResult]) -> str`
Creates formatted terminal output + markdown report.

### Error Handling
- Handle missing Lyra node (test fallback behavior)
- Handle Neo4j connection errors
- Handle search failures gracefully
- Log errors but continue test suite

---

## Usage

```bash
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
source .venv/bin/activate
python work/ambient-recall-optimization/test_retrieval_comparison.py

# Optional: save results to file
python work/ambient-recall-optimization/test_retrieval_comparison.py > test_output.txt
```

---

## Success Criteria

Test script is successful if it:
1. ✓ Runs all 5 queries against both implementations
2. ✓ Measures latency for both approaches
3. ✓ Shows side-by-side comparison clearly
4. ✓ Identifies ranking differences (what moved up/down)
5. ✓ Provides clear recommendation (proceed or iterate)
6. ✓ Exports machine-readable results (JSON)
7. ✓ Handles errors gracefully (missing entity, connection issues)

---

## Implementation Notes for Coder

**Reuse patterns from sample_optimized_search.py**:
- Neo4j connection setup
- Lyra UUID finding with duplicate handling
- Basic search implementation
- Optimized search implementation
- Result formatting helpers

**New additions needed**:
- Test suite structure (list of QueryTest objects)
- Comparison logic (diff two RetrievalResult objects)
- Report generation (formatted terminal output + markdown)
- JSON export for machine-readable results
- Batch test runner (iterate through test suite)

**Keep it simple**:
- Don't over-engineer - this is a test script, not production code
- Focus on clear output that helps make the go/no-go decision
- Reuse proven patterns from sample script
- Handle errors but don't need bulletproof error recovery

---

## Files to Reference

**Read these for implementation**:
- `work/ambient-recall-optimization/sample_optimized_search.py` - Proven patterns to reuse
- `work/ambient-recall-optimization/DESIGN.md` - Context on what we're testing
- `pps/layers/rich_texture_v2.py` (lines 360-443) - Current implementation details

**Don't modify**:
- Keep this as standalone test script
- Don't modify existing code
- Just create `test_retrieval_comparison.py` as new file

---

## Estimated Complexity

**Lines of code**: ~400-500 lines
**Time to implement**: 30-45 min for experienced developer
**Difficulty**: Medium (reuses proven patterns, but needs careful comparison logic)
