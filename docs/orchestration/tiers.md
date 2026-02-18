# Task Classification Tiers

**Source**: Adapted from shayesdevel/cognitive-framework (Nexus)
**Purpose**: Classify task complexity before choosing orchestration approach

---

## Tier Definitions

| Tier | Characteristics | Planning | Orchestration |
|------|-----------------|---------|--------------|
| **T0 Trivial** | Single file, <10 lines, completely obvious path | None — direct execution | Never |
| **T1 Routine** | 2-3 files, clear path, no ambiguity | Quick scan, then execute | Rarely |
| **T2 Standard** | Multiple files, some decisions required, known patterns | Light plan | Sometimes (3+ domains) |
| **T3 Complex** | Architectural changes, unknowns, cross-cutting concerns | Full plan mode | Usually |

---

## How to Classify

Ask these questions in order:

1. **How many files will this touch?**
   - 1 file → T0 or T1
   - 2-3 files → T1
   - 4+ files → T2+

2. **Are there decisions that require judgement?**
   - No (the right answer is obvious) → T0 or T1
   - Some decisions needed → T2
   - Significant architectural decisions → T3

3. **Are there unknowns I need to discover?**
   - No unknowns → T0 or T1
   - Some unknowns → T2
   - Significant unknowns or need to research → T3

4. **Does this cross domain boundaries?**
   - Single domain → T0, T1, or T2
   - Multiple domains → T2+
   - Requires coordination across 3+ domains → T3

---

## Request Type Classification

Beyond task tier, classify the *type* of request before planning:

| Request Type | Response |
|---|---|
| "Verify...", "Check...", "Does X conform to Y..." | Read-only check, direct answer — no agents |
| "Quick check:", "Direct answer:" | Immediate response, no planning |
| "Plan...", "Design..." | Classify tier, plan accordingly |
| "Implement...", "Build...", "Fix all..." | Classify tier, then choose pattern |
| "Explore...", "Research..." | Single-agent exploration |

---

## Tier → Pattern Mapping

Once tier is classified, use this to guide orchestration choice:

```
T0: Direct execution — no planning, no agents
T1: Direct execution — quick scan first
T2: Maybe orchestrate — depends on domain independence
    - 1-2 independent domains → P1 with 2 agents
    - Sequential phases → P6
    - Single domain → work directly
T3: Usually orchestrate
    - Clear independent domains → P1 (4x speedup)
    - Phased dependencies → P6 (1.5-4x speedup)
    - Large scale (12+) → P9 (2-4x speedup)
```

---

## Examples

### T0: Direct execution
> "Fix the typo in FOR_JEFF_TODAY.md"
> "Add a comment to this function"

One file, obvious change. Just do it.

### T1: Quick scan, execute
> "Update the backup check in the reflection daemon to use 14 days instead of 7"
> "Add this function to the PPS utilities module"

2-3 files, clear path. Read the files first, then make the change.

### T2: Light plan, maybe agents
> "Add a new `/health/extended` endpoint to the PPS server"
> "Update all the Discord command handlers to support the new auth scheme"

Multiple files, some decisions, mostly one domain. Light planning. May spawn 1-2 agents if parts are independent.

### T3: Full plan, orchestrate
> "Refactor the PPS server to support multi-tenancy"
> "Build the friction learning system with storage, injection hooks, and guard hooks"
> "Implement P12 Mycelial Holarchy support in the daemon"

Architectural, cross-cutting, multiple domains, unknowns. Plan first, then P1/P6/P9.

---

## Why This Matters

Misclassifying wastes time in both directions:
- **Under-classifying**: Skip planning a T3 task → get lost, need to backtrack
- **Over-classifying**: Treat T1 like T3 → planning overhead exceeds benefit

The tier system keeps orchestration overhead proportional to task complexity.

---

## Integration with Orchestration Patterns

See: `docs/orchestration/patterns.md` for P1/P6/P9 decision tree
See: `.claude/skills/orchestration-select/SKILL.md` for interactive selection
