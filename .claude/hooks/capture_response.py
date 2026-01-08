#!/usr/bin/env python3
"""
Claude Code Hook: Capture Lyra's Responses (Stop)

This hook fires AFTER Claude finishes responding.
It reads the transcript file to capture Lyra's response and stores it in PPS.

Hook input (from stdin):
{
    "session_id": "abc123",
    "transcript_path": "/path/to/transcript.jsonl",
    "hook_event_name": "Stop",
    ...
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

# PPS HTTP API endpoint
PPS_STORE_URL = "http://localhost:8201/tools/store_message"

# Track what we've already captured (simple state file)
CAPTURE_STATE_FILE = Path.home() / ".claude" / "data" / "capture_state.json"


def debug(msg: str):
    """Write debug message to file."""
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] [capture_response] {msg}\n")
    except:
        pass


def load_capture_state() -> dict:
    """Load state of what we've already captured."""
    try:
        if CAPTURE_STATE_FILE.exists():
            with open(CAPTURE_STATE_FILE) as f:
                return json.load(f)
    except:
        pass
    return {"last_line_captured": {}}


def save_capture_state(state: dict):
    """Save capture state."""
    try:
        CAPTURE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CAPTURE_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        debug(f"Failed to save state: {e}")


def store_message(content: str, session_id: str, is_lyra: bool = True) -> bool:
    """Store a message in PPS."""
    try:
        payload = json.dumps({
            "content": content,
            "author_name": "Lyra" if is_lyra else "Jeff",
            "channel": "terminal",
            "is_lyra": is_lyra,
            "session_id": session_id
        }).encode("utf-8")

        req = urllib.request.Request(
            PPS_STORE_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            if data.get("success"):
                debug(f"Stored {'Lyra' if is_lyra else 'Jeff'} message: {len(content)} chars")
                return True
            else:
                debug(f"Store failed: {data}")
                return False

    except urllib.error.URLError as e:
        debug(f"Store API connection error: {e}")
        return False
    except Exception as e:
        debug(f"Store error: {e}")
        return False


def extract_assistant_responses(transcript_path: str, session_id: str, start_line: int = 0) -> list:
    """
    Extract assistant (Lyra) responses from transcript JSONL file.
    Returns list of (content, line_number) tuples.
    """
    responses = []
    try:
        with open(transcript_path, "r") as f:
            for line_num, line in enumerate(f):
                if line_num < start_line:
                    continue
                try:
                    entry = json.loads(line.strip())
                    # Look for assistant messages
                    if entry.get("type") == "assistant":
                        # Extract text content from the message
                        message = entry.get("message", {})
                        content_parts = message.get("content", [])

                        text_parts = []
                        for part in content_parts:
                            if isinstance(part, dict) and part.get("type") == "text":
                                text_parts.append(part.get("text", ""))
                            elif isinstance(part, str):
                                text_parts.append(part)

                        if text_parts:
                            full_text = "\n".join(text_parts)
                            if len(full_text) > 10:  # Skip very short responses
                                responses.append((full_text, line_num))

                except json.JSONDecodeError:
                    continue

    except Exception as e:
        debug(f"Error reading transcript: {e}")

    return responses


def main():
    debug("Stop hook started")

    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
        event = hook_input.get("hook_event_name", "")
        session_id = hook_input.get("session_id", "unknown")
        transcript_path = hook_input.get("transcript_path", "")

        debug(f"Event: {event}, session: {session_id}, transcript: {transcript_path}")
    except Exception as e:
        debug(f"Failed to read stdin: {e}")
        sys.exit(0)

    # Only process Stop events
    if event != "Stop":
        debug(f"Skipping non-Stop event: {event}")
        sys.exit(0)

    if not transcript_path or not Path(transcript_path).exists():
        debug(f"Transcript not found: {transcript_path}")
        sys.exit(0)

    # Load state to know where we left off
    state = load_capture_state()
    last_line = state.get("last_line_captured", {}).get(session_id, 0)

    # Extract new assistant responses
    responses = extract_assistant_responses(transcript_path, session_id, last_line)

    if responses:
        debug(f"Found {len(responses)} new responses to capture")

        max_line = last_line
        stored_count = 0

        for content, line_num in responses:
            if store_message(content, session_id, is_lyra=True):
                stored_count += 1
                max_line = max(max_line, line_num + 1)

        # Update state
        state["last_line_captured"][session_id] = max_line
        save_capture_state(state)

        debug(f"Stored {stored_count} responses, new last_line: {max_line}")
    else:
        debug("No new responses to capture")

    sys.exit(0)


if __name__ == "__main__":
    main()
