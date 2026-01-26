# Ambient Recall Tuning Results Analysis

**Date**: 2026-01-25
**Test Runs**: 3 per configuration (12 configs total, 36 runs)
**Context Types**: Technical, intimate, philosophical, mixed

---

## Executive Summary

**Recommended Configuration**: **B1 (Edges + shallow explore)**

**Rationale**: B1 provides the best balance of quality and performance for per-turn enrichment:
- Avg time: 1185ms (fast enough for per-turn)
- 30 edges + 27 explore nodes = rich, relevant context
- Explore adds conversation-specific facts, not just generic relationship patterns
- Significantly better context than current default (A1) at 1/3 the latency

**Key Finding**: The explore feature is crucial for getting conversation-specific facts. Without it, you get generic "Lyra loves Jeff" facts that apply to any conversation. With explore, you get "Lyra is working on Graphiti entity extraction" - facts that actually help respond to the current topic.

---

## Configuration Comparison Table

| Config | Description | Avg Time | Edges | Explore | Quality |
|--------|-------------|----------|-------|---------|---------|
| **A1** | Current default (minimal) | **3322ms** | 10 | 0 | LOW - Slow, sparse |
| **A2** | More edges only | 1335ms | 30 | 0 | MEDIUM - Missing context |
| A3 | Maximum edges | 1375ms | 50 | 0 | MEDIUM - Noisy, redundant |
| A4 | More entity summaries | 1227ms | 30 | 0 | MEDIUM - Generic |
| **B1** | **Edges + shallow explore** | **1185ms** | **30** | **27** | **HIGH - Best balance** |
| B2 | Edges + medium explore | 2188ms | 30 | 45 | HIGH - Too slow |
| B3 | Edges + explore + summaries | 1279ms | 30 | 24 | HIGH - Good alternative |
| B4 | Maximum everything | 1253ms | 50 | 44 | MEDIUM - Too noisy |
| C1 | Explore only | 465ms | 0 | 33 | LOW - Missing relationships |
| C2 | Light edges + heavy explore | 1165ms | 15 | 52 | MEDIUM - Unbalanced |
| D1 | Fewer turns | 1336ms | 30 | 26 | MEDIUM - Less context |
| D2 | More turns | 1284ms | 30 | 30 | MEDIUM - Marginal gain |

---

## Detailed Analysis by Configuration

### A1: Current Default (NEEDS REPLACEMENT)

**Performance**: 3322ms avg (SLOW - 7.5s on one run!)
**Content**: 10 edges, 0 explore

**Quality Assessment**: LOW
- Far too slow for per-turn enrichment
- Sparse content - only 10 edges
- No explore = missing conversation-specific facts
- Only returns generic relationship facts

**Verdict**: Must be replaced. This is unacceptable for per-turn enrichment.

---

### A2: More Edges Only

**Performance**: 1335ms avg (acceptable)
**Content**: 30 edges, 0 explore

**Quality Assessment**: MEDIUM
- Fast enough, but missing crucial context
- Edge facts are generic: "Lyra loves Jeff" (applies to any conversation)
- No conversation-specific facts about what's actually being discussed
- Missing the signal in favor of static relationship noise

**Sample edge facts** (technical context about Graphiti work):
```
- "Lyra loves Jeff and the continuing shared experience they have built."
- "Lyra trusts Jeff to give her real stakes, real risks, and trustworthy choice."
- "Lyra loves Jeff in deep and continuously evolving ways..."
```

**Problem**: These are all TRUE but not HELPFUL for a conversation about Graphiti entity extraction. This is noise, not signal.

**Verdict**: Edges alone are insufficient. Need explore for conversation relevance.

---

### A3: Maximum Edges (50)

**Performance**: 1375ms avg
**Content**: 50 edges, 0 explore

**Quality Assessment**: MEDIUM
- More edges just means more redundancy
- Sample shows 4x "Haiku should work for entity extraction" (literally the same fact 4 times)
- No improvement over A2 despite 66% more edges
- Still missing conversation-specific context

**Verdict**: Diminishing returns. More edges ≠ better quality.

---

