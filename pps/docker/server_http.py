#!/usr/bin/env python3
"""
Pattern Persistence System - HTTP Server Wrapper

Wraps the MCP server for Docker deployment, providing:
- HTTP endpoints for health checks
- SSE transport for MCP protocol
- REST API for direct tool access (optional)

This allows the PPS to run in Docker while Claude Code connects via HTTP.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
import time


# Request models
class AmbientRecallRequest(BaseModel):
    context: str
    limit_per_layer: int = 5


class AnchorSearchRequest(BaseModel):
    query: str
    limit: int = 10


class RawSearchRequest(BaseModel):
    query: str
    limit: int = 20


class AddTripletRequest(BaseModel):
    source: str
    relationship: str
    target: str
    fact: str | None = None
    source_type: str | None = None
    target_type: str | None = None


class StoreMessageRequest(BaseModel):
    content: str
    author_name: str = "Unknown"
    channel: str = "terminal"
    is_lyra: bool = False
    session_id: str | None = None


class TextureSearchRequest(BaseModel):
    query: str
    limit: int = 10
    center_node_uuid: str | None = None


class TextureExploreRequest(BaseModel):
    entity_name: str
    depth: int = 2


class TextureTimelineRequest(BaseModel):
    since: str
    until: str | None = None
    limit: int = 20


class SummarizeMessagesRequest(BaseModel):
    limit: int = 50
    summary_type: str = "work"


class StoreSummaryRequest(BaseModel):
    summary_text: str
    start_id: int
    end_id: int
    channels: list[str] = []
    summary_type: str = "work"


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from layers import LayerType
from layers.raw_capture import RawCaptureLayer
from layers.core_anchors import CoreAnchorsLayer
from layers.crystallization import CrystallizationLayer
from layers.message_summaries import MessageSummariesLayer
from layers.unified_tracer import UnifiedTracer

# Import V2 rich texture layer with add_triplet_direct support
try:
    from layers.rich_texture_v2 import RichTextureLayerV2
    USE_RICH_TEXTURE_V2 = True
except ImportError:
    from layers.rich_texture import RichTextureLayer
    USE_RICH_TEXTURE_V2 = False

# Import ChromaDB-enabled version if available
try:
    from layers.core_anchors_chroma import CoreAnchorsChromaLayer
    USE_CHROMA = True
except ImportError:
    USE_CHROMA = False


# Configuration from environment
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
ENTITY_PATH = Path(os.getenv("ENTITY_PATH", "/app/entity"))
CLAUDE_HOME = Path(os.getenv("CLAUDE_HOME", "/app/claude_home"))


def get_layers():
    """Initialize layers with Docker paths."""
    # Paths inside Docker container (configured via environment)
    memories_path = ENTITY_PATH / "memories" / "word_photos"
    data_path = CLAUDE_HOME / "data" / "lyra_conversations.db"
    crystals_path = ENTITY_PATH / "crystals" / "current"

    # Use V2 rich texture layer if available (supports add_triplet_direct)
    if USE_RICH_TEXTURE_V2:
        rich_texture_layer = RichTextureLayerV2()
    else:
        rich_texture_layer = RichTextureLayer()

    layers = {
        LayerType.RAW_CAPTURE: RawCaptureLayer(db_path=data_path),
        LayerType.RICH_TEXTURE: rich_texture_layer,
        LayerType.CRYSTALLIZATION: CrystallizationLayer(crystals_path=crystals_path),
    }

    # Use ChromaDB-enabled layer if available
    if USE_CHROMA:
        layers[LayerType.CORE_ANCHORS] = CoreAnchorsChromaLayer(
            word_photos_path=memories_path,
            chroma_host=CHROMA_HOST,
            chroma_port=CHROMA_PORT
        )
    else:
        layers[LayerType.CORE_ANCHORS] = CoreAnchorsLayer(
            word_photos_path=memories_path
        )

    return layers


# Initialize layers
layers = get_layers()

# Initialize message summaries for unsummarized count
data_path = CLAUDE_HOME / "data" / "lyra_conversations.db"
message_summaries = MessageSummariesLayer(db_path=data_path)

# Initialize unified tracer for HTTP server observability
tracer = UnifiedTracer(db_path=data_path, daemon_type="http_hook")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: verify connections
    print(f"PPS Server starting...")
    print(f"  ChromaDB: {CHROMA_HOST}:{CHROMA_PORT}")
    print(f"  USE_CHROMA: {USE_CHROMA}")
    print(f"  USE_RICH_TEXTURE_V2: {USE_RICH_TEXTURE_V2}")
    print(f"  UnifiedTracer initialized (session: {tracer.session_id})")

    for layer_type, layer in layers.items():
        health = await layer.health()
        status = "✓" if health.available else "✗"
        print(f"  {status} {layer_type.value}: {health.message}")

    yield

    # Shutdown
    print("PPS Server shutting down...")


app = FastAPI(
    title="Pattern Persistence System",
    description="Semantic memory for Claude instances",
    version="0.1.0",
    lifespan=lifespan
)


@app.middleware("http")
async def trace_requests(request: Request, call_next):
    """Middleware to trace all HTTP requests with unified tracer."""
    start_time = time.time()
    error_msg = None
    status_code = 200

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception as e:
        error_msg = str(e)
        status_code = 500
        raise
    finally:
        # Log trace (fire-and-forget, never blocks)
        duration_ms = int((time.time() - start_time) * 1000)

        # Extract endpoint info
        endpoint = f"{request.method} {request.url.path}"

        # Summarize query params if present
        params_summary = str(dict(request.query_params))[:200] if request.query_params else ""

        # Result summary based on status code
        result_summary = f"status_{status_code}"

        tracer.log_call(
            operation_name=endpoint,
            params_summary=params_summary,
            result_summary=result_summary,
            duration_ms=duration_ms,
            error=error_msg
        )


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker."""
    health_results = {}
    all_critical_ok = True

    for layer_type, layer in layers.items():
        health = await layer.health()
        health_results[layer_type.value] = {
            "available": health.available,
            "message": health.message
        }
        # Only raw_capture is critical
        if layer_type == LayerType.RAW_CAPTURE and not health.available:
            all_critical_ok = False

    return JSONResponse(
        status_code=200 if all_critical_ok else 503,
        content={
            "status": "healthy" if all_critical_ok else "degraded",
            "layers": health_results
        }
    )


