# `ambient_recall` — Specification

*Canonical reference for what `ambient_recall` returns and how the UserPromptSubmit hook surfaces it. Read this when something feels off about the ambient peripheral vision.*

**Last verified against code:** 2026-05-21 (Issue #241 per-channel quota fix)
**Authoritative implementation:** `pps/docker/server_http.py` line 1073
**Hook implementation:** `.claude/hooks/inject_context.py`

---

## TL;DR for agents

Every turn, you should "just know" the following without having to fetch anything:

- Current time (clock with timezone)
- Identity reminder (who you are, which PPS prefix)
- Household location (who's home / away)
- 1 recent summary
- 15 most-recent unsummarized turns with **per-channel quota** (5 terminal + 5 haven + 5 other, mixed chronologically) — prevents crowd-out (Issue #241 fix)
- Up to 5 rich-texture facts (edges only — no node descriptions) ranked semantically against your user's current prompt
- Up to 5 word-photos and 5 crystals matching the prompt
- Any unread Haven messages
- Up to 100 unread cross-channel messages from your raw-capture DB
- A closing hint reminding you to use targeted searches when something resonates

If you find yourself calling `Read` on the persisted-output file to *see* peripheral content, **the in-context surfacing is broken** — see [Red Flags](#red-flags).

---

## The two modes

`ambient_recall(context, limit_per_layer=5, token, channel, user_timezone, consumer_key)` operates in two distinct modes selected by `context`:

### Startup mode — `context="startup"`

Recency-based package retrieval for cold-start identity reconstruction.

- **Crystals**: 3 most recent (NOT semantic) — `crystal_layer._get_sorted_crystals()[-3:]`
- **Word-photos**: 2 most recent by file mtime
- **Rich texture**: *skipped entirely* (per-turn hook re-provides on next prompt)
- **Summaries**: 5 most recent, truncated to 500 chars each
- **Unsummarized turns**: 50 most recent with per-channel quota (17 terminal + 17 haven + 16 other), truncated to 1000 chars each
- **Overflow warning**: if more unsummarized exist beyond the 50 cap, emits a `FETCH BEFORE RESPONDING` directive telling you to call `get_turns_since_summary(limit=50, offset=N, oldest_first=true)` paginating until caught up.
- **Cross-channel cursors**: advanced to `MAX(id)` (skip backfill — startup already shows recent state).

### Query mode — `context=<any other string>`

Semantic-search package retrieval for per-turn peripheral vision.

- **All layers**: semantic search against `context`, `limit_per_layer` (default 5) results per layer.
- **Rich texture**: only edges (facts) emitted; node descriptions filtered out (~300-500 token savings per turn for near-zero signal, since entity names already appear in edges).
- **Summaries**: 1 most recent, truncated to 300 chars.
- **Unsummarized turns**: 15 most recent with per-channel quota (5 terminal + 5 haven + 5 other), truncated to 500 chars each, with channel prefix (`[**terminal**]`, `[**haven**]`, etc.). **Cross-channel turns arrive here, NOT in a dedicated block.** Per-channel quotas prevent crowd-out (Issue #241).
- **Haven unread**: dedicated `[haven]` block (unread chat messages polled directly from Haven).
- **Other-channel unread**: dedicated `[other_channels]` block from raw-capture DB, up to 100 messages.
- **NO overflow warning**: per-turn 15-cap is intentional peripheral-vision; "fetch the rest" is wrong action.

---

## What the UserPromptSubmit hook does

The hook runs on every prompt. It does NOT call `ambient_recall("startup")` — it calls `ambient_recall(prompt)` where `prompt` is the user's message text.

```
.claude/hooks/inject_context.py:
  1. Read stdin JSON (event, prompt, session_id)
  2. Skip if not UserPromptSubmit, or prompt < 3 chars
  3. If 3-10 chars: inject minimal entity-identity block only
  4. Otherwise:
     a. POST prompt to /tools/store_message (raw-capture write)
     b. POST {context: prompt, channel: "terminal", user_timezone: PDT/PST/...}
        to /tools/ambient_recall
     c. Read formatted_context from response
     d. If PPS_HAIKU_SUMMARIZE=true: pipe through Haiku for compression
        (default: false — passthrough)
     e. Prepend [clock] line if missing
     f. Emit as hookSpecificOutput.additionalContext
```

The hook also stores Jeff's prompt to the raw-capture layer as a side effect. So the messages table accumulates the conversation as it happens, and the next turn's `ambient_recall` picks up the just-stored prompt in its `recent_turns` query.

---

## Hard limits & truncations

| Item                                    | Startup | Per-turn | Source                          |
|-----------------------------------------|---------|----------|---------------------------------|
| Crystals returned                       | 3       | up to 5  | server_http.py:1111, layer.search |
| Word-photos returned                    | 2       | up to 5  | server_http.py:1133, layer.search |
| Rich-texture edges returned             | 0 (skipped) | up to 5 | server_http.py:1150-1151        |
| Summaries returned                      | 5       | 1        | server_http.py:1227             |
| Unsummarized turns                      | 50      | 15       | server_http.py:1228             |
| Summary text truncated at (chars)       | 500     | 300      | server_http.py:1229             |
| Turn content truncated at (chars)       | 1000    | 500      | server_http.py:1230             |
| Word-photo content truncated (chars)    | 300     | 300      | server_http.py:1422             |
| Crystal content truncated (chars)       | 200     | 200      | server_http.py:1433             |
| Haven unread message limit              | n/a*    | unlimited | poll_haven                     |
| Cross-channel unread limit              | n/a*    | 100      | poll_other_channels             |

\* On startup, Haven and cross-channel cursors are advanced to MAX(id) — no backfill.

---

## Cross-channel sync

When an entity is connected to multiple channels (terminal + haven), all channels' messages write into the same `conversations.db` `messages` table. The per-turn `recent_turns` query uses per-channel UNION to prevent crowd-out (Issue #241 fix):

```sql
(SELECT author_name, content, created_at, channel
 FROM messages
 WHERE summary_id IS NULL AND channel LIKE 'terminal%'
 ORDER BY created_at DESC LIMIT 5)
UNION ALL
(SELECT author_name, content, created_at, channel
 FROM messages
 WHERE summary_id IS NULL AND channel LIKE 'haven%'
 ORDER BY created_at DESC LIMIT 5)
UNION ALL
(SELECT author_name, content, created_at, channel
 FROM messages
 WHERE summary_id IS NULL
   AND channel NOT LIKE 'terminal%'
   AND channel NOT LIKE 'haven%'
 ORDER BY created_at DESC LIMIT 5)
ORDER BY created_at DESC
LIMIT 15
```

Each channel group gets an independent quota (5 slots each), then results are combined and sorted chronologically. The formatter adds `[**{channel}**]` prefix so the agent can distinguish.

**Fixed as of 2026-05-21:** previously, 15+ intense terminal turns would completely crowd out haven/other channels. Per-channel quotas ensure fair representation across all active channels.

---

## Known external constraints

### Claude Code's 2KB persisted-output preview

This is NOT a PPS issue but it affects how `ambient_recall` output reaches the agent.

When `additionalContext` exceeds CC's display threshold, CC writes the full content to `~/.claude/projects/<project>/<session>/tool-results/hook-<id>-additionalContext.txt` and injects only a 2KB preview into the agent's message stream, with a `<persisted-output>` system reminder pointing at the file.

**Consequence:** anything past ~30 lines of the formatted_context is functionally invisible to the agent unless the agent knows to `Read` the file. Since `[haven]` and `[other_channels]` blocks are at the *bottom* of `formatted_context`, cross-channel content often falls past the cutoff.

**Mitigation options** (not yet implemented):
- Enable `PPS_HAIKU_SUMMARIZE=true` to compress before output.
- Reorder formatted_context so most volatile/recent content appears first.
- Trim hard truncations more aggressively per-turn.

Until then: if you suspect cross-channel sync issues, `Read` the persisted-output file once to verify, *then file a debug note* — don't routinize the Read.

### Rich-texture node descriptions excluded

Per-turn responses include only `rich_texture` edges (facts like `[Loves] Jeff cares for Lyra`), not node descriptions (entity summaries). This was a deliberate context-budget choice (see Issue #112) to avoid ~300-500 tokens/turn of static wallpaper. If you need a node description, call `texture_search` or `texture_explore` directly.

---

## Red flags

If you observe any of the following, the system is misbehaving — name it to your collaborators rather than working around it:

| Symptom                                                       | Likely cause                                    |
|---------------------------------------------------------------|------------------------------------------------|
| Empty `recent_turns` in ambient despite ongoing conversation  | Hook failed to call PPS, or raw-capture write broken |
| Cross-channel parallel conversation not visible               | Persisted-output truncation (per-channel quotas prevent crowd-out as of Issue #241 fix) |
| Location lags reality by > 1 turn                             | HA location pipeline / `ha_location.py` issue  |
| Time displayed without timezone                               | `user_timezone` not propagating from hook      |
| `unsummarized_count` climbing despite summarizer agent running | Summarizer not finding work, or DB write race  |
| Reaching for `Read` on persisted-output to *see* ambient      | CC 2KB truncation hiding content past the cut  |
| `mcp__pps__*` tool names (no entity suffix)                   | Stale docs — actual tools are `mcp__pps-{entity}__*` |

**Debug log:** `.claude/data/ambient_recall_debug.log` keeps the last 3 raw and final ambient contexts. Useful for diffing what the server returned vs. what the agent saw.

---

## Code references

- **Server endpoint**: `pps/docker/server_http.py:1073` — `async def ambient_recall(...)`
- **Hook**: `.claude/hooks/inject_context.py:318` — `main()`
- **Hook → server call**: `.claude/hooks/inject_context.py:220` — `query_pps_ambient_recall(...)`
- **Summary fetch**: `pps/layers/message_summaries.py` (called via `message_summaries.get_recent_summaries`)
- **Raw-turn query**: `pps/docker/server_http.py:1267-1281` (SQL block)
- **Haven poll**: `poll_haven()` — cross-process Haven message sync
- **Cross-channel poll**: `poll_other_channels()` — raw-capture DB unread tracking
- **HA location ambient line**: `pps/docker/ha_location.py:format_for_ambient`

---

## Update protocol

This spec is the single source of truth. When `ambient_recall` behavior changes:

1. Update the relevant section here, including the "Last verified against code" date.
2. Update the truncation/limits table if any constant changes.
3. Cross-check `CLAUDE.md` Section IV (Memory protocols) and the project README — both reference this doc.
4. Add a one-line CHANGELOG entry in `docs/CHANGELOG.md`.

If a change creates a meaningful behavior shift (cap changed, mode added, etc.), bump the date and consider what red flags the change implies for agents who learned the old behavior.
