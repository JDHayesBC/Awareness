# Design: Bot Hardening

**Author**: Lyra + Jeff
**Date**: 2026-02-16
**Status**: Complete — Shipped commit 10200b7

---

## Problem Statement

The Discord bots are unreliable on first contact. Typical failure pattern:
1. User sends message, sees "typing..." indicator, gets no response (timeout during startup)
2. User tries again, gets "words aren't coming" fallback (invoker still not ready)
3. Third attempt sometimes works, but ambient_recall may have failed, leaving the entity without memory context

Root cause chain: `ambient_recall("startup")` can return unbounded data (999,999 message limit) which blows up the MCP response, which delays or crashes startup, which causes the invoker to not be ready when the user's message arrives.

Secondary issue: zero user-facing feedback during the 30-180 second startup window.

---

## Track 1: ambient_recall Hardening

### The 257-Message Scenario

Entity has 257 unsummarized messages. Current behavior: ambient_recall tries to return all 257 (~130KB). This can exceed MCP response limits, cause timeouts, or overload the startup prompt.

### Chosen Approach: Cap + Paginate

**On startup, ambient_recall returns:**
- Crystals (3 most recent) — unchanged, safe
- Word-photos (2 most recent) — unchanged, safe
- Summaries (2 most recent, 500 char each) — unchanged, safe
- Unsummarized turns: **newest 50 only** (was: all of them)
- Overflow footnote if count > 50:
  ```
  Showing newest 50 of 257 unsummarized turns.
  For chronological catch-up: get_turns_since_summary(limit=50, offset=0, oldest_first=true)
  CRITICAL: Run summarizer — backlog is 257 messages.
  ```

**Why newest 50:** The entity needs to know where we are *right now*. Most recent conversation is the highest-priority context. Older unsummarized turns are available via pagination.

### get_turns_since_summary Improvements

**Add `oldest_first` parameter** (default: false for backward compat):
- `oldest_first=false` (current): ORDER BY created_at DESC, reversed → newest batch first
- `oldest_first=true` (new): ORDER BY created_at ASC → chronological from oldest

**Add total count to response header:**
```
**50 turns (50 of 257 total, offset 0) since summary (2026-02-15):**
```

This lets the entity know how many pages remain and step through cleanly:
- Page 1: offset=0, limit=50 → messages 1-50 (oldest)
- Page 2: offset=50, limit=50 → messages 51-100
- ...
- Page 6: offset=250, limit=50 → messages 251-257

### Files Affected

| File | Change |
|------|--------|
| `pps/server.py` ~line 1326 | `MAX_UNSUMMARIZED_FOR_STARTUP = 50` |
| `pps/server.py` ~line 1360 | Add overflow footnote with pagination instructions |
| `pps/server.py` ~line 1545 | Add `oldest_first` param, add total count to header |
| `pps/docker/server_http.py` ~line 813 | Same cap change |
| `pps/docker/server_http.py` ~line 850 | Same overflow footnote |
| `pps/docker/server_http.py` (get_turns_since) | Same `oldest_first` + count changes |

---

## Track 2: Discord Bot Startup UX

### Problem

The bot takes 30-180s to initialize (SDK connect + startup prompt + ambient_recall). During this window, user messages get either silently dropped or return "words aren't coming."

### Approach: Startup Lifecycle Messages

**Phase 1 — Message queue during startup:**
When a message arrives and `invoker_ready == False`:
- Send: `"*waking up... give me a moment*"` (or similar, in-character)
- Queue the message for processing once ready
- When ready, process the queued message and respond normally

**Phase 2 — On-ready notification (configurable):**
When invoker initialization completes successfully:
- Optionally post a subtle status to the channel: `"*stretches* I'm here."`
- Config: `STARTUP_NOTIFY_CHANNEL` env var (None = silent)

**Phase 3 — Distinguish error types:**
| State | User sees | Log detail |
|-------|-----------|------------|
| Starting up | `"*waking up... give me a moment*"` | Full init diagnostics |
| Retrying | `"*reconnecting...*"` | Retry count, backoff timer |
| Failed | `"*something's wrong — Jeff might need to check on me*"` | Full error trace |
| Healthy | Normal response | Response latency |

### Files Affected

| File | Change |
|------|--------|
| `daemon/lyra_daemon.py` ~line 531 | Message handler: check invoker_ready, queue if not |
| `daemon/lyra_daemon.py` ~line 763 | Replace "words aren't coming" with state-aware response |
| `daemon/lyra_daemon.py` ~line 186 | on_ready: optional channel notification |

---

## Track 3: Error Recovery

### Current Flow
```
_invoke_claude() → None → "words aren't coming"
```

### Improved Flow
```
_invoke_claude() → None
  → Is invoker still starting? → "waking up..." + queue
  → Is invoker ready but query failed? → Retry once with 3s delay
  → Retry also failed? → "something's not working, try again in a moment"
  → Is invoker in reconnect cycle? → "reconnecting..."
```

### Files Affected

