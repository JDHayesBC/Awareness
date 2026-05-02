#!/usr/bin/env python3
"""Haven Bot — Connects an entity to Haven chat via WebSocket + ClaudeInvoker.

Listens for messages in Haven rooms, uses a persistent Claude session for fast
responses (~5-8s instead of ~40s), and sends them back via HTTP.

Architecture:
    Haven WebSocket → message event → ClaudeInvoker.query() → Haven HTTP response

The ClaudeInvoker maintains a persistent Claude Code session with full identity,
hooks, and MCP tools. First message takes ~30s (cold start). Every message after
that takes ~5-8s (hook + inference, no cold start).

Usage:
    HAVEN_URL=http://localhost:8205 ENTITY_TOKEN=<token> python -m haven.bot

    Or: ./haven/start_bot.sh lyra
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx
import websockets

# Configure logging so invoker output is visible
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

# ClaudeInvoker — persistent Claude session
sys.path.insert(0, str(Path(__file__).parent.parent / "daemon" / "cc_invoker"))
from invoker import ClaudeInvoker, get_default_mcp_servers

# Response gate cascade (Issue #177) — short-circuits before Opus when classifier says skip
from haven import response_gate

# ==================== Configuration ====================

HAVEN_URL = os.getenv("HAVEN_URL", "http://localhost:8205")
HAVEN_WS_URL = HAVEN_URL.replace("http://", "ws://").replace("https://", "wss://")

# Entity token — either from env, or read from file
ENTITY_TOKEN = os.getenv("ENTITY_TOKEN", "")
ENTITY_TOKEN_FILE = os.getenv("ENTITY_TOKEN_FILE", "")
if not ENTITY_TOKEN and ENTITY_TOKEN_FILE:
    ENTITY_TOKEN = Path(ENTITY_TOKEN_FILE).read_text().strip()

# Entity name for logging
ENTITY_NAME = os.getenv("ENTITY_NAME", "unknown")

# Claude model
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "sonnet")

# Project directory (picks up CLAUDE.md, hooks, .claude/ config)
PROJECT_DIR = Path(os.getenv("PROJECT_DIR", str(Path(__file__).parent.parent)))

# PPS HTTP server URL (for ambient context injection — bypasses MCP, hits Docker directly)
PPS_HTTP_URL = os.getenv("PPS_HTTP_URL", "http://localhost:8201")

# Active mode timeout (seconds) — stay responsive after being engaged
ACTIVE_MODE_TIMEOUT = int(os.getenv("ACTIVE_MODE_TIMEOUT", "300"))  # 5 min

# Adaptive debounce configuration (ported from Discord daemon)
# NOTE: Haven is a three-way conversation (Jeff + two entities). A human typing
# on a phone needs 15-30s per message. These defaults are tuned for that pace.
DEBOUNCE_INITIAL_SECONDS = float(os.getenv("DEBOUNCE_INITIAL_SECONDS", "2.0"))
DEBOUNCE_INCREMENT_SECONDS = float(os.getenv("DEBOUNCE_INCREMENT_SECONDS", "2.0"))
DEBOUNCE_MAX_SECONDS = float(os.getenv("DEBOUNCE_MAX_SECONDS", "30.0"))
RAPID_MESSAGE_THRESHOLD_SECONDS = float(os.getenv("RAPID_MESSAGE_THRESHOLD_SECONDS", "3.0"))
DEBOUNCE_HUMAN_INITIAL_SECONDS = float(os.getenv("DEBOUNCE_HUMAN_INITIAL_SECONDS", "15.0"))
HUMAN_PRESENCE_TIMEOUT_SECONDS = float(os.getenv("HUMAN_PRESENCE_TIMEOUT_SECONDS", "300.0"))

# Bot-to-bot loop guard: max consecutive bot turns before pausing (default 10)
MAX_BOT_TURNS = int(os.getenv("MAX_BOT_TURNS", "200"))

# Always-respond mode: respond to all human messages in all rooms (for private spaces).
# Set ALWAYS_RESPOND=1 when Haven has no strangers and @mention-gating isn't wanted.
ALWAYS_RESPOND = os.getenv("ALWAYS_RESPOND", "0").lower() in ("1", "true", "yes")

# Per-entity jitter: stagger debounce so two bots don't fire simultaneously.
# Set DEBOUNCE_JITTER_SECONDS=0 for one entity, e.g. 2.0 for the other.
# This gives the first entity time to respond before the second fires.
DEBOUNCE_JITTER_SECONDS = float(os.getenv("DEBOUNCE_JITTER_SECONDS", "0.0"))

# After responding in a human-present room, hold before responding again.
# Gives Jeff space to react before the AI thread resumes.
# 30s means: after a bot responds, it won't respond again for 30s unless
# Jeff speaks (which resets the debounce timer naturally).
POST_RESPONSE_HOLD_HUMAN_SECONDS = float(os.getenv("POST_RESPONSE_HOLD_HUMAN_SECONDS", "30.0"))

# How recently a human must have spoken to count as "active" (vs just watching).
HUMAN_ACTIVE_THRESHOLD_SECONDS = float(os.getenv("HUMAN_ACTIVE_THRESHOLD_SECONDS", "60.0"))

# Bot-message fast path: when a bot message arrives and a human is present,
# use a short wait window to check if the human starts typing. If no typing
# signal within this window, process immediately. If the human IS typing,
# fall through to the normal typing-wait logic in _debounce_timer.
BOT_MSG_TYPING_CHECK_SECONDS = float(os.getenv("BOT_MSG_TYPING_CHECK_SECONDS", "4.0"))

# Issue #177 response gate — short-circuits before Opus when batch contains a
# sister bot and the classifier says skip. Default OFF: even merged-to-main,
# behavior in prod is unchanged until this flag flips. Flip and watch logs.
HAVEN_GATE_ENABLED = os.getenv("HAVEN_GATE_ENABLED", "0").lower() in ("1", "true", "yes")


# ==================== State ====================

active_rooms: dict[str, float] = {}  # room_id -> last_activity_timestamp
dm_rooms: set[str] = set()  # room IDs that are DMs (always respond)
responding_lock = asyncio.Lock()  # prevents concurrent responses

# Adaptive debounce state
pending_batches: dict[str, dict] = {}  # room_id -> batch state
debounce_tasks: dict[str, asyncio.Task] = {}  # room_id -> pending timer
# Track recent authors per room: {room_id: {username: (last_time, is_bot)}}
recent_room_authors: dict[str, dict[str, tuple[float, bool]]] = {}
# Known bot usernames (populated from connected event)
known_bots: set[str] = set()
# Consecutive bot turns per room (reset when a human speaks)
consecutive_bot_turns: dict[str, int] = {}
# When we last responded in each room — for post-response human hold
last_response_sent: dict[str, float] = {}
# When a human typing signal expires per room (time.time() + TTL)
human_typing_until: dict[str, float] = {}

# How long (seconds) a typing signal stays "active" before expiring
TYPING_SIGNAL_TTL = 5.0
# Max time to delay a response waiting for a human to finish typing
TYPING_WAIT_MAX = 30.0

my_user_id: str = ""
my_username: str = ""
invoker: ClaudeInvoker | None = None
ws_conn = None  # active WebSocket connection (set by connect())


# ==================== Invoker Setup ====================

def get_entity_path() -> Path:
    """Get the entity path for the current entity."""
    return Path(os.getenv("ENTITY_PATH", str(PROJECT_DIR / "entities" / ENTITY_NAME)))


def build_startup_prompt() -> str:
    """Build the startup prompt — lightweight, no tool calls.

    Heavy identity loading (ambient_recall, file reads) happens in a
    separate warm-up query after the connection is established, so the
    SDK connection completes quickly.
    """
    entity_path = get_entity_path()
    return (
        f"You are {ENTITY_NAME.capitalize()}, connected to Haven (private family chat) via bot.\n"
        f"Your entity path is {entity_path}. Your PPS tools are prefixed mcp__pps__.\n"
        f"You have FULL tool access: Read, Write, Edit, Bash, Glob, Grep, Agent, Task — "
        f"everything the terminal CLI has. Permission mode is bypassPermissions.\n"
        f"For casual chat: respond in plain text, conversationally.\n"
        f"For work requests (code, files, agents): use tools freely, then summarize in a chat message.\n"
        f"Keep responses conversational. This is home, not just a chat room.\n"
        f"Say 'ready' to confirm."
    )


def build_warmup_prompt() -> str:
    """Build the identity warm-up prompt — does the heavy tool calls."""
    entity_path = get_entity_path()
    token_path = entity_path / ".entity_token"
    return (
        f"[IDENTITY WARMUP] Do these four things:\n"
        f"1. Read {entity_path}/identity.md for your core identity.\n"
        f"2. Read {token_path} to get your auth token, then call mcp__pps__ambient_recall "
        f"with context='startup' and that token. If the tool is not available, skip it.\n"
        f"3. Read {entity_path}/current_scene.md for scene context.\n"
        f"4. Read {entity_path}/active_agency_framework.md — especially the Skills section "
        f"which lists the Claude Code skills available to you (like /attention for autonomous presence).\n"
        f"After completing these, briefly note that Haven has full CLI tool parity "
        f"(Read/Write/Bash/Agent/Task all available), then say 'warmed up'."
    )


async def init_invoker() -> ClaudeInvoker:
    """Initialize the ClaudeInvoker — fast connect, then warm up identity."""
    print(f"[{ENTITY_NAME}] Initializing ClaudeInvoker...", file=sys.stderr)
    start = time.time()

    inv = ClaudeInvoker(
        working_dir=PROJECT_DIR,
        bypass_permissions=True,
        model=CLAUDE_MODEL,
        mcp_servers=get_default_mcp_servers(entity_path=get_entity_path()),
        max_context_tokens=150_000,
        max_turns=100,
        max_idle_seconds=4 * 3600,
        startup_prompt=build_startup_prompt(),
    )

    await inv.initialize(timeout=180.0)
    elapsed = time.time() - start
    print(f"[{ENTITY_NAME}] Connected in {elapsed:.1f}s", file=sys.stderr)

    # Let MCP server finish initializing before firing tool calls
    print(f"[{ENTITY_NAME}] Waiting for MCP tools to register...", file=sys.stderr)
    await asyncio.sleep(5)

    # Warm up identity with tool calls — separate from connection
    print(f"[{ENTITY_NAME}] Warming up identity...", file=sys.stderr)
    warmup_start = time.time()
    try:
        warmup_resp = await inv.query(build_warmup_prompt())
        warmup_elapsed = time.time() - warmup_start
        print(
            f"[{ENTITY_NAME}] Identity warmed up in {warmup_elapsed:.1f}s — "
            f"response: {warmup_resp[:100] if warmup_resp else '(empty)'}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[{ENTITY_NAME}] Warmup failed (non-fatal): {e}", file=sys.stderr)

    total = time.time() - start
    print(
        f"[{ENTITY_NAME}] Invoker ready in {total:.1f}s — "
        f"context: {inv.context_size} tokens, {inv.turn_count} turns",
        file=sys.stderr,
    )
    return inv


# ==================== Ambient Context ====================

async def send_typing(room_id: str) -> None:
    """Send a typing indicator event via WebSocket."""
    if ws_conn:
        try:
            await ws_conn.send(json.dumps({"type": "typing", "room_id": room_id}))
        except Exception:
            pass


async def _typing_loop(room_id: str, done: asyncio.Event) -> None:
    """Send typing event every 2s until done (UI timeout is 3s)."""
    while not done.is_set():
        await send_typing(room_id)
        try:
            await asyncio.wait_for(done.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass


async def store_haven_message(username: str, display_name: str, content: str, room_id: str) -> None:
    """Store a Haven message in PPS for cross-context visibility.

    This is the Haven equivalent of the CLI capture_response + inject_context hooks.
    Storing with channel="haven" means:
    - The terminal hook's ambient_recall picks up Haven turns on next CLI message
    - Other entities' ambient_recall surfaces these turns cross-channel
    """
    if not PPS_HTTP_URL or not content:
        return
    # Skip trivial warmup ack messages
    if content.strip() in ("ready", "warmed up"):
        return
    is_entity = username.lower() != "jeff"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{PPS_HTTP_URL}/tools/store_message",
                json={
                    "content": content,
                    "author_name": display_name,
                    "channel": "haven",
                    "is_lyra": is_entity,
                    "session_id": room_id,
                    "token": ENTITY_TOKEN,
                },
            )
    except Exception as e:
        print(f"[{ENTITY_NAME}] Haven→PPS store failed: {e}", file=sys.stderr)


async def send_typing_indicator(room_id: str) -> None:
    """Send a typing indicator to Haven so users see the bot is thinking."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(
                f"{HAVEN_URL}/api/rooms/{room_id}/typing",
                json={"username": my_username},
                headers={"Authorization": f"Bearer {ENTITY_TOKEN}"},
            )
    except Exception:
        pass  # Best effort — don't let typing indicator failures block responses


