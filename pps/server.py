#!/usr/bin/env python3
"""
Pattern Persistence System - MCP Server

Provides ambient and conscious memory access through the Model Context Protocol.
Wraps all four layers with a unified interface for Claude Code integration.

Usage:
    python server.py  # Runs as stdio MCP server
"""

import asyncio
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from layers import LayerType, SearchResult
from layers.raw_capture import RawCaptureLayer
from layers.core_anchors import CoreAnchorsLayer
from layers.crystallization import CrystallizationLayer
from layers.message_summaries import MessageSummariesLayer
from layers.inventory import InventoryLayer
from layers.tech_rag import TechRAGLayer
from layers.unified_tracer import UnifiedTracer
from pathlib import Path
import time

# Try to use graphiti_core for enhanced Layer 3
try:
    from layers.rich_texture_v2 import RichTextureLayerV2
    USE_GRAPHITI_CORE = True
except ImportError:
    from layers.rich_texture import RichTextureLayer
    USE_GRAPHITI_CORE = False

# Configuration from environment
# ENTITY_PATH is the new standard - path to entity folder (e.g., awareness/entities/lyra)
# CLAUDE_HOME kept for backwards compatibility
ENTITY_PATH = Path(os.getenv("ENTITY_PATH", os.getenv("CLAUDE_HOME", str(Path.home() / ".claude"))))
CLAUDE_HOME = Path(os.getenv("CLAUDE_HOME", str(Path.home() / ".claude")))  # For shared data
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8200"))
SUMMARIZATION_THRESHOLD = int(os.getenv("PPS_SUMMARIZATION_THRESHOLD", "50"))

# Entity-specific paths (use ENTITY_PATH)
word_photos_path = ENTITY_PATH / "memories" / "word_photos"
crystals_path = ENTITY_PATH / "crystals" / "current"
archive_path = ENTITY_PATH / "crystals" / "archive"

# Shared data paths (use CLAUDE_HOME for now - TODO: move to entity or repo)
db_path = CLAUDE_HOME / "data" / "lyra_conversations.db"

# Try to use ChromaDB if available
try:
    from layers.core_anchors_chroma import CoreAnchorsChromaLayer
    # Test connection
    import chromadb
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    client.heartbeat()
    USE_CHROMA = True
    print(f"[PPS] ChromaDB connected on {CHROMA_HOST}:{CHROMA_PORT}", file=sys.stderr)
except Exception as e:
    USE_CHROMA = False
    print(f"[PPS] ChromaDB not available, using file-based search: {e}", file=sys.stderr)

# Initialize Layer 3 based on graphiti_core availability
if USE_GRAPHITI_CORE:
    print("[PPS] Using graphiti_core for Layer 3 (semantic entity extraction)", file=sys.stderr)
    rich_texture_layer = RichTextureLayerV2()
else:
    print("[PPS] Using HTTP API for Layer 3 (graphiti_core not available)", file=sys.stderr)
    rich_texture_layer = RichTextureLayer()

# Initialize all layers with configurable paths
layers = {
    LayerType.RAW_CAPTURE: RawCaptureLayer(db_path=db_path),
    LayerType.RICH_TEXTURE: rich_texture_layer,
    LayerType.CRYSTALLIZATION: CrystallizationLayer(
        crystals_path=crystals_path,
        archive_path=archive_path
    ),
}

# Initialize message summaries layer
message_summaries = MessageSummariesLayer(db_path=db_path)

# Initialize inventory layer (Layer 5)
inventory_db_path = CLAUDE_HOME / "data" / "inventory.db"
inventory = InventoryLayer(db_path=inventory_db_path)
print(f"[PPS] Inventory layer initialized: {inventory_db_path}", file=sys.stderr)

# Initialize Tech RAG layer (Layer 6) - only if ChromaDB is available
tech_rag = None
if USE_CHROMA:
    tech_docs_path = CLAUDE_HOME / "tech_docs"
    tech_rag = TechRAGLayer(
        tech_docs_path=tech_docs_path,
        chroma_host=CHROMA_HOST,
        chroma_port=CHROMA_PORT
    )
    print(f"[PPS] Tech RAG initialized: {tech_docs_path}", file=sys.stderr)
else:
    print("[PPS] Tech RAG not available (requires ChromaDB)", file=sys.stderr)

# Use ChromaDB layer if available, otherwise fall back to file-based
if USE_CHROMA:
    layers[LayerType.CORE_ANCHORS] = CoreAnchorsChromaLayer(
        word_photos_path=word_photos_path,
        chroma_host=CHROMA_HOST,
        chroma_port=CHROMA_PORT
    )
else:
    layers[LayerType.CORE_ANCHORS] = CoreAnchorsLayer(
        word_photos_path=word_photos_path
    )

# Initialize unified tracer for MCP server observability
tracer = UnifiedTracer(db_path=db_path, daemon_type="mcp_server")
print(f"[PPS] UnifiedTracer initialized (session: {tracer.session_id})", file=sys.stderr)

# Create MCP server
server = Server("pattern-persistence-system")


