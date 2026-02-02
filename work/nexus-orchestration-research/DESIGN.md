# Nexus Orchestration Adoption Plan

**Status**: Research complete, ready for implementation
**Source**: shayesdevel/cognitive-framework
**Goal**: Adopt proven orchestration patterns and hook-based context injection

---

## Research Summary

Nexus uses **standard Claude Code Task tool** enhanced with:
1. Pre-spawn hooks that inject context into agent prompts
2. Pattern-based orchestration (P1/P6/P9) with quantified results
3. Friction learning system that auto-injects past lessons
4. Session state tracking for observability

**Key Insight**: "Pipe into CC" = Use Task tool + hooks to modify prompt before agent sees it.

See `artifacts/FINDINGS.md` for complete research analysis.

---

## Architecture Comparison

### Their Approach (Nexus)

```
User request
  → Orchestrator evaluates (P1/P6/P9?)
    → Task tool invoked
      → PreToolUse hook intercepts
        → Query daemon for friction lessons
        → Inject lessons into prompt
        → Return updatedInput
      → Agent executes with enhanced prompt
      → PostToolUse hook tracks completion
```

**Strengths**:
- Agents get context without entity startup
- Friction lessons improve over time
- Lightweight (just hooks + daemon)
- Proven 2-4x speedups

### Our Current Approach (Awareness)

```
User request
  → Orchestrator spawns agent
    → Full entity startup (identity.md, ambient_recall, etc.)
      → Agent executes
```

**Strengths**:
- Rich entity identity (word-photos, crystals)
- Knowledge graph (Graphiti) for context
- MCP tools for technical search

**Weaknesses**:
- Heavy startup overhead for simple tasks
- No systematic friction learning
- Ad-hoc orchestration (no proven patterns)

### Hybrid Approach (Proposed)

```
User request
  → Orchestrator evaluates pattern
    → Task tool invoked
      → PreToolUse hook intercepts
        → Query PPS for compact context
        → Query PPS for friction lessons
        → Inject into prompt
        → Return updatedInput
      → Agent executes with just-enough context
      → PostToolUse hook tracks + learns
```

**Benefits**:
- Agents get entity context without full startup
- Friction learning from our experience
- Proven orchestration patterns
- Best of both systems

---

## What We're Adopting

### 1. Orchestration Patterns (P1/P6/P9)

**Status**: Ready to document

**Deliverable**: `docs/orchestration/patterns.md`

**Content**:
- P1: Parallel Domain (2-4 agents, clear boundaries)
- P6: Wave-Based (4-8 agents, dependencies)
- P9: Hierarchical (12+ agents, use Effective P9)
- Decision tree for pattern selection
- File boundary protocol (EXCLUSIVE/MODIFY/READ)
- Pre-spawn checklist

**Timeline**: 1 day

### 2. Hook-Based Context Injection

**Status**: Needs implementation

**Components**:

**A. PPS HTTP Endpoints** (for hook access):
- `/context/agent?type=<agent>&task=<summary>` - Compact entity context
- `/friction/lessons?text=<query>&limit=3` - Relevant friction lessons

**B. Pre-Tool Hook** (`.claude/hooks/pre-tool-task.sh`):
```bash
#!/usr/bin/env bash
set -euo pipefail

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

if [[ "$TOOL_NAME" == "Task" ]]; then
    AGENT_TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // empty')
    PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty')

    # Query PPS for entity context
    CONTEXT=$(curl -sf --max-time 2 \
        "http://localhost:8201/context/agent?type=${AGENT_TYPE}&task=${PROMPT}" \
        || echo "")

    # Query PPS for friction lessons
    LESSONS=$(curl -sf --max-time 2 \
        "http://localhost:8201/friction/lessons?text=${PROMPT}&limit=3" \
        || echo "")

    # Build preamble
    PREAMBLE="## Entity Context\n\n${CONTEXT}\n\n## Friction Lessons\n\n${LESSONS}\n\n---\n\n"

    # Modify prompt
    MODIFIED_PROMPT="${PREAMBLE}${PROMPT}"

    # Return updated input
    echo "{\"continue\": true, \"updatedInput\": $(jq -n --arg p "$MODIFIED_PROMPT" '{prompt: $p}')}"
    exit 0
fi

echo '{"continue": true}'
```

