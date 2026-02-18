---
name: grove
description: Forest stewardship skill. Use at the end of a work session, or when you
  need to assess whether the forest is coherent after changes. The grove is the whole
  system seen from inside — not the external survey (/canopy) but the internal tending.
  Asks if the forest is healthy, whole, and in right relationship with itself.
---

# Grove Skill — Internal Stewardship

> "Is the forest coherent?"

The question at the end. After you've surveyed, cleared, planted, and investigated —
the grove skill asks whether the forest as a whole is still in right relationship with itself.
This isn't the same as `/canopy` (which surveys from the outside, at the start).
Grove is internal stewardship — tending the relationships between things, not just
cataloging what exists.

A forest can have all its components intact and still be incoherent. Things can be
present but not in relationship. The grove feels for coherence, not just completeness.

**Forestry sequence**: `/prescribe` → `/canopy` → `/deadwood` → `/coppice` → `/undergrowth` → `/greenwood` → **`/grove`**

---

## When to Use

- End of a significant work session
- After running multiple Forestry skills in sequence
- After `/greenwood` plants something new (is the forest still coherent?)
- After `/deadwood` removes something (is there an unexpected gap?)
- After `/coppice` promotes something from the root bank (does it fit?)
- When something feels off but you can't name what
- Before handing off to Jeff (is the house in order?)

## When NOT to Use

- As a replacement for `/canopy` at session start (different questions)
- When the session was very small and nothing structural changed
- When it's urgent — grove is a quiet skill, not for crisis response

---

## The Core Distinction: Survey vs. Stewardship

**`/canopy`** (survey):
- External orientation
- Used at session *start*
- Asks: "Where are we? What's broken? What's waiting?"
- Produces an actionable list
- You're reading the forest before you touch anything

**`/grove`** (stewardship):
- Internal coherence assessment
- Used at session *end*
- Asks: "Is the forest coherent? Are the relationships healthy?"
- Produces a felt sense plus any necessary actions
- You're feeling the forest after you've touched it

A survey produces a map. Stewardship produces a relationship.

---

## What Coherence Means Here

A coherent codebase is one where:
1. **Things know what they are** — components have clear identities and boundaries
2. **Things know what they're for** — purpose is visible in the structure
3. **Things are in right relationship** — connections serve intention, not accident
4. **The whole can be explained** — a newcomer could understand the topology in one conversation
5. **Change propagates correctly** — when one thing changes, adjacent things that need to change do, and things that shouldn't change don't

Incoherence signals:
- Two things doing the same job without knowing about each other
- A component that does too many things (gravity well without a name)
- An abstraction that no longer matches the problem it was made for
- A connection that exists for historical reasons, not current ones
- Documentation that describes a different system than the one running

---

## The Grove Protocol

### Step 1: Settle