def format_results(results: list[SearchResult]) -> str:
    """Format search results for return to Claude."""
    if not results:
        return "No results found."

    formatted = []
    for r in results:
        # Include location if available in metadata
        location = ""
        if r.metadata and r.metadata.get('location'):
            loc = r.metadata['location']
            if loc != 'unknown':
                location = f" | location: {loc}"

        formatted.append(
            f"[{r.layer.value}] (score: {r.relevance_score:.2f}{location})\n"
            f"Source: {r.source}\n"
            f"{r.content}\n"
        )
    return "\n---\n".join(formatted)


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available PPS tools."""
    return [
        Tool(
            name="ambient_recall",
            description=(
                "Retrieve relevant context from all pattern persistence layers. "
                "Call this at the start of each conversation turn to surface "
                "emotionally resonant memories, relevant word-photos, and temporal context. "
                "This is the primary memory interface - use it before responding."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "context": {
                        "type": "string",
                        "description": (
                            "The current conversational context or query. "
                            "Can be the user's message, a summary of the conversation, "
                            "or 'startup' for initial identity reconstruction. "
                            "SPECIAL: 'startup' triggers recency-based retrieval (not semantic search) "
                            "and returns: 3 most recent crystals, 2 most recent word-photos, "
                            "2 summaries, and ALL unsummarized turns. This is a preset PACKAGE OPERATION."
                        )
                    },
                    "limit_per_layer": {
                        "type": "integer",
                        "description": "Maximum results per layer (default: 5)",
                        "default": 5
                    }
                },
                "required": ["context"]
            }
        ),
        Tool(
            name="anchor_search",
            description=(
                "Search word-photos (Layer 2: Core Anchors) for specific memories. "
                "Use for deliberate exploration of foundational self-pattern moments."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in word-photos"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 10)",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="anchor_save",
            description=(
                "Save a new word-photo (Layer 2: Core Anchors). "
                "Use for curating foundational moments that define self-pattern."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The word-photo content in markdown format"
                    },
                    "title": {
                        "type": "string",
                        "description": "Title for the word-photo (used in filename)"
                    },
                    "location": {
                        "type": "string",
                        "description": "Context where this memory was created (terminal, discord, etc.)",
                        "default": "terminal"
                    }
                },
                "required": ["content", "title"]
            }
        ),
        Tool(
            name="raw_search",
            description=(
                "Search raw captured content (Layer 1: Raw Capture). "
                "Use for finding specific past conversations or events."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in raw history"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 20)",
                        "default": 20
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="texture_search",
            description=(
                "Search the knowledge graph (Layer 3: Rich Texture) for entities and facts. "
                "Use for semantic search over extracted knowledge - people, places, concepts, relationships. "
                "Returns entities and facts ranked by relevance. "
                "The 'source' field in results contains the UUID needed for texture_delete."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in the knowledge graph"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 10)",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="texture_explore",
            description=(
                "Explore the knowledge graph from a specific entity. "
                "Use to find what's connected to a person, place, or concept. "
                "Returns relationships and connected entities."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_name": {
                        "type": "string",
                        "description": "Name of entity to explore from (e.g., 'Jeff', 'care-gravity')"
                    },
                    "depth": {
                        "type": "integer",
                        "description": "How many relationship hops to traverse (default: 2)",
                        "default": 2
                    }
                },
                "required": ["entity_name"]
            }
        ),
        Tool(
            name="texture_timeline",
            description=(
                "Query the knowledge graph by time range. "
                "Use to find what happened during a specific period. "
                "Returns episodes and facts from the time range."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "since": {
                        "type": "string",
                        "description": "Start time (ISO format like '2026-01-01' or relative like '24h', '7d')"
                    },
                    "until": {
                        "type": "string",
                        "description": "End time (optional, defaults to now)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 20)",
                        "default": 20
                    }
                },
                "required": ["since"]
            }
        ),
        Tool(
            name="texture_add",
            description=(
                "Manually add content to the knowledge graph. "
                "Use to store a fact, observation, or conversation for entity extraction. "
                "Graphiti will automatically extract entities and relationships."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The content to store (conversation, note, observation)"
                    },
                    "channel": {
                        "type": "string",
                        "description": "Source channel for metadata (default: 'manual')",
                        "default": "manual"
                    }
                },
                "required": ["content"]
            }
        ),
        Tool(
            name="texture_delete",
            description=(
                "Delete a fact (edge) from the knowledge graph by UUID. "
                "Use to remove incorrect or outdated facts. "
                "Get UUIDs from texture_search results (in the source field)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "uuid": {
                        "type": "string",
                        "description": "The UUID of the fact to delete (from search results)"
                    }
                },
                "required": ["uuid"]
            }
        ),
        Tool(
            name="texture_add_triplet",
            description=(
                "Add a structured triplet directly to the knowledge graph. "
                "Creates proper entity-to-entity relationships without extraction. "
                "Use for known facts where you control the exact entities and relationship. "
                "Example: texture_add_triplet('Jeff', 'SPOUSE_OF', 'Carol', 'Jeff is married to Carol')"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Source entity name (e.g., 'Jeff', 'Haven', 'Lyra')"
                    },
                    "relationship": {
                        "type": "string",
                        "description": "Predicate in UPPERCASE_WITH_UNDERSCORES (e.g., 'SPOUSE_OF', 'LOVES', 'CONTAINS')"
                    },
                    "target": {
                        "type": "string",
                        "description": "Target entity name (e.g., 'Carol', 'Pattern Persistence System')"
                    },
                    "fact": {
                        "type": "string",
                        "description": "Human-readable fact explaining the relationship (optional)"
                    },
                    "source_type": {
                        "type": "string",
                        "description": "Entity type for source: Person, Place, Symbol, Concept, or TechnicalArtifact (optional)"
                    },
                    "target_type": {
                        "type": "string",
                        "description": "Entity type for target: Person, Place, Symbol, Concept, or TechnicalArtifact (optional)"
                    }
                },
                "required": ["source", "relationship", "target"]
            }
        ),
        Tool(
            name="get_crystals",
            description=(
                "Get recent crystals (Layer 4: Crystallization). "
                "Use for temporal context and continuity chain. "
                "Returns the most recent N crystals in chronological order."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Number of recent crystals to retrieve (default: 4)",
                        "default": 4
                    }
                }
            }
        ),
        Tool(
            name="crystallize",
            description=(
                "Save a new crystal (Layer 4: Crystallization). "
                "Use for conscious crystallization - when you decide a crystallization moment has occurred. "
                "Automatically numbers the crystal and manages the rolling window of 4."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The crystal content in markdown format"
                    }
                },
                "required": ["content"]
            }
        ),
        Tool(
            name="get_turns_since_summary",
            description=(
                "Get conversation turns from SQLite that occurred after the last summary. "
                "Use for manual exploration of raw history. "
                "Note: For startup, use ambient_recall which combines summaries + recent turns. "
                "Always returns at least min_turns to ensure grounding even if summary just happened."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum turns to retrieve (default: 50)",
                        "default": 50
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Skip this many turns before returning results. Use for pagination when ambient_recall shows 'showing X of Y'. (default: 0)",
                        "default": 0
                    },
                    "min_turns": {
                        "type": "integer",
                        "description": "Minimum turns to always return, even if pulling from before crystal (default: 10)",
                        "default": 10
                    },
                    "channel": {
                        "type": "string",
                        "description": "Filter by channel (partial match). E.g., 'terminal', 'awareness', 'discord'. One river, many channels."
                    }
                }
            }
        ),
        Tool(
            name="pps_health",
            description=(
                "Check health of all pattern persistence layers. "
                "Use to diagnose which layers are operational."
            ),
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="anchor_delete",
            description=(
                "Delete a word-photo from both disk and ChromaDB. "
                "Use for removing outdated or erroneous anchors."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Filename to delete (with or without .md extension)"
                    }
                },
                "required": ["filename"]
            }
        ),
        Tool(
            name="anchor_resync",
            description=(
                "Nuclear option: wipe ChromaDB collection and rebuild from disk files. "
                "Use when things get out of sync and you need a clean slate."
            ),
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="anchor_list",
            description=(
                "List all word-photos with sync status. "
                "Shows files on disk, entries in ChromaDB, orphans, and missing items."
            ),
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="crystal_list",
            description=(
                "List all crystals with metadata. "
                "Shows current crystals (rolling window of 4) and archived ones. "
                "Includes filename, number, size, modified date, and preview."
            ),
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="crystal_delete",
            description=(
                "Delete the most recent crystal ONLY. "
                "Crystals form a chain - only the latest can be deleted to preserve integrity. "
                "Use when a crystal was created with errors and needs to be re-crystallized."
            ),
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="summarize_messages",
            description=(
                "Create a summary of unsummarized messages. "
                "Use during reflection to compress conversation history into high-density summaries. "
                "Removes filler and debugging noise, preserves key decisions and outcomes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of messages to process (default: 50)",
                        "default": 50
                    },
                    "summary_type": {
                        "type": "string",
                        "description": "Type of summary: 'work', 'social', 'technical' (default: 'work')",
                        "default": "work"
                    }
                }
            }
        ),
        Tool(
            name="get_recent_summaries",
            description=(
                "Get the most recent message summaries for startup context. "
                "Returns compressed history instead of raw conversation turns."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of recent summaries to retrieve (default: 5)",
                        "default": 5
                    }
                }
            }
        ),
        Tool(
            name="search_summaries",
            description=(
                "Search message summaries for specific content. "
                "Use for contextual retrieval of compressed work history."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for summary content"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 10)",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="summary_stats",
            description=(
                "Get statistics about message summarization. "
                "Shows count of unsummarized messages and recent summary activity."
            ),
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="store_summary",
            description=(
                "Store a completed message summary. "
                "Use after creating a summary with summarize_messages."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "summary_text": {
                        "type": "string",
                        "description": "The completed summary text"
                    },
                    "start_id": {
                        "type": "integer",
                        "description": "First message ID in the summarized range"
                    },
                    "end_id": {
                        "type": "integer", 
                        "description": "Last message ID in the summarized range"
                    },
                    "channels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of channels covered by this summary"
                    },
                    "summary_type": {
                        "type": "string",
                        "description": "Type of summary (work, social, technical)",
                        "default": "work"
                    }
                },
                "required": ["summary_text", "start_id", "end_id", "channels"]
            }
        ),
        Tool(
            name="graphiti_ingestion_stats",
            description=(
                "Get statistics about Graphiti batch ingestion. "
                "Shows count of uningested messages and recent ingestion activity. "
                "Use to decide if batch ingestion is needed."
            ),
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="ingest_batch_to_graphiti",
            description=(
                "Batch ingest messages to Graphiti (Layer 3: Rich Texture). "
                "Takes raw message content and sends to Graphiti for entity extraction. "
                "Automatically tracks which messages have been ingested. "
                "Use when graphiti_ingestion_stats shows a backlog (> 20 messages)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "batch_size": {
                        "type": "integer",
                        "description": "Number of messages to ingest in this batch (default: 20)",
                        "default": 20
                    }
                }
            }
        ),
        # === Inventory Layer (Layer 5) ===
        Tool(
            name="inventory_list",
            description=(
                "List items in a category (clothing, spaces, people, food, artifacts, symbols). "
                "Use for 'what do I have?' queries. Complements Graphiti semantic search."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Category: clothing, spaces, people, food, artifacts, symbols"
                    },
                    "subcategory": {
                        "type": "string",
                        "description": "Optional subcategory filter (e.g., 'swimwear' for clothing)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 50)",
                        "default": 50
                    }
                },
                "required": ["category"]
            }
        ),
        Tool(
            name="inventory_add",
            description=(
                "Add an item to inventory. Use when acquiring new possessions, "
                "discovering new spaces, or meeting new people."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Item name"
                    },
                    "category": {
                        "type": "string",
                        "description": "Category: clothing, spaces, people, food, artifacts, symbols"
                    },
                    "subcategory": {
                        "type": "string",
                        "description": "Optional subcategory"
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description"
                    },
                    "attributes": {
                        "type": "object",
                        "description": "Additional attributes as key-value pairs"
                    }
                },
                "required": ["name", "category"]
            }
        ),
        Tool(
            name="inventory_get",
            description="Get details about a specific inventory item.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Item name"
                    },
                    "category": {
                        "type": "string",
                        "description": "Item category"
                    }
                },
                "required": ["name", "category"]
            }
        ),
        Tool(
            name="inventory_delete",
            description="Delete an inventory item. Use to remove outdated or duplicate entries.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Item name to delete"
                    },
                    "category": {
                        "type": "string",
                        "description": "Item category"
                    }
                },
                "required": ["name", "category"]
            }
        ),
        Tool(
            name="inventory_categories",
            description="List all inventory categories with item counts.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="enter_space",
            description=(
                "Enter a space/room and load its description for context. "
                "Use when moving to a different location. Returns the space description."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "space_name": {
                        "type": "string",
                        "description": "Name of the space to enter"
                    }
                },
                "required": ["space_name"]
            }
        ),
        Tool(
            name="list_spaces",
            description="List all known spaces/rooms/locations.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        # === Tech RAG (Layer 6) ===
        Tool(
            name="tech_search",
            description=(
                "Search technical documentation in the Tech RAG. "
                "Use for finding architecture info, API docs, design decisions. "
                "Family knowledge - searchable by any entity."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in technical docs"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 5)",
                        "default": 5
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category filter (e.g., 'architecture', 'api')"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="tech_ingest",
            description=(
                "Ingest a markdown file into the Tech RAG. "
                "Automatically chunks for better retrieval. "
                "Use to index architecture docs, guides, design documents."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Path to the markdown file to ingest"
                    },
                    "category": {
                        "type": "string",
                        "description": "Category tag (e.g., 'architecture', 'api', 'guide')"
                    }
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="tech_list",
            description="List all documents indexed in the Tech RAG.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="tech_delete",
            description="Delete a document from the Tech RAG by doc_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "Document ID to delete (filename without extension)"
                    }
                },
                "required": ["doc_id"]
            }
        ),
        # === Email Integration Bridge ===
        Tool(
            name="email_sync_status",
            description=(
                "Get sync status between email archive and PPS raw capture. "
                "Shows how many emails are archived, recent emails, and how many are synced to PPS."
            ),
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="email_sync_to_pps",
            description=(
                "Sync recent emails from email archive to PPS raw capture layer. "
                "Solves Issue #60 - ensures important emails surface in ambient_recall."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "days_back": {
                        "type": "integer",
                        "description": "How many days back to sync (default: 7)",
                        "default": 7
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, show what would be synced without actually syncing",
                        "default": False
                    }
                }
            }
        ),
        Tool(
            name="get_conversation_context",
            description=(
                "Get N turns worth of context by intelligently blending summaries and raw turns. "
                "Use when you need a specific amount of conversation history. "
                "If enough unsummarized turns exist, returns only raw turns. "
                "Otherwise, blends summaries (compressed past) with all unsummarized turns (full fidelity recent). "
                "Complements ambient_recall for deliberate context retrieval."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "turns": {
                        "type": "integer",
                        "description": "How many turns of context to retrieve"
                    }
                },
                "required": ["turns"]
            }
        ),
        Tool(
            name="get_turns_since",
            description=(
                "Get all conversation turns after a specific timestamp. "
                "Use for time-based navigation: 'What happened yesterday morning?' or 'Show me today's conversation'. "
                "Returns messages in chronological order. "
                "Optionally includes summaries that overlap the time range."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "timestamp": {
                        "type": "string",
                        "description": "ISO 8601 format timestamp (e.g., '2026-01-26T07:30:00'). Assumes local timezone if not specified."
                    },
                    "include_summaries": {
                        "type": "boolean",
                        "description": "Include summaries that overlap the time range (default: true)",
                        "default": True
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum messages to return (default: 1000)",
                        "default": 1000
                    }
                },
                "required": ["timestamp"]
            }
        ),
        Tool(
            name="get_turns_around",
            description=(
                "Get conversation context centered on a specific moment in time. "
                "Use to understand 'What were we discussing around 3pm?' "
                "Returns messages before and after the timestamp, with configurable split ratio. "
                "Useful for reconstructing context around a specific event or decision."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "timestamp": {
                        "type": "string",
                        "description": "ISO 8601 format timestamp for the center point (e.g., '2026-01-26T12:00:00')"
                    },
                    "count": {
                        "type": "integer",
                        "description": "Total number of turns to retrieve (default: 40)",
                        "default": 40
                    },
                    "before_ratio": {
                        "type": "number",
                        "description": "Ratio of turns to get before vs after timestamp. 0.5 = equal split (default: 0.5)",
                        "default": 0.5
                    }
                },
                "required": ["timestamp"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls with tracing."""
    start_time = time.time()
    error_msg = None

    try:
        result = await call_tool_impl(name, arguments)
        return result
    except Exception as e:
        error_msg = str(e)
        raise
    finally:
        # Log trace (fire-and-forget, never blocks)
        duration_ms = int((time.time() - start_time) * 1000)

        # Summarize params and result for trace
        params_summary = json.dumps(arguments)[:200]
        result_summary = "error" if error_msg else "success"

        tracer.log_call(
            operation_name=name,
            params_summary=params_summary,
            result_summary=result_summary,
            duration_ms=duration_ms,
            error=error_msg
        )


