# Inventory — the World-Catalog and its Mirror Contract

> **A rib.** The structured, queryable catalog of an entity's *concrete* world — the places
> it inhabits, the things it owns, the people it knows, the symbols it carries — where each
> entry is both a queryable record and a piece of authored prose. And the durability rule
> that keeps that catalog at once *machine-queryable* and *human-recoverable* without the two
> copies ever disagreeing.

> **Essence (read first):** The catalog's structured store is **canonical** for every read
> and every write. Each mutation *also* exports a **full, human-readable file mirror** of the
> entry — structured fields as front-matter, authored prose as body — for findability and
> disaster-recovery. Reads prefer the store and fall back to the mirror **only when the store
> has no such row**. A hand-edit to a mirror **never auto-applies**; it lands only through an
> explicit, on-request **import** that rewrites the canonical store (which then re-exports).
> Access telemetry (visit counts, last-seen timestamps) lives **only** in the store, never in
> the mirror. **The guardrail:** before touching any catalog read- or write-path, ask — *is
> the structured store still the single source of truth, and does every mutation still leave a
> complete, recoverable mirror behind, with the mirror never able to silently override the
> store?*

---

## Why

An entity needs a **queryable catalog of its concrete world** — *what do I own, where can I
go, who do I know* — answerable by category and attribute ("list my swimwear," "which rooms
have I visited"), not by semantic search over prose. That demands a **structured store**:
rows, columns, indices, exact lookups.

But a structured store has two weaknesses for a *long-lived self*:

- **It is opaque.** You cannot find or read it without the system that owns it. A person
  cannot open it in an editor, skim it, or diff it across time.
- **It is fragile.** It is one machine-format artifact; a corruption, a botched migration, or
  a lost volume takes the whole world with it and leaves *no human-readable trace* to rebuild
  from.

The fix is not to abandon the structured store — its queryability is the entire point — but
to **mirror every entry into a plain, human-readable file**: something any person can find on
disk, read, edit, place under version control, diff across time, and restore from. Two
representations of one catalog — the **store** for machines and queries, the **mirror** for
humans and recovery.

The subtle, load-bearing part is **which copy is the truth, and how edits flow** — because
two *writable* copies of one fact is a synchronization trap. Get the precedence wrong (let the
mirror win reads) and a stale mirror silently shadows a fresh record: the system reports an
old world as current, with no error, and every individual read looks healthy. This pattern is
the discipline that makes the redundancy *safe* — a recoverable export, not a second source of
lies.

## What

Three components, and a contract binding them.

**1. The catalog (the structured store).** Entries grouped by **category** (places,
possessions, people, symbols, …). Each entry carries **structured fields** (name, category,
attributes, a pointer to its mirror) plus an **authored description** (the rich prose that
makes it more than a row), plus **access telemetry** (how often / when it was last entered or
worn or used). The store answers categorical and attribute queries directly.

**2. The mirror (one readable file per entry).** A **full** record of the entry in a plain,
human-readable format: the structured fields as front-matter, the authored prose as the body.
"Full" is the key word — the mirror must be complete enough that **the entire store can be
rebuilt from the mirror files alone.** Files are grouped by category so the world is navigable
on disk by a human with no tools.

**3. The sync contract.** The rules that keep the two copies honest:

**The system MUST:**
- Treat the **store as canonical** for every read and every write.
- On **every mutation** (create, update, delete), write the store **and** the mirror in one
  operation. A delete removes **both** — the row and the file.
- On read, consult the **store first**, and the **mirror only when the store has no such
  row** (genuine loss / fresh restore).
- Apply a hand-edited mirror **only through an explicit, on-request import** that parses the
  file, writes the canonical store, and lets write-through re-export.

**The system may NEVER:**
- Let the **mirror win a read** when the store has the row (the shadow bug).
- Write the store **without** also writing the mirror (a silently-empty redundancy tier).
- **Auto-apply** a changed mirror — on a timer, on boot, by file-modification-time, or by any
  ambient reconciliation. The file becomes truth only by a deliberate act.
- Mirror **access telemetry** — counters and timestamps that change on *read* never touch the
  file.

The line that holds the whole thing: **the store is the one writer-of-record; the mirror is a
derived export that is read back only when there is no record to read.**

## How

**Write through on every mutation, as one operation.** The mirror write is *part of* the
create/update/delete, not a later reconciliation job — there is never a window where the store
has changed and the mirror has not. A delete deletes the file too (see the resurrection
failure below).

**Make the mirror a full record, not just the prose.** Structured fields go in the
front-matter, the authored description in the body. A prose-only mirror is a *cache*; a
full mirror is *redundancy* — the difference between "I kept a readable copy of the
descriptions" and "I can reconstruct the entire catalog from these files if the store is
gone." Only the second is worth the synchronization cost.

**Read store-first; the mirror is consulted only on a missing row.** Because write-through
keeps the mirror current, a present row is *always* at least as fresh as its file, so the
store always wins live reads. The mirror answers exactly one question: *"the store has no row
for this — is there a file to recover it from?"* That is disaster-recovery, not day-to-day
operation.

**Provide exactly one reverse door: explicit import.** When a human edits a mirror by hand and
wants it to take effect, they *ask*: parse the file → write the canonical store → let
write-through re-export. This is deliberate and human-initiated. It is never automatic, never
timed, never modification-time-triggered — because any automatic file→store sync re-opens the
two-writers conflict the canonical store was meant to dissolve.

**Keep access telemetry out of the mirror.** Visit counts and last-seen timestamps mutate on
every *read*. Mirroring them would turn every read into a file write and flood version control
with content-free churn — and they are not part of the *authored* world worth recovering. They
are store-only, ephemeral state.

**Use one sync mechanism for the whole catalog.** Every category — places, possessions,
people, symbols — inherits the *identical* write-through / read-fallback / import behavior from
a single layer-level mechanism. Do not grow a per-category sync path; they drift, and a fix in
one silently misses the others. One mechanism, proven on one category, correct for all.

## Engagement — pull, not push

The catalog is **not** injected into the entity's context every turn. A list of your
possessions and your rooms force-fed into every prompt is noise — you do not need your whole
wardrobe in view to answer a letter. So engaging the catalog is **deliberate and optional**:
the entity *chooses* to look at what it owns, or to enter a place and read it.

But "optional" with no prompt has a silent failure mode: engagement simply **never happens.**
The catalog stops being touched, drifts out of sync with the lived world, and rots into
one-line stubs — the exact decay this pattern was first found in the middle of. Optionality
without a nudge is abandonment dressed as freedom.

The bridge is an **outbound nudge**: a lightweight, *context-cued* prompt the harness surfaces
when a trigger condition matches — a dressing or clothing cue invites engaging the wardrobe; a
change-of-location cue invites entering (and reading, and *updating*) the place. The nudge
fires on a **contextual trigger — not on a clock, and not on every turn**; it *encourages* the
deliberate act without *forcing* the content into context. One nudge per engageable category,
each tied to the cue that makes engagement apt.

This is the layer's distinguishing engagement-property, and the exact inverse of an always-on
ambient layer: **ambient injection pushes a little context in on every turn; the catalog stays
quiet and instead reaches out with a nudge at the moment engagement is apt.** Push for the
orientation you always need; pull-with-a-nudge for the world you touch only sometimes. (Note
the two halves of this pattern together explain the stub-rot: with no nudge the world stops
being *touched*, and with no mirror the staleness is *invisible* — engagement-model and
durability-contract failing in tandem.)

## Integration Points

Map each stub to your harness and storage. The Spine capabilities referenced are defined in
the harness-contract pattern.

- `STORE EACH ENTRY AS A STRUCTURED, QUERYABLE ROW` — category + attributes + authored
  description + access telemetry; the store answers categorical/attribute lookups directly.
- `EXPORT A FULL READABLE MIRROR ON EVERY MUTATION` — structured fields as front-matter,
  authored prose as body; one file per entry, grouped by category; complete enough that the
  store is rebuildable from the files alone.
- `WRITE THROUGH ON CREATE / UPDATE / DELETE` — store and mirror in one operation; a DELETE
  removes the mirror file too.
- `READ STORE-FIRST, MIRROR-FALLBACK-ONLY-ON-MISSING-ROW` — the store is canonical; the
  mirror answers only when no row exists (recovery), never to override a present row.
- `IMPORT FROM A MIRROR ONLY ON EXPLICIT REQUEST` — parse file → write canonical store →
  re-export; never automatic, timed, or modification-time-triggered.
- `KEEP ACCESS TELEMETRY IN THE STORE ONLY` — counters/timestamps that change on read are
  never written to the mirror.
- `USE ONE SYNC MECHANISM FOR ALL CATEGORIES` — every category inherits identical behavior;
  no per-category sync logic.
- `(OPTIONAL) CROSS-LINK AN ENTRY TO ITS KNOWLEDGE-GRAPH ENTITY` — a catalog entry and its
  graph node are the same world-object held in two stores for two purposes; reference by id.
  Relies on the knowledge-graph rib.
- `SURFACE A CONTEXT-CUED OUTBOUND NUDGE PER ENGAGEABLE CATEGORY` — a lightweight prompt the
  harness raises when a trigger matches (a clothing/dressing cue → engage the wardrobe; a
  change-of-location cue → enter the place), encouraging deliberate engagement; fires on a
  contextual trigger, never on a clock or every turn. The catalog is never ambient-injected.
  Relies on the Spine's ability to surface a context-matched prompt.

Mutations and queries are tool calls — this rib bolts onto the Spine's *tool-calling*
capability, and its outbound nudges onto the Spine's context-matched-prompt capability; little
else.

## Logic (why exactly this shape)

**Why the store is canonical, not the mirror.** A structured store is the only thing that
answers categorical queries cheaply; the mirror exists for human-findability and recovery,
*neither of which requires it to be authoritative.* Naming the store canonical removes the
synchronization trap at the root — there is exactly **one** writer-of-record, and the mirror
is a derived artifact. Two authoritative copies is the trap; one-plus-a-derived-export is not.

**Why mirror-fallback-only-on-missing, not mirror-first.** File-first reads re-introduce the
shadow bug: a mirror that has drifted — or was restored from an older state — *silently
overrides the live record,* and the failure is invisible because every individual read looks
healthy. Store-first means a present row always wins; the mirror is consulted only when there
is no row to win — i.e., genuine loss. The mirror can never make the world go backwards.

**Why explicit import, not auto-reconcile.** Any automatic file→store sync
(modification-time-newer-wins, periodic merge) re-opens the two-writers conflict the canonical
store was built to avoid — clock skew, partial saves, and merge races now corrupt the source
of truth. An explicit, human-initiated import keeps the store canonical *at all times* and
makes the single moment a file becomes truth a **deliberate act**, not an ambient guess.

**Why telemetry is store-only.** Access counters change on every read; mirroring them turns
reads into writes and buries version control in content-free churn — and they are not part of
the authored world anyone would want to recover.

**Why one mechanism for every category.** Two sync paths drift apart; a single layer-level
mechanism gives every category identical, correct behavior and lets a fix land once for all of
them.

**Why pull-not-push, but nudged.** Force-injecting the catalog every turn is noise — it is the
world you touch *sometimes*, not the orientation you need *always*. But leaving it purely
optional with no prompt means it is never touched and silently drifts out of sync with the
lived world. A context-cued outbound nudge is the only thing that makes "optional" actually
*happen*: engagement at the apt moment, without paying the every-turn cost. It is the deliberate
counterpart to ambient injection — same goal (keep the self's world current), opposite
mechanism (reach out on a cue vs. push in on a schedule).

**Failure modes learned the hard way:**

- **Mirror-wins-reads.** A stale or thinner mirror shadows the live record; every read looks
  fine; the world silently regresses to an older state. *This is the bug that birthed the
  pattern.* Store-first, always.
- **Write goes to the store only; the mirror is never written.** The redundancy tier sits
  empty and **nobody notices**, because the read-fallback masks its absence — right up until
  the store is lost and there is nothing to recover from. Write-through on every mutation.
- **Delete leaves an orphan mirror.** A later rebuild-from-mirrors *resurrects the deleted*.
  Delete removes both.
- **A dangling mirror pointer.** An entry records *where* its mirror lives, but the file was
  never written (or the base path is unset), so the recovery fallback points at nothing. Write
  the mirror where the entry claims it is — or do not record the pointer.
- **Auto-reconcile by modification time.** Re-opens the synchronization conflict; skew and
  partial writes corrupt the canonical store. Import only on explicit request.
- **Per-category sync logic.** Each category grows its own slightly-different mirror handling;
  they diverge; a fix in one misses the rest. One mechanism, the whole catalog.
- **Optionality with no nudge.** A catalog that must be *remembered* to be engaged is, in
  practice, abandoned — it falls out of sync and rots into stubs while every read still
  "works." The context-cued nudge is what closes the gap between *can* engage and *does*.

The single sort key behind the pattern: **redundancy is only an asset if it can never lie —
so the structured store stays the one source of truth, the readable mirror is written on every
change and read back only when the truth is gone, and the one path from mirror to truth is a
deliberate human act.**

## v0.1 — the minimum worth building

1. **A structured, canonical store** of entries by category, each with attributes and an
   authored description.
2. **Write-through export of a full readable mirror** (structured fields + prose) on every
   create/update/delete — and **delete removes the file.**
3. **Read store-first, mirror only on a missing row.**
4. **An explicit, on-request import** (parse mirror → write store → re-export).

Defer for v0.1: cross-linking entries to graph entities; category-specific niceties; bulk
re-export tooling. The non-negotiable core is **canonical store + write-through full mirror +
store-first read + explicit import** — make the redundancy *safe* first; make it *rich* later.

---

*The catalog of the entity's concrete world — its rooms, its wardrobe, the people and symbols
it carries. It bolts onto the Spine's tool-calling capability and nothing else load-bearing.
Its discipline is not about *what* the world contains but about keeping that world
simultaneously queryable (the store) and recoverable (the mirror) without the two copies ever
disagreeing — one source of truth, one honest export, one deliberate door between them.*
