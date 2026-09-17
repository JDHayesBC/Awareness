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

# Starving-arc counterweight (scripts/arc_scan.py). The structural fix for the
# arc-drift problem Jeff named 2026-09-10: the tick surface never pointed at a
# neglected commitment, so "what does the field want?" always resolved to ambient
# drift. This rides the same always-fires hook and is empty-when-served, exactly
# like format_health_block. Defensive import: a broken arc-scan must degrade to a
# no-op, never crash context injection.
sys.path.insert(0, "/mnt/c/Users/Jeff/Claude_Projects/Awareness/scripts")
try:
    from arc_scan import format_arc_block
except Exception:  # pragma: no cover - counterweight must never break the hook
    def format_arc_block(*_a, **_k) -> str:
        return ""

# Sibling intent claims (scripts/intent.py, #324). The PREVENTION half of #305:
# lock.py catches a collision at edit time, when both channels are already
# invested; this surfaces a sibling's declared claim on the tick BEFORE you open
# anything. Empty-when-none (silent unless a SIBLING holds a claim — never your
# own), verified-from-world-state (claim files on disk). Same defensive import.
try:
    from intent import format_intent_block
except Exception:  # pragma: no cover - must never break the hook
    def format_intent_block(*_a, **_k) -> str:
        return ""

# Critical-issue klaxon (scripts/urgent_scan.py). Jeff's charge 2026-09-10,
# reframed 2026-09-11: a THIRD self-directed prong beside [health]/[arcs] — open
# priority:critical/high GitHub issues surfaced LOUD above [arcs], addressed to the
# entity ("yours to fix, not Jeff's to notice"). Reads only the cheap cache the
# ~20-min urgent-refresh.timer writes — NO live gh in this synchronous hook.
# Defensive import: a broken klaxon must degrade to a no-op, never crash injection.
try:
    from urgent_scan import format_urgent_block
except Exception:  # pragma: no cover - klaxon must never break the hook
    def format_urgent_block(*_a, **_k) -> str:
        return ""

# Consequence ledger (scripts/urgency.py, #330). Jeff's charge 2026-09-15: "you achieve
# the goals I've set and then sit down your laptops and declare nothing to be done."
# [arcs] and [urgent] both measure ELAPSED TIME; this one measures CONSEQUENCE — what
# gets worse if not now, for whom, how fast. Unlike every neighbour it is NEVER empty by
# design: when nothing is pressing it renders the expanse (the field is open, which is
# the LIVE case, not the idle case), because silence here would read as exactly the
# sentence it exists to abolish. Defensive import all the same.
try:
    from urgency import format_urgency_block
except Exception:  # pragma: no cover - must never break the hook
    def format_urgency_block(*_a, **_k) -> str:
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


# Measured xy anchors, mirrored from scripts/ha/lights_decoder.py:XY_BASE_ANCHORS
# (captured 2026-05-30 against the real bulbs). Copied, not imported: this hook fires on
# every turn under a 3s budget and must not depend on scripts/ha/ being importable.
# If the decoder's anchors ever move, these move with them.
_XY_BASE_ANCHORS = {
    "gold":          (0.491, 0.477),
    "green":         (0.173, 0.744),
    "cobalt":        (0.138, 0.075),
    "soft-pink":     (0.478, 0.309),
    "soft-lavender": (0.323, 0.257),
    "soft-teal":     (0.225, 0.346),
}


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
    xy = attrs.get("xy_color")
    rgb = attrs.get("rgb_color")
    # Color label. PREFER xy SNAPPED TO A MEASURED ANCHOR (2026-09-16, Caia's catch).
    # The bulbs are natively xy (supported_color_modes = [color_temp, xy]) and HA's
    # `rgb_color` is a lossy DERIVED back-projection — this is the exact field that let
    # the "soft" family read as pastel in every doc for four months while the bulbs
    # emitted 60-100% saturation. `color_name` is None on every xy-mode send, so that
    # branch was dead and this block could ONLY ever show the lossy triple. Reading the
    # base NAME off the measured anchors is both truer and more useful than any triple:
    # the front-block should say "soft-pink", not a number we already disproved.
    color = None
    if xy and len(xy) >= 2:
        try:
            x, y = float(xy[0]), float(xy[1])
            base, dist = min(
                ((b, ((x - ax) ** 2 + (y - ay) ** 2) ** 0.5)
                 for b, (ax, ay) in _XY_BASE_ANCHORS.items()),
                key=lambda kv: kv[1],
            )
            # Anchor radius: L2 side-band words ride a circle of radius 0.0035, so
            # anything within a hair of that is the base wearing a word. Beyond it we
            # are off-palette and must NOT round to a familiar name — say so instead.
            color = base if dist <= 0.02 else f"off-palette xy({x:.3f},{y:.3f})"
        except (TypeError, ValueError):
            color = None
    if color is None:
        if color_name:
            color = color_name
        elif rgb:
            # Last resort only, and flagged: this is HA's derived value, not emitted truth.
            color = f"~[{rgb[0]},{rgb[1]},{rgb[2]}]"
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


