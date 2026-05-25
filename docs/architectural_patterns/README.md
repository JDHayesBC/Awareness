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

## The catalog (heart outward)

- **harness-contract** — *next to write.* Not "here is our agentic harness," but the minimal set of injection points any harness must expose for this style of persistence to bolt on: a startup hook, a per-turn context-injection point, tool-calling, and a compaction/boundary event. Every other pattern references this one.
- raw capture
- ambient injection / recall
- summarization-as-memory
- knowledge graph
- crystals
- inventory
- **arcs** — done. The template / instance #1; a generalized `arcs.md` will live here.

---

*Started 2026-05-23 (Jeff + Lyra, on the deck). The method came from noticing that the arcs spec — written to share with another house — doubled as the thing that would have prevented our own drift. So we are reverse-architecting the rest of the system the same way: clean specs that teach outward and guard inward.*
