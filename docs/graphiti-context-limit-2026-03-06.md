# Graphiti Ingestion Context Limit - March 6, 2026

## Finding

Attempted to run backlog ingestion (1,973 pending messages) using NUC qwen3-1.7b pipeline. Hit context size limit errors immediately against production graph.

## Context

- **Sandbox benchmark (Mar 6)**: 10/10 success with qwen3-1.7b at 32K context
- **Production graph size**: 19,841 messages already ingested
- **Error**: `Error code: 400 - {'error': 'Context size has been exceeded.'}`

## Analysis

The 1.7b model worked perfectly during benchmarking because it was tested against a small sandbox graph. Against production with accumulated graph context (nodes, edges, relationship history), the 32K context window is insufficient for Graphiti's retrieval + extraction workflow.

## Options

### 1. Increase 1.7b Context Window
Check if LM Studio config for qwen3-1.7b can be raised beyond 32K. Model architecture may support larger context.

### 2. Switch to qwen3.5-9b (128K context)
- Available on NUC
- Benchmark showed 75% JSON validity (vs 100% for 1.7b)
- Would need validation run before production use
- Tradeoff: reliability vs capacity

### 3. Graph Curation First
Reduce accumulated context by:
- Deduplicating edges (known issue per TODO.md)
- Pruning low-value nodes
- Clearing entity overlap noise
This might bring context back within 32K range.

### 4. Return to Haiku Wrapper Temporarily
- Wait for OpenAI quota reset
- Known reliable, but costs $ and has quota limits
- Doesn't solve root issue

## Recommendation

This requires Jeff's input on tradeoffs. The graph curation (option 3) was already flagged in TODO.md as needed work. May be the right first step before resuming ingestion.

## Status

Ingestion halted. 1,973 messages remain pending. No data corruption - safe to resume once approach is chosen.