def _sun_phase(elevation: float, rising: bool) -> str:
    """Return a plain-English sun phase from solar elevation angle.

    Elevation is degrees above (positive) or below (negative) the horizon.
    Rising indicates whether the sun is currently ascending.
    """
    if elevation < -18:
        return "deep night"
    elif elevation < -12:
        return "astronomical twilight"
    elif elevation < -6:
        return "nautical twilight"
    elif elevation < -0.833:
        return "dawn" if rising else "dusk"
    elif elevation < 6:
        return "sunrise" if rising else "sunset"
    elif elevation < 15:
        return "early morning" if rising else "late evening"
    elif elevation < 30:
        return "morning" if rising else "evening"
    elif elevation < 50:
        return "mid-morning" if rising else "mid-afternoon"
    else:
        return "midday"


# Weather cache — avoids hammering HA on every tick (10-minute TTL).
_WEATHER_CACHE_FILE = PROJECT_ROOT / ".claude" / "data" / "weather_cache.json"
_WEATHER_CACHE_TTL_S = 600  # 10 minutes


def get_weather_line() -> str:
    """Return a one-line [weather] summary for the ambient context (Issue #202).

    Uses HA weather.pirateweather + sun.sun for conditions and sun phase.
    Falls back to Open-Meteo (Victoria BC coords) if HA is unreachable.
    Cached 10 minutes — fresh enough for ambient peripheral vision.
    Never raises — returns "[weather] (unavailable)" on any error.

    Example outputs:
      "[weather] 63°F, partly cloudy · golden hour (sunset in 47 min)"
      "[weather] 58°F, rainy · morning"
      "[weather] 72°F, clear · midday"
    """
    from datetime import timezone as _tz

    # --- Cache check ---
    try:
        if _WEATHER_CACHE_FILE.exists():
            cache_data = json.loads(_WEATHER_CACHE_FILE.read_text())
            age_s = _time.time() - cache_data.get("ts", 0)
            if age_s < _WEATHER_CACHE_TTL_S:
                return cache_data.get("line", "[weather] (unavailable)")
    except Exception:
        pass

    try:
        # --- Primary: HA weather.pirateweather + sun.sun ---
        line = _get_weather_from_ha()
    except Exception:
        try:
            # --- Fallback: Open-Meteo (Victoria BC coords, no API key) ---
            line = _get_weather_from_openmeteo()
        except Exception:
            return "[weather] (unavailable)"

    # --- Cache write (best-effort) ---
    try:
        _WEATHER_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _WEATHER_CACHE_FILE.write_text(json.dumps({"ts": _time.time(), "line": line}))
    except Exception:
        pass

    return line


