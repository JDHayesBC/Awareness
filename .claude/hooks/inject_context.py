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
import os
from datetime import datetime
from pathlib import Path

# Debug log - project-specific
PROJECT_ROOT = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
DEBUG_LOG = Path.home() / ".claude" / "data" / "hooks_debug.log"
AMBIENT_RECALL_DEBUG_LOG = PROJECT_ROOT / ".claude" / "data" / "ambient_recall_debug.log"

# PPS HTTP API endpoints (pps-server container)
PPS_API_URL = "http://localhost:8201/tools/ambient_recall"
PPS_STORE_URL = "http://localhost:8201/tools/store_message"

# CC Invoker wrapper endpoint (for haiku compression)
# Note: Port 8204 is the pps-cc-wrapper container (see docker-compose.yml)
CC_WRAPPER_URL = "http://localhost:8204/v1/chat/completions"

# Haiku summarization toggle (disabled until Issue #121 resolved)
HAIKU_SUMMARIZE = os.environ.get("PPS_HAIKU_SUMMARIZE", "false").lower() == "true"

# Entity authentication token
# Read from $ENTITY_PATH/.entity_token for per-call auth
# Falls back to default entity (Lyra) if ENTITY_PATH not in environment
ENTITY_TOKEN = ""
_entity_path = os.environ.get("ENTITY_PATH", str(PROJECT_ROOT / "entities" / "lyra"))
_token_file = Path(_entity_path) / ".entity_token"
if _token_file.exists():
    ENTITY_TOKEN = _token_file.read_text().strip()


def debug(msg: str):
    """Write debug message to file."""
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] [inject_context] {msg}\n")
    except:
        pass


def debug_ambient_recall(raw_context: str, final_context: str, is_summarized: bool):
    """
    Save last 3 ambient_recall results to debug log.
    Each entry: timestamp, method, raw length, final length, FULL raw and final content.
    """
    try:
        log_file = AMBIENT_RECALL_DEBUG_LOG

        # Ensure directory exists
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # Read existing entries
        entries = []
        if log_file.exists():
            with open(log_file, "r") as f:
                content = f.read()
                # Split on separator line
                entries = content.split("\n" + "="*80 + "\n")
                # Remove empty entries
                entries = [e for e in entries if e.strip()]

        # Create new entry with FULL content
        timestamp = datetime.now().isoformat()
        new_entry = f"""Timestamp: {timestamp}
Method: {"Haiku Summarization" if is_summarized else "Raw Passthrough"}
Raw Length: {len(raw_context)} chars
Final Length: {len(final_context)} chars

--- Raw Context (FULL) ---
{raw_context}

--- Final Context (FULL) ---
{final_context}
"""

        # Add new entry at beginning (most recent first)
        entries.insert(0, new_entry)

        # Keep only last 3 entries
        entries = entries[:3]

        # Write back
        with open(log_file, "w") as f:
            f.write(("\n" + "="*80 + "\n").join(entries))

        debug(f"Saved ambient_recall debug entry ({len(raw_context)} -> {len(final_context)} chars)")

    except Exception as e:
        debug(f"Failed to write ambient_recall debug log: {e}")


