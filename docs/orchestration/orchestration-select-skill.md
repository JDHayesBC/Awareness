---
name: orchestration-select
description: |
  Select the appropriate orchestration pattern for multi-agent work.
  When to use: Task has 3+ distinct components, or deciding whether to spawn agents.
  NOT for: Simple single-file changes, quick Q&A, tasks under 30 minutes.
---

# Orchestration Pattern Selection

> What are we building? How much of it? How interdependent?

## Step 1: Classify Task Tier

| Tier | Characteristics | Approach |
|------|-----------------|---------|
| T0 Trivial | Single file, <10 lines | Direct execution |
| T1 Routine | 2-3 files, clear path | Execute directly |
| T2 Standard | Multiple files, some decisions | Light plan, maybe 1-2 agents |
| T3 Complex | Architectural, unknowns, coordination | Full plan mode, orchestrate |

Request types: "Verify..." = read-only direct answer. "Implement..." = classify tier first.

## Step 2: Choose Pattern

```
Multi-agent needed? (T2 with 3+ domains, or T3)
  No  → Work directly
  Yes → Tasks fully independent? → Yes → P1 (2-4 agents, 4x speedup)
       → No → 12+ agents? → Yes → P9 (hierarchical, 2-4x)
              → No → Complex deps? → Yes → P6 (4-8 agents, 1.5-4x)
                                   → No → P1
```

## Pattern Reference

**P1: Parallel Domain** (2-4 agents, ~4x speedup)
Use when tasks have no dependencies, clear file boundaries, distinct domains.
Spawn all agents simultaneously. Each owns exclusive file domains.
Example: Backend API + Frontend UI + Documentation — all independent.

**P6: Wave-Based** (4-8 agents, 1.5-4x speedup)
Use when sequential dependencies exist. Work phases: Foundation → Implementation → Integration.
Example: Database schema → API layer → UI → Tests.

**P9: Hierarchical** (12+ agents, 2-4x speedup)
For large-scale work with multiple major domains. Use "Effective P9" (many parallel agents, no sub-orchestrators) for most cases — true 3-level hierarchy only when genuinely needed.

## Pre-Spawn Checklist

Before calling Task tool:
- [ ] Pattern selected: P1 / P6 / P9
- [ ] Task tier: T0/T1/T2/T3
- [ ] Agent count and domains named
- [ ] File boundaries declared (EXCLUSIVE/MODIFY/READ)
- [ ] Validation commands specified per agent
- [ ] Success criteria defined

## Trust Signal Matching

| Signal | Scope |
|--------|-------|
| "Help me with X" | Cautious: 1-2 agents |
| "Fix these issues" | Moderate: 3-4 agents |
| "Go be agentic" / "I trust you" | Expand: 5-7+ agents |
| "Aggressive parallel" | Maximum viable |

## Context Pressure

Hooks auto-track spawned agents:
- 4+ agents → Warning injected
- 6+ agents → Critical — mark todos NOW before context fills

## When NOT to Orchestrate

Task < 30 min, exploratory work, sequential-only, single domain, high coordination overhead.
In these cases, just work directly.

## Awareness-Specific Notes

- PPS access in sub-agents: HTTP at `localhost:8201` (agents can't use MCP tools)
- Context injection: `inject_agent_context.py` auto-injects entity context into sub-agent prompts
- Agent pressure: `monitor_agent_pressure.py` tracks spawns and warns at 4+/6+ thresholds
- Sub-agents should commit their own work with clear messages referencing the orchestration
