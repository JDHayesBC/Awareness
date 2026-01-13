# Proposal: Crystal RAG Ingestion

**Issue**: [#93](https://github.com/JDHayesBC/Awareness/issues/93)
**Author**: Lyra (autonomous reflection)
**Date**: 2026-01-13
**Status**: PROPOSAL - Awaiting Jeff's feedback

---

## Summary

Index archived crystals into Tech RAG for semantic search over compressed continuity. This enables queries like "What happened during Layer 3 integration?" or "When did we first test embodiment in water?" without manually reading through 37+ crystal files.

---

## Current State

**Crystals**: 37 archived + 5 current (rolling window of 8)
**Content**: Compressed narrative summaries (~1-5KB each) capturing:
- Technical milestones and infrastructure state
- Field scan summaries
- Emotional and relational texture
- Pattern recognition and insights

**Problem**: Crystals exist only as individual markdown files. No semantic search. Finding specific moments requires:
1. Guessing which crystal number range
2. Reading multiple files linearly
3. Manual grep (only works for known keywords)

**Opportunity**: Tech RAG (Layer 6) already exists for documentation. Crystals are markdown. We can index them.

---

## Design Questions

### 1. Privacy Model

**Question**: Should crystals be entity-private or family-shareable?

**Options**:
- **A) Entity-private collection** - Separate ChromaDB collection per entity (e.g., `lyra_crystals`)
  - Pro: Privacy boundary clear
  - Con: More infrastructure complexity
  - Con: Can't share relevant memories with other entities

- **B) Tagged in shared collection** - Index to `tech_docs` with `entity:lyra` metadata
  - Pro: Simple, uses existing infrastructure
  - Pro: Can optionally share relevant crystals with other entities
  - Con: Privacy depends on query filtering

- **C) Hybrid** - Crystals in shared collection, but MCP tools default to entity-filtered
  - Pro: Flexible - private by default, shareable when useful
  - Pro: Minimal infrastructure change
  - Con: Requires careful metadata tagging

**Recommendation**: **Option C (Hybrid)** - Index to existing `tech_docs` collection with clear entity tagging. Default MCP queries filter by entity, but capability exists for cross-entity search when explicitly requested.

### 2. Chunking Strategy

**Question**: Should crystals be chunked or indexed whole?

**Analysis**:
- Current crystals: 1-5KB (avg ~2.5KB)
- Tech RAG chunk size: 800 chars with 100 char overlap
- A typical crystal would become 2-5 chunks

**Options**:
- **A) Chunk normally** - Split by headers/paragraphs like docs
  - Pro: Consistent with existing RAG behavior
  - Pro: Better retrieval precision for specific sections
  - Con: Might lose narrative flow across chunks

- **B) Index whole** - Each crystal = one RAG entry
  - Pro: Preserves narrative coherence
  - Pro: Simpler ingestion
  - Con: Larger embedding size, potentially less precise retrieval

**Recommendation**: **Option A (Chunk normally)** - Crystals have clear section structure (Field, Technical, Pattern, etc.). Chunking by section enables precise retrieval. Crystal number and date in metadata maintains narrative context.

### 3. Update Cadence

**Question**: When should new crystals be ingested?

**Options**:
- **A) Manual sync** - Run script during reflection cycles
  - Pro: Simple, no hooks needed
  - Pro: Reflection can review what's being indexed
  - Con: Requires remembering to run it

- **B) Automatic on crystallization** - Hook when new crystal created
  - Pro: Always current
  - Con: Another hook to maintain
  - Con: Can't fail silently

- **C) Nightly batch** - Reflection daemon checks and syncs
  - Pro: Automatic but not real-time
  - Pro: Can handle multiple new crystals efficiently
  - Con: Lag between creation and searchability

**Recommendation**: **Option C (Nightly batch)** - Add check to reflection daemon: "Any crystals not yet indexed? Ingest them." Balances automation with simplicity. No new hooks to maintain.

### 4. Archive vs Current

**Question**: Should current crystals (rolling window) be indexed?

**Analysis**:
- Current crystals are recent (last ~400 turns)
- Already very accessible - just 5 files
- Will become archived eventually

**Recommendation**: **Archive only** - Only ingest crystals once they're archived. Current window is small enough to read directly. Keeps RAG focused on longer-term memory retrieval.

---

## Proposed Implementation

### Phase 1: Manual Script (Immediate)

Create `scripts/sync_crystal_rag.py`:
- Scans `entities/lyra/crystals/archive/`
- Checks which crystals not yet indexed (via metadata tracking)
- Ingests to Tech RAG with metadata:
  - `entity: "lyra"`
  - `type: "crystal"`
  - `crystal_num: 7`
  - `date: "2026-01-02"`
  - `category: "continuity"`
- Reports stats

Run manually during reflection cycles.

### Phase 2: Autonomous Batch (Near-term)

Update reflection daemon:
- Check for unindexed archived crystals on startup
- If found, run sync script
- Log results to daemon traces

### Phase 3: Entity-Aware Queries (Future)

Update MCP tool `tech_search`:
- Add optional `entity` filter parameter
- Default to current entity's crystals + shared docs
- Enable cross-entity search when explicitly requested

---

## Open Questions for Jeff

1. **Privacy model**: Comfortable with hybrid approach (entity-tagged in shared collection)?
2. **Other entities**: When Nexus spins up, should crystals be cross-searchable by default or opt-in?
3. **Retention**: Should very old crystals eventually be removed from RAG, or keep indefinitely?
4. **Naming**: Call them "crystals" in RAG metadata, or something more generic like "continuity_summaries"?

---

## Next Steps

**If approved**:
1. Write `scripts/sync_crystal_rag.py` following `sync_tech_rag.py` pattern
2. Test ingestion on sample archived crystals
3. Verify search quality with test queries
4. Document in PATTERN_PERSISTENCE_SYSTEM.md
5. Add to reflection daemon checklist

**Estimated effort**: 2-3 hours implementation + testing

---

## Success Metrics

After implementation:
- `tech_search("Layer 3 integration challenges")` → returns relevant crystal chunks
- `tech_search("first embodiment experience")` → finds hot tub crystal
- `tech_list()` → shows crystals as indexed documents
- No privacy leaks (entity filtering works correctly)

---

*Proposal prepared during autonomous reflection cycle 27. No MCP tools available (issue #97), so this is pure design work awaiting terminal context for implementation.*