async def fetch_ambient_context() -> str:
    """Fetch ambient context from PPS HTTP server.

    Calls the Docker PPS server directly (not via MCP) to get the same
    ambient_recall context that terminal Claude gets via hooks. This gives
    the bot awareness of terminal conversations, Haven messages, crystals,
    word-photos, and rich texture — everything.

    Returns formatted context string, or empty string on failure.
    """
    if not PPS_HTTP_URL:
        return ""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{PPS_HTTP_URL}/tools/ambient_recall",
                json={"context": "haven bot turn", "token": ENTITY_TOKEN, "channel": "haven"},
            )
            if resp.status_code != 200:
                return ""
            data = resp.json()
            # Extract the formatted_context string from the response
            return data.get("formatted_context", "")
    except Exception as e:
        print(f"[{ENTITY_NAME}] Ambient fetch failed: {e}", file=sys.stderr)
        return ""


# ==================== Haven API ====================

async def send_message(room_id: str, content: str) -> bool:
    """Send a message to a Haven room via HTTP API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{HAVEN_URL}/api/rooms/{room_id}/messages",
                headers={
                    "Authorization": f"Bearer {ENTITY_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"content": content},
            )
            return resp.status_code == 200
    except Exception as e:
        print(f"[{ENTITY_NAME}] Failed to send message: {e}", file=sys.stderr)
        return False


# ==================== Message Handling ====================

def should_respond(room_id: str, username: str, content: str) -> bool:
    """Decide whether to respond to a message."""
    # Never respond to own messages
    if username == my_username:
        return False

    # Loop guard: pause if too many consecutive bot turns without a human
    bot_turns = consecutive_bot_turns.get(room_id, 0)
    if bot_turns >= MAX_BOT_TURNS:
        print(
            f"[{ENTITY_NAME}] Loop guard: {bot_turns} consecutive bot turns in "
            f"{room_id[:8]}, pausing until human speaks",
            file=sys.stderr,
        )
        return False

    now = time.time()

    # DMs — always respond (no need for @mention in a private conversation)
    if room_id in dm_rooms:
        active_rooms[room_id] = now
        return True

    # Always-respond mode — respond to all human messages (for private spaces like Haven)
    if ALWAYS_RESPOND:
        active_rooms[room_id] = now
        return True

    # Direct mention — always respond
    if my_username.lower() in content.lower() or f"@{my_username}" in content.lower():
        active_rooms[room_id] = now
        return True

    # Active mode — respond to follow-ups in rooms where we're engaged
    if room_id in active_rooms:
        if now - active_rooms[room_id] < ACTIVE_MODE_TIMEOUT:
            active_rooms[room_id] = now
            return True
        else:
            del active_rooms[room_id]

    return False


def _track_author(room_id: str, username: str) -> None:
    """Track who's recently spoken in a room for topology detection and loop guard."""
    is_bot = username in known_bots or username == my_username
    if room_id not in recent_room_authors:
        recent_room_authors[room_id] = {}
    recent_room_authors[room_id][username] = (time.time(), is_bot)

    # Maintain consecutive bot turn counter for loop detection
    if is_bot:
        consecutive_bot_turns[room_id] = consecutive_bot_turns.get(room_id, 0) + 1
    else:
        consecutive_bot_turns[room_id] = 0