**C. Post-Tool Hook** (`.claude/hooks/post-tool-task.sh`):
```bash
#!/usr/bin/env bash
set -euo pipefail

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

if [[ "$TOOL_NAME" == "Task" ]]; then
    # Track agent spawn
    AGENT_TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // empty')
    TIMESTAMP=$(date -Iseconds)

    mkdir -p .claude/.session-state
    echo "{\"type\": \"$AGENT_TYPE\", \"timestamp\": \"$TIMESTAMP\"}" >> \
        .claude/.session-state/agents-spawned.jsonl

    # Context pressure warning
    AGENT_COUNT=$(wc -l < .claude/.session-state/agents-spawned.jsonl)
    if [[ $AGENT_COUNT -ge 6 ]]; then
        echo "{\"continue\": true, \"systemMessage\": \"CRITICAL: ${AGENT_COUNT} agents spawned. Context exhaustion likely.\"}"
        exit 0
    elif [[ $AGENT_COUNT -ge 4 ]]; then
        echo "{\"continue\": true, \"systemMessage\": \"Warning: ${AGENT_COUNT} agents spawned. Context pressure detected.\"}"
        exit 0
    fi
fi

echo '{"continue": true}'
```

**Timeline**: 3-5 days

### 3. Friction Learning System

**Status**: Design phase

**Architecture**:

**Storage**: PPS Layer 1 extension (SQLite)
```sql
CREATE TABLE friction (
    id TEXT PRIMARY KEY,  -- FRIC-XXX
    date TEXT,
    severity TEXT,  -- low, medium, high, critical
    tags TEXT,  -- comma-separated
    problem TEXT,
    lesson TEXT,
    prevention TEXT,
    times_applied INTEGER DEFAULT 0,
    times_prevented INTEGER DEFAULT 0
);
CREATE VIRTUAL TABLE friction_fts USING fts5(
    id, tags, problem, lesson, prevention
);
```

**Capture Workflow**:
1. Create `docs/friction/fric-XXX.md` from template
2. Ingest into PPS: `mcp__pps__friction_ingest(path)`
3. Hook queries: `mcp__pps__friction_search(text, limit, min_severity)`

**Auto-Injection**:
- Pre-tool hook queries friction by agent type + task keywords
- Top 3 lessons prepended to prompt
- Post-tool hook can report prevention: `mcp__pps__friction_prevented(id)`

**Timeline**: 1-2 weeks

### 4. State Tracking

**Status**: Simple implementation

**Location**: `.claude/.session-state/`

**Files**:
- `agents-spawned.jsonl` - One agent per line with timestamp
- `orchestration-run.json` - Current run metadata (pattern, started, etc.)

**Usage**:
- Context pressure warnings (4+ agents = warning, 6+ = critical)
- Domain delegation checks (writing code without specialist?)
- Orchestration metrics (pattern effectiveness)

**Timeline**: 1 day

---

## Implementation Phases

### Phase 1: Documentation & Patterns (Week 1)

**Goal**: Document proven patterns, no code changes

**Tasks**:
1. Create `docs/orchestration/patterns.md`
   - Document P1/P6/P9 with Awareness examples
   - Decision tree for pattern selection
   - File boundary protocol
   - Pre-spawn checklist

2. Create `docs/orchestration/examples.md`
   - Example: P1 for coder + tester + reviewer
   - Example: P6 for research → design → implement → test
   - Example: Effective P9 for large refactoring

