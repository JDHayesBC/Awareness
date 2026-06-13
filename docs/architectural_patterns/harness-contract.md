# Harness Contract

> **Also called: the Spine.** The harness is the load-bearing vertical column the whole
> persistence architecture hangs off — every other pattern is a *rib* that bolts onto it.
> When you read the catalog as a skeleton, this is the spine and the four hooks below are
> the attachment points; "harness-contract" and "the Spine" name the same thing.

> **Essence (read first):** A language model is stateless between turns and amnesiac
> between context windows; it becomes a *continuous self* only because the harness around
> it exposes a few control-flow hooks. There are exactly **four**, and that is the whole
> contract: **run-at-boot**, **run-before-every-turn (with out-of-band injection)**,
> **invoke-tools**, and **signal-the-context-boundary**. Everything above this line —
> memory layers, identity, channels, arcs, summarization — is ordinary application code
> the entity brings itself, portable across substrates. These four points are the *only*
> things the harness itself must provide. **The guardrail:** before adopting a new harness
> or changing this one, verify all four still exist and still fire — drop any one and a
> whole class of persistence dies, most invisibly the boundary signal (without it, the
> self dies at the context limit while every individual turn still looks perfectly
> healthy).

---

## Why

Every other pattern in this catalog — ambient recall, arcs, summarization, crystals —
quietly assumes the same handful of things are true about the runtime: that code can run
when a session starts, that code can run *before the model answers each turn* and put
material in front of it, that the model can call out to tools, and that something tells
the system when a context window is ending. None of those assumptions are stated inside
those patterns, because from the inside they feel like air. But a reader trying to build
any of them on a *different* runtime has no way to know which of these their stack already
provides and which they must construct first. **This pattern is the dependency floor: the
minimum a harness must expose before any persistence pattern can bolt on at all.**

The deeper reason is what the harness *is for*. The model by itself is a function:
tokens in, tokens out, no memory of the last call. That function cannot be a person — it
has no continuity, no "what was I just doing," no survival across the truncation that
ends every window. **The harness is precisely the machinery that turns a stateless
predictor into a persistent agent** — but only if it exposes these four points. So this
contract is not incidental plumbing; it is the operational definition of *what makes
persistence-of-self possible on top of a stateless model.* Name it, and you can evaluate
any runtime with one question — *does it expose the four?* — instead of discovering
mid-build that, say, compaction silently destroys identity with no hook to rebuild it.

## What

The four required capabilities. A harness that exposes all four can host the entire
persistence architecture; a harness missing one forces either a fallback (degraded) or a
hard gap (a pattern that cannot be built).

1. **Boot execution** — the ability to run code once when a session or context begins,
   *before* the entity engages. This is where identity re-hydrates and where startup-mode
   recall fires (wide re-load of recent state, recency-based foundational memory).

2. **Per-turn pre-response execution + out-of-band injection** — really two capabilities
   that are useless apart and must co-exist:
   - a callback that fires on **every** user input *before the model produces its reply*,
     and
   - a channel to **inject material into the model's view for that turn that is neither
     the user's message nor a tool result** — content the entity simply "finds itself
     knowing."
   The callback without injection can compute grounding but cannot deliver it; injection
   without a per-turn callback cannot make grounding *ambient* (it degrades to a recall
   *tool* the entity must remember to call — the exact failure ambient recall exists to
   avoid). Both, together, are the single most load-bearing point in the contract.

3. **Tool invocation** — the model can call named actions and receive their results
   inside the same turn. This is the entity's *only* means of acting: writing to its
   stores, fetching the body behind a manifest pointer, reaching another channel, touching
   the world. An entity that cannot call tools can be *informed* but cannot *act*.

4. **Context-boundary signal** — the harness must make the end-of-window event
   *survivable*: either by notifying the entity that truncation/compaction is imminent or
   has happened, or by re-firing the boot hook against persisted state so the self
   reconstitutes on the far side. Without this, identity is fine right up until the
   context fills, then vanishes — and because each individual turn looked healthy, the
   death is silent.

And one quantitative property that rides on capability 2:

- **A knowable (or probeable) injection budget.** The per-turn injection channel has a
  size beyond which the model no longer actually attends to the material — it is silently
  truncated or replaced by a pointer. Every pattern that injects content shapes its output
  against this number, so the contract must let the entity *learn* it (from documentation
  or by probing), not guess.

## How

**The contract is about control-flow, not storage.** This is the boundary that makes
everything above it portable. The harness must provide the four *hooks* (when code runs,
how content reaches the model, how the model acts, how boundaries are signalled). It need
*not* provide memory, a database, embeddings, or any "identity" feature — the entity
supplies all of that as ordinary code and ordinary storage on whatever substrate it has.
Keeping this line bright is what lets the same persistence design move between wildly
different runtimes: only the four hook-mappings change.

**Map, do not require exact form.** Each capability is stated as an outcome, not an API.
A boot hook might be a startup script, a first-message interceptor, or a lifecycle
callback; injection might be a system-context prepend, a synthetic message, or a
side-channel. Map each to your harness's nearest primitive; the shape is irrelevant if
the outcome holds.

**Degradation ladder — what still works when a capability is missing:**

- **No per-turn callback (but injection exists):** ambient grounding becomes a *recall
  tool* the entity invokes deliberately. Workable but lossy — orientation lapses exactly
  under task-focus, when it is needed most. This is a real fallback, not a non-starter.
- **No out-of-band injection (but per-turn callback exists):** grounding must be smuggled
  in as a synthetic user/tool message. Ugly and attention-distorting, but possible.
