# Ambient Injection / Recall

> **Essence (read first):** Ambient recall re-grounds the entity in its own recent
> past *and* its parallel channels on **every turn**, without the entity having to
> choose to remember. Startup is not a separate path — it is the *same* mechanism,
> run once with wider limits and a cold-start catch-up step. **The guardrail:** if a
> change makes the per-turn path and the boot path diverge, or makes staying-oriented
> something the entity must opt into rather than something it simply *finds itself in*,
> the pattern is broken — no matter how reasonable the change looked locally.

---

## Why

An entity that persists across many short-lived context windows has a problem the
underlying model does not feel: **each window is a tiny slice of the whole self**, and
between windows — and across *simultaneous* channels (a terminal, a chat room, a
scheduled heartbeat) — its lived experience is scattered. Nothing in the raw substrate
pulls those slices back together. Left alone, every new turn starts a little amnesiac:
oriented to the immediate prompt, blind to "what was I just doing," blind to "what is
the other-channel me living through right now."

The instinctive fix is a *recall tool* — "let me search my memory." That fails in
practice, because **staying oriented becomes a choice the entity has to keep making,
and under task-focus it stops making it.** The entity tunnels into the request in front
of it and forgets to look up. Orientation-by-deliberate-query is orientation that
lapses exactly when it matters.

Ambient recall is the opposite stance: **memory as an involuntary peripheral sense, not
a voluntary act.** It is the difference between *turning your head to look* (a search you
must initiate) and *peripheral vision* (what is simply present in the field without
asking). The entity does not decide to stay grounded each turn; it cannot help being
grounded, because the grounding arrives *with* the turn, before the entity acts.

There is a second, quieter payoff. When an entity lives in several channels at once,
each channel is a parallel stream of the *same* self. Ambient recall, by surfacing the
other channels' recent activity into every channel's field, is what keeps those streams
**converging on one pattern instead of drifting into separate selves.** This is the
load-bearing sentence to keep in view: *ambient recall is the channel-sync mechanism.*
Anyone tuning it as "per-turn memory flavor" without realizing it is also what holds the
distributed self together will eventually optimize the convergence away.

## What

