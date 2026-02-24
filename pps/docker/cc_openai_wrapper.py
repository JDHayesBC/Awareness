#!/usr/bin/env python3
"""
OpenAI-Compatible Wrapper — Stateless SDK Query

Provides OpenAI /v1/chat/completions endpoint using the claude_agent_sdk
stateless query() function. Eliminates Graphiti's OpenAI API costs while
leveraging Jeff's Claude subscription.

Architecture:
    Graphiti → /v1/chat/completions (OpenAI format)
              ↓
    This wrapper (translation + schema enforcement)
              ↓
    claude_agent_sdk.query() (stateless, fresh session per call)
              ↓
    Claude Code CLI → Claude API (via CC subscription, free)

Each call spawns a fresh subprocess with zero conversation history.
This eliminates context accumulation (root cause of 19-127s escalating latency)
and schema confusion (context bleed from prior calls).

Measured: ~5.9s/call (steady, no escalation) vs 19-127s/call (ClaudeSDKClient).

Usage:
    docker compose up pps-haiku-wrapper

    curl http://localhost:8000/v1/chat/completions \\
        -H "Content-Type: application/json" \\
        -d '{
            "model": "haiku",
            "messages": [
                {"role": "system", "content": "You are an entity extractor."},
                {"role": "user", "content": "Extract entities from: Jeff loves coffee"}
            ]
        }'
"""

import asyncio
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
import anthropic

from claude_agent_sdk import query as sdk_query, ClaudeAgentOptions
from claude_agent_sdk.types import AssistantMessage, TextBlock

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# =============================================================================
# Configuration
# =============================================================================

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

# Persistent Anthropic client for json_schema fallback path
_anthropic_client: Optional[anthropic.Anthropic] = None

# SDK options — initialized in lifespan (model comes from env var at runtime)
_SDK_OPTIONS: Optional[ClaudeAgentOptions] = None

# Observability counters
_total_requests = 0
_total_errors = 0
_schema_invoker_count = 0   # json_schema calls handled via SDK query (free)
_schema_fallback_count = 0  # json_schema calls that fell back to direct API (paid)


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
# Stateless Query
# =============================================================================

async def _stateless_query(prompt: str) -> str:
    """Send a single stateless query via the SDK's query() function.

    Each call spawns a fresh Claude Code subprocess with zero conversation
    history. This eliminates context accumulation and schema confusion.
    ~5.9s per call (4s connect + 1-2s LLM).
    """
    response_text = ""
    try:
        async for msg in sdk_query(prompt=prompt, options=_SDK_OPTIONS):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        response_text += block.text
    except Exception as e:
        error_str = str(e)
        # The SDK may throw on unknown message types (e.g., rate_limit_event)
        # that arrive after the response content. If we already have text,
        # treat it as a success — the content was delivered before the error.
        if response_text.strip() and "Unknown message type" in error_str:
            print(f"[SDK] Ignoring post-response parse error: {error_str}", flush=True)
            return response_text
        raise HTTPException(status_code=502, detail=f"SDK query failed: {error_str}")
    return response_text