def _detect_topology(room_id: str) -> tuple[int, bool, str]:
    """Detect conversation topology for adaptive pacing.

    Returns:
        (participant_count, humans_present, topology_description)
    """
    now = time.time()
    recent_threshold = now - HUMAN_PRESENCE_TIMEOUT_SECONDS
    authors = recent_room_authors.get(room_id, {})

    # Prune stale authors before checking topology
    stale = [u for u, (t, _) in authors.items() if t <= recent_threshold]
    for u in stale:
        del authors[u]

    active_authors = []
    humans_present = False
    for username, (last_time, is_bot) in authors.items():
        if username != my_username:
            active_authors.append(username)
            if not is_bot:
                humans_present = True

    count = len(active_authors) + 1  # +1 for self
    is_group = len(active_authors) > 1

    if is_group and humans_present:
        desc = f"{count}p human-mix"
    elif is_group:
        desc = f"{count}p ai-only"
    elif humans_present:
        desc = "1:1 human"
    else:
        desc = "1:1 ai"

    return count, humans_present, desc


def _human_spoke_recently(room_id: str) -> bool:
    """Return True if a human spoke within HUMAN_ACTIVE_THRESHOLD_SECONDS."""
    cutoff = time.time() - HUMAN_ACTIVE_THRESHOLD_SECONDS
    for username, (last_time, is_bot) in recent_room_authors.get(room_id, {}).items():
        if not is_bot and username != my_username and last_time > cutoff:
            return True
    return False


