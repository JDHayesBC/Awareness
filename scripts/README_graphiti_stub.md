# Graphiti Ingestion Stub

Standalone script for validating knowledge graph extraction quality WITHOUT writing to the database.

## Purpose

Issue #107 implements the "stub → test → iterate → wire" pattern for graph ingestion.

**Problem**: Automatic extraction produces too many low-value nodes (Issue #81). Generic entities like "discord_user(user)", vague session artifacts, and overly generic Claude statements pollute the graph.

**Solution**: Test extraction quality in isolation before wiring into the live graph.

## Usage

### Basic Usage

```bash
# From stdin
echo "Jeff: Let's implement auth" | python3 scripts/graphiti_ingest_stub.py

# From file
python3 scripts/graphiti_ingest_stub.py scripts/sample_conversation.txt

# Specify channel context
python3 scripts/graphiti_ingest_stub.py --channel terminal input.txt

# With scene and crystal context
python3 scripts/graphiti_ingest_stub.py \
  --scene-context "Main room, evening, cozy" \
  --crystal-context "Recent work on PPS Layer 3" \
  input.txt
```

### Input Formats

The script supports three input formats:

#### 1. Simple Format (Speaker: Message)
```
Jeff: Let's implement the authentication system
Lyra: I'll create the auth module with JWT tokens
Jeff: Sounds good, let's start with the user model
```

#### 2. Structured Format (Key: Value blocks)
```
channel: terminal
speaker: Jeff
content: Let's implement the authentication system
timestamp: 2026-01-21T00:30:00Z

channel: terminal
speaker: Lyra
content: I'll create the auth module
timestamp: 2026-01-21T00:30:15Z
```

#### 3. JSON Format
```json
[
  {
    "channel": "discord",
    "speaker": "Jeff",
    "content": "Working on PPS improvements",
    "timestamp": "2026-01-21T10:00:00Z"
  },
  {
    "channel": "discord",
    "speaker": "Lyra",
    "content": "The crystallization layer is working well",
    "timestamp": "2026-01-21T10:01:00Z"
  }
]
```

### Output Format

The script outputs JSON to stdout:

```json
[
  {
    "subject": "Jeff",
    "predicate": "REQUESTED_IMPLEMENTATION_OF",
    "object": "authentication system",
    "confidence": 0.9,
    "metadata": {
      "timestamp": "2026-01-21T00:30:00Z",
      "channel": "terminal"
    }
  }
]
```

### Command-Line Options

```
Options:
  input_file              Input file (or read from stdin if not provided)
  --channel TEXT          Default channel for messages without explicit channel
  --scene-context TEXT    Scene context to inject into extraction
  --crystal-context TEXT  Crystal context to inject into extraction
  --neo4j-uri TEXT        Neo4j URI (default: bolt://localhost:7687)
  --neo4j-user TEXT       Neo4j username (default: neo4j)
  --neo4j-password TEXT   Neo4j password (default: password123)
  --group-id TEXT         Group ID for extraction (default: stub_extraction)
```

## Testing

Run the test suite:

```bash
python3 scripts/test_graphiti_stub.py
```

Tests verify:
- Message parsing (all three formats)
- Speaker extraction
- Timestamp handling
- Output structure validation

## Example Workflow

### 1. Extract from recent terminal conversation
```bash
# Get recent conversation from PPS
# (This would require a query tool - placeholder for now)

# Run extraction
python3 scripts/graphiti_ingest_stub.py conversation.txt > triplets.json
```

### 2. Review extraction quality
```bash
# Pretty print
cat triplets.json | jq '.'

# Count triplets
cat triplets.json | jq 'length'

# Check for noise (generic entities)
cat triplets.json | jq '.[] | select(.subject == "?" or .object == "?")'
```

### 3. Iterate on extraction rules
If extraction produces noise:
1. Adjust `pps/layers/extraction_context.py`
2. Modify entity types in `pps/layers/rich_texture_entities.py`
3. Re-run stub on same conversation
4. Compare output quality

### 4. Wire into production
Once extraction quality is good:
1. Integration happens in `pps/layers/rich_texture_v2.py`
2. The `_store_direct()` method already uses these extraction rules
3. Stub validates what WOULD be extracted

## Current Limitations

**IMPORTANT**: This is a STUB implementation. It demonstrates the pattern but has limitations:

1. **No actual triplet extraction yet**: The script shows the structure but doesn't parse graphiti_core's actual extraction results. This requires understanding graphiti_core's internal result format.

2. **Neo4j connection still required**: Even for dry-run mode, graphiti_core needs database access for LLM-based extraction. We call `add_episode()` but should capture results without persisting.

3. **Extraction result parsing needed**: The `_parse_extraction_result()` method is a stub. Real implementation needs to parse what graphiti_core extracted (entities, edges, relationships).

## Next Steps

To complete this tool:

1. **Parse graphiti extraction results**: Study what `client.add_episode()` returns and extract the actual triplets that WOULD be saved.

2. **Add query mode**: Query the stub_extraction group_id to see what WAS extracted (if we can't intercept before save).

3. **Comparison mode**: Run extraction on same conversation twice with different rules, compare output.

4. **Quality metrics**: Count noise entities, duplicate edges, vague predicates.

## Related Files

- `pps/layers/rich_texture_v2.py` - Production graphiti layer
- `pps/layers/extraction_context.py` - Extraction instructions
- `pps/layers/rich_texture_entities.py` - Entity type definitions
- `scripts/graph_curator.py` - Graph curation tool
- `scripts/sample_conversation.txt` - Example input

## Issues

- Issue #107: This feature (stub testing)
- Issue #81: Graph pollution from automatic extraction