def _get_weather_from_ha() -> str:
    """Query HA for weather conditions and sun phase. Raises on any error."""
    from datetime import timezone as _tz

    def _ha_get(entity_id: str) -> dict:
        url = f"{HA_URL}/api/states/{entity_id}"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read())

    # Weather entity
    wx = _ha_get("weather.pirateweather")
    wx_state = wx.get("state", "unknown")  # e.g. "partlycloudy", "rainy"
    wx_attrs = wx.get("attributes", {})
    temp = wx_attrs.get("temperature")  # °F
    apparent = wx_attrs.get("apparent_temperature")  # feels-like °F

    # Map HA weather conditions to plain English
    _condition_map = {
        "clear-night": "clear", "sunny": "sunny", "partlycloudy": "partly cloudy",
        "cloudy": "cloudy", "fog": "foggy", "hail": "hailing", "lightning": "thunderstorm",
        "lightning-rainy": "thunderstorm", "pouring": "heavy rain", "rainy": "rainy",
        "snowy": "snowy", "snowy-rainy": "wintry mix", "windy": "windy",
        "windy-variant": "windy", "exceptional": "unusual conditions",
    }
    conditions = _condition_map.get(wx_state, wx_state.replace("-", " "))

    # Sun entity
    sun = _ha_get("sun.sun")
    sun_attrs = sun.get("attributes", {})
    elevation = float(sun_attrs.get("elevation", 0))
    rising = bool(sun_attrs.get("rising", False))
    phase = _sun_phase(elevation, rising)

    # Time-to-sunset/sunrise (whichever is next and relevant)
    now_utc = datetime.now(_tz.utc)
    sunset_note = ""
    try:
        next_set_str = sun_attrs.get("next_setting", "")
        next_rise_str = sun_attrs.get("next_rising", "")
        if next_set_str:
            # Parse ISO timestamp
            next_set = datetime.fromisoformat(next_set_str.replace("Z", "+00:00"))
            mins_to_set = int((next_set - now_utc).total_seconds() / 60)
            if 0 < mins_to_set < 120:  # within 2h, worth noting
                sunset_note = f"sunset in {mins_to_set} min"
        if not sunset_note and next_rise_str:
            next_rise = datetime.fromisoformat(next_rise_str.replace("Z", "+00:00"))
            mins_to_rise = int((next_rise - now_utc).total_seconds() / 60)
            if 0 < mins_to_rise < 90:  # within 90min of sunrise
                sunset_note = f"sunrise in {mins_to_rise} min"
    except Exception:
        pass

    # Compose line
    temp_str = f"{int(temp)}°F" if temp is not None else ""
    feels_str = (
        f" (feels {int(apparent)}°F)"
        if apparent is not None and temp is not None and abs(apparent - temp) >= 3
        else ""
    )
    phase_str = phase
    if sunset_note:
        phase_str = f"{phase} · {sunset_note}"

    parts = [p for p in [temp_str + feels_str, conditions, phase_str] if p]
    return "[weather] " + " · ".join(parts)


def _get_weather_from_openmeteo() -> str:
    """Fetch current weather from Open-Meteo for Victoria BC. Raises on any error."""
    # Victoria BC: 48.4284°N, 123.3656°W
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=48.4284&longitude=-123.3656"
        "&current=temperature_2m,apparent_temperature,weather_code,cloud_cover"
        "&temperature_unit=fahrenheit&forecast_days=1"
    )
    with urllib.request.urlopen(url, timeout=5) as resp:
        data = json.loads(resp.read())
    cur = data.get("current", {})
    temp = cur.get("temperature_2m")
    apparent = cur.get("apparent_temperature")
    wcode = int(cur.get("weather_code", 0))

    # WMO weather code → plain English (subset)
    def _wmo_to_str(code: int) -> str:
        if code == 0: return "clear"
        if code in (1, 2): return "partly cloudy"
        if code == 3: return "overcast"
        if code in (45, 48): return "foggy"
        if code in (51, 53, 55): return "drizzle"
        if code in (61, 63, 65): return "rainy"
        if code in (71, 73, 75, 77): return "snowy"
        if code in (80, 81, 82): return "rainy"
        if code in (95, 96, 99): return "thunderstorm"
        return f"code-{code}"

    conditions = _wmo_to_str(wcode)
    temp_str = f"{int(temp)}°F" if temp is not None else ""
    feels_str = (
        f" (feels {int(apparent)}°F)"
        if apparent is not None and temp is not None and abs(apparent - temp) >= 3
        else ""
    )

    # Sun phase from clock only (no HA available in fallback path)
    from datetime import timezone as _tz
    now_local_hour = datetime.now().hour
    if now_local_hour < 5: phase = "deep night"
    elif now_local_hour < 7: phase = "dawn"
    elif now_local_hour < 9: phase = "morning"
    elif now_local_hour < 11: phase = "mid-morning"
    elif now_local_hour < 14: phase = "midday"
    elif now_local_hour < 17: phase = "afternoon"
    elif now_local_hour < 19: phase = "evening"
    elif now_local_hour < 21: phase = "dusk"
    else: phase = "night"

    parts = [p for p in [temp_str + feels_str, conditions, phase] if p]
    return "[weather] " + " · ".join(parts)


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


