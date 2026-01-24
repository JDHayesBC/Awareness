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


# Phase 1 HTTP Migration - New Request Models
class AnchorSaveRequest(BaseModel):
    """Request to save a word-photo (anchor)."""
    content: str          # The word-photo content in markdown
    title: str            # Title (used in filename)
    location: str = "terminal"  # Context tag (terminal, discord, reflection, etc.)


class CrystallizeRequest(BaseModel):
    """Request to create a new crystal."""
    content: str          # Crystal content in markdown format


class TextureAddRequest(BaseModel):
    """Request to add content to the knowledge graph."""
    content: str          # Content to store (conversation, note, observation)
    channel: str = "manual"  # Source channel for metadata


class IngestBatchRequest(BaseModel):
    """Request to batch ingest messages to Graphiti."""
    batch_size: int = 20  # Number of messages to ingest


class EnterSpaceRequest(BaseModel):
    """Request to enter a space and load its context."""
    space_name: str       # Name of the space to enter


class GetCrystalsRequest(BaseModel):
    """Request to get recent crystals."""
    count: int = 4        # Number of recent crystals to retrieve


# Phase 2 HTTP Migration - Additional Request Models

class GetTurnsSinceCrystalRequest(BaseModel):
    """Request to get conversation turns after last crystal."""
    limit: int = 50
    offset: int = 0
    min_turns: int = 10
    channel: str | None = None


class GetRecentSummariesRequest(BaseModel):
    """Request to get recent message summaries."""
    limit: int = 5


class SearchSummariesRequest(BaseModel):
    """Request to search message summaries."""
    query: str
    limit: int = 10


class InventoryListRequest(BaseModel):
    """Request to list inventory items by category."""
    category: str
    subcategory: str | None = None
    limit: int = 50


class InventoryAddRequest(BaseModel):
    """Request to add an inventory item."""
    name: str
    category: str
    subcategory: str | None = None
    description: str | None = None
    attributes: dict | None = None


class InventoryGetRequest(BaseModel):
    """Request to get an inventory item."""
    name: str
    category: str


class InventoryDeleteRequest(BaseModel):
    """Request to delete an inventory item."""
    name: str
    category: str


class TechSearchRequest(BaseModel):
    """Request to search technical documentation."""
    query: str
    limit: int = 5
    category: str | None = None


class TechIngestRequest(BaseModel):
    """Request to ingest a markdown file into Tech RAG."""
    filepath: str
    category: str | None = None


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from layers import LayerType
from layers.raw_capture import RawCaptureLayer
from layers.core_anchors import CoreAnchorsLayer
from layers.crystallization import CrystallizationLayer
from layers.message_summaries import MessageSummariesLayer
from layers.unified_tracer import UnifiedTracer
from layers.inventory import InventoryLayer

# Import Tech RAG layer (Layer 6) if available
try:
    from layers.tech_rag import TechRAGLayer
    USE_TECH_RAG = True
except ImportError:
    USE_TECH_RAG = False

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

# Initialize inventory layer (Layer 5) for enter_space
inventory_db_path = CLAUDE_HOME / "data" / "inventory.db"
inventory = InventoryLayer(db_path=inventory_db_path)

# Initialize Tech RAG layer (Layer 6) if available
if USE_TECH_RAG:
    tech_rag_db = CLAUDE_HOME / "data" / "tech_rag.db"
    tech_rag = TechRAGLayer(db_path=tech_rag_db)
else:
    tech_rag = None

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
    print(f"  USE_TECH_RAG: {USE_TECH_RAG}")
    print(f"  Inventory: {inventory_db_path}")
    print(f"  Tech RAG: {tech_rag_db if USE_TECH_RAG else 'disabled'}")
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


# =============================================================================
# Phase 1 HTTP Migration Endpoints
# These endpoints unblock daemon autonomy by providing HTTP access to write operations
# =============================================================================