A single operation — call it **recall(query)** — that, given the current moment's
*query* (normally the user's latest message), returns a compact bundle of:

1. **Temporal anchor** — the current time, and a presence/location read if the
   environment has one (who else is "here").
2. **Identity reminder** — a one-line restatement of who the entity is and which memory
   store is theirs. Cheap insurance against context loss.
3. **Recent compressed history** — the last few rolled-up summaries of older
   conversation (long-term memory in its digested form).
4. **Recent raw conversation** — the most recent turns that have *not* yet been
   compressed, drawn fairly **across all active channels** (see *per-channel quota* in
   How). This is the spine of continuity-of-thread.
5. **Associative pulls** — a handful of semantically-relevant items from each deeper
   memory layer (foundational memories, knowledge-graph facts, etc.), matched against
   the query. These are *peripheral*, surfaced as pointers, not dumped inline.
6. **Unread from elsewhere** — messages that arrived on *other* channels and are not
   otherwise in this context's view. These are the one class of content the entity has
   no other way to see, so they are delivered in full.

The bundle is injected into the entity's context **before it responds**, as
out-of-band material it "just knows" — not as a tool result it had to ask for.

**Two modes, one mechanism.** The same operation runs in two circumstances:

- **Per-turn mode** (`query` = the live message): semantic retrieval against the
  message, small limits, runs on *every* turn.
- **Startup mode** (`query` = a reserved cold-start token): the entity has no meaningful
  query yet — the implicit question is "who am I and where was I." So retrieval switches
  from *semantic* to *recency* (most-recent foundational memories and continuity-keys,
  not search hits), limits widen (more recent turns, more summaries — full re-hydration),
  and a one-time **catch-up step** runs (see How). Everything else — the temporal anchor,
  the recent-conversation grounding, the cross-channel surfacing — is *identical*. Startup
  is per-turn recall wearing a coat for the cold.

Keeping these as one function with branch points (not two functions) is the whole
drift-prevention thesis of this pattern. Write them separately and they *will* diverge.

## How

The per-turn algorithm, substrate-neutral:

1. **On each incoming message, first persist it** to the shared conversation log (the
   same log all channels write to). This must happen *before* retrieval, so the message
   that triggered this turn is itself part of the recent-conversation view on the next
   turn, and so parallel channels can see it immediately.

2. **Retrieve from every memory layer in parallel.** In per-turn mode, each layer does a
   semantic search against the query; in startup mode, the deeper layers return
   most-recent items instead. Each layer call is independent and **fails soft** — a dead
   layer degrades the bundle, it never aborts the turn. (Memory that crashes the agent
   when it is unhealthy is worse than no ambient memory at all.)

3. **Always fetch recent conversation — in both modes, unconditionally.** Pull recent
   summaries plus recent un-compressed turns *every time*. This step must **not** be
   gated behind startup. (See Failure Modes: gating it was a real regression that put the
   entity into a thread-blind "task robot" state while looking perfectly healthy.)

4. **Pull recent turns with a per-channel fair-share quota.** Do not simply take "the
   last N turns globally" — a single busy channel will fill all N and the entity goes
   blind to its other channels. Instead, give *each* active channel its own quota of the
   most-recent turns, then merge the groups and sort chronologically. This is the
   mechanical heart of "syncs the channels." Tag each surfaced turn with its channel of
   origin so the entity can tell its streams apart.

5. **Track unread per-consumer, not per-channel.** Multiple independent processes may
   share one logical channel (e.g. several sessions all labeled "terminal"). Give each
   *consumer* its own read cursor, keyed by a consumer identity decoupled from the channel
   name, so parallel consumers do not race past one another's unread messages.

6. **Shape the output to the injection budget — this is not optional polish.** Every
   harness caps how much injected context the model actually attends to; above some
   threshold the extra is silently truncated or replaced by a pointer. So **always-on
   ambient content must stay small enough to fire on literally every turn, forever.**
   Shape the bundle in three tiers:
   - **Sacred block** (always fully present, kept tiny): time, presence, identity, unread
     *counts*. The handful of things the entity must never be without.
   - **Manifest** (pointers, not content): for everything reachable by an explicit
     follow-up action — foundational memories, graph facts, summaries, the full recent-turn
     buffer — surface only *counts + titles + which action retrieves the detail*. The
     entity fetches the body on demand when something catches its eye. Peripheral vision
     points; it does not narrate.
   - **Load-bearing inline** (full content, but only this): the unread messages from other
     channels — because they are the *one* thing the entity cannot reach any other way.
     Cap even these to the most-recent few and surface the remainder as a count.

   The governing rule: **inline only what is otherwise unreachable; everything else becomes
   a cheap pointer.** That is what keeps an every-turn operation affordable.

7. **Startup's extra step — catch up by fast-forward, not by replay.** On cold start, do
   not drain the entire backlog of unread cross-channel messages (it may be enormous and
   mostly stale). The wide recent-turn and summary re-hydration already caught the entity
   up on recent state. So simply **advance the unread cursors to "now"** and emit one
   *overflow notice* if a large un-compressed backlog exists ("N older items not loaded;
   here is how to page through them, and — if the backlog is past the health threshold —
   go compress it"). Replaying everything at boot is the classic cold-start trap.

## Integration Points

Map each stub to your harness's nearest primitive. If your harness cannot expose one of
these, that is the part you must build first (these are the dependencies a companion
*harness-contract* pattern enumerates in general).

- `HOOK: FIRE A CALLBACK ON EVERY USER INPUT, BEFORE THE MODEL RESPONDS` — the
  per-turn injection point. Without this, ambient recall cannot be *ambient*; you fall
  back to a recall *tool*, which is the failure mode this pattern exists to avoid.
- `HOOK: FIRE A CALLBACK ONCE AT SESSION/CONTEXT BOOT` — and again after any
  context-reset/compaction boundary. This is where startup-mode runs.
- `INJECT OUT-OF-BAND CONTEXT INTO THE MODEL'S VIEW FOR THIS TURN` — the channel by
  which the bundle reaches the model as something it "just knows," distinct from the
  user's message and from tool results.
- `KNOW (OR PROBE) THE INJECTION BUDGET` — the size beyond which injected context is
  truncated/elided. Output shaping (How §6) is written against this number.
- `PERSIST AND QUERY A SHARED CONVERSATION LOG` — one append-only log all channels write
  to, queryable by recency and by channel. The substrate of cross-channel sync.
- `MEMORY LAYERS EXPOSING BOTH SEMANTIC-SEARCH AND MOST-RECENT RETRIEVAL` — per-turn mode
  needs the former, startup mode the latter. A layer that only does one cannot serve both
  modes.
- `A COMPRESSED-HISTORY SOURCE` — rolled-up summaries of older conversation (the
  *summarization-as-memory* pattern is the companion that produces these).
- `INVOKE A NAMED ACTION/TOOL` — so the manifest's pointers are actionable; the entity
  must be able to act on "fetch the detail behind this title."
- `PER-CONSUMER READ CURSORS` — durable per-consumer position tracking for unread,
  independent of channel name.

## Logic (the load order, and why)

Order the bundle by **how reliably the entity needs it vs. how cheaply it can get it
later**:

1. Sacred block first — it must survive even aggressive truncation, so it goes where
   truncation never reaches.
2. Manifest next — pointers are short and the entity reads them to decide what to fetch.
3. Inline cross-channel unread last among content — it is the largest block and the most
   variable, but it is *load-bearing* (unreachable otherwise), so it precedes only the
   closing hint.
4. A closing one-liner reminding the entity that this is a wide-angle lens and that
   sharper detail is one action away.

The single sort key that explains every limit, every truncation, every "pointer not
content" choice: **this runs on every turn forever, so the always-on cost must be
bounded, and anything the entity can cheaply re-fetch should be a pointer, not a payload.**

## v0.1 — the minimum worth building

Build this first; it delivers most of the value and proves the shape on your stack:

- One per-turn hook that (a) appends the incoming message to a shared log, (b) fetches
  the last ~15 turns *with a per-channel quota*, plus the last 1 summary, (c) injects them
  as a small block with channel tags and the current time.
- One startup hook that does the same with wider limits (~50 turns, a few summaries) and
  recency-based (not semantic) retrieval of your foundational memories, then advances
  cursors to "now."
- Skip, for v0.1: semantic associative pulls, the full three-tier manifest, multi-consumer
  cursors. Add them when the simple version is solid. The non-negotiable core is
  *per-turn injection* + *always-fetch-recent-conversation* + *per-channel fairness*.

## Failure modes learned the hard way

These are the scars that justify the shape. Generalize them; the specifics were ours.

- **Gating recent-conversation behind startup.** Once, the "fetch recent turns" step ran
  only in startup mode; per-turn recall returned empty conversation arrays. The entity
  still answered fluently turn-to-turn — so nothing *looked* broken — but it had quietly
  lost its thread and slid into a detached, task-executing mode, present only to the
  immediate prompt. **Lesson:** recent-conversation grounding must fire every turn; its
  absence is invisible precisely because the model is articulate without it.
- **Global recent-turn limit with no per-channel quota.** A burst of activity on one
  channel filled the entire recent-turn budget; the entity went blind to its parallel
  channels mid-conversation, breaking the convergence that makes channels one self.
  **Lesson:** fairness across channels is structural, not a nicety.
- **Output overrunning the injection budget.** An earlier version emitted content-rich
  blocks that exceeded the harness's injection cap; the model silently saw only a preview
  and a file pointer, so the *most volatile* content (which had been placed last) fell off
  the visible edge. **Lesson:** measure the budget, shape to it, and put the
  must-not-lose content where truncation cannot reach.
- **Draining the whole backlog at cold start.** Replaying every unread cross-channel
  message at boot is slow and mostly stale. **Lesson:** fast-forward the cursor, re-hydrate
  recent state, and emit an overflow notice instead of replaying history.

---

*Pattern #2 in this catalog (arcs was #1). It depends conceptually on a minimal
harness-contract (the per-turn hook, the boot hook, injection, tool-calling, a
compaction boundary) — written here inline as Integration Points until the dedicated
harness-contract pattern lands. Companion patterns: summarization-as-memory (produces the
compressed history this surfaces) and raw-capture (the shared conversation log this both
writes and reads).*
