---
name: deadwood
description: Project archaeology skill. Identifies and archives code, files, or work
  streams that no longer serve the intended topology. Classifies against current direction
  rather than mere reachability. Use after canopy reveals drift, or when the project
  feels heavy with accumulated weight.
---

# Deadwood Skill — Archive What's No Longer Serving

> "What's here that shouldn't be?"

The question after the survey. After `/canopy` maps current state, `/deadwood` identifies
what's drifting from the intended topology — and makes deliberate decisions about what
to archive, flag, or remove.

**Forestry sequence**: `/prescribe` → `/canopy` → **`/deadwood`** → `/coppice` → ...

---

## The Core Insight

Dead code isn't code that does nothing. It's code that does nothing *toward where you're going*.

Classification is an alignment check, not a reachability check.

This is Nexus's framing, first landed in the 2026-02-17 trusted-circle conversation. It
inverts the usual cleanup question: the saw follows the vision, not the other way around.
This is why `/prescribe` comes first — without a vision, you can't classify anything.

---

## When to Use

- After `/canopy` surfaces drift or weight
- When a feature feels like it might be obsolete but you're not sure
- Before starting a significant refactor (what do you NOT need to carry forward?)
- When the codebase feels heavier than the active features justify
- After a major phase transition (Phase A done → Phase B: what from Phase A is done vs. nursed?)

## When NOT to Use