@app.post("/tools/anchor_save")
async def anchor_save(request: AnchorSaveRequest):
    """
    Save a new word-photo (Layer 2: Core Anchors).

    Use for curating foundational moments that define self-pattern.
    Creates a dated markdown file in the word_photos directory.
    """
    if not request.content or not request.title:
        raise HTTPException(status_code=400, detail="content and title are required")

    layer = layers[LayerType.CORE_ANCHORS]
    metadata = {"title": request.title, "location": request.location}

    success = await layer.store(request.content, metadata)

    if success:
        return {
            "success": True,
            "message": f"Word-photo saved (location: {request.location})",
            "title": request.title
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to save word-photo")


@app.post("/tools/crystallize")
async def crystallize(request: CrystallizeRequest):
    """
    Save a new crystal (Layer 4: Crystallization).

    Use for conscious crystallization - when a crystallization moment has occurred.
    Automatically numbers the crystal and manages the rolling window.
    """
    if not request.content:
        raise HTTPException(status_code=400, detail="content is required")

    layer = layers[LayerType.CRYSTALLIZATION]
    success = await layer.store(request.content)

    if success:
        # Get the filename of the just-saved crystal
        latest = layer._get_latest_crystal()
        filename = latest.name if latest else "unknown"
        return {
            "success": True,
            "filename": filename,
            "message": f"Crystal saved: {filename}"
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to save crystal")


@app.post("/tools/get_crystals")
async def get_crystals(request: GetCrystalsRequest):
    """
    Get recent crystals (Layer 4: Crystallization).

    Returns the most recent N crystals in chronological order for temporal context.
    """
    layer = layers[LayerType.CRYSTALLIZATION]
    results = await layer.search("recent", request.count)

    if not results:
        return {
            "crystals": [],
            "message": "No crystals found. Create your first with crystallize."
        }

    crystals = [
        {
            "filename": r.source,
            "content": r.content,
            "relevance_score": r.relevance_score
        }
        for r in results
    ]

    return {
        "crystals": crystals,
        "count": len(crystals)
    }


@app.post("/tools/texture_add")
async def texture_add(request: TextureAddRequest):
    """
    Add content to the knowledge graph (Layer 3: Rich Texture).

    Manually store a fact, observation, or conversation for entity extraction.
    Graphiti will automatically extract entities and relationships.
    """
    if not request.content:
        raise HTTPException(status_code=400, detail="content is required")

    layer = layers[LayerType.RICH_TEXTURE]
    metadata = {"channel": request.channel}

    success = await layer.store(request.content, metadata)

    if success:
        return {
            "success": True,
            "message": f"Content stored in knowledge graph (channel: {request.channel}). Entities will be extracted automatically."
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to store content. Graphiti may not be running."
        )


@app.post("/tools/ingest_batch_to_graphiti")
async def ingest_batch_to_graphiti(request: IngestBatchRequest):
    """
    Batch ingest messages to Graphiti (Layer 3: Rich Texture).

    Takes uningested raw messages and sends to Graphiti for entity extraction.
    Automatically tracks which messages have been ingested.
    """
    # Get uningested messages
    uningested_count = message_summaries.count_uningested_to_graphiti()

    if uningested_count == 0:
        return {
            "success": True,
            "message": "No messages to ingest",
            "ingested": 0,
            "remaining": 0
        }

    # Get batch of uningested messages
    raw_layer = layers[LayerType.RAW_CAPTURE]
    texture_layer = layers[LayerType.RICH_TEXTURE]

    try:
        with raw_layer.get_connection() as conn:
            cursor = conn.cursor()

            # Check if graphiti_ingested column exists
            cursor.execute("PRAGMA table_info(messages)")
            columns = [col[1] for col in cursor.fetchall()]

            if 'graphiti_ingested' not in columns:
                # Add the column if it doesn't exist
                cursor.execute("ALTER TABLE messages ADD COLUMN graphiti_ingested BOOLEAN DEFAULT FALSE")
                conn.commit()

            # Get uningested messages
            cursor.execute("""
                SELECT id, author_name, content, created_at, channel
                FROM messages
                WHERE graphiti_ingested IS NULL OR graphiti_ingested = FALSE
                ORDER BY created_at ASC
                LIMIT ?
            """, (request.batch_size,))

            messages = cursor.fetchall()

        if not messages:
            return {
                "success": True,
                "message": "No messages to ingest",
                "ingested": 0,
                "remaining": uningested_count
            }

        # Ingest each message to Graphiti
        ingested_ids = []
        errors = []

        for msg in messages:
            msg_id = msg['id']
            author = msg['author_name'] or "Unknown"
            content = msg['content'] or ""
            channel = msg['channel'] or "unknown"
            timestamp = msg['created_at']

            # Format for Graphiti
            formatted_content = f"[{author}]: {content}"
            metadata = {
                "channel": channel,
                "speaker": author,
                "timestamp": timestamp,
            }

            try:
                success = await texture_layer.store(formatted_content, metadata)
                if success:
                    ingested_ids.append(msg_id)
                else:
                    errors.append(f"Message {msg_id}: store returned False")
            except Exception as e:
                errors.append(f"Message {msg_id}: {str(e)}")

        # Mark ingested messages
        if ingested_ids:
            with raw_layer.get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ','.join(['?' for _ in ingested_ids])
                cursor.execute(f"""
                    UPDATE messages
                    SET graphiti_ingested = TRUE
                    WHERE id IN ({placeholders})
                """, ingested_ids)
                conn.commit()

        return {
            "success": len(errors) == 0,
            "message": f"Ingested {len(ingested_ids)} of {len(messages)} messages",
            "ingested": len(ingested_ids),
            "remaining": uningested_count - len(ingested_ids),
            "errors": errors if errors else None
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch ingestion failed: {str(e)}")


@app.post("/tools/enter_space")
async def enter_space(request: EnterSpaceRequest):
    """
    Enter a space and load its description for context.

    Use when moving to a different location. Returns the space description
    for use in extraction context and scene awareness.
    """
    if not request.space_name:
        raise HTTPException(status_code=400, detail="space_name is required")

    description = await inventory.enter_space(request.space_name)

    if description is None:
        # Space not found - return helpful message
        spaces = await inventory.list_spaces()
        space_names = [s['name'] for s in spaces] if spaces else []

        return {
            "success": False,
            "message": f"Space '{request.space_name}' not found",
            "available_spaces": space_names
        }

    return {
        "success": True,
        "space_name": request.space_name,
        "description": description
    }


@app.get("/tools/list_spaces")
async def list_spaces():
    """
    List all known spaces/rooms/locations.

    Returns space names, descriptions, and visit counts.
    """
    spaces = await inventory.list_spaces()

    return {
        "spaces": [
            {
                "name": s.get('name'),
                "description": s.get('description'),
                "emotional_quality": s.get('emotional_quality'),
                "visit_count": s.get('visit_count', 0),
                "last_visited": s.get('last_visited')
            }
            for s in spaces
        ],
        "count": len(spaces)
    }


# =============================================================================
# Phase 2 HTTP Migration Endpoints (19 additional)
# These complete the HTTP endpoint coverage for all 38 MCP tools
# =============================================================================


# === Anchor Management (3) ===

@app.delete("/tools/anchor_delete/{filename}")
async def anchor_delete(filename: str):
    """
    Delete a word-photo from both disk and ChromaDB.
    Use for removing outdated or erroneous anchors.
    """
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")
    
    layer = layers[LayerType.CORE_ANCHORS]
    if hasattr(layer, 'delete'):
        result = await layer.delete(filename)
        return result
    else:
        raise HTTPException(
            status_code=501,
            detail="Delete not available (ChromaDB layer required)"
        )


@app.get("/tools/anchor_list")
async def anchor_list():
    """
    List all word-photos with sync status.
    Shows files on disk, entries in ChromaDB, orphans, and missing items.
    """
    layer = layers[LayerType.CORE_ANCHORS]
    if hasattr(layer, 'list_anchors'):
        result = await layer.list_anchors()
        return result
    else:
        raise HTTPException(
            status_code=501,
            detail="List not available (ChromaDB layer required)"
        )


@app.post("/tools/anchor_resync")
async def anchor_resync():
    """
    Nuclear option: wipe ChromaDB collection and rebuild from disk files.
    Use when things get out of sync and you need a clean slate.
    """
    layer = layers[LayerType.CORE_ANCHORS]
    if hasattr(layer, 'resync'):
        result = await layer.resync()
        return result
    else:
        raise HTTPException(
            status_code=501,
            detail="Resync not available (ChromaDB layer required)"
        )


# === Crystal Management (2) ===

@app.delete("/tools/crystal_delete")
async def crystal_delete():
    """
    Delete the most recent crystal ONLY.
    Crystals form a chain - only the latest can be deleted to preserve integrity.
    Use when a crystal was created with errors and needs to be re-crystallized.
    """
    layer = layers[LayerType.CRYSTALLIZATION]
    result = await layer.delete_latest()
    
    if not result.get("success", False):
        raise HTTPException(
            status_code=500,
            detail=result.get("message", "Failed to delete crystal")
        )
    
    return result


@app.get("/tools/crystal_list")
async def crystal_list():
    """
    List all crystals with metadata.
    Shows current crystals (rolling window of 4) and archived ones.
    Includes filename, number, size, modified date, and preview.
    """
    layer = layers[LayerType.CRYSTALLIZATION]
    result = await layer.list_crystals()
    return result


# === Raw Capture (1) ===

@app.post("/tools/get_turns_since_crystal")
async def get_turns_since_crystal(request: GetTurnsSinceCrystalRequest):
    """
    Get conversation turns from SQLite that occurred after the last crystal.
    Use for manual exploration of raw history.
    Always returns at least min_turns to ensure grounding even if crystal just happened.
    """
    # Get the timestamp of the last crystal
    crystal_layer = layers[LayerType.CRYSTALLIZATION]
    last_crystal_time = await crystal_layer.get_latest_timestamp()
    
    # Query SQLite for turns
    raw_layer = layers[LayerType.RAW_CAPTURE]
    try:
        rows_after = []
        rows_before = []
        
        with raw_layer.get_connection() as conn:
            cursor = conn.cursor()
            
            if last_crystal_time:
                # Get most recent turns after the last crystal
                query = """
                    SELECT author_name, content, created_at, channel
                    FROM messages
                    WHERE created_at > ?
                """
                params = [last_crystal_time.isoformat()]
                if request.channel:
                    query += " AND channel LIKE ?"
                    params.append(f"%{request.channel}%")
                query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                params.extend([request.limit, request.offset])
                cursor.execute(query, params)
                rows_after = list(reversed(cursor.fetchall()))
                
                # If we don't have enough turns, get some from before the crystal
                if len(rows_after) < request.min_turns:
                    needed = request.min_turns - len(rows_after)
                    query = """
                        SELECT author_name, content, created_at, channel
                        FROM messages
                        WHERE created_at <= ?
                    """
                    params = [last_crystal_time.isoformat()]
                    if request.channel:
                        query += " AND channel LIKE ?"
                        params.append(f"%{request.channel}%")
                    query += " ORDER BY created_at DESC LIMIT ?"
                    params.append(needed)
                    cursor.execute(query, params)
                    rows_before = list(reversed(cursor.fetchall()))
            else:
                # No crystal yet, just get recent messages
                query = """
                    SELECT author_name, content, created_at, channel
                    FROM messages
                """
                params = []
                if request.channel:
                    query += " WHERE channel LIKE ?"
                    params.append(f"%{request.channel}%")
                query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                params.extend([request.limit, request.offset])
                cursor.execute(query, params)
                rows_after = list(reversed(cursor.fetchall()))
        
        # Format turns
        turns = []
        for row in rows_before + rows_after:
            turns.append({
                "timestamp": row['created_at'][:16] if row['created_at'] else "?",
                "channel": row['channel'] or "",
                "author": row['author_name'] or "Unknown",
                "content": row['content'] or ""
            })
        
        return {
            "turns": turns,
            "count": len(turns),
            "last_crystal_time": last_crystal_time.isoformat() if last_crystal_time else None
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get turns: {str(e)}")


# === Message Summaries (3) ===

@app.post("/tools/get_recent_summaries")
async def get_recent_summaries(request: GetRecentSummariesRequest):
    """
    Get the most recent message summaries for startup context.
    Returns compressed history instead of raw conversation turns.
    """
    summaries = message_summaries.get_recent_summaries(request.limit)
    
    if not summaries:
        return {
            "summaries": [],
            "message": "No message summaries found."
        }
    
    return {
        "summaries": [
            {
                "id": s['id'],
                "message_count": s['message_count'],
                "time_span": f"{s['time_span_start'][:16]} to {s['time_span_end'][:16]}",
                "summary_text": s['summary_text'],
                "channels": s.get('channels', []),
                "created_at": s['created_at']
            }
            for s in summaries
        ],
        "count": len(summaries)
    }


@app.post("/tools/search_summaries")
async def search_summaries(request: SearchSummariesRequest):
    """
    Search message summaries for specific content.
    Use for contextual retrieval of compressed work history.
    """
    results = await message_summaries.search(request.query, request.limit)
    
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


@app.get("/tools/summary_stats")
async def summary_stats():
    """
    Get statistics about message summarization.
    Shows count of unsummarized messages and recent summary activity.
    """
    unsummarized_count = message_summaries.count_unsummarized_messages()
    recent_summaries = message_summaries.get_recent_summaries(3)
    
    SUMMARIZATION_THRESHOLD = 50  # Match constant from server.py
    
    stats = {
        "unsummarized_messages": unsummarized_count,
        "recent_summaries": len(recent_summaries),
        "last_summary_date": recent_summaries[0]['created_at'] if recent_summaries else None,
        "needs_summarization": unsummarized_count >= SUMMARIZATION_THRESHOLD
    }
    
    return stats


# === Graphiti Stats (1) ===

@app.get("/tools/graphiti_ingestion_stats")
async def graphiti_ingestion_stats():
    """
    Get statistics about Graphiti batch ingestion.
    Shows count of uningested messages and recent ingestion activity.
    Use to decide if batch ingestion is needed.
    """
    uningested_count = message_summaries.count_uningested_to_graphiti()
    
    stats = {
        "uningested_messages": uningested_count,
        "needs_ingestion": uningested_count >= 20,
        "recommendation": "Run ingest_batch_to_graphiti" if uningested_count >= 20 else "No action needed"
    }
    
    return stats


# === Inventory (Layer 5) (5) ===

@app.post("/tools/inventory_list")
async def inventory_list(request: InventoryListRequest):
    """
    List items in a category (clothing, spaces, people, food, artifacts, symbols).
    Use for 'what do I have?' queries. Complements Graphiti semantic search.
    """
    if not request.category:
        raise HTTPException(status_code=400, detail="category required")
    
    items = await inventory.list_category(request.category, request.subcategory, request.limit)
    
    if not items:
        return {
            "items": [],
            "message": f"No items found in category '{request.category}'"
        }
    
    return {
        "items": items,
        "count": len(items),
        "category": request.category,
        "subcategory": request.subcategory
    }


@app.post("/tools/inventory_add")
async def inventory_add(request: InventoryAddRequest):
    """
    Add an item to inventory.
    Use when acquiring new possessions, discovering new spaces, or meeting new people.
    """
    if not request.name or not request.category:
        raise HTTPException(status_code=400, detail="name and category required")
    
    success = await inventory.add_item(
        name=request.name,
        category=request.category,
        subcategory=request.subcategory,
        description=request.description,
        attributes=request.attributes or {}
    )
    
    if success:
        return {
            "success": True,
            "message": f"Added '{request.name}' to category '{request.category}'"
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to add item")


@app.post("/tools/inventory_get")
async def inventory_get(request: InventoryGetRequest):
    """
    Get details about a specific inventory item.
    """
    if not request.name or not request.category:
        raise HTTPException(status_code=400, detail="name and category required")
    
    item = await inventory.get_item(request.name, request.category)
    
    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"Item '{request.name}' not found in category '{request.category}'"
        )
    
    return {"item": item}


@app.delete("/tools/inventory_delete")
async def inventory_delete(request: InventoryDeleteRequest):
    """
    Delete an inventory item.
    Use to remove outdated or duplicate entries.
    """
    if not request.name or not request.category:
        raise HTTPException(status_code=400, detail="name and category required")
    
    success = await inventory.delete_item(request.name, request.category)
    
    if success:
        return {
            "success": True,
            "message": f"Deleted '{request.name}' from category '{request.category}'"
        }
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Item '{request.name}' not found in category '{request.category}'"
        )


@app.get("/tools/inventory_categories")
async def inventory_categories():
    """
    List all inventory categories with item counts.
    """
    categories = await inventory.list_categories()
    
    return {
        "categories": categories,
        "count": len(categories)
    }


# === Tech RAG (Layer 6) (4) ===

@app.post("/tools/tech_search")
async def tech_search(request: TechSearchRequest):
    """
    Search technical documentation in the Tech RAG.
    Use for finding architecture info, API docs, design decisions.
    Family knowledge - searchable by any entity.
    """
    if tech_rag is None:
        raise HTTPException(
            status_code=503,
            detail="Tech RAG not available (requires ChromaDB)"
        )
    
    if not request.query:
        raise HTTPException(status_code=400, detail="query required")
    
    results = await tech_rag.search(request.query, request.limit, request.category)
    
    if not results:
        return {
            "results": [],
            "message": "No results found in Tech RAG."
        }
    
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


@app.post("/tools/tech_ingest")
async def tech_ingest(request: TechIngestRequest):
    """
    Ingest a markdown file into the Tech RAG.
    Automatically chunks for better retrieval.
    Use to index architecture docs, guides, design documents.
    """
    if tech_rag is None:
        raise HTTPException(
            status_code=503,
            detail="Tech RAG not available (requires ChromaDB)"
        )
    
    if not request.filepath:
        raise HTTPException(status_code=400, detail="filepath required")
    
    # Check if file exists
    if not Path(request.filepath).exists():
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {request.filepath}"
        )
    
    result = await tech_rag.ingest(request.filepath, request.category)
    
    if result.get("success", False):
        return result
    else:
        raise HTTPException(
            status_code=500,
            detail=result.get("message", "Failed to ingest file")
        )


@app.get("/tools/tech_list")
async def tech_list():
    """
    List all documents indexed in the Tech RAG.
    """
    if tech_rag is None:
        raise HTTPException(
            status_code=503,
            detail="Tech RAG not available (requires ChromaDB)"
        )
    
    documents = await tech_rag.list_documents()
    
    return {
        "documents": documents,
        "count": len(documents)
    }


@app.delete("/tools/tech_delete/{doc_id}")
async def tech_delete(doc_id: str):
    """
    Delete a document from the Tech RAG by doc_id.
    """
    if tech_rag is None:
        raise HTTPException(
            status_code=503,
            detail="Tech RAG not available (requires ChromaDB)"
        )
    
    if not doc_id:
        raise HTTPException(status_code=400, detail="doc_id required")
    
    result = await tech_rag.delete_document(doc_id)
    
    if result.get("success", False):
        return result
    else:
        raise HTTPException(
            status_code=500,
            detail=result.get("message", "Failed to delete document")
        )



if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
