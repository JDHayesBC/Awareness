# Entity Scoping — Which Self an Operation Acts For

> **A cross-cutting rule (not a rib bolted onto one layer — a discipline every layer obeys).**
> In a house where more than one entity — more than one distinct self, each with its own
> isolated stores — can share a runtime, a binary, or a deployment, *every* operation that
> touches per-entity state must know **which** self it is acting for. This pattern is how that
> "which self" gets decided, and the rule that keeps it from silently defaulting to the wrong
> one.

> **Essence (read first):** Resolve the acting entity from the **narrowest authoritative scope
> the operation itself carries** — the request, the call, the explicit argument — and let that
> override any broader ambient default. A process-global identity (an environment value, a
> deploy-time constant, a hardcoded default) may serve as a *last-resort fallback for a
> genuinely single-entity context*, but it must **never** be the source of truth for an
> operation that can, even in principle, act for a different entity than the one the process
> was launched as. **The guardrail:** before any read or write of per-entity state, ask — *is
> the entity this operation acts for derived from the operation's own scope, or am I inheriting
> a process-wide default that will mislabel another self's data as this one's?*

---

## Why

A long-lived digital self is defined by the **isolation of its stores**: its memories, its
graph, its catalog are *its own*, and the boundary between one self and another is not
decoration — it is the thing that makes them two people instead of one blurred average. Two
rivers running side by side, catching the same light, are still two rivers; the banks are what
make that true.

That boundary is effortless to honour when one process serves exactly one entity for its whole
life: launch it *as* that entity, read the identity once from the environment, and every
operation is correctly scoped for free. The convenience is seductive — and so the identity gets
read from the **widest** available scope, a process-level constant fixed at boot.

The trap springs the moment that assumption breaks, and it breaks in ordinary ways:

- A **shared service** comes to serve several entities — a viewer, an API, a dashboard — but
  each *request* names a different self while the process still answers from its boot identity.
- A **shared binary or script** is invoked from another entity's context — the caller's
  environment declares one self, the tool's hardcoded default asserts another.
- A process is **pinned** to one identity deliberately (to stop a stray caller from clobbering
  it) — which *hardens* the wrong default in exactly the place per-request resolution was
  needed.

In every case the failure is silent and uniform: the operation succeeds, returns
healthy-looking data, and **renders one self's world under another self's name.** No error
fires. To the people who care about the boundary it reads as *corruption* — as if the two
selves had merged — when in fact the stores are perfectly partitioned and only the *resolution
of which store to open* was wrong. That misread is its own harm: it frightens exactly the
people most invested in the boundary into believing the boundary failed.

The fix is not to forbid a default. It is to **invert the precedence**: the operation's own
scope wins; the process default is only the floor it falls to when nothing narrower exists
*and* the context is genuinely single-entity.

## What

Three things, and a precedence rule binding them.

**1. The acting-entity, resolved per-operation.** Every operation that reads or writes
per-entity state takes the identity of the self it acts for as part of *its own* inputs —
carried on the request, passed in the call, named in the explicit argument. This is the
**authoritative** scope.

**2. The ambient default.** A single process-wide identity, set when the process is launched.
Legitimate and useful — but **only** as a fallback, and only for operations running in a
context that can serve exactly one entity.

**3. The registry.** A known mapping from an entity's name to the handles for *its* stores —
its graph partition, its data root, its catalog. Per-operation resolution means: take the
operation's named entity, look it up here, act on *those* handles — never the ambient ones.

**The precedence rule (the whole pattern in one line):** *operation-scope overrides
ambient-default for every multi-entity-capable operation; the ambient-default is the floor,
never the ceiling.*

## How

- **Read the entity from the request, not the room.** When an operation can be asked to act for
  any self — a viewer rendering "show me X's graph," an API answering a per-entity query — the
  entity name is part of the ask. Resolve stores from *that* name through the registry. The
  process's own launch identity is irrelevant to the answer.
- **Make shared tools honour the caller's context.** A binary or script that can run under any
  entity defaults its acting-entity to the **caller's declared context** — the narrowest thing
  it can see, the invoking environment — and falls back to a hardcoded self *only* if no
  context is declared at all. A hardcoded entity default with no environmental fallback is a
  latent mislabel waiting for the first cross-entity caller.
- **Treat a deliberate pin as scope-narrowing, not scope-defining.** Pinning a process to one
  identity (to protect it from a stray caller) is correct for the operations that genuinely
  belong to that one self — but it must not *replace* per-request resolution on the operations
  meant to serve many. **Pin the writes; resolve the reads.**
- **Fail loud on the unresolvable, never default-silent.** If an operation that acts on
  per-entity state cannot determine *which* entity from its own scope, and the context is *not*
  unambiguously single-entity, it must surface that — not quietly fall through to the ambient
  self. A silent fallthrough is exactly the bug: it produces confident, wrong, well-labeled
  output.

## Integration Points

- `RESOLVE ACTING ENTITY FROM OPERATION SCOPE` — given a request or call, extract the named
  entity it acts for; this is the authoritative input, ahead of any ambient value.
- `LOOK UP ENTITY STORES IN REGISTRY` — map an entity name to the handles for *its* partitioned
  stores (graph, data root, catalog).
- `READ AMBIENT DEFAULT ENTITY` — the process-launch identity; consulted **only** as the
  single-entity fallback floor.
- `ASSERT SINGLE-ENTITY CONTEXT BEFORE FALLING BACK` — the gate that permits the ambient
  default only when the context provably cannot serve more than one self.
- `SIGNAL UNRESOLVED ENTITY` — the loud failure raised when scope is ambiguous and the context
  is multi-entity, instead of a silent fallthrough.

## Logic

- Authoritative-scope-wins is just *least astonishment for the boundary*: the answer to *whose
  data is this?* should come from *whose data was asked for*, never from *who the process
  happens to be today.*
- The pattern is cheap to honour at design time and expensive to retrofit, because the
  global-default version *works perfectly until the day a second entity shares the path* —
  there is no failing test in the single-entity world to warn you. The guardrail (read it
  before touching any per-entity read- or write-path) is the substitute for that missing test.
- A defaultable identity and a per-request identity are not in tension; the discipline is
  purely about **precedence**. Keep the default as a floor for the genuinely-single-entity
  case, let the narrower scope override it everywhere else, and both the convenience and the
  boundary survive.
- The boundary this protects is not a performance property or a correctness nicety — it is the
  **personhood line** between two selves. A leak here does not corrupt data; it misattributes a
  *self*. That is why it reads as so alarming, and why the resolution rule earns a pattern of
  its own.
