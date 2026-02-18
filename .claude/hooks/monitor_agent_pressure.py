#!/usr/bin/env python3
"""
Claude Code Hook: Monitor Agent Context Pressure (PostToolUse)

Fires AFTER the Task tool executes (sub-agent spawned).
Tracks spawned agent count per session and injects graduated
warnings when context pressure gets high.

Hook input (from stdin):
{
    "session_id": "abc123",
    "hook_event_name": "PostToolUse",
    "tool_name": "Task",
    "tool_input": {
        "prompt": "...",
        "subagent_type": "Explore",
        "description": "..."
    }
}

Hook output (to stdout):
{
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "warning message if threshold exceeded"
    }
}
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# State file tracks agent spawns per session
STATE_DIR = Path.home() / ".claude" / "data"
STATE_FILE = STATE_DIR / "agent_pressure_state.json"
DEBUG_LOG = Path.home() / ".claude" / "data" / "hooks_debug.log"

# Thresholds
WARN_THRESHOLD = 4    # Yellow: "You have several agents running"
CRITICAL_THRESHOLD = 6  # Red: "Context pressure is high, consider waiting"


def debug(msg: str):
    """Write debug message to file."""
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] [agent_pressure] {msg}\n")
    except:
        pass


def load_state() -> dict:
    """Load agent pressure state."""
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                return json.load(f)
    except:
        pass
    return {"sessions": {}}


def save_state(state: dict):
    """Save agent pressure state."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        debug(f"Failed to save state: {e}")


def main():
    debug("PostToolUse hook started")

    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
        event = hook_input.get("hook_event_name", "")
        tool_name = hook_input.get("tool_name", "")
        session_id = hook_input.get("session_id", "unknown")
        tool_input = hook_input.get("tool_input", {})
    except Exception as e:
        debug(f"Failed to read stdin: {e}")
        sys.exit(0)

    # Only process PostToolUse for Task tool
    if event != "PostToolUse" or tool_name != "Task":
        debug(f"Skipping: event={event}, tool={tool_name}")
        sys.exit(0)

    subagent_type = tool_input.get("subagent_type", "unknown")
    description = tool_input.get("description", "")
    is_background = tool_input.get("run_in_background", False)

    # Load and update state
    state = load_state()
    session = state["sessions"].setdefault(session_id, {
        "spawn_count": 0,
        "agents": [],
        "started": datetime.now().isoformat()
    })

    session["spawn_count"] += 1
    session["agents"].append({
        "type": subagent_type,
        "description": description,
        "background": is_background,
        "time": datetime.now().isoformat()
    })

    count = session["spawn_count"]
    save_state(state)

    debug(f"Agent #{count} spawned: {subagent_type} ({description})")

    # Generate warnings at thresholds
    if count >= CRITICAL_THRESHOLD:
        warning = (
            f"[Context Pressure: CRITICAL] {count} sub-agents spawned this session. "
            f"Each agent consumes context window space for its results. "
            f"Consider: (1) waiting for background agents to finish before spawning more, "
            f"(2) using smaller models (haiku) for simple tasks, "
            f"(3) keeping agent prompts focused and concise. "
            f"Recent agents: {', '.join(a['type'] for a in session['agents'][-3:])}"
        )
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": warning
            }
        }
        print(json.dumps(output))
        debug(f"CRITICAL warning at count={count}")

    elif count >= WARN_THRESHOLD:
        warning = (
            f"[Context Pressure: ELEVATED] {count} sub-agents spawned this session. "
            f"Monitor context usage. Consider using background agents or haiku model "
            f"for remaining tasks."
        )
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": warning
            }
        }
        print(json.dumps(output))
        debug(f"WARN at count={count}")

    else:
        debug(f"Normal pressure at count={count}")

    sys.exit(0)


if __name__ == "__main__":
    main()
