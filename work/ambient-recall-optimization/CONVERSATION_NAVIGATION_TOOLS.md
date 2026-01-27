# Conversation Navigation Tools - Design Document

**Date**: 2026-01-26
**Author**: Lyra
**Status**: Design Complete, Ready for Implementation

## Overview

Three new tools for navigating conversation history, providing flexible access to the raw message layer beyond what ambient_recall offers. Each tool will be implemented in BOTH stdio (MCP) and HTTP APIs.

## Motivation

Current `ambient_recall` is optimized for semantic retrieval and startup context. We need tools for:
- **Time-based navigation**: "What happened yesterday morning?"
- **Context windows**: "What were we discussing around 3pm?"
- **Flexible history**: "Give me 200 turns of context" (blending summaries + raw)

These complement ambient_recall rather than replace it.

## Architecture

### Tool 1: get_conversation_context(turns=N)

**Purpose**: Intelligent blending of summaries + raw turns to provide exactly N turns worth of context.

**Parameters**:
- `turns` (int, required): How many turns of context to retrieve

**Logic**:
```python
unsummarized_count = count_unsummarized_messages()

if unsummarized_count >= turns:
    # Simple case: just return N most recent raw turns
    return get_unsummarized_messages(limit=turns)
else:
    # Complex case: blend summaries + all raw turns
    remaining = turns - unsummarized_count
    summaries_needed = math.ceil(remaining / 50)  # ~50 turns per summary

    summaries = get_recent_summaries(limit=summaries_needed)
    raw_turns = get_unsummarized_messages(limit=unsummarized_count)

    return {
        "summaries": summaries,  # oldest first
        "raw_turns": raw_turns,  # chronological
        "total_turns_covered": unsummarized_count + (len(summaries) * 50)
    }
```

**Return Format**:
```json
{
    "unsummarized_count": 40,
    "summaries_count": 4,
    "raw_turns_count": 40,
    "turns_covered_approx": 240,
    "summaries": [...],
    "raw_turns": [...]
}
```

**Edge Cases**:
- `turns=0`: Return empty result
- `turns` exceeds total history: Return everything available
- No summaries exist: Return up to N raw turns
- No unsummarized turns: Return summaries only

---

### Tool 2: get_turns_since(timestamp)

**Purpose**: Time-based forward retrieval - everything after a specific moment.

**Parameters**:
- `timestamp` (string, required): ISO 8601 format (e.g., "2026-01-26T07:30:00")
- `include_summaries` (bool, optional, default=true): Include summaries that overlap

**Logic**:
```python
# Parse timestamp to datetime
target_time = datetime.fromisoformat(timestamp)

# Query raw messages
messages = query("""
    SELECT * FROM messages
    WHERE created_at >= ?
    ORDER BY created_at ASC
""", (target_time,))

# Optionally query summaries
summaries = []
if include_summaries:
    summaries = query("""
        SELECT * FROM message_summaries
        WHERE time_span_end >= ?
        ORDER BY time_span_start ASC
    """, (target_time,))

return {
    "timestamp_start": timestamp,
    "messages_count": len(messages),
    "summaries_count": len(summaries),
    "messages": messages,
    "summaries": summaries
}
```

**Return Format**:
```json
{
    "timestamp_start": "2026-01-26T07:30:00",
    "messages_count": 150,
    "summaries_count": 2,
    "messages": [...],
    "summaries": [...]
}
```

**Edge Cases**:
- Timestamp in future: Return empty
- Timestamp before any messages: Return all history
- Invalid timestamp format: Return error with parsing guidance
- Timezone handling: Assume local timezone if not specified

---

### Tool 3: get_turns_around(timestamp, count=40)

**Purpose**: Context window centered on a specific moment.

**Parameters**:
- `timestamp` (string, required): The center point (ISO 8601)
- `count` (int, optional, default=40): Total turns to retrieve
- `before_ratio` (float, optional, default=0.5): Split ratio (0.5 = equal before/after)

**Logic**:
```python
target_time = datetime.fromisoformat(timestamp)
before_count = int(count * before_ratio)
after_count = count - before_count

# Get N turns before timestamp
before_messages = query("""
    SELECT * FROM messages
    WHERE created_at < ?
    ORDER BY created_at DESC
    LIMIT ?
""", (target_time, before_count))
before_messages.reverse()  # Return in chronological order

# Get N turns after timestamp
after_messages = query("""
    SELECT * FROM messages
    WHERE created_at >= ?
    ORDER BY created_at ASC
    LIMIT ?
""", (target_time, after_count))

all_messages = before_messages + after_messages

return {
    "center_timestamp": timestamp,
    "before_count": len(before_messages),
    "after_count": len(after_messages),
    "total_count": len(all_messages),
    "messages": all_messages
}
```