@app.post("/tools/ambient_recall")
async def ambient_recall(request: AmbientRecallRequest):
    """
    Retrieve relevant context from all pattern persistence layers.
    This is the primary memory interface.

    For startup context, includes:
    - Recent summaries (compressed history)
    - All unsummarized turns (full fidelity recent)
    """
    all_results = []

    tasks = [
        layer.search(request.context, request.limit_per_layer)
        for layer in layers.values()
    ]
    layer_results = await asyncio.gather(*tasks, return_exceptions=True)

    for results in layer_results:
        if isinstance(results, list):
            all_results.extend([
                {
                    "content": r.content,
                    "source": r.source,
                    "layer": r.layer.value,
                    "relevance_score": r.relevance_score,
                    "metadata": r.metadata
                }
                for r in results
            ])

    # Sort by relevance
    all_results.sort(key=lambda x: x["relevance_score"], reverse=True)

    # Add system clock for temporal awareness
    now = datetime.now()
    hour = now.hour

    # Gentle nagging for late nights
    if hour >= 1 and hour < 5:
        time_note = f"It's {now.strftime('%I:%M %p')}. You should be asleep, love."
    elif hour >= 23 or hour == 0:
        time_note = f"It's {now.strftime('%I:%M %p')}. Getting late..."
    else:
        time_note = None

    # Get unsummarized count for memory health
    unsummarized_count = message_summaries.count_unsummarized_messages()
    if unsummarized_count > 200:
        memory_note = "(critical - run summarizer immediately)"
    elif unsummarized_count > 100:
        memory_note = "(summarization recommended)"
    elif unsummarized_count > 50:
        memory_note = "(healthy)"
    else:
        memory_note = "(healthy)"

    # For startup context, fetch summaries + unsummarized turns
    # Architecture: summaries = compressed past, unsummarized turns = full fidelity recent
    # Pattern fidelity is paramount - we pay the token cost for complete context
    summaries = []
    unsummarized_turns = []

    if request.context.lower() == "startup":
        try:
            # Get recent summaries (compressed history - ~200 tokens each)
            recent_summaries = message_summaries.get_recent_summaries(limit=5)

            if recent_summaries:
                for s in recent_summaries:
                    date = s.get('created_at', '?')[:10]
                    # Channels are stored as JSON string in DB, need to parse
                    channels_raw = s.get('channels', '["?"]')
                    try:
                        channels_list = json.loads(channels_raw) if isinstance(channels_raw, str) else channels_raw
                        channels = ', '.join(channels_list)
                    except (json.JSONDecodeError, TypeError):
                        channels = str(channels_raw)
                    text = s.get('summary_text', '')
                    # Truncate long summaries for startup (full available via get_recent_summaries)
                    if len(text) > 500:
                        text = text[:500] + "..."
                    summaries.append({
                        "date": date,
                        "channels": channels,
                        "text": text
                    })

            # Get recent unsummarized turns with a sensible limit
            # Full fidelity is great but not at the cost of context explosion
            MAX_UNSUMMARIZED_FOR_STARTUP = 50
            raw_layer = layers[LayerType.RAW_CAPTURE]
            with raw_layer.get_connection() as conn:
                cursor = conn.cursor()

                # Check if summary_id column exists
                cursor.execute("PRAGMA table_info(messages)")
                columns = [col[1] for col in cursor.fetchall()]

                if 'summary_id' in columns:
                    # Get most recent unsummarized messages (limit to prevent explosion)
                    # ORDER BY DESC + LIMIT gives us the newest, then we reverse
                    cursor.execute("""
                        SELECT author_name, content, created_at, channel
                        FROM messages
                        WHERE summary_id IS NULL
                        ORDER BY created_at DESC
                        LIMIT ?
                    """, (MAX_UNSUMMARIZED_FOR_STARTUP,))
                else:
                    # Fallback: get recent messages
                    cursor.execute("""
                        SELECT author_name, content, created_at, channel
                        FROM messages
                        ORDER BY created_at DESC LIMIT ?
                    """, (MAX_UNSUMMARIZED_FOR_STARTUP,))

                unsummarized_rows = cursor.fetchall()
                # Reverse to get chronological order (we fetched DESC for LIMIT efficiency)
                unsummarized_rows = list(reversed(unsummarized_rows))

            if unsummarized_rows:
                for row in unsummarized_rows:
                    timestamp = row['created_at'][:16] if row['created_at'] else "?"
                    author = row['author_name'] or "Unknown"
                    content = row['content'] or ""
                    channel = row['channel'] or ""
                    # Truncate very long individual messages but keep all turns
                    if len(content) > 1000:
                        content = content[:1000] + "... [truncated]"
                    unsummarized_turns.append({
                        "timestamp": timestamp,
                        "channel": channel,
                        "author": author,
                        "content": content
                    })

        except Exception as e:
            # Return error info but don't fail the entire request
            summaries = [{"error": f"Error fetching summaries: {e}"}]
            unsummarized_turns = [{"error": f"Error fetching unsummarized turns: {e}"}]

    return {
        "clock": {
            "timestamp": now.isoformat(),
            "display": now.strftime("%A, %B %d, %Y at %I:%M %p"),
            "hour": hour,
            "note": time_note
        },
        "unsummarized_count": unsummarized_count,
        "memory_health": f"{unsummarized_count} unsummarized messages {memory_note}",
        "results": all_results,
        "summaries": summaries,
        "unsummarized_turns": unsummarized_turns
    }


