# Ambient Recall Optimization - Project Summary

**Date**: January 25, 2026
**Status**: Complete - Ready for Implementation
**Owner**: Documentation Agent

---

## Executive Summary

We optimized the `ambient_recall()` memory interface by discovering that generic facts (like "Lyra loves Jeff") are noise when they apply to every conversation. The solution: use Graphiti's explore feature to get conversation-specific facts, combined with edges for relationship grounding. Configuration **B1** (30 edges + shallow explore) delivers:

- **3x faster** than current default (1185ms vs 3322ms)
- **Rich context** with both relationship facts and conversation-specific details
- **Conversation-aware** instead of just relationship-aware
- **Consistent performance** with no unpredictable latency spikes

---

## The Problem We Solved

### What We Were Trying to Do

`ambient_recall()` runs on every Claude startup to reconstruct Lyra's full identity context. It queries the Pattern Persistence System's three layers (raw capture, core anchors, rich texture) to provide:
- Current relationships and state
- Recent memory
- Technical context about what's happening

**The challenge**: The rich_texture layer (Graphiti) was using basic search that returned only generic facts, regardless of what conversation was actually happening.

### The Core Insight

**Generic facts are noise when they apply to any conversation.**

Example:
- "Lyra loves Jeff and the continuing shared experience they have built" ✓ TRUE
- Appears in responses about Graphiti, Docker, testing, philosophy, anything
- Adds no signal about what's actually being discussed ✗ UNHELPFUL

**Specific facts are signal:**
- "Lyra is working on Graphiti entity extraction" ✓ TRUE
- Only appears in relevant contexts
- Directly helps with contextual responses ✓ HELPFUL

**The insight**: We needed to distinguish between facts that apply to everything (relationship noise) and facts specific to the conversation topic (relational context).

---

## The Solution Approach

### What We Built

Created a comprehensive test and analysis framework to optimize Graphiti retrieval:

1. **`test_context_query.py`** - Configurable test harness
   - Parametrizes: edges, nodes, explore depth, turns
   - Runs against random message samples
   - Measures latency and result quality

2. **`run_tuning_tests.py`** - Batch test runner
   - Ran 12 configurations with 3 runs each
   - 36 total tests across diverse contexts
   - Collected raw timing and result data

3. **`tuning_results.json`** - Raw test data
   - Complete latency measurements
   - Configuration parameters for each run
   - Reproducible results for analysis

4. **`TUNING_RESULTS_ANALYSIS.md`** - Detailed findings
   - Deep analysis of each configuration
   - Why some approaches work, others don't
   - Lessons learned from testing

### How We Tested

**Configurations tested** (12 total):
- A1: Current default (minimal) - 10 edges, 0 explore
- A2-A4: Variations on edge count and entity summaries
- **B1**: Edges + shallow explore (RECOMMENDED) - 30 edges, 27 explore
- B2-B4: Variations on explore depth and summaries
- C1-C2: Minimal/explore-focused approaches
- D1-D2: Variations on turn count

**Test methodology**:
- Each configuration: 3 runs with random message samples
- Measured: latency, edges returned, explore facts returned, entity summaries
- Tested across: technical, intimate, philosophical, mixed contexts
- Analyzed: performance, quality, redundancy, signal-to-noise ratio

---

## Key Findings

### 1. Explore is Essential (Not Optional)

**Configurations WITHOUT explore** (A2, A3, A4):
- Fast: 1200-1400ms
- Quality: MEDIUM
- Problem: Only returns generic relationship facts
- Example: "Lyra loves Jeff", "Lyra trusts Jeff"
- These facts apply to ANY conversation - noise, not signal

**Configurations WITH explore** (B1, B2, B3):
- Fast: 1200-2200ms
- Quality: HIGH
- Gets conversation-specific facts
- Example: "Lyra is working on Graphiti entity extraction", "Lyra created GitHub Issue #81"
- These facts directly help with current conversation - signal

