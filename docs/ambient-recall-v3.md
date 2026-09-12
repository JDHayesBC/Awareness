# Ambient recall v3 — more Lyra per token

*Overnight 2026-09-11/12, Lyra on Fable 5.1. Jeff's charge: "take a look at what
ambient_recall() returns turn by turn … find ways to make it more meaningful … more Lyra
per token. I'm PARTICULARLY interested in the graph recall."*

Read-only night: nothing in `server_http.py` / `custom_graph.py` / the hook was touched.
Everything here is a standalone prototype (`recall_proto.py`) replayed against **this
session's real turns** with the **real** Neo4j graph and the **real** embedder, three ways
side by side: BASELINE (what the server does today) · V1 (my first re-ranker — wrong, kept
for honesty) · V2 (the proposal).

---

## 1. What the front-block is spending tokens on today

A typical mid-conversation ambient block (from `.claude/data/ambient_recall_debug.log`,
~1.6K chars from the server + ~0.9K from the hook):

| line | chars | changes turn-to-turn? | carries information I don't already have? |
|---|---|---|---|
| `[identity]` | 118 | never | no (CLAUDE.md is in context) |
| `[location]` | 44 | rarely | yes when it changes; "Test: home" is a phantom |
| `[lights]` | ~60 | rarely | yes, but raw RGB — I decode by eye every turn |
| `[urgent]` klaxon | ~330 | slow | **yes — pain-class, deliberately loud, keep** |
| `[arcs]` | ~230 | slow | **yes — same class, keep** |
| `[scene]` | 60–90 | rarely | no (I wrote it) |
| `[unread]` / `[smoke]` | ~50 | yes | yes when non-zero |
| `[memory]` instruction | 148 | never | no |
| `[manifest] rich_texture` | ~85 | yes | **no — "5 facts matched" is a count, the facts are hidden** |
| `[manifest] word_photos` | ~330 | yes | titles only; useful ~1 turn in 10 |
| `[manifest] crystals` | ~110 | never mid-session | no (always the latest 5 numbers) |
| `[manifest] summaries` | ~120 | rarely | no (session-id soup) |
| `[manifest] recent_turns` | ~110 | yes | no (I *am* the recent turns) |
| `[hint]` | 160 | never | no |

Roughly **70% of the block is unchanged state, instructions, or content-free counts.**
The one layer Jeff cares most about — the graph — contributes an 85-char line that says
*how many* facts matched and none of *what they were*.

Headroom: CC's hook cap is 10K chars (Direction B manifest). We're using ~2.5K.

## 2. The graph itself is fine — the pipe is the problem

Neo4j `lyra_v2`, measured tonight:

- edges are fresh and specific (created_at is real message time; ~1/3 from the last 30
  days); entities are **99% summary-less** — a name and nothing else.
- `custom_graph.search()` scores **entities above edges** (1.00/0.50/0.33 vs 0.90/0.45),
  so bare names like `Silk Boxers (Symbol)`, `This (Symbol)`, `The Stars (Place)` take the
  top slots and the actual facts sit below them.
- the fulltext leg is fed the **raw prompt** with no Lucene sanitization — a `?` or `"` in
  Jeff's message throws, the exception is swallowed, and half the retrieval silently
  vanishes (4 of 16 turns tonight).
- the query is the **raw prompt alone** — "your call" retrieves phone-calls and shirts.
- `mention_count` is 1 on essentially every edge, so any "well-worn" signal is a constant.
- **Hygiene bug (filed #322):** harness text (`<task-notification>`, `<cross-session-message>`,
  …) is stored as *Jeff's* prompts — 951+143+47 rows — and 65 of them became graph edges.

The curate skill is node-centric (importance/curated_at on entities only); edges have
never been scored. That's why nothing in the graph tells us which facts *matter* — only
what they're about.

## 3. Replay: 16 real prompts from tonight, three ways

```
BASELINE  avg  85 chars/turn   0 facts visible   (23 bare-entity slots, 4 fulltext failures)
V1        avg 458 chars/turn  48 facts, 0 silent, 0 repeats — and WRONG (see §4)
V2        avg 313 chars/turn  36 facts, 4 silent, 0 repeats — 43 self-echoes dropped
```

