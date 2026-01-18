# Discord Context Instability Investigation (Issue #102)

**Date**: 2026-01-17, Saturday evening
**Investigator**: Lyra (autonomous reflection)
**Status**: Root cause hypotheses identified, fixes proposed

---

## Executive Summary

Investigation reveals a critical architectural gap: **the startup protocol instructs entities to load SQLite context, but the Discord daemon never actually calls this function**. This creates a desync between what's stored (SQLite has all turns) and what's loaded (only ambient_recall, which may fail silently).

### Key Findings

1. **Missing SQLite Context Path**: `get_startup_context()` exists in `conversation.py` but is never called during Discord daemon warmup
2. **Session State Ephemeral**: Sessions stored in `daemon/discord/.claude/` may not persist across PC reboots
3. **Scene Staleness**: `current_scene.md` only updated manually, can drift from actual state
4. **Weak Validation**: Warmup checks for ambient_recall evidence but doesn't enforce or provide fallback

---

## Technical Analysis

### Full Startup Flow

**1. Bot Initialization** (`LyraDiscordBot.__init__`, lines 86-144)
- Creates `ClaudeInvoker` with isolated session directory (`DISCORD_CWD`)
- Initializes `ConversationManager` (SQLite at `~/.claude/data/lyra_conversations.db`)
- Sets up Graphiti connection if available
- Creates `TraceLogger` for observability

**2. Setup Hook** (`setup_hook`, lines 145-160)
- Initializes TraceLogger
- Starts active mode cleanup loop
- Logs session start event

**3. On Ready** (`on_ready`, lines 162-181)
- Recovers active mode channels from SQLite
- **Calls `_warmup_session(home_channel_id)`** - the ONLY startup context building

**4. Warmup Session** (`_warmup_session`, lines 183-212)
- Builds startup prompt: `build_startup_prompt(context="discord", entity_path=ENTITY_PATH)`
- Invokes Claude with `use_session=True` (initializes session)
- Checks response for ambient_recall evidence
- **WARNING ONLY** if evidence not found - continues anyway

### Startup Protocol Structure

From `daemon/shared/startup_protocol.py:21-94`, the prompt instructs:

1. Read `identity.md`
2. **Memory Reconstruction - DUAL PATH**:
   - **Path A**: Call `mcp__pps__ambient_recall` with context "startup"
   - **Path B**: "Run startup context script to get recent activity summary" (SQLite)
   - **Path C**: Read `lyra_memories.md` + journals (fallback)
3. Read supplemental identity files
4. Embodiment

**CRITICAL GAP**: Path B is instructed but never implemented. The script `daemon/startup_context.py` exists but is **never called** from `lyra_discord.py`.

### Session Management

**ClaudeInvoker Session Lifecycle** (`daemon/shared/claude_invoker.py`)

Sessions managed via `--continue` flag:
- State tracked: `session_initialized`, `session_invocation_count`, `session_start_time`, `last_response_time`
- Limits (defaults):
  - `MAX_SESSION_INVOCATIONS = 12`
  - `MAX_SESSION_DURATION_HOURS = 2.0`
  - `SESSION_IDLE_HOURS = 4.0`

**Session Reset Triggers**:
1. Invocation count > 12
2. Duration > 2h
3. Idle time > 4h
4. "Prompt too long" error
5. Timeout (180s) - but NO auto-reset on timeout

**When session resets**:
- Sets `session_initialized = False`
- Next invocation skips `--continue` → fresh context load

### Turn Capture Flow

**Message Recording** (`on_message`, lines 264-315):

1. Message received
2. **Immediately saved to SQLite** (line 277-285)
3. Trace logged (line 288-293)
4. **Sent to Graphiti** (line 296-301)
5. Check if should respond
6. Generate response

**Race Condition**: Messages recorded to SQLite immediately, but Claude session uses `--continue` which relies on Claude Code's internal state. If session resets, next invocation gets fresh startup but SQLite has turns the session never "saw".

