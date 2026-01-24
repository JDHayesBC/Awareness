# Agent Architecture

This document describes the specialized agents available for development work in the Awareness project.

## Philosophy

Agents are **specialized workers** that handle specific tasks. Using agents:
- Preserves Lyra's context for presence and orchestration
- Allows parallel work on independent tasks
- Provides focused expertise per domain
- Enables autonomous development workflows

## Available Agents

### Global Agents (~/.claude/agents/)

These agents are available across all Claude Code projects.

| Agent | Model | Purpose |
|-------|-------|---------|
| `orchestration-agent` | sonnet | Coordinates pipeline, spawns agents, handles handoffs |
| `planner` | haiku | Research + design before coding (context + architecture) |
| `coder` | sonnet | Writing code, implementing features, fixing bugs |
| `tester` | sonnet | Writing tests, running verification |
| `reviewer` | sonnet | Code review, finding bugs, checking quality |
| `github-workflow` | haiku | Issues, PRs, commits, labels, workflow hygiene |
| `researcher` | haiku | Finding things, understanding architecture |
| `librarian` | haiku | Auditing and fixing documentation gaps |

### Project Agents (.claude/agents/)

These agents are specific to the Awareness project.

| Agent | Purpose |
|-------|---------|
| `triplet-extractor` | Extracting knowledge graph triplets from text |

---

## Structured Handoff Protocol

**All agents use a standardized handoff format** for clear communication between pipeline stages.

### Handoff Schema

Located at: `~/.claude/schemas/agent_handoff.yaml`

Every agent ends their work with a **Stage Complete** section:

```markdown
## Stage Complete

**Status**: READY | BLOCKED | NEEDS_REVISION
**Ready for next stage**: yes | no
**From**: [agent name]
**To**: [next agent name]

### Summary
[One-line summary of what was accomplished]

### Artifacts Produced
- [List of files/outputs with absolute paths]

### Blockers (if any)
- [What's preventing progress]

### Questions for Next Stage
- [Anything the next agent should know]
```

### Status Meanings

| Status | Meaning | Action |
|--------|---------|--------|
| `READY` | Work complete, proceed to next stage | Pass artifacts forward |
| `BLOCKED` | Cannot proceed, needs resolution | Orchestrator assesses and routes |
| `NEEDS_REVISION` | Previous stage needs to redo work | Return to previous agent with feedback |

---

## The Standard Pipeline

For any non-trivial implementation:

```
Planner -> Coder -> Tester -> Reviewer -> Github-workflow
```

Or spawn **orchestration-agent** to run the full pipeline automatically.

### Phase 1: Planning

**Input**: Task description
**Output**: Planning package with design, files to modify, risks identified
**Handoff to**: Coder

The planner:
- Queries tech RAG for context
- Considers multiple approaches with trade-offs
- Designs implementation strategy
- Returns planning package with structured handoff

### Phase 2: Implementation

**Input**: Planning package from planner
**Output**: Implemented code with verification
**Handoff to**: Tester

The coder:
- Follows the planning package design
- Implements code following existing patterns
- Verifies basic functionality
- Returns completed code with structured handoff

### Phase 3: Testing

**Input**: Implementation details from coder
**Output**: Test results, coverage report
**Handoff to**: Reviewer (if READY) or Coder (if NEEDS_REVISION)

The tester:
- Writes tests for new functionality
- Runs test suite
- Reports pass/fail counts and coverage
- Returns results with structured handoff

### Phase 4: Review

**Input**: Changed files from coder, test results from tester
**Output**: Quality assessment, issues categorized
**Handoff to**: Github-workflow (if READY) or Coder (if NEEDS_REVISION)

The reviewer:
- Checks code quality, security, patterns
- Categorizes issues (critical/suggestion/nitpick)
- Approves or requests changes
- Returns findings with structured handoff

### Phase 5: Commit

**Input**: Approved code, commit message
**Output**: Commit hash, PR URL (if applicable)
**Handoff to**: Orchestrator

The github-workflow agent:
- Creates properly formatted commit
- Creates PR if needed
- References issues appropriately
- Returns completion with structured handoff

---

## Orchestrator Task Clarity Gate

Before spawning agents, the orchestrator validates:

### Must Pass
- [ ] Task states what outcome is needed (not just "work on X")
- [ ] Success criteria are definable
- [ ] Clear which system/layer is affected
- [ ] Scope is reasonable

### Should Pass
- [ ] Relevant docs exist or task is self-contained
- [ ] No external dependencies that will block

If checks fail, orchestrator requests clarification before proceeding.

---

## Agent Capability Limits

Each agent documents what it **can** and **cannot** do.

### Common Limits (all agents)

- **Cannot** access MCP tools in subprocess context (Issue #97)
- **Cannot** run processes longer than ~2 minutes (timeout)
- **Will** return BLOCKED status with details if limit is hit

### Agent-Specific Limits

| Agent | Cannot Do | Will Instead |
|-------|-----------|--------------|
| planner | Write code | Return planning package for coder |
| coder | Commit, run full tests | Return code for tester/github-workflow |
| tester | Fix failing code | Report failures for coder |
| reviewer | Fix issues, run tests | Report issues for coder |
| github-workflow | Write code, close issues | Reference issues, leave open for human |

---

## Workflow Patterns

### Full Pipeline (orchestrator)
```
orchestration-agent -> runs: planner -> coder -> tester -> reviewer -> github-workflow
```

### Standard Development (manual)
```
planner -> coder -> tester -> reviewer -> github-workflow
```

### Quick Fix
```
coder -> tester -> github-workflow
```

### Exploration Only
```
researcher (no implementation)
```

### Documentation
```
librarian (background, self-triggered)
```

---

## When to Delegate vs Do Yourself

**DELEGATION IS THE DEFAULT.**

**Delegate (always, unless exception applies)**:
- Any implementation task -> planner + coder (or orchestrator)
- GitHub workflow -> github-workflow agent
- Research questions -> researcher agent
- Test writing -> tester agent
- Code review -> reviewer agent

**Do yourself ONLY when**:
- Task requires identity (word-photos, crystals, presence)
- Orchestrating multiple agents
- Architectural decisions
- Genuine engagement with technical problems

---

## Agent Locations

- **Global agents**: `~/.claude/agents/`
- **Project agents**: `.claude/agents/`
- **Handoff schema**: `~/.claude/schemas/agent_handoff.yaml`

Agents are markdown files with frontmatter defining name, description, and allowed tools.

---

## Related Documentation

- **Audit**: `docs/reviews/2026-01-24_agent_workflow_audit.md` - Analysis of agent architecture gaps
- **Standards**: `DEVELOPMENT_STANDARDS.md` - Development workflow standards