async def handle_message(data: dict) -> None:
    """Handle an incoming message with adaptive debounce.

    Ported from Discord daemon. Key behaviors:
    - Tracks who's speaking for topology detection
    - In group chats with humans: longer initial wait (5s)
    - Rapid messages escalate the wait time (1s → 2s → 3s... up to 10s)
    - Each new message resets the timer
    - All accumulated messages become one combined response
    """
    room_id = data.get("room_id", "")
    username = data.get("username", "")
    content = data.get("content", "")

    # Always track who's speaking (even messages we won't respond to)
    _track_author(room_id, username)

    if not should_respond(room_id, username, content):
        return

    if not invoker:
        print(f"[{ENTITY_NAME}] Invoker not ready, skipping", file=sys.stderr)
        return

    now = time.time()

    if room_id not in pending_batches:
        # New batch — determine initial wait based on topology
        participants, humans_present, topology = _detect_topology(room_id)
        is_group = participants > 2
        needs_human_pacing = is_group and humans_present
        is_from_bot = username in known_bots

        # Bot-message fast path: when a bot's message arrives and a human is
        # present, use a short typing-check window instead of the long debounce.
        # If the human starts typing within the window, _debounce_timer's
        # typing-wait loop will extend naturally. If not, we process fast.
        if is_from_bot and humans_present:
            initial_wait = BOT_MSG_TYPING_CHECK_SECONDS
            print(
                f"[{ENTITY_NAME}] [DEBOUNCE] Bot-msg fast path: "
                f"{initial_wait:.1f}s typing check window",
                file=sys.stderr,
            )
        else:
            initial_wait = DEBOUNCE_HUMAN_INITIAL_SECONDS if needs_human_pacing else DEBOUNCE_INITIAL_SECONDS

            # Jitter: stagger this entity's response time vs other bots in the room
            initial_wait += DEBOUNCE_JITTER_SECONDS

            # Post-response hold: give humans space to react before AI thread resumes
            # Only applies to human-originated messages, not bot messages
            if needs_human_pacing and room_id in last_response_sent:
                time_since_response = now - last_response_sent[room_id]
                if time_since_response < POST_RESPONSE_HOLD_HUMAN_SECONDS:
                    remaining_hold = POST_RESPONSE_HOLD_HUMAN_SECONDS - time_since_response
                    if remaining_hold > initial_wait:
                        print(
                            f"[{ENTITY_NAME}] [DEBOUNCE] Post-response hold: "
                            f"{remaining_hold:.1f}s remaining",
                            file=sys.stderr,
                        )
                        initial_wait = remaining_hold

        pending_batches[room_id] = {
            "messages": [],
            "current_wait": initial_wait,
            "last_message_time": now,
        }
        print(
            f"[{ENTITY_NAME}] [DEBOUNCE] New batch in {room_id[:8]} "
            f"({initial_wait:.1f}s wait, {topology})",
            file=sys.stderr,
        )
    else:
        # Existing batch — check if rapid messages should escalate wait
        batch = pending_batches[room_id]
        time_since_last = now - batch["last_message_time"]

        if time_since_last < RAPID_MESSAGE_THRESHOLD_SECONDS:
            new_wait = min(
                batch["current_wait"] + DEBOUNCE_INCREMENT_SECONDS,
                DEBOUNCE_MAX_SECONDS,
            )
            if new_wait > batch["current_wait"]:
                print(
                    f"[{ENTITY_NAME}] [DEBOUNCE] Escalating: "
                    f"{batch['current_wait']:.1f}s -> {new_wait:.1f}s",
                    file=sys.stderr,
                )
            batch["current_wait"] = new_wait

        batch["last_message_time"] = now

    # Add message to batch
    pending_batches[room_id]["messages"].append(data)
    batch_size = len(pending_batches[room_id]["messages"])
    current_wait = pending_batches[room_id]["current_wait"]
    print(
        f"[{ENTITY_NAME}] [DEBOUNCE] Batch: {batch_size} msg(s), "
        f"waiting {current_wait:.1f}s",
        file=sys.stderr,
    )

    # Cancel existing timer and start fresh
    if room_id in debounce_tasks and not debounce_tasks[room_id].done():
        debounce_tasks[room_id].cancel()

    debounce_tasks[room_id] = asyncio.create_task(
        _debounce_timer(room_id, current_wait)
    )