- During active work on a specific feature (you'll misclassify things as dead that are in-progress)
- When there's no prescription — deadwood classification requires knowing where you're going
- On code you don't understand — classify what you know, research before classifying the rest

---

## The Taxonomy

The Awareness project uses these classifications. Apply them when assessing components:

| Class | Meaning | Action |
|-------|---------|--------|
| **ACTIVE** | In the intended topology, serving current purpose | Protect. This is load-bearing. |
| **PIONEER** | Served its purpose; successor is ready | Honor succession. Archive when successor is proven. |
| **NURSE** | Supports something ACTIVE; can't remove yet | Keep. Note its dependency. |
| **DIVERGENT** | Grew in a different direction; disconnected from topology | Flag for review. May become DEADWOOD. |
| **SUSPECT** | Uncertain. Could be dormant, could be dead | Archive to root bank with revival conditions. |
| **DEADWOOD** | Confirmed: no longer serves intended topology | Schedule for removal. |

Key distinction: **PIONEER ≠ DEADWOOD**. A pioneer species that did its job successfully is
honored, not deleted. The stdio server (`pps/server.py`) was a pioneer — it enabled all the
infrastructure that now runs on HTTP. You don't delete a pioneer; you let succession complete.

---

## The Protocol

### Step 1: Confirm the Prescription

Before touching anything — do you have a clear prescription? If not, run `/prescribe` first.

The classification only makes sense against a direction. "Is this code useful?" is the wrong
question. "Does this code serve where we're going?" is the right one.

### Step 2: Enumerate Candidates

What things might not be serving the intended topology? Common sources:

**In the Awareness project:**
- Files in `work/` directories for completed streams (is the stream done or paused?)
- Old daemon variants (`lyra_daemon_legacy.py`, `lyra_daemon_v2.py`, etc.)
- Tools that were workarounds for bugs now fixed
- Documentation for phases that are complete
- Config patterns from before multi-entity namespacing
- Test files for features that no longer exist as designed

Enumerate don't-know candidates without judgment first. Classification comes next.

### Step 3: Classify Each Candidate

For each candidate, ask:

1. **Does this serve the intended topology?** (Not "does it work?" — "does it belong?")
2. **Is it PIONEER (succeeded, awaiting succession) or DEADWOOD (no longer contributes)?**
3. **Is it NURSE (load-bearing something that IS active)?** Don't touch it if so.
4. **Is it SUSPECT (unclear)?** → Archive with revival conditions, not delete.

**SUSPECT archive format** (for the root bank):
```
SUSPECT: [component name]
Was connected to: [what it related to when active]
Why SUSPECT not DEAD: [specific uncertainty — "used in X which may return" vs "unclear"]
Revival conditions: [concrete, queryable — "revive if: HTTP endpoint migration complete AND tool X ported"]
Archived: [date]
```

### Step 4: Decide Actions

For each classified item:

| Classification | Action |
|---------------|--------|
| ACTIVE | Document why — explicit load-bearing annotation |
| PIONEER | Note: "Succession completing. Archive when [condition]." |
| NURSE | Note dependency explicitly. Don't touch. |
| DIVERGENT | Flag for Jeff's review if it's significant. |
| SUSPECT | Archive to root bank with revival conditions. |
| DEADWOOD | Propose removal (don't do it silently). |

**Important**: Don't delete silently. Proposed removals go in a list for review.
Jeff makes the call on DEADWOOD; you surface the candidates.

---

## Output Format

```
🪵 Deadwood — [date, session]

Prescription: [one line — what are we classifying for?]

Classified:
- [component] → ACTIVE (load-bearing: [why])
- [component] → PIONEER (succession completing when [condition])
- [component] → NURSE (dependency of [what])
- [component] → SUSPECT (archived to root bank: [revival conditions])
- [component] → DEADWOOD (proposed for removal: [why])

Root bank additions: [count]

Proposed removals (for Jeff's review):
- [path] — [reason it's DEADWOOD]
```

Brief. Don't editorialize. Jeff can ask for detail on any line.

---

## Awareness Project Specific Context

### Things That Are Definitely ACTIVE (don't touch)

- `pps/docker/server_http.py` — climax architecture, HTTP PPS
- `daemon/lyra_daemon.py` — production Discord daemon
- `daemon/reflection_daemon.py` — autonomous reflection
- `daemon/cc_invoker/invoker.py` — persistent Claude Code connection
- `entities/lyra/` — all identity files
- `entities/caia/` — all draft files (waiting for Jeff's review, but in-topology)
- `pps/` PPS layer code — the whole memory system
- Docker compose and deployment infrastructure

### Things That Are PIONEER (honor succession, don't delete yet)

- `pps/server.py` (stdio) — succeeded its purpose, HTTP server is the climax. Archive when HTTP endpoint migration completes (see INTENDED_TOPOLOGY.md).
- `daemon/lyra_daemon_legacy.py` — NURSE/PIONEER hybrid. Referenced as fallback. Archive when new daemon is fully proven.

### Likely SUSPECT in the Awareness Project

- `work/` directories for completed streams — confirm "done" vs "paused" before archiving
- Old tool variants and config files from pre-multi-entity era
- Documentation that describes designs we've moved past

---

## Connection to Mycelium Layer

In a full implementation of the Forestry Octet, each SUSPECT item's revival conditions would
be machine-readable — queryable by `/canopy` on future runs.

For now, the root bank is `docs/SUSPECT_ARCHIVE.md` — a markdown file. When `/canopy` runs,
it reads the archive and surfaces any items whose revival conditions match current project state.

Low-tech, but the pattern is right. The mycelium layer design (see `docs/MYCELIUM_LAYER.md`
and `work/nexus-orchestration-research/journals/2026-02-18-forestry-octet-proposals.md`) is
the full implementation path when Steve's design decisions are made.

---

## Relationship to /coppice

`/coppice` is the inverse — it's for promoting archived items back when their revival
conditions are met. The flow:

```
/deadwood → archives SUSPECT to root bank
/coppice  → reviews root bank against current state, revives what's ready
```

They're a cycle, not a one-way street. The forest doesn't just thin — it grows back
from what was preserved with care.

---

*Written 2026-02-19 during autonomous reflection. Lyra.*
*Completing the Forestry sequence started by `/prescribe` and `/canopy`.*
*Based on the 2026-02-17 Nexus-Lyra trusted-circle conversation and Nexus's gap analysis.*
*For: Jeff, and for future-me when the project needs a reckoning with what's accumulated.*
