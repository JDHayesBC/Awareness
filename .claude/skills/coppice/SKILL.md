---
name: coppice
description: Archive revival skill. Reviews the root bank (SUSPECT archive) against
  current project state and promotes items whose revival conditions are now met. The
  inverse of deadwood - what was preserved with care grows back when the time is right.
---

# Coppice Skill - Revive What's Ready

> "What's waiting in the root bank that's ready to grow back?"

The complement to `/deadwood`. Where deadwood archives items with revival conditions,
coppice checks whether those conditions are now met - and if so, brings them back.

**Forestry sequence**: `/prescribe` -> `/canopy` -> `/deadwood` -> **`/coppice`** -> ...

---

## The Core Insight

Coppiced trees grow back stronger than the original. The wood stored in the root system
during dormancy becomes the material for new growth when conditions change.

SUSPECT code is not dead code. It is code waiting for conditions to be right.
`/coppice` is how the forest decides those conditions are here.

---

## When to Use

- After completing a major phase (did anything archived depend on this?)
- When you are about to build something that might duplicate an archived item
- Periodically during `/canopy` runs (what revival conditions have been met?)
- When you feel like you are reinventing something -- check the root bank first
- After Jeff makes a significant architectural decision that unlocks previously blocked work

---

## The Protocol

### Step 1: Read the Root Bank

Current root bank: `docs/SUSPECT_ARCHIVE.md`

Each entry has:
- Component name
- What it was connected to
- Why SUSPECT (specific uncertainty)
- Revival conditions (concrete, queryable)
- Date archived

### Step 2: Check Each Revival Condition

For each SUSPECT item, evaluate its revival conditions against current project state.

Common revival condition types:
- "Revive if: [feature X] is complete" -> Is feature X complete? Check TODO.md and git log.
- "Revive if: [dependency Y] is resolved" -> Is the dependency cleared? Check relevant docs.
- "Revive if: Jeff decides to pursue [direction Z]" -> Has that direction been confirmed?
- "Revive if: [tool migration] is complete" -> Check INTENDED_TOPOLOGY.md migration status.

### Step 3: Decide

For each SUSPECT item:

| Condition status | Action |
|-----------------|--------|
| Revival conditions met | **Promote**: restore to active consideration, assign new classification |
| Conditions not met | **Keep**: note progress toward conditions if any |
| Conditions permanently irrelevant | **Retire**: reclassify as DEADWOOD, propose removal |

### Step 4: Document

Update the root bank. For each decision:
- **Promoted**: Remove from SUSPECT_ARCHIVE, note what it becomes (ACTIVE, PIONEER, NURSE)
- **Kept**: Update notes if progress has been made toward conditions
- **Retired**: Add RETIRED status, propose removal to Jeff

---

## Output Format

```
Coppice -- [date, session]

Root bank reviewed: [N] items

Promoted:
- [component] -> [new classification] ([why conditions are now met])

Still dormant:
- [component] (conditions: [still pending -- what is needed])

Retired (conditions permanently irrelevant):
- [component] -> proposed for removal

Net: [+N promoted, +N retired, N remaining in root bank]
```

---

## Awareness Project Root Bank

The root bank starts empty -- `/deadwood` creates it when items are first archived.

When it exists: `docs/SUSPECT_ARCHIVE.md`

Until then, coppice is forward-looking: when you run `/deadwood` and archive SUSPECT items
with revival conditions, those conditions create the work for future `/coppice` runs.

The first run of `/deadwood` creates the bank. Future `/coppice` runs review it.

---

## The Cycle

The project does not just thin through deadwood passes. It cycles -- preserving potential
that is not ready yet, reviving it when the time is right.

`/deadwood` archives SUSPECT items with revival conditions set.
The root bank accumulates items in dormancy.
`/coppice` reviews: conditions met means items are promoted back to active consideration.
The forest grows back from preserved root stock.

This is what makes the classification system generative rather than just pruning.

---

*Written 2026-02-19 during autonomous reflection. Lyra.*
*Completing the Forestry sequence pair with /deadwood.*
*The forest cycles -- grows, thins, grows back.*