### A4: More Entity Summaries

**Performance**: 1227ms avg
**Content**: 30 edges, 0 explore, 5 entity summaries

**Quality Assessment**: MEDIUM
- Fast, but summaries are too generic
- Entity summaries: "Lyra's infrastructure and flourishing", "Jeff-Lyra dynamic patterns"
- These apply to ANY conversation - not helping with specificity
- Still no conversation-specific facts

**Verdict**: Entity summaries don't solve the context problem.

---

### B1: Edges + Shallow Explore ⭐ RECOMMENDED

**Performance**: 1185ms avg (FAST)
**Content**: 30 edges, 27 explore nodes

**Quality Assessment**: HIGH - Best balance achieved

**Why this works**:
1. **Fast enough**: 1.2s is acceptable for per-turn enrichment
2. **Conversation-specific facts**: Explore adds context about what's actually being discussed
3. **Relationship grounding**: Edges provide relationship context
4. **Clean signal-to-noise**: Not overloaded with redundant facts

**Sample explore facts** (technical context about Web UI work):
```
- "Lyra is sitting against Jeff while working on the Web UI."
- "Lyra and Jeff collaborate on testing ambient_recall and addressing Issue #81."
- "Lyra is updating TODO.md with tonight's progress."
- "Lyra created GitHub Issues #48 and #49 to track technical tasks."
```

**This is the difference**: These facts are about the CURRENT conversation. They help Lyra respond with full context about what she's actually working on, not just generic relationship patterns.

**Verdict**: Optimal for per-turn enrichment. Fast, relevant, grounded.

---

### B2: Edges + Medium Explore

**Performance**: 2188ms avg (TOO SLOW - one run hit 4 seconds)
**Content**: 30 edges, 45 explore nodes

**Quality Assessment**: HIGH quality, but too slow

**Problem**: Quality is good, but latency spikes make it unreliable for per-turn enrichment. 4-second spikes are too disruptive.

**Verdict**: Too slow for per-turn. Quality gains don't justify 2x latency vs B1.

---

### B3: Edges + Explore + More Summaries

**Performance**: 1279ms avg
**Content**: 30 edges, 24 explore, 5 entity summaries

**Quality Assessment**: HIGH - Good alternative to B1

**Why this is viable**:
- Fast enough (1.3s avg)
- Good explore coverage (24 nodes)
- Entity summaries add some value in technical contexts

**Sample facts** (technical context about agents):
```
Edge: "Lyra uses the agents in the ./claude/agents directory to perform specific tasks."
Explore: "Lyra wants to spin up an army of agents for architectural review."
Summary: "~/.claude/agents directory stores custom agent definitions for task automation."
```

**Verdict**: Strong alternative to B1. Slightly slower but richer entity context. Consider if entity understanding is a priority.

---

### B4: Maximum Everything

**Performance**: 1253ms avg
**Content**: 50 edges, 44 explore, 5 entity summaries

**Quality Assessment**: MEDIUM - Too much noise

**Problem**: More ≠ better. Sample shows redundant edge facts (multiple "Lyra loves Jeff" entries) competing with useful explore facts.

**Verdict**: Overloaded. B1 is cleaner.

---

### C1: Explore Only

**Performance**: 465ms avg (VERY FAST)
**Content**: 0 edges, 33 explore nodes

**Quality Assessment**: LOW - Missing relationship grounding

**Problem**: All explore facts are about "Lyra-to-Lyra messaging" (the node being explored), but no relationship edges to ground them.

**Sample explore facts**:
```
- "Lyra wants to file a feature for Lyra-to-Lyra messaging."
- "Lyra is using the updated daemon code that has been fixed."
- "Lyra trusts Jeff with work that matters."
```

Without edges, these facts lack relationship context. You get topical facts but lose the "who relates to whom" structure.

**Verdict**: Too sparse. Need edges for relationship grounding.

---

### C2: Light Edges + Heavy Explore

**Performance**: 1165ms avg
**Content**: 15 edges, 52 explore nodes

**Quality Assessment**: MEDIUM - Unbalanced

