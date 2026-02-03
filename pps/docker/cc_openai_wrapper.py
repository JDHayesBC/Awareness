#!/usr/bin/env python3
"""
OpenAI-Compatible Wrapper for ClaudeInvoker

Provides OpenAI /v1/chat/completions endpoint using ClaudeInvoker backend.
Eliminates Graphiti's OpenAI API costs while leveraging Jeff's Claude subscription.

Architecture:
    Graphiti → /v1/chat/completions (OpenAI format)
              ↓
    This wrapper (translation)
              ↓
    ClaudeInvoker (persistent Claude connection)
              ↓
    Claude Code CLI

Hardened for production use:
    - Zero-downtime restarts (requests queue during restart, never 503)
    - Role priming after restart (no identity confusion)
    - Proactive restart at 80% context (restart between requests)
    - Response validation with retry (no empty responses)
    - Request-level retry on failure
    - Full observability (timing, context %, restart counts)

Usage:
    docker compose up pps-haiku-wrapper

    curl http://localhost:8000/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d '{
            "model": "haiku",
            "messages": [
                {"role": "system", "content": "You are an entity extractor."},
                {"role": "user", "content": "Extract entities from: Jeff loves coffee"}
            ]
        }'
"""

import asyncio
import gc
import json
import os
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# Add daemon directory to path for ClaudeInvoker import
sys.path.insert(0, str(Path(__file__).parent / "daemon"))

from cc_invoker.invoker import ClaudeInvoker, InvokerQueryError


# =============================================================================
# Configuration
# =============================================================================

STARTUP_PROMPT = (
    "You are a stateless JSON extraction API. "
    "You receive requests in 'System: ... User: ...' format. "
    "Respond with exactly what is requested - typically raw JSON. "
    "Do not introduce yourself. Do not explain what you are. "
    "Do not wrap JSON in markdown code fences. "
    "Just output the requested content directly."
)

# Verbose mode for debugging extraction issues
# Set WRAPPER_VERBOSE=1 to log full prompts and responses
VERBOSE = os.getenv("WRAPPER_VERBOSE", "0") == "1"


# =============================================================================
# Request/Response Models (OpenAI Chat Completions format)
# =============================================================================

class Message(BaseModel):
    """Single message in OpenAI format."""
    role: str  # "system", "user", or "assistant"
    content: str


class ChatCompletionRequest(BaseModel):
    """OpenAI /v1/chat/completions request format."""
    model: str
    messages: list[Message]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    response_format: Optional[dict[str, Any]] = None
    # Ignore other OpenAI params (stream, top_p, etc.) - not needed for extraction


class ChatMessage(BaseModel):
    """Message in response."""
    role: str
    content: str


