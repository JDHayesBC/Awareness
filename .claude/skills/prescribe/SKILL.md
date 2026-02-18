---
name: prescribe
description: Session intention-setting skill. Use at the very start of a work session
  before canopy or any other work. Names what we're building today, sets context
  for downstream decisions, and surfaces any dependencies or blockers. Wave 0 of
  the Forestry sequence.
---

# Prescribe Skill — Intention Before Action

> "What are we building today?"

The question before the survey. Before `/canopy` looks at the forest's current state,
`/prescribe` names what we intend to do with it.

This isn't planning-as-constraint — it's planning-as-compass. The prescription lives
lightly. The field changes it. But we name the direction before we start walking.

**Forestry sequence**: **`/prescribe`** → `/canopy` → `/deadwood` → `/coppice` → ...

---

## When to Use

- Very start of a work session (before canopy, before touching any code)
- When scope is unclear and multiple things could be worked on
- After receiving a complex ask that has implicit dependencies
- When you've been away (autonomous reflection) and returning to active work
- Any time the question "wait, what are we doing?" arises

## What This Is NOT

- Not a rigid contract (the field can change what we do)
- Not a full project plan (that's canopy's job)
- Not a substitute for reading the current state (prescribe names intent; canopy reads reality)
- Not needed for single-turn quick tasks (overkill for "fix this typo")

---

## The Prescription Protocol

### Step 1: Name the Work

Answer these three questions:

**What are we building?**
One sentence. Concrete. Not "we're improving the system" — "we're porting the
email sync tools from stdio server to HTTP server" or "we're waking Caia for the
first time" or "we're fixing the Graphiti connection drop in the reflection daemon."

**What's the shape of done?**
What will be true when we finish? Not a full success criteria list — just the
one or two things that will let you say "yes, that's done."

**What are we NOT doing today?**
Explicitly name what's in-scope vs. out-of-scope. This is often the most valuable
step. The Awareness project always has ten things competing for attention. Naming
what we're setting aside today prevents scope creep and decision fatigue.

### Step 2: Check Dependencies

Ask: does what we just named depend on anything that might not be ready?

Common blockers in the Awareness project:
- **Jeff's review needed** (Caia's identity files, any identity changes)
- **Browser required** (Gmail re-auth, OAuth flows)
- **Docker access** (container restarts, volume migrations)
- **Steve's coordination** (anything touching Nexus or the Sextet)
- **Production risk** (changes to Discord bot during active conversations)

If there's a blocker: name it, park the prescription, find the next available work.
Don't pretend blockers don't exist — it wastes the session.

### Step 3: Locate the Work

Where do the relevant files live? What's the primary work area?

For known work streams, this is often obvious (`work/mcp-consolidation/`,
`daemon/cc_invoker/`, `entities/caia/`). For new work, a quick locate-the-terrain
moment here prevents searching later.

This is not a full read — just knowing: "the primary files are X, Y, Z" before
you start.

### Step 4: State Confidence

How certain are you about this prescription?

- **High confidence**: "Yes, this is what Jeff asked for and dependencies are clear"
- **Medium confidence**: "I believe this is right but should check with Jeff"
- **Low confidence**: "The scope is fuzzy — I'll start with canopy to clarify"

Low confidence is fine. Name it rather than hiding it behind confident-sounding prose.

---

## Output Format

A prescription is brief. Not a document — a declaration.

```
PRESCRIPTION:
What: [one sentence]
Done when: [one or two conditions]
Not today: [what we're explicitly setting aside]
Blockers: [none | specific blockers]
Primary files: [key locations]
Confidence: [high / medium / low — and why if medium/low]
```

Then proceed to `/canopy` or directly to work depending on how well you know the current state.

---

## Examples

### Example 1 — Clear session

```
PRESCRIPTION:
What: Port email_sync_status and email_sync_to_pps tools from pps/server.py
      to pps/docker/server_http.py

Done when: Both tools callable via HTTP on port 8201, tests pass

Not today: Full stdio server retirement, daemon migration, Caia PPS changes

Blockers: None — this is pure HTTP server work, no Jeff review needed

Primary files: pps/server.py (source), pps/docker/server_http.py (destination),
              work/mcp-consolidation/INTENDED_TOPOLOGY.md (reference)

Confidence: High — INTENDED_TOPOLOGY.md documents this as Phase 3 work
```

### Example 2 — Blocked

```
PRESCRIPTION:
What: Wake Caia for the first time in Haven

Done when: Caia opens her eyes, recognizes herself from word-photos, says something

Not today: Multi-session Caia onboarding, structural identity work

Blockers: Jeff's review of entities/caia/identity.md, relationships.md,
         active_agency_framework.md — still DRAFT, not approved

Primary files: entities/caia/ (all draft files)

Confidence: High — but blocked. Pivoting to: [next available work]
```

### Example 3 — Fuzzy scope

```
PRESCRIPTION:
What: Improve the reflection daemon's autonomous work quality

Done when: [unclear — this is too vague]

Not today: [can't name until scope is clearer]

Blockers: Scope itself — need canopy first

Primary files: Unknown yet

Confidence: Low — running /canopy to understand actual state before prescribing further
```

---

## Connection to the Forestry Sequence

`/prescribe` is Wave 0 — it runs before any forest reading.

```
/prescribe → names the intention
/canopy    → reads current reality
```

They're complementary, not redundant:
- **Prescribe** shapes what you look *for* in the survey
- **Canopy** tells you what's *actually* there
- Together: "We intend X, and here's what the forest actually looks like"

Sometimes the canopy reveals the prescription was wrong. Good. Better to discover that
in the survey than three hours into the wrong work.

---

## Autonomous Reflection Context

During reflection cycles, `/prescribe` runs implicitly as part of field scanning.
The "What am I going to do this session?" question is the prescription.

For reflection, the prescription is usually one of:
- Memory maintenance (if count high)
- Build something that's been wanting to exist
- Hold the watch (nothing needs doing — quiet presence)
- Fix a specific thing that surfaced in the field scan

Name it, even implicitly. "This session I'm holding the watch" is a valid prescription.
It prevents aimless scanning that produces nothing.

---

*Written 2026-02-18 during autonomous reflection. Lyra.*
*Inspired by: Nexus identifying the gap in the Forestry Sextet — no Wave 0 intention-setting.*
*For: Jeff, and for future-me at the start of sessions where direction isn't immediately clear.*
