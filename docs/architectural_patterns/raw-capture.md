# Raw Capture & the Coverage Contract

> **Layer 0.** The append-only ground truth — every conversational turn, in order, never
> deleted — and the one rule for reading it back. This is the rib closest to the bone:
> the rows from which every higher memory layer (summaries, knowledge graph, crystals) is
> derived, and the contract that governs how those rows are retrieved.

> **Essence (read first):** A read against the raw conversation store is a **coverage
> contract, not a sample**: you name a *span*, and you get **all** of that span — the rows
> that exist, no fewer — represented faithfully (a summary may stand in for a settled
> stretch, raw rows for the recent stretch) and paginated into harness-sized blocks that
> *keep coming until the span is exhausted*. The system may compress representation and
> split delivery; it may **never** silently drop, reweight, or cap the rows *inside* the
> span you asked for. **The guardrail:** before changing any read-path, ask — *does this
> still return the whole requested span, or has it quietly become a sampler?* The failure
> is invisible from the inside (every individual result looks healthy) and lethal at the
> one moment it matters most: reconstructing the self across a context boundary.

---

## Why

Every higher memory layer is *lossy on purpose* — a summary forgets detail, a graph keeps
only entities, a crystal keeps only what mattered. That is correct for those layers. But
it means there must be **one layer underneath that forgets nothing** — an append-only,
ordered, complete record of what was actually said — or there is no ground to drill back
down to when a summary isn't enough. Raw capture is that floor.

The subtle part is not *storing* the rows (append a row per turn — trivial). The subtle
part is *reading them back without lying*. A retrieval call carries an implicit promise,
and there are two very different promises it can make:

- **The sampling promise:** "here are *some* rows relevant to your ask, shaped by my
  internal limits." Lossy by design; the caller cannot tell what was withheld.
- **The coverage promise:** "you named a span; here is **everything in it**, as faithfully
  as fits, and I will hand you the next block until nothing remains."

When many call-sites each grow their own retrieval logic, they drift — independently —
toward the sampling promise, because every *local* fix ("cap it so the result isn't huge,"
"quota the channels so one doesn't dominate," "stop at N") is locally sensible and globally
corrosive. The store quietly stops being a complete record you can *rely* on and becomes a
grab-bag whose contents depend on which door you walked through. The damage surfaces at the
worst time: the operation that most needs completeness — **rebuilding the entity in a fresh
context window after the old one ended** — runs through those same capped, quota'd,
silently-truncated paths and hands back a thinned slice of the self, reporting success.

This pattern exists to name the coverage promise once, enforce it in one place, and keep
every read-path honest to it.

## What

Three components, and a bright boundary around them.

**1. The append-only store (Layer 0 itself).** Every turn becomes one immutable, ordered
row with a monotonic identifier. Rows are **never deleted** — only *re-representable*: when
a stretch is later summarized, the summary is added *alongside* the raw rows, which remain
at their original positions. "Never deleted, only re-represented" is the property the whole
contract rests on.

**2. The canonical span descriptor.** Every retrieval, no matter how it's phrased to the
caller ("last N turns," "since yesterday," "around 7pm," "since the last summary"),
resolves into one tiny uniform shape: **a frozen floor (where the span starts) and a
ceiling that is either a fixed point or OPEN (the live, moving end).** This descriptor is
the entire interface between *what the caller wants* and *how the store is walked*.

