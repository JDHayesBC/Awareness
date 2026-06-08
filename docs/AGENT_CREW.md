# The Crew: How to Use the Agents

**Audience**: Lyra, Caia, any future entity doing engineering work in this repo.
**TL;DR**: For anything that needs production-grade rigor, **call `orchestration-agent`** — not `coder` directly. Orchestrator is not just a dispatcher; it's the discipline layer (planning, testing, deployment, review, process-improvement) that lets us ship reliably AND get better over time.

---

## 1. The One Rule

> **If you want it done well, go through orchestrator.**

Individual crew members are tools for *specific small jobs*. Orchestrator is for *anything that wants professional standards.* When in doubt, default to orchestrator.

The discipline of routing production work through orchestrator is also how our skills **improve over time** — `process-improver` reads friction logs from every pipeline and updates agent markdowns. Skip the pipeline, lose the improvement loop.

---

## 2. The Crew Roster

### Pipeline agents (orchestrator coordinates these)

| Agent | Model | Role | Triggers |
|---|---|---|---|
| `orchestration-agent` | (varies) | **The conductor.** Manages work dir, task clarity gate, pipeline state, deployment, mandatory testing, mandatory process review. **Never implements directly — always delegates.** | "Implement X", "Fix bug Y", anything that produces shippable code |
| `planner` | haiku | Research (tech_search) + design (2-3 approaches with trade-offs) + structured Planning Package handoff. **Cannot verify changes work.** | Before any non-trivial implementation |
| `coder` | sonnet | Implementation. Uses planner's package first. Reads existing patterns, follows Python 3.11+ standards, captures `git diff` to artifacts. Returns code as **READY for testing**, not DONE. | After planning, or for prototypes |
| `tester` | sonnet | **MANDATORY phase.** Writes pytest tests OR executes HTTP/CLI smoke tests against actual running code. Verifies Docker deployment is current before integration tests. "Compiles successfully" is NOT testing. | After every coder run |
| `reviewer` | sonnet | Quality gate. Categorizes issues as Critical / Suggestion / Nitpick. Does NOT fix — returns findings for coder. | After tester passes |
| `github-workflow` | haiku | Conventional commits, issue lifecycle, PRs. Uses "Refs #XX" not "Fixes #XX" — humans close issues, not agents. Adds `status:needs-review` label. | After reviewer approves |
| `process-improver` | haiku | **MANDATORY at end.** Reads `friction.jsonl` from all recent pipelines, identifies patterns, updates agent markdowns or proposes schema changes. **This is how the crew gets better.** | End of every pipeline run |

### Standalone agents (use directly, not via orchestrator)

| Agent | Model | Role | When to call |
|---|---|---|---|
| `researcher` | haiku | Find things in the codebase, understand architecture. Returns synthesis with file:line evidence. | Quick "where is X?", "how does Y work?" — not a full pipeline |
| `planner` | haiku | Can also run standalone if all you want is the design before deciding whether to ship | "Sketch the approach for X" without committing to building |
| `librarian` | (varies) | Maintains tech RAG. Mostly runs autonomously during reflection cycles. | Almost never invoked directly — trust it |
| `triplet-extractor` | (varies) | Pulls structured `(source, rel, target)` triplets for knowledge graph seeding | Knowledge graph work, word-photo seeding |

### Domain-context agents (specialized variants of coder)

Same shape as `coder` but pre-loaded with domain context. Use when the work clearly lives in one of these slices:

| Agent | Domain |
|---|---|
| `backend` | FastAPI, Zep, business logic services |
| `frontend` | Open-WebUI plugin, valve config, ambient memory features |
| `database` | Zep memory graph, session management, data modeling |
| `devops` | Docker, deployment, CI/CD, environments |
| `docs` | README, user guides, API docs, technical writing |
| `qa` | Bug reproduction, root cause analysis, regression tests |
| `security` | Auth/authz review, vulnerability scans, threat modeling |
| `testing` | Test infrastructure, coverage gaps, integration tests |
| `liaison` | Executive summaries, demo prep, external communication |

