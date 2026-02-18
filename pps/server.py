#!/usr/bin/env python3
"""
Pattern Persistence System - MCP Server (Thin HTTP Proxy)

Implements the MCP stdio protocol and forwards all tool calls to the HTTP
server (server_http.py) running on localhost. This eliminates the dual
maintenance problem: all logic lives in server_http.py, this is just a
protocol adapter.

# ROLLBACK: If this proxy causes issues after restart:
# 1. git checkout HEAD~1 -- pps/server.py
# 2. Restart Claude Code
# The HTTP server (server_http.py) is unchanged and all other clients are unaffected.

Usage:
    python server.py  # Runs as stdio MCP server
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Entity authentication token schema (reused in all tool definitions)
TOKEN_PARAM_SCHEMA = {
    "type": "string",
    "description": (
        "Entity authentication token. Read from $ENTITY_PATH/.entity_token at startup. "
        "Required for all entity-specific tools when PPS_STRICT_AUTH=true. "
        "Re-read file if lost after compaction."
    )
}

# Port mapping: entity name -> HTTP server port
ENTITY_PORTS = {
    "lyra": 8201,
    "caia": 8211,
}

# Resolve port from env or entity name
ENTITY_PATH = Path(os.environ.get("ENTITY_PATH", str(Path.home() / ".claude")))
entity_name = ENTITY_PATH.name
PPS_HTTP_PORT = int(os.environ.get("PPS_HTTP_PORT", ENTITY_PORTS.get(entity_name, 8201)))
PPS_HTTP_BASE = f"http://localhost:{PPS_HTTP_PORT}"

# Read entity token (injected into calls that don't include it)
def _read_entity_token() -> str:
    token_path = ENTITY_PATH / ".entity_token"
    try:
        return token_path.read_text().strip()
    except Exception:
        return ""

ENTITY_TOKEN = _read_entity_token()

# Create MCP server
server = Server("pattern-persistence-system")


def _forward(tool_name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Forward a tool call to the HTTP server and return TextContent."""
    # Inject entity token if not already present (tools that need it)
    if "token" in _get_tool_schema(tool_name).get("properties", {}) and "token" not in arguments:
        arguments = dict(arguments)
        arguments["token"] = ENTITY_TOKEN

    # tech_delete uses DELETE with path param (not POST with body)
    if tool_name == "tech_delete":
        doc_id = arguments.get("doc_id", "")
        if not doc_id:
            return [TextContent(type="text", text="Error: doc_id required")]
        url = f"{PPS_HTTP_BASE}/tools/tech_delete/{doc_id}"
        try:
            response = requests.delete(url, timeout=30)
        except requests.exceptions.ConnectionError:
            return [TextContent(type="text", text=f"Error: PPS HTTP server not reachable at {PPS_HTTP_BASE}")]
        except requests.exceptions.Timeout:
            return [TextContent(type="text", text=f"Error: PPS HTTP server timed out for 'tech_delete'")]
        if not response.ok:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            return [TextContent(type="text", text=f"Error ({response.status_code}): {detail}")]
        try:
            data = response.json()
        except Exception:
            return [TextContent(type="text", text=response.text)]
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    url = f"{PPS_HTTP_BASE}/tools/{tool_name}"

    try:
        response = requests.post(url, json=arguments, timeout=60)
    except requests.exceptions.ConnectionError:
        return [TextContent(
            type="text",
            text=f"Error: PPS HTTP server not reachable at {PPS_HTTP_BASE}. Is it running?"
        )]
    except requests.exceptions.Timeout:
        return [TextContent(
            type="text",
            text=f"Error: PPS HTTP server timed out for tool '{tool_name}'"
        )]

    if response.status_code == 403:
        data = response.json()
        return [TextContent(type="text", text=data.get("error", "Authentication failed"))]

    if response.status_code == 404:
        return [TextContent(type="text", text=f"Tool '{tool_name}' not found on HTTP server")]

    if not response.ok:
        try:
            data = response.json()
            detail = data.get("detail", data.get("error", response.text))
        except Exception:
            detail = response.text
        return [TextContent(type="text", text=f"Error from HTTP server ({response.status_code}): {detail}")]

    try:
        data = response.json()
    except Exception:
        # Non-JSON response, return raw text
        return [TextContent(type="text", text=response.text)]

    # Convert JSON response to text for MCP
    if isinstance(data, str):
        text = data
    elif isinstance(data, dict):
        text = json.dumps(data, indent=2)
    else:
        text = str(data)

    return [TextContent(type="text", text=text)]