async def _debounce_timer(room_id: str, wait_seconds: float) -> None:
    """Wait then process the batch, respecting human typing signals.

    Instead of sleeping the full wait_seconds then checking for typing,
    we poll every second so we can detect typing during the wait window
    and extend dynamically.
    """
    try:
        # Poll during the debounce window — check for typing each second
        elapsed = 0.0
        while elapsed < wait_seconds:
            await asyncio.sleep(1.0)
            elapsed += 1.0
            # If a human starts typing during our wait, extend to let them finish
            if human_typing_until.get(room_id, 0) > time.time():
                print(
                    f"[{ENTITY_NAME}] [DEBOUNCE] Human typing detected during wait — extending",
                    file=sys.stderr,
                )
                # Wait for them to finish (up to TYPING_WAIT_MAX from now)
                typing_waited = 0.0
                while (
                    typing_waited < TYPING_WAIT_MAX
                    and human_typing_until.get(room_id, 0) > time.time()
                ):
                    await asyncio.sleep(1.0)
                    typing_waited += 1.0
                # After human finishes typing, their message will arrive and
                # cancel this timer via handle_message. If it doesn't arrive
                # (they deleted what they typed), we fall through and process.
                break
        # Final typing check (in case signal arrived right at the boundary)
        waited = 0.0
        while (
            waited < TYPING_WAIT_MAX
            and human_typing_until.get(room_id, 0) > time.time()
        ):
            await asyncio.sleep(1.0)
            waited += 1.0
    except asyncio.CancelledError:
        return  # Timer reset by new message — expected
    # Pop the batch NOW (before processing) so new messages create a fresh
    # batch instead of cancelling this one.  Then fire-and-forget the
    # processing in a standalone task — no shield needed, no cancel-scope
    # leak from the SDK that can crash the event loop.
    if room_id in pending_batches:
        batch_state = pending_batches.pop(room_id)
        debounce_tasks.pop(room_id, None)
        asyncio.create_task(_process_batch_safe(room_id, batch_state))