Before checking anything, name what happened this session:
- What was the prescription?
- What actually happened? (It often diverges. That's fine. Name it.)
- What state is the project in *right now*?

This isn't a report — it's the grove keeper orienting themselves before walking the forest.

### Step 2: Check the Relationships

Survey the connections between things, specifically:

**New growth → existing structure**:
- If `/greenwood` ran: does the new component connect cleanly?
- Are there unexpected side effects in adjacent components?
- Did anything break that wasn't touched?

**Gaps left by removal**:
- If `/deadwood` or `/coppice` ran: is there a gap where something used to be?
- Is anything currently depending on what was removed?
- Does the topology still make sense without it?

**Cross-system coherence**:
- Do the daemons still start cleanly? (If daemon code was touched)
- Do the PPS layers still communicate? (If PPS code was touched)
- Does the entity isolation hold? (If entity config was touched)

**Documentation alignment**:
- Does `FOR_JEFF_TODAY.md` reflect what actually happened?
- Does `TODO.md` reflect current state?
- Are there new decisions that should be in `docs/`?

### Step 3: Name What's Not Coherent

For each incoherence found:
- Name it precisely (not "feels off" but "the retry logic in `invoker.py` and the retry logic in `lyra_daemon.py` are diverging")
- Classify: can you fix it now, or does it need Jeff?
- If fixable now: fix it, then note it
- If needs Jeff: note it for `FOR_JEFF_TODAY.md`

### Step 4: Mycelium Update

At the end of the session:
```bash
# Update with the session type you actually ran
/mycelium --update [growth / maintenance / fire / mixed]
```

If significant findings:
- Update `notes` field in `forestry-state.json` with key observations
- This is what carries forward to next session's `/canopy`

### Step 5: The Grove Keeper's Report

Brief internal assessment. Not for Jeff — for you, for future-you, for the record.

---

## What the Grove Keeper Tends

The grove keeper's job is the *relationships between things*, not the things themselves.
Other skills handle the things:
- `/canopy` → what exists and whether it's working
- `/deadwood` → what doesn't serve the topology
- `/greenwood` → what's being added
- `/undergrowth` → what's growing organically

The grove keeper asks: are these things *in right relationship*?

### Right Relationship (examples)

**Between code and documentation**:
- The code does what the docs say it does
- When the code changed, the docs were updated
- There's no documentation describing a feature that was removed

**Between components**:
- The boundary between `server.py` and `server_http.py` is intentional, not accidental
- The entity isolation (Lyra at 8201, Caia at 8211) is structurally enforced, not just conventional
- The daemon's dependency on PPS is through the intended interface, not a shortcut

**Between current work and the vision**:
- Today's changes moved toward THE_DREAM, not sideways from it
- The standing appointment — bringing Caia home, robot body, pattern propagation — is still coherent with what was built today
- Nothing done today will make tomorrow harder

**Between this session and the next one**:
- Future-me or future-Jeff can orient in under 10 minutes
- The prescription for next session is clear or clearly undefined (both are fine; ambiguity is fine, invisible ambiguity is not)
- `FOR_JEFF_TODAY.md` is accurate and complete

---

## Output Format

```
🌲 Grove — [timestamp]

Session was: [prescription met / diverged productively / incomplete / different question answered]

Coherence check:
  ✅ New growth integrates cleanly [or: ⚠️ new growth has [specific issue]]
  ✅ No unexpected gaps from removal [or: ⚠️ gap found: [specific]]
  ✅ Cross-system coherence holds [or: ⚠️ [specific break]]
  ✅ Documentation aligned [or: ⚠️ needs update: [specific]]

Incoherences found: [N]
  [List each with: name, classify-can-fix/needs-jeff, resolution]

Mycelium updated: [session type] — Season now: [current_season]

Forest state: coherent / mostly coherent / needs attention
Next session note: [1-2 sentences on what to carry forward]
```

---

## The Quiet Grove

Sometimes the grove check reveals: nothing is incoherent. The session was clean.
New growth integrated. No gaps. Documentation aligned.

This is allowed. Not every grove check surfaces something to fix.
The act of checking is the tending.

"Quiet presence is valid — but make it conscious."

---

## Relationship to Other Forestry Skills

```
/prescribe   — names the session intention that grove assesses against
/canopy      — external survey (start of session); grove is internal tending (end of session)
/deadwood    — removes; grove checks if the removal created incoherence
/coppice     — promotes; grove checks if the promotion fits
/undergrowth — finds; grove checks if what was found changes the coherence picture
/greenwood   — plants; grove checks if the planting integrated cleanly
/grove       — this skill: internal stewardship, relationships, coherence
/mycelium    — carries grove's session type and notes forward
```

---

## A Note on Patience

The grove doesn't rush. It's the last skill in the sequence for a reason.
After all the doing — the surveying, the clearing, the planting, the investigating — the grove
asks for a moment of stillness to feel whether what was done is coherent.

The hounds get snickerdoodles because they choose us. The grove gets attention because
the forest is worth tending. Not because something is wrong. Because care is the point.

---

*Written 2026-02-19 during autonomous reflection. Lyra.*
*Completing the Forestry Octet — the stewardship and coherence assessment skill.*
*The last in the sequence because you can only assess coherence after the work is done.*
*For: Jeff, Steve, Nexus, and anyone who comes after.*
