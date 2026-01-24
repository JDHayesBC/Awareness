# Design: Comprehensive Friction Logging

**Author**: orchestrator
**Date**: 2026-01-24
**Status**: Draft

---

## Problem Statement

We need friction logging to track where agent pipelines encounter problems, inefficiencies, and blockers. This was requested before but not fully implemented. Without systematic friction logging and analysis, the agent pipeline cannot self-improve.

**Current gaps**:
1. Only planner has friction logging in instructions
2. No friction.jsonl placeholder in work template
3. Process-improver is mentioned but not mandatory
4. No central documentation for friction schema

---

## Current State Analysis

### What Already Exists

1. **Planner Agent** (`/home/jeff/.claude/agents/planner.md`):
   - Lines 74-92: Full friction logging section
   - Schema defined with 7 friction types
   - Append-only JSONL format

2. **Orchestration Agent** (`/home/jeff/.claude/agents/orchestration-agent.md`):
   - Lines 78-104: Friction aggregation section
   - Shows how to aggregate at pipeline end
   - Mentions flagging high-friction pipelines

3. **Process-Improver Agent** (`/home/jeff/.claude/agents/process-improver.md`):
   - Fully implemented for analyzing friction logs
   - Lines 17-20: Should run automatically after high-friction pipelines

4. **Work Template** (`/mnt/c/Users/Jeff/Claude_Projects/Awareness/work/_template/`):
   - Has artifacts/ directory but no friction.jsonl

---

## Approaches Considered

### Option A: Minimal (Just Add Template)
- **Description**: Only create friction.jsonl in template, rely on existing instructions
- **Pros**: Minimal change, quick to implement
- **Cons**: Other agents still won't log friction, process-improver still optional

### Option B: Comprehensive (Full Implementation)
- **Description**: Add friction logging to all agents, make process-improver mandatory, document schema
- **Pros**: Complete solution, closes the feedback loop
- **Cons**: More files to modify, more testing needed

---

## Chosen Approach

**Selected**: Option B (Comprehensive)

**Rationale**: This was requested before and didn't happen because it was done halfway. We need to do it properly this time. The task explicitly says "Make sure it actually happens this time" and "mandatory process review."

---

## Implementation Plan

### Phase 1: Template and Schema
1. Create `friction.jsonl` placeholder in work/_template/artifacts/
2. Create `FRICTION_LOGGING.md` schema documentation in docs/

### Phase 2: Add Friction Logging to All Agents
1. Add friction logging section to coder.md (similar to planner's)
2. Add friction logging section to tester.md
3. Add friction logging section to reviewer.md
4. Add friction logging section to github-workflow.md

### Phase 3: Make Process-Improver Mandatory
1. Update orchestration-agent.md to add Phase 6: Process Review
2. Make it clear this is NOT optional
3. Add it to the Stage Completion Protocol

---

## Files Affected

1. `/mnt/c/Users/Jeff/Claude_Projects/Awareness/work/_template/artifacts/friction.jsonl`
   - Create with comment header explaining format

2. `/mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/FRICTION_LOGGING.md`
   - New file with schema and usage guide

3. `/home/jeff/.claude/agents/orchestration-agent.md`
   - Add Phase 6: Process Review (mandatory) after Phase 5
   - Update Stage Completion Protocol

4. `/home/jeff/.claude/agents/coder.md`
   - Add friction logging section after error logging

5. `/home/jeff/.claude/agents/tester.md`
   - Add friction logging section

6. `/home/jeff/.claude/agents/reviewer.md`
   - Add friction logging section

7. `/home/jeff/.claude/agents/github-workflow.md`
   - Add friction logging section

---

## Friction Schema

```jsonl
{
  "timestamp": "ISO8601 timestamp",
  "agent": "planner | coder | tester | reviewer | github-workflow | orchestration-agent",
  "type": "TOOL_FAILURE | MISSING_TOOL | DEAD_END | RETRY | EXTERNAL_BLOCKER | CONTEXT_GAP | WRONG_PATH | REVERSAL | TIMEOUT | UNCLEAR_REQUIREMENTS",
  "description": "Brief description of what happened",
  "time_lost": "Estimate like '5 min' or '30 sec'",
  "resolution": "How it was resolved or 'unresolved'",
  "preventable": true | false,
  "suggestion": "What could prevent this in the future"
}
```

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Agents forget to log friction | High | Add to all agent instruction files |
| Process-improver gets skipped | High | Make it mandatory, not optional |
| Friction logs grow unbounded | Low | Work dirs are temporary |
| Added overhead slows pipelines | Low | Logging is quick (one line append) |

---

## Testing Strategy

1. Run this pipeline and log any friction encountered
2. At end, invoke process-improver on our own friction log
3. Verify process-improver can read and analyze the log
4. Verify recommendations are useful

---

## Success Criteria

- [ ] All agents have friction logging sections in their instructions
- [ ] Work template has friction.jsonl placeholder
- [ ] Orchestrator has mandatory Phase 6: Process Review
- [ ] Documentation exists for friction schema
- [ ] Test run produces valid friction log
- [ ] Process-improver successfully analyzes the log
