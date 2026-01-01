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
from layers.rich_texture import RichTextureLayer
from layers.crystallization import CrystallizationLayer
from pathlib import Path

# Configuration from environment
CLAUDE_HOME = Path(os.getenv("CLAUDE_HOME", str(Path.home() / ".claude")))
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8200"))

# Derived paths
word_photos_path = CLAUDE_HOME / "memories" / "word_photos"
db_path = CLAUDE_HOME / "data" / "lyra_conversations.db"
summaries_path = CLAUDE_HOME / "summaries" / "current"
archive_path = CLAUDE_HOME / "summaries" / "archive"

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

# Initialize all layers with configurable paths
layers = {
    LayerType.RAW_CAPTURE: RawCaptureLayer(db_path=db_path),
    LayerType.RICH_TEXTURE: RichTextureLayer(),
    LayerType.CRYSTALLIZATION: CrystallizationLayer(
        summaries_path=summaries_path,
        archive_path=archive_path
    ),
}

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
            name="texture_query",
            description=(
                "Query the knowledge graph (Layer 3: Rich Texture). "
                "Use for exploring entities, relationships, and facts. "
                "Note: Currently stubbed, returns empty until Graphiti is configured."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to query in the knowledge graph"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_summaries",
            description=(
                "Get recent crystallized summaries (Layer 4: Crystallization). "
                "Use for temporal context and continuity chain. "
                "Returns the most recent N summaries in chronological order."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Number of recent summaries to retrieve (default: 4)",
                        "default": 4
                    }
                }
            }
        ),
        Tool(
            name="crystallize",
            description=(
                "Save a new crystallized summary (Layer 4: Crystallization). "
                "Use for conscious summary creation - when you decide a summary moment has occurred. "
                "Automatically numbers the summary and manages the rolling window of 4."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The crystallized summary content in markdown format"
                    }
                },
                "required": ["content"]
            }
        ),
        Tool(
            name="get_turns_since_summary",
            description=(
                "Get conversation turns from SQLite that occurred after the last summary. "
                "Use on startup to fill the gap between summaries and now. "
                "Returns raw conversation history for immediate context. "
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
                    "min_turns": {
                        "type": "integer",
                        "description": "Minimum turns to always return, even if pulling from before summary (default: 10)",
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
            name="summary_list",
            description=(
                "List all crystallized summaries with metadata. "
                "Shows current summaries (rolling window of 4) and archived ones. "
                "Includes filename, number, size, modified date, and preview."
            ),
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="summary_delete",
            description=(
                "Delete the most recent summary ONLY. "
                "Summaries form a chain - only the latest can be deleted to preserve integrity. "
                "Use when a summary was created with errors and needs to be re-crystallized."
            ),
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

        # Search all layers in parallel
        all_results: list[SearchResult] = []
        tasks = [
            layer.search(context, limit)
            for layer in layers.values()
        ]
        layer_results = await asyncio.gather(*tasks, return_exceptions=True)

        for results in layer_results:
            if isinstance(results, list):
                all_results.extend(results)
            # Silently skip exceptions - graceful degradation

        # Sort by relevance score
        all_results.sort(key=lambda r: r.relevance_score, reverse=True)

        if not all_results:
            return [TextContent(
                type="text",
                text=(
                    clock_info +
                    "No memories surfaced from ambient recall.\n\n"
                    "Layer status:\n"
                    "- Raw Capture: FTS5 full-text search\n"
                    "- Core Anchors: " + ("ChromaDB" if USE_CHROMA else "file-based") + "\n"
                    "- Rich Texture: stub (Graphiti not configured)\n"
                    "- Crystallization: active"
                )
            )]

        return [TextContent(type="text", text=clock_info + format_results(all_results))]

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

    elif name == "texture_query":
        query = arguments.get("query", "")
        results = await layers[LayerType.RICH_TEXTURE].search(query)
        return [TextContent(type="text", text=format_results(results))]

    elif name == "get_summaries":
        count = arguments.get("count", 4)
        results = await layers[LayerType.CRYSTALLIZATION].search("recent", count)
        if not results:
            return [TextContent(type="text", text="No summaries found. Create your first with crystallize.")]
        # Format summaries nicely for reading
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
            # Get the number of the just-saved summary
            layer = layers[LayerType.CRYSTALLIZATION]
            latest = layer._get_latest_summary()
            filename = latest.name if latest else "unknown"
            return [TextContent(type="text", text=f"Summary crystallized: {filename}")]
        return [TextContent(type="text", text="Error: Failed to save summary")]

    elif name == "get_turns_since_summary":
        limit = arguments.get("limit", 50)
        min_turns = arguments.get("min_turns", 10)
        channel_filter = arguments.get("channel")

        # Get the timestamp of the last summary
        crystal_layer = layers[LayerType.CRYSTALLIZATION]
        last_summary_time = await crystal_layer.get_latest_timestamp()

        # Query SQLite for turns using WAL-enabled connection
        raw_layer = layers[LayerType.RAW_CAPTURE]
        try:
            conn = raw_layer._connect_with_wal()
            cursor = conn.cursor()

            rows_after = []
            rows_before = []

            if last_summary_time:
                # First, get turns AFTER the last summary
                query = """
                    SELECT author_name, content, created_at, channel
                    FROM messages
                    WHERE created_at > ?
                """
                params = [last_summary_time.isoformat()]
                if channel_filter:
                    query += " AND channel LIKE ?"
                    params.append(f"%{channel_filter}%")
                query += " ORDER BY created_at ASC LIMIT ?"
                params.append(limit)
                cursor.execute(query, params)
                rows_after = cursor.fetchall()

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
                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(max(limit, min_turns))
                cursor.execute(query, params)
                rows_after = list(reversed(cursor.fetchall()))  # Reverse to get chronological order

            conn.close()

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
                turns.append(f"[{timestamp}] [{channel}] {author}: {content[:500]}")

            # Build header with context
            header_parts = [f"**{len(turns)} turns"]
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

    elif name == "summary_list":
        layer = layers[LayerType.CRYSTALLIZATION]
        result = await layer.list_summaries()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "summary_delete":
        layer = layers[LayerType.CRYSTALLIZATION]
        result = await layer.delete_latest()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

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
