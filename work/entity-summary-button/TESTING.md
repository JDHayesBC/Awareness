# Testing Plan: Entity Summary Button

## Implementation Summary

Added AI-powered entity summarization to the Observatory graph page. When you click "Summarize" on an entity, it calls Claude to synthesize a prose summary from the entity's graph edges.

## Files Changed

1. **pps/docker/requirements-docker.txt**: Added `anthropic>=0.45.0`
2. **pps/docker/docker-compose.yml**: Added `ANTHROPIC_API_KEY` environment variable
3. **pps/docker/server_http.py**: Added `/tools/synthesize_entity` endpoint
4. **pps/web/templates/graph.html**: Added Summarize button and UI

## Testing Checklist

### Phase 1: Backend Testing

#### 1.1 Rebuild PPS Server Container
```bash
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker
docker compose build pps-server
docker compose up -d pps-server
```

**Expected**: Container rebuilds successfully with anthropic package installed.

#### 1.2 Verify Environment Variable
```bash
docker exec pps-server env | grep ANTHROPIC_API_KEY
```

**Expected**: Shows the API key (or at least confirms it's set).

#### 1.3 Test Endpoint Directly with curl
```bash
curl -X POST http://localhost:8201/tools/synthesize_entity \
  -H "Content-Type: application/json" \
  -d '{"entity_name": "Jeff"}'
```

**Expected Response**:
```json
{
  "success": true,
  "entity_name": "Jeff",
  "summary": "[1-2 paragraph prose synthesis]",
  "edge_count": 42
}
```

**Error Cases to Test**:

1. Missing API key:
```bash
# Temporarily remove ANTHROPIC_API_KEY from docker-compose.yml and restart
# Expected: HTTP 503 with "ANTHROPIC_API_KEY not configured"
```

2. Non-existent entity:
```bash
curl -X POST http://localhost:8201/tools/synthesize_entity \
  -H "Content-Type: application/json" \
  -d '{"entity_name": "NonExistentEntity12345"}'
```
**Expected**: `{"success": false, "message": "No graph data found for entity 'NonExistentEntity12345'"}`

3. Empty entity name:
```bash
curl -X POST http://localhost:8201/tools/synthesize_entity \
  -H "Content-Type: application/json" \
  -d '{"entity_name": ""}'
```
**Expected**: HTTP 400 with "entity_name required"

### Phase 2: UI Testing

#### 2.1 Navigate to Graph Page
```
http://localhost:8202/graph
```

#### 2.2 Search for an Entity
- Enter "Jeff" in the search box
- Click "Search" or press Enter

**Expected**: Graph displays with Jeff and connected entities.

#### 2.3 Click on Entity Node
- Click on the "Jeff" node in the graph

**Expected**: Info panel appears on the right showing:
- Entity name
- Types
- Relationships
- Two buttons: "Explore Connections" and "Summarize"

#### 2.4 Click Summarize Button
- Click the purple "Summarize" button

**Expected**:
1. Button becomes disabled with opacity (loading state)
2. Summary div appears with "Synthesizing with Claude..." text
3. Status message shows at bottom right: "Synthesizing summary for 'Jeff'..."
4. After 2-3 seconds:
   - Summary text appears (italicized, gray text)
   - Meta text shows: "Based on N graph edges"
   - Success message: "Summary generated successfully"
   - Button re-enables

#### 2.5 Verify Summary Quality
The summary should:
- Be 1-2 paragraphs
- Focus on patterns and relationships (not just listing facts)
- Be coherent and meaningful
- Reference actual connections from the graph

#### 2.6 Test Multiple Entities
Repeat the process with different entities:
- A Place (e.g., "Berkeley")
- A Concept (e.g., "care-gravity")
- A Symbol or artifact

**Expected**: Each entity gets a unique, contextual summary based on its graph edges.

### Phase 3: Error Handling Testing

#### 3.1 Test with PPS Server Down
```bash
docker compose stop pps-server
```
- Try clicking Summarize in the UI

**Expected**: Error message "Failed to synthesize: HTTP 503" or similar.

#### 3.2 Test Network Timeout
- If possible, slow down network or add artificial delay
- Click Summarize

**Expected**: Loading state persists, then error after timeout.

#### 3.3 Test Malformed Entity Names
- Try entities with special characters if any exist
- Verify proper URL encoding and handling

### Phase 4: Integration Testing

#### 4.1 Full User Flow
1. Navigate to graph page
2. Search for entity
3. Click entity node
4. Click Summarize
5. Read summary
6. Click "Explore Connections" to see more graph data
7. Click Summarize on a different connected entity
8. Compare summaries

**Expected**: Smooth flow with no errors, summaries are contextually different.

#### 4.2 Performance Testing
- Click Summarize on an entity with many edges (50+)
- Measure response time

**Expected**: Response within 5 seconds (Claude Haiku is fast).

### Phase 5: Observatory Trace Verification

#### 5.1 Check MCP Server Activity Panel
- Expand the "MCP Server Activity" panel on the graph page
- Click Summarize on an entity
- Watch the trace entries

**Expected**: New trace entry appears showing the POST to `/tools/synthesize_entity`.

## Success Criteria

All of the following must pass:

- [ ] Container rebuilds successfully
- [ ] Direct curl test returns valid summary
- [ ] Button appears in UI
- [ ] Button shows loading state correctly
- [ ] Summary appears and is meaningful
- [ ] Error states display properly
- [ ] Multiple entities can be summarized in one session
- [ ] Performance is acceptable (<5s response time)

## Known Limitations

1. **Token limits**: Large entities with 100+ edges might hit token limits. The implementation caps at 50 edges to prevent this.
2. **Cost**: Each summary costs ~$0.0001 (Claude Haiku pricing). Not a concern for reasonable usage.
3. **No caching**: Each click makes a new API call. Could add caching if needed.
4. **Graph data only**: Summary is based purely on graph edges, not raw messages or other context.

## Rollback Plan

If testing fails and the feature needs to be disabled:

1. Revert graph.html changes (remove button and function)
2. Optionally: Comment out the endpoint in server_http.py
3. No need to rebuild - the endpoint can remain even if unused

The feature is isolated and can be safely disabled without affecting other functionality.