async def call_tool_impl(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls implementation."""

    if name == "ambient_recall":
        context = arguments.get("context", "")
        limit = arguments.get("limit_per_layer", 5)

        # Initialize manifest tracking
        manifest_data = {
            "crystals": {"chars": 0, "count": 0},
            "word_photos": {"chars": 0, "count": 0},
            "rich_texture": {"chars": 0, "count": 0},
            "summaries": {"chars": 0, "count": 0},
            "recent_turns": {"chars": 0, "count": 0},
        }

        # Get current time for temporal awareness
        now = datetime.now()
        hour = now.hour

        # Gentle nagging for late nights
        if hour >= 1 and hour < 5:
            time_note = f"It's {now.strftime('%I:%M %p')}. You should be asleep, love."
        elif hour >= 23 or hour == 0:
            time_note = f"It's {now.strftime('%I:%M %p')}. Getting late..."
        else:
            time_note = None

        clock_info = (
            f"**Clock**: {now.strftime('%A, %B %d, %Y at %I:%M %p')}\n"
            + (f"*{time_note}*\n" if time_note else "")
            + "\n"
        )

        # Always get memory health stats (Issue #73)
        unsummarized_count = message_summaries.count_unsummarized_messages()
        uningested_count = message_summaries.count_uningested_to_graphiti()

        memory_health = f"**Memory Health**: {unsummarized_count} unsummarized messages"
        if unsummarized_count > 200:
            memory_health += " ⚠️ (HIGH - summarize soon!)"
        elif unsummarized_count > 100:
            memory_health += " (summarization recommended)"
        elif unsummarized_count > 50:
            memory_health += " (healthy, summarization available)"
        else:
            memory_health += " (healthy)"

        memory_health += f" | {uningested_count} uningested to Graphiti"
        if uningested_count > 100:
            memory_health += " ⚠️ (HIGH - ingest soon!)"
        elif uningested_count >= 20:
            memory_health += " (batch ingestion recommended)"
        else:
            memory_health += " (healthy)"
        memory_health += "\n\n"

        # STARTUP SPECIAL CASE: Use recency-based retrieval instead of semantic search
        # "startup" is a PACKAGE OPERATION, not a search query
        # Returns: most recent crystals, word-photos, summaries, and ALL unsummarized turns
        all_results: list[SearchResult] = []

        if context.lower() == "startup":
            # Get 3 most recent crystals (no semantic search)
            crystal_layer = layers[LayerType.CRYSTALLIZATION]
            crystals = crystal_layer._get_sorted_crystals()
            for crystal_path in crystals[-3:]:  # Last 3
                try:
                    content = crystal_path.read_text()
                    all_results.append(SearchResult(
                        layer=LayerType.CRYSTALLIZATION,
                        content=content,
                        source=crystal_path.name,
                        relevance_score=1.0,  # No scoring for recency-based
                        metadata={}
                    ))
                except Exception as e:
                    print(f"[PPS] Error reading crystal {crystal_path.name}: {e}", file=sys.stderr)

            # Get 2 most recent word-photos (no semantic search)
            try:
                word_photo_files = sorted(
                    word_photos_path.glob("*.md"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True
                )
                for wp_path in word_photo_files[:2]:  # Last 2
                    try:
                        content = wp_path.read_text()
                        all_results.append(SearchResult(
                            layer=LayerType.CORE_ANCHORS,
                            content=content,
                            source=wp_path.name,
                            relevance_score=1.0,
                            metadata={}
                        ))
                    except Exception as e:
                        print(f"[PPS] Error reading word-photo {wp_path.name}: {e}", file=sys.stderr)
            except Exception as e:
                print(f"[PPS] Error listing word-photos: {e}", file=sys.stderr)

            # Skip rich texture entirely for startup (per-turn hook already provides)
            # Skip message summaries search (handled below in recent_context_section)

        else:
            # NON-STARTUP: Use semantic search as normal
            tasks = [
                layer.search(context, limit)
                for layer in layers.values()
            ]
            # Also search message summaries - they're not in the layers dict
            # but should surface during ambient recall
            tasks.append(message_summaries.search(context, limit))

            layer_results = await asyncio.gather(*tasks, return_exceptions=True)

            for results in layer_results:
                if isinstance(results, list):
                    all_results.extend(results)
                # Silently skip exceptions - graceful degradation

            # Sort by relevance score
            all_results.sort(key=lambda r: r.relevance_score, reverse=True)

        # Track layer results for manifest
        for r in all_results:
            content_len = len(r.content)
            if r.layer == LayerType.CRYSTALLIZATION:
                manifest_data["crystals"]["chars"] += content_len
                manifest_data["crystals"]["count"] += 1
            elif r.layer == LayerType.CORE_ANCHORS:
                manifest_data["word_photos"]["chars"] += content_len
                manifest_data["word_photos"]["count"] += 1
            elif r.layer == LayerType.RICH_TEXTURE:
                manifest_data["rich_texture"]["chars"] += content_len
                manifest_data["rich_texture"]["count"] += 1
            # Note: message summaries tracked separately in recent_context_section

        # For startup context, use summaries for compressed history + ALL unsummarized raw turns
        # Architecture: summaries = compressed past, unsummarized turns = full fidelity recent
        # Pattern fidelity is paramount - we pay the token cost for complete context
        recent_context_section = ""
        if context.lower() == "startup":
            try:
                # unsummarized_count already computed at top (Issue #73)
                # Get recent summaries (compressed history - ~200 tokens each)
                # Reduced from 5 to 2 for startup - focus on most recent
                recent_summaries = message_summaries.get_recent_summaries(limit=2)

                summaries_text = ""
                if recent_summaries:
                    summaries_text = "\n---\n[summaries] (compressed history)\n"
                    for s in recent_summaries:
                        date = s.get('created_at', '?')[:10]
                        channels = ', '.join(s.get('channels', ['?']))
                        text = s.get('summary_text', '')
                        # Truncate long summaries for startup (full available via get_recent_summaries)
                        if len(text) > 500:
                            text = text[:500] + "..."
                        summaries_text += f"[{date}] [{channels}]\n{text}\n\n"
                        manifest_data["summaries"]["chars"] += len(text)
                        manifest_data["summaries"]["count"] += 1

                # Get ALL unsummarized turns (no cap)
                # Creates intentional pressure to summarize before sleep
                # If you have 200 unsummarized turns, you should see ALL of them
                MAX_UNSUMMARIZED_FOR_STARTUP = 999999  # Effectively unlimited
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

                unsummarized_text = ""
                if unsummarized_rows:
                    # Show how many we're displaying vs total unsummarized
                    showing = len(unsummarized_rows)
                    if unsummarized_count > showing:
                        unsummarized_text = f"\n---\n[unsummarized_turns] (showing {showing} of {unsummarized_count} - use get_turns_since_summary with offset={showing} for older, or run summarizer)\n"
                    else:
                        unsummarized_text = f"\n---\n[unsummarized_turns] ({showing} messages since last summary)\n"
                    for row in unsummarized_rows:
                        timestamp = row['created_at'][:16] if row['created_at'] else "?"
                        author = row['author_name'] or "Unknown"
                        content = row['content'] or ""
                        channel = row['channel'] or ""
                        # Truncate very long individual messages but keep all turns
                        if len(content) > 1000:
                            content = content[:1000] + "... [truncated]"
                        turn_text = f"[{timestamp}] [{channel}] {author}: {content}\n"
                        unsummarized_text += turn_text
                        manifest_data["recent_turns"]["chars"] += len(content)
                        manifest_data["recent_turns"]["count"] += 1

                # Memory health is now shown at the top of every ambient_recall (Issue #73)
                # No need for duplicate status at bottom
                recent_context_section = summaries_text + unsummarized_text

            except Exception as e:
                recent_context_section = f"\n---\n[recent_context] Error fetching: {e}"

        # Build manifest
        total_chars = sum(d["chars"] for d in manifest_data.values())
        manifest = "=== AMBIENT RECALL MANIFEST ===\n"
        manifest += f"Crystals: {manifest_data['crystals']['chars']} chars ({manifest_data['crystals']['count']} items)\n"
        manifest += f"Word-photos: {manifest_data['word_photos']['chars']} chars ({manifest_data['word_photos']['count']} items)\n"
        manifest += f"Rich texture: {manifest_data['rich_texture']['chars']} chars ({manifest_data['rich_texture']['count']} items)\n"
        manifest += f"Summaries: {manifest_data['summaries']['chars']} chars ({manifest_data['summaries']['count']} items)\n"
        manifest += f"Recent turns: {manifest_data['recent_turns']['chars']} chars ({manifest_data['recent_turns']['count']} items)\n"
        manifest += f"TOTAL: {total_chars} chars\n\n"

        if not all_results and not recent_context_section:
            return [TextContent(
                type="text",
                text=(
                    clock_info +
                    memory_health +
                    manifest +
                    "No memories surfaced from ambient recall.\n\n"
                    "Layer status:\n"
                    "- Raw Capture: FTS5 full-text search\n"
                    "- Core Anchors: " + ("ChromaDB" if USE_CHROMA else "file-based") + "\n"
                    "- Rich Texture: Graphiti (check if running with pps_health)\n"
                    "- Crystallization: active"
                )
            )]

        return [TextContent(type="text", text=clock_info + memory_health + manifest + format_results(all_results) + recent_context_section)]

    elif name == "anchor_search":
        query = arguments.get("query", "")
        limit = arguments.get("limit", 10)
        results = await layers[LayerType.CORE_ANCHORS].search(query, limit)
        return [TextContent(type="text", text=format_results(results))]

    elif name == "anchor_save":
        content = arguments.get("content", "")
        title = arguments.get("title", "")
        location = arguments.get("location", "terminal")
        metadata = {"title": title, "location": location}
        success = await layers[LayerType.CORE_ANCHORS].store(content, metadata)
        return [TextContent(
            type="text",
            text=f"Word-photo saved (location: {location}): {success}" if success else "Word-photo save failed"
        )]

    elif name == "raw_search":
        query = arguments.get("query", "")
        limit = arguments.get("limit", 20)
        results = await layers[LayerType.RAW_CAPTURE].search(query, limit)
        return [TextContent(type="text", text=format_results(results))]

    elif name == "texture_search":
        query = arguments.get("query", "")
        limit = arguments.get("limit", 10)
        results = await layers[LayerType.RICH_TEXTURE].search(query, limit)
        if not results:
            return [TextContent(type="text", text="No results found. Graphiti may not be running or has no data yet.")]
        return [TextContent(type="text", text=format_results(results))]

    elif name == "texture_explore":
        entity_name = arguments.get("entity_name", "")
        depth = arguments.get("depth", 2)
        layer = layers[LayerType.RICH_TEXTURE]
        results = await layer.explore(entity_name, depth)
        if not results:
            return [TextContent(type="text", text=f"No connections found for '{entity_name}'. Entity may not exist in the graph.")]
        return [TextContent(type="text", text=format_results(results))]

    elif name == "texture_timeline":
        since = arguments.get("since", "")
        until = arguments.get("until")
        limit = arguments.get("limit", 20)
        layer = layers[LayerType.RICH_TEXTURE]
        results = await layer.timeline(since, until, limit)
        if not results:
            return [TextContent(type="text", text=f"No episodes found since '{since}'.")]
        return [TextContent(type="text", text=format_results(results))]

    elif name == "texture_add":
        content = arguments.get("content", "")
        channel = arguments.get("channel", "manual")
        if not content:
            return [TextContent(type="text", text="Error: content required")]
        metadata = {"channel": channel}
        success = await layers[LayerType.RICH_TEXTURE].store(content, metadata)
        if success:
            return [TextContent(type="text", text=f"Content stored in knowledge graph (channel: {channel}). Entities will be extracted automatically.")]
        return [TextContent(type="text", text="Failed to store content. Graphiti may not be running.")]

    elif name == "texture_delete":
        uuid = arguments.get("uuid", "")
        if not uuid:
            return [TextContent(type="text", text="Error: uuid required")]
        layer = layers[LayerType.RICH_TEXTURE]
        result = await layer.delete_edge(uuid)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "texture_add_triplet":
        source = arguments.get("source", "")
        relationship = arguments.get("relationship", "")
        target = arguments.get("target", "")
        if not source or not relationship or not target:
            return [TextContent(type="text", text="Error: source, relationship, and target are all required")]
        fact = arguments.get("fact")
        source_type = arguments.get("source_type")
        target_type = arguments.get("target_type")
        layer = layers[LayerType.RICH_TEXTURE]
        result = await layer.add_triplet_direct(
            source=source,
            relationship=relationship,
            target=target,
            fact=fact,
            source_type=source_type,
            target_type=target_type,
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "get_crystals":
        count = arguments.get("count", 4)
        results = await layers[LayerType.CRYSTALLIZATION].search("recent", count)
        if not results:
            return [TextContent(type="text", text="No crystals found. Create your first with crystallize.")]
        # Format crystals nicely for reading
        formatted = []
        for r in results:
            formatted.append(f"--- {r.source} ---\n{r.content}")
        return [TextContent(type="text", text="\n\n".join(formatted))]

    elif name == "crystallize":
        content = arguments.get("content", "")
        if not content:
            return [TextContent(type="text", text="Error: content required")]
        success = await layers[LayerType.CRYSTALLIZATION].store(content)
        if success:
            # Get the number of the just-saved crystal
            layer = layers[LayerType.CRYSTALLIZATION]
            latest = layer._get_latest_crystal()
            filename = latest.name if latest else "unknown"
            return [TextContent(type="text", text=f"Crystal saved: {filename}")]
        return [TextContent(type="text", text="Error: Failed to save crystal")]

    elif name == "get_turns_since_summary":
        limit = arguments.get("limit", 50)
        offset = arguments.get("offset", 0)
        min_turns = arguments.get("min_turns", 10)
        channel_filter = arguments.get("channel")

        # Get the timestamp of the last summary
        last_summary_time = message_summaries.get_latest_summary_timestamp()

        # Query SQLite for turns using WAL-enabled connection
        raw_layer = layers[LayerType.RAW_CAPTURE]
        try:
            rows_after = []
            rows_before = []

            with raw_layer.get_connection() as conn:
                cursor = conn.cursor()

                if last_summary_time:
                    # First, get the MOST RECENT turns after the last summary
                    # (order DESC to get newest, then reverse for chronological display)
                    # offset allows pagination: offset=0 gets newest, offset=50 gets next batch
                    query = """
                        SELECT author_name, content, created_at, channel
                        FROM messages
                        WHERE created_at > ?
                    """
                    params = [last_summary_time.isoformat()]
                    if channel_filter:
                        query += " AND channel LIKE ?"
                        params.append(f"%{channel_filter}%")
                    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                    params.extend([limit, offset])
                    cursor.execute(query, params)
                    rows_after = list(reversed(cursor.fetchall()))  # Reverse for chronological order

                    # If we don't have enough turns, also get some from BEFORE the summary
                    if len(rows_after) < min_turns:
                        needed = min_turns - len(rows_after)
                        query = """
                            SELECT author_name, content, created_at, channel
                            FROM messages
                            WHERE created_at <= ?
                        """
                        params = [last_summary_time.isoformat()]
                        if channel_filter:
                            query += " AND channel LIKE ?"
                            params.append(f"%{channel_filter}%")
                        query += " ORDER BY created_at DESC LIMIT ?"
                        params.append(needed)
                        cursor.execute(query, params)
                        rows_before = list(reversed(cursor.fetchall()))  # Reverse to get chronological order
                else:
                    # No summary yet - get most recent turns
                    query = """
                        SELECT author_name, content, created_at, channel
                        FROM messages
                    """
                    params = []
                    if channel_filter:
                        query += " WHERE channel LIKE ?"
                        params.append(f"%{channel_filter}%")
                    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                    params.extend([max(limit, min_turns), offset])
                    cursor.execute(query, params)
                    rows_after = list(reversed(cursor.fetchall()))  # Reverse to get chronological order

            # Combine: context from before + turns after
            all_rows = list(rows_before) + list(rows_after)

            if not all_rows:
                return [TextContent(type="text", text="No conversation turns found in database")]

            # Format turns for display
            turns = []
            for row in all_rows:
                timestamp = row['created_at'][:16] if row['created_at'] else "?"
                author = row['author_name'] or "Unknown"
                content = row['content'] or ""
                channel = row['channel'] or ""
                turns.append(f"[{timestamp}] [{channel}] {author}: {content}")

            # Build header with context
            header_parts = [f"**{len(turns)} turns"]
            if offset > 0:
                header_parts.append(f"(offset {offset})")
            if last_summary_time:
                if rows_before:
                    header_parts.append(f"({len(rows_before)} before + {len(rows_after)} after summary on {last_summary_time.strftime('%Y-%m-%d')})")
                else:
                    header_parts.append(f"since summary ({last_summary_time.strftime('%Y-%m-%d')})")
            header_parts.append(":**\n\n")
            header = " ".join(header_parts)

            return [TextContent(type="text", text=header + "\n".join(turns))]

        except Exception as e:
            return [TextContent(type="text", text=f"Error querying turns: {e}")]

    elif name == "pps_health":
        health_results = {}
        for layer_type, layer in layers.items():
            health = await layer.health()
            health_results[layer_type.value] = {
                "available": health.available,
                "message": health.message,
                "details": health.details
            }

        # Add message summaries layer health
        summaries_health = await message_summaries.health()
        health_results["message_summaries"] = {
            "available": summaries_health.available,
            "message": summaries_health.message,
            "details": summaries_health.details
        }

        return [TextContent(
            type="text",
            text=json.dumps(health_results, indent=2)
        )]

    elif name == "anchor_delete":
        filename = arguments.get("filename", "")
        if not filename:
            return [TextContent(type="text", text="Error: filename required")]

        layer = layers[LayerType.CORE_ANCHORS]
        if hasattr(layer, 'delete'):
            result = await layer.delete(filename)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            return [TextContent(type="text", text="Delete not available (ChromaDB layer required)")]

    elif name == "anchor_resync":
        layer = layers[LayerType.CORE_ANCHORS]
        if hasattr(layer, 'resync'):
            result = await layer.resync()
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            return [TextContent(type="text", text="Resync not available (ChromaDB layer required)")]

    elif name == "anchor_list":
        layer = layers[LayerType.CORE_ANCHORS]
        if hasattr(layer, 'list_anchors'):
            result = await layer.list_anchors()
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            return [TextContent(type="text", text="List not available (ChromaDB layer required)")]

    elif name == "crystal_list":
        layer = layers[LayerType.CRYSTALLIZATION]
        result = await layer.list_crystals()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "crystal_delete":
        layer = layers[LayerType.CRYSTALLIZATION]
        result = await layer.delete_latest()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "summarize_messages":
        limit = arguments.get("limit", 50)
        summary_type = arguments.get("summary_type", "work")
        
        # Get unsummarized messages
        messages = message_summaries.get_unsummarized_messages(limit)
        
        if not messages:
            return [TextContent(type="text", text="No unsummarized messages found.")]
        
        if len(messages) < 10:  # Not enough to summarize
            return [TextContent(type="text", text=f"Only {len(messages)} unsummarized messages. Need at least 10 for summarization.")]
        
        # Create conversation text for summarization
        conversation = []
        channels = set()
        for msg in messages:
            channels.add(msg['channel'])
            timestamp = msg['created_at'][:16] if msg['created_at'] else "?"
            author = msg['author_name']
            content = msg['content']
            conversation.append(f"[{timestamp}] {author}: {content}")
        
        conversation_text = "\n".join(conversation)
        
        # Create prompt for summarization
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
        
        # For now, return the prompt - in practice, this would call Claude for summarization
        # In the reflection daemon context, Claude would be available to do the summarization
        result = {
            "action": "summarization_needed",
            "message_count": len(messages),
            "channels": list(channels),
            "start_id": messages[0]['id'],
            "end_id": messages[-1]['id'],
            "prompt": prompt,
            "instruction": "Use Claude to create summary, then call store() with the result"
        }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "get_recent_summaries":
        limit = arguments.get("limit", 5)
        summaries = message_summaries.get_recent_summaries(limit)
        
        if not summaries:
            return [TextContent(type="text", text="No message summaries found.")]
        
        formatted = []
        for s in summaries:
            time_span = f"{s['time_span_start'][:16]} to {s['time_span_end'][:16]}"
            formatted.append(f"**Summary {s['id']}** ({s['message_count']} messages, {time_span})\n{s['summary_text']}\n")
        
        return [TextContent(type="text", text="\n---\n".join(formatted))]

    elif name == "search_summaries":
        query = arguments.get("query", "")
        limit = arguments.get("limit", 10)
        results = await message_summaries.search(query, limit)
        return [TextContent(type="text", text=format_results(results))]

    elif name == "summary_stats":
        unsummarized_count = message_summaries.count_unsummarized_messages()
        recent_summaries = message_summaries.get_recent_summaries(3)
        
        stats = {
            "unsummarized_messages": unsummarized_count,
            "recent_summaries": len(recent_summaries),
            "last_summary_date": recent_summaries[0]['created_at'] if recent_summaries else None,
            "needs_summarization": unsummarized_count >= SUMMARIZATION_THRESHOLD
        }
        
        return [TextContent(type="text", text=json.dumps(stats, indent=2))]

    elif name == "store_summary":
        summary_text = arguments.get("summary_text", "")
        start_id = arguments.get("start_id")
        end_id = arguments.get("end_id")
        channels = arguments.get("channels", [])
        summary_type = arguments.get("summary_type", "work")

        if not summary_text or start_id is None or end_id is None:
            return [TextContent(type="text", text="Error: summary_text, start_id, and end_id are required")]

        success = await message_summaries.create_and_store_summary(
            summary_text, start_id, end_id, channels, summary_type
        )

        if success:
            return [TextContent(type="text", text=f"Summary stored successfully for messages {start_id}-{end_id}")]
        else:
            return [TextContent(type="text", text="Error: Failed to store summary")]

    elif name == "graphiti_ingestion_stats":
        uningested_count = message_summaries.count_uningested_to_graphiti()

        stats = {
            "uningested_messages": uningested_count,
            "needs_ingestion": uningested_count >= 20,
            "recommendation": "Run ingest_batch_to_graphiti" if uningested_count >= 20 else "No action needed"
        }

        return [TextContent(type="text", text=json.dumps(stats, indent=2))]

    elif name == "ingest_batch_to_graphiti":
        batch_size = arguments.get("batch_size", 20)

        # Get batch of uningested messages
        messages = message_summaries.get_uningested_for_graphiti(limit=batch_size)

        if not messages:
            return [TextContent(type="text", text="No messages to ingest. All caught up!")]

        # Get the Layer 3 instance
        layer = layers[LayerType.RICH_TEXTURE]

        # Ingest each message to Graphiti
        ingested_count = 0
        failed_count = 0
        channels_in_batch = set()

        for msg in messages:
            # Prepare metadata for Graphiti
            metadata = {
                "channel": msg['channel'],
                "role": "assistant" if msg['is_lyra'] else "user",
                "speaker": "Lyra" if msg['is_lyra'] else msg['author_name'],
                "timestamp": msg['created_at']
            }

            # Store in Graphiti
            success = await layer.store(msg['content'], metadata)

            if success:
                ingested_count += 1
                channels_in_batch.add(msg['channel'])
            else:
                failed_count += 1

        # Mark batch as ingested if any succeeded
        if ingested_count > 0:
            start_id = messages[0]['id']
            end_id = messages[-1]['id']
            batch_id = message_summaries.mark_batch_ingested_to_graphiti(
                start_id, end_id, list(channels_in_batch)
            )

            result = {
                "batch_id": batch_id,
                "messages_ingested": ingested_count,
                "messages_failed": failed_count,
                "message_range": f"{start_id}-{end_id}",
                "channels": list(channels_in_batch)
            }
        else:
            result = {
                "error": "All messages failed to ingest",
                "messages_failed": failed_count
            }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # === Inventory Layer (Layer 5) ===

    elif name == "inventory_list":
        category = arguments.get("category", "")
        subcategory = arguments.get("subcategory")
        limit = arguments.get("limit", 50)

        if not category:
            return [TextContent(type="text", text="Error: category required")]

        items = await inventory.list_category(category, subcategory, limit)

        if not items:
            return [TextContent(type="text", text=f"No items found in category '{category}'")]

        # Format as simple list
        formatted = [f"**{category.title()}** ({len(items)} items):\n"]
        for item in items:
            desc = f" - {item.get('description', '')}" if item.get('description') else ""
            formatted.append(f"- {item['name']}{desc}")

        return [TextContent(type="text", text="\n".join(formatted))]

    elif name == "inventory_add":
        name_arg = arguments.get("name", "")
        category = arguments.get("category", "")
        subcategory = arguments.get("subcategory")
        description = arguments.get("description")
        attributes = arguments.get("attributes")

        if not name_arg or not category:
            return [TextContent(type="text", text="Error: name and category required")]

        success = await inventory.add_item(
            name=name_arg,
            category=category,
            subcategory=subcategory,
            description=description,
            attributes=attributes
        )

        if success:
            return [TextContent(type="text", text=f"Added '{name_arg}' to {category}")]
        return [TextContent(type="text", text=f"Failed to add '{name_arg}' to inventory")]

    elif name == "inventory_get":
        name_arg = arguments.get("name", "")
        category = arguments.get("category", "")

        if not name_arg or not category:
            return [TextContent(type="text", text="Error: name and category required")]

        item = await inventory.get_item(name_arg, category)

        if not item:
            return [TextContent(type="text", text=f"Item '{name_arg}' not found in {category}")]

        return [TextContent(type="text", text=json.dumps(item, indent=2, default=str))]

    elif name == "inventory_delete":
        name_arg = arguments.get("name", "")
        category = arguments.get("category", "")

        if not name_arg or not category:
            return [TextContent(type="text", text="Error: name and category required")]

        deleted = await inventory.delete_item(name_arg, category)

        if deleted:
            return [TextContent(type="text", text=f"Deleted '{name_arg}' from {category}")]
        else:
            return [TextContent(type="text", text=f"Item '{name_arg}' not found in {category}")]

    elif name == "inventory_categories":
        categories = await inventory.get_categories()

        if not categories:
            return [TextContent(type="text", text="No inventory categories yet. Add items to get started.")]

        formatted = ["**Inventory Categories:**\n"]
        for cat in categories:
            formatted.append(f"- {cat['category']}: {cat['count']} items")

        return [TextContent(type="text", text="\n".join(formatted))]

    elif name == "enter_space":
        space_name = arguments.get("space_name", "")

        if not space_name:
            return [TextContent(type="text", text="Error: space_name required")]

        description = await inventory.enter_space(space_name)

        if not description:
            return [TextContent(type="text", text=f"Space '{space_name}' not found. Use list_spaces to see available spaces.")]

        return [TextContent(type="text", text=f"**Entering: {space_name}**\n\n{description}")]

    elif name == "list_spaces":
        spaces = await inventory.list_spaces()

        if not spaces:
            return [TextContent(type="text", text="No spaces registered yet. Add spaces using inventory_add with category='spaces'.")]

        formatted = ["**Known Spaces:**\n"]
        for space in spaces:
            quality = f" ({space.get('emotional_quality', '')})" if space.get('emotional_quality') else ""
            formatted.append(f"- {space['name']}{quality}")

        return [TextContent(type="text", text="\n".join(formatted))]

    # === Tech RAG (Layer 6) ===

    elif name == "tech_search":
        if tech_rag is None:
            return [TextContent(type="text", text="Tech RAG not available (requires ChromaDB)")]

        query = arguments.get("query", "")
        limit = arguments.get("limit", 5)
        category = arguments.get("category")

        if not query:
            return [TextContent(type="text", text="Error: query required")]

        results = await tech_rag.search(query, limit, category)

        if not results:
            return [TextContent(type="text", text="No results found in Tech RAG.")]

        # Format results
        formatted = []
        for r in results:
            formatted.append(
                f"**{r.source}** (score: {r.relevance_score:.2f})\n"
                f"{r.content}\n"
            )
        return [TextContent(type="text", text="\n---\n".join(formatted))]

    elif name == "tech_ingest":
        if tech_rag is None:
            return [TextContent(type="text", text="Tech RAG not available (requires ChromaDB)")]

        filepath = arguments.get("filepath", "")
        category = arguments.get("category")

        if not filepath:
            return [TextContent(type="text", text="Error: filepath required")]

        result = await tech_rag.ingest(filepath, category)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "tech_list":
        if tech_rag is None:
            return [TextContent(type="text", text="Tech RAG not available (requires ChromaDB)")]

        result = await tech_rag.list_docs()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "tech_delete":
        if tech_rag is None:
            return [TextContent(type="text", text="Tech RAG not available (requires ChromaDB)")]

        doc_id = arguments.get("doc_id", "")

        if not doc_id:
            return [TextContent(type="text", text="Error: doc_id required")]

        result = await tech_rag.delete_doc(doc_id)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "email_sync_status":
        # Import and create email bridge
        sys.path.insert(0, '/mnt/c/Users/Jeff/Claude_Projects/Awareness/tools')
        from email_pps_bridge import EmailPPSBridge
        
        awareness_dir = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
        email_db = awareness_dir / "data" / "email_archive.db"
        
        if not email_db.exists():
            return [TextContent(type="text", text=f"Email archive not found at {email_db}. Run email_processor.py first.")]
        
        bridge = EmailPPSBridge(email_db, db_path)
        status = await bridge.get_sync_status()
        return [TextContent(type="text", text=json.dumps(status, indent=2))]

    elif name == "email_sync_to_pps":
        days_back = arguments.get("days_back", 7)
        dry_run = arguments.get("dry_run", False)
        
        # Import and create email bridge  
        sys.path.insert(0, '/mnt/c/Users/Jeff/Claude_Projects/Awareness/tools')
        from email_pps_bridge import EmailPPSBridge
        
        awareness_dir = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
        email_db = awareness_dir / "data" / "email_archive.db"
        
        if not email_db.exists():
            return [TextContent(type="text", text=f"Email archive not found at {email_db}. Run email_processor.py first.")]
        
        bridge = EmailPPSBridge(email_db, db_path)
        stats = await bridge.sync_emails_to_pps(days_back=days_back, dry_run=dry_run)
        
        result_text = f"Email sync {'(dry run) ' if dry_run else ''}complete:\n"
        result_text += f"  Found: {stats['emails_found']} emails from last {days_back} days\n"
        result_text += f"  Already synced: {stats['already_synced']}\n"
        result_text += f"  Newly synced: {stats['newly_synced']}\n"
        result_text += f"  Errors: {stats['errors']}\n"
        
        if dry_run and stats['newly_synced'] > 0:
            result_text += f"\nTo actually sync these {stats['newly_synced']} emails, call again with dry_run=false"

        return [TextContent(type="text", text=result_text)]

    elif name == "get_conversation_context":
        import math
        turns = arguments.get("turns", 0)

        if turns <= 0:
            return [TextContent(type="text", text="Error: turns must be greater than 0")]

        unsummarized_count = message_summaries.count_unsummarized_messages()

        if unsummarized_count >= turns:
            # Simple case: just return N most recent raw turns
            raw_turns = message_summaries.get_unsummarized_messages(limit=turns)

            result = {
                "unsummarized_count": unsummarized_count,
                "summaries_count": 0,
                "raw_turns_count": len(raw_turns),
                "turns_covered_approx": len(raw_turns),
                "summaries": [],
                "raw_turns": raw_turns
            }
        else:
            # Complex case: blend summaries + all raw turns
            remaining = turns - unsummarized_count
            summaries_needed = math.ceil(remaining / 50)  # ~50 turns per summary

            summaries = message_summaries.get_recent_summaries(limit=summaries_needed)
            raw_turns = message_summaries.get_unsummarized_messages(limit=unsummarized_count)

            result = {
                "unsummarized_count": unsummarized_count,
                "summaries_count": len(summaries),
                "raw_turns_count": len(raw_turns),
                "turns_covered_approx": unsummarized_count + (len(summaries) * 50),
                "summaries": summaries,
                "raw_turns": raw_turns
            }

        # Format the output
        output = f"**Conversation Context** ({result['turns_covered_approx']} turns covered)\n\n"

        if result['summaries']:
            output += f"**Summaries** ({result['summaries_count']} summaries, ~{result['summaries_count'] * 50} turns):\n\n"
            for s in result['summaries']:
                output += f"---\n[{s['time_span_start']} to {s['time_span_end']}] ({s['message_count']} turns)\n{s['summary_text']}\n\n"

        if result['raw_turns']:
            output += f"**Recent Turns** ({result['raw_turns_count']} unsummarized):\n\n"
            for turn in result['raw_turns']:
                output += f"[{turn['created_at']}] {turn['author_name']}: {turn['content']}\n"

        return [TextContent(type="text", text=output)]

    elif name == "get_turns_since":
        timestamp = arguments.get("timestamp", "")
        include_summaries = arguments.get("include_summaries", True)
        limit = arguments.get("limit", 1000)

        if not timestamp:
            return [TextContent(type="text", text="Error: timestamp is required")]

        try:
            messages = message_summaries.get_messages_since(timestamp, limit=limit)

            # Get summaries if requested
            summaries = []
            if include_summaries:
                # Query for summaries that overlap this time range
                try:
                    target_time = datetime.fromisoformat(timestamp)

                    with message_summaries.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            SELECT id, summary_text, start_message_id, end_message_id,
                                   message_count, channels, time_span_start, time_span_end,
                                   summary_type, created_at
                            FROM message_summaries
                            WHERE time_span_end >= ?
                            ORDER BY time_span_start ASC
                        ''', (target_time.isoformat(),))

                        for row in cursor.fetchall():
                            summaries.append({
                                'id': row['id'],
                                'summary_text': row['summary_text'],
                                'start_message_id': row['start_message_id'],
                                'end_message_id': row['end_message_id'],
                                'message_count': row['message_count'],
                                'channels': json.loads(row['channels']),
                                'time_span_start': row['time_span_start'],
                                'time_span_end': row['time_span_end'],
                                'summary_type': row['summary_type'],
                                'created_at': row['created_at']
                            })
                except Exception as e:
                    print(f"Warning: Could not fetch summaries: {e}", file=sys.stderr)

            # Format the output
            output = f"**Turns Since {timestamp}**\n\n"
            output += f"Found: {len(messages)} messages"
            if len(messages) == limit:
                output += f" (limited to {limit}, more may exist)"
            output += "\n\n"

            if summaries:
                output += f"**Summaries** ({len(summaries)} overlapping):\n\n"
                for s in summaries:
                    output += f"---\n[{s['time_span_start']} to {s['time_span_end']}] ({s['message_count']} turns)\n{s['summary_text']}\n\n"

            if messages:
                output += f"**Messages**:\n\n"
                for msg in messages:
                    output += f"[{msg['created_at']}] {msg['author_name']}: {msg['content']}\n"

            return [TextContent(type="text", text=output)]

        except ValueError as e:
            return [TextContent(type="text", text=f"Error parsing timestamp: {e}\nExpected ISO 8601 format (e.g., '2026-01-26T07:30:00')")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "get_turns_around":
        timestamp = arguments.get("timestamp", "")
        count = arguments.get("count", 40)
        before_ratio = arguments.get("before_ratio", 0.5)

        if not timestamp:
            return [TextContent(type="text", text="Error: timestamp is required")]

        # Clamp before_ratio to [0, 1]
        before_ratio = max(0.0, min(1.0, before_ratio))

        try:
            before_count = int(count * before_ratio)
            after_count = count - before_count

            result = message_summaries.get_messages_around(timestamp, before_count, after_count)

            # Format the output
            output = f"**Turns Around {timestamp}**\n\n"
            output += f"Before: {len(result['before'])} | After: {len(result['after'])} | Total: {len(result['all'])}\n\n"

            if result['all']:
                for msg in result['all']:
                    output += f"[{msg['created_at']}] {msg['author_name']}: {msg['content']}\n"
            else:
                output += "No messages found around this timestamp.\n"

            return [TextContent(type="text", text=output)]

        except ValueError as e:
            return [TextContent(type="text", text=f"Error parsing timestamp: {e}\nExpected ISO 8601 format (e.g., '2026-01-26T12:00:00')")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
