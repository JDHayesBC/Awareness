# get_turns_since_summary Tool

## Overview

The `get_turns_since_summary` tool retrieves raw conversation turns from the SQLite database that occurred after the last message summary was created. This provides access to **unsummarized** conversation history for manual exploration and debugging.

## Purpose

Unlike `ambient_recall` which automatically combines summaries with recent turns, `get_turns_since_summary` is for **manual retrieval** of raw history. Use it when you need to:

- Explore actual conversation turns in detail
- Debug what happened in recent conversations
- Review raw history without compression
- Paginate through large amounts of unsummarized content

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `channel` | string | None | Filter by channel (partial match). Examples: "terminal", "discord", "awareness" |
| `limit` | integer | 50 | Maximum number of turns to retrieve |
| `min_turns` | integer | 10 | Minimum turns to return even if pulling from before last summary |
| `offset` | integer | 0 | Skip this many turns before returning results (for pagination) |

## Return Format

```json
{
  "turns": [
    {
      "timestamp": "2026-01-26 18:45",
      "channel": "terminal#awareness",
      "author": "Jeff",
      "content": "Message content here..."
    },
    ...
  ],
  "count": 47,
  "last_summary_time": "2026-01-26T17:30:00"
}
```

### Fields

- `turns`: Array of conversation turn objects
  - `timestamp`: ISO 8601 timestamp (truncated to minute)
  - `channel`: Source channel identifier
  - `author`: Author name
  - `content`: Message content
- `count`: Total number of turns returned
- `last_summary_time`: Timestamp of the last summary (ISO 8601), or null if no summaries exist

## Behavior

1. **Queries the last summary timestamp** from the `message_summaries` table
2. **Retrieves turns after that timestamp** in reverse chronological order (newest first)
3. **Ensures minimum context** by also pulling `min_turns` from before the summary if needed
4. **Reverses the order** to display chronologically (oldest to newest)
5. **Supports pagination** via the `offset` parameter

### When No Summaries Exist

If no summaries have been created yet, the tool retrieves the most recent `limit` turns from the database.

## Example Usage

### Basic - Get unsummarized turns
```python
mcp__pps__get_turns_since_summary(limit=30)
```

### With channel filter
```python
mcp__pps__get_turns_since_summary(channel="terminal", limit=50)
```

### Pagination - get next batch
```python
# First 50 turns
mcp__pps__get_turns_since_summary(limit=50, offset=0)

# Next 50 turns
mcp__pps__get_turns_since_summary(limit=50, offset=50)
```

## Comparison: get_turns_since_summary vs ambient_recall

| Feature | get_turns_since_summary | ambient_recall |
|---------|------------------------|----------------|
| **Purpose** | Manual raw history exploration | Automatic unified startup context |
| **Returns** | Only raw turns since last summary | Summaries + recent turns + crystals + word-photos |
| **When to use** | Debugging, detailed review, pagination | Startup, context loading, orientation |
| **Compression** | None - raw turns only | Combines compressed summaries with raw recent turns |
| **Layers** | Layer 1 only (Raw Capture) | All layers (1-4) |

**Rule of thumb**: Use `ambient_recall` for startup and context loading. Use `get_turns_since_summary` when you need to manually explore raw conversation history.

## Implementation Details

### Data Source
- **Database**: `~/.claude/data/lyra_conversations.db`
- **Table**: `messages`
- **Timestamp comparison**: Uses `message_summaries.time_span_end` as the cutoff point

### Query Logic
```sql
-- Get turns after last summary
SELECT author_name, content, created_at, channel
FROM messages
WHERE created_at > (SELECT time_span_end FROM message_summaries ORDER BY created_at DESC LIMIT 1)
ORDER BY created_at DESC
LIMIT ? OFFSET ?
```

### Why "time_span_end"?

The `message_summaries` table tracks which messages have been summarized using `time_span_start` and `time_span_end`. The `time_span_end` represents the timestamp of the **last message** that was included in a summary. Any message with `created_at > time_span_end` is unsummarized.

## Architecture Change (Jan 2026)

### Before
- Tool was named `get_turns_since_crystal`
- Used crystal timestamp as the cutoff point
- Problem: Crystals are now RARE (identity snapshots), so this could return thousands of turns

### After
- Renamed to `get_turns_since_summary`
- Uses summary timestamp as the cutoff point
- Summaries happen FREQUENTLY (~every 50 turns), so this returns manageable amounts of data

### Migration Impact
- All references to `get_turns_since_crystal` updated to `get_turns_since_summary`
- Documentation updated to reflect summary-based retrieval
- HTTP endpoint renamed: `/tools/get_turns_since_summary`
- Request model renamed: `GetTurnsSinceSummaryRequest`

## See Also

- `ambient_recall` - Unified startup context from all layers
- `get_recent_summaries` - Retrieve compressed conversation summaries
- `summarize_messages` - Create new summaries from unsummarized messages
- `summary_stats` - Check how many messages are unsummarized