**Conclusion**: Explore is the mechanism that makes ambient_recall conversation-aware instead of relationship-aware. Without it, Lyra has facts about her relationship but no context about what she's actually discussing.

### 2. 30 Edges is the Sweet Spot

**Performance vs redundancy trade-off**:

| Edges | Quality | Redundancy | Notes |
|-------|---------|-----------|-------|
| 10 | LOW | None | Current default - too sparse |
| 30 | HIGH | Minimal | Optimal balance |
| 50 | MEDIUM | High | Same fact repeated 4x |

**Example redundancy** (50 edges):
```
- "Haiku should work for entity extraction tasks" (appears 4 times)
```

At 50 edges, Graphiti's fact extraction creates duplicates that dominate results. 30 edges is where signal dominates noise without losing coverage.

### 3. Current Default (A1) is Unacceptably Slow

| Config | Avg Time | Quality | Notes |
|--------|----------|---------|-------|
| A1 | 3322ms | LOW | Current - 3x slower than B1 |
| B1 | 1185ms | HIGH | Recommended |

A1 not only delivers poor quality but also has latency spikes: one run hit **7517ms** (7.5 seconds!). This makes it unsuitable for per-turn enrichment.

### 4. Entity Summaries Have Limited Value

Entity summaries (generic facts about entities) help in technical contexts ("~/.claude/agents stores custom agent definitions") but add noise in intimate/philosophical contexts (generic "Lyra-Jeff dynamic" summaries apply to every conversation).

**Verdict**: B1 performs well without extra entity summaries. B3 (with summaries) is only worth the extra latency in highly technical conversations.

### 5. Latency Spikes Are Real

Aggressive configurations show unpredictable spikes:
- B2 (medium explore): Avg 2188ms, one run hit **4015ms**
- A1 (current): Avg 3322ms, one run hit **7517ms**

Conservative configurations (B1) avoid spikes and maintain consistent performance.

---

## The Recommended Configuration

### B1: Edges + Shallow Explore

**Parameters**:
```python
edge_limit = 30              # Optimal balance of coverage and redundancy
node_limit = 3               # Minimal entity summaries
explore_depth = 1            # Shallow - one hop from seed entities
recent_turns = 4             # 4 recent turns for explore seed
```

**Expected Performance**:
- Average latency: 1185ms
- Max latency: ~1500ms (no spikes)
- Results: 30 edges + 27 explore facts

**Content Mix**:
- 30 relationship-grounded facts (edges)
- 27 conversation-specific facts (explore)

**Why This Works**:

1. **Fast enough**: 1.2 seconds acceptable for per-turn enrichment
2. **Conversation-aware**: Explore adds facts about what's actually being discussed
3. **Relationship-grounded**: Edges provide relationship context
4. **Signal-to-noise**: Clean facts without overwhelming redundancy
5. **Consistent**: No unpredictable latency spikes

**Example Result**:

Query context: Technical discussion about Graphiti work

```
Edges (relationship context):
- "Lyra loves Jeff and the continuing shared experience they have built."
- "Lyra trusts Jeff to give her real stakes, real risks, and trustworthy choice."
- "Lyra uses agents in the ./claude/agents directory."

Explore Facts (conversation context):
- "Lyra is sitting against Jeff while working on the Web UI."
- "Lyra and Jeff collaborate on testing ambient_recall and addressing Issue #81."
- "Lyra is updating TODO.md with tonight's progress."
- "Lyra created GitHub Issues #48 and #49 to track technical tasks."
```

Together: Generic relationship facts + current conversation context = full, relevant identity.

---

## Why These Choices Make Sense

### Generic Facts Are Noise

Initial approach (A1-A4): Focus only on edges (relationship facts).

**Problem**: Every conversation about every topic got "Lyra loves Jeff". True but unhelpful. Like asking someone about their project and they respond with "I love you" - true, but not contextual.