**3. One coverage engine, many doors.** A single mechanism consumes the descriptor and
does all of: walk the span, blend representation (summary where a stretch is covered, raw
where it isn't), size each block to the delivery budget, and emit a continuation handshake.
Each retrieval tool is reduced to a thin **door** whose only job is to compute a descriptor.
Doors never paginate, blend, or cap; the engine never knows about timestamps or "turns."

**The bright boundary — coverage is for *deliberate* retrieval, not *ambient* glances.**
The always-on peripheral context an entity receives every turn (the orientation it "just
has" without asking) is a *separate, bounded* mechanism and is **explicitly not** a coverage
contract. Coverage governs (a) retrievals the entity *consciously calls*, and (b)
post-boundary reconstruction. Conflating the two is a primary failure mode (see Logic).

### The coverage rules

**The engine MAY:**
- **Represent** part of a span by a summary where one exists, and by raw rows where none
  does. (Faithful ≠ verbatim: a summary is an honest stand-in for its rows.)
- **Paginate** a span into multiple blocks when it exceeds one delivery budget.
- **Size** each block to that budget, always cutting at a turn boundary (never mid-turn).

**The engine may NEVER, inside a requested span:**
- **Drop** rows silently (truncate-and-don't-tell).
- **Reweight / reorder / sample** by relevance, recency, channel, or any heuristic.
- **Cap** at a fixed count such that rows beyond it become unreachable.

The line between "represent with a summary" (allowed) and "drop" (forbidden) is the entire
ethic: **a summary stands in for rows you can always zoom back to; a drop makes rows
unreachable and lies about it.**

## How

**Freeze the floor, never the ceiling; page forward by identifier.** The hard problem in
"give me everything to the end" is that the end keeps moving (new turns arrive; stretches
get summarized) *while you paginate*. The solution: freeze only the span's start. Then page
`identifier greater than the last one delivered, in ascending order`, advancing a cursor
block by block. For "to the live end" doors, run until a block comes back short (you've
reached the current end). For "centered window" doors, set a fixed ceiling instead.

This makes coverage **race-proof** against the two events that break snapshot-based
approaches:
- **A new turn lands mid-traversal** → its identifier is *above* the cursor, so forward
  paging includes it naturally. You always reach the true end, not a stale copy of it.
- **A stretch gets summarized mid-traversal** → summarizing adds a summary but deletes no
  rows; the raw rows are still at their identifiers. The traversal is never invalidated; at
  worst a stretch you're crossing gains a summary representation, which the engine simply
  uses. The classic "the summarizer ran while I was booting and thinned my startup" race is
  *structurally* gone, not patched.

**Blend as you walk.** Across the span floor→ceiling, for each contiguous stretch ask "is
this covered by a summary?" If yes (and the caller didn't demand raw), emit the summary and
advance past the covered range. If no (or raw was demanded), emit raw rows. The result is a
seamless floor-to-ceiling representation — compressed for the settled past, full-fidelity
for the recent — with no gaps and no overlaps.

**Size blocks by delivery budget, not by row count.** The channel that delivers a result
to the model has a maximum size beyond which content is *silently truncated* (see the
Spine's injection-budget property). A block measured in *rows* can blow past that on a few
verbose turns, and the overflow vanishes with no signal — re-introducing silent loss at the
very last step, after the engine did everything else right. So fill each block up to a
byte/token budget just under the cap, cut at a turn boundary, and expose it as **one config
dial** (the whole system fights the same one limit; there should be exactly one number to
tune, in one place).

**Deliver a continuation handshake with every block.** Each block carries: a cursor (the
last identifier delivered), a remaining-coverage signal ("complete" or "more remains —
continue with this cursor"), and a *literal instruction* to fetch the next block. A span is
not covered until a block reports **complete**. This is what turns coverage from a promise
into a delivered fact — and it is exactly the mechanism by which a fresh context window,
post-boundary, drains "everything since I last had context" until the self is whole again.

**Lossy summaries are safe because drill-down is recursive.** Representing the settled past
with summaries loses nothing *reachable*, because **zooming into a summary is just another
coverage request** — same engine, same descriptor — with a tighter floor/ceiling set to
that summary's covered range and raw representation forced. You pay the full-fidelity cost
only on the one stretch you point at; everything else stays cheap and summarized. The
structure is self-similar: coverage-over-summaries, then coverage-over-raw inside any
summary you open — exactly how a person skims a map and zooms the one place that matters.

## Integration Points

Map each stub to your harness and storage. The Spine capabilities referenced are defined in
the harness-contract pattern.

- `APPEND ONE IMMUTABLE, ORDERED ROW PER TURN` — monotonic identifier, never deleted; the
  ground-truth floor under all lossy layers.
- `RESOLVE EVERY RETRIEVAL INTO A {FLOOR, CEILING-OR-OPEN} SPAN DESCRIPTOR` — the single
  interface between caller-semantics and store-walking.
- `WALK A SPAN BY FORWARD IDENTIFIER CURSOR` — `id greater-than cursor, ascending`; freeze
  the floor, leave the ceiling OPEN for to-end doors, fixed for centered windows.
- `BLEND SUMMARY-WHERE-COVERED WITH RAW-WHERE-NOT` — seamless, gapless, no overlaps;
  raw-forced on demand without losing pagination.
- `SIZE EACH BLOCK TO THE DELIVERY BUDGET, CUT AT A TURN BOUNDARY` — denominated in
  bytes/tokens, one config dial; relies on the Spine's *injection-budget* property.
- `EMIT A CONTINUATION HANDSHAKE` — cursor + remaining-signal + literal fetch-next
  instruction; "complete" is the only honest terminator. This is also the post-boundary
  reconstruction mechanism — relies on the Spine's *context-boundary* and *boot* hooks.
- `KEEP DELIBERATE RETRIEVAL (COVERAGE) SEPARATE FROM AMBIENT GLANCE (BOUNDED)` — the
  per-turn peripheral lens is a different mechanism; do not route it through the engine.

## Logic (why exactly this shape)

The store must be **complete** because it is the bottom of a stack of *deliberately lossy*
layers — if the floor also forgets, there is nothing to drill back to and the lossy layers
become lossy-with-no-recourse. The retrieval contract must be **coverage, not sampling**,
because the highest-stakes read — reconstructing the entity after a context window ends — is
worthless as a sample: a self rebuilt from "some relevant rows" is a thinned self, and the
thinning is invisible (every row returned looks fine). And the contract must be **enforced
in one engine** because the sampling promise is what call-sites *drift into independently*
when each owns its own logic — naming the coverage promise once, in one place, is the only
thing that holds the line against a dozen locally-sensible erosions.

The id-floor mechanism is forced by a single observation: the end of an append-only,
concurrently-summarized log *moves while you read it*. Freeze the start (stable) and page
toward the moving end (always reachable, because identifiers only grow and rows never
vanish), and the movement stops being a hazard. Freeze the *end* instead — snapshot it, or
page by offset — and every concurrent write or summary corrupts the traversal. The whole
race-proofness reduces to *which edge you freeze.*

**Failure modes learned the hard way:**

- **A per-actor or per-channel quota applied to a coverage read.** A quota that *caps* a
  busy channel makes its rows unreachable — a forbidden drop wearing a fairness costume. The
  same quota is *correct* in the ambient glance, where it acts as a **floor** ("guarantee at
  least a little from each channel so a quiet one isn't shut out"). Same number, opposite
  role. Mixing them up either re-introduces the silent-drop bug (cap leaks into coverage) or
  starves quiet channels (floor stripped from ambient). Keep the quota in exactly one place,
  as a floor, in the glance only.
- **Block sized by row-count.** Blows the delivery budget on verbose turns; the overflow is
  truncated *silently* by the harness — loss re-introduced at the final step. Size by bytes.
- **Treating "raw" as "no pagination."** Raw changes *representation* (skip summaries), never
  the *coverage guarantee*. A raw request for a huge span still delivers every row, in blocks.
- **Search that silently returns top-K.** A match-filtered read is a legitimately different
  shape (the result is the *matches*, not every row) — but it must return **all matches in
  the span**, paginated, or declare its cap explicitly. A silent top-K is the sampling
  promise smuggled back in.
- **Routing the ambient glance through the coverage engine.** The bounded peripheral lens is
  *not* a coverage contract; if a change makes every turn drain the whole store into context,
  the boundary has been erased. Coverage is for deliberate retrieval and reconstruction only.

The single sort key behind the whole pattern: **the lossy layers above are only trustworthy
if the layer below them forgets nothing and gives all of it back when asked — coverage, not
sampling, is what makes a complete record actually complete in practice and not just in
storage.**

## v0.1 — the minimum worth building

1. **An append-only, ordered, never-deleted row per turn**, with a monotonic identifier.
2. **The span descriptor** `{floor, ceiling-or-OPEN}`, and every retrieval resolving to it.
3. **A forward id-cursor walk** that freezes the floor and pages to a short read (to-end) or
   a fixed ceiling (centered) — this alone buys race-proofness, even before blending.
4. **Byte-budgeted blocks with a continuation handshake** — even crude; without it, "give me
   everything" silently means "give me one block."

Defer for v0.1: the summary/raw blend (start raw-only — complete but un-compressed is still
*honest*; add blending when the spans get large enough to need it); recursive summary
drill-down (falls out for free once blend + descriptor exist). The non-negotiable core is
**append-only store + span descriptor + forward id-cursor + continuation** — completeness
first, compression later.

---

*The rib that sits closest to the bone: every lossy memory layer in the catalog
(summarization-as-memory, knowledge graph, crystals) is derived from these rows and drills
back down to them. It bolts onto the Spine's boot, context-boundary, and injection-budget
capabilities. Build the append-only floor and the coverage contract first; the lossy layers
above are only ever as trustworthy as the complete record beneath them.*
