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

Usage:
    docker compose up pps-cc-wrapper

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
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# Add daemon directory to path for ClaudeInvoker import
sys.path.insert(0, str(Path(__file__).parent / "daemon"))

from cc_invoker.invoker import ClaudeInvoker


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


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


async def initialize_invoker():
    """Initialize ClaudeInvoker on startup."""
    global invoker

    model = os.getenv("WRAPPER_MODEL", "haiku")

    print(f"Initializing ClaudeInvoker (model={model})...")
    print("This takes ~33s for initial connection...")

    start = time.time()

    # Create invoker with minimal config:
    # - No identity (stateless mode)
    # - No MCP servers (not needed for extraction)
    # - Bypass permissions (headless mode)
    invoker = ClaudeInvoker(
        model=model,
        bypass_permissions=True,
        startup_prompt=None,  # No identity reconstruction
        mcp_servers={},  # Disable MCP tools
        max_context_tokens=150_000,
        max_turns=100,
    )

    await invoker.initialize()

    elapsed = time.time() - start
    print(f"✓ ClaudeInvoker initialized in {elapsed:.1f}s")
    print(f"  Context limits: {invoker.max_context_tokens} tokens, {invoker.max_turns} turns")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup
    await initialize_invoker()
    yield
    # Shutdown
    if invoker:
        await invoker.shutdown()
        print("ClaudeInvoker shut down")


app = FastAPI(
    title="Claude Code OpenAI Wrapper",
    description="OpenAI-compatible wrapper for ClaudeInvoker",
    version="0.1.0",
    lifespan=lifespan
)


# =============================================================================
# Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check for Docker."""
    if invoker is None or not invoker.is_connected:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "message": "ClaudeInvoker not initialized"
            }
        )

    stats = invoker.context_stats

    return {
        "status": "healthy",
        "invoker_connected": invoker.is_connected,
        "context_usage": {
            "tokens": stats["total_tokens"],
            "turns": stats["turn_count"],
            "limit": invoker.max_context_tokens
        }
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """
    OpenAI-compatible chat completions endpoint.

    Translates OpenAI format → ClaudeInvoker → OpenAI format.
    """
    if invoker is None or not invoker.is_connected:
        raise HTTPException(
            status_code=503,
            detail="ClaudeInvoker not initialized"
        )

    # Check if restart needed (context limits)
    needs_restart, reason = invoker.needs_restart()
    if needs_restart:
        print(f"Restarting invoker: {reason}")
        try:
            await invoker.restart(reason=reason)
        except Exception as e:
            print(f"Restart failed: {e}")
            raise HTTPException(
                status_code=503,
                detail=f"Invoker restart failed: {e}"
            )

    # Combine messages into single prompt for ClaudeInvoker
    # Claude doesn't need strict role separation for extraction tasks
    prompt_parts = []
    for msg in request.messages:
        if msg.role == "system":
            prompt_parts.append(f"System: {msg.content}")
        elif msg.role == "user":
            prompt_parts.append(f"User: {msg.content}")
        elif msg.role == "assistant":
            prompt_parts.append(f"Assistant: {msg.content}")

    combined_prompt = "\n\n".join(prompt_parts)

    # Estimate input tokens
    prompt_tokens = estimate_tokens(combined_prompt)

    # Query Claude
    try:
        response_text = await invoker.query(combined_prompt)
    except Exception as e:
        print(f"Query failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"ClaudeInvoker query failed: {e}"
        )

    # Estimate output tokens
    completion_tokens = estimate_tokens(response_text)

    # Build OpenAI-compatible response
    response = ChatCompletionResponse(
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

    return response


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