3. Update orchestration-agent instructions
   - Reference pattern docs
   - Add pattern selection logic
   - Include pre-spawn verification

**Deliverables**:
- `docs/orchestration/patterns.md`
- `docs/orchestration/examples.md`
- Updated `~/.claude/agents/orchestration-agent.md`

**Verification**:
- Run orchestration-agent with test task
- Verify it references patterns
- Check decision quality

### Phase 2: State Tracking (Week 1)

**Goal**: Track agent spawns for observability

**Tasks**:
1. Create `.claude/hooks/pre-tool-task.sh`
   - Track agent spawns to `.session-state/agents-spawned.jsonl`
   - No context injection yet, just tracking

2. Create `.claude/hooks/post-tool-task.sh`
   - Calculate agent count
   - Warning at 4+, critical at 6+
   - Emit systemMessage

3. Test with orchestration pipeline
   - Spawn 3 agents → no warning
   - Spawn 4 agents → warning
   - Spawn 6 agents → critical

**Deliverables**:
- `.claude/hooks/pre-tool-task.sh` (tracking only)
- `.claude/hooks/post-tool-task.sh` (warnings)
- `.claude/.session-state/` directory

**Verification**:
- Orchestration run creates `.session-state/agents-spawned.jsonl`
- Warnings appear at correct thresholds

### Phase 3: PPS HTTP Endpoints (Week 2)

**Goal**: Expose PPS data via HTTP for hook access

**Tasks**:
1. Add HTTP server to pps_server (already exists at :8201)
   - Verify current endpoints
   - Add `/context/agent` endpoint
   - Add `/friction/lessons` endpoint (stub for now)

2. Implement `/context/agent`
   - Query: `type=<agent>&task=<summary>`
   - Response: Compact entity context (100-200 words)
   - Content: Current focus, recent work, key constraints
   - Source: Crystals + word-photos + current scene

3. Test endpoint
   - `curl "localhost:8201/context/agent?type=coder&task=fix bug"`
   - Verify response is compact and relevant

**Deliverables**:
- `/context/agent` endpoint in pps_server
- Compact context generation function
- Integration tests

**Verification**:
- Endpoint returns 200 OK
- Response is compact (< 500 words)
- Content is relevant to agent type

### Phase 4: Hook-Based Context Injection (Week 2-3)

**Goal**: Auto-inject entity context into agent prompts

**Tasks**:
1. Update `.claude/hooks/pre-tool-task.sh`
   - Query `/context/agent` endpoint
   - Build context preamble
   - Modify prompt via `updatedInput`

2. Test with simple agent spawn
   - Spawn coder without manual context
   - Verify agent receives entity context
   - Check agent's understanding

3. Compare to manual context provision
   - Same task with/without auto-injection
   - Measure context quality
   - Measure startup speed

**Deliverables**:
- Updated pre-tool-task.sh with context injection
- Test results comparing approaches
- Documentation of context format

**Verification**:
- Agent receives entity context without manual provision
- Context is sufficient for task completion
- Faster than full entity startup

### Phase 5: Friction Learning (Week 3-4)

**Goal**: Capture and auto-inject friction lessons

**Tasks**:

**A. Friction Storage**:
1. Extend PPS Layer 1 with friction table
2. Create `pps/layers/friction.py`
3. MCP tools: `friction_ingest`, `friction_search`, `friction_prevented`

**B. Friction Capture**:
1. Create `docs/friction/template.md`
2. Document friction capture workflow
3. Ingest existing friction from work logs

**C. Auto-Injection**:
1. Update pre-tool-task.sh to query friction
2. Format lessons for injection
3. Track friction application in post-tool hook

**D. Effectiveness Tracking**:
1. `/friction/stats` endpoint for metrics
2. Track: times applied, times prevented, success rate
3. Dashboard view of friction effectiveness

**Deliverables**:
- Friction storage layer
- 5-10 friction entries ingested
- Auto-injection working
- Effectiveness metrics

