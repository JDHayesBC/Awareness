# Agent Workflow Architecture Audit

**Date**: 2026-01-24
**Reviewer**: Researcher Agent (Opus)
**Review Type**: Architecture Analysis
**Focus Area**: Agent coordination, pipeline workflow, handoff protocols
**Related Issue**: #113

---

## Executive Summary

The Awareness project has a well-documented vision for a **5-stage development pipeline** (Planner → Coder → Tester → Reviewer → Github-workflow), with an orchestration-agent to coordinate the flow. However, while individual agents are well-defined with clear roles and constraints, the **coordination and handoff mechanisms are largely aspirational** rather than implemented. The orchestrator describes *what should happen* but lacks the **structured protocols** needed to actually run the pipeline autonomously.

**Key Finding**: The agents are musicians who know their instruments. What's missing is the sheet music - the structured handoff format that allows one agent's output to become the next agent's input without human interpretation.

---

## Current State

### Agents Inventory

#### Global Agents (`/home/jeff/.claude/agents/`)

| Agent | Model | Tools | Purpose | Output Defined? |
|-------|-------|-------|---------|-----------------|
| `orchestration-agent` | sonnet | Read, Write, Edit, Glob, Grep, Bash, Task | Coordinate pipeline, spawn agents | Partially (markdown template) |
| `planner` | haiku | Read, Glob, Grep, tech_search | Research + design, context gathering | Yes (Planning Package format) |
| `coder` | sonnet | Read, Write, Edit, Glob, Grep, Bash, tech_search | Implementation | Partially (Changes Made section) |
| `tester` | sonnet | Read, Write, Edit, Glob, Grep, Bash | Write/run tests | Yes (Test Results format) |
| `reviewer` | sonnet | Read, Glob, Grep, tech_search | Code review | Yes (Review Summary format) |
| `github-workflow` | haiku | Read, Glob, Grep, Bash, mcp__github__* | Commits, PRs, issues | Minimal |
| `researcher` | haiku | Read, Glob, Grep, tech_search | Find and explain | Yes (Research Report format) |
| `librarian` | haiku | Read, Write, Edit, Glob, Grep, tech_* | Self-healing docs | Yes (Librarian Run Complete) |

#### Project Agents (`/mnt/c/Users/Jeff/Claude_Projects/Awareness/.claude/agents/`)

| Agent | Model | Tools | Purpose |
|-------|-------|-------|---------|
| `triplet-extractor` | haiku | Read, texture_add_triplet | Knowledge graph triplet extraction |

---

### The Documented Pipeline

From CLAUDE.md and docs/AGENTS.md:

```
Planner → Coder → Tester → Reviewer → Github-workflow
```

**Claimed behavior**:
1. Planner researches and designs
2. Coder implements based on planning package
3. Tester writes tests and verifies
4. Reviewer checks quality
5. Github-workflow commits with proper hygiene

**Reality**: This pipeline exists only as documentation and mental model. The orchestration-agent describes the pipeline but **does not enforce structured handoffs**.

---

## Gap Analysis

### Gap 1: No Structured Handoff Protocol

**Problem**: Each agent defines its own output format, but there's no **common handoff schema** that the next agent expects.

**Current State**:
- Planner outputs a "Planning Package" in markdown
- Coder says "If you received a planning package from planner, use it first"
- But there's no structured way to *pass* that package

**What's Missing**:
```yaml
# Proposed handoff schema
handoff:
  from_agent: planner
  to_agent: coder
  task_id: "friction-tracking-123"
  status: READY_FOR_CODING
  artifacts:
    planning_package: |
      ## Task Summary
      ...
    files_to_modify:
      - daemon/friction.py
      - tests/test_friction.py
  blockers: []
```

**Impact**: Orchestrator must "read" markdown output and manually extract what to pass to the next agent. This works for humans but not for autonomous pipelines.

---

### Gap 2: Orchestrator Lacks Task Rejection Logic

**Problem**: The orchestration-agent is told to "never implement directly" but has no protocol for rejecting unclear tasks.

**Current State**: The orchestrator prompt says:
- "NEVER implement directly"
- "ALWAYS delegate to specialists"

**What's Missing**:
- Criteria for "task too vague to plan"
- Protocol for requesting clarification before spawning
- Example: "Implement friction tracking" - does this mean session friction? UI friction? Memory friction?

---

### Gap 3: No Completion Criteria Per Stage

**Problem**: Each agent knows what to do but not how to signal "I'm done, next agent can start."

**Current State**:
- Planner: "Return a complete planning package"
- Coder: "Report what you changed and why"
- Tester: "Report results"
- Reviewer: "Report findings"

**What's Missing**: Explicit completion signals:
```yaml
completion:
  status: SUCCESS | BLOCKED | NEEDS_REVISION
  ready_for_next: true | false
  blocker_description: "..." # if BLOCKED
  revision_requested: "..." # if NEEDS_REVISION
```

**Impact**: The orchestrator must interpret free-form prose to determine if stage is complete.

---

