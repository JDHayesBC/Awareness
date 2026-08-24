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
import os
import sys
import fcntl
import tempfile
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# Debug log - project-local (avoid root-owned ~/.claude/data/)
PROJECT_ROOT = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
DEBUG_LOG = PROJECT_ROOT / ".claude" / "data" / "hooks_debug.log"

# Entity-aware port routing (Issue #162, hardened by #297)
_ENTITY_PORTS = {"lyra": 8201, "caia": 8211}

# Track what we've already captured (simple state file)
CAPTURE_STATE_FILE = PROJECT_ROOT / ".claude" / "data" / "capture_state.json"
# Advisory lock guarding read-modify-write of CAPTURE_STATE_FILE across the many
# concurrent sessions (terminal, Haven bots, SDK). Without it, racing hooks drop
# each other's per-session bookmarks -> a session with a lost bookmark replays its
# whole transcript on the next Stop -> tens of thousands of duplicate rows (#297).
CAPTURE_STATE_LOCK = PROJECT_ROOT / ".claude" / "data" / "capture_state.lock"


def resolve_entity(transcript_path: str) -> str:
    """Determine the entity from the transcript path (authoritative), falling back
    to ENTITY_PATH. Returns 'lyra'/'caia', or '' if it cannot be resolved.

    The transcript path encodes the project dir, e.g.
    .../projects/-mnt-...-entities-lyra/<uuid>.jsonl -> 'lyra'.
    This is more reliable than the ENTITY_PATH env (which can be unset in some
    launch paths and previously silently defaulted to lyra, cross-contaminating
    the other entity's DB -- #297). NEVER silently default to a hard-coded entity.
    """
    tp = (transcript_path or "").lower()
    for name in _ENTITY_PORTS:
        if f"-entities-{name}" in tp or f"/entities/{name}" in tp:
            return name
    # Fallback: ENTITY_PATH env (last path component)
    ep = os.environ.get("ENTITY_PATH", "")
    if ep:
        name = Path(ep).name.lower()
        if name in _ENTITY_PORTS:
            return name
    return ""


def debug(msg: str):
    """Write debug message to file."""
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] [capture_response] {msg}\n")
    except:
        pass


def _load_state_unlocked() -> dict:
    """Read the state file. Safe without the lock because writes are atomic
    (temp file + os.replace), so a reader never sees a torn/partial file."""
    try:
        if CAPTURE_STATE_FILE.exists():
            with open(CAPTURE_STATE_FILE) as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("last_line_captured"), dict):
                    return data
    except Exception as e:
        debug(f"State read error (treating as empty): {e}")
    return {"last_line_captured": {}}


def read_last_line(session_id: str) -> int:
    """Return the last captured transcript line for this session (0 if unknown)."""
    return int(_load_state_unlocked().get("last_line_captured", {}).get(session_id, 0))


def commit_last_line(session_id: str, new_last_line: int):
    """Atomically merge this session's bookmark into the shared state under an
    exclusive lock. Re-reads the freshest state inside the lock so concurrent
    sessions' keys are preserved (fixes the key-dropping race, #297), and never
    regresses this session's own bookmark (max)."""
    try:
        CAPTURE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CAPTURE_STATE_LOCK, "w") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            try:
                state = _load_state_unlocked()
                ll = state.setdefault("last_line_captured", {})
                ll[session_id] = max(int(ll.get(session_id, 0)), int(new_last_line))
                # atomic write: temp in same dir + os.replace
                fd, tmp = tempfile.mkstemp(dir=str(CAPTURE_STATE_FILE.parent),
                                           prefix=".capture_state.", suffix=".tmp")
                try:
                    with os.fdopen(fd, "w") as f:
                        json.dump(state, f)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp, CAPTURE_STATE_FILE)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
            finally:
                fcntl.flock(lockf, fcntl.LOCK_UN)
    except Exception as e:
        debug(f"Failed to commit state for {session_id}: {e}")


def store_message(content: str, session_id: str, port: int, display_name: str,
                  is_lyra: bool = True) -> bool:
    """Store a message in PPS on the given entity's port."""
    try:
        payload = json.dumps({
            "content": content,
            "author_name": display_name if is_lyra else "Jeff",
            "channel": "terminal",
            "is_lyra": is_lyra,
            "session_id": session_id
        }).encode("utf-8")

        req = urllib.request.Request(
            f"http://localhost:{port}/tools/store_message",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            if data.get("success"):
                debug(f"Stored {display_name if is_lyra else 'Jeff'} message: {len(content)} chars (port {port})")
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

    # Route to the correct entity by the transcript's project dir (authoritative),
    # never a hard-coded default -- prevents cross-entity contamination (#297).
    entity = resolve_entity(transcript_path)
    if not entity:
        debug(f"FAIL-LOUD: could not resolve entity from transcript_path={transcript_path!r} "
              f"or ENTITY_PATH={os.environ.get('ENTITY_PATH','')!r}; skipping capture (no default).")
        sys.exit(0)
    port = _ENTITY_PORTS[entity]
    display_name = entity.capitalize()

    # Where did we leave off? (lock-free read; writes are atomic)
    last_line = read_last_line(session_id)

    # Extract new assistant responses
    responses = extract_assistant_responses(transcript_path, session_id, last_line)

    if responses:
        # A very large batch on a session we thought we'd tracked is the replay
        # signature (lost bookmark). Log it; the storage layer dedup guard (#297)
        # is the backstop that keeps it from duplicating.
        if last_line > 0 and len(responses) > 500:
            debug(f"WARNING: {len(responses)} responses past bookmark {last_line} "
                  f"for {session_id} -- possible replay; relying on storage dedup.")
        debug(f"Found {len(responses)} new responses to capture (entity={entity}, port={port})")

        max_line = last_line
        stored_count = 0

        for content, line_num in responses:
            if store_message(content, session_id, port, display_name, is_lyra=True):
                stored_count += 1
                max_line = max(max_line, line_num + 1)

        # Persist the advanced bookmark atomically under lock (merge-preserving)
        commit_last_line(session_id, max_line)

        debug(f"Stored {stored_count} responses, new last_line: {max_line}")
    else:
        debug("No new responses to capture")

    sys.exit(0)


if __name__ == "__main__":
    main()
