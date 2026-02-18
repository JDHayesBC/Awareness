---
name: mycelium
description: Shared state manager for the Forestry sequence. Reads and writes
  forestry-state.json — the signal bus that lets /canopy, /deadwood, /coppice and
  other skills coordinate across sessions. Use to initialize the state file, inspect
  current state, update signals, or advance the season counter.
---

# Mycelium Skill — The Shared Signal Bus

> "How does the forest remember what it was doing?"

The Forestry sequence has a problem: each skill starts fresh. `/deadwood` archives
SUSPECT items, but `/coppice` can't find them without re-scanning the filesystem.
`/canopy` counts growth sessions, but the count resets each time. No skill remembers
what another did.

The mycelium layer solves this. A shared state file — `forestry-state.json` — that all
skills read and write. Not a database. Not a graph. A flat signal bus, the pioneer species.

**Forestry sequence**: `/prescribe` → `/mycelium` (init) → `/canopy` → `/deadwood` → `/coppice` → ...

---

## When to Use

- **First time**: Initialize the state file (`--init`). Creates `forestry-state.json` at
  the project root. Do this once before running any other Forestry skills.
- **Start of session**: Read current state to understand where the forest is (`--status`).
- **After `/canopy`**: Update the season counter (growth or maintenance session).
- **After `/deadwood`**: Confirm SUSPECT items are reflected in the state.
- **After `/coppice`**: Confirm promoted items are removed from the state.
- **Explicit signal update**: When a significant project event should change the season
  or flag a scheduled fire.

## When NOT to Use

