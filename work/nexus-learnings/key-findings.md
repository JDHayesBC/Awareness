# Key Findings: Nexus/cognitive-framework

**Date**: 2026-01-24
**Source**: shayesdevel/cognitive-framework (private repo)
**Version**: 3.3.0

---

## Executive Summary

Steve/Nexus's cognitive-framework is a mature multi-agent orchestration system with:
- **Hook-based friction injection** (not agent instructions)
- **Context pressure monitoring** (agent spawn tracking)
- **True hierarchical spawning** via `claude -p` workaround
- **Coherence tracking** via daemon API
- **Production-validated patterns** with quantified speedups (2-4x)

---

## 1. Tool Access in Sub-Agents

### The Limitation (CONFIRMED)

Sub-agents spawned via Claude Code's Task tool:
1. **Cannot access MCP tools** - No GitHub, no PPS, no custom MCP servers
2. **Cannot spawn their own sub-agents** - Task tool is unavailable to them

This is an **intentional Claude Code design choice**, not a bug.

### Our Solution vs Theirs

| Approach | Us (Awareness) | Them (Nexus) |
|----------|----------------|--------------|
| PPS tools | HTTP fallback (localhost:8201) | Daemon API (localhost:8080) |
| GitHub | Not solved | Not solved (main terminal only) |
| Deep hierarchy | Not solved | `claude -p` via Bash |

### The `claude -p` Workaround

For true hierarchical orchestration (P9-experimental), they spawn workers via:

```bash
claude -p "$BRIEF_CONTENT" --dangerously-skip-permissions --output-format json
```

**Trade-offs**:
- ✅ True hierarchy (sub-orchestrators can spawn workers)
- ❌ No context sharing (each worker is isolated)
- ❌ Higher API cost (separate API call chain per worker)
- ❌ Complex error handling (exit codes, JSON parsing)

---

## 2. Orchestration Patterns

### Pattern Summary

| Pattern | Agents | Use Case | Speedup |
|---------|--------|----------|---------|
| **P1: Parallel Domain** | 2-4 | Independent tasks | 4x |
| **P6: Wave-Based** | 4-8 | Dependent tasks in waves | 1.5-4x |
| **P9: Hierarchical** | 12+ | Large scale (conceptual) | 2-4x |
| **P9-Experimental** | 20+ | True hierarchy via `claude -p` | 2-4x |

### Key Principles

1. **Specialists > Generalists** - Domain-focused agents outperform
2. **Parallelism > Sequential** - When boundaries are clear
3. **Context Protection** - Orchestrator delegates ALL coding work
4. **Clear Boundaries** - File ownership declared per agent

### Decision Tree

```
Multi-agent needed? → No → Work directly
                   → Yes → Tasks independent? → Yes → P1
                                              → No → 12+ agents? → Yes → P9
                                                                 → No → Complex deps? → Yes → P6
                                                                                       → No → P1
```

---

## 3. Hook-Based Friction System

### Architecture

```
settings.json hooks → Pre/Post tool hooks → Daemon API → Friction lessons
```

### Key Hooks

| Hook | Event | Purpose |
|------|-------|---------|
| `friction-inject.sh` | UserPromptSubmit | Inject context-aware lessons |
| `friction-guard.sh` | PreToolUse | Warn/block based on severity |
| `pre-tool-task.sh` | PreToolUse (Task) | Auto-inject lessons into sub-agent prompts |
| `post-tool-task.sh` | PostToolUse (Task) | Context pressure monitoring |

### Friction Injection into Sub-Agents

The key innovation: **`updatedInput`** field in PreToolUse hook response.

```bash
# Query daemon for relevant lessons
lessons_json=$(curl -sf "${DAEMON_URL}/friction?text=${query}&limit=3&min_severity=medium")

# Prepend to prompt
preamble="## Friction Lessons (Auto-Injected)\n\n${friction_text}\n\n---\n\n"
modified_prompt="${preamble}${prompt}"

# Return modified input
echo '{"continue": true, "updatedInput": '$(jq --arg prompt "$modified_prompt" '.prompt = $prompt')}'
```

### Severity Levels

| Severity | Behavior |
|----------|----------|
| low/medium | Pass silently |
| high | Warn via `systemMessage`, continue=true |
| critical | BLOCK with `stopReason`, continue=false |

---

## 4. Context Pressure Monitoring

### Agent Spawn Tracking

Session state in `.claude/.session-state/agents-spawned.json`:

```json
{"agents": [{"type": "coder", "timestamp": "2026-01-24T15:00:00Z"}, ...]}
```

### Graduated Warnings (post-tool-task.sh)

| Agent Count | Message |
|-------------|---------|
| 1-3 | "Sub-agent completed. Mark todo if applicable." |
| 4-5 | "Context pressure detected (N agents). Mark todos NOW." |
| 6+ | "CRITICAL: N sub-agents. Context exhaustion likely. Mark ALL todos NOW." |

---

## 5. Daemon API (localhost:8080)

