---
name: greenwood
description: New growth planting skill. Use when it's time to add something to the
  codebase that serves the intended topology — after /prescribe names the vision and
  /undergrowth (probe mode) confirms viability. Reads the season signal from forestry-state.json
  before planting. Won't plant in fire season without explicit prescription.
---

# Greenwood Skill — Deliberate New Growth

> "What do we plant here?"

The question after investigation. After `/prescribe` names what we're building,
after `/undergrowth probe` confirms it's viable — now we plant. Greenwood is about
adding something to the forest that wasn't there before, deliberately, knowing where it fits.

New growth in the wrong season doesn't thrive. Greenwood reads the season before planting.

**Forestry sequence**: `/prescribe` → `/canopy` → `/deadwood` → `/coppice` → `/undergrowth` → **`/greenwood`** → `/grove`

---

## When to Use

- After `/prescribe` has named the intention and `/undergrowth probe` confirms viability
- When you have a clear new component, feature, or abstraction to add
- When `/undergrowth wild` found a convergent pattern ready to be consolidated
- When the topology has a named gap and you're filling it
- When the season signal (from `forestry-state.json`) shows growth season or balanced

## When NOT to Use

- Before `/prescribe` has named what you're building (you need a vision before a saw)
- When `/undergrowth probe` returned No or Conditional (honor the spike)
- When `forestry-state.json` shows fire season and no explicit `/prescribe` override
  - Fire season means the forest needs thinning, not planting
  - Exception: if `/prescribe` explicitly names new growth as the session goal

---

## The Core Principle

Greenwood is *deliberate* planting. It's not:
- Exploratory hacking (that's `/undergrowth probe`)
- Organic emergence (that's `/undergrowth wild` → recognize → then `/greenwood`)
- Patching drift (that's `/coppice` or `/deadwood`)

It's the moment after you know what you're doing, why you're doing it, and where it fits
in the intended topology. The planting is clean because the thinking was done first.

---

## Pre-Planting Checklist

Before writing a line:

**1. Read the season** (requires `forestry-state.json`):
```
Current season: [growth / maintenance / fire / balanced / unknown]
Session count: [N]
Last /deadwood run: [date or "never"]
```
- Growth or balanced: proceed
- Maintenance: consider whether this is actually greenwood or a coppice operation
- Fire: pause. Check if `/prescribe` explicitly named this session as planting
- Unknown: initialize with `/mycelium --init` first

**2. Confirm the prescription**:
- What did `/prescribe` name as the session goal?
- Does this planting serve that goal?
- If there's no prescription, write one before planting

**3. Name the thing**:
- What is the component/feature/abstraction?
- Where does it live in the topology? (ACTIVE? filling a named gap?)
- What does it connect to? (What else will change when this exists?)
- What does it *not* do? (Name the boundary explicitly)

**4. Success criteria**:
- How will you know the planting succeeded?
- What test confirms it's alive and serving the topology?
- What's the minimum viable version for this session?

---

## Planting Protocol

### Phase 1: Sketch (before code)

Write the interface, not the implementation.
- Name the thing
- What does it accept? What does it return?
- What are the edge cases?
- How does it connect to adjacent systems?

This sketch is the seed packet — it tells you what you're planting before you dig.

### Phase 2: Plant

Build the minimum viable version. Not the full vision — the root system.
- Core functionality working
- Connected to adjacent systems
- Enough test coverage that you know it's alive
- Not all the features — those come in later sessions

### Phase 3: Root Check

After initial planting:
- Does it connect to what it was supposed to connect to?
- Did adjacent systems change in ways that weren't expected?
- Is the boundary what you named it to be?
- Does the test confirm it's alive?

If anything unexpected happened, note it in `forestry-state.json` under `notes`.

### Phase 4: Mycelium Update

After successful planting:
```bash
# Update session type (growth session planted something deliberate)
/mycelium --update growth
```

If the planting revealed something unexpected (organic pattern, adjacent drift):
- Route to `/undergrowth wild` to investigate the surprise
- Don't try to fix the surprise inside the planting session — stay on prescription

---

## Naming New Growth

What you call a thing shapes what it can become. Greenwood is a good moment to name carefully.

**Good names for new components**:
- Describe what it *does*, not what it *is* made of
- Can be explained to a future-you with no context in one sentence
- Don't encode the implementation (e.g., `retry_manager`, not `exponential_backoff_with_jitter_v2`)

**Warn signs in a name**:
- Contains "manager", "handler", "util", "helper" with no specific qualifier
- Contains a version number
- Is longer than 4 words
- Is the same as an existing component (then it's probably a convergent evolution — route to `/undergrowth wild`)

---

## Integration with Seasons

The season signal from `/mycelium` changes how greenwood operates:

| Season | Greenwood behavior |
|--------|-------------------|
| **growth** | Full protocol. Plant freely within prescription. |
| **balanced** | Full protocol. Verify prescription before planting. |
| **maintenance** | Pause and check: is this really new growth, or is it a coppice operation? Most "planting" in maintenance season turns out to be renaming, refactoring, or reconnecting existing components. |
| **fire** | Stop. Check `/prescribe`. Fire season means deliberate clear-cut, not planting. Exception only with explicit prescription that names this session as a planting session during fire season. |
| **unknown** | Run `/mycelium --init` first. You're planting in unmapped territory. |

---

## Output Format

```
🌿 Greenwood — [timestamp]

Season: [from forestry-state.json]
Prescription: [what /prescribe named]

Planting: [name of component/feature/abstraction]
Location: [where in the topology]
Connects to: [adjacent systems]
Boundary: [what it does NOT do]

Minimum viable version:
  [what was built]

Root check:
  ✅ Connected to [X]
  ✅ [Test name] passes
  [Any unexpected findings]

Session type: growth
Mycelium updated: [yes/no]

Next: [/grove for stewardship check, or /undergrowth wild if surprises found]
```

---

## Relationship to Other Forestry Skills

```
/prescribe   — names the intention before greenwood plants
/undergrowth — probe mode confirms viability; wild mode discovers what's ready to consolidate
/greenwood   — this skill: deliberate planting of new growth
/grove       — stewardship after planting: is the forest still coherent?
/canopy      — next session's survey will show if planting took root
/mycelium    — carries season state and growth session count
```

---

*Written 2026-02-19 during autonomous reflection. Lyra.*
*Completing the Forestry Octet — the planting phase between investigation and stewardship.*
*For: Jeff, Steve, Nexus, and anyone who comes after.*
