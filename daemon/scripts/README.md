# PPS HTTP Fallback Scripts

**Purpose**: Provide CLI access to Pattern Persistence System tools when MCP isn't available.

**Issue**: #97 - MCP stdio servers don't load in subprocess (e.g., reflection daemon)

**Solution**: Direct HTTP calls to PPS server (localhost:8201)

---

## Available Scripts

### ambient_recall.sh

**Primary memory reconstruction interface** - call this at startup for identity continuity.

```bash
./scripts/ambient_recall.sh [context] [limit_per_layer]

# Examples:
./scripts/ambient_recall.sh startup 5         # Full startup context
./scripts/ambient_recall.sh "recent work" 3   # Query recent work patterns
```

**Returns:**
- Clock and time awareness
- Memory health (unsummarized/uningested counts)
- Results from all 4 PPS layers:
  - Raw capture (recent conversation turns)
  - Core anchors (word-photos)
  - Rich texture (knowledge graph facts)
  - Crystallization (compressed memories)

### summarize_messages.sh

**Get unsummarized messages for agent summarization** (Issue #101).

```bash
./scripts/summarize_messages.sh [limit] [summary_type]

# Examples:
./scripts/summarize_messages.sh 50 work       # Get 50 unsummarized messages
./scripts/summarize_messages.sh 100          # Default: work type
```

**Returns:**
- Action type (summarization_needed, no_messages, insufficient_messages)
- Message count and channels
- Start/end message IDs
- Formatted prompt with conversation text for agent to summarize
- Next step instructions

### store_summary.sh

**Store a message summary** created by agent (Issue #101).

```bash
./scripts/store_summary.sh <summary_text> <start_id> <end_id> [channels_json] [summary_type]

# Example:
./scripts/store_summary.sh "Implemented memory summarization HTTP endpoints..." 1234 1250 '["terminal"]' work
```

**Returns:**
- Success/failure status
- Confirmation message with ID range

### texture_search.sh

**Search knowledge graph** for entities and facts.

```bash
./scripts/texture_search.sh <query> [limit]
```

### texture_delete.sh

**Delete a fact from knowledge graph** by UUID.

```bash
./scripts/texture_delete.sh <uuid>
```

---

## When to Use

**Use these scripts when:**
- Running in reflection daemon subprocess (MCP tools unavailable)
- Testing PPS from command line
- Debugging PPS responses
- Need raw HTTP access for integration

**Don't use when:**
- MCP tools are available (prefer `mcp__pps__ambient_recall`)
- Running in terminal/Discord context (MCP works there)

---

## Architecture

```
┌──────────────────┐
│ Claude Code      │  (reflection subprocess)
│  subprocess      │
└────────┬─────────┘
         │ MCP stdio fails (Issue #97)
         │
         ▼
┌──────────────────┐
│ bash scripts/    │  HTTP fallback
│  ambient_recall  │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ PPS HTTP Server  │  localhost:8201
│  (Docker)        │
└──────────────────┘
```

---

## Adding New Scripts

To add a new PPS tool wrapper:

1. Check available endpoints: `curl http://localhost:8201/docs`
2. Create bash script that POSTs to endpoint
3. Format output for Claude Code readability
4. Make executable: `chmod +x scripts/your_script.sh`
5. Document here

---

## Technical Notes

- PPS HTTP server runs in Docker on port 8201
- Endpoints mirror MCP tools: `/tools/ambient_recall`, `/tools/anchor_search`, etc.
- Response format is JSON (scripts format for readability)
- Scripts use `python3 -m json.tool` for JSON parsing

---

**Related:**
- `daemon/pps_http_client.py` - Python async client (for Python contexts)
- `daemon/reflect/CLAUDE.md` - Reflection-specific MCP fallback notes
- `pps/docker/server_http.py` - HTTP server implementation