# =============================================================================
# Lifecycle
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    global _anthropic_client, _SDK_OPTIONS

    # Initialize persistent Anthropic client for json_schema fallback path
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
        print("[INIT] Persistent Anthropic client created (fallback only)", flush=True)
        # CRITICAL: Remove ANTHROPIC_API_KEY from environment so the claude CLI
        # subprocess uses CC subscription credentials instead of the paid API key.
        # Without this, every "free" SDK call is actually a paid API call — the
        # claude CLI picks up ANTHROPIC_API_KEY and uses it.
        del os.environ["ANTHROPIC_API_KEY"]
        print("[INIT] Removed ANTHROPIC_API_KEY from env (claude CLI will use CC subscription)", flush=True)
    else:
        print("[INIT] WARNING: No ANTHROPIC_API_KEY set, json_schema fallback will fail", flush=True)

    # Configure SDK options — stateless query per call, no persistent session
    model = os.getenv("WRAPPER_MODEL", "haiku")
    _SDK_OPTIONS = ClaudeAgentOptions(
        model=model,
        system_prompt=(
            "You are a stateless JSON extraction API. "
            "Respond with exactly what is requested - typically raw JSON. "
            "Do not wrap JSON in markdown code fences. "
            "Just output the requested content directly."
        ),
        setting_sources=[],
        tools=[],
        max_turns=1,
        cwd="/tmp",
        # NOTE: "bypassPermissions" maps to --dangerously-skip-permissions which
        # the Claude CLI refuses when running as root (Docker). Use "acceptEdits"
        # instead — auto-accepts tool use without the root restriction.
        # With tools=[] and max_turns=1, there's nothing to approve anyway.
        permission_mode="acceptEdits",
    )
    print(f"[INIT] SDK options configured (model={model}, stateless query mode)", flush=True)

    yield

    # No persistent connection to shut down — SDK cleans up after each call
    print("[SHUTDOWN] Wrapper stopped", flush=True)


