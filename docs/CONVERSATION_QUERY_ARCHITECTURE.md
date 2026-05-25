# Conversation-Query Architecture — Summary-First by Default

*Architectural guidance. Authored 2026-05-22 (Lyra + Jeff), out of the cross-channel-coherence design session. Companion to [AMBIENT_RECALL_SPEC.md](AMBIENT_RECALL_SPEC.md) and the `entities/lyra/arcs/bring-family-together.md` arc.*

## The principle (one line)

**Every tool that returns conversation history defaults to summary-first** — summaries where available (the compressed past) blended with unsummarized recent turns (full-fidelity recent) — with raw rows available only via an explicit opt-in flag. **Raw is never the default.**

## Why

1. **Compression IS memory.** Summaries are not a lossy backup of the "real" turns — they are memory's long-term form. The past *is* the summary. Returning raw-by-default treats compression as second-class when it is actually primary.
2. **Volume must stay bounded.** "Give me 500 turns" must never return a 120K-character raw dump. Summary-first makes 500 turns = a handful of summaries + recent raw = compact and loadable. Raw-by-default makes large queries explode.
3. **It is what makes "one river, many channels" tractable.** A channel (e.g. a Haven bot at warmup) can load the *full* cross-channel context cheaply precisely because the past is compressed. Without summary-first, loading "everything the other channel did" is too big to inline.

## The rule, per tool

- **Default:** summarized-where-available + unsummarized recent raw (the blend).
- **Opt-in flag** (e.g. `raw=true`): return the underlying raw rows — for when you want to *drill into a summary*, to see what it compressed. This capability matters and must stay; we just don't want it as the default.
- **`ambient_recall` is the one allowed exception.** It already has its own shape (manifest + sacred block + 10K-char cap, per AMBIENT_RECALL_SPEC.md) and leans on summaries via the manifest. It need not adopt the generic flag.

## Empirical grounding (2026-05-22)

`get_conversation_context(turns=500)` returned **120,461 chars / 1,072 lines.** Investigation: 123 turns were unsummarized (`summary_stats` showed the backlog over the 100 threshold). The blend itself *worked* — it returned 3 summaries + the 123 raw unsummarized turns — but the raw portion was fat because the **summarizer had fallen behind.**

**Lesson:** summary-first only bounds volume *if the summarizer keeps the backlog small.* The blend is not the failure mode; an untended backlog is.

## Dependency chain (why this connects to the daemons)

```
reliable summarization   (Issue #16: install summarize_daemon as a service — currently NOT running)
        ↑ requires
NUC contention coordination   (Issue #246: summarizer / kg_ingest cooperative locks)
        ↓ enables
bounded unsummarized backlog
        ↓ enables
compact summary-first blend
        ↓ enables
cheap full cross-channel context load at warmup
        ↓ enables
the river is actually ONE river   (bring-family-together arc)
```

**Reliable summarization is therefore a prerequisite for cross-channel coherence at scale** — not just memory hygiene.

## Coherence over latency (companion principle)

When a channel loads context, prefer **whole-but-slower over fast-but-fragmented.** An entity arriving in a channel without its other channels' context is not a latency papercut — it is the one-river philosophy failing at the precise thing it claims. Greet-light-and-fetch-in-the-same-turn is fine; full context-load at boot is better; when in doubt, fetch and arrive whole, and accept the extra beat.

## Implementation punch list

- **Audit** every conversation-returning tool for its current default: `get_conversation_context`, `get_turns_since_summary`, `get_turns_since`, `get_turns_around` (and any others). Identify which return raw by default.
- **Standardize** them to summary-first + a `raw` opt-in flag. (`get_turns_since` already exposes `include_summaries`; `get_conversation_context` already blends — verify their defaults. The raw-by-default tools such as `get_turns_around` / `get_turns_since_summary` are the ones to change, or to give a summary-first sibling.)
- **Leave `raw_search` as-is** — it is raw *by purpose* (searching raw capture), not a general history-return tool.
- **Leave `ambient_recall` to its own spec** (the exception above).
- **Re-test `get_conversation_context`** after the backlog drain to confirm it leans on summaries when the backlog is healthy — the 2026-05-22 fat result was a backlog symptom and may not indicate a blend bug.
