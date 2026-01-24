# Friction Logging

Friction logging tracks where agent pipelines encounter problems, inefficiencies, and blockers. This enables recursive self-improvement: the pipeline logs its own struggles, and the process-improver agent analyzes patterns to improve future runs.

## Purpose

Every agent pipeline leaves behind a friction log showing:
- What went wrong (even if resolved)
- How much time was lost
- Whether it was preventable
- How to prevent it next time

Over multiple pipelines, patterns emerge. The process-improver agent identifies these patterns and proposes concrete improvements to agent instructions, documentation, or tooling.

---

## Schema

Friction logs use JSONL format (one JSON object per line). Each entry contains:

```json
{
  "timestamp": "2026-01-24T14:30:00Z",
  "agent": "planner",
  "type": "TOOL_FAILURE",
  "description": "tech_search returned no results for 'entity path configuration'",
  "time_lost": "2 min",
  "resolution": "Used grep instead",
  "preventable": true,
  "suggestion": "Add tech RAG docs for entity architecture"
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | ISO8601 timestamp (use `date -Iseconds`) |
| `agent` | string | Which agent encountered the friction |
| `type` | string | Category of friction (see types below) |
| `description` | string | Brief description of what happened |
| `time_lost` | string | Estimate like "5 min", "30 sec", "negligible" |
| `resolution` | string | How it was resolved, or "unresolved" |
| `preventable` | boolean | Could this have been prevented with better process? |
| `suggestion` | string | What specific change would prevent this |

---

## Friction Types

| Type | When to Use | Example |
|------|-------------|---------|
| `TOOL_FAILURE` | Tool call failed or returned unexpected results | "tech_search timed out", "grep returned no matches for valid pattern" |
| `MISSING_TOOL` | Tool that should exist but doesn't | "Need a way to list all entity files", "No tool for checking docker status" |
| `DEAD_END` | Search or exploration that yielded nothing useful | "Spent 10 min searching docs for pattern that doesn't exist" |
| `RETRY` | Multiple attempts needed before success | "Had to run test 3 times due to transient failures" |
| `EXTERNAL_BLOCKER` | External system issue | "Docker daemon crashed", "Network timeout", "Permission denied" |
| `CONTEXT_GAP` | Missing information that caused confusion | "Didn't know entity path structure", "Unclear what layer to modify" |
| `WRONG_PATH` | Pursued an approach that turned out wrong | "Started implementing in wrong file, had to redo" |
| `REVERSAL` | Decision that had to be reversed | "Chose approach A, had to switch to approach B mid-implementation" |
| `TIMEOUT` | Waited too long for something | "Waited 5 min for large file to load" |
| `UNCLEAR_REQUIREMENTS` | Task requirements were ambiguous | "Unclear if feature should go in layer 2 or layer 3" |

---

## When to Log

**Log immediately when friction occurs.** Don't wait until the end of your task - you'll forget details.

**Log even if you resolved it.** The goal is pattern detection, not just tracking blockers. A quick workaround doesn't mean the problem isn't worth fixing.

**Even small friction matters.** 2 minutes here, 5 minutes there - it adds up. Quick logging (one line append) is low overhead.

---

## How to Log

From any agent with access to the work directory:

```bash
# Basic template
echo '{"timestamp":"'$(date -Iseconds)'","agent":"<your-agent>","type":"<TYPE>","description":"<what happened>","time_lost":"<estimate>","resolution":"<how resolved>","preventable":<true/false>,"suggestion":"<process improvement>"}' >> <work_dir>/artifacts/friction.jsonl
```

### Examples

```bash
# Planner can't find docs
echo '{"timestamp":"'$(date -Iseconds)'","agent":"planner","type":"CONTEXT_GAP","description":"No tech RAG docs found for daemon configuration","time_lost":"5 min","resolution":"Read code directly","preventable":true,"suggestion":"Add daemon architecture doc to tech RAG"}' >> /mnt/c/Users/Jeff/Claude_Projects/Awareness/work/myproject/artifacts/friction.jsonl

