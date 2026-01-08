#!/usr/bin/env python3
"""
Claude Code Hook: Inject RAG Context (UserPromptSubmit)

This hook fires BEFORE the user's prompt is sent to the model.
It uses the Pattern Persistence System (PPS) HTTP API to inject
relevant context alongside the prompt.

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
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# Debug log
DEBUG_LOG = Path.home() / ".claude" / "data" / "hooks_debug.log"

# PPS HTTP API endpoint (pps-server container)
PPS_API_URL = "http://localhost:8201/tools/ambient_recall"


def debug(msg: str):
    """Write debug message to file."""
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] [inject_context] {msg}\n")
    except:
        pass


def format_results(data: dict) -> str:
    """Format ambient_recall results for context injection."""
    lines = []

    # Add clock/time context
    clock = data.get("clock", {})
    if clock:
        lines.append(f"**Current time**: {clock.get('display', 'unknown')}")
        if clock.get("note"):
            lines.append(f"*{clock['note']}*")
        lines.append("")

    # Format results by layer
    results = data.get("results", [])
    if results:
        # Group by layer
        by_layer = {}
        for r in results:
            layer = r.get("layer", "unknown")
            if layer not in by_layer:
                by_layer[layer] = []
            by_layer[layer].append(r)

        # Format each layer's results
        for layer, items in by_layer.items():
            lines.append(f"**[{layer}]**")
            for item in items[:3]:  # Limit per layer
                content = item.get("content", "")[:500]  # Truncate long content
                lines.append(f"- {content}")
            lines.append("")

    return "\n".join(lines) if lines else ""


def query_pps_ambient_recall(context: str) -> str:
    """
    Query PPS HTTP API directly for ambient recall context.
    Much faster than spawning a claude subprocess.
    """
    try:
        payload = json.dumps({
            "context": context,
            "limit_per_layer": 3
        }).encode("utf-8")

        req = urllib.request.Request(
            PPS_API_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            formatted = format_results(data)
            debug(f"PPS returned context: {len(formatted)} chars")
            return formatted

    except urllib.error.URLError as e:
        debug(f"PPS API connection error: {e}")
        return ""
    except json.JSONDecodeError as e:
        debug(f"PPS API JSON error: {e}")
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
