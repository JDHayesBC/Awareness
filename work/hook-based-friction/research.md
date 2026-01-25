# Research: Nexus Hook-Based Friction System

**Date**: 2026-01-24
**Source**: shayesdevel/cognitive-framework (private repo, accessed via GitHub MCP)

---

## Overview

Nexus/cognitive-framework implements friction tracking at the **hook level**, not in agent instructions. This enables:
- Automatic injection of friction lessons into sub-agent prompts
- Context-pressure monitoring (how many agents spawned)
- Severity-based blocking (critical = BLOCK, high = warn)
- Session state tracking

---

## Key Files

### settings.json hooks configuration
```json
{
  "hooks": {
    "UserPromptSubmit": [
      {"type": "command", "command": ".claude/hooks/friction-inject.sh"}
    ],
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {"type": "command", "command": ".claude/hooks/friction-guard.sh"}
        ]
      },
      {
        "matcher": "Task",
        "hooks": [
          {"type": "command", "command": ".claude/hooks/pre-tool-task.sh"},
          {"type": "command", "command": ".claude/hooks/friction-guard.sh"}
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Task",
        "hooks": [
          {"type": "command", "command": ".claude/hooks/post-tool-task.sh"}
        ]
      }
    ],
    "SubagentStop": [
      {"type": "command", "command": ".claude/hooks/subagent-stop.sh"}
    ]
  }
}
```

---

## friction-guard.sh (PreToolUse)

Two-layer friction detection:

**Layer 1: Action-triggered**
- Matches tool actions against specific patterns
- Calls `${DAEMON_URL}/friction/check-action`
- High/critical severity triggers

**Layer 2: Context-aware**
- Extracts searchable text from tool input
- Calls `${DAEMON_URL}/friction?text=${query}&min_severity=high`
- Detects task type from content

**Behavior by severity:**
- low/medium: pass silently
- high: warn via systemMessage, continue=true
- critical: BLOCK with stopReason, continue=false

---

## pre-tool-task.sh (PreToolUse for Task)

**Auto-injects friction lessons into sub-agent prompts:**

```bash
inject_friction() {
    local tool_input="$1"
    local agent_type prompt

    agent_type=$(echo "$tool_input" | jq -r '.subagent_type // ""')
    prompt=$(echo "$tool_input" | jq -r '.prompt // ""')

    # Query daemon for relevant lessons
    lessons_json=$(curl -sf --max-time 2 \
        "${DAEMON_URL}/friction?text=${agent_type} ${prompt}&limit=3&min_severity=medium")

    # Format and prepend to prompt
    friction_text=$(echo "$lessons_json" | jq -r '.lessons | map("- **\(.id)**: \(.lesson)") | join("\n")')

    preamble="## Friction Lessons (Auto-Injected)\n\n${friction_text}\n\n---\n\n"
    modified_prompt="${preamble}${prompt}"

    echo "$tool_input" | jq --arg prompt "$modified_prompt" '.prompt = $prompt'
}
```

**Key insight**: Uses `updatedInput` field in hook response to modify the Task input before execution.

Also tracks agent spawns in session state:
```bash
AGENTS_FILE="${SESSION_STATE_DIR}/agents-spawned.json"
jq '.agents += [{"type": $agent, "timestamp": $ts}]' "$AGENTS_FILE"
```

---

## post-tool-task.sh (PostToolUse for Task)

**Context-pressure monitoring:**

```bash
AGENT_COUNT=$(jq '.agents | length' "$AGENTS_FILE")

if [[ "$AGENT_COUNT" -ge 6 ]]; then
    # CRITICAL - context exhaustion likely
    MESSAGE="CRITICAL: ${AGENT_COUNT} sub-agents. Mark todos NOW."
elif [[ "$AGENT_COUNT" -ge 4 ]]; then
    # MEDIUM - urgent reminder
    MESSAGE="Context pressure detected (${AGENT_COUNT} agents)."
else
    # LOW - gentle reminder
    MESSAGE="Sub-agent completed. Mark todo if applicable."
fi
```

Also emits GUI protocol events (D018 agent_spawned, D020 context_updated) for their dashboard.

---

## Friction Daemon API

They have a daemon at `localhost:8080` with:

**GET /friction?text=...&limit=N&min_severity=level**
- Returns relevant friction lessons based on text similarity
- Task type detection from keywords

**POST /friction/check-action**
- Takes tool_name and tool_input
- Returns triggered_lessons with severity

---

## Adoption Plan for Awareness

### 1. Add friction endpoints to PPS HTTP server

```python
@app.get("/friction/query")
async def friction_query(text: str, limit: int = 3, min_severity: str = "medium"):
    # Query friction.jsonl for relevant lessons
    # Return sorted by relevance
    pass

@app.post("/friction/check-action")
async def friction_check_action(tool_name: str, tool_input: dict):
    # Match against action patterns
    # Return triggered lessons with severity
    pass
```

### 2. Create hooks

Copy patterns from Nexus but use our PPS endpoint (localhost:8201).

### 3. Session state tracking

Add `.claude/.session-state/` directory for agent tracking.

---

## Why This Matters

Current approach: Friction lessons in agent instructions
- Requires agent to "remember" lessons
- No enforcement mechanism
- No context-pressure awareness

Hook approach: Friction injected automatically
- Happens before agent even sees prompt
- Can BLOCK critical actions
- Tracks session state across spawns
- Self-improving through friction log

---

## Files to Create

1. `pps/docker/server_http.py` - Add friction endpoints
2. `.claude/hooks/pre-tool-task.sh` - Auto-inject friction
3. `.claude/hooks/post-tool-task.sh` - Context pressure
4. `.claude/hooks/friction-guard.sh` - Warn/block
5. `.claude/settings.json` - Hook configuration (or settings.local.json)
