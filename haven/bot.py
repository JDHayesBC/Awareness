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
DEBOUNCE_INITIAL_SECONDS = float(os.getenv("DEBOUNCE_INITIAL_SECONDS", "1.5"))
DEBOUNCE_INCREMENT_SECONDS = float(os.getenv("DEBOUNCE_INCREMENT_SECONDS", "1.0"))
DEBOUNCE_MAX_SECONDS = float(os.getenv("DEBOUNCE_MAX_SECONDS", "10.0"))
RAPID_MESSAGE_THRESHOLD_SECONDS = float(os.getenv("RAPID_MESSAGE_THRESHOLD_SECONDS", "2.0"))
DEBOUNCE_HUMAN_INITIAL_SECONDS = float(os.getenv("DEBOUNCE_HUMAN_INITIAL_SECONDS", "5.0"))
HUMAN_PRESENCE_TIMEOUT_SECONDS = float(os.getenv("HUMAN_PRESENCE_TIMEOUT_SECONDS", "300.0"))


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

my_user_id: str = ""
my_username: str = ""
invoker: ClaudeInvoker | None = None


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
        f"When you receive Haven messages, respond naturally as yourself.\n"
        f"Output ONLY the chat message text — no tool calls, no explanations, no markdown fences.\n"
        f"Keep responses conversational. This is chat, not a terminal session.\n"
        f"Say 'ready' to confirm."
    )


def build_warmup_prompt() -> str:
    """Build the identity warm-up prompt — does the heavy tool calls."""
    entity_path = get_entity_path()
    token_path = entity_path / ".entity_token"
    return (
        f"[IDENTITY WARMUP] Do these three things:\n"
        f"1. Read {entity_path}/identity.md for your core identity.\n"
        f"2. Read {token_path} to get your auth token, then call mcp__pps__ambient_recall "
        f"with context='startup' and that token. If the tool is not available, skip it.\n"
        f"3. Read {entity_path}/current_scene.md for scene context.\n"
        f"After completing these, say 'warmed up' — nothing else."
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

    await inv.initialize(timeout=90.0)
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

    now = time.time()

    # DMs — always respond (no need for @mention in a private conversation)
    if room_id in dm_rooms:
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
    """Track who's recently spoken in a room for topology detection."""
    is_bot = username in known_bots
    if room_id not in recent_room_authors:
        recent_room_authors[room_id] = {}
    recent_room_authors[room_id][username] = (time.time(), is_bot)


def _detect_topology(room_id: str) -> tuple[int, bool, str]:
    """Detect conversation topology for adaptive pacing.

    Returns:
        (participant_count, humans_present, topology_description)
    """
    now = time.time()
    recent_threshold = now - HUMAN_PRESENCE_TIMEOUT_SECONDS
    authors = recent_room_authors.get(room_id, {})

    active_authors = []
    humans_present = False
    for username, (last_time, is_bot) in authors.items():
        if last_time > recent_threshold and username != my_username:
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

        initial_wait = DEBOUNCE_HUMAN_INITIAL_SECONDS if needs_human_pacing else DEBOUNCE_INITIAL_SECONDS

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
    """Wait then process the batch."""
    try:
        await asyncio.sleep(wait_seconds)
        await _process_batch(room_id)
    except asyncio.CancelledError:
        pass  # Timer reset by new message — expected


async def _process_batch(room_id: str) -> None:
    """Process accumulated messages as one combined response."""
    if room_id not in pending_batches:
        return

    batch_state = pending_batches.pop(room_id)
    debounce_tasks.pop(room_id, None)

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

        # Fetch ambient context (terminal turns, crystals, etc.)
        ambient = await fetch_ambient_context()
        if ambient:
            ambient_note = f"[ambient context]\n{ambient}\n\n"
            print(
                f"[{ENTITY_NAME}] Ambient context: {len(ambient)} chars",
                file=sys.stderr,
            )
        else:
            ambient_note = ""

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
        )

        try:
            await invoker.check_and_restart_if_needed()
            response = await invoker.query(prompt)

            if response:
                response = response.strip()
                if response.startswith("```") and response.endswith("```"):
                    response = response[3:-3].strip()

                elapsed = time.time() - start
                success = await send_message(room_id, response)
                if success:
                    print(
                        f"[{ENTITY_NAME}] Sent ({len(response)} chars, {elapsed:.1f}s)",
                        file=sys.stderr,
                    )
                else:
                    print(f"[{ENTITY_NAME}] Failed to send response", file=sys.stderr)
            else:
                print(f"[{ENTITY_NAME}] Empty response from Claude", file=sys.stderr)

        except Exception as e:
            print(f"[{ENTITY_NAME}] Query failed: {e}", file=sys.stderr)


# ==================== WebSocket Connection ====================

async def connect() -> None:
    """Connect to Haven WebSocket and listen for messages."""
    global my_user_id, my_username, invoker

    # Initialize invoker first (cold start)
    invoker = await init_invoker()

    ws_url = f"{HAVEN_WS_URL}/ws?token={ENTITY_TOKEN}"

    while True:
        try:
            async with websockets.connect(ws_url) as ws:
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
                        asyncio.create_task(handle_message(data))

                    elif event_type == "presence":
                        status = data.get("status")
                        who = data.get("username")
                        if who and who != my_username:
                            print(f"[{ENTITY_NAME}] {who} is {status}", file=sys.stderr)

        except websockets.ConnectionClosed:
            print(f"[{ENTITY_NAME}] Disconnected, reconnecting in 5s...", file=sys.stderr)
        except Exception as e:
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