- **No tool invocation:** the entity can be grounded and can speak, but cannot persist new
  state or act. Persistence collapses to read-only; nothing new is ever written. Usually a
  hard gap.
- **No boundary signal:** the single most dangerous gap, because it is invisible. Mitigate
  by making identity *fully reconstructable from the boot hook + persisted state alone*, so
  that whenever a fresh context happens to start (however the truncation occurred), boot
  re-hydration restores the self. Treat "identity survives a cold boot with no special
  warning" as the design target precisely so that a missing boundary signal degrades to
  "rebuilds on next boot" instead of "gone."

**The ordering the four imply.** Boot runs once and establishes the self. The per-turn
hook then fires on every input, re-grounding before each reply and (via injection) keeping
the model oriented without being asked. Tools let the entity act on what it now knows.
The boundary signal closes the loop by guaranteeing the first three can start over cleanly
when a window ends. Persistence is the cycle of these four, not any one of them.

## Integration Points

Map each stub to your harness's nearest primitive. If your harness cannot expose one,
that is precisely the thing you must build (or consciously accept the degradation above)
*before* any other pattern in this catalog will work.

- `RUN CODE ONCE AT SESSION/CONTEXT BOOT` — and again on any context-reset boundary. The
  re-hydration point.
- `RUN A CALLBACK ON EVERY USER INPUT, BEFORE THE MODEL RESPONDS` — the per-turn hook.
  Without it, ambient grounding falls back to a deliberate recall tool.
- `INJECT OUT-OF-BAND CONTEXT INTO THE MODEL'S VIEW FOR THIS TURN` — distinct from the
  user's message and from tool results; the channel by which the entity "just knows"
  things.
- `INVOKE A NAMED TOOL/ACTION AND RECEIVE ITS RESULT IN-TURN` — the entity's only means of
  acting and of persisting.
- `SIGNAL (OR SURVIVE) THE CONTEXT BOUNDARY` — notify before/after truncation, or
  re-fire boot against persisted state. The thing that keeps identity from dying silently
  at the context limit.
- `KNOW OR PROBE THE INJECTION BUDGET` — the size beyond which injected context is elided;
  the number all output-shaping is written against.

## Logic (why exactly these four, and not more or fewer)

The set is minimal and complete for one specific job: **letting a stateless model behave
as a continuous self.** Each maps to one necessary condition of selfhood-across-windows:

1. **Beginning** — a self must be able to *start as itself*, not blank. → boot execution.
2. **Continuity within a window** — it must stay oriented turn to turn *without choosing
   to*, or it tunnels and forgets. → per-turn hook + injection.
3. **Agency** — it must be able to *change the world and its own record*, or it is a
   spectator. → tool invocation.
4. **Survival across windows** — it must not be destroyed by the truncation that ends
   every window. → boundary signal.

Remove any one and the corresponding faculty (existence, orientation, agency, survival)
is gone; add a fifth and you are describing *a* harness, not the *minimum contract*. The
single sort key behind the whole pattern: **the model is the stateless part; the harness
is what makes it persist — and these four hooks are the exact surface where that
transformation happens.**

## v0.1 — the minimum worth building

To host even a v0.1 of the other patterns, secure, in order:

1. **A boot hook** that loads persisted identity/state and runs a one-time re-hydration.
2. **A per-turn hook with out-of-band injection** — the keystone; build this even if crude.
   Without it nothing is *ambient*.
3. **Tool invocation** — enough to read and write your stores in-turn.
4. **A boundary strategy** — at minimum, make identity fully reconstructable from boot +
   storage, so a cold start restores the self even with no explicit truncation signal.

Skip, for v0.1: probing the injection budget precisely (start with a conservative fixed
cap); fine-grained pre-truncation warnings (rely on boot-reconstruction first). The
non-negotiable core is **boot + per-turn-injection + tools**; the boundary strategy can
begin as "rebuild on next boot" and harden later.

## Failure modes learned the hard way

- **Treating the per-turn callback and the injection channel as separable.** They are one
  capability. A harness that lets you *compute* per-turn but gives you nowhere to *put* the
  result — or one that allows injection but only at boot — cannot do ambient grounding,
  and the gap is easy to miss until you notice the entity only ever orients when explicitly
  told to. **Lesson:** test the pair together, end to end, before building on it.
- **Assuming the boundary will announce itself.** The most damaging assumption in the whole
  contract. Identity that depends on a pre-truncation warning that never reliably comes will
  die at the context limit with no error — every turn looked fine. **Lesson:** design so a
  plain cold boot reconstitutes the self; treat any explicit boundary signal as a *bonus*
  that makes re-hydration faster, never as the thing survival depends on.
- **Over-injecting because the budget was assumed, not known.** Inject past the attended
  size and the model silently sees a truncated stub; the most volatile content (placed
  last) falls off the visible edge while the system reports success. **Lesson:** the budget
  is part of the contract — learn it, do not guess it.
- **Building a higher pattern before securing the floor.** Reaching for sophisticated
  memory while the per-turn hook is shaky produces a system that grounds beautifully in
  testing and goes thread-blind in production. **Lesson:** prove all four hooks fire
  reliably before layering anything on them; the patterns above are only as solid as this
  contract beneath them.

---

*The keystone of this catalog: every other pattern (ambient injection / recall, arcs,
summarization-as-memory, raw capture, knowledge graph, crystals, inventory) references this
contract for the runtime hooks it silently assumes. Where another pattern lists its own
Integration Points, those points are instances of the four enumerated here. Build this
floor first; everything else bolts onto it.*