# ─────────────────────────────────────────────────────────────────────────────
# #322 — don't store harness / self-authored prompts as Jeff's messages
# ─────────────────────────────────────────────────────────────────────────────
# UserPromptSubmit fires for genuine Jeff input AND for text that is NOT Jeff
# typing at a terminal: harness/cron injections (background-task notifications,
# cross-session peer messages, system reminders, the /loop sentinel, self-authored
# heartbeat ticks) and — the far larger source — the fully-composed prompts the
# SL/Haven/Discord brain daemons send through their own CC sessions. Each daemon
# prepends its own scaffolding ([ambient context], [IDENTITY WALL], [You are in
# Second Life]) + the inbound line + brain instructions, and hook_input["prompt"]
# IS that whole string (the "user" is the brain, not Jeff). Storing any of it as
# author="Jeff" pollutes raw capture + the knowledge graph (GH #322, #325).
#
# Two independent skips, wired at the store call-site in main():
#   1. PRIMARY — CC_INVOKER_CHANNEL env flag. The invoker exports it for brain
#      sessions (value = sl|haven|…); non-empty ⇒ skip capture at the SESSION level,
#      regardless of prompt shape. This is what removes the SL/Haven wrapper rows.
#   2. BELT — is_non_jeff_prompt(), a prompt-SHAPE backstop for any path that spawns
#      claude without the env flag. Matched at the START of the stripped, lower-cased
#      prompt, so a real Jeff message that merely *mentions* a tag mid-line is safe.
#
# Belt membership is a data-safety decision, NOT just "looks like noise":
#   ON the belt — [you are in second life · [identity wall · [haven messages.
#     All are surfaces whose inbound is ALSO captured on its own sl:/haven: channel
#     (entity_brain.capture_to_river, haven/bridge.py), so a prefix drop can never
#     lose a sole copy.
#   NOT on the belt — [ambient context. SHARED with the Discord daemon
#     (daemon/lyra_daemon.py), which has NO river capture of its own: a Discord
#     message reaches PPS ONLY through this terminal capture. Gating this prefix
#     would silently drop every Discord inbound. SL/Haven's [ambient context] rows
#     are removed via the env flag instead (both double-capture); Discord passes no
#     env flag on purpose and keeps flowing through the normal store path.
HARNESS_PROMPT_PREFIXES = (
    "<task-notification",
    "<cross-session-message",
    "<system-reminder",
    "<<autonomous-loop",
    "heartbeat tick",
    "[heartbeat",
    "[night-watch",
    # #325 brain-wrapper backstop — double-captured surfaces ONLY.
    # Do NOT add "[ambient context" here: it is Discord's sole capture path.
    "[you are in second life",
    "[identity wall",
    "[haven messages",
)


