# Agent HTTP Fallback Implementation

**Date**: 2026-01-24
**Issue**: #97 - Sub-agents can't access MCP tools
**Solution**: HTTP fallback instructions for PPS API access

## Changes Made

### Agent Configurations Updated

1. **planner.md** (`/home/jeff/.claude/agents/planner.md`)
   - Added "PPS Access Fallback" section with HTTP endpoint usage
   - Updated capability limits to note HTTP fallback available
   - Removed blocking statement about MCP unavailability

2. **coder.md** (`/home/jeff/.claude/agents/coder.md`)
   - Added "PPS Access Fallback" section with HTTP endpoint usage
   - Updated capability limits to note HTTP fallback available
   - Removed blocking statement about MCP unavailability

3. **researcher.md** (`/home/jeff/.claude/agents/researcher.md`)
   - Added "PPS Access Fallback" section with HTTP endpoint usage
   - Provides research-focused examples

4. **librarian.md** (`/home/jeff/.claude/agents/librarian.md`)
   - Added comprehensive PPS Access Fallback section
   - Includes tech_search, tech_list, and tech_ingest endpoints
   - Provides full workflow examples for doc maintenance

5. **orchestration-agent.md** (`/home/jeff/.claude/agents/orchestration-agent.md`)
   - Added note about HTTP fallback capability
   - Documents that Issue #97 is now worked around

## How It Works

### Detection
Agents detect MCP unavailability when:
- MCP tool commands return "command not found"
- Running in Task subprocess context
- Tool calls fail to execute

### Fallback
Agents use curl to call HTTP endpoints at `http://localhost:8201`:
- POST /tools/tech_search - Search tech documentation
- GET /tools/tech_list - List indexed documents
- POST /tools/tech_ingest - Re-ingest documentation

### Example Usage
```bash
# Search tech RAG via HTTP
curl -s -X POST http://localhost:8201/tools/tech_search \
    -H "Content-Type: application/json" \
    -d '{"query":"entity path configuration","limit":5}' \
    | jq -r '.results[] | "[\(.metadata.chunk_id)] \(.content)"'
```

## Testing Plan

### Phase 1: Individual Agent Tests
Test each agent can use HTTP fallback when spawned as subprocess:

1. **Planner test**: Spawn planner with task requiring tech_search
2. **Coder test**: Spawn coder with task requiring tech_search
3. **Researcher test**: Spawn researcher with question
4. **Librarian test**: Spawn librarian to audit docs

### Phase 2: Pipeline Test
Run full orchestration pipeline to verify:
- Planner can research via HTTP
- Coder can query patterns via HTTP
- No blocking due to MCP unavailability
- Pipeline completes successfully

### Phase 3: Verification
- Check that HTTP calls succeed
- Verify responses are parsed correctly
- Confirm agents continue without blocking

## Success Criteria

- [x] Agent configs updated with HTTP fallback instructions
- [x] Reference to PPSHttpClient provided for Python context
- [x] Clear curl examples for bash context
- [ ] Planner tested with HTTP fallback
- [ ] Coder tested with HTTP fallback
- [ ] Full pipeline tested
- [ ] Documentation updated

## Remaining Limitations

### What's Fixed
- Agents can now access tech_search via HTTP when MCP unavailable
- No more blocking on "cannot access MCP tools"
- Librarian can maintain docs via HTTP

### Still Not Available via HTTP
The following PPS tools are HTTP-accessible but not documented in agent configs (add if needed):
- ambient_recall (startup memory reconstruction)
- anchor_search (word-photo search)
- texture_search, texture_explore, texture_timeline (knowledge graph)
- All inventory tools (spaces, categories, items)

These were not added because:
1. Sub-agents don't typically need identity/memory tools
2. Planning/coding agents primarily need tech_search
3. Can be added on-demand if use case emerges

## Reference Implementation

See `daemon/pps_http_client.py` for:
- Full async Python client
- All 38 PPS tools as HTTP methods
- Error handling patterns
- Response parsing

## Files Modified

- `/home/jeff/.claude/agents/planner.md`
- `/home/jeff/.claude/agents/coder.md`
- `/home/jeff/.claude/agents/researcher.md`
- `/home/jeff/.claude/agents/librarian.md`
- `/home/jeff/.claude/agents/orchestration-agent.md`

## Next Steps

1. **Test the changes** - Spawn agents and verify HTTP fallback works
2. **Document in TODO.md** - Record that Issue #97 is worked around
3. **Monitor for issues** - Watch for friction during actual use
4. **Iterate if needed** - Add more endpoints if agents need them

## Notes

- HTTP server must be running at localhost:8201 (daemon PPS server)
- Requires `curl` and `jq` available in agent environment
- Agents fall back automatically - no orchestrator action needed
- This is a workaround, not a fix - MCP subprocess loading still broken