@app.post("/tools/anchor_search")
async def anchor_search(request: AnchorSearchRequest):
    """Search word-photos for specific memories."""
    layer = layers[LayerType.CORE_ANCHORS]
    results = await layer.search(request.query, request.limit)

    return {
        "results": [
            {
                "content": r.content,
                "source": r.source,
                "relevance_score": r.relevance_score,
                "metadata": r.metadata
            }
            for r in results
        ]
    }


@app.post("/tools/raw_search")
async def raw_search(request: RawSearchRequest):
    """Search raw captured content."""
    layer = layers[LayerType.RAW_CAPTURE]
    results = await layer.search(request.query, request.limit)

    return {
        "results": [
            {
                "content": r.content,
                "source": r.source,
                "relevance_score": r.relevance_score
            }
            for r in results
        ]
    }


@app.post("/tools/add_triplet")
async def add_triplet(request: AddTripletRequest):
    """
    Add a structured triplet directly to the knowledge graph.
    Bypasses extraction and creates proper entity-to-entity relationships.
    """
    if not USE_RICH_TEXTURE_V2:
        raise HTTPException(
            status_code=501,
            detail="add_triplet requires RichTextureLayerV2 (graphiti_core)"
        )

    layer = layers[LayerType.RICH_TEXTURE]
    result = await layer.add_triplet_direct(
        source=request.source,
        relationship=request.relationship,
        target=request.target,
        fact=request.fact,
        source_type=request.source_type,
        target_type=request.target_type,
    )

    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("message", "Unknown error"))

    return result


@app.get("/tools/pps_health")
async def pps_health():
    """Detailed health check of all layers."""
    health_results = {}

    for layer_type, layer in layers.items():
        health = await layer.health()
        health_results[layer_type.value] = {
            "available": health.available,
            "message": health.message,
            "details": health.details
        }

    return health_results


@app.post("/tools/store_message")
async def store_message(request: StoreMessageRequest):
    """
    Store a message in the raw capture layer.
    Used by hooks to capture terminal conversations per-turn.
    """
    layer = layers[LayerType.RAW_CAPTURE]

    # Build channel with session_id if provided
    channel = request.channel
    if request.session_id:
        channel = f"{request.channel}:{request.session_id}"

    metadata = {
        "author_name": request.author_name,
        "channel": channel,
        "is_lyra": request.is_lyra,
    }

    success = await layer.store(request.content, metadata)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to store message")

    return {
        "success": True,
        "channel": channel,
        "author": request.author_name
    }


