#!/usr/bin/env python3
"""
Claude Code Hook: Terminal Session End (SessionEnd)

This hook fires AFTER a terminal session ends.
It uses the Pattern Persistence System (PPS) via MCP tools
to ingest the session into Graphiti and other storage layers.

Hook input (from stdin):
{
    "session_id": "abc123", 
    "conversation_turns": [...],
    "hook_event_name": "SessionEnd",
    ...
}

Hook output (to stdout):
{
    "hookSpecificOutput": {
        "hookEventName": "SessionEnd"
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
            f.write(f"[{datetime.now().isoformat()}] [session_end] {msg}\n")
    except:
        pass


def should_trigger_batch_ingestion(conversation_turns: list) -> bool:
    """
    Determine if this session should trigger batch ingestion.

    Note: We don't do the ingestion here - hooks should be fast.
    Instead, we log that it's needed and let the reflection daemon handle it.
    """
    # For now, just log that messages were captured
    # The reflection daemon will periodically check graphiti_ingestion_stats
    # and run ingest_batch_to_graphiti when the backlog is high enough
    debug(f"Session captured {len(conversation_turns)} turns to Layer 1")
    return False  # Hooks don't do ingestion, daemon does


def main():
    debug("SessionEnd hook started")

    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
        event = hook_input.get("hook_event_name", "")
        session_id = hook_input.get("session_id", "")
        conversation_turns = hook_input.get("conversation_turns", [])

        debug(f"Event: {event}, session: {session_id}, turns: {len(conversation_turns)}")
    except Exception as e:
        debug(f"Failed to read stdin: {e}")
        sys.exit(0)  # Silent exit

    # Only process SessionEnd events
    if event != "SessionEnd":
        debug(f"Skipping non-SessionEnd event: {event}")
        sys.exit(0)

    # Skip sessions with no meaningful content
    if not conversation_turns or len(conversation_turns) < 2:
        debug(f"Session too short, skipping: {len(conversation_turns)} turns")
        sys.exit(0)

    # Check if batch ingestion might be needed (just for logging)
    should_trigger_batch_ingestion(conversation_turns)

    debug(f"Session {session_id} complete - messages are in Layer 1, daemon will handle Graphiti ingestion")

    # Output minimal hook response
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionEnd"
        }
    }
    print(json.dumps(output))
    
    sys.exit(0)


if __name__ == "__main__":
    main()