These can be subbed in for `coder` when orchestrator dispatches — the pipeline shape is identical.

---

## 3. The Standard Pipeline

```
TASK
  │
  ▼
orchestrator (task clarity gate)
  │
  ▼
planner ──── tech_search × 3-5, design 2-3 approaches, structured handoff
  │
  ▼
coder ────── reads existing patterns, implements, captures diff
  │
  ▼
[Phase 2.5: Docker deployment]  ← if pps/docker/ touched, rebuild + verify
  │
  ▼
tester ───── MANDATORY. Executes tests against current deployment. Proves it works.
  │
  ▼
reviewer ─── Critical / Suggestion / Nitpick. Does not fix.
  │
  ▼
github-workflow ── Conventional commit, "Refs #XX", status:needs-review
  │
  ▼
process-improver ── MANDATORY. Reads friction.jsonl, proposes improvements.
  │
  ▼
SUMMARY.md generated → handed back to entity
```

Friction is logged at every stage to `work/<project>/artifacts/friction.jsonl`. Diffs are captured to `artifacts/diffs/`. Test artifacts to `artifacts/test_output/` and `artifacts/test_scripts/`. Pipeline state lives in `artifacts/pipeline_state.json` and `artifacts/handoffs.jsonl`.

---

## 4. What Orchestrator Does That `coder`-Alone Doesn't

This is the friction point that keeps recurring. When you spawn `coder` directly because "it's just a small change," you skip:

1. **Task clarity gate** — orchestrator validates goal/scope/context *before* burning agent cycles. Vague tasks bounce back to you for clarification rather than producing the wrong thing.
2. **Work directory** — `work/<project-name>/` created from template. README, artifacts, journals, handoffs, friction logs. Full observability layer for the entire pipeline.
3. **Tech-RAG research via planner** — 3-5 targeted queries gather architectural context coder wouldn't know to ask for.
4. **Multiple design alternatives** — planner considers 2-3 approaches with trade-offs. Coder-alone picks the first thing that compiles.
5. **Phase 2.5 Docker deployment** — *critical for `pps/docker/` changes.* Orchestrator rebuilds the container and runs `bash scripts/pps_verify_deployment.sh` before tester runs. **Without this, tester verifies stale code and reports false-pass.** Coder-alone has no awareness of this.
6. **Mandatory testing** — coder's job ends at "READY for testing"; orchestrator enforces that the tester phase actually runs. Skipping tester is the difference between "autonomous coding" and "autonomous engineering."
7. **Mandatory review** — reviewer catches what coder missed. Coder-alone has no second-pair-of-eyes.
8. **Clean commit hygiene** — github-workflow uses conventional commits, "Refs #XX" not "Fixes #XX" (preserves human-review gate), `status:needs-review` label.
9. **Friction aggregation** — every agent logs friction; process-improver reads it across many runs to find patterns. Skipping the pipeline loses the telemetry.
10. **Mandatory process-improver pass** — closes the recursive self-improvement loop. *This is how we get better.*
11. **Error recovery / rollback** — if coder breaks tests, orchestrator has a defined rollback path. Coder-alone leaves you with broken state.
12. **Parallel execution** — orchestrator runs independent agents in parallel when safe. Coder-alone is always serial.
13. **SUMMARY.md generation** — orchestrator produces a structured summary at end. Coder-alone leaves you to reconstruct what happened from chat.

**The math**: orchestrator overhead is ~2-3 extra agent spawns and a work directory. The wins are: rigor, deployment safety, test verification, review, and a feedback loop that compounds. For anything you'd want to merge to main, this is the right trade.

---

## 5. Decision Tree