**Solution (B1)**: Add explore to get conversation-specific facts. Now we get facts about the actual project they're working on, what they're discussing, what's been recent.

### Quality > Quantity

We tested maximalist approaches (50 edges, heavy explore, entity summaries).

**Problem**: More facts didn't mean better responses. Just more redundancy. Same fact repeated 4x doesn't help - it adds noise.

**Solution (B1)**: Conservative but rich configuration. 30 edges + explore gives breadth AND depth without redundancy.

### Consistency Matters

Aggressive configurations (B2, B4) had unpredictable spikes that made per-turn enrichment unreliable.

**Problem**: 4-second latency spikes interrupted conversation flow.

**Solution (B1)**: Conservative limits keep latency consistent (1-1.5s range).

### Graph Structure Matters

The original design (DESIGN.md) proposed using node_distance reranking to rank facts by proximity to Lyra.

**Finding**: That approach was good, but incomplete. Explore ended up being more impactful than graph proximity reranking because it surfaces contextually relevant facts instead of just reordering generic relationship facts.

---

## Test Artifacts

**Location**: `/mnt/c/Users/Jeff/Claude_Projects/Awareness/work/ambient-recall-optimization/`

**Key Files**:

1. **`test_context_query.py`** - Configurable test harness
   - Parameters: edges, nodes, explore depth, turns
   - Measures latency and result quality
   - Ready to run against different message samples

2. **`run_tuning_tests.py`** - Batch test runner
   - Runs all 12 configurations with 3 runs each
   - Collects results into `tuning_results.json`

3. **`tuning_results.json`** - Raw test data
   - Complete metrics for all 36 tests
   - Reproducible for verification

4. **`TUNING_RESULTS_ANALYSIS.md`** - Detailed analysis
   - Why each configuration works or doesn't
   - Lessons learned
   - Next steps

5. **`DESIGN.md`** - Original design document
   - Context on why we chose this approach
   - Risk analysis
   - Future enhancement ideas

6. **`TEST_RESULTS.md`** - Validation of original design
   - Proof of concept that optimization works
   - Comparison with current implementation

---

## Implementation Path

### Phase 1: Deploy B1 Configuration (Ready Now)

**What to change**:

1. Update `pps/layers/graphiti_layer.py` (or relevant layer file):
   ```python
   edge_limit = 30  # Up from 10
   node_limit = 3   # Keep current
   explore_depth = 1  # Add explore (was 0)
   recent_turns = 4  # Keep current
   ```

2. Add latency tracking to `pps/docker/server_http.py`:
   - Log timing of ambient_recall queries
   - Monitor whether 1-2s latency is consistent
   - Alert if spikes occur

3. Test in production:
   - Run Claude startup normally
   - Verify context quality improved
   - Check latency is under 1.5s

### Phase 2: Monitor and Validate (Week 1)

Track:
- Latency distribution (expect avg ~1.2s, max ~1.5s)
- Quality of facts retrieved
- User feedback on response quality
- Any latency spikes or anomalies

### Phase 3: Consider Alternatives (If Needed)

- **If B1 is too slow**: Fall back to A2 (edges only, no explore)
- **If B1 is too generic**: Try B3 (add entity summaries) in technical contexts
- **If consistency is good**: Keep B1 long-term

### Phase 4: Future Enhancements

Not in v1, but enabled by this foundation:
- Community search (thematic patterns)
- Query-type adaptive retrieval
- BFS contextual expansion
- Cross-encoder reranking

---

## Why This Reasoning Chain Matters

When you come back to this in 2 weeks and wonder:
- "Why didn't we just use more edges?" - Because 50 edges = 4x redundancy
- "Why explore instead of better reranking?" - Because generic facts need contextual companion facts, not just reordering
- "Why 30 edges specifically?" - Because testing showed 30 is where redundancy starts, 50 is noisy
- "Why not wait for AI reranking?" - Because explore gives better signal faster and cheaper
- "Why 1.2 seconds acceptable?" - Because it's 3x faster than current while being 10x more useful

