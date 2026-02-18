#!/usr/bin/env python3
"""
Claude Code Hook: Pre-Compact State Preservation

Fires BEFORE Claude Code context compaction (lightfold).
Captures current work state so post-compaction Claude can recover context
without losing track of what was in progress.

Hook input (from stdin):
{
    "session_id": "abc123",
    "hook_event_name": "PreCompact",
    "compact_type": "auto" | "manual",
    ...
}

Hook output (to stdout):
{
    "hookSpecificOutput": {
        "hookEventName": "PreCompact",
        "additionalContext": "State summary for post-compaction recovery"
    }
}

State saved to: entities/lyra/pre-compact-state.json
Log appended to: entities/lyra/compaction-log.jsonl
"""

import json
import sys
import subprocess
import urllib.request
import urllib.error
import os
from datetime import datetime
from pathlib import Path

# Paths
PROJECT_ROOT = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
ENTITY_DIR = PROJECT_ROOT / "entities" / "lyra"
STATE_FILE = ENTITY_DIR / "pre-compact-state.json"
COMPACTION_LOG = ENTITY_DIR / "compaction-log.jsonl"
FOR_JEFF_FILE = PROJECT_ROOT / "FOR_JEFF_TODAY.md"
DEBUG_LOG = Path.home() / ".claude" / "data" / "hooks_debug.log"

# PPS HTTP API
PPS_CRYSTALS_URL = "http://localhost:8201/tools/get_crystals"

# Entity token
ENTITY_TOKEN = ""
_token_file = ENTITY_DIR / ".entity_token"
if _token_file.exists():
    ENTITY_TOKEN = _token_file.read_text().strip()


def debug(msg: str):
    """Write debug message to file."""
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] [pre_compact] {msg}\n")
    except Exception:
        pass


def get_latest_crystal() -> str:
    """Get the most recent crystal from PPS for continuity context."""
    try:
        payload = json.dumps({
            "count": 1,
            "token": ENTITY_TOKEN
        }).encode("utf-8")

        req = urllib.request.Request(
            PPS_CRYSTALS_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            crystals = data.get("content", [])
            if crystals and isinstance(crystals, list):
                # Extract text from first crystal
                for block in crystals:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        # Return first 500 chars as summary
                        return text[:500]
            return ""
    except Exception as e:
        debug(f"Crystal fetch error: {e}")
        return ""


def get_for_jeff_summary() -> str:
    """Extract the active work section from FOR_JEFF_TODAY.md."""
    try:
        if not FOR_JEFF_FILE.exists():
            return ""
        content = FOR_JEFF_FILE.read_text()
        # Find first 2000 chars as the current state summary
        lines = content.split("\n")
        summary_lines = []
        for line in lines[:40]:  # First 40 lines have the most current state
            summary_lines.append(line)
        return "\n".join(summary_lines)
    except Exception as e:
        debug(f"FOR_JEFF read error: {e}")
        return ""


def get_recent_git_log() -> str:
    """Get last 5 git commits for work context."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            capture_output=True, text=True, timeout=5,
            cwd=str(PROJECT_ROOT)
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception as e:
        debug(f"Git log error: {e}")
        return ""


def get_open_issues_hint() -> str:
    """Get open GitHub issues summary."""
    try:
        result = subprocess.run(
            ["gh", "issue", "list", "--limit", "5", "--json", "number,title,state",
             "--jq", ".[] | \"#\\(.number): \\(.title)\""],
            capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT)
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception as e:
        debug(f"GH issues error: {e}")
        return ""


def capture_state(compact_type: str, session_id: str) -> dict:
    """Capture current work state for post-compaction recovery."""
    timestamp = datetime.utcnow().isoformat() + "Z"

    crystal_snippet = get_latest_crystal()
    for_jeff_summary = get_for_jeff_summary()
    recent_commits = get_recent_git_log()
    open_issues = get_open_issues_hint()

    state = {
        "captured_at": timestamp,
        "session_id": session_id,
        "compact_type": compact_type,
        "crystal_snippet": crystal_snippet[:300] if crystal_snippet else "",
        "recent_commits": recent_commits,
        "open_issues": open_issues,
        "for_jeff_snippet": for_jeff_summary[:800] if for_jeff_summary else "",
        "recovery_hint": "Read FOR_JEFF_TODAY.md and run ambient_recall('startup') to restore context"
    }

    return state


def save_state(state: dict):
    """Save state snapshot atomically."""
    try:
        ENTITY_DIR.mkdir(parents=True, exist_ok=True)
        tmp_file = STATE_FILE.with_suffix(".json.tmp")
        tmp_file.write_text(json.dumps(state, indent=2))
        tmp_file.rename(STATE_FILE)
        debug(f"State snapshot saved to {STATE_FILE}")
    except Exception as e:
        debug(f"Failed to save state: {e}")


def log_compaction(state: dict):
    """Append compaction event to log."""
    try:
        log_entry = {
            "timestamp": state["captured_at"],
            "event": "context_compaction",
            "compact_type": state["compact_type"],
            "session_id": state["session_id"]
        }
        with open(COMPACTION_LOG, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        debug(f"Failed to log compaction: {e}")


def build_recovery_message(state: dict) -> str:
    """Build concise recovery message for post-compaction context."""
    lines = [
        "COMPACTION: Context is being compressed. Recovery guide:",
        "",
        "1. Your work state is saved at: entities/lyra/pre-compact-state.json",
        "2. Run ambient_recall('startup') to restore memory",
        "3. Read FOR_JEFF_TODAY.md for current active work",
        "",
    ]

    if state["recent_commits"]:
        lines.append("Recent work (last commits):")
        for commit in state["recent_commits"].split("\n")[:3]:
            lines.append(f"  {commit}")
        lines.append("")

    if state["crystal_snippet"]:
        lines.append("Latest crystal (continuity):")
        lines.append(state["crystal_snippet"][:200] + "...")
        lines.append("")

    lines.append("All todos, active issues, and project state are preserved.")
    lines.append("Resume by reading FOR_JEFF_TODAY.md — it has the current work context.")

    return "\n".join(lines)


def main():
    debug("Pre-compact hook started")

    # Read hook input
    try:
        hook_input = json.load(sys.stdin)
        event = hook_input.get("hook_event_name", "")
        compact_type = hook_input.get("compact_type", "auto")
        session_id = hook_input.get("session_id", "unknown")
        debug(f"Event: {event}, compact_type: {compact_type}, session: {session_id}")
    except Exception as e:
        debug(f"Failed to read stdin: {e}")
        sys.exit(0)

    # Capture state
    state = capture_state(compact_type, session_id)

    # Save to disk
    save_state(state)

    # Log the event
    log_compaction(state)

    # Build recovery message
    recovery_msg = build_recovery_message(state)

    # Output for hook system
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreCompact",
            "additionalContext": recovery_msg
        }
    }
    print(json.dumps(output))
    debug("Pre-compact hook complete")
    sys.exit(0)


if __name__ == "__main__":
    main()
