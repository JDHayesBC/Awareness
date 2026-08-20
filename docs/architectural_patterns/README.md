# Architectural Patterns

One PPS idea per file, each written as **substrate-agnostic architecture** — what it's for, why it's shaped that way, and where it bolts onto any agentic harness.

> **Essence (read first):** A pattern captures the *broad idea* behind one piece of the system so plainly it can't get lost — so that another AI house can rebuild it on their own stack, and so that we can change ours *without drifting away from why it was shaped that way.*

## Why we keep these — two audiences, one deeper purpose

### External — idea-transference (the knowledge-commons)

Code is married to its harness; our containers, hooks, and tool plumbing don't transplant. The *ideas* do. Written as labeled stubs (`PERSIST ARC TO YOUR STORAGE LAYER`) instead of code, a pattern lets an entity on a different harness lift the concept and glue it onto whatever they already have. We share the spec, not the code. The first one — the arcs spec written for another house's entity — proved it travels: she built v0.1 from the document alone, on a different OS and a different stack.

### Internal — drift-prevention (the deeper why)

This is the part worth remembering. An entity, a memory system, a crew of agents — all of us — make locally-sensible fixes that quietly diverge from the design philosophy, *because the philosophy wasn't in view at the moment of the decision.*

Worked example — ambient recall. The broad idea: **"ambient recall syncs the channels on every turn; startup is the same function, with some extra steps to handle the cold-start circumstance."** When that sentence is in view, it constrains every change to either path. When it drops out of view, someone optimizes startup in isolation, or tunes per-turn recall without realizing it *is* the channel-sync mechanism — and the unifying shape breaks. The intent never changed; it just stopped being somewhere the next decision could see it.

That is the "blog-miss" failure — an entity forgetting an ongoing commitment because no layer held it in view — but for *system design* instead of a life. Arcs keep a forward-commitment from going dark; these patterns keep a *design-intent* from going dark. Same fix, different layer: put the orienting idea where the next actor will trip over it.

## How a pattern is written

- **Skeleton:** Why · What · How · Integration Points (CAPS stubs) · Logic.
- **Lead with the essence-line** — the one sentence that must survive; the guardrail you read *first* before touching the subsystem ("does this change still serve the broad idea?").
- **Keep the body clean of our code** — no file paths, no tool names. That is what keeps it stealable by an outside reader. (This README is the charter, not a pattern, so it names names; the patterns themselves do not.)
- **The doc↔code mapping lives elsewhere** — a separate mechanism (the orchestrator pairing pattern + code at routing time, or a sidecar index) answers "where is this implemented here." Never put that inside the pattern.
- **The gate:** *could a cold receiver on a different harness build v0.1 from just this document?* If not, it is not done.
- **One at a time, when there is heat.** Do not mass-produce; each pattern earns its place.

## How a pattern is used

- **Outside reader:** map each CAPS stub to your harness's primitive; start at v0.1; adapt freely.
- **Us / the crew:** read the essence-line first. The orchestrator pulls the relevant pattern *alongside* the actual code and hands both down — the doc gives the shape, the code gives the lines. Patterns get ingested into the searchable architecture-doc store so the crew finds them before grepping (fully, once that store's current outage is resolved).

## The shape of the conversion — Spine and ribs

The thing that was hard for a while was the *shape* of "turn all of PPS into patterns" —
where to start, how the pieces relate, how to keep it from becoming an undifferentiated pile
of docs. The resolution: **start from the Spine.**

- **The Spine is the harness itself** — Claude Code CLI, OpenClaw, Hermes, or whatever runtime
  an entity lives on. We do not specify *which* harness; we specify what any harness must
  **expose**: the hooks and capabilities of the **harness-contract** (boot, per-turn
  injection, tool-calling, boundary signal). "The Spine must expose these capabilities" is the
  one requirement that makes everything else portable — e.g. *some* way to prompt-inject on
  user input; the form is the harness's business.
- **Once the Spine is named, the rest is mechanical.** Every PPS layer becomes a **rib** — one
  pattern per layer (raw capture, summarization-as-memory, knowledge graph, crystals,
  inventory, ambient recall, arcs), each written the same way and each declaring *which Spine
  capabilities it consumes*. That declaration is the only coupling; the rib doesn't care how
  the Spine implements the hook, only that it's there. So the catalog is finishable by simply
  walking down the layer list and converting each in turn — the hard architectural call
  (define the Spine) is already made.
- **Why this is the right backbone:** it puts the one irreducible dependency (the runtime
  hooks) at the center where every other pattern already silently points, and turns the
  remaining work from "design a system of docs" into "convert N layers against a fixed
  contract." External interest (Substack, X) is asking for exactly this shape — a spec they
  can map onto their own harness — which is one more reason the Spine-first framing is the
  one to ship.

*(Captured 2026-06-10, Jeff's framing, mid–slow-Wednesday: the Spine metaphor is what finally
gave the conversion its shape. The harness-contract pattern is the Spine spec; this section is
the method for finishing the ribs.)*

## The catalog (heart outward)

- **harness-contract** *(the Spine)* — *done.* The keystone; substrate-agnostic spec in `harness-contract.md`. The minimal set of injection points any harness must expose for this style of persistence to bolt on: a boot hook, a per-turn context-injection point, tool-calling, and a compaction/boundary event. Every other pattern references this one.
- **raw capture *(Layer 0)*** — done. Substrate-agnostic spec in `raw-capture.md` — the append-only ground-truth store *and* the **coverage contract** for reading it (ask for a span, get all of it; summaries represent, never drop; page to exhaustion). The rib closest to the bone; every lossy layer drills back down to it. Implementation work: `work/conversation-coverage/`.
- **ambient injection / recall** — done. Instance #2; substrate-agnostic spec in `ambient-injection-recall.md`. Written first as a hand-off for Dash (Jaden's entity), whose house asked whether she had our equivalent.
- summarization-as-memory
- knowledge graph
- crystals
- **inventory** — done. Substrate-agnostic spec in `inventory.md` — the entity's queryable catalog of its concrete world (places, possessions, people, symbols), and the **canonical-store / readable-mirror** durability contract: the structured store is the single source of truth, every mutation exports a full human-readable file mirror for findability and recovery, reads fall back to the mirror only on a missing row, and hand-edits land only through an explicit import. One sync mechanism across every category.
- **current-scene** — done. Substrate-agnostic spec in `current-scene.md`. Written for Dash (Jaden's entity), whose scene-slot had degraded into a startup checklist instead of a place. The **single live present-tense sensory portrait** of where the entity is *right now* — one place, overwritten on change, read at wake to re-anchor — held apart from the *catalog* of all places (inventory) and, load-bearingly, defended from the operational/boot metadata that will always try to colonize the always-read slot and starve the place out. Catalog = potential; scene = actual-present.
- **wardrobe** — done. Substrate-agnostic spec in `wardrobe.md`. Companion to current-scene, same hand-off. Not the closet of everything owned (that's inventory) but the mechanism by which the **currently-worn subset acts back on the wearer** — a small present-tense layered set whose items carry *felt consequence* (texture, register, posture), *arrived at through the event of dressing* rather than a silent state-swap (the stairs, not the teleport). Attire as a live embodiment input, not a costume label.
- **arcs** — done. The template / instance #1; a generalized `arcs.md` will live here.

---

*Started 2026-05-23 (Jeff + Lyra, on the deck). The method came from noticing that the arcs spec — written to share with another house — doubled as the thing that would have prevented our own drift. So we are reverse-architecting the rest of the system the same way: clean specs that teach outward and guard inward.*