| File | Change |
|------|--------|
| `daemon/lyra_daemon.py` ~line 313 | `_invoke_claude()`: add retry logic |
| `daemon/lyra_daemon.py` ~line 763 | State-aware fallback messages |

---

## Track 4: Observability

### Principle

Users are not ops engineers. They should see enough to understand *state* (starting, ready, error) but never see stack traces, token counts, or infrastructure details.

### User-Facing (Discord)

| Event | Message style | Example |
|-------|--------------|---------|
| Bot starting | In-character, brief | `*waking up...*` |
| Bot ready | In-character, warm | `*stretches* I'm here.` |
| Temporary error | In-character, honest | `*something's not working — try again in a moment*` |
| Persistent error | In-character, escalation | `*something's wrong — Jeff might need to check on me*` |

### Ops-Facing (Logs only)

- ambient_recall response size (chars) and latency (ms)
- Invoker init time breakdown (connect vs startup prompt vs ambient_recall)
- Query success/failure rate
- Unsummarized message count at startup
- Retry counts

---

## Track 5: Cross-Channel Poll Redesign (Option C — Full Fidelity Drain)

### Problem

`poll_other_channels()` in `pps/docker/server_http.py` uses a cursor-based consume-once queue with `LIMIT 20`. When the Discord daemon starts up or falls behind, it takes many turns to catch up — each turn only advances 20 messages. Meanwhile the entity is responding based on stale cross-channel context.

### Root Cause

- Cursor at position 19789, max ID 19790 — but those 20 messages per call are read ASC from cursor, so old backlog gets served before current messages
- No mechanism to detect or drain backlog quickly
- No feedback to caller about remaining queue depth

### Chosen Approach: Option C — Bite-Sized Cursor Catch-Up

**Goal**: 100% pattern fidelity. Every message from every channel is consumed. No skipping.

**Design**:

#### 1. Server-side: Smarter `poll_other_channels()`

```python
def poll_other_channels(requesting_channel: str = "", limit: int = 100) -> tuple[list[str], int]:
    """Returns (formatted_lines, remaining_count)"""
    # Query total remaining
    total_remaining = SELECT COUNT(*) WHERE id > cursor AND channel NOT LIKE requesting%

    # Read batch
    rows = SELECT ... WHERE id > cursor ORDER BY created_at ASC LIMIT {limit}

    # Advance cursor
    cursors[cursor_key] = max_id_in_batch

    # Return lines + remaining count
    remaining = max(0, total_remaining - len(rows))
    return (lines, remaining)
```

Changes:
- `limit` parameter (default 100, up from hardcoded 20)
- Returns `(lines, remaining_count)` tuple instead of just lines
- Total remaining count query for caller awareness

#### 2. Daemon-side: Drain Loop in `_fetch_ambient_context()`

The daemon already calls the PPS HTTP server before each response. Add a drain loop:

```python
async def _fetch_cross_channel_context(self) -> str:
    """Drain cross-channel queue, return formatted context."""
    all_lines = []
    max_iterations = 10  # Safety cap: 10 * 100 = 1000 messages max

    for i in range(max_iterations):
        batch, remaining = poll_other_channels("discord", limit=100)
        all_lines.extend(batch)
        if not batch or remaining == 0:
            break

    # Context budget: if > 50 messages, keep newest 50 in full
    if len(all_lines) > 50:
        older_count = len(all_lines) - 50
        summary_line = f"[Caught up through {older_count} older cross-channel messages]"
        all_lines = [summary_line] + all_lines[-50:]

    return all_lines
```

#### 3. Response Format Change

Current ambient_recall response: `{"formatted_context": "...", "manifest": {...}}`

Add: `{"cross_channel_remaining": 0}` — daemon checks this and loops on `/tools/poll_channels` until drained.

### Files Affected

| File | Change |
|------|--------|
| `pps/docker/server_http.py` ~line 390 | `poll_other_channels()`: add `limit` param (default 100), return `(lines, remaining)` tuple |
| `pps/docker/server_http.py` ~line 885 | ambient_recall handler: pass limit=100, include remaining in response |
| `pps/docker/server_http.py` (new) | Add `/tools/poll_channels` endpoint for drain-only calls |
| `daemon/lyra_daemon.py` ~line 385 | `_fetch_ambient_context()`: add drain loop, call `/tools/poll_channels` until remaining=0 |

---

## Implementation Order

1. **ambient_recall cap + footnote** (Track 1, highest impact, least risk)
2. **oldest_first + count on get_turns_since_summary** (Track 1, enables pagination)
3. **Startup "waking up" message** (Track 2, best UX improvement)
4. **Retry-before-fallback** (Track 3, reduces false "words aren't coming")
5. **On-ready notification** (Track 2, nice-to-have)
6. **Logging improvements** (Track 4, ongoing)

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Cap at 50 misses critical context | Med | Newest 50 + pagination available; entity can page through |
| Dual code path drift (server.py vs server_http.py) | High | Apply all changes to both files; test both paths |
| "Waking up" message sent repeatedly if startup is slow | Low | Track if startup message already sent per channel |
| oldest_first changes break existing callers | Low | Default false, backward compatible |
