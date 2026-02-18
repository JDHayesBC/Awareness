#!/usr/bin/env python3
"""
Claude Code Hook: Inject Entity Context into Sub-Agents (PreToolUse)

Fires BEFORE the Task tool executes (sub-agent spawned).
Queries PPS HTTP API for compact entity context and appends it
to the sub-agent's prompt via updatedInput, so every sub-agent
automatically gets entity awareness without explicit prompt crafting.

Pattern from: shayesdevel/cognitive-framework (Nexus orchestration)
Adapted for: Awareness project (PPS-backed entity context)

Hook input (from stdin):
{
    "session_id": "abc123",
    "hook_event_name": "PreToolUse",
    "tool_name": "Task",
    "tool_input": {
        "prompt": "...",
        "subagent_type": "coder",
        "description": "...",
        "model": "sonnet"
    }
}

Hook output (to stdout):
{
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "updatedInput": {
            "prompt": "original prompt + injected context"
        }
    }
}
"""

import json
import sys
import urllib.request
import urllib.error
import os
from datetime import datetime
from pathlib import Path

# Debug log
DEBUG_LOG = Path.home() / ".claude" / "data" / "hooks_debug.log"

# PPS HTTP API endpoints
PROJECT_ROOT = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
PPS_AGENT_CONTEXT_URL = "http://localhost:8201/context/agent"
PPS_FRICTION_SEARCH_URL = "http://localhost:8201/friction/search"

# Entity authentication token
ENTITY_TOKEN = ""
_entity_path = os.environ.get("ENTITY_PATH", str(PROJECT_ROOT / "entities" / "lyra"))
_token_file = Path(_entity_path) / ".entity_token"
if _token_file.exists():
    ENTITY_TOKEN = _token_file.read_text().strip()

# Agent types that should NOT get context injection
# (e.g., claude-code-guide is a documentation lookup, not a code agent)
SKIP_AGENT_TYPES = {
    "claude-code-guide",
    "statusline-setup",
    "claude-hud",
}


def debug(msg: str):
    """Write debug message to file."""
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] [inject_agent_context] {msg}\n")
    except:
        pass


def get_compact_context() -> str:
    """Query PPS HTTP API for compact agent context."""
    try:
        payload = json.dumps({
            "token": ENTITY_TOKEN
        }).encode("utf-8")

        req = urllib.request.Request(
            PPS_AGENT_CONTEXT_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            context = data.get("compact_context", "")
            debug(f"Got compact context: {len(context)} chars")
            return context

    except urllib.error.URLError as e:
        debug(f"PPS connection error: {e}")
        return ""
    except Exception as e:
        debug(f"Context fetch error: {e}")
        return ""


def get_friction_lessons(task_description: str) -> str:
    """Query PPS for friction lessons relevant to this specific task."""
    try:
        payload = json.dumps({
            "token": ENTITY_TOKEN,
            "query": task_description[:200],  # Truncate long descriptions
            "limit": 3,
            "min_severity": "medium"
        }).encode("utf-8")

        req = urllib.request.Request(
            PPS_FRICTION_SEARCH_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
            results = data.get("results", [])
            if not results:
                return ""

            lines = ["Relevant friction lessons (avoid these known issues):"]
            for r in results:
                lines.append(f"- [{r['severity'].upper()}] {r['lesson']}")

            debug(f"Got {len(results)} friction lessons for task")
            return "\n".join(lines)

    except Exception as e:
        debug(f"Friction search error: {e}")
        return ""


def main():
    debug("PreToolUse hook started")

    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
        event = hook_input.get("hook_event_name", "")
        tool_name = hook_input.get("tool_name", "")
        tool_input = hook_input.get("tool_input", {})
    except Exception as e:
        debug(f"Failed to read stdin: {e}")
        sys.exit(0)

    # Only process PreToolUse for Task tool
    if event != "PreToolUse" or tool_name != "Task":
        debug(f"Skipping: event={event}, tool={tool_name}")
        sys.exit(0)

    subagent_type = tool_input.get("subagent_type", "")
    original_prompt = tool_input.get("prompt", "")
    description = tool_input.get("description", "")

    # Skip certain agent types that don't need entity context
    if subagent_type.lower() in {s.lower() for s in SKIP_AGENT_TYPES}:
        debug(f"Skipping context injection for {subagent_type}")
        sys.exit(0)

    # Get compact context from PPS (includes general friction lessons)
    context = get_compact_context()

    # Get task-specific friction lessons
    task_text = f"{description} {original_prompt[:200]}"
    friction = get_friction_lessons(task_text)

    if not context and not friction:
        debug("No context available, passing through unchanged")
        sys.exit(0)

    # Build injected block
    parts = [original_prompt, "", "---", "[Injected Entity Context — from PPS hook]"]
    if context:
        parts.append(context)
    if friction:
        parts.append("")
        parts.append(friction)
    parts.append("---")

    enhanced_prompt = "\n".join(parts)

    debug(f"Enhanced prompt: {len(original_prompt)} -> {len(enhanced_prompt)} chars for {subagent_type}")

    # Output updated input — pass through ALL original fields plus modified prompt
    # updatedInput replaces the entire tool_input, not a shallow merge
    updated = dict(tool_input)
    updated["prompt"] = enhanced_prompt

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": updated
        }
    }
    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