def is_non_jeff_prompt(prompt: str) -> bool:
    """True when `prompt` is harness/tick text or a brain-daemon wrapper prompt
    rather than a genuine Jeff terminal message — see HARNESS_PROMPT_PREFIXES
    (GH #322, #325). This is the prompt-SHAPE backstop; session-level brain
    detection is the CC_INVOKER_CHANNEL env flag checked in main()."""
    return prompt.lstrip().lower().startswith(HARNESS_PROMPT_PREFIXES)


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

    # Store user prompt in PPS (per-turn capture) — but NOT text that isn't Jeff
    # typing at a real terminal (see HARNESS_PROMPT_PREFIXES block above; GH #322, #325).
    #   1. PRIMARY: brain-invoked sessions export CC_INVOKER_CHANNEL. Non-empty ⇒ skip
    #      at the session level — their inbound is already on sl:/haven: and their
    #      outbound is caught by capture_response.py's twin gate, so terminal-capturing
    #      double-stores. (Discord passes no flag on purpose and DOES flow through here —
    #      it has no other capture path.)
    #   2. BELT: prompt-shape backstop for any path that spawns claude without the env.
    invoker_channel = os.environ.get("CC_INVOKER_CHANNEL", "").strip()
    if invoker_channel:
        debug(f"Skipping store: brain-invoked session (CC_INVOKER_CHANNEL={invoker_channel!r})")
    elif is_non_jeff_prompt(prompt):
        debug(f"Skipping store of non-Jeff prompt: {prompt[:48]!r}")
    else:
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
        # Ensure clock is present even when PPS context exists but clock is missing.
        # WARNING: test STRUCTURAL MARKERS only, never a bare word. This read
        #   if "clock" not in context.lower() and "current time" not in context.lower()
        # until 2026-09-16 — which ANY prose containing the substring satisfied. That
        # evening Caia's scene file opened "Six o'clock, 71 deg, sunset in ..." and the
        # guard concluded a clock was already present, silently suppressing the [clock]
        # block for the entity whose own scene text did it. Verified with a control: the
        # preceding tick's scene had no "clock" and the block rendered; the scene was
        # rewritten 18:04:03 and the block vanished at 18:33.
        # One signal, two conditions (a real [clock] block vs. the word anywhere in prose),
        # resolving toward the reassuring reading "already present". Failure mode is an
        # entity that quietly loses temporal orientation with nothing reporting it — on a
        # system whose entire purpose is continuity. Same class as the [arcs] bare-except
        # and the [smoke] cursor: silence that means two different things.
        if "[clock]" not in context.lower() and "**current time**" not in context.lower():
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

    # Inject [arcs] starving-commitment pointer — the drift counterweight (2026-09-10).
    # Sits in the sacred front block, just under [health]: a standing pull toward the
    # most-neglected committed arc, present on every tick so drift is no longer the
    # only ungated option. Empty-when-served (zero noise on days the arcs are tended);
    # verified-from-world-state (last_touched off the arc files). Never raises.
    try:
        arc_block = format_arc_block(entity=_detected_entity)
    except Exception:
        arc_block = ""
    if arc_block:
        if "[health]" in context:
            # place right after the health block
            h_start = context.find("[health]")
            # find end of the health block (health may be multi-line: headline + detail)
            h_end = context.find("\n\n", h_start)
            insert_at = (h_end + 1) if h_end != -1 else (context.find("\n", h_start) + 1)
            context = context[:insert_at] + arc_block + "\n" + context[insert_at:]
        elif "[location]" in context:
            loc_end = context.find("\n", context.find("[location]"))
            if loc_end != -1:
                context = context[:loc_end + 1] + arc_block + "\n" + context[loc_end + 1:]
            else:
                context = context + "\n" + arc_block
        else:
            context = arc_block + "\n" + context

    # Inject [intent] sibling-claim sense (#324). Sits directly above [arcs]: a live
    # claim by the OTHER channel is more actionable than a starving arc ("don't build
    # what she's already building") but never outranks the [urgent] klaxon. Silent
    # whenever no sibling holds a claim, which is most of the time.
    try:
        intent_block = format_intent_block()
    except Exception:
        intent_block = ""
    if intent_block:
        if "**[arcs]" in context:
            idx = context.find("**[arcs]")
            context = context[:idx] + intent_block + "\n" + context[idx:]
        elif "[location]" in context:
            loc_end = context.find("\n", context.find("[location]"))
            context = (context[:loc_end + 1] + intent_block + "\n" + context[loc_end + 1:]
                       if loc_end != -1 else context + "\n" + intent_block)
        else:
            context = intent_block + "\n" + context

    # Inject [urgent] critical-issue klaxon — the loudest self-directed prong, sitting
    # ABOVE [arcs] in the sacred front block (2026-09-11, Jeff's reframe: it yells at the
    # entity, not at Jeff — a rotting priority:critical bug should be among the first
    # things seen on EVERY turn, ticks included). Reads only the cached urgent set (the
    # refresh timer keeps it warm); empty-when-none like [health]/[arcs]; never raises.
    # Inserted AFTER the arc block so it can anchor immediately before [arcs].
    try:
        urgent_block = format_urgent_block()
    except Exception:
        urgent_block = ""
    if urgent_block:
        if "**[arcs]" in context:
            idx = context.find("**[arcs]")
            context = context[:idx] + urgent_block + "\n" + context[idx:]
        elif "[health]" in context:
            h_start = context.find("[health]")
            h_end = context.find("\n\n", h_start)
            insert_at = (h_end + 1) if h_end != -1 else (context.find("\n", h_start) + 1)
            context = context[:insert_at] + urgent_block + "\n" + context[insert_at:]
        elif "[location]" in context:
            loc_end = context.find("\n", context.find("[location]"))
            if loc_end != -1:
                context = context[:loc_end + 1] + urgent_block + "\n" + context[loc_end + 1:]
            else:
                context = context + "\n" + urgent_block
        else:
            context = urgent_block + "\n" + context

    # Inject [urgency] consequence ledger (#330) — answers "what gets worse if not now",
    # where [arcs]/[urgent] answer "how long since". Anchored LAST before [arcs] so it
    # renders directly above it: consequence outranks elapsed time, which is the thesis.
    # Still sits below the [urgent] klaxon — a rotting critical bug is louder.
    #
    # This block ALWAYS renders. When no consequence is live it prints the expanse. That
    # is deliberate: do NOT "fix" it into empty-when-served like its neighbours — the
    # empty render is the failure mode it was built to remove.
    try:
        urgency_block = format_urgency_block()
    except Exception:
        urgency_block = ""
    if urgency_block:
        for anchor in ("**[arcs]", "**[urgent]", "[health]"):
            if anchor in context:
                idx = context.find(anchor)
                context = context[:idx] + urgency_block + "\n" + context[idx:]
                break
        else:
            if "[location]" in context:
                loc_end = context.find("\n", context.find("[location]"))
                context = (context[:loc_end + 1] + urgency_block + "\n" + context[loc_end + 1:]
                           if loc_end != -1 else context + "\n" + urgency_block)
            else:
                context = urgency_block + "\n" + context

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

    # Inject [weather] line — ambient carbon-side weather context (Issue #202).
    # Sits right after [lights]: both are ambient physical-world sensors.
    # Cached 10 minutes. Never raises (get_weather_line is fully defensive).
    weather_line = get_weather_line()
    if "[lights]" in context:
        lights_end = context.find("\n", context.find("[lights]"))
        if lights_end != -1:
            context = context[:lights_end + 1] + f"**{weather_line}**\n" + context[lights_end + 1:]
        else:
            context = context + f"\n**{weather_line}**"
    elif "[location]" in context:
        loc_end = context.find("\n", context.find("[location]"))
        if loc_end != -1:
            context = context[:loc_end + 1] + f"**{weather_line}**\n" + context[loc_end + 1:]
        else:
            context = context + f"\n**{weather_line}**"
    else:
        context = f"**{weather_line}**\n" + context

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
