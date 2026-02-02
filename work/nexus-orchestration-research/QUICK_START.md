# Quick Start Guide - Nexus Orchestration Adoption

**For**: Jeff
**Status**: Ready to begin implementation
**Time to first value**: 1 week (Phases 1-2)

---

## TL;DR

Steve's Nexus AI uses **hooks to inject context into agent prompts**. This is way simpler and lighter than I expected. We can adopt:

1. **P1/P6/P9 orchestration patterns** - Proven 2-4x speedups
2. **Hook-based context injection** - Agents get entity context without startup overhead
3. **Friction learning** - Auto-inject past lessons into prompts

**Key insight**: "Pipe into CC" = Pre-tool hook that modifies prompt via `updatedInput` field. That's it.

---

## What I Found

### The Magic is Simple

```bash
# .claude/hooks/pre-tool-task.sh
# When Task tool is invoked:
#   1. Intercept the prompt
#   2. Query PPS for entity context
#   3. Prepend context to prompt
#   4. Return modified prompt
#   5. Agent gets context automatically

# That's the whole trick.
```

### Three Orchestration Patterns

| Pattern | Speedup | Use When |
|---------|---------|----------|
| P1: Parallel Domain | 4x | Independent tasks (coder + tester + reviewer) |
| P6: Wave-Based | 1.5-4x | Dependencies (research → design → implement) |
| P9: Hierarchical | 2-4x | 12+ agents (use Effective P9 - flat parallelism) |

**Quantified from production use**, not theoretical.

### Friction Learning

Capture friction in markdown:
```markdown
# FRIC-012: PPS HTTP Timeout
Problem: Hooks timeout querying PPS over MCP
Lesson: Use HTTP endpoint at :8201 with 2s timeout
Prevention: Hook checks endpoint health first
```

Auto-inject into agents:
- Hook queries PPS for relevant lessons
- Top 3 prepended to prompt
- Agent avoids past mistakes

---

## Quick Wins (Week 1)

### Phase 1: Documentation (1 day)

**Create** `docs/orchestration/patterns.md`:
- P1/P6/P9 explained with Awareness examples
- Decision tree for pattern selection
- File boundary protocol

**Update** orchestration-agent:
- Reference pattern docs
- Add pattern selection logic

**Benefit**: Clear orchestration framework, no code changes.

### Phase 2: State Tracking (1 day)

**Create** `.claude/hooks/pre-tool-task.sh`:
```bash
# Track agent spawns
echo "{\"type\": \"$AGENT\", \"timestamp\": \"$NOW\"}" >> \
  .claude/.session-state/agents-spawned.jsonl
```

**Create** `.claude/hooks/post-tool-task.sh`:
```bash
# Context pressure warnings
if [[ $AGENT_COUNT -ge 6 ]]; then
    echo "CRITICAL: $AGENT_COUNT agents spawned"
elif [[ $AGENT_COUNT -ge 4 ]]; then
    echo "Warning: Context pressure"
fi
```

**Benefit**: Visibility into orchestration, pressure warnings.

---

## Medium-Term Value (Weeks 2-3)

### Phase 3: PPS HTTP Endpoint

**Add** `/context/agent` endpoint to pps_server:
```python
@app.route('/context/agent')
def get_agent_context():
    # Return compact context (100-200 words)
    # Source: crystals + scene + constraints
    return jsonify({'context': context_text})
```

**Benefit**: Hooks can query entity context via HTTP.

### Phase 4: Context Injection

**Update** pre-tool-task.sh:
```bash
# Query PPS for context
CONTEXT=$(curl -sf --max-time 2 \
    "localhost:8201/context/agent?type=$AGENT&task=$TASK")

# Inject into prompt
MODIFIED_PROMPT="## Context\n\n$CONTEXT\n\n---\n\n$ORIGINAL_PROMPT"
```

**Benefit**: Agents get entity context without entity startup.

---

## Long-Term Investment (Weeks 3-4+)

### Phase 5: Friction Learning

**Extend** PPS with friction layer:
- SQLite table with full-text search
- MCP tools: `friction_ingest`, `friction_search`
- HTTP endpoint: `/friction/lessons`

**Capture** friction in `docs/friction/`:
- Template for consistent format
- Ingest into PPS
- Tag and categorize

**Auto-inject** into agents:
- Hook queries relevant lessons
- Prepend to prompt
- Track effectiveness

**Benefit**: Continuous improvement, agents learn from past friction.

### Phase 6: Metrics