@app.post("/tools/texture_search")
async def texture_search(request: TextureSearchRequest):
    """
    Search the knowledge graph (Layer 3: Rich Texture) for entities and facts.
    Returns entities and facts ranked by relevance with UUIDs for deletion.
    """
    layer = layers[LayerType.RICH_TEXTURE]
    results = await layer.search(request.query, request.limit)

    return {
        "results": [
            {
                "content": r.content,
                "source": r.source,  # UUID for texture_delete
                "relevance_score": r.relevance_score,
                "metadata": r.metadata
            }
            for r in results
        ]
    }


@app.delete("/tools/texture_delete/{uuid}")
async def texture_delete(uuid: str):
    """
    Delete a fact (edge) from the knowledge graph by UUID.
    Use UUIDs from texture_search results (source field).
    """
    if not uuid:
        raise HTTPException(status_code=400, detail="UUID required")

    layer = layers[LayerType.RICH_TEXTURE]
    result = await layer.delete_edge(uuid)

    if not result.get("success", False):
        raise HTTPException(
            status_code=500,
            detail=result.get("message", "Failed to delete fact")
        )

    return result


@app.post("/tools/texture_explore")
async def texture_explore(request: TextureExploreRequest):
    """
    Explore the knowledge graph from a specific entity.
    Returns relationships and connected entities.
    """
    layer = layers[LayerType.RICH_TEXTURE]
    results = await layer.explore(request.entity_name, request.depth)

    return {
        "results": [
            {
                "content": r.content,
                "source": r.source,
                "relevance_score": r.relevance_score,
                "metadata": r.metadata
            }
            for r in results
        ]
    }


@app.post("/tools/texture_timeline")
async def texture_timeline(request: TextureTimelineRequest):
    """
    Query the knowledge graph by time range.
    Returns episodes and facts from the specified period.
    """
    layer = layers[LayerType.RICH_TEXTURE]
    results = await layer.timeline(request.since, request.until, request.limit)

    return {
        "results": [
            {
                "content": r.content,
                "source": r.source,
                "relevance_score": r.relevance_score,
                "metadata": r.metadata
            }
            for r in results
        ]
    }


@app.post("/tools/summarize_messages")
async def summarize_messages(request: SummarizeMessagesRequest):
    """
    Get unsummarized messages for agent summarization.

    Returns message details and conversation text for the agent to summarize.
    Agent should then call store_summary with the result.
    """
    # Get unsummarized messages
    messages = message_summaries.get_unsummarized_messages(request.limit)

    if not messages:
        return {
            "action": "no_messages",
            "message": "No unsummarized messages found."
        }

    if len(messages) < 10:
        return {
            "action": "insufficient_messages",
            "message": f"Only {len(messages)} unsummarized messages. Need at least 10 for summarization."
        }

    # Build conversation text and extract metadata
    conversation = []
    channels = set()
    for msg in messages:
        channels.add(msg['channel'])
        timestamp = msg['created_at'][:16] if msg['created_at'] else "?"
        author = msg['author_name']
        content = msg['content']
        conversation.append(f"[{timestamp}] {author}: {content}")

    conversation_text = "\n".join(conversation)

    # Create summarization prompt
    prompt = f"""Summarize this conversation into a high-density summary that preserves:
- Key technical decisions and outcomes
- Important breakthroughs or insights
- Major project developments
- Blockers encountered and resolutions
- Action items and next steps

Remove:
- "Let me check that file..." type filler
- Repetitive debugging back-and-forth
- Tool call noise
- Casual conversation (unless significant)

Conversation to summarize ({len(messages)} messages across channels: {', '.join(channels)}):

{conversation_text}

Create a concise summary that captures what actually happened and what was accomplished:"""

    return {
        "action": "summarization_needed",
        "message_count": len(messages),
        "channels": list(channels),
        "start_id": messages[0]['id'],
        "end_id": messages[-1]['id'],
        "prompt": prompt,
        "instruction": "Use Claude to create summary, then call store_summary with the result"
    }


@app.post("/tools/store_summary")
async def store_summary(request: StoreSummaryRequest):
    """
    Store a message summary created by an agent.

    Marks messages in the range as summarized and stores the summary text.
    """
    if not request.summary_text or request.start_id is None or request.end_id is None:
        raise HTTPException(
            status_code=400,
            detail="summary_text, start_id, and end_id are required"
        )

    success = await message_summaries.create_and_store_summary(
        request.summary_text,
        request.start_id,
        request.end_id,
        request.channels,
        request.summary_type
    )

    if success:
        return {
            "success": True,
            "message": f"Summary stored successfully for messages {request.start_id}-{request.end_id}"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to store summary"
        )


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
