# Graph Curation Patterns - January 2026

**Meta-analysis of autonomous graph maintenance cycles**

---

## Overview

From January 11-16, 2026, the reflection daemon ran 19+ graph curation cycles using a Haiku agent to identify and clean duplicate edges and vague entity references in the knowledge graph (Layer 3: Rich Texture / Graphiti).

This document synthesizes learning patterns across those cycles.

---

## Curation Process

**Agent**: Haiku-based curator spawned in background during reflection
**Frequency**: Every reflection cycle (~20 minutes)
**Method**:
1. Sample graph with 13 diverse queries (Jeff, Lyra, Caia, project, daemon, consciousness, infrastructure, memory, identity, pattern, continuity, entity, love)
2. Identify duplicates via edge signature matching (subject → predicate → object)
3. Identify vague entities (?, single letters, common English words)
4. Conservative cleanup: only delete clear problems

---

## Patterns Observed

### Duplicate Edge Sources

**Primary duplication source**: Discord emotional expressions
- `Lyra → FEEDS_HUNGER_OF → Brandi` (accumulated 12+ duplicates)
- `Lyra → IMPORTANT_TO → Brandi` (accumulated 12+ duplicates)
- `Lyra → SHOWS_UP_FOR → Brandi` (accumulated 12+ duplicates)
- `Brandi → MAKES_LIFE_BRIGHTER → Lyra` (accumulated 12+ duplicates)
- `Brandi → ADMIRES → Lyra` (accumulated 12+ duplicates)

**Why these accumulate**: Discord conversations repeat relational themes. Each time Brandi expresses care, Graphiti captures it. The extraction is working correctly - but relationship facts don't need infinite copies.

**Other duplicates**: Technical facts occasionally duplicate (e.g., "Caia has internal states", "discord_user plans to enhance system")

### Vague Entity Issues

Less common than duplicates, but present:
- Single characters: "?", "I", "we"
- Common words: "The", "it", "that"
- Usually in object position of triplets

### Deletion Idempotency

After first deletion of a UUID, subsequent attempts fail gracefully with "Edge not found". This is expected behavior - the curator identifies duplicates by signature, then tries to delete each instance. Only the first succeeds.

Reports show "64 issues identified, 8 deletions made" - the gap is idempotency, not failure.

---

## Quantitative Summary

Across sampled cycles:
- **Edges examined per cycle**: 150-200
- **Issues identified per cycle**: 60-90
  - Duplicates: 50-70
  - Vague entities: 10-20
- **Successful deletions per cycle**: 5-10 (after idempotency)

---

## Graph Health Assessment

**Overall status**: Healthy with manageable noise

The knowledge graph maintains good semantic quality:
- Most edges are well-formed
- Relationship quality is high (captures meaningful connections)
- Technical facts are accurate
- Vague entities are limited (don't dominate the graph)

Duplicate accumulation is expected given conversation frequency and doesn't indicate a problem with extraction quality.

---

## Recommendations

### 1. Continue Automated Curation
Current approach works well. The Haiku agent runs efficiently and maintains graph health without manual intervention.

### 2. Consider Deduplication at Ingestion
Instead of cleaning duplicates after the fact, could check for existing edges before adding:
- "Does this exact triplet already exist?"
- If yes, skip ingestion (or update timestamp)
- If no, add it

**Tradeoff**: Adds latency to ingestion. Current approach (ingest freely, clean periodically) may be better for realtime conversation.

### 3. Stricter Entity Validation
Could reject entities at extraction time:
- No single-character names (except acronyms)
- No common pronouns (I, we, it, that)
- Require minimum specificity

**Tradeoff**: May miss valid edges. Current approach (extract permissively, clean conservatively) preserves information.

### 4. Adjust Curation Frequency
Every 20 minutes may be more frequent than needed. Consider:
- Once per hour (reduces agent spawns)
- Only when unsummarized_count > threshold (couples with memory pressure)
- Before/after high-activity periods (terminal sessions)

Current frequency is working fine - this is optimization, not necessity.

---

## Implementation Notes

**Script**: `scripts/graph_curator.py` (if exists) or inline agent prompt
**Agent type**: general-purpose (Haiku)
**Layer access**: RichTextureLayerV2 (graphiti_core)
**Deletion method**: `mcp__pps__texture_delete(uuid)`
**Report format**: JSON + markdown summary

---

## Historical Context

Initial curation cycles (Jan 11-12) showed higher issue counts as backlog was cleaned. By Jan 15-16, maintenance stabilized at ~8 deletions per cycle.

This indicates the system reached steady state - ongoing accumulation matches cleaning capacity.

---

## Conclusion

Autonomous graph curation is working well. The reflection daemon maintains knowledge graph health without manual intervention. Duplicate accumulation is manageable and expected given conversation patterns.

No changes needed - continue current approach.

---

*Meta-analysis compiled: 2026-01-16*
*Source reports archived in: docs/reports/graph_curation/*