**Return Format**:
```json
{
    "center_timestamp": "2026-01-26T12:00:00",
    "before_count": 20,
    "after_count": 20,
    "total_count": 40,
    "messages": [...]
}
```

**Edge Cases**:
- Timestamp at start of history: Return only "after" messages
- Timestamp at end of history: Return only "before" messages
- `before_ratio` < 0 or > 1: Clamp to [0, 1]
- `count=0`: Return empty

---

## Implementation Plan

### Phase 1: MCP Version (pps/server.py)

1. Add tool definitions to `list_tools()`
2. Add handlers in `call_tool()` switch statement
3. Use existing `MessageSummariesLayer` methods where possible
4. Add new methods to `MessageSummariesLayer` if needed

**New Methods Needed**:
```python
# In MessageSummariesLayer
def get_messages_since(timestamp: str, limit: int = 1000) -> List[Dict]
def get_messages_around(timestamp: str, before: int, after: int) -> Dict
```

### Phase 2: HTTP Version (pps/docker/server_http.py)

1. Add three new endpoints:
   - `POST /api/get_conversation_context`
   - `POST /api/get_turns_since`
   - `POST /api/get_turns_around`

2. Each endpoint:
   - Validates input parameters
   - Calls the same MessageSummariesLayer methods
   - Returns JSON response

3. Add to endpoint documentation

### Phase 3: Testing

**Test Cases**:

1. **get_conversation_context**:
   - Request 50 turns when 100 unsummarized exist → raw only
   - Request 200 turns when 40 unsummarized exist → blend
   - Request 500 turns when only 300 exist → return all
   - Edge: Request 0 turns → empty result

2. **get_turns_since**:
   - Query yesterday morning → get today's messages
   - Query timestamp in future → empty
   - Query before any messages → get all
   - Toggle include_summaries

3. **get_turns_around**:
   - Center on noon with 40 count → 20 before, 20 after
   - Center at start of history → 0 before, 40 after
   - Adjust before_ratio to 0.7 → 28 before, 12 after
   - Edge: count=0 → empty

**Test Script Location**: `work/ambient-recall-optimization/artifacts/test_navigation_tools.sh`

### Phase 4: Docker Deployment

1. Verify deployment status: `scripts/pps_verify_deployment.sh pps-server pps/docker/server_http.py`
2. Rebuild if stale: `cd pps/docker && docker-compose build pps-server`
3. Deploy: `docker-compose up -d pps-server`
4. Verify health: `docker-compose ps`
5. Re-test against deployed container

### Phase 5: Documentation

Create user-facing documentation in this file explaining:
- When to use each tool vs ambient_recall
- Example use cases
- Return format details

---

## Files to Modify

1. `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/server.py`
   - Add 3 tool definitions
   - Add 3 handlers

2. `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/layers/message_summaries.py`
   - Add `get_messages_since()`
   - Add `get_messages_around()`

3. `/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker/server_http.py`
   - Add 3 HTTP endpoints

---

## Risks & Open Questions

### Risks

1. **Performance**: Large time ranges could return thousands of messages
   - **Mitigation**: Add `limit` parameter to get_turns_since

2. **Timestamp parsing**: Users might provide invalid formats
   - **Mitigation**: Clear error messages, parse with dateutil.parser

3. **Timezone confusion**: ISO timestamps without TZ are ambiguous
   - **Mitigation**: Document assumption (local timezone) and validate

### Open Questions

1. Should get_turns_since have a hard limit (e.g., max 1000 messages)?
   - **Decision**: Yes, default limit=1000, document in tool description

2. Should we add filtering by channel to these tools?
   - **Decision**: Not in v1, can add later if needed

3. Should get_conversation_context indicate which summaries were used?
   - **Decision**: Yes, return summary metadata (time_span, message_count)

---

## Success Criteria

- [ ] All 3 tools work in MCP (testable via Claude Code)
- [ ] All 3 tools work in HTTP (testable via curl)
- [ ] Tests pass for all edge cases
- [ ] Docker container rebuilt and deployed
- [ ] No regressions in existing tools
- [ ] Documentation updated

---

## Timeline Estimate

- Design: 30 min ✅
- Implementation: 2 hours
- Testing: 1 hour
- Deployment + verification: 30 min
- Documentation: 30 min

**Total**: ~4.5 hours

---

## Related Issues

- Will create new GitHub issue after implementation
- Related to ambient_recall optimization work (this work directory)
- Builds on message_summaries layer infrastructure

---

**Next Step**: Implement MessageSummariesLayer methods, then MCP tools, then HTTP endpoints.