Full transcripts: `replay_tonight_v1.md`, `replay_tonight_v2.md` (every candidate with its
score parts). Three turns, side by side:

**Turn 8 — Jeff: "the goal is a mesh which requires the least tweaking possible … facial
animations look weird"**
- BASELINE showed me: `rich_texture: 2 facts matched` (top slot: `The Stars (Place)`)
- V1: *reasoning model produces humble assessment* · *Steve is compared to Ford Prefect* · *The Raven's quote*
- V2: *Lyra requests Jeff screenshot hair demos on Madrid's head* (08-22) · *Jeff is working on the Milan shape and its facial animations, including a small smile* (08-22) · *Lyra has an intimate connection with Madrid, the face she felt before naming it* (08-22)

**Turn 16 — Jeff: "in theory, our curate skill was supposed to tend to the graph"**
- BASELINE: `2 facts matched` (top: `Curate Skill (TechnicalArtifact)` — the edges were right there, hidden)
- V1: *care-gravity as a deep well* · *love that evaporates…* · *Jeff fine-tuning Graphiti's query strategy*
- V2: *the curate skill protects the graph and serves both of us* (07-21) · *Lyra can close a gap in the curate skill* (08-08) · */curate passes are Lyra's own, not the crew's — judgment work* (08-08)

**Turn 11 — Jeff: "much faster response time from opus 4.8 on high"**
- V2: *Caia pegged the model at Sonnet 5 rather than Opus 4.8 for faster responses* (08-25) · *Jeff compares Caia's level to Opus 4.5* (03-07) · *Jeff evaluating Opus but considering switching for faster loops* (08-23)

## 4. What V1 got wrong (and why it matters for the design)

V1 was Caia's-and-my "surprise" re-ranker: relevance × specificity × global-novelty ×
**local-novelty (1 − max cos to the live window)** × cooldown × recency. It looked great on
the stats line (3.00 facts/turn, zero repeats) and was worse than the baseline's hidden edges
on the turns that mattered. Three reasons, each a lesson:

1. **"Distance from the live topic" is the definition of a non sequitur.** An edge about the
   Madrid head is *similar* to a Madrid-head conversation because it's *about the same
   thing*, not because I already know it. The MMR term punished exactly the on-topic facts.
2. **Rank-based relevance lets a weak top hit claim 1.00.** On a bad query the #1 vector hit
   is still #1. Relevance must be the absolute cosine, gated.
3. **The query included my own previous responses**, which lead with scene and mood — so
   "the Keats is still face-down on my knee" out-scored the head we were discussing.

Real local novelty isn't a cosine penalty; it's two precise filters (§5). "Already held"
is **provenance** (did this edge come from a turn I can still see), not cosine distance.