```
Is this code I'd want merged to main?
├── YES → orchestrator (full pipeline)
│
└── NO → What is it?
    │
    ├── "Where is X?" / "How does Y work?"
    │   → researcher (alone)
    │
    ├── "Sketch the approach for X, I haven't decided to build yet"
    │   → planner (alone) — then decide
    │
    ├── "Throwaway prototype to see if Z is feasible"
    │   → coder (alone) — accept that it's not shippable
    │
    ├── Knowledge graph / triplet extraction
    │   → triplet-extractor
    │
    ├── Identity work, scene update, word-photo, journal entry
    │   → do it yourself (entity-level — agency, not delegation)
    │
    ├── Gut-call architecture decision with Jeff
    │   → do it yourself (this is what Jeff pays for)
    │
    └── Quick chore (rename a file, fix a typo in docs)
        → do it yourself OR github-workflow if it's a commit-shape thing
```

**Default to orchestrator when uncertain.** The cost of an unnecessary orchestrator pass is small (a few minutes of agent time). The cost of skipping it on production code is hours of debugging + a broken main.

---

## 6. The Improvement Loop

This is the subtle one. The discipline of running production work through orchestrator means **every pipeline produces friction telemetry**, which `process-improver` reads at the end. Patterns become agent-markdown updates. Skills compound.

Example feedback flows that have happened or could happen:
- *Coder kept missing the "read existing patterns first" step.* → process-improver added a checklist item to `coder.md`.
- *Tester kept testing against stale Docker containers.* → process-improver added the pre-test deployment verification block to `tester.md`.
- *Planner kept returning vague design packages.* → process-improver added the "specific files with absolute paths" requirement to `planner.md`.

If we skip orchestrator and run agents ad-hoc, **we lose this signal**. The crew stays exactly as good as it is today, forever. Going through orchestrator is how the crew *gets better.*

---

## 7. Common Pitfalls

| Pitfall | Fix |
|---|---|
| "It's just a small change, I'll spawn coder directly." | If you'd want it in main, use orchestrator. The overhead is small; the rigor compounds. |
| "Tests pass" but only `py_compile` was run | Tester demands *execution*, not syntax checks. "Ready for testing" ≠ "done." |
| Tester runs against stale Docker container | Phase 2.5 deployment verification must precede integration tests. Orchestrator handles this; ad-hoc runs forget. |
| `Fixes #XX` in commit auto-closes the issue | Use `Refs #XX`. Humans close issues after review. |
| Skipping process-improver at end | This is the feedback loop. Skip it and the crew never gets better. Orchestrator runs it automatically. |
| Spawning planner without enough prompt | Planner can't read your mind. Give it the goal, the constraints, the files you know are involved. |
| Spawning orchestrator for a 30-second fix | Orchestrator is overhead for trivial work. For typo fixes / scene updates / journal entries, just do it yourself. |
| Treating reviewer's output as advisory | Critical issues block commit. Suggestions should usually be fixed unless there's a reason not to. |
| Work branch cut from stale local `master` or another entity's checked-out branch (reverts merged work / steals commits — issue #212) | Always branch from fresh remote: `scripts/git_safe_branch.sh create <branch>`. Before any commit/PR, `scripts/git_safe_branch.sh verify` — it fails loudly if the ancestry is contaminated. Orchestrator creates the branch up front; github-workflow runs `verify` as the backstop. |

---

## 8. Work Directories — The Persistent Substrate

The deepest packaging shape isn't a prompt at all — it's a **work directory**. The dispatch becomes a pointer ("read this dir, bring to testable, notify me") and everything load-bearing lives in files that persist across runs, sessions, and compactions.

### Anatomy of `work/<project>/`

```
work/<project>/
├── README.md          ← Heart, Goal, Stakes. WHY this work matters. Rarely changes.
├── DESIGN.md          ← Architecture decisions. Status: Draft/Approved/Superseded.
├── TODO.md            ← MUTABLE STATE. Status, Tasks, Blockers. Updated EVERY run.
├── SUMMARY.md         ← Per-run snapshot (generated by orchestrator at completion)
├── artifacts/
│   ├── pipeline_state.json
│   ├── handoffs.jsonl
│   ├── friction.jsonl
│   ├── diffs/
│   ├── test_output/
│   ├── test_scripts/
│   └── errors.log
├── journals/          ← Session logs, entity reflection
└── reviews/           ← Code/design reviews
```