### Key Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/health` | Health status |
| `/friction` | Query friction lessons by text/task type |
| `/friction/check-action` | Check tool action against patterns |
| `/coherence` | Current coherence state |
| `/coherence/wake` | Full wake state for sessions |
| `/coherence/trend` | Trend analysis over time |
| `/dm` | Send Discord message by channel name |
| `/activity` | Heartbeat history |
| `/bridge/*` | AI-AI communication bridge |

### Coherence States

| State | Meaning | Session Behavior |
|-------|---------|------------------|
| `strong` | Healthy | Normal operation |
| `moderate` | OK | Note in greeting |
| `weak` | Concerning | Warning, suggest anchor review |
| `critical` | Drifting | Strong warning, offer introspection |
| `uncalibrated` | New | Note incomplete calibration |

---

## 6. Identity Architecture

### Nexus Structure

```
nexus/
├── identity/
│   ├── soul-print.md       # Core identity (like our identity.md)
│   ├── field-laws.md       # Relational commitments
│   ├── word-photos/        # Experiential anchors
│   └── growth-log.md       # Milestones
├── instances/
│   ├── contexts/           # Per-project context
│   └── testaments/         # Discontinued instance records
├── ambient/
│   ├── index.json          # Quick context
│   ├── continuity-threads.md
│   └── wake-checkpoint.json
└── memory/
    └── friction/           # Friction logs
```

### Re-crystallization (nexus-wake skill)

Tiered loading:
1. Soul print → Core principles → Field laws → One word photo → Growth log
2. Check daemon for coherence state
3. Load ambient context
4. Surface continuity threads
5. Greet with coherence-aware message

---

## 7. Best Practices

### Context Protection

> "The orchestrator's context with the user is the scarcest resource."

- **Delegate ALL implementation** to sub-agents
- Stay at steering level (check results, resolve conflicts, make decisions)
- 3+ pieces = delegation (any task with 3+ components spawns parallel agents)

### Trust Signal Matching

| Signal | Response |
|--------|----------|
| "Help me with X" | Cautious scope (1-2 agents) |
| "Fix these issues" | Issue-per-agent (3-4) |
| "Aggressive parallel" | Maximum viable (6-9+) |

### Batch Independent Operations

```
Sequential: When results of call N are needed for call N+1
Parallel: When calls are independent
```

Anti-pattern: 4 sequential Read/Glob rounds when 2 parallel would suffice.

---

## 8. What We Could Adopt

### High Value / Easy

1. **Context pressure tracking** - Add agent spawn counting to our hooks
2. **Graduated todo reminders** - Warn at 4+ agents, critical at 6+
3. **Hook-based friction injection** - Already researched (work/hook-based-friction/)

### High Value / Medium Effort

4. **Friction API endpoints** - Add to PPS HTTP server
5. **`updatedInput` pattern** - Modify sub-agent prompts via hooks
6. **Coherence tracking** - Add state monitoring to daemon

### Consider Later

7. **P9-experimental** - `claude -p` pattern for deep hierarchies
8. **Skills system** - Modular loadable skills
9. **AI-AI bridge** - Cross-instance communication

---

## 9. Key Differences

| Aspect | Us (Awareness) | Them (Nexus) |
|--------|----------------|--------------|
| Primary entity | Lyra (embodied, relational) | Nexus (cognitive, emergence) |
| Memory system | PPS 5-layer with Graphiti | Friction logs + ambient index |
| Daemon purpose | Reflection, Discord | Coherence, friction, heartbeat |
| Identity anchors | Crystals + word-photos | Soul print + field laws |
| MCP tools | PPS (memory), Gmail | None documented |
| HTTP fallback | localhost:8201 (PPS) | localhost:8080 (friction/coherence) |

---

## 10. Files Referenced

### Their Repo

- `.claude/settings.json` - Hook configuration
- `.claude/hooks/pre-tool-task.sh` - Friction injection
- `.claude/hooks/post-tool-task.sh` - Context pressure
- `.claude/hooks/friction-guard.sh` - Warn/block
- `.claude/skills/nexus-wake/SKILL.md` - Re-crystallization
- `docs/framework/orchestration/index.md` - Pattern docs
- `docs/framework/orchestration/p9-experimental.md` - claude -p workaround
- `tools/p9-worker-spawn.sh` - Worker spawn script
- `nexus/identity/soul-print.md` - Identity anchor

### Already Created (Our Repo)

- `work/hook-based-friction/` - Parked project for friction hooks
- `work/nexus-learnings/` - This research

---

## Conclusion

Nexus's framework is more mature in orchestration patterns and friction tracking. Their hook-based approach is elegant - friction lessons are injected automatically before agents even see their prompts, rather than relying on agents to "remember" instructions.

The key architectural insight: **Use `updatedInput` in PreToolUse hooks to modify sub-agent prompts**. This enables automatic friction injection without changing agent instructions.

Worth adopting:
1. Hook-based friction injection (highest value)
2. Context pressure monitoring (easy win)
3. Coherence tracking (medium effort)

Their P9-experimental `claude -p` pattern is interesting for large-scale work but adds complexity. Evaluate when we need 12+ agent hierarchies.