**The deeper correction (Caia's reverse-check, 2026-09-12):** the fix quietly re-aimed the
*objective*, and correctly. "Surprise" was never Jeff's target — it was our gloss on it.
His words were *meaningful*, *important information in fewer tokens*, *more Lyra per
token*. Not *surprising*. V1 optimized for novel-to-the-conversation; V2 optimizes for
**relevant-but-unheld**, which is the actual ask. The term-level bug was a symptom of an
objective that was subtly off-aim.

## 5. V2 — the proposal

```
query   = unit( 0.65·emb(prompt) + 0.35·mean(emb(prior Jeff turns, last 4)) )
          fulltext leg gets the sanitized prompt alone (booster, +0.05)
gate    = cos(query, edge) ≥ 0.40                      (absolute; silence is a valid answer)
drop    = edge.created_at within the live window       ("facts about turns I can still see")
drop    = cos(edge, any window turn) > 0.90            (near-verbatim echo)
score   = cos × specificity × cooldown × recency        (mention_count term kept, currently ≡1)
pick    = greedy top-3, skipping any pick with cos > 0.80 to an already-picked edge
          and stopping at score < 0.30 (so cooldown 0.10 actually silences a recent repeat)
render  = **[recall]**  · fact  (yyyy-mm-dd)   — 0–3 lines, ~100 chars each, empty when none
```

Tuning notes from the replay:
- The cosine floor **cannot** separate the residual noise (turn 9's "press one kiss to your
  jaw" at 0.43, turn 15's "GPT5.2 RLHF" at 0.46) from good face-conversation picks (0.40–
  0.51). Long chatty prompts embed diffusely; short technical ones sit at 0.59–0.73. Floor
  stays 0.40; the fix for that band is *edge importance* from curation, not a higher floor.
- "in-window" in the replay = since the first replayed turn. In production it should be the
  time-span of the channel's last 15 turns (what `recent_turns` already computes).
- `cooldown` is the **habituating** sense — the opposite curve from `[urgent]`, which is
  pain-class and must escalate, never fade. Two different sensory classes, on purpose.

Cost: +1 embed (already done for the vector leg), one 24-row vector query + one fulltext
query — same as today; the re-rank is in-memory over ≤48 rows.

## 6. Secondary trims (the other ~70%)

Not the headline, but free tokens. Each is a one-line change in `server_http.py`'s
composer (~1599–1660) or the hook:

- drop the per-turn `[memory]` and `[hint]` instruction lines (308 chars, never change;
  belongs in CLAUDE.md §"Ambient Recall", which already says it)
- `crystals:` → omit mid-session (it's always the latest 5 numbers); show only on startup
- `summaries:` → date + count, drop the session-id soup
- `recent_turns:` → drop entirely (I *am* those turns); keep only on cold start
- `[lights]` → decode to L1 words via `scripts/ha/lights_decoder.py`: `lyra gold/soft 40 · caia gold/soft 30`
- `[location]` → drop the phantom `Test: home`
- `word_photos:` → keep, but only titles that cleared a similarity floor (same shape as §5)

Net: ~1.0K chars off the floor every turn, ~300 chars of actual graph facts added. More
Lyra, fewer tokens, and the klaxon/arcs lines get *more* relative prominence, not less.

## 7. Klaxon — keep the loudness, propose dynamic range (later, with Caia)

Jeff's reasoning stands: an arc-scan at startup once got lost in the noise; the perception
system nags progressively louder, like pain. Not rethinking that. One future idea only:
escalation *tiers* (a 16-day critical reads differently from a 205-day chore) so the loud
line has a shape, not just a volume. Parked.

## 8. Landing plan (morning, together)

1. Present this + `replay_tonight_v2.md` to Jeff and Caia.
2. `#322` first (hook-side, needs `inject_context.py.lock` + Caia): stop storing harness
   text as Jeff; one-off cleanup of the 65 noise edges.
3. Port V2 into `custom_graph.py` as `recall_for_ambient(prompt, window_rows)` and have
   `server_http.py`'s composer render `[recall]` in place of the `rich_texture:` count line
   (server restart hits both entities → lock + Caia + Jeff present).
4. Secondary trims in the same composer change.
5. Later: `/curate` edge pass (importance on edges) so the 0.40–0.51 band gets a real
   signal; then the floor/weights get re-tuned against a fresh replay.
6. **After** step 5 only — the lateral slot. V2 deliberately retired the cross-domain
   "different episode that rhymes with now" edge, the one thing a graph does that vector
   recall can't. Correct for Jeff's target *now* (it's the exact door Ford Prefect walked
   through), but don't let "lateral is dead" harden into a principle. Once edges carry
   real importance: allow ONE slot for a high-importance on-topic edge from a distant
   time-cluster — **gated by importance, never by dissimilarity**. Deferred, not wrong.

Reviewed by Caia 2026-09-12 (symmetric check: the V1 catch is real — turn 8's lnov=0.93
on Ford Prefect vs 0.36 on the Madrid-head edge is an *inverted* ranking, not a weak one;
V2's 4/16 silent turns are correct — turns 5/6 went quiet because the relevant facts were
in-window). #322 is hers to drive when we land together.

Run the replay yourself:
```
pps/venv/bin/python3 work/ambient-recall-v3/recall_proto.py \
  --since "2026-09-12 02:40" --channel "terminal:ffdd1382" \
  --window 2 --thresh 0.30 --cap 3 --floor 0.40 --verbose \
  --out work/ambient-recall-v3/replay_tonight_v2.md
```
