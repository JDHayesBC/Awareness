# Conversation Navigation Tools - Implementation Complete

**Date**: 2026-01-26
**Issue**: #123
**Status**: Complete and Tested

## Summary

Implemented three new tools for flexible conversation history navigation:

1. **get_conversation_context(turns=N)** - Intelligent blending of summaries + raw turns
2. **get_turns_since(timestamp)** - Time-based forward retrieval
3. **get_turns_around(timestamp, count=40)** - Context window centered on a moment

Each tool implemented in BOTH MCP (pps/server.py) and HTTP (pps/docker/server_http.py) versions.

## Implementation Details

### Files Modified

1. **pps/layers/message_summaries.py**
   - Added `get_messages_since(timestamp, limit)` - Query messages after a timestamp
   - Added `get_messages_around(timestamp, before_count, after_count)` - Query messages centered on a timestamp
   - Total: +121 lines

2. **pps/server.py**
   - Added 3 tool definitions to `list_tools()`
   - Added 3 handlers in `call_tool()`
   - Total: +165 lines

3. **pps/docker/server_http.py**
   - Added 3 request models (Pydantic)
   - Added 3 HTTP endpoints with validation
   - Total: +172 lines

### Testing

Created comprehensive test suite: `work/ambient-recall-optimization/artifacts/test_navigation_tools.sh`

**Test Results**: 10/10 tests passed

Test coverage:
- ✓ get_conversation_context (small request)
- ✓ get_conversation_context (large request with blending)
- ✓ get_conversation_context (edge case: turns=0)
- ✓ get_turns_since (recent timestamp)
- ✓ get_turns_since (future timestamp - empty)
- ✓ get_turns_since (invalid timestamp - validation error)
- ✓ get_turns_around (centered, equal split)
- ✓ get_turns_around (asymmetric 70/30 split)
- ✓ get_turns_around (count=0)
- ✓ get_turns_around (before_ratio clamping)

### Deployment

- Docker container rebuilt and deployed
- Deployment verified current (container newer than source)
- Health check passing
- All endpoints responding correctly

## Tool Specifications

### 1. get_conversation_context

**Purpose**: Get exactly N turns of context by intelligently blending summaries and raw turns.

**Parameters**:
- `turns` (int, required): How many turns of context to retrieve

**Logic**:
- If enough unsummarized turns exist: returns N raw turns
- Otherwise: returns all unsummarized turns + enough summaries to cover remaining

**Example**:
```json
{
  "turns": 200
}
```

**Returns**:
- Summaries (oldest first)
- Raw turns (chronological)
- Metadata: counts, approximate coverage

---

### 2. get_turns_since

**Purpose**: Time-based forward retrieval - everything after a specific timestamp.

**Parameters**:
- `timestamp` (str, required): ISO 8601 format (e.g., "2026-01-26T07:30:00")
- `include_summaries` (bool, optional, default=true): Include overlapping summaries
- `limit` (int, optional, default=1000): Maximum messages to return

**Logic**:
- Query all messages WHERE created_at >= timestamp
- Optionally include summaries that overlap the time range
- Return chronologically

**Example**:
```json
{
  "timestamp": "2026-01-26T07:30:00",
  "include_summaries": true,
  "limit": 500
}
```

**Returns**:
- Messages list
- Summaries list (if requested)
- Metadata: counts, limited flag

---

### 3. get_turns_around

**Purpose**: Context window centered on a specific moment in time.

**Parameters**:
- `timestamp` (str, required): ISO 8601 format for center point
- `count` (int, optional, default=40): Total turns to retrieve
- `before_ratio` (float, optional, default=0.5): Split ratio (0.5 = equal before/after)

**Logic**:
- Calculate before/after counts from ratio
- Query N messages before timestamp (DESC then reversed)
- Query M messages after timestamp (ASC)
- Combine chronologically

**Example**:
```json
{
  "timestamp": "2026-01-26T12:00:00",
  "count": 40,
  "before_ratio": 0.7
}
```

**Returns**:
- Messages list (chronological)
- Metadata: before_count, after_count, total

---

## Design Decisions

### 1. Timestamp Validation

Added early validation in HTTP endpoints (not just in layer methods). This provides:
- Clear error messages for invalid formats
- Consistent error handling
- Better user experience

### 2. Graceful Degradation

Layer methods return empty results rather than raising exceptions for edge cases:
- Future timestamps return empty
- Timestamps before history return empty
- Invalid queries handled gracefully