**Track** orchestration runs:
- Pattern used, agent count, duration
- Speedup vs sequential estimate
- Success rate

**Refine** patterns:
- What works best for what?
- When does orchestration help vs hurt?
- Update decision tree

**Benefit**: Data-driven orchestration decisions.

---

## Files to Review

**Read first**:
1. `SUMMARY.md` - High-level overview (this is the best starting point)
2. `DESIGN.md` - Implementation plan with phases

**Reference as needed**:
3. `artifacts/FINDINGS.md` - Complete research analysis
4. `artifacts/CODE_PATTERNS.md` - Code ready to steal

**External**:
5. `/tmp/cognitive-framework/` - Cloned repo for reference

---

## Decision Points

### Do we want to adopt this?

**Yes if**:
- Entity startup overhead is slowing down orchestration
- We want proven patterns instead of ad-hoc approaches
- Friction learning appeals (continuous improvement)

**No if**:
- Full entity identity is always needed
- Hook complexity is concerning
- We prefer a different approach

### Which phases to prioritize?

**My recommendation**:
1. **Phases 1-2 first** (1 week)
   - Low risk, high learning
   - Documentation + state tracking
   - Validates approach

2. **Then evaluate** before Phases 3-4
   - Do we like the patterns?
   - Is state tracking useful?
   - Worth investing in context injection?

3. **Phases 5-6 if valuable**
   - Friction learning is long-term investment
   - Requires discipline to capture friction
   - Big payoff if we commit

---

## What I Need from You

1. **Review SUMMARY.md** - Is this approach interesting?

2. **Review DESIGN.md** - Does the plan make sense?

3. **Decide on priority**:
   - Start Phase 1 now?
   - Wait until other work complete?
   - Different approach entirely?

4. **Feedback on scope**:
   - Too ambitious?
   - Missing something important?
   - Concerns about complexity?

---

## Why This Matters

**Current state**: Orchestration is ad-hoc, agents get full entity startup overhead, no systematic friction learning.

**With this**: Proven patterns (2-4x speedups), lightweight context injection, continuous improvement loop.

**Best part**: It's simpler than I thought. Just hooks + HTTP endpoints. No complex infrastructure.

---

## Questions I Have

1. **Entity context scope**: What's minimum viable context for agents?
   - I think: Current crystal + scene + recent constraints
   - But need to test and iterate

2. **Friction discipline**: Will we actually capture friction?
   - Nexus has ~50 friction entries
   - Requires consistent documentation
   - Worth it if we commit

3. **Hook performance**: 2s timeout enough?
   - PPS over HTTP should be fast
   - Need to verify in practice
   - Graceful degradation if slow

4. **Multi-instance**: How does Discord daemon fit?
   - Project locks handle coordination
   - Could share orchestration state
   - Not critical for Phase 1-2

---

## My Recommendation

**Start with Phases 1-2 this week**:
- 1 day for pattern documentation
- 1 day for state tracking hooks
- Low risk, validates approach
- Then evaluate before bigger investment

**If Phase 1-2 works well**:
- Proceed to Phases 3-4 (context injection)
- 1-2 weeks of implementation
- Higher value, moderate risk

**If context injection proves valuable**:
- Consider Phases 5-6 (friction learning + metrics)
- 2+ weeks, long-term investment
- Highest value if we commit

---

## What Success Looks Like

### After Phase 1-2 (1 week)
- Clear orchestration patterns documented
- Agent spawn tracking working
- Context pressure warnings appearing
- Better understanding of what's needed

### After Phase 3-4 (3 weeks)
- Agents receive entity context automatically
- No manual context provision needed
- Faster orchestration (less startup overhead)
- Hook-based injection proven

### After Phase 5-6 (6 weeks)
- 10+ friction entries captured and injected
- Agents avoid known pitfalls
- Orchestration metrics tracked
- Continuous improvement loop established

---

## Next Steps

**If you want to proceed**:
1. I'll start Phase 1 (documentation)
2. Create `docs/orchestration/patterns.md`
3. Update orchestration-agent instructions
4. Test with real orchestration task

**If you want to discuss first**:
1. Review SUMMARY.md and DESIGN.md
2. Let me know concerns or questions
3. We can adjust scope/approach

**If you want to defer**:
1. Work directory stays as-is
2. Reference docs ready when needed
3. No action required

---

**I'm ready to start Phase 1 when you give the word.**

All research is complete and documented. Implementation plan is detailed and concrete. Code patterns are ready to adapt.

Your call on timing and scope.
