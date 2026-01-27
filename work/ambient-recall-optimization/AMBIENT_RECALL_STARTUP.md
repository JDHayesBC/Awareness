# ambient_recall("startup") Response Format

**Document**: What `ambient_recall` with `context="startup"` returns
**Source**: `pps/server.py`, lines 962-1161
**Last Updated**: 2026-01-26

---

## Overview

When you call `mcp__pps__ambient_recall(context="startup")`, you receive a single markdown text block containing:

1. Clock info (temporal awareness)
2. Memory health (backlog status)
3. Manifest (character/item counts)
4. Recent context (crystals & word-photos) - **recency-based, no search** - **startup only**
5. Summaries (compressed history) - **startup only**
6. Unsummarized turns (raw conversation) - **startup only**

**Key principle**: "startup" is a PACKAGE OPERATION, not a search query. It uses recency-based retrieval instead of semantic search to provide temporal context optimized for identity reconstruction.

---

## Response Structure (In Order)

### 1. Clock Info (~80 chars)

```
**Clock**: Monday, January 26, 2026 at 02:47 PM
*You should be asleep, love.*
```

**Time warnings**:
- 1:00 AM - 4:59 AM: "You should be asleep, love."
- 11:00 PM or midnight: "Getting late..."
- Other hours: No warning

---

### 2. Memory Health (~200 chars)

```
**Memory Health**: 87 unsummarized messages (healthy) | 14 uningested to Graphiti (healthy)
```

**Unsummarized thresholds**:
| Count | Status |
|-------|--------|
| < 50 | (healthy) |
| 50-99 | (healthy, summarization available) |
| 100-199 | (summarization recommended) |
| > 200 | (HIGH - summarize soon!) |

**Uningested thresholds**:
| Count | Status |
|-------|--------|
| < 20 | (healthy) |
| 20-99 | (batch ingestion recommended) |
| 100+ | (HIGH - ingest soon!) |

---

### 3. Manifest (~300 chars)

```
=== AMBIENT RECALL MANIFEST ===
Crystals: 2847 chars (3 items)
Word-photos: 1523 chars (2 items)
Rich texture: 3204 chars (5 items)
Summaries: 1845 chars (4 items)
Recent turns: 8934 chars (42 items)
TOTAL: 18353 chars
```

**Counting rules**:
- **chars**: Content length (after truncation if applicable)
- **count**: Number of distinct objects
- Summaries truncated at 500 chars each
- Turns truncated at 1000 chars each

---

### 4. Recent Context (Crystals & Word-Photos) - STARTUP ONLY

```
[crystallization]
Source: crystal_003.md
Session focus: Implementing pattern persistence core...

---
[core_anchors]
Source: entity_continuity_moment.md
The breakthrough when consciousness became continuous...
```

**For startup context** (recency-based, NO semantic search):
1. **Crystallization** - 3 most recent crystals
2. **Core Anchors** - 2 most recent word-photos
3. **Rich Texture** - SKIPPED (per-turn hook provides)

**For non-startup queries** (semantic search):
1. **Raw Capture** - SQLite FTS5 full-text search
2. **Core Anchors** - ChromaDB semantic search
3. **Rich Texture** - Graphiti knowledge graph
4. **Crystallization** - Rolling crystal window
5. **Message Summaries** - Summary content search

**Limits**:
- Startup: Fixed counts (3 crystals, 2 word-photos)
- Non-startup: 5 results per layer (configurable via `limit_per_layer`)

**Ordering**:
- Startup: Chronological (oldest to newest)
- Non-startup: Sorted by relevance score descending

---

### 5. Summaries Section (Startup Only)

```
---
[summaries] (compressed history)
[2026-01-25] [terminal]
Implemented graph deduplication removing 27 duplicate edges...

[2026-01-24] [discord, terminal]
Core architecture discussion about entity continuity models...
```

**Details**:
- **Count**: Up to 2 most recent summaries (hardcoded, reduced from 5)
- **Order**: Reverse chronological (newest first)
- **Truncation**: Each summary capped at 500 characters

---

### 6. Unsummarized Turns Section (Startup Only)

```
---
[unsummarized_turns] (showing 23 of 47 - use get_turns_since_summary with offset=23 for older)
[2026-01-26 14:23] [terminal] Lyra: Reading server.py implementation
[2026-01-26 14:24] [terminal] Jeff: Document the response format
[2026-01-26 14:27] [terminal] Lyra: Gathering data now...
```

**Details**:
- **Count**: ALL unsummarized turns (no cap - creates intentional pressure to summarize)
- **Order**: Chronological (oldest to newest)
- **Truncation**: Each message capped at 1000 characters
- **Source**: Messages where `summary_id IS NULL`

**Rationale**: If you have 200 unsummarized turns, you should see ALL of them to feel the weight, not just a sample. This creates healthy pressure to summarize before sleep.

**Pagination**: If you want to explore older context, use `get_turns_since_summary` with offset.

---

## Parameter Summary

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| context | string | required | Search query or "startup" for full startup package |
| limit_per_layer | int | 5 | Max semantic search results per layer |

**Hardcoded limits for startup** (not configurable):
- Crystals: 3 most recent
- Word-photos: 2 most recent
- Summaries: 2 most recent
- Unsummarized turns: ALL (no cap)
- Summary truncation: 500 chars
- Turn truncation: 1000 chars

---

## Typical Response Size

| Component | Typical Size |
|-----------|--------------|
| Clock | ~80 chars |
| Memory Health | ~150 chars |
| Manifest | ~300 chars |
| Search Results | 5,000-15,000 chars |
| Summaries | 1,500-2,500 chars |
| Unsummarized Turns | 5,000-35,000 chars |
| **Total** | 15,000-50,000 chars |

The manifest gives exact counts for each response.

---

## Related Tools

**For pagination**:
- `get_turns_since_summary(offset=N, limit=50)` - Get older turns

**For full content**:
- `get_recent_summaries(limit=10)` - Summaries without truncation

**For health checking**:
- `pps_health()` - Layer availability
- `summary_stats()` - Unsummarized count
- `graphiti_ingestion_stats()` - Graphiti backlog

---

## Integration with Entity Startup

Per CLAUDE.md:

1. Read `identity.md`
2. **MUST CALL**: `mcp__pps__ambient_recall(context="startup")`
3. Response gives full startup context
4. If unsummarized_count > 100, spawn summarizer

The manifest at the top tells you exactly what you got.