def _forward_get(tool_name: str) -> list[TextContent]:
    """Forward a GET request (for tools with no body)."""
    url = f"{PPS_HTTP_BASE}/tools/{tool_name}"
    try:
        response = requests.get(url, timeout=30)
    except requests.exceptions.ConnectionError:
        return [TextContent(type="text", text=f"Error: PPS HTTP server not reachable at {PPS_HTTP_BASE}")]
    except requests.exceptions.Timeout:
        return [TextContent(type="text", text=f"Error: PPS HTTP server timed out for '{tool_name}'")]

    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        return [TextContent(type="text", text=f"Error ({response.status_code}): {detail}")]

    try:
        data = response.json()
    except Exception:
        return [TextContent(type="text", text=response.text)]

    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# Cache of tool schemas for token injection logic
_TOOL_SCHEMAS: dict[str, dict] = {}

def _get_tool_schema(tool_name: str) -> dict:
    return _TOOL_SCHEMAS.get(tool_name, {})


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available PPS tools."""
    tools = [
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "oldest_first": {
                        "type": "boolean",
                        "description": "If true, return turns in chronological order (oldest first) instead of newest first. Useful for reading catch-up context forward. (default: false)",
                        "default": False
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
            name="pps_regenerate_token",
            description=(
                "Regenerate this entity's authentication token. MASTER TOKEN REQUIRED. "
                "Old token is immediately invalidated. Returns the new token. "
                "Use only for recovery when entity token is lost or compromised."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "master_token": {
                        "type": "string",
                        "description": "The master token (from entities/.master_token). Required."
                    }
                },
                "required": ["master_token"]
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                "properties": {
                    "token": TOKEN_PARAM_SCHEMA
                }
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
                "properties": {
                    "token": TOKEN_PARAM_SCHEMA
                }
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
                "properties": {
                    "token": TOKEN_PARAM_SCHEMA
                }
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
                "properties": {
                    "token": TOKEN_PARAM_SCHEMA
                }
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                "properties": {
                    "token": TOKEN_PARAM_SCHEMA
                }
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                "properties": {
                    "token": TOKEN_PARAM_SCHEMA
                }
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
                },
                "required": ["name", "category"]
            }
        ),
        Tool(
            name="inventory_categories",
            description="List all inventory categories with item counts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "token": TOKEN_PARAM_SCHEMA
                }
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
                },
                "required": ["space_name"]
            }
        ),
        Tool(
            name="list_spaces",
            description="List all known spaces/rooms/locations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "token": TOKEN_PARAM_SCHEMA
                }
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
                "properties": {
                    "token": TOKEN_PARAM_SCHEMA
                }
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
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
                "Useful for reconstructinging context around a specific event or decision."
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
                    },
                    "token": TOKEN_PARAM_SCHEMA
                },
                "required": ["timestamp"]
            }
        ),
    ]

    # Populate schema cache for token injection
    for tool in tools:
        _TOOL_SCHEMAS[tool.name] = tool.inputSchema

    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Forward all tool calls to the HTTP server."""
    # pps_regenerate_token uses a different endpoint path pattern
    return _forward(name, arguments)


async def main():
    """Run the MCP server."""
    print(f"[PPS Proxy] Forwarding to {PPS_HTTP_BASE}", file=sys.stderr)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
