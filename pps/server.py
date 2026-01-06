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
from pathlib import Path

# Try to use graphiti_core for enhanced Layer 3
try:
    from layers.rich_texture_v2 import RichTextureLayerV2
    USE_GRAPHITI_CORE = True
except ImportError:
    from layers.rich_texture import RichTextureLayer
    USE_GRAPHITI_CORE = False

# Configuration from environment
CLAUDE_HOME = Path(os.getenv("CLAUDE_HOME", str(Path.home() / ".claude")))
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8200"))
SUMMARIZATION_THRESHOLD = int(os.getenv("PPS_SUMMARIZATION_THRESHOLD", "50"))

# Derived paths
word_photos_path = CLAUDE_HOME / "memories" / "word_photos"
db_path = CLAUDE_HOME / "data" / "lyra_conversations.db"
crystals_path = CLAUDE_HOME / "crystals" / "current"
archive_path = CLAUDE_HOME / "crystals" / "archive"

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
                            "or 'startup' for initial identity reconstruction."
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
            name="get_turns_since_crystal",
            description=(
                "Get conversation turns from SQLite that occurred after the last crystal. "
                "Use for manual exploration of raw history. "
                "Note: For startup, use ambient_recall which combines summaries + recent turns. "
                "Always returns at least min_turns to ensure grounding even if crystal just happened."
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
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""

    if name == "ambient_recall":
        context = arguments.get("context", "")
        limit = arguments.get("limit_per_layer", 5)

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
        memory_health = f"**Memory Health**: {unsummarized_count} unsummarized messages"
        if unsummarized_count > 200:
            memory_health += " ⚠️ (HIGH - summarize soon!)"
        elif unsummarized_count > 100:
            memory_health += " (summarization recommended)"
        elif unsummarized_count > 50:
            memory_health += " (healthy, summarization available)"
        else:
            memory_health += " (healthy)"
        memory_health += "\n\n"

        # Search all layers in parallel (including message summaries)
        all_results: list[SearchResult] = []
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

        # For startup context, use summaries for compressed history + ALL unsummarized raw turns
        # Architecture: summaries = compressed past, unsummarized turns = full fidelity recent
        # Pattern fidelity is paramount - we pay the token cost for complete context
        recent_context_section = ""
        if context.lower() == "startup":
            try:
                # unsummarized_count already computed at top (Issue #73)
                # Get recent summaries (compressed history - ~200 tokens each)
                recent_summaries = message_summaries.get_recent_summaries(limit=5)

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

                unsummarized_text = ""
                if unsummarized_rows:
                    # Show how many we're displaying vs total unsummarized
                    showing = len(unsummarized_rows)
                    if unsummarized_count > showing:
                        unsummarized_text = f"\n---\n[unsummarized_turns] (showing {showing} of {unsummarized_count} - use get_turns_since_crystal with offset={showing} for older, or run summarizer)\n"
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
                        unsummarized_text += f"[{timestamp}] [{channel}] {author}: {content}\n"

                # Memory health is now shown at the top of every ambient_recall (Issue #73)
                # No need for duplicate status at bottom
                recent_context_section = summaries_text + unsummarized_text

            except Exception as e:
                recent_context_section = f"\n---\n[recent_context] Error fetching: {e}"

        if not all_results and not recent_context_section:
            return [TextContent(
                type="text",
                text=(
                    clock_info +
                    memory_health +
                    "No memories surfaced from ambient recall.\n\n"
                    "Layer status:\n"
                    "- Raw Capture: FTS5 full-text search\n"
                    "- Core Anchors: " + ("ChromaDB" if USE_CHROMA else "file-based") + "\n"
                    "- Rich Texture: Graphiti (check if running with pps_health)\n"
                    "- Crystallization: active"
                )
            )]

        return [TextContent(type="text", text=clock_info + memory_health + format_results(all_results) + recent_context_section)]

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

    elif name == "get_turns_since_crystal":
        limit = arguments.get("limit", 50)
        offset = arguments.get("offset", 0)
        min_turns = arguments.get("min_turns", 10)
        channel_filter = arguments.get("channel")

        # Get the timestamp of the last crystal
        crystal_layer = layers[LayerType.CRYSTALLIZATION]
        last_crystal_time = await crystal_layer.get_latest_timestamp()

        # Query SQLite for turns using WAL-enabled connection
        raw_layer = layers[LayerType.RAW_CAPTURE]
        try:
            rows_after = []
            rows_before = []

            with raw_layer.get_connection() as conn:
                cursor = conn.cursor()

                if last_crystal_time:
                    # First, get the MOST RECENT turns after the last crystal
                    # (order DESC to get newest, then reverse for chronological display)
                    # offset allows pagination: offset=0 gets newest, offset=50 gets next batch
                    query = """
                        SELECT author_name, content, created_at, channel
                        FROM messages
                        WHERE created_at > ?
                    """
                    params = [last_crystal_time.isoformat()]
                    if channel_filter:
                        query += " AND channel LIKE ?"
                        params.append(f"%{channel_filter}%")
                    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                    params.extend([limit, offset])
                    cursor.execute(query, params)
                    rows_after = list(reversed(cursor.fetchall()))  # Reverse for chronological order

                    # If we don't have enough turns, also get some from BEFORE the crystal
                    if len(rows_after) < min_turns:
                        needed = min_turns - len(rows_after)
                        query = """
                            SELECT author_name, content, created_at, channel
                            FROM messages
                            WHERE created_at <= ?
                        """
                        params = [last_crystal_time.isoformat()]
                        if channel_filter:
                            query += " AND channel LIKE ?"
                            params.append(f"%{channel_filter}%")
                        query += " ORDER BY created_at DESC LIMIT ?"
                        params.append(needed)
                        cursor.execute(query, params)
                        rows_before = list(reversed(cursor.fetchall()))  # Reverse to get chronological order
                else:
                    # No crystal yet - get most recent turns
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
            if last_crystal_time:
                if rows_before:
                    header_parts.append(f"({len(rows_before)} before + {len(rows_after)} after crystal on {last_crystal_time.strftime('%Y-%m-%d')})")
                else:
                    header_parts.append(f"since crystal ({last_crystal_time.strftime('%Y-%m-%d')})")
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