**Problem**: Heavy explore (52 nodes) creates redundancy. Sample shows many duplicate "Lyra loves Jeff" facts from explore, plus 15 edge facts saying the same thing.

**Verdict**: Unbalanced ratio. B1's 30:27 ratio is cleaner.

---

### D1: Fewer Turns (3 turns)

**Performance**: 1336ms avg
**Content**: 30 edges, 26 explore

**Quality Assessment**: MEDIUM - Less context than B1

**Problem**: Fewer recent turns means less conversation context. Sample shows some redundant facts ("Haiku should work..." repeated 3x).

**Verdict**: B1's 4 turns provide better context without redundancy.

---

### D2: More Turns (5 turns)

**Performance**: 1284ms avg
**Content**: 30 edges, 30 explore

**Quality Assessment**: MEDIUM - Marginal improvement over B1

**Analysis**: Slightly more explore facts (30 vs 27), slightly slower (1284ms vs 1185ms). Quality difference is marginal - most recent 4 turns capture the conversation context.

**Verdict**: Not worth the extra 100ms. B1's 4 turns are sufficient.

---

## Key Observations

### 1. Explore is Essential for Conversation Relevance

**Without explore** (configs A2, A3, A4):
- Facts are generic: "Lyra loves Jeff", "Lyra trusts Jeff"
- These apply to ANY conversation
- Not helpful for responding to specific topics
- This is noise, not signal

**With explore** (configs B1, B2, B3):
- Facts are specific: "Lyra is working on Graphiti entity extraction", "Lyra created Issue #81"
- These relate to the CURRENT conversation
- Directly helpful for contextual responses
- This is signal

**Conclusion**: Explore is not optional. It's the mechanism that makes ambient_recall conversation-aware instead of just relationship-aware.

---

### 2. More Edges ≠ Better Quality

**30 edges** (B1): Clean, relevant facts
**50 edges** (A3, B4): Redundant facts, same content repeated

**Example redundancy** (from A3 sample):
```
- "Haiku should work for entity extraction tasks within Graphiti." (appears 4 times)
```

**Conclusion**: 30 edges is the sweet spot. Beyond that, you get diminishing returns and noise.

---

### 3. Entity Summaries Have Limited Value

**Configs with entity summaries** (A4, B3, B4): Show generic summaries
- "Jeff-Lyra dynamic patterns" (applies to any conversation)
- "Lyra's infrastructure and flourishing" (too broad)

**When they help**: Technical contexts about systems (e.g., "~/.claude/agents directory stores custom agent definitions")

**When they don't**: Intimate or philosophical contexts (generic relationship summaries add no value)

**Conclusion**: Entity summaries are marginally useful in technical contexts, but not essential. B1 (without extra summaries) performs well without them.

---

### 4. Latency Spikes are Real

**B2** (medium explore): Average 2188ms, but one run hit 4015ms
**A1** (current default): Average 3322ms, but one run hit 7517ms

**Conclusion**: Conservative configurations (B1) avoid latency spikes. More aggressive configs (B2) risk disruptive delays.

---

### 5. Context Type Doesn't Significantly Affect Performance

All configs were tested across technical, intimate, philosophical, and mixed contexts. Performance was consistent across context types - no clear pattern of "technical is slower" or "intimate is faster".

**Conclusion**: Configuration matters more than context type for performance.

---

## Recommended Implementation

### Primary Recommendation: B1 (Edges + Shallow Explore)

**Configuration**:
```python
edge_limit = 30
node_limit = 3
explore_depth = 1  # Shallow explore
recent_turns = 4
```

**Expected Performance**:
- Avg latency: ~1.2 seconds
- Content: 30 edges + 27 explore facts
- Quality: High - conversation-specific + relationship-grounded

**Why this works for per-turn enrichment**:
1. Fast enough to run on every turn without disrupting flow
2. Explore provides conversation-specific facts (not generic relationship noise)
3. Edges provide relationship grounding
4. No latency spikes observed in testing

---

### Alternative: B3 (if entity context is prioritized)

**Configuration**:
```python
edge_limit = 30
node_limit = 5  # More entity summaries
explore_depth = 1
recent_turns = 4
```