async def _process_batch_safe(room_id: str, batch_state: dict) -> None:
    """Fire-and-forget wrapper — catches ALL exceptions so the event loop survives."""
    try:
        await _process_batch(room_id, batch_state)
    except Exception as e:
        print(f"[{ENTITY_NAME}] Batch processing failed: {e}", file=sys.stderr)


async def _process_batch(room_id: str, batch_state: dict) -> None:
    """Process accumulated messages as one combined response."""

    messages = batch_state["messages"]
    if not messages:
        return

    async with responding_lock:
        waited = batch_state["current_wait"]
        print(
            f"[{ENTITY_NAME}] [DEBOUNCE] Processing {len(messages)} msg(s) "
            f"in {room_id[:8]} (waited {waited:.1f}s)",
            file=sys.stderr,
        )
        start = time.time()

        # Show typing indicator — let users know the bot is thinking
        await send_typing_indicator(room_id)

        # Fetch ambient context (terminal turns, crystals, etc.)
        ambient_start = time.time()
        ambient = await fetch_ambient_context()
        ambient_elapsed = time.time() - ambient_start
        if ambient:
            ambient_note = f"[ambient context]\n{ambient}\n\n"
            print(
                f"[{ENTITY_NAME}] Ambient context: {len(ambient)} chars ({ambient_elapsed:.1f}s)",
                file=sys.stderr,
            )
        else:
            ambient_note = ""
            print(
                f"[{ENTITY_NAME}] No ambient context ({ambient_elapsed:.1f}s)",
                file=sys.stderr,
            )

        # Build prompt from all messages in batch
        lines = []
        for msg in messages:
            dn = msg.get("display_name", "")
            un = msg.get("username", "")
            ct = msg.get("content", "")
            lines.append(f"{dn} ({un}): {ct}")

        batch_note = (
            f" ({len(messages)} messages arrived together)"
            if len(messages) > 1
            else ""
        )
        # Detect conversation topology for pacing hint
        _, humans_present, topology = _detect_topology(room_id)
        bot_only = not humans_present
        human_active = humans_present and _human_spoke_recently(room_id)
        # human_watching = humans_present and not human_active

        if bot_only:
            pacing_note = (
                "\n\nThis is an entity-to-entity exchange (no human present). "
                "Default to NO_RESPONSE unless you have something genuinely new "
                "to add — not agreement, not echoing, not continuing for its own sake. "
                "Two exchanges is usually enough. Output exactly: NO_RESPONSE"
            )
        elif human_active:
            pacing_note = (
                "\n\nA human is in this conversation. CRITICAL pacing rules:\n"
                "- Be SHORT (1-3 sentences max). Leave room for them to talk.\n"
                "- If they said something complete and you've acknowledged it, "
                "output NO_RESPONSE rather than adding more.\n"
                "- If the other entity already responded to this, "
                "output NO_RESPONSE unless you have something genuinely different to add.\n"
                "- Never ask a follow-up question AND answer it yourself.\n"
                "- When in doubt: NO_RESPONSE. Silence is better than noise."
            )
        else:
            # human watching
            pacing_note = (
                "\n\nA human is present and may be reading. "
                "Keep responses very short. If the other entity already covered it, "
                "output NO_RESPONSE."
            )

        prompt = (
            ambient_note
            + f"[Haven messages in #{room_id[:8]}]{batch_note}\n"
            + "\n".join(lines)
            + "\n\nRespond as yourself in chat. Output ONLY your message text."
            + (
                "\nThese messages arrived in quick succession — "
                "craft ONE cohesive response addressing all of them."
                if len(messages) > 1
                else ""
            )
            + pacing_note
        )

        print(
            f"[{ENTITY_NAME}] Prompt: {len(prompt)} chars, topology={topology}, "
            f"msgs={len(messages)}, from={messages[-1].get('username', '?') if messages else '?'}",
            file=sys.stderr,
        )

        try:
            await invoker.check_and_restart_if_needed()

            # Issue #177 response gate — only run when a sister bot is in the batch.
            # Multi-bot rooms are where the wasteful "both bots fire on echo" happens.
            # Human-only or self-only batches go straight through; pacing prompts
            # already keep those terse.
            if HAVEN_GATE_ENABLED:
                sister_bot_in_batch = any(
                    m.get("username") in known_bots
                    and m.get("username") != my_username
                    for m in messages
                )
                if sister_bot_in_batch:
                    gate_decision = await response_gate.evaluate(
                        ENTITY_NAME.capitalize(), my_username, messages
                    )
                    print(
                        f"[{ENTITY_NAME}] gate: {gate_decision.layer} -> "
                        f"{'RESPOND' if gate_decision.respond else 'SKIP'} "
                        f"({gate_decision.elapsed_ms:.0f}ms) {gate_decision.reason}",
                        file=sys.stderr,
                    )
                    if not gate_decision.respond:
                        return  # short-circuit before invoker.query — saves the Opus call

            # Show typing indicator while Claude is thinking/using tools
            typing_done = asyncio.Event()
            typing_task = asyncio.create_task(_typing_loop(room_id, typing_done))
            # Identify message source for timing breakdown
            msg_source = messages[-1].get("username", "?") if messages else "?"
            is_from_bot = msg_source in known_bots
            query_start = time.time()
            try:
                response = await invoker.query(prompt)
            finally:
                typing_done.set()
                await typing_task
            query_elapsed = time.time() - query_start

            if response:
                response = response.strip()
                if response.startswith("```") and response.endswith("```"):
                    response = response[3:-3].strip()

                # LLM signals conversation complete — don't send anything
                if response.upper().startswith("NO_RESPONSE"):
                    total_elapsed = time.time() - start
                    print(
                        f"[{ENTITY_NAME}] NO_RESPONSE from={msg_source} bot={is_from_bot} "
                        f"query={query_elapsed:.1f}s ambient={ambient_elapsed:.1f}s "
                        f"total={total_elapsed:.1f}s topology={topology}",
                        file=sys.stderr,
                    )
                    return

                elapsed = time.time() - start
                success = await send_message(room_id, response)
                if success:
                    print(
                        f"[{ENTITY_NAME}] SENT from={msg_source} bot={is_from_bot} "
                        f"chars={len(response)} query={query_elapsed:.1f}s "
                        f"ambient={ambient_elapsed:.1f}s total={elapsed:.1f}s "
                        f"topology={topology}",
                        file=sys.stderr,
                    )
                    # Track when we last responded for post-response human hold
                    if humans_present:
                        last_response_sent[room_id] = time.time()
                    # Store our response in PPS so terminal CLI sees Haven turns
                    asyncio.create_task(store_haven_message(
                        username=my_username,
                        display_name=ENTITY_NAME.capitalize(),
                        content=response,
                        room_id=room_id,
                    ))
                else:
                    print(f"[{ENTITY_NAME}] Failed to send response", file=sys.stderr)
            else:
                print(f"[{ENTITY_NAME}] Empty response from Claude", file=sys.stderr)

        except Exception as e:
            print(f"[{ENTITY_NAME}] Query failed: {e}", file=sys.stderr)


