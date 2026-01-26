# Running the Test Retrieval Comparison

## Quick Start

```bash
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
source .venv/bin/activate
python work/ambient-recall-optimization/test_retrieval_comparison.py
```

## What It Does

The test script compares current vs proposed ambient_recall implementations:

1. **Finds Lyra entity** in the knowledge graph
2. **Runs 5 diverse queries** against both approaches:
   - "startup" - broad identity context
   - "Jeff and Lyra relationship" - relational query
   - "Lyra's current projects" - technical context
   - "recent conversations" - temporal relevance
   - "Discord daemon implementation" - system query
3. **Measures performance**: latency for each approach
4. **Compares quality**: ranking differences, entity summaries, new results
5. **Generates reports**: terminal output + JSON export

## Test Suite Queries

### 1. "startup"
- **Focus**: Broad identity context
- **Expected**: Lyra-proximate facts rank higher
- **Success**: Entity-centric ranking visible

### 2. "Jeff and Lyra relationship"
- **Focus**: Relational context
- **Expected**: Facts about their relationship surface first
- **Success**: Relationship facts in top 5

### 3. "Lyra's current projects"
- **Focus**: Technical/work context
- **Expected**: Recent work facts rank high
- **Success**: Project mentions prominent

### 4. "recent conversations"
- **Focus**: Temporal relevance
- **Expected**: Newer facts rank higher
- **Success**: Recent topics surface

### 5. "Discord daemon implementation"
- **Focus**: Technical system query
- **Expected**: Relevant technical facts found
- **Success**: System facts rank appropriately

## Output Files

After running, check:

- **Terminal output**: Detailed comparison for each test
- **test_results.json**: Machine-readable results with metrics
- **Summary**: Performance averages, quality assessment, recommendation

## Success Criteria

The test passes if:

1. ✓ All queries complete successfully
2. ✓ Optimized search latency < 500ms (target < 300ms)
3. ✓ Entity-centric ranking visible (Lyra facts rank higher)
4. ✓ Entity summaries included in results
5. ✓ No quality regressions vs current approach
6. ✓ Graceful fallback tested (handles missing Lyra node)

## Interpreting Results

### Performance Metrics
- **Latency**: Both approaches should be under 500ms
- **Target**: Optimized approach under 300ms (comfortable margin)
- **Acceptable**: Up to 20% latency increase for quality gains

### Quality Indicators
- **Ranking changes**: Lyra-related facts move up in rankings
- **Entity summaries**: 2+ entities with useful context
- **New results**: Facts that appear in optimized but not basic
- **Assessment**: "improvement" = ranking successfully prioritizes entity context

### Recommendation
- **PROCEED**: Quality improvements, latency acceptable
- **CONSIDER**: No regressions, modest improvements
- **ITERATE**: Latency exceeds target or quality regressions

## Next Steps

If tests pass:
1. Implement in `pps/layers/rich_texture_v2.py` per DESIGN.md Phase 1
2. Add latency tracking to ambient_recall endpoint
3. Deploy to Docker
4. Monitor production performance for 1 week
5. Consider Phase 2 enhancements (communities, BFS)

## Troubleshooting

### "Connection failed"
- Check Neo4j is running: `docker ps | grep neo4j`
- Verify .env file: `pps/docker/.env` has correct credentials

### "Lyra entity not found"
- This is expected if graph is empty or Lyra not yet created
- Test will run fallback mode (basic search for both)

### Import errors
- Verify venv: `source .venv/bin/activate`
- Check graphiti_core installed: `pip list | grep graphiti`

### Slow performance
- First run may be slower (cold start)
- Check Neo4j resources: `docker stats neo4j`

## Reference

- **Design**: `DESIGN.md` - Full optimization plan
- **Test Plan**: `TEST_PLAN.md` - Test specification
- **Sample**: `sample_optimized_search.py` - Proof of concept