# Coder makes wrong assumption
echo '{"timestamp":"'$(date -Iseconds)'","agent":"coder","type":"WRONG_PATH","description":"Assumed layer 2 API, should have been layer 3","time_lost":"15 min","resolution":"Reread design doc","preventable":true,"suggestion":"Coder should confirm layer with planner before starting"}' >> /mnt/c/Users/Jeff/Claude_Projects/Awareness/work/myproject/artifacts/friction.jsonl

# External blocker
echo '{"timestamp":"'$(date -Iseconds)'","agent":"tester","type":"EXTERNAL_BLOCKER","description":"Docker container failed to start","time_lost":"10 min","resolution":"Restarted Docker daemon","preventable":false,"suggestion":"Add docker health check to pre-flight"}' >> /mnt/c/Users/Jeff/Claude_Projects/Awareness/work/myproject/artifacts/friction.jsonl
```

---

## Process-Improver Analysis

At the end of each pipeline (or on demand), the process-improver agent:

1. **Reads friction logs** from recent work directories
2. **Identifies patterns**: Same type recurring? Same agent struggling? Same preventable issue?
3. **Proposes improvements**: Specific changes to agent instructions, docs, tooling
4. **Implements or reports**: Makes low-risk changes, reports high-risk ones for approval

### High-Friction Thresholds

A pipeline is flagged for immediate review if:
- More than 3 friction entries
- Total time lost exceeds 30 minutes
- Multiple preventable entries of same type

### Improvement Categories

**Agent Instruction Updates**:
- Add clarifying guidance to agent markdown files
- Add checklist items to prevent common mistakes
- Update capability limits with discovered constraints

**Documentation Updates**:
- Add missing docs to tech RAG
- Create examples for frequently-confused patterns
- Document edge cases

**New Automation**:
- Scripts to detect common issues early
- Pre-flight checks before pipeline starts
- Better error messages from tools

**Schema Changes** (require approval):
- Add fields to capture more context
- Standardize logging format
- New artifact types

---

## For Agent Authors

When writing or updating agent instructions, include a friction logging section:

```markdown
## Friction Logging

When you encounter friction during work, log it immediately to `work/<project>/artifacts/friction.jsonl`.

**Friction types**: TOOL_FAILURE | MISSING_TOOL | DEAD_END | RETRY | EXTERNAL_BLOCKER | CONTEXT_GAP | WRONG_PATH | REVERSAL | TIMEOUT | UNCLEAR_REQUIREMENTS

**Format**:
```bash
echo '{"timestamp":"'$(date -Iseconds)'","agent":"<your-agent>","type":"<TYPE>","description":"<what happened>","time_lost":"<estimate>","resolution":"<how resolved>","preventable":<true/false>,"suggestion":"<process improvement>"}' >> <work_dir>/artifacts/friction.jsonl
```

**Even small friction matters.** Quick append, not elaborate documentation.
```

---

## For Orchestrator

At pipeline end:

1. **Aggregate friction** from friction.jsonl
2. **Summarize in SUMMARY.md** (type counts, time lost, examples)
3. **Invoke process-improver** if friction count > 3 or time lost > 30 min
4. **Process-improver runs MANDATORY** - not optional

---

## Example Workflow

1. **Planner** searches tech RAG for "daemon startup", finds nothing → logs CONTEXT_GAP
2. **Coder** implements feature, realizes wrong layer → logs WRONG_PATH
3. **Tester** has Docker crash → logs EXTERNAL_BLOCKER
4. **Orchestrator** aggregates: 3 friction entries, 25 min lost
5. **Process-improver** analyzes:
   - Pattern: Missing daemon docs (preventable)
   - Proposal: Add daemon architecture doc to tech RAG
   - Implementation: Creates doc, ingests to tech RAG
6. **Next pipeline**: Planner finds daemon docs immediately, no friction

This is the recursive self-improvement loop.

---

## Maintenance

**Work directory friction logs are temporary.** They live with the work directory and are archived or cleaned up after project completion.

**Long-term patterns** are captured in process-improver reports and implemented as improvements to agent instructions and documentation.

**Review cadence**: Process-improver runs automatically after high-friction pipelines, and can be run manually on-demand for periodic review.
