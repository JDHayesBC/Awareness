# Session: Terminal to Graphiti Batch Ingestion
*Date: 2026-01-09*

## Problem

Terminal conversation turns were captured to SQLite (Layer 1) but NEVER ingested into Graphiti (Layer 3). The SessionEnd hook was calling a non-existent MCP tool `store_terminal_session`, breaking terminal session processing.

Discord ingestion worked fine - it had a working pattern to follow.

## Solution Implemented

Implemented batch ingestion tracking following the existing message summarization pattern:

### Database Schema
- `graphiti_batches` table - tracks batch metadata (similar to `message_summaries`)
- `graphiti_batch_id` column in messages table (similar to `summary_id`)

### Layer Methods (MessageSummariesLayer)
```python
count_uningested_to_graphiti() -> int
get_uningested_for_graphiti(limit=20) -> List[Dict]
mark_batch_ingested_to_graphiti(start_id, end_id, channels) -> Optional[int]
```

### MCP Tools
```python
graphiti_ingestion_stats  # Check backlog, get recommendations
ingest_batch_to_graphiti  # Batch ingest messages to Graphiti
```

### Integration Points
- **ambient_recall**: Now shows Graphiti ingestion stats in Memory Health
- **SessionEnd hook**: Fixed to remove broken tool call (daemon handles ingestion)
- **Batch size**: Default 20 messages (configurable)

## Technical Decisions

1. **Batch vs per-turn ingestion**: Chose batching because Haiku extraction has overhead. 20 messages per batch balances cost and freshness.

2. **Pattern reuse**: Followed existing message summarization architecture (graphiti_batch_id mirrors summary_id) for consistency.

3. **Daemon handles ingestion**: Hooks should be fast. Reflection daemon checks stats periodically and runs batch ingestion when backlog > 20.

4. **Raw messages, not summaries**: Knowledge graph needs actual content for entity extraction, not compressed summaries.

## Testing

Added 8 comprehensive tests in `TestGraphitiBatchTracking`:
- Table creation verification
- Count/retrieval accuracy  
- Batch marking and tracking
- Edge cases (invalid ranges)

All 23 tests pass (15 existing + 8 new).

```bash
pytest tests/test_pps/test_message_summaries.py -v
```

## Commits

- `0b29793` feat(pps): implement batch ingestion from terminal to Graphiti

## Files Modified

- `pps/layers/message_summaries.py` - Added Graphiti tracking methods (160 lines)
- `pps/server.py` - Added MCP tools and ambient_recall integration (80 lines)
- `hooks/session_end.py` - Removed broken tool call (simplified)
- `tests/test_pps/test_message_summaries.py` - Added comprehensive tests (120 lines)

## Next Steps

1. Update reflection daemon to use new tools:
   - Check `graphiti_ingestion_stats` periodically
   - Run `ingest_batch_to_graphiti` when backlog >= 20
   
2. Run initial backlog ingestion on production data

3. Monitor Memory Health stats in ambient_recall

4. Consider adding ingestion stats to web dashboard

## Notes for Future

This implementation closes the gap between terminal and Discord for Layer 3 ingestion. Both channels now have proper batch ingestion with tracking.

The pattern is reusable for other future ingestion sources (email, docs, etc).

Grafana metrics could track:
- Ingestion backlog over time
- Messages ingested per day
- Batch processing success rate
