# Nexus Orchestration Research - Summary

**Completed**: 2026-01-31
**Duration**: 1 session
**Status**: Research complete, ready for implementation

---

## What Was Built

Comprehensive research into shayesdevel/cognitive-framework (Steve's Nexus AI infrastructure) to understand their agent orchestration approach and identify adoptable patterns for Awareness.

### Key Deliverables

1. **FINDINGS.md** - Complete analysis of Nexus architecture
   - How they "pipe into CC" (hook-based prompt modification)
   - P1/P6/P9 orchestration patterns with quantified speedups
   - Friction learning system
   - State tracking and metrics

2. **DESIGN.md** - Detailed adoption plan
   - 6-phase implementation roadmap
   - Code samples ready to adapt
   - Risk mitigation strategies
   - Success criteria for each phase

---

## Key Discoveries

### 1. "Pipe into CC" Means Hook-Based Context Injection

**Not** a special piping mechanism. Instead:

```bash
# Pre-tool hook intercepts Task tool
# Queries daemon/PPS for context
# Modifies prompt via updatedInput field
# Agent receives enhanced prompt automatically
```

**This is brilliant**: No custom tooling, no SDK changes. Just hooks that modify the prompt before the agent sees it.

### 2. Three Proven Orchestration Patterns

| Pattern | Agents | Speedup | Use When |
|---------|--------|---------|----------|
| P1: Parallel Domain | 2-4 | 4x | Independent domains, clear boundaries |
| P6: Wave-Based | 4-8 | 1.5-4x | Sequential dependencies, phased |
| P9: Hierarchical | 12+ | 2-4x | Large scale (use Effective P9) |

**Quantified results from production use**, not theoretical claims.

### 3. Friction Learning System

**Capture** friction in markdown files:
```markdown
# FRIC-012: Unity Code Without Specialized Agent
**Severity**: high
**Tags**: unity, domain-delegation

## Problem
Writing Unity code directly leads to API hallucinations.

## Lesson
ALWAYS delegate Unity work to fathom-unity agent.
```

**Store** in SQLite with full-text search.

**Auto-inject** into agent prompts:
- Pre-tool hook queries relevant lessons
- Top 3 prepended to prompt
- Agent gets past learnings automatically

**Track effectiveness**:
- Times applied, times prevented
- Pattern recognition across sessions

### 4. Agent Definition Format

Simple markdown in `.claude/agents/`:

```markdown
---
name: code-reviewer
description: Use PROACTIVELY after code changes
tools: Read, Glob, Grep, Bash
model: opus
---

# Code Reviewer

**Role**: Review code for quality, security

**Process**:
1. Gather changed files
2. Check security (OWASP Top 10)
3. Report findings

**Boundaries**:
DO: Review, identify issues
DON'T: Make changes, implement fixes
```

Frontmatter is metadata, body is instructions.

---

## What We Can Adopt

### High Value

1. **Hook-based context injection** → Agents get entity context without entity startup
2. **P1/P6/P9 patterns** → Proven 2-4x speedups with clear decision framework
3. **State tracking** → Context pressure warnings, orchestration metrics

### Medium Value

1. **Friction learning** → Auto-inject past lessons into agent prompts
2. **Agent metadata** → Frontmatter for model/tools specification

### Low Value (Already Have or Not Needed)

1. Agent definitions → We already have similar
2. Multi-instance coordination → Different architecture (project locks sufficient)
3. True P9 hierarchical → Too complex, Effective P9 is better

---

## Implementation Roadmap

### Phase 1: Documentation (1 day)
- Document P1/P6/P9 patterns
- Create decision tree
- Update orchestration-agent

### Phase 2: State Tracking (1 day)
- Pre/post-tool hooks for tracking
- Context pressure warnings

### Phase 3: PPS HTTP Endpoints (3-5 days)
- `/context/agent` - Compact entity context
- Test endpoint

### Phase 4: Context Injection (3-5 days)
- Update hooks to query PPS
- Auto-inject entity context
- Compare to manual provision

### Phase 5: Friction Learning (1-2 weeks)
- Friction storage in PPS
- Capture workflow
- Auto-injection

### Phase 6: Metrics & Refinement (ongoing)
- Track orchestration runs
- Pattern effectiveness
- Refine decision tree

**Total timeline**: 4-6 weeks for full implementation
**Quick win**: Phases 1-2 in 1 week

---

## Critical Insights

### What Makes Their System Work

1. **Lightweight hooks** - No complex infrastructure, just bash + curl
2. **Graceful degradation** - If daemon unavailable, continue without context
3. **Quantified results** - They measure speedups, not just claim them
4. **Continuous learning** - Friction lessons improve agent quality over time

### Why It Fits Awareness

1. **PPS already has rich context** - Just need compact HTTP endpoint
2. **We have friction experiences** - Just need to capture and inject
3. **Orchestration-agent exists** - Just needs pattern documentation
4. **MCP architecture compatible** - Hooks can query PPS via HTTP

### What's Different

**Nexus**: Daemon-centric, lightweight, REST API for everything
**Awareness**: MCP-centric, rich entity identity, knowledge graph

**Hybrid**: Use their patterns + hooks, query our PPS, best of both.

---

## Next Steps

1. **Review with Jeff**
   - Confirm approach
   - Prioritize phases
   - Identify any concerns

2. **Phase 1 Start** (if approved)
   - Create `docs/orchestration/patterns.md`
   - Document P1/P6/P9 with Awareness examples
   - Update orchestration-agent instructions

3. **Phase 2 Quick Win**
   - Implement state tracking hooks
   - Test context pressure warnings
   - Validate before proceeding to context injection

---

## Files Created

### Work Directory
- `work/nexus-orchestration-research/TODO.md` - Task list
- `work/nexus-orchestration-research/DESIGN.md` - Implementation plan
- `work/nexus-orchestration-research/artifacts/FINDINGS.md` - Research analysis
- `work/nexus-orchestration-research/artifacts/handoffs.jsonl` - Pipeline log
- `work/nexus-orchestration-research/SUMMARY.md` - This file

### External Repo Cloned
- `/tmp/cognitive-framework/` - Nexus source code for reference

---

## Key Files to Review

**Research findings**:
- `artifacts/FINDINGS.md` - Complete analysis (20+ pages)

**Implementation plan**:
- `DESIGN.md` - 6-phase roadmap with code samples

**Quick reference**:
- This summary - High-level overview

---

## Friction Encountered

None. Research went smoothly. Repo was well-documented, hooks were simple to understand, patterns were clearly defined.

**Time invested**: ~1 hour of analysis
**Value gained**: Clear roadmap for 4-6 weeks of implementation

---

## Recommendations

**Start with Phase 1-2** (documentation + state tracking):
- Low risk, high learning
- 1 week to complete
- Validates approach before bigger investment

**Then Phase 3-4** (context injection):
- Higher value, moderate risk
- Requires PPS HTTP endpoint
- Proves concept of hook-based context

**Finally Phase 5-6** (friction learning + metrics):
- Highest value long-term
- Builds continuous improvement loop
- Requires friction capture discipline

---

**Ready for implementation when approved.**