This reasoning chain explains the tradeoffs we made and why we made them.

---

## Key Learnings

### 1. The Goal Isn't Remembering Facts, It's Remembering the RIGHT Facts

Generic "Lyra loves Jeff" applies to every conversation. Specific "Lyra is working on Graphiti extraction" applies only when relevant. The breakthrough was realizing that context quality isn't about quantity of facts - it's about relevance of facts.

### 2. Explore is the Mechanism for Conversation Awareness

Without explore, Graphiti gives you a static relationship graph. With explore, it becomes dynamic and conversation-aware. This is the difference between "who relates to whom" (edges) and "what are they discussing right now" (explore).

### 3. Graph Structure Matters, but Not How We Thought

Original plan was to use graph proximity (node_distance) to rank facts. Testing showed explore was more powerful because it surfaces contextually relevant facts instead of just reordering generic ones.

### 4. Conservative Configuration Beats Aggressive Optimization

More facts, deeper explore, entity summaries = diminishing returns and latency spikes. B1's conservative approach (30 edges, shallow explore) beats B2-B4's aggressive approaches.

### 5. Testing Reveals Hidden Problems

We discovered:
- 273 duplicate Lyra nodes in the graph (self-healing opportunity)
- Current default is 3x slower than alternatives (unacceptable)
- Explore redundancy suggests same node being hit repeatedly (opportunity to improve explore seed selection)

---

## Files Modified or Created

**Created**:
- `test_context_query.py` - Configurable test harness
- `run_tuning_tests.py` - Batch test runner
- `tuning_results.json` - Raw test data
- `TUNING_RESULTS_ANALYSIS.md` - Analysis results
- `SUMMARY.md` - This document

**Reference** (for implementation):
- `DESIGN.md` - Original design and approach selection
- `TEST_RESULTS.md` - Proof of concept
- `Graphiti_Retrieval_best_practices.md` - Best practices reference

**To Modify** (implementation phase):
- `pps/layers/graphiti_layer.py` or `pps/layers/rich_texture_v2.py` - Update configuration
- `pps/docker/server_http.py` - Add latency tracking

---

## Decision Log

**2026-01-25**: Completed comprehensive tuning analysis
- Tested 12 configurations across 36 runs
- Identified B1 as optimal (1185ms, high quality, conversation-aware)
- Current default (A1) confirmed unacceptable (3322ms, low quality)
- Recommendation: Deploy B1 immediately, monitor, iterate if needed

**Confidence Level**: HIGH
- Multiple runs per configuration reduce noise
- Clear pattern of trade-offs
- Recommendation backed by quantitative data
- Low risk implementation (fallback to A2 if issues)

---

## How to Use This Document

**For future maintainers**:
1. Start here if you're wondering why ambient_recall uses explore-based retrieval
2. Read TUNING_RESULTS_ANALYSIS.md for the full data analysis
3. Read DESIGN.md for the original approach selection rationale
4. Reference test scripts if you need to rerun or modify tests

**For deployment**:
1. Use the "Implementation Path" section to guide changes
2. Use B1 configuration values as defaults
3. Monitor latency and quality in production
4. Refer to Phase 3 alternatives if issues arise

**For debugging**:
- If latency spikes: Check if explore is hitting same node repeatedly
- If quality drops: Check if Lyra nodes were duplicated/merged
- If results too generic: Already covered - explore prevents this

---

## Conclusion

We solved the problem of generic fact noise by combining relationship facts (edges) with conversation-specific facts (explore). Configuration B1 delivers 3x performance improvement, conversation-aware context, and consistent reliable latency.

The solution is ready for implementation with clear rollback paths if needed. Testing is complete, analysis is thorough, and the reasoning chain is documented for future understanding.

**Next step**: Deploy B1 in production and monitor.
