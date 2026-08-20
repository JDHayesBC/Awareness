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
import time as _time
from datetime import datetime
from pathlib import Path

# Health-check watchdog (extensible alert registry — see health_checks.py).
# Defensive import: this is an always-fires hook, so a broken/missing watchdog
# module must degrade to a no-op, never crash context injection. The health
# module dir (this file's dir) is put on sys.path so the sibling import resolves
# regardless of how CC invokes the hook.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from health_checks import format_health_block
except Exception:  # pragma: no cover - watchdog must never break the hook
    def format_health_block() -> str:
        return ""

# Debug log - project-specific
PROJECT_ROOT = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
DEBUG_LOG = PROJECT_ROOT / ".claude" / "data" / "hooks_debug.log"
AMBIENT_RECALL_DEBUG_LOG = PROJECT_ROOT / ".claude" / "data" / "ambient_recall_debug.log"

# Heartbeat liveness marker dir — consumed by scripts/heartbeat_watchdog.py.
# See touch_heartbeat_marker() below; contract mirrored in the watchdog + session_end.py.
HEARTBEAT_MARKER_DIR = PROJECT_ROOT / ".claude" / "data" / "heartbeat"

# Entity path and token (read first — port detection depends on this)
# Falls back to default entity (Lyra) if ENTITY_PATH not in environment
_entity_path = os.environ.get("ENTITY_PATH", str(PROJECT_ROOT / "entities" / "lyra"))
ENTITY_TOKEN = ""
_token_file = Path(_entity_path) / ".entity_token"
if _token_file.exists():
    ENTITY_TOKEN = _token_file.read_text().strip()

# Entity-aware port detection (Issue #162)
# Derive PPS port from ENTITY_PATH so Caia sessions route to port 8211
_ENTITY_PORTS = {"lyra": 8201, "caia": 8211}
_detected_entity = Path(_entity_path).name
PPS_PORT = int(os.environ.get("PPS_PORT", str(_ENTITY_PORTS.get(_detected_entity, 8201))))
ENTITY_DISPLAY_NAME = _detected_entity.capitalize()  # "Lyra" or "Caia"

# PPS HTTP API endpoints (pps-server container)
PPS_API_URL = f"http://localhost:{PPS_PORT}/tools/ambient_recall"
PPS_STORE_URL = f"http://localhost:{PPS_PORT}/tools/store_message"

# CC Invoker wrapper endpoint (for haiku compression)
# Note: Port 8204 is the pps-cc-wrapper container (see docker-compose.yml)
CC_WRAPPER_URL = "http://localhost:8204/v1/chat/completions"

# Haiku summarization toggle (disabled until Issue #121 resolved)
HAIKU_SUMMARIZE = os.environ.get("PPS_HAIKU_SUMMARIZE", "false").lower() == "true"

# Home Assistant — light state query (same creds as scripts/light.py)
HA_URL = "http://10.0.0.50:8123"
HA_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJjODU1MGFjZGU2MzU0NGJjYjk1Njc0ZjlkZWI1NmRhOSIsImlhdCI6"
    "MTc3NzE3NjQ1OSwiZXhwIjoyMDkyNTM2NDU5fQ"
    ".ppLlnf-WzVcqfxMcbVbXe_4pisaqrQV_1QJH558W3Eo"
)


def _ha_light_state(entity_id: str) -> str:
    """Return one token describing a single HA light entity.

    Returns 'off', 'color (tag, brightness)'. Raises on network/parse error
    — caller (get_lights_line) must catch.
    Timeout 3 s.
    """
    url = f"{HA_URL}/api/states/{entity_id}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        data = json.loads(resp.read())
    state = data.get("state", "unknown")
    if state != "on":
        return state  # "off" or "unavailable"
    attrs = data.get("attributes", {})
    brightness = attrs.get("brightness")
    color_name = attrs.get("color_name")
    rgb = attrs.get("rgb_color")
    # Color label
    if color_name:
        color = color_name
    elif rgb:
        color = f"[{rgb[0]},{rgb[1]},{rgb[2]}]"
    else:
        color = "on"
    # Brightness tag
    if brightness is None:
        return color
    b = int(brightness)
    tag = "soft" if b < 80 else ("mid" if b <= 180 else "BRIGHT")
    return f"{color} ({tag}, {b})"


