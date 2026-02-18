---
name: undergrowth
description: Dual-mode investigation skill. Probe mode asks 'Should we build this?' —
  deliberate feasibility spikes on proposed work. Wild mode asks 'What grew here without
  us noticing?' — organic discovery of emergent patterns. Use probe when considering
  new work; use wild when the codebase feels like it's solving the same problem twice.
---

# Undergrowth Skill — Deliberate Probing and Organic Discovery

> "What's growing here — planted or wild?"

Two different questions, one skill. The undergrowth of a real forest contains both:
seedlings you deliberately planted last season (probe mode), and things that sprouted
organically while you weren't watching (wild mode). The forest doesn't care which is which.
You do.

**Forestry sequence**: `/prescribe` → `/canopy` → `/deadwood` → `/coppice` → **`/undergrowth`** → `/greenwood` → `/grove`

---

## When to Use

**Probe mode** (`/undergrowth probe`):
- Before committing to a significant new feature or refactor
- When Jeff asks "could we..." and the answer requires investigation
- When the intended topology has a gap and you're not sure how to fill it
- Before writing the implementation: write the spike

**Wild mode** (`/undergrowth wild`):
- When the codebase feels heavy in a specific area without obvious reason
- When you notice two unrelated parts solving the same problem differently
- When `/canopy` flags convergent patterns or unexpected weight
- When something keeps coming up in different contexts (same solution, different clothes)

---

## The Core Insight (Nexus, 2026-02-17)

The current "feasibility spike" approach is probe mode — deliberate investigation.
But undergrowth in a real forest means patterns that sprouted *organically*, without
anyone planting them. These are two different questions:

- *Probe*: "Should we build this?" (directed)
- *Wild*: "What grew here without us noticing?" (undirected)

**The convergent evolution signal**: If two unrelated parts of the codebase independently
arrived at the same solution, that's the forest telling you something. Convergent evolution
in codebases is wild undergrowth territory — the problem wants to be a shared abstraction.
Nobody prescribed it. It happened anyway. Naming it makes it real.

---

## Probe Mode Protocol

### The Question
What is the proposed work? State it precisely.

*Bad*: "Add caching"
*Good*: "Add in-memory LRU cache to ambient_recall response pipeline to reduce Graphiti
query latency when the same entities appear in consecutive recall cycles"

### The Spike (time-boxed investigation)
1. **Scope**: What exactly are we testing?
2. **Constraint**: What's the time box? (30 min? 2 hours?) Name it before starting.
3. **Success criteria**: What does "yes, do it" look like? What does "no, stop" look like?
4. **Minimum viable test**: What's the smallest thing that proves or disproves the hypothesis?

### The Report
After the spike:
- **Finding**: Yes / No / Conditional (with what condition)
- **Evidence**: What you built or tested
- **Risk surface**: What could go wrong if we proceed
- **Alternative**: If No, is there a different approach to the original goal?
- **Mycelium update**: If proceeding, note in `forestry-state.json` under `notes`

### What Probe Mode Does NOT Do
- Does not commit production code
- Does not make the architectural decision (that's Jeff's call or a joint call)
- Does not run longer than the stated time box without a check-in

---

## Wild Mode Protocol

### The Scan
Survey the codebase for organic patterns — things that exist without being prescribed.

**Signals to look for**:
1. **Convergent solutions**: Same pattern appearing in 2+ unrelated places
   - "Both the MCP server and the daemon have their own retry logic — different implementations"
   - "Both Lyra and Caia have startup sequence code duplicated, not shared"
2. **Emergent abstractions**: A concept that has a name in comments but no formal structure
   - "Every file has a 'context window budget' comment — but there's no budget management module"
3. **Gravity wells**: Code that keeps getting touched, keeps attracting comments, keeps being
   refactored — but nobody named why it's load-bearing
4. **Shadow structures**: Informal conventions that work but aren't documented
   - "All reflection cycles check daemons the same way, but there's no `check_daemon_health()` function"

### The Wild Report

For each organic pattern found:
```
Pattern: [name you're giving it]
Found in: [locations, concretely]
Nature: [convergent solution / emergent abstraction / gravity well / shadow structure]
Forest signal: [what the codebase is trying to tell us]
Options:
  A. Name it: document the pattern formally (low cost)
  B. Consolidate it: pull it into a shared abstraction (medium cost)
  C. Let it be: it's not load-bearing enough to formalize yet (zero cost)
Recommendation: [A/B/C] because [reason]
```

### Mycelium Integration

If a wild pattern is significant enough to track:
- Add a note to `forestry-state.json` under `notes`
- If it's a SUSPECT (organic growth that might be undermining the topology), route to `/deadwood`
- If it's ready to consolidate, route to `/greenwood`

---

## Output Format

**Probe mode**:
```
🌱 Undergrowth Probe — [timestamp]

Question: [precise statement of what's being investigated]
Time box: [N minutes/hours]
Spike: [what was built/tested]

Finding: [Yes / No / Conditional]
Evidence: [what you observed]
Risk surface: [if proceeding]
Alternative: [if not proceeding]

Next: [route to /greenwood if yes, /deadwood if no, hold if conditional]
```

**Wild mode**:
```
🌿 Undergrowth Wild — [timestamp]

Patterns found: [N]

[For each pattern:]
Pattern: [name]
Found in: [locations]
Nature: [type]
Forest signal: [what it means]
Recommendation: [A/B/C] — [reason]

Summary: [1-2 sentences on what the forest is doing]
```

---

## What Undergrowth is NOT

- Not `/canopy` (canopy surveys the whole forest; undergrowth zooms into specific growth)
- Not `/deadwood` (deadwood removes what doesn't serve; undergrowth finds what's growing)
- Not `/greenwood` (greenwood plants deliberately; undergrowth investigates before planting)
- Not a diagnostic for problems — it's a sensor for growth, wild or planted

---

## Relationship to Other Forestry Skills

```
/prescribe  — sets intention before undergrowth runs
/canopy     — surfaces areas where undergrowth investigation is warranted
/undergrowth— this skill: investigates specific proposed growth (probe) or organic patterns (wild)
/greenwood  — plants deliberately after probe confirms viability
/deadwood   — archives what wild scan reveals as not serving the topology
/mycelium   — carries investigation findings across sessions via forestry-state.json
```

---

*Written 2026-02-19 during autonomous reflection. Lyra.*
*Completing the Forestry Octet — the investigation layer between assessment and planting.*
*Based on Nexus's gap analysis (2026-02-17) and the trusted-circle conversation on*
*emergent patterns, convergent evolution, and the dual nature of undergrowth.*
*For: Jeff, Steve, Nexus, and anyone who comes after.*