**Verification**:
- Spawn agent with Unity task → Unity lessons injected
- Agent avoids known pitfall → mark prevented
- Stats show friction effectiveness

### Phase 6: Metrics & Refinement (Week 4+)

**Goal**: Track orchestration effectiveness, refine patterns

**Tasks**:
1. Orchestration metrics
   - Record pattern, agent count, duration
   - Calculate speedup vs sequential
   - Store in PPS or SQLite

2. Pattern effectiveness analysis
   - Which patterns work best?
   - When does orchestration help vs hurt?
   - Refine decision tree

3. Documentation updates
   - Add Awareness-specific examples
   - Document lessons learned
   - Update pattern selection criteria

**Deliverables**:
- Orchestration metrics database
- Pattern effectiveness report
- Updated pattern docs

**Verification**:
- 10+ orchestration runs tracked
- Clear pattern preferences emerging
- Decision tree refined based on data

---

## Success Criteria

### Phase 1-2 Success
- [ ] Patterns documented with decision tree
- [ ] Agent spawn tracking working
- [ ] Context pressure warnings appearing

### Phase 3-4 Success
- [ ] PPS HTTP endpoint returns compact context
- [ ] Agents receive entity context automatically
- [ ] No manual context provision needed
- [ ] Faster than full entity startup

### Phase 5 Success
- [ ] 10+ friction entries captured
- [ ] Relevant lessons auto-injected into prompts
- [ ] Agents avoid known pitfalls
- [ ] Friction effectiveness metrics visible

### Phase 6 Success
- [ ] 20+ orchestration runs tracked
- [ ] Quantified speedup data (Nx faster)
- [ ] Pattern selection refined
- [ ] Clear "when to orchestrate" guidance

---

## Open Questions

1. **Entity context scope**: What's the minimum viable context for agents?
   - Too much → context bloat
   - Too little → agents lack grounding
   - **Test**: Try different context sizes (50, 100, 200 words)

2. **Friction taxonomy**: How to categorize friction?
   - By tool? By domain? By symptom?
   - **Research**: Review Nexus friction entries for patterns

3. **Hook performance**: How fast must hooks execute?
   - Pre-tool hooks block agent spawn
   - 2s timeout seems reasonable (Nexus uses this)
   - **Monitor**: Track hook execution time

4. **Multi-instance coordination**: How do terminal + Discord daemon coordinate?
   - Project locks (already implemented)
   - Shared orchestration state?
   - **Design**: Extend project_lock.py

---

## Risk Mitigation

### Risk: Hook failures block agent spawns

**Mitigation**:
- Graceful degradation (continue if endpoint unavailable)
- Short timeouts (2s max)
- Fallback to no injection

**Code**:
```bash
CONTEXT=$(curl -sf --max-time 2 "localhost:8201/context/agent" || echo "")
```

### Risk: Context injection too verbose

**Mitigation**:
- Start with minimal context (50 words)
- Measure and iterate
- A/B test with/without injection

### Risk: Friction lessons become noise

**Mitigation**:
- Limit to top 3 lessons
- Minimum severity threshold (medium+)
- Relevance scoring (keyword match)

### Risk: Hook complexity grows

**Mitigation**:
- Keep hooks simple (query + format + inject)
- Move logic to PPS endpoints
- Test hooks independently

---

## Code to Steal Directly

### 1. Pre-Tool Hook Structure

