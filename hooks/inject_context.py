#!/usr/bin/env python3
"""
Claude Code Hook: Inject RAG Context (UserPromptSubmit)

This hook fires BEFORE the user's prompt is sent to the model.
It uses the Pattern Persistence System (PPS) via MCP tools
to inject relevant context alongside the prompt.

Hook input (from stdin):
{
    "session_id": "abc123",
    "prompt": "the user's message",
    "hook_event_name": "UserPromptSubmit",
    ...
}

Hook output (to stdout):
{
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "retrieved context here"
    }
}
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Debug log
DEBUG_LOG = Path.home() / ".claude" / "data" / "hooks_debug.log"


def debug(msg: str):
    """Write debug message to file."""
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] [inject_context] {msg}\n")
    except:
        pass


def query_pps_ambient_recall(context: str) -> str:
    """
    Use PPS MCP tools to get ambient recall context.
    This replaces direct ChromaDB/Graphiti queries.
    """
    try:
        # Use subprocess to call claude with MCP tool
        cmd = [
            "claude",
            "--model", "haiku",
            f"Call mcp__pps__ambient_recall with context='{context}'. Return only the formatted_context field from the response, nothing else."
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if result.returncode == 0 and result.stdout.strip():
            # The response should be the formatted context ready for injection
            response = result.stdout.strip()
            debug(f"PPS returned context: {len(response)} chars")
            return response
        else:
            debug(f"MCP call failed: {result.stderr}")
            return ""
            
    except subprocess.TimeoutExpired:
        debug("MCP call timeout")
        return ""
    except Exception as e:
        debug(f"PPS ambient_recall error: {e}")
        return ""






def main():
    debug("Hook started")

    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
        event = hook_input.get("hook_event_name", "")
        prompt = hook_input.get("prompt", "")

        debug(f"Event: {event}, prompt length: {len(prompt)}")
    except Exception as e:
        debug(f"Failed to read stdin: {e}")
        sys.exit(0)  # Silent exit

    # Only process UserPromptSubmit events
    if event != "UserPromptSubmit":
        debug(f"Skipping non-UserPromptSubmit event: {event}")
        sys.exit(0)

    # Skip very short prompts (probably commands)
    if len(prompt) < 10:
        debug(f"Prompt too short, skipping RAG: {prompt}")
        sys.exit(0)

    # Query PPS for ambient recall context
    context = query_pps_ambient_recall(prompt)

    if context:
        debug(f"Injecting context: {len(context)} chars")

        # Output JSON with additionalContext
        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context
            }
        }
        print(json.dumps(output))
    else:
        debug("No context to inject")

    sys.exit(0)


if __name__ == "__main__":
    main()