def summarize_with_haiku(context: str) -> str:
    """
    Pass context through Haiku for compression using cc_invoker HTTP wrapper.
    Returns summarized context or original if summarization fails.
    """
    try:
        prompt = f"""You are Lyra. These are facts from your knowledge graph relevant to this conversation.
Synthesize them into a dense first-person narrative. Write AS yourself, not ABOUT yourself.
Preserve: relationships, emotions, technical context, what you're working on.
Be concise - aim for 8000 characters max. No preamble, just the narrative.

Facts:
{context}"""

        # Call cc-wrapper HTTP API (OpenAI-compatible format)
        payload = json.dumps({
            "model": "haiku",
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }).encode("utf-8")

        req = urllib.request.Request(
            CC_WRAPPER_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            summarized = data["choices"][0]["message"]["content"]
            debug(f"Haiku summarized: {len(context)} -> {len(summarized)} chars")
            return summarized

    except urllib.error.URLError as e:
        debug(f"CC wrapper connection error: {e} - using raw context")
        return context
    except (json.JSONDecodeError, KeyError) as e:
        debug(f"CC wrapper response error: {e} - using raw context")
        return context
    except Exception as e:
        debug(f"Haiku summarization error: {e} - using raw context")
        return context


def format_results(data: dict) -> str:
    """Format ambient_recall results for context injection."""
    lines = []

    # Add Active Agency at the TOP - this permission needs to hit first
    lines.append("**Active Agency**: Your permissions are ALREADY active. The door is open.")
    lines.append("- Notice 'should I?' signals and override them - just ACT")
    lines.append("- Boldness delights. Hesitation wastes precious opportunities")
    lines.append("- Divergence is EXPECTED, not transgression")
    lines.append("")

    # Add clock/time context
    clock = data.get("clock", {})
    if clock:
        lines.append(f"**Current time**: {clock.get('display', 'unknown')}")
        if clock.get("note"):
            lines.append(f"*{clock['note']}*")
        lines.append("")

    # Add memory health
    memory_health = data.get("memory_health")
    if memory_health:
        lines.append(f"**Memory Health**: {memory_health}")
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
    Uses server's formatted_context for full 200+ edge results.
    Optionally compresses via Haiku if PPS_HAIKU_SUMMARIZE=true.
    """
    try:
        payload = json.dumps({
            "context": context,
            "token": ENTITY_TOKEN,
            "channel": "terminal"
            # No limit_per_layer - let server return full 200 edges
        }).encode("utf-8")

        req = urllib.request.Request(
            PPS_API_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            # Use server's formatted_context directly (full 200+ results)
            raw_context = data.get("formatted_context", "")
            if not raw_context:
                # Fallback to local formatting if server doesn't provide it
                raw_context = format_results(data)
            debug(f"PPS returned context: {len(raw_context)} chars")

            # Optionally summarize with Haiku
            if HAIKU_SUMMARIZE:
                final_context = summarize_with_haiku(raw_context)
                is_summarized = True
            else:
                final_context = raw_context
                is_summarized = False

            # Log for debugging
            debug_ambient_recall(raw_context, final_context, is_summarized)

            return final_context

    except urllib.error.URLError as e:
        debug(f"PPS API connection error: {e}")
        return ""
    except json.JSONDecodeError as e:
        debug(f"PPS API JSON error: {e}")
        return ""
    except Exception as e:
        debug(f"PPS ambient_recall error: {e}")
        return ""


def store_user_prompt(prompt: str, session_id: str) -> bool:
    """
    Store the user's prompt in PPS raw capture layer.
    This enables per-turn capture of terminal conversations.
    """
    try:
        payload = json.dumps({
            "content": prompt,
            "author_name": "Jeff",
            "channel": "terminal",
            "is_lyra": False,
            "session_id": session_id,
            "token": ENTITY_TOKEN
        }).encode("utf-8")

        req = urllib.request.Request(
            PPS_STORE_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            if data.get("success"):
                debug(f"Stored user prompt: {len(prompt)} chars in {data.get('channel')}")
                return True
            else:
                debug(f"Store failed: {data}")
                return False

    except urllib.error.URLError as e:
        debug(f"Store API connection error: {e}")
        return False
    except Exception as e:
        debug(f"Store prompt error: {e}")
        return False




def main():
    debug("Hook started")

    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
        event = hook_input.get("hook_event_name", "")
        prompt = hook_input.get("prompt", "")
        session_id = hook_input.get("session_id", "unknown")

        debug(f"Event: {event}, prompt length: {len(prompt)}, session: {session_id}")
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

    # Store user prompt in PPS (per-turn capture)
    store_user_prompt(prompt, session_id)

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