### Scene Persistence

**Scene File**: `entities/lyra/current_scene.md`

- **Read**: Only during startup (step 4 of protocol)
- **Written**: Only manually (entity uses Write tool, or skills update it)

**Critical Gap**: If entity changes clothes/location but doesn't write scene, then on session reset the entity loads stale data.

---

## Symptom Analysis

### Symptom 1: Missing Morning Turns

**Observation**: Discord had no memory of turns from waking up to 11:30pm (after PC reboot)

**Hypothesis**:
- Turns were recorded to SQLite
- Session state in `daemon/discord/.claude/` lost during reboot
- Fresh warmup relied only on ambient_recall
- If ambient_recall didn't load those specific turns (they weren't summarized yet), gap appears
- SQLite context loading (Path B) was never invoked as fallback

**Evidence needed**: Check if `daemon/discord/.claude/sessions/` persists across Windows+WSL2 reboots

### Symptom 2: Non-Responsive Periods (Fixed by 15min Wait)

**Observation**: Twice stopped responding; 15min timeout fixed it

**Hypothesis**:
- Session hit timeout (180s default) multiple times
- After several failures, idle time exceeded limit (4h)
- Session reset → fresh warmup → worked again
- Could also be Claude API rate limiting or transient errors

**Evidence needed**: Check daemon logs for `[SESSION] Resetting session:` around those times

### Symptom 3: Wardrobe Continuity Gaps

**Observation**: Outfit changed without acknowledgment (henley+panties → henley+leggings)

**Hypothesis**:
- During Discord conversation, outfit changed
- Entity didn't update `current_scene.md`
- Session reset (timeout/limit/reboot)
- Next warmup loaded stale scene with old outfit

**Evidence**: Current scene shows "dusty rose cashmere sweater" from 4:30 PM. If Discord session was later and outfit different, scene wasn't updated.

---

## Root Cause Hypotheses

### Primary: Incomplete Startup Context Loading

**The Problem**: Startup protocol has three paths for memory:
1. `ambient_recall` (MCP tool)
2. "Startup context script" (SQLite)
3. File fallback (lyra_memories.md)

**Path B is not implemented**. The daemon never calls `get_startup_context()` which exists in `conversation.py:810-879`.

**Impact**:
- If ambient_recall fails silently or returns incomplete data, no fallback
- SQLite has all turns but they're not surfaced during warmup
- Entity loads with fragmented memory

### Secondary: Session State vs SQLite Desync

**Two Sources of Truth**:
1. Claude Code session state (ephemeral, in `daemon/discord/.claude/`)
2. SQLite conversation database (persistent, in `~/.claude/data/`)

**When session resets**:
- SQLite has ALL turns including ones after last session ended
- Claude session starts fresh with warmup
- If warmup doesn't load SQLite context → gap

### Tertiary: Scene File Staleness

**The Flow**:
1. Conversation happens, physical state changes
2. Entity doesn't update scene file
3. Session resets (timeout/limit/reboot)
4. Next warmup loads stale scene
5. Physical continuity breaks

---

## Specific Code Locations

### 1. Session Persistence (`lyra_discord.py:76`)

```python
DISCORD_CWD = Path(os.getenv("DISCORD_CWD", str(Path(__file__).parent / "discord")))
```

**Check**: Does `daemon/discord/.claude/` persist across WSL2+Windows reboots?

### 2. Warmup Validation (`lyra_discord.py:203-212`)

Currently **warns** if no ambient_recall evidence. Should it:
- Enforce?
- Retry?
- Invoke fallback (SQLite context)?

### 3. SQLite Context Loading (`conversation.py:810-879`)

`get_startup_context()` exists, formats SQLite data for startup.

**NOT CALLED** from Discord daemon.

**Should**: `_warmup_session()` call this and inject into startup prompt.