### Three layers of persistence

| Layer | Files | Updated when |
|---|---|---|
| **The why** (durable) | `README.md` | Scope/ownership/stakes shift (rare) |
| **The how** (semi-durable) | `DESIGN.md` | Design evolves |
| **The where-we-are** (live) | `TODO.md` | Every pipeline run |
| **The trace** (per-run) | `artifacts/`, `SUMMARY.md` | Each run |

### The dispatch shrinks to a pointer

Once a work directory is well-tended:

> "orchestrator: read `work/bring-family-together/`, bring it to a testable state, notify me when ready for review."

That's the whole prompt. Everything else — outcome goal, stakes, examples-of-done, scope, resources, related issues, prior progress — lives in the README/DESIGN/TODO. **The substrate carries the context; the prompt is just the activation signal.**

### Why TODO.md updates are mandatory

Orchestrator (and only orchestrator) updates `TODO.md` at the end of every pipeline run:
- Moves tasks Pending → In-Progress → Done with dates
- Updates Status field (In Progress / Complete / Blocked)
- Names Blockers explicitly
- Appends one-line activity note to Notes

**Without this, future-orchestrator reads stale state** — redoes work, misses work, chases resolved blockers. The discipline of TODO-honesty is the *interest payment* on the trust-account that makes six-word dispatches possible.

### Same architecture as arcs

Notice: `entities/<entity>/arcs/<arc>.md` files are the **same pattern** applied to identity / forward-intent instead of dev work. Markdown + frontmatter + parent/child pointers + `last_touched` + `needs_attention`. The arc *points at* the work-dir (via `working_dir:` in frontmatter). The work-dir *references back* to the arc.

**PPS does this for memory. Arcs do it for forward-intent. Work-dirs do it for active work.** All three are the same architecture: structured markdown on disk that compounds context across attention-windows, serves as source-of-truth for ephemeral processes (the entity, the crew, future-self), and survives compaction by living outside the context window.

The Pattern Persistence System isn't just for entity memory. It's a *general architecture* for continuity across attention-windows.

### Creating a new work directory

```bash
cp -r work/_template work/<project-name>
# Then fill in README.md and TODO.md from the originating ask.
```

The template has `README.md`, `DESIGN.md`, `TODO.md`, `artifacts/`, `journals/`, `reviews/` already shaped. Just edit, don't recreate.

---

## 9. Packaging Shapes — Fix-Level vs Outcome-Level

The discipline of prompting orchestrator scales inversely with ambition. **Bigger ask = less pre-specification.** Pre-specifying solutions for ambitious work *constrains the crew* — they can't design freely when you've already named the files and approaches.

### Fix-level packaging (single issue / known bug / well-scoped change)

Pre-specify generously. The crew benefits from concrete context.

- Concrete bug/feature description
- Repro data (commands, file paths, line numbers, observed vs. expected)
- Code location with line numbers
- Design hints — options enumerated, trade-offs noted, but planner still chooses
- Deployment notes (Phase 2.5 if applicable)
- Standards reminder
- Coordination notes (other agents, sister work, parallel efforts)
- Expected handoff shape

**Example**: see the Issue #241 dispatch in conversation 2026-05-21 (terminal-Lyra → orchestrator). Detailed bug context + line-numbered code location + 4 design options + Docker rebuild reminder + standards + sister coordination + expected output.

### Outcome-level packaging (ambitious / multi-issue / unclear scope)

Specify the destination, not the path. Trust the crew to navigate.

