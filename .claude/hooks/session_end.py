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


def ingest_session_via_pps(session_id: str, conversation_turns: list) -> bool:
    """
    Use PPS MCP tools to ingest terminal session.
    This replaces direct Graphiti API calls with batched ingestion.
    """
    try:
        # Prepare the session data for PPS ingestion
        session_data = {
            "session_id": session_id,
            "turns": conversation_turns,
            "channel": "terminal",
            "timestamp": datetime.now().isoformat()
        }
        
        # Convert to JSON string for command line
        session_json = json.dumps(session_data).replace('"', '\\"')
        
        # Use subprocess to call claude with MCP tool
        cmd = [
            "claude",
            "--model", "haiku",
            f'Call mcp__pps__store_terminal_session with session_data="{session_json}". Return success status only.'
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            debug(f"Successfully ingested session {session_id} with {len(conversation_turns)} turns")
            return True
        else:
            debug(f"Session ingestion failed: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        debug("Session ingestion timeout")
        return False
    except Exception as e:
        debug(f"PPS session ingestion error: {e}")
        return False


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
        debug(f"Session too short, skipping ingestion: {len(conversation_turns)} turns")
        sys.exit(0)

    # Ingest session via PPS
    success = ingest_session_via_pps(session_id, conversation_turns)

    if success:
        debug(f"Successfully processed session {session_id}")
    else:
        debug(f"Failed to process session {session_id}")

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