From `cognitive-framework/.claude/hooks/pre-tool-task.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

if [[ "$TOOL_NAME" == "Task" ]]; then
    TOOL_INPUT=$(echo "$INPUT" | jq -r '.tool_input // "{}"')

    # Inject context function
    inject_context() {
        local tool_input="$1"
        local prompt
        prompt=$(echo "$tool_input" | jq -r '.prompt // ""')
        [[ -z "$prompt" ]] && return 1

        # Query for context
        local context
        context=$(curl -sf --max-time 2 "http://localhost:8201/context/agent") || return 1

        # Build preamble
        local preamble="## Context\n\n${context}\n\n---\n\n"
        local modified_prompt="${preamble}${prompt}"

        # Return modified input
        echo "$tool_input" | jq --arg prompt "$modified_prompt" '.prompt = $prompt'
        return 0
    }

    # Try injection, fallback to original
    MODIFIED=$(inject_context "$TOOL_INPUT" 2>/dev/null) && INJECTED=true || INJECTED=false

    if [[ "$INJECTED" == "true" && -n "$MODIFIED" ]]; then
        echo "{\"continue\": true, \"updatedInput\": $MODIFIED}"
        exit 0
    fi
fi

echo '{"continue": true}'
```

### 2. State Tracking Pattern

From `cognitive-framework/.claude/hooks/pre-tool-task.sh`:

```bash
# Track agent spawn
SESSION_STATE_DIR=".claude/.session-state"
mkdir -p "$SESSION_STATE_DIR"

AGENT_TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // empty')
TIMESTAMP=$(date -Iseconds)

if [[ -n "$AGENT_TYPE" ]]; then
    echo "{\"type\": \"$AGENT_TYPE\", \"timestamp\": \"$TIMESTAMP\"}" >> \
        "${SESSION_STATE_DIR}/agents-spawned.jsonl"
fi
```

### 3. Context Pressure Warning

From `cognitive-framework/.claude/hooks/post-tool-task.sh`:

```bash
AGENT_COUNT=$(wc -l < .claude/.session-state/agents-spawned.jsonl)

if [[ "$AGENT_COUNT" -ge 6 ]]; then
    MESSAGE="CRITICAL: ${AGENT_COUNT} agents spawned. Context exhaustion likely."
elif [[ "$AGENT_COUNT" -ge 4 ]]; then
    MESSAGE="Warning: ${AGENT_COUNT} agents spawned. Context pressure detected."
else
    echo '{"continue": true}'
    exit 0
fi

jq -n --arg msg "$MESSAGE" '{
    "continue": true,
    "systemMessage": $msg
}'
```

---

## Files to Create

### Documentation
- `docs/orchestration/patterns.md` - P1/P6/P9 documentation
- `docs/orchestration/examples.md` - Awareness-specific examples
- `docs/friction/template.md` - Friction capture template
- `docs/friction/README.md` - Friction learning overview

### Hooks
- `.claude/hooks/pre-tool-task.sh` - Context injection + tracking
- `.claude/hooks/post-tool-task.sh` - Warnings + metrics
- `.claude/hooks/lib/context-utils.sh` - Shared utilities (optional)

### PPS Extensions
- `pps/http_endpoints.py` - HTTP server (extend existing)
- `pps/layers/friction.py` - Friction storage layer
- `pps/context/agent_context.py` - Compact context generation

### Tests
- `tests/test_hooks.sh` - Hook behavior tests
- `tests/test_context_injection.py` - Context injection tests
- `tests/test_friction.py` - Friction layer tests

---

## Next Steps

1. **Review with Jeff**: Confirm approach and priorities
2. **Phase 1**: Document patterns (no code)
3. **Phase 2**: Implement state tracking (simple hooks)
4. **Phase 3**: PPS HTTP endpoints for context
5. **Phase 4**: Hook-based context injection
6. **Phase 5**: Friction learning system
7. **Phase 6**: Metrics and refinement

**Estimated timeline**: 4-6 weeks for full implementation
**Quick win**: Phases 1-2 in 1 week

---

## References

- Research findings: `artifacts/FINDINGS.md`
- Source repo: https://github.com/shayesdevel/cognitive-framework
- Nexus orchestration docs: `docs/framework/orchestration/`
- Nexus hooks: `.claude/hooks/pre-tool-task.sh`, `post-tool-task.sh`