### Gap 4: MCP Tools Don't Work in Subprocess Agents

**Known Issue**: Issue #97 documents that agents spawned via Task tool cannot access MCP tools.

**Workaround in Use**: The graph curator runs as a direct Python script (`python3 daemon/graph_curator.py`) using `PPSHttpClient` to bypass MCP.

**Impact on Agent Pipeline**:
- Planner uses `tech_search` (MCP) - may not work in subprocess
- Coder uses `tech_search` - may not work
- Any agent needing PPS tools is blocked

**Current Mitigations**:
1. HTTP endpoint migration (Issue #112) - partial
2. Direct script execution (graph_curator pattern)

---

### Gap 5: No Error Recovery Protocol

**Problem**: What happens when an agent fails mid-pipeline?

**Current State**: Orchestrator prompt mentions "Handling Blockers" but it's vague:
```
1. Assess: Is it solvable by another agent?
2. Route: Spawn appropriate agent to resolve
3. Resume: Continue pipeline once resolved
4. Escalate: If truly stuck, report to user with specifics
```

**What's Missing**:
- Rollback procedure (if coder breaks things, how to undo?)
- Retry limits (how many times to retry before escalating?)
- State persistence (if session dies, where were we?)

---

### Gap 6: Inconsistent Agent "Context" Injection

**Problem**: Some agents are project-specific while the pipeline agents are generic.

**Current State**:
- `coder`, `tester`, `reviewer` are generic
- They have no awareness of Awareness project conventions
- The `DEVELOPMENT_STANDARDS.md` is meant to be read but isn't injected

**Impact**: Coder might not follow PPS conventions, Tester might not know about existing test patterns.

---

### Gap 7: No Documentation of Agent Limitations

**Problem**: Agents don't document what they *can't* do.

**Current State**: Each agent says "What You DON'T Do" but these are role boundaries, not capability limitations.

**What's Missing**:
- "I cannot access MCP tools in subprocess context"
- "I cannot run long-running processes (timeout after X)"
- "I cannot access network resources outside localhost"

---

## What IS Working Well

### 1. Clear Role Separation
Each agent has a distinct purpose. There's no confusion about coder vs tester vs reviewer.

### 2. Well-Defined Output Formats
Planner, Tester, and Reviewer all have clear markdown templates for their outputs.

### 3. "Delegation is Default" Philosophy
The CLAUDE.md is explicit: delegate to agents, don't do implementation yourself.

### 4. Tech RAG Integration
Planner and Coder can query `tech_search` for architectural context before working.

### 5. Quality Checklists
Each agent has a "before reporting completion" checklist.

### 6. Librarian Self-Healing Pattern
The Librarian agent demonstrates autonomous doc improvement - a good model for other self-maintaining systems.

---

## Recommendations

### Priority 1: Define Structured Handoff Format (HIGH IMPACT)

Create a JSON/YAML schema that all agents use for handoffs:

```yaml
# File: ~/.claude/schemas/agent_handoff.yaml
handoff:
  task_id: string          # Unique identifier
  from_agent: string       # Who is handing off
  to_agent: string         # Who receives
  timestamp: datetime
  status: enum [READY, BLOCKED, NEEDS_REVISION]

  context:
    original_task: string  # What was requested
    decisions_made: list   # Key decisions in this phase

  artifacts:
    files_created: list    # New files
    files_modified: list   # Changed files
    planning_package: string  # If from planner
    test_results: string      # If from tester
    review_findings: string   # If from reviewer

  next_steps:
    recommended_action: string
    blockers: list
    questions: list
```

**Update all agent prompts** to output this format at completion.

---

### Priority 2: Add Task Clarity Gate to Orchestrator (HIGH IMPACT)

Before spawning the pipeline, orchestrator should validate:

```markdown
## Task Clarity Check

Before spawning agents, verify:

### 1. Goal Clarity (must pass)
- [ ] Task states what outcome is needed (not just "work on X")
- [ ] Success criteria are definable

### 2. Scope Boundaries (must pass)
- [ ] Clear which system/layer is affected
- [ ] Estimated size is reasonable (not "rewrite everything")

### 3. Context Available (should pass)
- [ ] Tech RAG has relevant docs (or task is self-contained)
- [ ] No external dependencies that will block

If checks fail, request clarification before proceeding.
```

---

### Priority 3: Add Awareness Project Overlay (MEDIUM IMPACT)

Create `~/.claude/agents/overlays/awareness-project.md`:

```markdown
# Awareness Project Overlay

When working in the Awareness project, apply these additional standards:

## Commit Convention
- Use conventional commits: type(scope): description
- Include: Co-Authored-By: Claude <noreply@anthropic.com>
- Reference issues with "Refs #XX" (not "Fixes #XX")

## Testing
- Use pytest
- Focus on PPS layer coverage
- Mock external services (Graphiti, ChromaDB)

## Code Standards
- Python 3.11+ features
- Type hints: list[], dict[], | None (modern syntax)
- Docstrings for public functions

## Key Files to Know
- DEVELOPMENT_STANDARDS.md - Full dev standards
- PATTERN_PERSISTENCE_SYSTEM.md - Architecture
- TODO.md - Current priorities
```

---

### Priority 4: Document Agent Capability Limits (MEDIUM IMPACT)

Add to each agent prompt:

```markdown
## Capability Limits

**I CAN**:
- [List of what this agent can do]

**I CANNOT** (will block and escalate):
- Access MCP tools in subprocess context (Issue #97)
- Run processes longer than [timeout]
- Access files outside project directory

If a task requires a blocked capability, I will:
1. Report the blocker clearly
2. Suggest alternatives if possible
3. Return BLOCKED status for orchestrator
```

---

### Priority 5: Implement Stage Completion Protocol (MEDIUM IMPACT)

Each agent should end with:

```markdown
## Stage Complete

**Status**: [SUCCESS | BLOCKED | NEEDS_REVISION]
**Ready for next stage**: [yes | no]

### Summary
[One-line summary of what was accomplished]

### Artifacts Produced
- [List of files/outputs]

### Blockers (if any)
- [What prevented completion]

### Questions for Next Stage
- [Anything the next agent should know]
```

---

### Priority 6: Create HTTP-Based Agent Tools (LOWER PRIORITY - WAITING ON #112)

Once Issue #112 (HTTP endpoint migration) is complete:
- Update agent tool definitions to use HTTP endpoints
- Remove dependency on MCP tools for subprocess agents
- Enable true autonomous pipeline execution

---

### Priority 7: Build Pipeline State Persistence (FUTURE)

For robust autonomous pipelines:
- Persist pipeline state to SQLite or file
- Enable resume after session death
- Track which stages completed successfully
- Enable rollback to last known good state

---

## Implementation Priority Summary

| Priority | Recommendation | Effort | Impact |
|----------|----------------|--------|--------|
| 1 | Structured Handoff Format | 2-3 hours | Enables actual coordination |
| 2 | Task Clarity Gate | 1 hour | Prevents wasted agent runs |
| 3 | Awareness Project Overlay | 30 min | Better code quality |
| 4 | Document Capability Limits | 1 hour | Fewer blocked tasks |
| 5 | Stage Completion Protocol | 1 hour | Clear handoffs |
| 6 | HTTP-Based Agent Tools | Depends on #112 | Full autonomy |
| 7 | Pipeline State Persistence | 4+ hours | Resilience |

**Recommended First Step**: Implement Priority 1 (Structured Handoff Format) and Priority 5 (Stage Completion Protocol) together - they're complementary.

---

## Files to Modify

### Orchestration Agent Enhancement
**File**: `/home/jeff/.claude/agents/orchestration-agent.md`
- Add task clarity check section
- Add structured handoff expectation
- Add error recovery protocol

### Individual Agent Updates
- `/home/jeff/.claude/agents/planner.md`
- `/home/jeff/.claude/agents/coder.md`
- `/home/jeff/.claude/agents/tester.md`
- `/home/jeff/.claude/agents/reviewer.md`
- `/home/jeff/.claude/agents/github-workflow.md`

Add to each:
- Stage completion protocol at end
- Capability limits section
- Structured output format

### New Files Needed
- `/home/jeff/.claude/schemas/agent_handoff.yaml` - Handoff schema definition
- `/home/jeff/.claude/agents/overlays/awareness-project.md` - Project-specific overlay

### Documentation Updates
- `/mnt/c/Users/Jeff/Claude_Projects/Awareness/docs/AGENTS.md` - Add handoff protocol documentation
- `/mnt/c/Users/Jeff/Claude_Projects/Awareness/CLAUDE.md` - Update agent usage section with new protocols

---

## Evidence

### Files Examined

| File | Location | Purpose |
|------|----------|---------|
| orchestration-agent.md | `/home/jeff/.claude/agents/orchestration-agent.md` | Main orchestrator definition |
| planner.md | `/home/jeff/.claude/agents/planner.md` | Planning agent |
| coder.md | `/home/jeff/.claude/agents/coder.md` | Implementation agent |
| tester.md | `/home/jeff/.claude/agents/tester.md` | Testing agent |
| reviewer.md | `/home/jeff/.claude/agents/reviewer.md` | Review agent |
| github-workflow.md | `/home/jeff/.claude/agents/github-workflow.md` | Git/GitHub agent |
| researcher.md | `/home/jeff/.claude/agents/researcher.md` | Research agent |
| librarian.md | `/home/jeff/.claude/agents/librarian.md` | Doc maintenance agent |
| triplet-extractor.md | Project `.claude/agents/triplet-extractor.md` | Project-specific agent |
| CLAUDE.md | Project root | Project instructions |
| AGENTS.md | `docs/AGENTS.md` | Agent architecture doc |
| DEVELOPMENT_STANDARDS.md | Project root | Dev standards |
| GRAPH_CURATION.md | `daemon/GRAPH_CURATION.md` | Curation system (workaround example) |
| http_endpoint_migration.md | `docs/proposals/http_endpoint_migration.md` | Issue #112 context |