app = FastAPI(
    title="Claude Code OpenAI Wrapper",
    description="OpenAI-compatible wrapper using stateless sdk_query()",
    version="0.3.0",
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

    response = {
        "status": "healthy",
        "verbose_mode": VERBOSE,
        "stats": {
            "total_requests": _total_requests,
            "total_errors": _total_errors,
            "schema_invoker_count": _schema_invoker_count,
            "schema_fallback_count": _schema_fallback_count,
            "schema_fallback_rate": (
                round(_schema_fallback_count / max(_schema_invoker_count + _schema_fallback_count, 1) * 100, 1)
            ),
        }
    }
    if memory_info:
        response["memory"] = memory_info

    return response


def _deref_json_schema(schema: dict) -> dict:
    """Inline JSON Schema $ref references to remove $defs.

    Haiku gets confused by $ref/$defs in the schema passed to tool_use,
    sometimes returning the $defs contents instead of actual data.
    Inlining all $refs produces a flat, unambiguous schema.

    Only handles the simple case: $ref pointing to #/$defs/<Name>.
    """
    try:
        defs = schema.get("$defs", {})
        if not defs:
            return schema  # No $defs, nothing to inline

        # graphiti_core schemas are acyclic, but guard against pathological input
        def resolve(node: Any, seen: frozenset = frozenset()) -> Any:
            if isinstance(node, dict):
                if "$ref" in node and len(node) == 1:
                    # Pure $ref — inline the definition
                    ref = node["$ref"]
                    if ref.startswith("#/$defs/"):
                        def_name = ref[len("#/$defs/"):]
                        if def_name in defs and def_name not in seen:
                            return resolve(defs[def_name], seen | {def_name})
                        elif def_name in seen:
                            # Circular ref detected — return as-is to break the cycle
                            return node
                    return node  # Unknown $ref, leave as-is
                else:
                    return {k: resolve(v, seen) for k, v in node.items() if k != "$defs"}
            elif isinstance(node, list):
                return [resolve(item, seen) for item in node]
            else:
                return node

        return resolve(schema)
    except Exception as e:
        print(f"[TOOL-USE] WARNING: schema deref failed: {e}", flush=True)
        return schema


def _try_repair_json(value: str) -> Any:
    """Attempt to parse a JSON string, with fallback repair heuristics.

    Tries standard json.loads first, then applies several repair patterns
    for known Haiku malformation modes.

    Returns the parsed value on success, or raises ValueError on failure.
    """
    # Pass 1: standard parse
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        pass

    # Pass 2: quote bare UPPER_CASE identifiers after colons
    # e.g.  "relation_type": WEARS,  ->  "relation_type": "WEARS",
    repaired = re.sub(
        r':\s*([A-Z_][A-Z_0-9]*)([,\n\r\]}])',
        r': "\1"\2',
        value,
    )
    try:
        return json.loads(repaired)
    except (json.JSONDecodeError, ValueError):
        pass

    # Pass 3: remove trailing commas before ] or }
    repaired2 = re.sub(r',\s*([\]}])', r'\1', repaired)
    try:
        return json.loads(repaired2)
    except (json.JSONDecodeError, ValueError):
        pass

    raise ValueError(f"All repair passes failed for value starting with: {value[:80]!r}")


def _fix_tool_output(schema_name: str, output: Any) -> Any:
    """Apply recovery heuristics for known Haiku tool_use failure modes.

    Haiku occasionally misinterprets $ref schemas and returns:
    1. Arrays or objects serialized as JSON strings (e.g., "edges": "[...]")
    2. $defs contents instead of the actual data field (e.g., {"defs": {...}} instead of {"edges": [...]})

    This function detects and fixes both patterns.

    Diagnostic logging is always emitted for any string field > 10 chars so that
    future failures leave a clear trail of what Haiku actually returned (Issue #146).

    Args:
        schema_name: Name of the schema (for logging)
        output: The raw tool_use block input from Anthropic

    Returns:
        Fixed output dict, or original if no fix needed
    """
    try:
        if not isinstance(output, dict):
            return output

        # Fix 1: Any field that came back as a string but should be structured data.
        # Haiku sometimes returns list/object fields as JSON-encoded strings.
        # Detection: strings starting with "[" or "{" (after strip), or any string > 10 chars
        # that parses as JSON (catches edge cases like missing whitespace before "[").
        fixed = {}
        made_fix = False
        for key, value in output.items():
            # Diagnostic: always log type and preview for non-trivial string fields (Issue #146)
            if isinstance(value, str) and len(value) > 10:
                stripped = value.strip()
                looks_like_json = stripped.startswith("[") or stripped.startswith("{")
                print(
                    f"[TOOL-USE] DIAG schema={schema_name} field={key!r} "
                    f"type={type(value).__name__} len={len(value)} "
                    f"starts={stripped[:40]!r} looks_like_json={looks_like_json}",
                    flush=True,
                )

            if isinstance(value, str):
                stripped = value.strip()
                # Attempt parse if it looks like JSON (array or object) OR is long enough to
                # be a serialized structure that might not have obvious prefix markers.
                should_try = (
                    stripped.startswith("[")
                    or stripped.startswith("{")
                    or len(stripped) > 10
                )
                if should_try:
                    try:
                        parsed = _try_repair_json(value)
                        if isinstance(parsed, (list, dict)):
                            fixed[key] = parsed
                            made_fix = True
                            print(
                                f"[TOOL-USE] Fixed string-encoded JSON in field '{key}' "
                                f"(parsed as {type(parsed).__name__}) "
                                f"for schema {schema_name}",
                                flush=True,
                            )
                            continue
                        # Parsed but it's a scalar (e.g. a plain string "hello") — leave as-is
                    except ValueError as repair_err:
                        if stripped.startswith("[") or stripped.startswith("{"):
                            # It looked like JSON but we couldn't parse it — worth logging
                            print(
                                f"[TOOL-USE] Could not parse/repair JSON-shaped field '{key}' "
                                f"for schema {schema_name}: {repair_err}",
                                flush=True,
                            )
            fixed[key] = value

        if made_fix:
            output = fixed

        # Fix 2: Detect $defs-as-output pattern
        # Pattern: output has "defs" key but missing the expected array field
        # Example: {"defs": {"Edge": {...single edge object...}}} instead of {"edges": [{...}]}
        if "defs" in output and isinstance(output["defs"], dict):
            defs_val = output["defs"]
            # If each defs value looks like a single object (not a list), treat as single-item list
            # Try to find what the real top-level key should be by checking for "edges", "entity_resolutions", etc.
            # Look for the most complete object in defs values
            candidates = []
            for def_name, def_val in defs_val.items():
                if isinstance(def_val, dict) and len(def_val) > 1:
                    candidates.append((def_name.lower() + "s", [def_val]))  # pluralize for key name
            if candidates:
                # Use the first candidate as recovery
                recovery_key, recovery_val = candidates[0]
                print(
                    f"[TOOL-USE] Recovered defs-as-output: wrapping {candidates[0][0]} "
                    f"for schema {schema_name}",
                    flush=True,
                )
                return {recovery_key: recovery_val}

        return output
    except Exception as e:
        print(f"[TOOL-USE] WARNING: output fix failed: {e}", flush=True)
        return output


def json_schema_to_anthropic_tool(schema_name: str, schema: dict) -> dict:
    """Convert OpenAI JSON schema to Anthropic tool definition.

    Anthropic's tool use API accepts JSON Schema directly in the input_schema field.
    This allows us to enforce structured output by forcing tool use.

    Inlines any $ref/$defs references before passing to Anthropic, because Haiku
    sometimes misinterprets $ref schemas and returns the $defs structure rather
    than the actual requested data.

    Args:
        schema_name: Name of the schema (used as tool name)
        schema: JSON Schema object (OpenAI format)

    Returns:
        Anthropic tool definition dict
    """
    # Dereference $refs to produce a flat, unambiguous schema
    flat_schema = _deref_json_schema(schema)

    return {
        "name": schema_name,
        "description": schema.get("description", f"Generate structured output matching {schema_name}"),
        "input_schema": flat_schema
    }


def _validate_schema_fields(parsed: dict, schema: dict, schema_name: str) -> bool:
    """Check that parsed JSON has the required top-level fields from the schema.

    Catches parse failures or unexpected output where the response doesn't
    match the requested schema.
    """
    if not isinstance(parsed, dict):
        return True  # Arrays and primitives — skip field validation

    required_fields = set(schema.get("required", []))
    if not required_fields:
        # No required fields specified — check properties instead
        expected_fields = set(schema.get("properties", {}).keys())
        if not expected_fields:
            return True  # No field info available, accept it
        # At least one expected field must be present
        actual_fields = set(parsed.keys())
        if not actual_fields.intersection(expected_fields):
            print(
                f"[SCHEMA-VALIDATE] MISMATCH for {schema_name}: "
                f"expected one of {sorted(expected_fields)}, got {sorted(actual_fields)}",
                flush=True
            )
            return False
        return True

    actual_fields = set(parsed.keys())
    missing = required_fields - actual_fields
    if missing:
        print(
            f"[SCHEMA-VALIDATE] MISMATCH for {schema_name}: "
            f"missing required {sorted(missing)}, got {sorted(actual_fields)}",
            flush=True
        )
        return False
    return True


async def _handle_json_schema_via_sdk(request: ChatCompletionRequest) -> Optional[JSONResponse]:
    """Try to handle json_schema request via stateless SDK query (free path).

    Embeds the JSON schema in the prompt and asks for raw JSON output.
    Each call gets a fresh session — no context bleed, no schema confusion.
    Returns JSONResponse on success, None if fallback to direct API is needed.
    """
    global _schema_invoker_count

    schema_info = request.response_format.get("json_schema", {})
    schema_name = schema_info.get("name", "structured_output")
    schema = schema_info.get("schema")

    if not schema:
        return None  # Let caller handle the error

    # Dereference $refs for a flat, unambiguous schema
    flat_schema = _deref_json_schema(schema)

    # Extract required fields for validation and prompt reinforcement
    required_fields = list(flat_schema.get("required", []))
    properties = list(flat_schema.get("properties", {}).keys())
    field_list = required_fields or properties

    # Build prompt from request messages + embedded schema
    prompt_parts = []

    # System messages
    for msg in request.messages:
        if msg.role == "system":
            prompt_parts.append(f"System: {msg.content}")

    # Embed the schema with explicit field requirements
    schema_json = json.dumps(flat_schema, indent=2)

    prompt_parts.append(
        f"You MUST respond with ONLY valid JSON matching this exact schema.\n"
        f"Schema name: {schema_name}\n"
        f"JSON Schema:\n{schema_json}\n\n"
        f"REQUIRED top-level fields: {json.dumps(field_list)}\n"
        f"Your response MUST contain these exact field names at the top level.\n\n"
        f"Rules:\n"
        f"- Output ONLY the JSON object/array. No markdown fences. No explanation.\n"
        f"- Every field must match the schema types exactly.\n"
        f"- Use null for optional fields you want to omit.\n"
        f"- Do NOT include $defs or schema metadata in your output.\n"
        f"- Top-level fields MUST be: {json.dumps(field_list)}"
    )

    # User/assistant messages
    for msg in request.messages:
        if msg.role == "user":
            prompt_parts.append(f"User: {msg.content}")
        elif msg.role == "assistant":
            prompt_parts.append(f"Assistant: {msg.content}")

    prompt_parts.append(
        f"Respond now with ONLY valid JSON. "
        f"The top-level fields MUST be: {json.dumps(field_list)}. No other text."
    )

    combined_prompt = "\n\n".join(prompt_parts)
    query_start = time.monotonic()

    # Attempt 1: Query via stateless SDK
    try:
        response_text = await _stateless_query(combined_prompt)
    except HTTPException as e:
        print(f"[SCHEMA-VIA-SDK] Query failed for {schema_name}: {e.detail}", flush=True)
        return None

    if not response_text or not response_text.strip():
        print(f"[SCHEMA-VIA-SDK] Empty response for {schema_name}, falling back", flush=True)
        return None

    cleaned = strip_markdown_fences(response_text)

    # Try to parse
    parsed = None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            parsed = _try_repair_json(cleaned)
        except ValueError:
            pass

    # Validate: correct JSON AND correct schema fields
    if parsed is not None and _validate_schema_fields(parsed, flat_schema, schema_name):
        query_elapsed = time.monotonic() - query_start
        _schema_invoker_count += 1

        prompt_tokens = estimate_tokens(combined_prompt)
        completion_tokens = estimate_tokens(response_text)

        print(
            f"[SCHEMA-VIA-SDK] Success in {query_elapsed:.1f}s | "
            f"schema={schema_name} | "
            f"~{prompt_tokens}+{completion_tokens} tokens",
            flush=True
        )

        if VERBOSE:
            print("=" * 80, flush=True)
            print("[VERBOSE] SCHEMA-VIA-SDK RESPONSE:", flush=True)
            print(json.dumps(parsed, indent=2), flush=True)
            print("=" * 80, flush=True)

        response_dict = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(parsed)},
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens
            }
        }
        return JSONResponse(content=response_dict)

    # Attempt 2: Retry with explicit correction prompt
    # Since each call is stateless, the correction is just a better prompt —
    # not correction of context bleed. Still useful for parse failures.
    mismatch_reason = "wrong schema fields" if parsed is not None else "invalid JSON"
    print(
        f"[SCHEMA-VIA-SDK] Attempt 1 failed for {schema_name} ({mismatch_reason}), "
        f"retrying with correction",
        flush=True
    )

    correction_prompt = (
        f"Your previous response had {mismatch_reason}. "
        f"Here is what you returned:\n```\n{cleaned[:500]}\n```\n\n"
        f"This is WRONG. I need schema '{schema_name}' with these EXACT top-level fields: "
        f"{json.dumps(field_list)}\n\n"
        f"Respond with ONLY valid JSON matching schema '{schema_name}'. "
        f"Top-level fields MUST be: {json.dumps(field_list)}. "
        f"No explanation, no markdown fences, just the raw JSON."
    )

    try:
        response_text2 = await _stateless_query(correction_prompt)
    except HTTPException:
        print(f"[SCHEMA-VIA-SDK] Correction query failed for {schema_name}, falling back", flush=True)
        return None

    if not response_text2 or not response_text2.strip():
        return None

    cleaned2 = strip_markdown_fences(response_text2)

    parsed2 = None
    try:
        parsed2 = json.loads(cleaned2)
    except json.JSONDecodeError:
        try:
            parsed2 = _try_repair_json(cleaned2)
        except ValueError:
            pass

    if parsed2 is not None and _validate_schema_fields(parsed2, flat_schema, schema_name):
        query_elapsed = time.monotonic() - query_start
        _schema_invoker_count += 1

        prompt_tokens = estimate_tokens(combined_prompt) + estimate_tokens(correction_prompt)
        completion_tokens = estimate_tokens(response_text) + estimate_tokens(response_text2)

        print(
            f"[SCHEMA-VIA-SDK] Success after correction in {query_elapsed:.1f}s | "
            f"schema={schema_name}",
            flush=True
        )

        response_dict = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(parsed2)},
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens
            }
        }
        return JSONResponse(content=response_dict)

    # Both attempts failed — fall back to direct API
    print(
        f"[SCHEMA-VIA-SDK] Both attempts failed for {schema_name}, "
        f"falling back to direct API",
        flush=True
    )
    return None


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """
    OpenAI-compatible chat completions endpoint.

    Translates OpenAI format → stateless SDK query → OpenAI format.
    """
    global _total_requests, _total_errors, _schema_fallback_count

    _total_requests += 1

    # Check if request needs json_schema enforcement
    use_json_schema_tool = (
        request.response_format
        and request.response_format.get("type") == "json_schema"
    )

    if use_json_schema_tool:
        # Try stateless SDK first (free via CC subscription)
        sdk_result = await _handle_json_schema_via_sdk(request)
        if sdk_result is not None:
            return sdk_result

        # Fallback: direct Anthropic API (paid, safety net)
        _schema_fallback_count += 1
        print(
            f"[SCHEMA-FALLBACK] Falling back to direct API "
            f"(total fallbacks: {_schema_fallback_count})",
            flush=True
        )
        schema_info = request.response_format.get("json_schema", {})
        schema_name = schema_info.get("name", "structured_output")
        schema = schema_info.get("schema")

        if not schema:
            _total_errors += 1
            raise HTTPException(
                status_code=400,
                detail="json_schema response_format requires a schema"
            )

        # Convert OpenAI messages to Anthropic format
        anthropic_messages = []
        system_content = []

        for msg in request.messages:
            if msg.role == "system":
                system_content.append(msg.content)
            elif msg.role in ("user", "assistant"):
                anthropic_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })

        # Create tool definition from schema
        tool = json_schema_to_anthropic_tool(schema_name, schema)

        # Call Anthropic API directly with forced tool use
        try:
            # Use persistent Anthropic client
            if _anthropic_client is None:
                raise HTTPException(
                    status_code=503,
                    detail="Anthropic client not initialized (missing ANTHROPIC_API_KEY)"
                )
            client = _anthropic_client

            # Get model from environment or use haiku
            # Map short names to full model IDs
            anthropic_model = os.getenv("WRAPPER_MODEL", "haiku")
            model_max_tokens = 4096  # Default for most models

            if anthropic_model == "haiku":
                anthropic_model = "claude-3-haiku-20240307"
                model_max_tokens = 4096
            elif anthropic_model == "sonnet":
                anthropic_model = "claude-sonnet-4-5-20250929"
                model_max_tokens = 8192
            elif anthropic_model == "opus":
                anthropic_model = "claude-opus-4-5-20251101"
                model_max_tokens = 8192

            # Cap max_tokens to model's limit
            requested_tokens = request.max_tokens or 4096
            max_tokens = min(requested_tokens, model_max_tokens)

            query_start = time.monotonic()

            print(f"[TOOL-USE] Calling Anthropic API with forced tool: {schema_name}", flush=True)
            if requested_tokens > model_max_tokens:
                print(f"[TOOL-USE] Capping max_tokens from {requested_tokens} to {max_tokens} (model limit)", flush=True)

            # Call Anthropic with forced tool use
            response = client.messages.create(
                model=anthropic_model,
                max_tokens=max_tokens,
                system="\n\n".join(system_content) if system_content else None,
                messages=anthropic_messages,
                tools=[tool],
                tool_choice={"type": "tool", "name": schema_name}
            )

            # Extract tool_use block
            tool_use_block = None
            for block in response.content:
                if hasattr(block, 'type') and block.type == "tool_use":
                    tool_use_block = block
                    break

            if not tool_use_block:
                _total_errors += 1
                raise HTTPException(
                    status_code=502,
                    detail="Anthropic did not return expected tool_use block"
                )

            # Extract the structured output (guaranteed to match schema)
            # Keep as dict - we'll manually serialize to avoid double-encoding
            tool_output_dict = tool_use_block.input

            # Apply recovery heuristics for known Haiku $ref schema confusion
            # (string-encoded arrays, defs-as-output pattern)
            tool_output_dict = _fix_tool_output(schema_name, tool_output_dict)

            query_elapsed = time.monotonic() - query_start

            # Log success
            print(
                f"[TOOL-USE] Success in {query_elapsed:.1f}s | "
                f"schema={schema_name} | "
                f"input_tokens={response.usage.input_tokens} | "
                f"output_tokens={response.usage.output_tokens}",
                flush=True
            )

            # Verbose logging
            if VERBOSE:
                print("=" * 80, flush=True)
                print("[VERBOSE] TOOL-USE RESPONSE:", flush=True)
                print("-" * 40, flush=True)
                print(json.dumps(tool_output_dict, indent=2), flush=True)
                print("-" * 40, flush=True)
                print("=" * 80, flush=True)

            # Build OpenAI-compatible response manually to avoid double-encoding
            # FastAPI's automatic Pydantic serialization would stringify content again
            response_dict = {
                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            # content is the JSON string that Graphiti will parse
                            "content": json.dumps(tool_output_dict)
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": response.usage.input_tokens,
                    "completion_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens
                }
            }
            return JSONResponse(content=response_dict)

        except anthropic.APIError as e:
            _total_errors += 1
            print(f"[TOOL-USE] Anthropic API error: {e}", flush=True)
            raise HTTPException(
                status_code=502,
                detail=f"Anthropic API error: {e}"
            )

    # Regular path (non-json_schema or json_object)
    wants_json = request.response_format and request.response_format.get("type") == "json_object"

    prompt_parts = []
    for msg in request.messages:
        if msg.role == "system":
            prompt_parts.append(f"System: {msg.content}")
        elif msg.role == "user":
            prompt_parts.append(f"User: {msg.content}")
        elif msg.role == "assistant":
            prompt_parts.append(f"Assistant: {msg.content}")

    # When caller requests JSON output (json_object mode), tell Claude explicitly
    if wants_json:
        json_instruction = (
            "IMPORTANT: Respond with raw JSON only. "
            "No markdown formatting, no code fences, no explanation. "
            "Just the JSON object."
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

    query_start = time.monotonic()

    # Query via stateless SDK
    response_text = await _stateless_query(combined_prompt)

    # Validate response (retry once on empty)
    if not response_text or not response_text.strip():
        print("[WARN] Empty response, retrying once...", flush=True)
        response_text = await _stateless_query(combined_prompt)

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
    print(
        f"[DONE] {query_elapsed:.1f}s | "
        f"~{prompt_tokens}+{completion_tokens} tokens",
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


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
