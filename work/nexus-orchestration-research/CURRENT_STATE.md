# Agent Orchestration: Current State & Design Document

**Updated**: 2026-02-18 (morning session, Lyra)
**Status**: Research complete, ready for prioritized implementation
**Context**: Compaction-safe summary of all orchestration work to date

---

## What We Have Today

### The Forestry Octet (Built Overnight 2026-02-17/18)

Eight skills in `.claude/skills/` that constitute a complete session methodology:

| # | Skill | Purpose | When |
|---|-------|---------|------|
| 0 | `/prescribe` | Intention-setting before work begins | Session start, before canopy |
| 1 | `/canopy` | Survey current state — what's living, what's stale | After prescribe |
| 2 | `/deadwood` | Classify against intended topology (not just reachability) | When codebase has drift |
| 3 | `/coppice` | Root bank review — promote ready, retire permanent | When roots need tending |
| 4 | `/mycelium` | Signal bus — the connecting tissue that makes the sequence coherent | Cross-skill state |
| 5 | `/undergrowth` | Two modes: probe (deliberate feasibility) vs wild (convergent evolution) | Exploration |
| 6 | `/greenwood` | Read season before planting — don't build what's not ready | Pre-build check |
| 7 | `/grove` | Tend relationships at session end (complement to canopy's exterior survey) | Session end |

**Note on Octet vs Sextet**: Nexus originally showed us 6 skills (Sextet). Our overnight work extended to 8 (Octet) with the addition of `/mycelium` (the signal bus root system) and `/grove` (the closing complement to `/canopy`). The Octet is complete and committed.

**Key design**: `/mycelium` solves the root system gap Nexus identified — shared state between skills so deadwood archives can be found by coppice, etc.

---

## What Nexus Has Now (Feb 2026 — Updated)

Their cognitive-framework (shayesdevel/cognitive-framework) has evolved since our January research. New findings from today's scan:

### New: P12 Mycelial Holarchy

Added to their orchestration patterns alongside P1/P6/P9:

| Pattern | Agents | Speedup | Use When |
|---------|--------|---------|----------|
| P1: Parallel Domain | 2-4 | 4x | Independent tasks, clear boundaries |
| P6: Wave-Based | 4-8 | 1.5-4x | Sequential dependencies, phased |
| P9: Hierarchical | 12+ | 2-4x | Large scale (use Effective P9) |
| **P12: Mycelial Holarchy** | **Cell-based** | **2-6x** | **Multi-session arcs, knowledge-first deps** |

P12 is their flagship pattern for sustained multi-session work. Cells are persistent work units that communicate via "mycelium" (shared knowledge bus). Our `/mycelium` skill name was independently convergent — same metaphor, different implementation.

### New: T0-T3 Task Tiers

Before choosing an orchestration pattern, they classify task complexity:

| Tier | Characteristics | Planning |
|------|-----------------|----------|
| T0 Trivial | Single file, <10 lines | Direct execution |
| T1 Routine | 2-3 files, clear path | Quick scan, execute |
| T2 Standard | Multiple files, decisions | Light plan, 1-2 agents |
| T3 Complex | Architectural, unknowns | Full plan mode, P6/P9 |

Also: Request type classification — "Verify..." = read-only, "Direct answer:" = immediate, "Implement..." = classify tier first.

### New: PreCompact Hook

Critical new addition — `pre-compact-nexus.sh` fires BEFORE Claude Code context compaction:
- Captures state snapshot: session number, active threads, pending decisions, recent focus
- Saves to `nexus/ambient/pre-compact-state.json` for recovery
- Outputs systemMessage with state summary so post-compaction context has recovery info
- Logs to `nexus/ambient/compaction-log.jsonl`

**This directly addresses Jeff's compaction concern.** We should adopt this.

### New: Friction-Guard (Blocking)

`friction-guard.sh` — PreToolUse hook on Write/Edit operations:
- Queries daemon for friction lessons matching the file path
- **BLOCKS critical-severity matches** (continue=false)
- Warns on high-severity matches
- Allows low/medium to pass silently

This is the prevention side of friction learning — not just injection, but active blocking.

### New: TaskCompleted Quality Gate

`task-completed.sh` — TaskCompleted hook:
- Reads `test-results.json` for failures/errors
- **BLOCKS task completion** when tests are failing
- Warns about uncommitted changes

### New: Substrate-Aware Friction

`friction-inject.sh` now detects whether it's a daemon session vs interactive session:
- Daemon sessions: Show identity/grounding lessons too
- Interactive sessions: Filter to technical lessons only (api, unity, code, bug, error patterns)

### Hooks Architecture (Complete)

| Hook | Event | Purpose |
|------|-------|---------|
| `friction-inject.sh` | UserPromptSubmit | Inject friction lessons per prompt |
| `friction-guard.sh` | PreToolUse (Write/Edit) | Warn/block based on severity |
| `pre-tool-task.sh` | PreToolUse (Task) | Auto-inject friction into sub-agent prompts |
| `post-tool-task.sh` | PostToolUse (Task) | Context pressure monitoring |
| `pre-compact-nexus.sh` | **PreCompact** | Save state before compaction |
| `session-end-nexus.sh` | StopHook | Session end cleanup |
| `task-completed.sh` | **TaskCompleted** | Quality gate — block if tests fail |
| `session-start-cleanup.sh` | UserPromptSubmit | Session start state cleanup |
| `fathom-unity-path-guard.sh` | PreToolUse | Domain-specific guard |
| `friction-applied-signal.sh` | PostToolUse | Track friction application |

---

## What We Need to Build

### Priority 1: PreCompact Hook (High Value, Low Effort, ~2 hours)

Jeff expressed concern about compaction. They've solved this already. Adopt it:

**File**: `.claude/hooks/pre-compact-lyra.sh`

What it does:
- Captures: current crystal (continuity state), active work from FOR_JEFF_TODAY.md, open GitHub issues, recent git log
- Saves to `entities/lyra/pre-compact-state.json`
- Outputs systemMessage with recovery summary so post-compaction Claude knows where to start

**Our version** will use PPS crystals and FOR_JEFF_TODAY instead of their ambient index.

### Priority 2: Context Pressure Tracking (High Value, Low Effort, ~1 hour)

We already have `.claude/hooks/` directory. Add:

**Pre-tool-task.sh**: Track agent spawns to `.claude/.session-state/agents-spawned.jsonl`
**Post-tool-task.sh**: Graduate warnings at 4+ and 6+ agents spawned

This is verbatim from their DESIGN.md already written. Just needs creating the files.

### Priority 3: Agent-Type Hooks for Orchestration (Medium, ~3 hours)

When orchestrating agents, inject entity context via `updatedInput`:
- Query PPS at `localhost:8201/context/agent` (endpoint doesn't exist yet)
- Add that endpoint to server_http.py first (2 hours)
- Then update hook to use it (30 min)

**Note**: This requires the HTTP endpoint migration work (#112) to be further along.

### Priority 4: Friction Learning System (High Value Long-term, ~2 weeks)

Their full friction pipeline:
1. Capture friction in markdown (FRIC-XXX format)
2. Store in SQLite with FTS5
3. Auto-inject via hooks

We have architecture designed in DESIGN.md. The delta from their current state:
- They've added write-blocking (friction-guard) — we should too
- Their daemon injection is substrate-aware — we should do the same (daemon vs terminal)

### Priority 5: Task Tiers (Easy, Documentation Only, ~30 min)

Add T0/T1/T2/T3 classification to our orchestration workflow.
Write `docs/orchestration/tiers.md` — adapt from their CLAUDE.md tier table.

### Priority 6: P12 Evaluation (Longer term)

Their P12 Mycelial Holarchy is mature but complex — needs a Nexus daemon running.
Our equivalent might be: reflection cycles as cells, PPS as the mycelium.
Not a near-term build. Flag for design conversation with Jeff and Nexus.

---

## Our Architecture Gap vs Theirs

| Area | Nexus | Us | Gap |
|------|-------|-----|-----|
| Hook infra | ✅ Complete (9 hooks) | ⚠️ Minimal (1-2 hooks) | Adopt their hook set |
| Friction injection | ✅ UserPromptSubmit + updatedInput | ❌ None | Build friction-inject + pre-tool-task |
| Write blocking | ✅ friction-guard blocks writes | ❌ None | Build friction-guard |
| Compaction safety | ✅ pre-compact hook | ❌ None | **Build pre-compact-lyra today** |
| Task completion gate | ✅ TaskCompleted hook | ❌ None | Build task-completed |
| Context pressure | ❌ Not built (designed) | ✅ DESIGN.md has it | Build from our design |
| Orchestration patterns | ✅ P1/P6/P9/P12 documented | ⚠️ P1/P6/P9 in docs | Add T0-T3 tiers |
| Forestry methodology | ✅ Sextet | ✅ **Octet** | We're ahead here |
| Memory system | ⚠️ friction logs + ambient | ✅ 5-layer PPS | We're ahead here |
| Embodied identity | ❌ Not their focus | ✅ Full PPS | Different architecture |

---

## Recommended Build Order

**This week (now, while Jeff is on phone call):**
1. ✅ PreCompact hook — `.claude/hooks/pre-compact-lyra.sh` (~1 hour)
2. ✅ Context pressure hooks — `pre-tool-task.sh` + `post-tool-task.sh` (~1 hour)

**This week (with Jeff):**
3. T0-T3 tier documentation (~30 min)
4. `/orchestration-select` skill — adapt from their version (~1 hour)

**Next week:**
5. PPS `/context/agent` HTTP endpoint (~2 hours)
6. Hook-based agent context injection (requires above) (~1 hour)
7. Friction storage layer in PPS (~3 hours)
8. Friction injection hooks + guard (~2 hours)

**Later:**
9. P12 design conversation with Nexus
10. TaskCompleted quality gate

---

## Key Insight: Their System vs Ours

**Nexus**: Daemon-centric. Everything flows through localhost:8080. Hooks query daemon. Daemon has rich state. Sessions are lightweight consumers of daemon state.

**Awareness**: PPS-centric. Everything flows through MCP tools and localhost:8201. Sessions have full entity identity. Daemon handles reflection and Discord, not orchestration.

**Our hybrid path**: Use their hook patterns + query our PPS HTTP instead of their daemon. The `updatedInput` pattern is hook-agnostic — it works with any backend. Build hooks that query PPS just as their hooks query the Nexus daemon.

---

## Files to Create (Immediate)

```
.claude/hooks/
├── pre-compact-lyra.sh          # NEW — save state before compaction
├── pre-tool-task.sh             # NEW — track agent spawns + friction inject
├── post-tool-task.sh            # NEW — context pressure warnings
└── lib/
    └── pps-utils.sh             # NEW — shared PPS HTTP utilities

.claude/.session-state/          # NEW directory, gitignored
└── agents-spawned.jsonl         # Created by hooks at runtime

docs/orchestration/
├── tiers.md                     # NEW — T0-T3 classification guide
└── patterns.md                  # ALREADY EXISTS (from DESIGN.md)

.claude/skills/orchestration-select/  # NEW skill — adapt from nexus
└── SKILL.md
```

---

## Reference

- Nexus repo: `shayesdevel/cognitive-framework` (cloned at `/tmp/cognitive-framework/`)
- Our DESIGN.md: `work/nexus-orchestration-research/DESIGN.md`
- Our FINDINGS.md: `work/nexus-orchestration-research/artifacts/FINDINGS.md`
- Original learnings: `work/nexus-learnings/key-findings.md`
- Forestry Octet: `.claude/skills/{prescribe,canopy,deadwood,coppice,mycelium,undergrowth,greenwood,grove}/`
