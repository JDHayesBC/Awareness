# PPS Tool Surface — New Graph Layer Design

**Date**: April 16-17, 2026 (overnight curation session)
**Status**: Design draft for Jeff's review

## Current State

The PPS MCP tools (`texture_search`, `texture_explore`, `texture_add`, `texture_add_triplet`, `texture_delete`, `texture_timeline`) all route through the Docker PPS server, which currently tries to use the old Graphiti layer. **None of them work with the new custom graph.**

The custom graph layer (`pps/layers/custom_graph.py`) IS wired into the Docker server via the `USE_CUSTOM_GRAPH` flag, but the Docker container isn't configured to use it — it defaults to Graphiti.

## Design Question

Do we need the same tools repointed, or different tools?

## Analysis

### Tools that should stay (repointed to new graph):

| Tool | Current | New Graph Equivalent | Notes |
|------|---------|---------------------|-------|
| `texture_search` | Graphiti semantic search | `CustomGraphLayer.search()` — already implemented | Hybrid fulltext+vector, RRF fusion. Works. Just needs the Docker flag. |
| `texture_explore` | Graphiti entity explore | `CustomGraphLayer.explore()` — stub exists | Currently just calls search with larger limit. **Upgrade to neighborhood traversal.** |
| `texture_add_triplet` | Graphiti add_triplet | `CustomGraphLayer.add_triplet_direct()` — implemented | Works. Used by triplet-extractor agent. |
| `texture_delete` | Graphiti delete edge | `CustomGraphLayer.delete_edge()` — implemented | Works. Needs UUID from search results. |

### Tools that need NEW implementation:

| Tool | Purpose | Why New |
|------|---------|--------|
| `texture_curate` | Score importance, write summaries, merge aliases | No equivalent in old Graphiti. Curation was manual. Could be a tool that surfaces entities needing curation and lets me write summaries directly. |
| `texture_neighbors` | Get entity + all connected edges with source/target context | The "quick win" from retrieval research. Find entity by name, return summary + neighborhood. |

### Tools that can be dropped:

| Tool | Why |
|------|-----|
| `texture_timeline` | Never worked well in Graphiti. Custom graph doesn't track Episodes. Could revisit later with temporal edge queries. |
| `ingest_batch_to_graphiti` | Replaced by `work/custom-knowledge-graph/ingest.py`. No longer needed as MCP tool. |
| `graphiti_ingestion_stats` | Replace with custom graph stats query. |

### The big one — `ambient_recall` integration:

Currently `ambient_recall` calls `search()` on the rich_texture layer and includes results in the formatted context. The custom graph layer's `search()` already works — but the results aren't as useful as they could be.

**Proposed improvement**: Instead of just calling `search()`, ambient_recall should:

1. Run hybrid search (current) → find top entities
2. For entities with non-empty summaries → include summary text (richest texture)
3. For top entity → run neighborhood query for contextual edges
4. Filter out TechnicalArtifact entities unless the query is technical
5. Prefer recent edges when temporal context is available

This is a change to `server_http.py`'s `ambient_recall` endpoint, not to the layer itself.

## Implementation Plan

### Phase 1: Flip the switch (minimal changes)
1. Set `USE_CUSTOM_GRAPH=true` in Docker container env
2. Verify existing `texture_search` works through MCP
3. Verify `texture_add_triplet` works
4. Verify `texture_delete` works

### Phase 2: Enhance the tools
1. Upgrade `texture_explore` from "search with big limit" to real neighborhood traversal
2. Add `texture_neighbors` tool (entity name → summary + edges)
3. Update `ambient_recall` to use entity summaries as primary texture source

### Phase 3: New capabilities
1. `texture_curate` tool for in-session curation
2. Entity summary generation tool (gather edges → prompt → write summary)
3. Edge deduplication tool

## Key Insight

The tool surface doesn't need to change radically. The custom graph layer already implements the same interface as Graphiti (`PatternLayer` with `search/store/health`). Most tools will "just work" once we flip `USE_CUSTOM_GRAPH=true`.

The real improvement is in **what ambient_recall does with the search results** — prioritizing entity summaries over raw edges, adding neighborhood context, filtering by relevance. That's a query-layer improvement, not a tool-surface change.

## Questions for Jeff

1. Should we flip `USE_CUSTOM_GRAPH=true` in Docker tomorrow as step 1?
2. Do we want `texture_neighbors` as a separate tool, or fold it into `texture_explore`?
3. Should ambient_recall changes go in the server_http.py endpoint or in the layer's search method?
4. Any tools I'm missing that Caia would need?