class Choice(BaseModel):
    """Single completion choice."""
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    """Token usage statistics (estimated)."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    """OpenAI /v1/chat/completions response format."""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage


# =============================================================================
# Global State
# =============================================================================

invoker: Optional[ClaudeInvoker] = None

# Zero-downtime restart coordination
_ready_event: asyncio.Event = None  # Initialized in lifespan (needs running loop)
_restart_lock: asyncio.Lock = None

# Track in-flight requests to prevent killing subprocess mid-query
_active_queries = 0
_no_active_queries: asyncio.Event = None  # Set when _active_queries == 0

# Unrecoverable state tracking (Issue #128)
_wrapper_offline = False
_offline_reason = ""

# Observability counters
_restart_count = 0
_total_requests = 0
_total_errors = 0


# =============================================================================
# Helpers
# =============================================================================

def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def strip_markdown_fences(text: str) -> str:
    """Strip markdown code fences from Claude responses.

    Claude wraps JSON in ```json ... ``` fences. Callers expecting raw JSON
    (like Graphiti's json.loads()) need the fences removed.
    """
    # Match ```json\n...\n``` or ```\n...\n```
    match = re.match(r'^```(?:json)?\s*\n(.*?)\n```\s*$', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


# =============================================================================
# Restart Management
# =============================================================================

async def _perform_restart(reason: str):
    """Restart invoker while blocking new requests.

    Uses _restart_lock to prevent concurrent restarts and _ready_event
    to queue incoming requests during the restart window.

    Recovery strategy:
    - Block new requests (clear _ready_event)
    - Wait for in-flight queries to drain (prevents _reconnect_with_backoff chaos)
    - Kill old invoker subprocess
    - Force garbage collection
    - Initialize fresh invoker
    - If that fails, schedule background retry loop
    """
    global invoker, _restart_count

    if _restart_lock.locked():
        # Another restart already in progress, just wait for it
        await _ready_event.wait()
        return

    async with _restart_lock:
        _ready_event.clear()
        try:
            print(f"[RESTART] Starting: {reason}", flush=True)
            start = time.monotonic()

            # Log memory before cleanup (if psutil available)
            mem_before = None
            if PSUTIL_AVAILABLE:
                try:
                    mem_before = psutil.Process().memory_info().rss / 1024 / 1024
                    print(f"[RESTART] Memory before: {mem_before:.1f} MB", flush=True)
                except Exception:
                    pass

            # CRITICAL: Wait for in-flight queries to complete before killing subprocess.
            # Without this, killing the subprocess causes in-flight queries to fail,
            # which triggers the OLD invoker's _reconnect_with_backoff() method.
            # That old invoker keeps trying to reconnect for 60s × 5 attempts = chaos.
            if _active_queries > 0:
                print(f"[RESTART] Waiting for {_active_queries} in-flight queries to drain...", flush=True)
                try:
                    await asyncio.wait_for(_no_active_queries.wait(), timeout=60.0)
                    print("[RESTART] All queries drained", flush=True)
                except asyncio.TimeoutError:
                    print(f"[RESTART] Timeout waiting for queries to drain, proceeding anyway", flush=True)

            # CRITICAL: Kill old invoker subprocess BEFORE creating new one
            # Without this, old invoker subprocesses accumulate in memory
            # (9.7GB leak after 8 restarts - each Claude Code process stays alive)
            #
            # We can't call invoker.shutdown() because it calls _client.disconnect()
            # which hits an anyio cancel scope bug. Instead, we forcefully kill
            # all child processes using psutil, then drop the reference.
            if invoker is not None:
                print("[RESTART] Killing old invoker subprocess...", flush=True)

                # Kill all child processes (the Claude Code CLI subprocess)
                if PSUTIL_AVAILABLE:
                    try:
                        current = psutil.Process()
                        children = current.children(recursive=True)
                        if children:
                            print(f"[RESTART] Found {len(children)} child processes to kill", flush=True)
                            for child in children:
                                try:
                                    print(f"[RESTART] Killing PID {child.pid} ({child.name()}) status={child.status()}", flush=True)
                                    child.kill()
                                except psutil.NoSuchProcess:
                                    print(f"[RESTART] PID {child.pid} already dead", flush=True)

                            # Wait and report results
                            gone, alive = psutil.wait_procs(children, timeout=5)
                            print(f"[RESTART] Killed: {len(gone)}, Still alive: {len(alive)}", flush=True)

                            # Force kill any survivors
                            for p in alive:
                                try:
                                    p.kill()
                                except Exception:
                                    pass
                        else:
                            print("[RESTART] No child processes to kill", flush=True)
                    except Exception as e:
                        print(f"[RESTART] Error killing children: {type(e).__name__}: {e}", flush=True)

                # Now drop the reference and GC
                old_invoker = invoker
                invoker = None
                del old_invoker
                gc.collect()
                print("[RESTART] Old invoker killed and released", flush=True)

            # Now create fresh invoker
            await initialize_invoker()

            # Verify new invoker is actually connected (Issue #128)
            if invoker is None or not invoker.is_connected:
                raise Exception("New invoker failed to connect")

            elapsed = time.monotonic() - start
            _restart_count += 1

            # Log memory after restart (if psutil available)
            if PSUTIL_AVAILABLE and mem_before is not None:
                try:
                    mem_after = psutil.Process().memory_info().rss / 1024 / 1024
                    mem_delta = mem_after - mem_before
                    print(f"[RESTART] Memory after: {mem_after:.1f} MB (delta: {mem_delta:+.1f} MB)", flush=True)
                except Exception:
                    pass

            print(f"[RESTART] Complete in {elapsed:.1f}s (total restarts: {_restart_count})", flush=True)
        except Exception as e:
            print(f"[RESTART] FAILED: {e}", flush=True)
            print("[RESTART] Scheduling background recovery...", flush=True)
            asyncio.create_task(_background_recovery())
        finally:
            _ready_event.set()


async def _background_recovery():
    """Recover invoker connection in the background after double failure.

    Retries with exponential backoff: 4s, 8s, 16s, 32s, 60s.
    During recovery, incoming requests get 502 (better than hanging).
    """
    global invoker, _restart_count, _wrapper_offline, _offline_reason

    for attempt in range(1, 6):
        delay = min(2 ** (attempt + 1), 60)
        print(f"[RECOVERY] Attempt {attempt}/5 in {delay}s...", flush=True)
        await asyncio.sleep(delay)

        # Check if main restart succeeded while we were waiting
        if invoker is not None and invoker.is_connected:
            print(f"[RECOVERY] Aborting - invoker already connected (main restart succeeded)", flush=True)
            # Clear offline state if it was set
            _wrapper_offline = False
            _offline_reason = ""
            return

        try:
            # Wait for in-flight queries to drain before killing subprocess
            if _active_queries > 0:
                print(f"[RECOVERY] Waiting for {_active_queries} in-flight queries to drain...", flush=True)
                try:
                    await asyncio.wait_for(_no_active_queries.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    print("[RECOVERY] Timeout waiting for queries, proceeding anyway", flush=True)

            # Kill old invoker subprocess before recovery attempt
            # (Don't call shutdown() - it hits the cancel scope bug)
            if invoker is not None:
                if PSUTIL_AVAILABLE:
                    try:
                        for child in psutil.Process().children(recursive=True):
                            child.kill()
                        psutil.wait_procs(psutil.Process().children(), timeout=5)
                    except Exception:
                        pass
                old_invoker = invoker
                invoker = None
                del old_invoker
                gc.collect()

            await initialize_invoker()

            # Verify new invoker is connected (Issue #128)
            if invoker is None or not invoker.is_connected:
                raise Exception("New invoker failed to connect")

            _restart_count += 1
            # Clear offline state on successful recovery
            _wrapper_offline = False
            _offline_reason = ""
            print(f"[RECOVERY] Success on attempt {attempt} (total restarts: {_restart_count})", flush=True)
            return
        except Exception as e:
            print(f"[RECOVERY] Attempt {attempt} failed: {e}", flush=True)

    # All recovery attempts exhausted - set offline state (Issue #128)
    _wrapper_offline = True
    _offline_reason = "All 5 recovery attempts exhausted. Manual restart required."
    print(f"[RECOVERY] {_offline_reason}", flush=True)


# =============================================================================
# Lifecycle
# =============================================================================

async def initialize_invoker():
    """Initialize ClaudeInvoker on startup."""
    global invoker

    model = os.getenv("WRAPPER_MODEL", "haiku")

    print(f"Initializing ClaudeInvoker (model={model})...")
    print("This takes ~33s for initial connection...")

    start = time.time()

    invoker = ClaudeInvoker(
        model=model,
        bypass_permissions=False,
        startup_prompt=STARTUP_PROMPT,
        mcp_servers={},
        max_context_tokens=150_000,
        max_turns=10,
    )

    await invoker.initialize()

    elapsed = time.time() - start
    print(f"Initialized in {elapsed:.1f}s")
    print(f"  Model: {model}")
    print(f"  Context limits: {invoker.max_context_tokens} tokens, {invoker.max_turns} turns")
    print(f"  Startup prompt: {len(STARTUP_PROMPT)} chars")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    global _ready_event, _restart_lock, _no_active_queries

    # Initialize async primitives (need running event loop)
    _ready_event = asyncio.Event()
    _restart_lock = asyncio.Lock()
    _no_active_queries = asyncio.Event()
    _no_active_queries.set()  # Initially no queries, so event is set

    # Startup
    await initialize_invoker()
    _ready_event.set()  # Signal ready for requests

    yield

    # Shutdown
    if invoker:
        await invoker.shutdown()
        print("ClaudeInvoker shut down")


app = FastAPI(
    title="Claude Code OpenAI Wrapper",
    description="OpenAI-compatible wrapper for ClaudeInvoker",
    version="0.2.0",
    lifespan=lifespan
)


# =============================================================================
# Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check for Docker."""
    # Get memory stats if psutil available
    memory_info = None
    if PSUTIL_AVAILABLE:
        try:
            process = psutil.Process()
            mem = process.memory_info()
            memory_info = {
                "rss_mb": round(mem.rss / 1024 / 1024, 1),
                "vms_mb": round(mem.vms / 1024 / 1024, 1),
            }
        except Exception:
            pass  # Silently skip if psutil fails

    # Check offline state first (Issue #128)
    if _wrapper_offline:
        response = {
            "status": "offline",
            "message": _offline_reason,
            "recovery_attempts": 5,
            "stats": {
                "total_requests": _total_requests,
                "total_errors": _total_errors,
                "restart_count": _restart_count,
            }
        }
        if memory_info:
            response["memory"] = memory_info
        return JSONResponse(status_code=503, content=response)

    if invoker is None:
        response = {"status": "starting", "message": "Invoker not yet created"}
        if memory_info:
            response["memory"] = memory_info
        return JSONResponse(status_code=503, content=response)

    restarting = not _ready_event.is_set() if _ready_event else False

    # During restart, report as healthy but restarting
    # (the invoker will be back shortly — don't fail Docker health checks)
    if restarting:
        response = {
            "status": "restarting",
            "invoker_connected": False,
            "active_queries": _active_queries,
            "stats": {
                "total_requests": _total_requests,
                "total_errors": _total_errors,
                "restart_count": _restart_count,
            }
        }
        if memory_info:
            response["memory"] = memory_info
        return response

    stats = invoker.context_stats

    response = {
        "status": "healthy",
        "invoker_connected": invoker.is_connected,
        "verbose_mode": VERBOSE,
        "active_queries": _active_queries,
        "context_usage": {
            "tokens": stats["total_tokens"],
            "turns": stats["turn_count"],
            "token_limit": invoker.max_context_tokens,
            "turn_limit": invoker.max_turns,
            "token_pct": round(stats["total_tokens"] / max(invoker.max_context_tokens, 1) * 100, 1),
            "turn_pct": round(stats["turn_count"] / max(invoker.max_turns, 1) * 100, 1),
        },
        "stats": {
            "total_requests": _total_requests,
            "total_errors": _total_errors,
            "restart_count": _restart_count,
        }
    }
    if memory_info:
        response["memory"] = memory_info

    return response


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """
    OpenAI-compatible chat completions endpoint.

    Translates OpenAI format → ClaudeInvoker → OpenAI format.
    Handles restarts transparently — requests queue instead of failing.
    """
    global _total_requests, _total_errors, _active_queries

    _total_requests += 1

    # Check offline state first (Issue #128)
    if _wrapper_offline:
        _total_errors += 1
        raise HTTPException(
            status_code=503,
            detail=f"Wrapper offline - {_offline_reason}"
        )

    if invoker is None:
        raise HTTPException(status_code=503, detail="Invoker not initialized")

    # Wait for readiness (blocks during restart instead of returning 503)
    try:
        await asyncio.wait_for(_ready_event.wait(), timeout=30.0)
    except asyncio.TimeoutError:
        _total_errors += 1
        raise HTTPException(
            status_code=504,
            detail="Timed out waiting for invoker restart"
        )

    # If invoker is disconnected (e.g., previous restart failed), recover
    if not invoker.is_connected:
        print("[WARN] Invoker disconnected, attempting recovery...", flush=True)
        await _perform_restart("invoker_disconnected")
        if not invoker.is_connected:
            _total_errors += 1
            raise HTTPException(status_code=503, detail="Invoker disconnected and recovery failed")

    # Check for proactive restart BEFORE tracking as active query.
    # This prevents deadlock: restart waits for queries, but we haven't started yet.
    approaching, approach_reason = invoker.approaching_restart()
    if approaching:
        print(f"[PROACTIVE] Inline restart: {approach_reason}", flush=True)
        await _perform_restart(f"proactive: {approach_reason}")

    # Hard restart at 100% — safety net
    needs_restart, reason = invoker.needs_restart()
    if needs_restart:
        await _perform_restart(reason)

    # NOW track as active query - restart checks are done
    _active_queries += 1
    _no_active_queries.clear()
    
    try:
        # Build prompt from OpenAI messages
        wants_json = request.response_format and request.response_format.get("type") in (
            "json_object", "json_schema"
        )

        prompt_parts = []
        for msg in request.messages:
            if msg.role == "system":
                prompt_parts.append(f"System: {msg.content}")
            elif msg.role == "user":
                prompt_parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                prompt_parts.append(f"Assistant: {msg.content}")

        # When caller requests JSON output, tell Claude explicitly
        if wants_json:
            json_instruction = (
                "IMPORTANT: Respond with raw JSON only. "
                "No markdown formatting, no code fences, no explanation. "
                "Just the JSON object."
            )

            # If a JSON schema is provided, include it so Claude uses exact field names
            if request.response_format.get("type") == "json_schema":
                schema_info = request.response_format.get("json_schema", {})
                schema = schema_info.get("schema")
                if schema:
                    json_instruction += (
                        f"\n\nYour response MUST conform to this JSON schema:\n"
                        f"{json.dumps(schema, indent=2)}"
                    )

            prompt_parts.append(json_instruction)

        combined_prompt = "\n\n".join(prompt_parts)

        # Verbose logging: dump full prompt
        if VERBOSE:
            print("=" * 80, flush=True)
            print("[VERBOSE] PROMPT:", flush=True)
            print("-" * 40, flush=True)
            print(combined_prompt, flush=True)
            print("-" * 40, flush=True)

        # Log request
        prompt_tokens = estimate_tokens(combined_prompt)
        schema_name = ""
        if wants_json and request.response_format.get("type") == "json_schema":
            schema_name = request.response_format.get("json_schema", {}).get("name", "unknown")

        query_start = time.monotonic()

        # Query with retry logic
        response_text = await _query_with_retry(combined_prompt)

        # Validate response (retry once on empty)
        if not response_text or not response_text.strip():
            print("[WARN] Empty response, retrying once...", flush=True)
            response_text = await _query_with_retry(combined_prompt)

        if not response_text or not response_text.strip():
            _total_errors += 1
            print("[ERROR] Empty response after retry", flush=True)
            raise HTTPException(status_code=502, detail="Backend returned empty response")

        # Strip markdown fences if caller expects JSON
        if wants_json:
            response_text = strip_markdown_fences(response_text)

        # Verbose logging: dump full response
        if VERBOSE:
            print("[VERBOSE] RESPONSE:", flush=True)
            print("-" * 40, flush=True)
            print(response_text, flush=True)
            print("-" * 40, flush=True)
            print("=" * 80, flush=True)

        # Timing and observability
        query_elapsed = time.monotonic() - query_start
        completion_tokens = estimate_tokens(response_text)
        stats = invoker.context_stats
        print(
            f"[DONE] {query_elapsed:.1f}s | "
            f"ctx={stats['total_tokens']}/{invoker.max_context_tokens} "
            f"({stats['total_tokens'] * 100 // max(invoker.max_context_tokens, 1)}%) | "
            f"turns={stats['turn_count']}/{invoker.max_turns} | "
            f"schema={schema_name or 'none'}",
            flush=True
        )

        # Build OpenAI-compatible response
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
            created=int(time.time()),
            model=request.model,
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=response_text
                    ),
                    finish_reason="stop"
                )
            ],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens
            )
        )
    finally:
        # Always decrement, even on error
        _active_queries -= 1
        if _active_queries == 0:
            _no_active_queries.set()


async def _query_with_retry(prompt: str) -> str:
    """Query invoker with retry on failure.

    Leverages InvokerQueryError.retried flag — if the invoker already
    did a reconnect+retry internally, we don't pile on. If it was a
    non-connection error, we retry once at the wrapper level.
    """
    global _total_errors

    try:
        return await invoker.query(prompt)
    except InvokerQueryError as e:
        if e.retried:
            # Invoker already retried (connection error + reconnect), don't pile on
            _total_errors += 1
            print(f"[ERROR] Query failed after invoker retry: {e}", flush=True)
            raise HTTPException(status_code=502, detail=f"Query failed after retry: {e}")
        else:
            # Non-connection error, retry once at wrapper level
            print(f"[WARN] Query failed ({e}), retrying once...", flush=True)
            try:
                return await invoker.query(prompt)
            except Exception as retry_err:
                _total_errors += 1
                print(f"[ERROR] Retry also failed: {retry_err}", flush=True)
                raise HTTPException(status_code=502, detail=f"Query failed after retry: {retry_err}")
    except Exception as e:
        _total_errors += 1
        print(f"[ERROR] Unexpected query error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
