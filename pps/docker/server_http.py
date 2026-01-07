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

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn


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


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from layers import LayerType
from layers.raw_capture import RawCaptureLayer
from layers.core_anchors import CoreAnchorsLayer
from layers.crystallization import CrystallizationLayer

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: verify connections
    print(f"PPS Server starting...")
    print(f"  ChromaDB: {CHROMA_HOST}:{CHROMA_PORT}")
    print(f"  USE_CHROMA: {USE_CHROMA}")
    print(f"  USE_RICH_TEXTURE_V2: {USE_RICH_TEXTURE_V2}")

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

    return {
        "clock": {
            "timestamp": now.isoformat(),
            "display": now.strftime("%A, %B %d, %Y at %I:%M %p"),
            "hour": hour,
            "note": time_note
        },
        "results": all_results
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


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
