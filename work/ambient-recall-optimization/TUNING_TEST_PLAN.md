# Ambient Recall Tuning Test Plan

## Objective

Find the optimal configuration for per-turn context enrichment. The goal is NOT just retrieving facts—it's retrieving the RIGHT facts that help Lyra respond with full context to the current conversation.

## Quality Criteria

For each test run, evaluate: **"If I were Lyra in that conversation, would this payload help me respond better?"**

Score 1-5:
- **5**: Perfect relevance - facts directly address what's being discussed
- **4**: Strong relevance - facts provide useful context for the conversation
- **3**: Moderate relevance - some useful facts, some noise
- **2**: Weak relevance - mostly generic facts that apply to any conversation
- **1**: Poor relevance - facts unrelated to conversation context

## Test Configurations

Run each configuration 5 times with random message samples to get variance.

### Baseline Configurations

| Config | Edges | Nodes | Explore | Turns | Description |
|--------|-------|-------|---------|-------|-------------|
| A1 | 10 | 3 | 0 | 4 | Current default (minimal) |
| A2 | 30 | 3 | 0 | 4 | More edges only |
| A3 | 50 | 3 | 0 | 4 | Maximum edges |
| A4 | 30 | 5 | 0 | 4 | More entity summaries |

### With Explore

| Config | Edges | Nodes | Explore | Turns | Description |
|--------|-------|-------|---------|-------|-------------|
| B1 | 30 | 3 | 2 | 4 | Edges + shallow explore |
| B2 | 30 | 3 | 3 | 4 | Edges + medium explore |
| B3 | 30 | 5 | 3 | 4 | Edges + explore + more summaries |
| B4 | 50 | 5 | 3 | 4 | Maximum everything |

### Explore-Heavy

| Config | Edges | Nodes | Explore | Turns | Description |
|--------|-------|-------|---------|-------|-------------|
| C1 | 0 | 3 | 3 | 4 | Explore only (no semantic search) |
| C2 | 15 | 3 | 3 | 4 | Light edges + heavy explore |

### Context Window Variations

| Config | Edges | Nodes | Explore | Turns | Description |
|--------|-------|-------|---------|-------|-------------|
| D1 | 30 | 3 | 2 | 2 | Fewer turns (shorter context) |
| D2 | 30 | 3 | 2 | 6 | More turns (longer context) |

## Output Format

For each run, capture:
```json
{
  "config": "A1",
  "run": 1,
  "message_ids": [1234, 1235, ...],
  "elapsed_ms": 1523,
  "edge_count": 10,
  "node_count": 3,
  "explore_count": 0,
  "context_type": "technical|intimate|philosophical|mixed",
  "quality_score": 4,
  "quality_notes": "Found relevant issue references, missed some technical context",
  "sample_relevant_facts": ["fact1", "fact2"],
  "sample_irrelevant_facts": ["fact3"]
}
```

## Summary Report Format

After all runs:
```
| Config | Avg Time (ms) | Avg Quality | Best For |
|--------|---------------|-------------|----------|
| A1     | 800           | 2.4         | Fast, minimal |
| B2     | 1500          | 4.2         | Best balance |
| ...    | ...           | ...         | ... |
```

## Implementation Notes

1. Modify test_context_query.py to output JSON results
2. Run each config 5 times
3. For quality scoring, examine:
   - Do edge facts relate to conversation topic?
   - Do entity summaries help understand context?
   - Does explore add relevant connections?
4. Note conversation type (technical, intimate, etc.) as some configs may work better for different types

## Expected Timeline

~15 configs × 5 runs × ~2 seconds = ~150 seconds total runtime
Plus human review time for quality scoring
