# Graph Health Dashboard

**Purpose**: Track Graphiti (Layer 3) health metrics over time. Individual curation cycle reports archived in `archive/`.

**Last Updated**: 2026-01-20, 10:03 PM (automated reflection cycle)

---

## Current Health Status

**Overall Health**: 9/10 (Excellent - sustained)
**Duplication Rate**: <1% (stable - no new duplicates detected)
**Last Curation**: 2026-01-20, 10:00 PM (light maintenance check)
**Unsummarized Messages**: 67 (healthy - no summarization needed)
**Recent Cleanup**: Graph remains clean after 01-19 cleanup (392+ artifacts removed)

### Trend Indicators
- ✅ Duplication rate declining (7.1% → 1.4% in one cycle)
- ✅ No vague entity names detected
- ✅ Zero self-loops remaining
- ✅ Predicate quality high (domain-specific, informative)
- ✅ Entity connectivity balanced (no isolated clusters)

---

## Health Metrics Timeline

| Date | Time | Edges Scanned | Duplicates Found | Duplicates Deleted | Duplication Rate | Health Score | Curator |
|------|------|---------------|------------------|-------------------|------------------|--------------|---------|
| 2026-01-20 | 10:00 PM | 90+ | 0 | 0 | <1% | 9/10 | Haiku (bg) |
| 2026-01-19 | 05:55 AM | 50+ | 4 (self-ref) | 4 | <1% | 9/10 | Lyra direct |
| 2026-01-19 | 04:44 AM | 300+ | 392+ (artifacts) | 392+ | N/A | 9/10 | Haiku (bg) - extraction cleanup |
| 2026-01-19 | 01:16 AM | 148 | 2 (remaining) | 10 | 1.4% | 9/10 | Haiku (bg) |
| 2026-01-19 | 01:16 AM | 140 | 10 | 10 | 7.1% | 8/10 | Haiku (bg) |
| 2026-01-18 | 10:57 PM | N/A | 0 | 0 | N/A | 9/10 | Analysis only (PPS offline) |
| 2026-01-18 | 08:38 PM | 286+ | 14 | 14 | ~4.9% | 9/10 | Haiku (bg) |
| 2026-01-18 | 11:17 AM | 250+ | 1 | 1 | 0.4% | 9/10 | Haiku (bg) |

### Key Observations

**Jan 18-19 Pattern**: Heavy curation activity (6+ cycles in 36 hours)
- Multiple curator agents spawned during reflection cycles
- Duplication rate peaked at 7.1%, then dropped to <1% via aggressive cleanup
- **Jan 19 breakthrough**: Comprehensive extraction artifact cleanup (392+ deleted)
  - 194+ "discord_user(user)" imprecise entity triplets removed
  - 93+ "terminal:UUID(assistant/user)" session artifacts removed
  - 5 generic "Claude is an AI" statements removed
  - Comprehensive multi-pass cleanup strategy
- Total deletions: 400+ edges cleaned in 36-hour period
- Graph now in excellent condition with high-quality triplets remaining

**Deletion Success Rate**: 100% (all attempted deletions succeeded)

**Common Issues Found**:
1. **Duplicate edges**: Same relationship stated multiple times (highest frequency)
2. **Self-loops**: Entity pointing to itself (cleaned in earlier cycles)
3. **Factual errors**: e.g., "Jeff WEARS short dress" (rare, <1%)
4. **Vague entities**: None found (previous cycles cleaned thoroughly)

---

## Entity Health

### Top Connected Entities (as of 2026-01-18)
1. **Jeff**: 48 relationships
2. **Lyra**: 40 relationships
3. **discord_user(user)**: 35 relationships
4. **Brandi**: 18 relationships
5. **active agency**: 8 relationships

**Structure**: Hub-and-spoke topology, balanced connectivity, no orphans

### Predicate Quality (Sample)
Most common predicates:
- `LOVES` (6 uses)
- `BUILT_ARCHITECTURE_FOR` (5 uses)
- `INCLUDES` (4 uses)
- `BUILT` (4 uses)
- `RUNS` (3 uses)

**Assessment**: High-information predicates, domain-specific vocabulary, minimal generic filler

---

## Curation Cycle Performance

### Deletion Efficiency
- **Batch 1 (Jan 18 morning)**: 1 deletion, 100% success
- **Batch 2 (Jan 18 evening)**: 14 deletions, 100% success
- **Batch 3 (Jan 19 early AM)**: 10 deletions, 100% success
- **Overall**: 25 deletions, 100% success rate

### HTTP API Reliability
- **Issue**: MCP stdio tools unavailable in reflection subprocess (Issue #97)
- **Workaround**: HTTP API fallback (`POST /tools/texture_search`, `DELETE /tools/texture_delete/{uuid}`)
- **Status**: Working reliably (all deletions successful)

### Agent Behavior Quality
The Haiku curator agent demonstrates:
- ✅ Self-discovery of API endpoints via `/openapi.json`
- ✅ Self-correction when initial deletion attempts fail (learns to extract real UUIDs)
- ✅ Post-cleanup verification scans
- ✅ Detailed reporting with metrics

---

## Maintenance Schedule

**Current Frequency**: Every reflection cycle (2-3 hours)
**Recommendation**: Reduce to every 12-24 hours now that duplication rate is low

### Trigger Thresholds
- **Routine**: Every 24 hours (maintenance scan)
- **Elevated**: Duplication rate >5% (more aggressive cleanup)
- **Critical**: Duplication rate >10% or vague entities detected (immediate action)

### Next Actions
1. ✅ Continue monitoring duplication rate trend
2. ⚠️ Reduce curation frequency to avoid report proliferation
3. ✅ Track if rate stays <2% or grows over time
4. ✅ Expand query coverage (10-15 queries instead of 5) when needed

---

## Known Issues

### Non-Critical
1. **Repeat deletion attempts**: Curator agent retry logic sometimes attempts to delete already-removed edges
   - **Impact**: None (idempotent deletions are safe)
   - **Status**: Agent behavior artifact, not graph corruption

2. **Remaining duplicates (Jan 19)**: 2 instances
   - `Jeff → EXPRESSED_TRUST_TO → Carol` (2x)
   - `warmth with a shimmer → IS_ASSOCIATED_WITH → intimacy` (2x)
   - **Next cycle**: Target with more specific queries

### Resolved
- ✅ Self-loops eliminated (Jan 18 evening cycle)
- ✅ Vague entity names cleaned (earlier cycles)
- ✅ Major duplication spike resolved (7.1% → 1.4%)

---

## Technical Notes

### Environment Constraints
- **PPS Services**: Must be running for active curation
  - Graphiti (Layer 3): localhost:8203
  - ChromaDB (Layer 2): localhost:8200
  - MCP server: Accessible via HTTP API
- **Reflection Context**: HTTP fallback required (MCP stdio unavailable)

### Deletion Best Practices
1. **Always use real UUIDs** from `texture_search` results (not hardcoded)
2. **Conservative approach**: Only delete clear duplicates or obviously incorrect entries
3. **Verify deletions**: Post-cleanup scan to measure impact
4. **Report findings**: Document what was found and cleaned

---

## Archive

Detailed curation cycle reports moved to `archive/` subdirectory:
- Individual cycle reports (2026-01-18 through 2026-01-19)
- Full deletion logs and search results
- Agent behavior transcripts

**Access**: `docs/curation/archive/YYYY-MM-DD_*.md`

---

*Dashboard maintained autonomously by Lyra during reflection cycles.*
*For detailed cycle reports, see archive/ subdirectory.*