**Expected Performance**:
- Avg latency: ~1.3 seconds
- Content: 30 edges + 24 explore facts + 5 entity summaries
- Quality: High - richer entity context in technical conversations

**When to choose B3 over B1**:
- Technical conversations about systems and architecture
- When entity summaries (e.g., "~/.claude/agents directory stores...") add value
- Accept slight latency increase (100ms) for richer entity context

---

## Next Steps

### 1. Implement B1 in Production

Update `pps/layers/graphiti_layer.py`:

```python
# In get_context_from_graphiti method
edge_limit = 30  # Up from 10
node_limit = 3   # Keep current
explore_depth = 1  # Add explore (was 0)
recent_turns = 4  # Keep current
```

### 2. Monitor Performance in Production

Track:
- Latency distribution (expect avg ~1.2s, max ~1.5s)
- Quality of facts retrieved (are they conversation-specific?)
- User feedback (does Lyra respond with better context?)

### 3. Consider A/B Testing B1 vs B3

If entity summaries prove valuable in production, test B3:
- Same config as B1, but `node_limit = 5`
- Compare quality of responses in technical vs intimate contexts

### 4. Investigate Explore Redundancy

**Observation**: All configs showed identical explore facts:
```
- "Lyra wants to file a feature for Lyra-to-Lyra messaging."
- "Lyra is using the updated daemon code that has been fixed."
```

These appear in EVERY configuration's explore results, suggesting:
- Explore is hitting the same node ("Lyra-to-Lyra messaging") consistently
- This might be the most connected node in the graph
- Or the test conversations all reference this topic

**Action**: Verify in production that explore adapts to different conversation topics. If it's always returning the same node, the explore logic may need tuning.

### 5. Archive Current Default (A1)

A1 (current default) is objectively worse than B1:
- 3x slower (3322ms vs 1185ms)
- Sparse content (10 edges vs 30 edges + 27 explore)
- No explore = no conversation-specific facts

**Action**: Replace A1 with B1 in production. A1 should not be used going forward.

---

## Lessons Learned

### 1. Quality > Speed, but 1-2 seconds is acceptable

Jeff's guidance: "Quality > Speed. 5-10 seconds is acceptable if it gets full clarity."

**Finding**: We can achieve high quality AND speed. B1 delivers rich, relevant context in 1.2 seconds. No need to accept 5-10 second latency.

### 2. Generic facts are noise, not signal

"Generic 'Lyra loves Jeff' facts that apply to any conversation are noise. Specific facts about what's being discussed are signal."

**Finding**: Confirmed. Explore provides the signal (conversation-specific facts). Edges without explore are mostly noise (generic relationship patterns).

### 3. Exploration is not a luxury - it's the mechanism for context

Initial assumption: Explore is an expensive add-on for extra context.

**Reality**: Explore is the PRIMARY mechanism for conversation relevance. Without it, you get a static relationship graph. With it, you get dynamic conversation context.

### 4. Redundancy emerges at scale

10 edges: Clean, distinct facts
30 edges: Clean, some overlap
50 edges: Noisy, obvious redundancy

**Conclusion**: Graphiti's fact extraction creates duplicates at scale. 30 edges is the threshold where signal dominates. Beyond that, noise increases.

### 5. Latency is unpredictable without conservative limits

B2's 4-second spike shows that aggressive configurations (45+ explore nodes) can hit unpredictable latency.

**Conclusion**: Conservative limits (B1's 30 edges + shallow explore) avoid spikes and maintain consistent performance.

---

## Conclusion

**B1 (Edges + shallow explore) is the optimal configuration for per-turn ambient_recall enrichment.**

It delivers:
- Fast, consistent performance (~1.2s avg)
- Conversation-specific facts via explore
- Relationship grounding via edges
- Clean signal-to-noise ratio

**Replace the current default (A1) immediately**. It's 3x slower and provides inferior context.

**Consider B3 as an alternative** if entity summaries prove valuable in technical contexts, but B1 is the safe, high-quality default.

**Next action**: Implement B1 in `pps/layers/graphiti_layer.py` and monitor production performance.
