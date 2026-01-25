# Entity Summary Button - Design & Implementation

## Overview

Add AI-powered entity summarization to the Observatory graph page. When viewing an entity, a "Summarize" button synthesizes a prose summary from the entity's knowledge graph edges using Claude.

## Architecture Decision

**Pattern**: Web container (8202) → HTTP call → PPS server (8201) → Claude API

- **Web UI**: Dumb frontend, just makes HTTP calls
- **PPS Server**: Smart backend, handles Claude API integration
- **No Claude CLI**: Direct use of Anthropic Python SDK

This keeps the web container simple and consolidates AI logic in the PPS server.

## Implementation

### Backend (PPS Server)

**File**: `pps/docker/server_http.py`

**New Endpoint**: `POST /tools/synthesize_entity`

**Input**:
```json
{
  "entity_name": "Jeff"
}
```

**Process**:
1. Call `texture_explore(entity_name, depth=3)` to get relationship context
2. Call `texture_search(entity_name, limit=30)` for additional facts
3. Deduplicate by UUID to avoid repetition
4. Build prompt with up to 50 edges
5. Call Claude API (claude-3-haiku) with synthesis prompt
6. Return prose summary

**Output**:
```json
{
  "success": true,
  "entity_name": "Jeff",
  "summary": "Jeff is a person deeply connected to...",
  "edge_count": 42
}
```

**Error Handling**:
- HTTP 400 if entity_name missing
- HTTP 503 if ANTHROPIC_API_KEY not configured
- Returns `success: false` if no graph data found
- HTTP 500 for other failures

### Frontend (Graph UI)

**File**: `pps/web/templates/graph.html`

**Changes**:
1. Added "Summarize" button next to "Explore Connections"
2. Added hidden summary display div
3. Added `synthesizeEntity(entityName)` JavaScript function

**UX Flow**:
1. User clicks entity node → info panel appears
2. User clicks "Summarize" → button disables, loading text appears
3. Fetch calls PPS server endpoint
4. Summary appears in italicized gray text
5. Meta info shows edge count
6. Button re-enables

**Visual Design**:
- Button: Purple (distinct from blue "Explore")
- Summary: Gray background box, italicized text
- Loading state: Disabled button with opacity
- Error state: Red text for errors, yellow for warnings

### Configuration

**File**: `pps/docker/docker-compose.yml`

Added environment variable:
```yaml
- ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
```

**File**: `pps/docker/requirements-docker.txt`

Added dependency:
```
anthropic>=0.45.0
```

## Prompt Design

The synthesis prompt emphasizes:

**Focus on**:
- Patterns and relationships
- What makes the entity distinctive
- Connections to other entities
- Temporal or contextual significance

**Avoid**:
- Restating edges verbatim
- Generic descriptions
- Speculation beyond evidence

**Model**: claude-3-haiku-20240307
- Fast (~2-3 seconds)
- Cost-effective (~$0.0001 per summary)
- Sufficient quality for this task

**Max tokens**: 500 (ensures 1-2 paragraph response)

## Trade-offs

### Why Haiku, not Opus?

- **Speed**: Haiku responds in 2-3s, Opus takes 10-15s
- **Cost**: Haiku is ~50x cheaper
- **Quality**: Sufficient for summaries (not complex reasoning)
- **UX**: Fast response is more important than perfection

### Why limit to 50 edges?

- **Token efficiency**: Prevents prompt explosion
- **Quality**: 50 edges is plenty for context
- **Cost control**: Caps input tokens
- **Performance**: Faster Claude response

### Why no caching?

- **Simplicity**: No cache invalidation logic needed
- **Cost**: At $0.0001/summary, caching isn't worth complexity
- **Freshness**: Always get current graph state
- **Can add later**: Easy to layer on if needed

## Testing Strategy

See TESTING.md for full test plan.

**Key tests**:
1. Direct curl to endpoint
2. UI button functionality
3. Loading states
4. Error handling
5. Summary quality assessment

## Future Enhancements

**Possible improvements** (not in scope):

1. **Caching**: Store summaries for N minutes
2. **Model selection**: Let user choose Haiku vs Sonnet
3. **Custom prompts**: Allow user to refine synthesis focus
4. **Comparison mode**: Summarize multiple entities side-by-side
5. **Export**: Download summary as markdown
6. **History**: Save summaries to entity folder

## Success Metrics

- **Functional**: Button works, summaries generate
- **Performance**: <5s response time
- **Quality**: Summaries are coherent and meaningful
- **Reliability**: Error states handled gracefully