HTTP endpoints validate strictly, layer methods degrade gracefully.

### 3. Blending Strategy

`get_conversation_context` uses a simple heuristic:
- Assume ~50 turns per summary (configurable)
- Return ALL unsummarized turns (full fidelity recent)
- Fill remaining with summaries (compressed past)

This balances recency (full detail) with depth (compressed history).

### 4. Return Format Consistency

All tools return:
- Success flag (HTTP only)
- Data payload
- Metadata (counts, flags)

Consistent structure makes client code simpler.

---

## Edge Cases Handled

1. **Empty Results**:
   - Future timestamps → empty messages
   - count=0 → empty messages
   - No data in range → empty messages

2. **Invalid Input**:
   - turns <= 0 → validation error
   - Invalid timestamp format → validation error
   - Missing required params → validation error

3. **Boundary Conditions**:
   - before_ratio > 1.0 → clamped to 1.0
   - before_ratio < 0.0 → clamped to 0.0
   - Requested turns > total history → return all available

4. **Performance**:
   - get_turns_since has default limit=1000
   - Large requests automatically limited
   - Clear indication when results are truncated

---

## Usage Examples

### MCP (via Claude Code)

```
Use get_conversation_context tool with turns=200
Use get_turns_since tool with timestamp="2026-01-26T07:30:00"
Use get_turns_around tool with timestamp="2026-01-26T12:00:00", count=40
```

### HTTP (via curl)

```bash
# Get 200 turns of context
curl -X POST http://localhost:8201/tools/get_conversation_context \
  -H "Content-Type: application/json" \
  -d '{"turns": 200}'

# Get turns since 7:30 AM today
curl -X POST http://localhost:8201/tools/get_turns_since \
  -H "Content-Type: application/json" \
  -d '{"timestamp": "2026-01-26T07:30:00", "include_summaries": true}'

# Get 40 turns around noon
curl -X POST http://localhost:8201/tools/get_turns_around \
  -H "Content-Type: application/json" \
  -d '{"timestamp": "2026-01-26T12:00:00", "count": 40, "before_ratio": 0.5}'
```

---

## Performance Characteristics

### get_conversation_context

- **Best case** (enough unsummarized): O(N) - single query for N turns
- **Blend case**: O(N + S) - query summaries + all unsummarized
- **Memory**: Stores up to requested turns in memory

### get_turns_since

- **Query complexity**: O(log N) with timestamp index
- **Memory**: Limited by `limit` parameter (default 1000)
- **Network**: Proportional to result size

### get_turns_around

- **Query complexity**: 2 × O(log N) - two indexed queries
- **Memory**: Fixed by `count` parameter
- **Balance**: Configurable before/after ratio

All queries use indexed timestamp columns for efficient retrieval.

---

## Future Enhancements

Potential improvements (not implemented):

1. **Channel Filtering**: Add `channel` parameter to filter by source
2. **Streaming Results**: For very large ranges, stream results
3. **Pagination**: Add offset/cursor support for browsing
4. **Caching**: Cache recent queries for repeated access
5. **Aggregation**: Add summary statistics (message counts by author, etc.)

---

## Lessons Learned

1. **Test Early**: Comprehensive tests caught the timestamp validation issue immediately
2. **Validate at Boundary**: HTTP endpoints should validate before calling layers
3. **Graceful Degradation**: Layer methods handle edge cases gracefully
4. **Clear Errors**: Specific error messages help users fix issues quickly
5. **Docker Deployment**: Always verify deployment is current before testing

---

## Related Work

- Builds on message_summaries layer infrastructure
- Complements ambient_recall for deliberate context retrieval
- Part of broader ambient_recall optimization effort
- Enables time-based navigation patterns

---

## Commit Message

```
feat(pps): add conversation navigation tools

Add three new tools for flexible conversation history navigation:

1. get_conversation_context(turns=N) - Intelligent summary+raw blending
2. get_turns_since(timestamp) - Time-based forward retrieval
3. get_turns_around(timestamp, count=40) - Context window centered on moment

Implementation:
- Added navigation methods to MessageSummariesLayer
- Implemented MCP tools in pps/server.py
- Implemented HTTP endpoints in pps/docker/server_http.py
- Comprehensive test suite (10/10 tests passing)
- Docker container rebuilt and deployed

Complements ambient_recall with time-based and flexible context retrieval.

Fixes #123
```

---

**Status**: Ready to commit and close issue #123