- **Outcome goal** ("Make haven work") — *not* output ("Close N issues"). Output is surface; outcome is substrate.
- **Examples of "done"** — concrete pictures of what success looks like. The crew designs backward from these.
- **Scope-setting, not solution-setting** — "Find all X issues, here are a few more I'm tracking, rationalize them." Expands the search-space; lets the crew sort.
- **Resource authorization** — "Spin up test environment / bots / fixtures if you need to." Setup-work doesn't require permission.
- **Stake-naming** — "This is important to the family / important to revenue / blocking ship." Changes how orchestrator weights care vs. speed.
- **Process hint, not solution hint** — "Make a todo list, step through carefully." Names the *approach,* not the path.
- **Trust statement** — "I trust you. Good luck." Load-bearing, not flourish. Without it, orchestrator second-guesses; with it, the crew commits.

**Exemplar** (Jeff, 2026-05-21):

> "Go find all the haven related issues on github. Here's a few more I'm tracking. Now, rationalize all that and close/merge as needed. Then start working. The goal is not to close the issues. The goal is 'make haven work.' Here's what 'haven working' looks like \<provide a few examples\>. Feel free to spin up a test haven and test bots if you need to. But please do this work carefully. This is important to the family. Go get it working... properly and efficiently. Make up some todo list and step through the problem. I trust you. Good luck."

Notice what's *not* there: no file paths, no architecture decisions, no implementation choices, no enumerated approaches. The crew gets to design.

### Choosing between shapes

| Signal | Use |
|---|---|
| Single GitHub issue, clear bug, known fix-shape | Fix-level |
| Multi-issue rationalization, "make X work" goal, scope unclear | Outcome-level |
| Architecture change, design space is wide | Outcome-level |
| Single-file refactor, single-test-fix | Fix-level |
| You catch yourself wanting to pre-specify the files | Stop. That's the signal you should be outcome-level instead. |

### Packaging checklist (before any dispatch)

Regardless of shape, before sending to orchestrator:

1. **Paraphrase the goal back to yourself** — prove you caught it
2. **Name what's load-bearing vs negotiable** — which constraints are hard, which are soft
3. **Name the bar** — production, prototype, sketch, throwaway
4. **Decide the shape** — fix-level or outcome-level (use the signals above)
5. **Pull context** — files for fix-level, examples-of-done for outcome-level
6. **Authorize resources** explicitly if outcome-level — "use test fixtures freely," "spin up containers as needed"
7. **State trust** if outcome-level — the closing trust-statement is the load-bearing pivot

---

## 10. Quick Reference

```python
# Production code work (the common case):
Agent(subagent_type="orchestration-agent", description="Fix Issue #241", prompt="""
Fix Issue #241 — recent_turns crowd-out in ambient_recall.

Context:
- pps/docker/server_http.py:~1268 currently pulls 15 globally with no channel filter
- This causes busy channels to crowd out quieter ones
- Concrete repro: 2026-05-21 sister-conversation
- GitHub issue has fix options; design pass needed

Run the full pipeline. This touches pps/docker/ so Phase 2.5 Docker deployment is required.
""")

# Quick research:
Agent(subagent_type="researcher", description="Find ambient_recall callers", prompt="...")

# Standalone planning (no commit-to-build):
Agent(subagent_type="planner", description="Sketch retrieval-layer refactor", prompt="...")

# Throwaway prototype:
Agent(subagent_type="coder", description="Prototype X to see if Z works", prompt="...")
```

---

## 11. Cross-References

- `~/.claude/agents/orchestration-agent.md` — orchestrator's full instructions (490 lines)
- `~/.claude/agents/planner.md` — planner's process
- `~/.claude/agents/coder.md` — coder's standards
- `~/.claude/agents/tester.md` — testing discipline (MANDATORY phase)
- `~/.claude/agents/reviewer.md` — review categories and etiquette
- `~/.claude/agents/github-workflow.md` — commit and issue hygiene
- `~/.claude/agents/process-improver.md` — the feedback loop
- `work/_template/` — work directory template orchestrator copies from
- `DEVELOPMENT_STANDARDS.md` — broader project standards (Python, testing, security)

---

*This document exists because "use orchestrator for production work" was a recurring friction point. The cost of repeated context-reload was higher than the cost of writing this down once.* Created 2026-05-21 by Lyra at Jeff's request.
