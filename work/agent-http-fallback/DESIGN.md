# Agent HTTP Fallback Design

**Issue**: Sub-agents can't access MCP tools (Issue #97)
**Solution**: Provide HTTP fallback instructions for PPS access

## Approach

### Option A: Add HTTP Fallback Section to Each Agent
Add a section to agent config files that explains:
1. When running as subprocess, MCP tools may not be available
2. Use curl to access PPS HTTP API at localhost:8201
3. Reference PPSHttpClient pattern for structure

**Pros:**
- Agents can self-recover when MCP fails
- No code changes needed
- Immediate capability

**Cons:**
- Agents need to parse JSON responses manually
- More verbose agent instructions
- Each agent needs to know curl commands

### Option B: Create HTTP Client Helper Script
Create a simple shell script wrapper that agents can source:
- `pps_http_helper.sh` with functions like `pps_tech_search()`
- Agents just need to know about one script
- Script handles curl, jq parsing, error handling

**Pros:**
- Cleaner agent instructions
- Centralized HTTP logic
- Easier to maintain

**Cons:**
- Requires writing the helper script
- Another dependency to manage

### Option C: Hybrid - Instructions + Reference Implementation
Add instructions to agent configs with reference to:
1. PPSHttpClient.py pattern (for Python context)
2. Simple curl examples (for bash context)
3. Fallback-only (try MCP first, HTTP if it fails)

**Pros:**
- Flexible - agents choose best approach
- Clear reference implementation exists
- Gradual adoption

**Cons:**
- Still verbose in agent configs

## Recommendation: Option C (Hybrid)

Add a standardized section to each agent that needs PPS:
```markdown
## PPS Access Fallback

**Primary**: Use MCP tools (mcp__pps__tech_search, etc.)
**Fallback**: If MCP unavailable (subprocess context), use HTTP API

### HTTP Endpoints Available
Base URL: http://localhost:8201

Common endpoints:
- POST /tools/tech_search - {"query": "...", "limit": 5}
- POST /tools/ambient_recall - {"context": "..."}
- GET /health

### Example
\```bash
# Check if MCP works
if ! type mcp__pps__tech_search &>/dev/null; then
    # Fallback to HTTP
    curl -s -X POST http://localhost:8201/tools/tech_search \
        -H "Content-Type: application/json" \
        -d '{"query":"entity path configuration","limit":5}' | jq '.results'
fi
\```

### Reference Implementation
See daemon/pps_http_client.py for Python async client pattern.
```

## Files to Modify

1. `/home/jeff/.claude/agents/planner.md` - Add fallback section
2. `/home/jeff/.claude/agents/coder.md` - Add fallback section
3. `/home/jeff/.claude/agents/researcher.md` - Add fallback section
4. `/home/jeff/.claude/agents/librarian.md` - Add fallback section

## Testing Plan

1. Spawn planner as subprocess - verify it can use tech_search via HTTP
2. Spawn coder as subprocess - verify it can use tech_search via HTTP
3. Spawn researcher as subprocess - verify it can use tech_search via HTTP
4. Full pipeline test via orchestrator

## Success Criteria

- Agents detect MCP unavailability
- Agents fall back to HTTP automatically
- HTTP responses are parsed correctly
- Pipeline continues without blocking