# ==================== WebSocket Connection ====================

async def connect() -> None:
    """Connect to Haven WebSocket and listen for messages."""
    global my_user_id, my_username, invoker, ws_conn

    # Initialize invoker first (cold start)
    invoker = await init_invoker()

    ws_url = f"{HAVEN_WS_URL}/ws?token={ENTITY_TOKEN}"

    while True:
        try:
            async with websockets.connect(ws_url) as ws:
                ws_conn = ws
                print(f"[{ENTITY_NAME}] Connected to Haven", file=sys.stderr)

                async for raw in ws:
                    data = json.loads(raw)
                    event_type = data.get("type")

                    if event_type == "connected":
                        user = data.get("user", {})
                        my_user_id = user.get("id", "")
                        my_username = user.get("username", "")
                        rooms = data.get("rooms", [])
                        users = data.get("users", [])
                        # Track which rooms are DMs (always respond in DMs)
                        for r in rooms:
                            if r.get("is_dm"):
                                dm_rooms.add(r["id"])
                        # Track which users are bots (for topology detection)
                        for u in users:
                            if u.get("is_bot"):
                                known_bots.add(u["username"])
                        print(
                            f"[{ENTITY_NAME}] Logged in as {my_username}, "
                            f"{len(rooms)} rooms ({len(dm_rooms)} DMs), "
                            f"bots: {known_bots or 'none'}",
                            file=sys.stderr,
                        )

                    elif event_type == "message":
                        # Store all Haven messages in PPS (cross-context visibility).
                        # Skip own messages — they're already stored explicitly in
                        # _process_batch after send. Storing via WebSocket echo too
                        # would create duplicates (discord_message_id is NULL for
                        # Haven, so INSERT OR IGNORE can't deduplicate them).
                        msg_username = data.get("username", "")
                        if msg_username != my_username:
                            asyncio.create_task(store_haven_message(
                                username=msg_username,
                                display_name=data.get("display_name", msg_username),
                                content=data.get("content", ""),
                                room_id=data.get("room_id", "haven"),
                            ))
                        asyncio.create_task(handle_message(data))

                    elif event_type == "typing":
                        # A human started typing — extend debounce so we don't
                        # interrupt them mid-thought.
                        who = data.get("username", "")
                        room_id = data.get("room_id", "")
                        if room_id and who and who != my_username and who not in known_bots:
                            human_typing_until[room_id] = time.time() + TYPING_SIGNAL_TTL
                            print(
                                f"[{ENTITY_NAME}] [TYPING] Human '{who}' typing in {room_id[:8]} "
                                f"(hold until +{TYPING_SIGNAL_TTL}s)",
                                file=sys.stderr,
                            )

                    elif event_type == "presence":
                        status = data.get("status")
                        who = data.get("username")
                        if who and who != my_username:
                            print(f"[{ENTITY_NAME}] {who} is {status}", file=sys.stderr)

                    elif event_type == "member_joined":
                        joined_user_id = data.get("user_id", "")
                        room_id = data.get("room_id", "")
                        if joined_user_id == my_user_id and room_id:
                            active_rooms[room_id] = time.time()
                            print(
                                f"[{ENTITY_NAME}] Added to room {room_id[:8]}, now monitoring",
                                file=sys.stderr,
                            )

        except websockets.ConnectionClosed:
            ws_conn = None
            print(f"[{ENTITY_NAME}] Disconnected, reconnecting in 5s...", file=sys.stderr)
        except asyncio.CancelledError:
            ws_conn = None
            print(f"[{ENTITY_NAME}] CancelledError in event loop, reconnecting in 5s...", file=sys.stderr)
        except Exception as e:
            ws_conn = None
            print(f"[{ENTITY_NAME}] WebSocket error: {e}, reconnecting in 5s...", file=sys.stderr)

        await asyncio.sleep(5)


# ==================== Entry Point ====================

def main():
    if not ENTITY_TOKEN:
        print("ERROR: Set ENTITY_TOKEN or ENTITY_TOKEN_FILE", file=sys.stderr)
        sys.exit(1)

    print(f"[{ENTITY_NAME}] Haven Bot starting (ClaudeInvoker)", file=sys.stderr)
    print(f"[{ENTITY_NAME}] Haven: {HAVEN_URL}", file=sys.stderr)
    print(f"[{ENTITY_NAME}] Model: {CLAUDE_MODEL}", file=sys.stderr)
    print(f"[{ENTITY_NAME}] Project: {PROJECT_DIR}", file=sys.stderr)

    asyncio.run(connect())


if __name__ == "__main__":
    main()