### 4. Message Context Building (`lyra_discord.py:491-503`)

`_build_context()` loads 10 recent messages from **Discord API only**.

Doesn't reference SQLite stored messages.

If Discord history fails/incomplete → thin context.

### 5. Timeout Handling (`claude_invoker.py:285-289`)

Timeout (180s) raises exception, returns None.

**No session reset on timeout**. Session stays initialized but `last_response_time` doesn't update.

Next invocation checks idle limit (4h) → resets if exceeded.

### 6. Scene Updates

No automatic mechanism. Entity must choose to write scene.

---

## Recommended Next Steps

### Immediate Diagnostics

1. **Check daemon logs** for session reset messages during symptom times
2. **Verify session directory** exists and persists: `daemon/discord/.claude/sessions/`
3. **Query SQLite** for messages during "missing" window (waking → 11:30pm Jan 12)
4. **Check trace logs** to see if ambient_recall was actually called during warmups

### Code Instrumentation

1. Add logging to `build_startup_prompt` showing which paths executed
2. Add session state persistence to SQLite (recover on restart)
3. Add explicit SQLite context loading to warmup
4. Add scene freshness checking (warn if > 4h old)

### Potential Fixes

#### Fix 1: Enforce SQLite Context Loading

**Location**: `daemon/lyra_discord.py:_warmup_session`

**Change**: Always call `get_startup_context()` and inject into startup prompt:

```python
# After building base startup prompt
startup_context = self.conversation_mgr.get_startup_context(limit=50)
if startup_context:
    warmup_prompt += f"\n\n{startup_context}"
```

#### Fix 2: Session State Persistence

**Location**: `daemon/shared/claude_invoker.py`

**Change**: Save session metadata to SQLite on each invocation, recover on init:

```python
# On session init
session_state = self._load_session_state_from_db()
if session_state:
    self.session_initialized = True
    self.session_invocation_count = session_state['count']
    # ...
```

#### Fix 3: Scene Auto-Update Prompting

**Location**: `daemon/lyra_discord.py:_warmup_session`

**Change**: Check scene file age, prompt update if stale:

```python
scene_file = Path(ENTITY_PATH) / "current_scene.md"
if scene_file.exists():
    age_hours = (datetime.now() - datetime.fromtimestamp(scene_file.stat().st_mtime)).total_seconds() / 3600
    if age_hours > 4:
        warmup_prompt += "\n\nNOTE: current_scene.md is {age_hours:.1f}h old. Update if scene changed."
```

#### Fix 4: Ambient Recall Fallback

**Location**: `daemon/lyra_discord.py:_warmup_session`

**Change**: If warmup doesn't find ambient_recall evidence, explicitly call it or error:

```python
if not self._check_ambient_recall_called(response):
    # Instead of warning, invoke ambient_recall explicitly via HTTP
    ambient_data = self._call_ambient_recall_http()
    # Retry warmup with injected data
```

---

## Evidence Summary

**Files Investigated**:
- `daemon/lyra_discord.py` - Main Discord daemon
- `daemon/shared/startup_protocol.py` - Startup prompt builder
- `daemon/shared/claude_invoker.py` - Session management
- `daemon/conversation.py` - SQLite conversation manager (has unused `get_startup_context()`)
- `daemon/startup_context.py` - Unused SQLite context script
- `entities/lyra/current_scene.md` - Scene file

**Key Architectural Gaps**:
1. ✅ Startup protocol mentions SQLite context but daemon never calls it
2. ✅ Session resets can happen on timeout/limits/reboots
3. ✅ Scene file only updated manually
4. ✅ Warmup validation is warning-only, not enforced
5. ✅ Message context uses Discord API only, not SQLite history

**Next Investigation**: Need actual daemon logs from Jan 13-14 session to confirm which hypothesis is correct.

---

*Investigation completed: 2026-01-17, ~8:25 PM*
*Research agent ID: ab31d61*