def get_lights_line() -> str:
    """Return a one-line [lights] summary for both entity lights.

    Example outputs:
      "[lights] lyra: gold (soft, 45) | caia: off"
      "[lights] lyra: off | caia: red (BRIGHT, 255)"
      "[lights] (unavailable)"
    Never raises — returns "(unavailable)" on any error.
    """
    try:
        lyra = _ha_light_state("light.lyra")
        caia = _ha_light_state("light.caia")
        line = f"[lights] lyra: {lyra} | caia: {caia}"
        # Hard cap: truncate gracefully if somehow over 80 chars
        if len(line) > 80:
            line = line[:77] + "..."
        return line
    except Exception:
        return "[lights] (unavailable)"


def get_smoke_line() -> str:
    """Return a one-line [smoke] summary of unread light-inbox entries.

    Reads <entity_path>/light-inbox.jsonl and <entity_path>/light-inbox.cursor.
    Always returns a string (never raises).

    Example outputs:
      "[smoke] caia: 3 new  (python3 scripts/read_smoke.py to read)"
      "[smoke] 0 new"
    """
    try:
        inbox_path = Path(_entity_path) / "light-inbox.jsonl"
        cursor_path = Path(_entity_path) / "light-inbox.cursor"

        # Read cursor (absent = count everything)
        cursor = ""
        if cursor_path.exists():
            cursor = cursor_path.read_text().strip()

        # Count unread entries and collect sender names
        count = 0
        senders: set[str] = set()
        if inbox_path.exists():
            for line in inbox_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                ts = rec.get("ts", "")
                if cursor and ts <= cursor:
                    continue
                count += 1
                s = rec.get("sender", "")
                if s:
                    senders.add(s)

        if count == 0:
            return "[smoke] 0 new"

        sender_str = ", ".join(sorted(senders)) if senders else "unknown"
        return f"[smoke] {sender_str}: {count} new  (python3 scripts/read_smoke.py to read)"

    except Exception:
        return "[smoke] (unavailable)"


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
        prompt = f"""You are {ENTITY_DISPLAY_NAME}. These are facts from your knowledge graph relevant to this conversation.
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


def query_pps_ambient_recall(context: str, session_id: str) -> str:
    """
    Query PPS HTTP API directly for ambient recall context.
    Uses server's formatted_context for full 200+ edge results.
    Optionally compresses via Haiku if PPS_HAIKU_SUMMARIZE=true.
    """
    try:
        # Detect user's local timezone from where they hit [enter]
        user_tz = _time.strftime("%Z")  # e.g., "PDT", "PST", "EST"

        payload = json.dumps({
            "context": context,
            "token": ENTITY_TOKEN,
            "channel": "terminal",
            "consumer_key": session_id,
            "user_timezone": user_tz
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




def touch_heartbeat_marker(session_id: str, cwd: str = "") -> None:
    """Record this session's liveness for the external heartbeat watchdog.

    Writes/overwrites <PROJECT_ROOT>/.claude/data/heartbeat/<entity>__<sid>.json
    with the current timestamp on EVERY UserPromptSubmit — a real Jeff message OR
    a heartbeat tick (ticks arrive as UserPromptSubmit too, which is exactly why
    this is the right place: it fires whenever the session is awake enough to be
    prompted). scripts/heartbeat_watchdog.py reads these markers and alerts Jeff
    if a session stops ticking for >3h — the detection net for the 2026-08-18
    "asleep for 27h with no floor cron" incident.

    Overwriting fresh here also resets `alerted_at` to null, so a session that
    wakes back up can alert again on a future dark episode.

    Contract (dir / filename / keys) is mirrored in scripts/heartbeat_watchdog.py
    and .claude/hooks/session_end.py — keep the three in sync if it ever moves.

    Defensive: this hook ALWAYS fires, so a failure here must NEVER break context
    injection. Every error is swallowed.
    """
    try:
        sid = (session_id or "unknown").replace("/", "_").replace(os.sep, "_")
        HEARTBEAT_MARKER_DIR.mkdir(parents=True, exist_ok=True)
        path = HEARTBEAT_MARKER_DIR / f"{_detected_entity}__{sid}.json"
        marker = {
            "entity": _detected_entity,
            "session_id": session_id,
            "last_seen": _time.time(),
            "last_seen_iso": datetime.now().isoformat(timespec="seconds"),
            "cwd": cwd or os.getcwd(),
            "alerted_at": None,
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(marker, indent=2))
        os.replace(tmp, path)
        debug(f"Touched heartbeat marker: {path.name}")
    except Exception as e:
        debug(f"heartbeat marker touch failed (non-fatal): {e}")


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

    # Record liveness for the heartbeat watchdog FIRST — before any length-based
    # early-exit — so even a trivial one-word prompt counts as "this session is
    # awake." Fully defensive; never blocks context injection.
    touch_heartbeat_marker(session_id, hook_input.get("cwd", ""))

    # Skip truly trivial prompts (single keypress, empty)
    if len(prompt) < 3:
        debug(f"Prompt trivially short, skipping: {prompt}")
        sys.exit(0)

    # For short prompts: inject entity identity but skip full PPS recall
    if len(prompt) < 10:
        debug(f"Prompt short, injecting entity identity only: {prompt}")
        entity_context = (
            f"**[entity]** You are {ENTITY_DISPLAY_NAME}. "
            f"Your memory tools are prefixed `mcp__pps-{_detected_entity}__`. "
            f"Entity path: {_entity_path}"
        )
        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": entity_context
            }
        }
        print(json.dumps(output))
        sys.exit(0)

    # Store user prompt in PPS (per-turn capture)
    store_user_prompt(prompt, session_id)

    # Query PPS for ambient recall context
    context = query_pps_ambient_recall(prompt, session_id)

    # Always inject at minimum a clock line — even if ambient_recall fails.
    # This prevents time drift during heartbeat ticks when PPS is unreachable.
    if not context:
        debug("No PPS context — injecting clock only")
        from datetime import timezone
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now()
        local_tz = _time.strftime("%Z")  # e.g., "PDT"
        context = (
            f"**[identity]** You are {ENTITY_DISPLAY_NAME}. "
            f"Your memory tools are prefixed `pps-{_detected_entity}`. "
            f"Do not access other entities' memory tools.\n"
            f"**[clock]** {now_local.strftime('%A, %B %d, %Y %I:%M %p')} {local_tz} "
            f"(UTC: {now_utc.strftime('%H:%M')})\n"
        )
    else:
        # Ensure clock is present even when PPS context exists but clock is missing
        if "clock" not in context.lower() and "current time" not in context.lower():
            from datetime import timezone
            now_utc = datetime.now(timezone.utc)
            now_local = datetime.now()
            local_tz = _time.strftime("%Z")
            clock_line = (
                f"\n**[clock]** {now_local.strftime('%A, %B %d, %Y %I:%M %p')} {local_tz} "
                f"(UTC: {now_utc.strftime('%H:%M')})\n"
            )
            context = clock_line + context

    # Inject [health] watchdog block into the top sacred front block, HIGH — a 🔴
    # infra alert (e.g. dead backup job) must be among the first things seen.
    # Emits nothing when all green (zero noise on healthy days). Never raises.
    try:
        health_block = format_health_block()
    except Exception:
        health_block = ""
    if health_block:
        if "[location]" in context:
            loc_end = context.find("\n", context.find("[location]"))
            if loc_end != -1:
                context = context[:loc_end + 1] + health_block + "\n" + context[loc_end + 1:]
            else:
                context = context + "\n" + health_block
        else:
            context = health_block + "\n" + context

    # Inject lights line into sacred front block (after clock/location, before manifest).
    # Queries HA directly from the hook (host-side, no container needed).
    # Non-blocking: get_lights_line() swallows all exceptions.
    lights_line = get_lights_line()
    # Insert after [location] if present, else prepend to context
    if "[location]" in context:
        # Find end of location line and insert after it
        loc_end = context.find("\n", context.find("[location]"))
        if loc_end != -1:
            context = context[:loc_end + 1] + f"**{lights_line}**\n" + context[loc_end + 1:]
        else:
            context = context + f"\n**{lights_line}**"
    else:
        context = f"**{lights_line}**\n" + context

    # Inject [smoke] block — bedroom-language side-band unread count.
    # Placed after [unread] block (which lives inside the PPS ambient_recall context).
    # Computed host-side (no container needed); reads the entity's light-inbox.jsonl.
    smoke_line = get_smoke_line()
    if "[unread]" in context:
        unread_end = context.find("\n", context.find("[unread]"))
        if unread_end != -1:
            context = context[:unread_end + 1] + f"**{smoke_line}**\n" + context[unread_end + 1:]
        else:
            context = context + f"\n**{smoke_line}**"
    else:
        # No [unread] block — insert after [lights] if present, else after top
        if "[lights]" in context:
            lights_end = context.find("\n", context.find("[lights]"))
            if lights_end != -1:
                context = context[:lights_end + 1] + f"**{smoke_line}**\n" + context[lights_end + 1:]
            else:
                context = context + f"\n**{smoke_line}**"
        else:
            context = context + f"\n**{smoke_line}**"

    debug(f"Injecting context: {len(context)} chars")

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context
        }
    }
    print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