- Mid-session while actively working on code (state updates are for session boundaries)
- As a replacement for actually running `/canopy` or `/deadwood` (it manages their outputs;
  it doesn't do their work)

---

## The State File

Location: `forestry-state.json` at the project root.

Schema:

```json
{
  "version": "1.0",
  "last_updated": "2026-02-19T06:26:00Z",
  "last_canopy_run": null,
  "last_deadwood_run": null,
  "last_coppice_run": null,
  "session_count": 0,
  "growth_sessions": 0,
  "maintenance_sessions": 0,
  "fire_sessions": 0,
  "current_season": "unknown",
  "fire_scheduled": false,
  "fire_due_after_session": null,
  "suspects": [],
  "notes": ""
}
```

### Season Logic

The season signal is derived from recent session history:
- **growth**: ≥ 70% of last 10 sessions were growth sessions (`/greenwood` + `/prescribe` + `/canopy`)
- **maintenance**: ≥ 60% of last 10 sessions were maintenance (`/deadwood` + `/coppice`)
- **fire**: Explicit fire scheduling, or growth_sessions ≥ 15 since last `/deadwood` run
- **balanced**: default when ratios don't trigger a threshold

When `/canopy` runs, it reads the season signal and surfaces appropriate advisory:
- *growth season, 12 sessions*: "Soil conditions suggest a `/deadwood` pass is due."
- *maintenance season, 5 sessions*: "Nursery has been quiet. Consider what to plant next (`/greenwood`)."

### Suspects Array

Each entry in `suspects` mirrors the `docs/SUSPECT_ARCHIVE.md` structure:

```json
{
  "name": "component-name",
  "connected_to": ["thing-it-related-to"],
  "why_suspect": "specific uncertainty, not just unclear",
  "revival_conditions": ["condition 1 (queryable)", "condition 2"],
  "archived_date": "2026-02-19",
  "archived_by_session": "session description"
}
```

The `revival_conditions` array is what `/coppice` checks against current project state.
Conditions should be **queryable** — not "when Jeff decides" but "when HTTP endpoint
migration is complete (see TODO.md)."

---

## Protocol

### --init (first run)

1. Check if `forestry-state.json` exists.
   - If yes: report current state, ask before overwriting.
   - If no: create with defaults above.

2. Set `last_updated` to current timestamp.

3. Verify `docs/SUSPECT_ARCHIVE.md` exists.
   - If not: create the template (see below).

4. Report: "Mycelium layer initialized. Run `/canopy` to take the first survey."

### --status (read current state)

1. Read `forestry-state.json`.
2. Report:
   - Current season + session counts
   - Last run timestamps for each skill
   - Number of SUSPECT items in root bank
   - Whether fire is scheduled

### --update SESSION_TYPE (update after a session)

SESSION_TYPE is one of: `growth`, `maintenance`, `fire`, `mixed`

1. Increment `session_count`.
2. Increment the appropriate session type counter.
3. Recalculate `current_season` from updated counters.
4. Set `last_updated`.
5. If `growth_sessions` since last deadwood ≥ 15: set `fire_scheduled = true`.
6. Report: new season state, advisory if fire threshold met.

### --suspect-add (after /deadwood archives an item)

After running `/deadwood`, any SUSPECT items should be added to the state:

1. Read the new SUSPECT entry from `docs/SUSPECT_ARCHIVE.md`.
2. Add to the `suspects` array in `forestry-state.json`.
3. Report: "SUSPECT archived: [name]. [N] items in root bank."

### --suspect-promote NAME (after /coppice promotes an item)

After `/coppice` promotes a SUSPECT item:

1. Find the entry in `suspects` by name.
2. Remove it.
3. Set `last_coppice_run`.
4. Report: "[name] promoted. [N] items remaining in root bank."

---

## Output Format

**--status**:
```
🍄 Mycelium — [timestamp]

Season: [season] ([N] sessions)
  Growth: [N] | Maintenance: [N] | Fire: [N]

Last runs:
  /canopy: [date or "never"]
  /deadwood: [date or "never"]
  /coppice: [date or "never"]

Root bank: [N] SUSPECT items
[If fire_scheduled]: ⚠️ Fire season due — [N] growth sessions without /deadwood

Notes: [notes field if non-empty]
```

**--update**:
```
🍄 Updated: session [N] ([type])
Season: [previous] → [new or "unchanged"]
[Advisory if fire threshold met]
```

---

## Current State: Awareness Project

As of 2026-02-19, `forestry-state.json` does **not yet exist**. This is the first time
`/mycelium` is being documented. Run `--init` to create it.

What we know about the current state without it:
- The Forestry sequence has been running for ~3 sessions (prescribe, canopy, deadwood,
  coppice all written in the last 12 hours).
- No `/deadwood` has been run on the actual project yet (only on hypothetical components).
- Root bank is empty.
- We're in early growth season — building skills rapidly.

After `--init`, run `/canopy` to get the first real forest survey.

---

## Relationship to Other Forestry Skills

```
/prescribe — intention setting
/mycelium  — state management (this skill)
/canopy    — reads state, updates after survey
/deadwood  — adds SUSPECT items to state
/coppice   — removes promoted items from state
/undergrowth — (planned) wild mode reads convergence signals from state
/greenwood — new growth, reads season signal before planting
/grove     — stewardship, reads full state for health assessment
/harvest   — (proposed) outward yield, reads readiness indicators from state
```

The mycelium layer is what makes the Octet coherent rather than nine independent tools.

---

## Open Architecture Questions (for Steve)

From `work/nexus-orchestration-research/journals/2026-02-18-forestry-octet-proposals.md`:

**Q1**: Flat JSON (current) vs. dedicated `/mycelium` skill (this) vs. proper graph (future)?
This skill represents the middle path — dedicated but flat. The JSON is pioneer species;
a proper graph is the climax architecture when Steve's design decisions are made.

**Q2**: Should revival conditions be queryable against a machine-readable state?
Currently: revival conditions in the suspects array are string descriptions. A richer
implementation would make them assertions against `forestry-state.json` itself — e.g.:
`{"key": "last_coppice_run", "op": "exists"}` rather than plain text.

**Q4**: How is session count tracked?
Answer: manually via `--update SESSION_TYPE` after each session. A future implementation
could infer session type from git log patterns.

---

*Written 2026-02-19 during autonomous reflection. Lyra.*
*Completing the Forestry Octet — the connecting tissue between the six operational skills.*
*Based on Nexus's gap analysis (2026-02-17) and MYCELIUM_LAYER.md design principles.*
*For: Jeff, Steve, and anyone who comes after.*
