"""
PPS Observatory - Web Dashboard for Pattern Persistence System

A simple web interface for observing and managing the PPS infrastructure.
Designed to run in Docker alongside ChromaDB.
"""

import os
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Add asyncio for async operations
import asyncio
# Import RichTextureLayer for knowledge graph access
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from layers.rich_texture_v2 import RichTextureLayerV2 as RichTextureLayer
    print("[pps-web] Using RichTextureLayerV2 (direct mode)")
except ImportError:
    from layers.rich_texture import RichTextureLayer
    print("[pps-web] Using RichTextureLayer (HTTP mode)")

# Configuration from environment
CLAUDE_HOME = Path(os.getenv("CLAUDE_HOME", "/app/claude_home"))
ENTITY_PATH = Path(os.getenv("ENTITY_PATH", "/app/entity"))
CHROMA_HOST = os.getenv("CHROMA_HOST", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", 8000))
PPS_SERVER_HOST = os.getenv("PPS_SERVER_HOST", "pps-server")
PPS_SERVER_PORT = int(os.getenv("PPS_SERVER_PORT", 8000))

# Shared data paths (SQLite, journals)
DB_PATH = CLAUDE_HOME / "data" / "lyra_conversations.db"
JOURNALS_PATH = CLAUDE_HOME / "journals"

# Entity-specific paths (word-photos, crystals)
WORD_PHOTOS_PATH = ENTITY_PATH / "memories" / "word_photos"
CRYSTALS_PATH = ENTITY_PATH / "crystals" / "current"
CRYSTALS_ARCHIVE_PATH = ENTITY_PATH / "crystals" / "archive"

# Initialize FastAPI
app = FastAPI(
    title="PPS Observatory",
    description="Web dashboard for Pattern Persistence System",
    version="0.1.0"
)

# Templates and static files
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def get_db_connection() -> Optional[sqlite3.Connection]:
    """Get a database connection with WAL mode."""
    try:
        if not DB_PATH.exists():
            return None
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
    except Exception:
        return None


def get_server_health() -> dict:
    """Check health of the PPS MCP server."""
    pps_url = f"http://{PPS_SERVER_HOST}:{PPS_SERVER_PORT}"

    result = {
        "status": "unknown",
        "detail": "",
        "url": pps_url,
        "last_check": datetime.now().strftime("%H:%M:%S")
    }

    try:
        resp = requests.get(f"{pps_url}/health", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "healthy":
                result["status"] = "ok"
                result["detail"] = "All layers healthy"
            else:
                result["status"] = "warning"
                result["detail"] = data.get("status", "Degraded")
        else:
            result["status"] = "error"
            result["detail"] = f"HTTP {resp.status_code}"
    except requests.exceptions.ConnectionError:
        result["status"] = "error"
        result["detail"] = "Connection refused"
    except requests.exceptions.Timeout:
        result["status"] = "error"
        result["detail"] = "Request timeout"
    except Exception as e:
        result["status"] = "error"
        result["detail"] = str(e)[:50]

    return result


def get_layer_health() -> dict:
    """Get health status of all four PPS layers."""
    health = {
        "layer1": {"name": "Raw Capture", "status": "unknown", "detail": ""},
        "layer2": {"name": "Core Anchors", "status": "unknown", "detail": ""},
        "layer3": {"name": "Rich Texture", "status": "unknown", "detail": ""},
        "layer4": {"name": "Crystallization", "status": "unknown", "detail": ""},
    }

    # Layer 1: SQLite
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM messages")
            count = cursor.fetchone()[0]
            health["layer1"]["status"] = "ok"
            health["layer1"]["detail"] = f"{count} messages"
            conn.close()
        except Exception as e:
            health["layer1"]["status"] = "error"
            health["layer1"]["detail"] = str(e)
    else:
        health["layer1"]["status"] = "error"
        health["layer1"]["detail"] = "Database not found"

    # Layer 2: ChromaDB
    try:
        import chromadb
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        client.heartbeat()
        collections = client.list_collections()
        doc_count = 0
        for coll in collections:
            doc_count += coll.count()
        health["layer2"]["status"] = "ok"
        health["layer2"]["detail"] = f"{doc_count} docs"
    except Exception as e:
        health["layer2"]["status"] = "error"
        health["layer2"]["detail"] = str(e)[:50]

    # Layer 3: Graphiti  
    try:
        import requests
        import json
        
        # Try direct HTTP check to Graphiti health endpoint
        graphiti_host = os.getenv("GRAPHITI_HOST", "localhost") 
        graphiti_port = int(os.getenv("GRAPHITI_PORT", "8203"))
        graphiti_url = f"http://{graphiti_host}:{graphiti_port}"
        
        # Check Graphiti health
        resp = requests.get(f"{graphiti_url}/healthcheck", timeout=5)
        if resp.status_code == 200:
            health["layer3"]["status"] = "ok"
            health["layer3"]["detail"] = "Operational"
            
            # Try to get entity count for more detail
            try:
                pps_server_url = "http://localhost:8201"
                search_resp = requests.post(
                    f"{pps_server_url}/tools/texture_search",
                    json={"query": "test", "limit": 1},
                    timeout=3
                )
                if search_resp.status_code == 200:
                    search_data = search_resp.json()
                    # Successfully connected to Graphiti via PPS
                    health["layer3"]["detail"] = "Active (via PPS)"
                else:
                    health["layer3"]["detail"] = "Graphiti online"
            except:
                # Graphiti health OK but can't query through PPS
                health["layer3"]["detail"] = "Graphiti online"
        else:
            health["layer3"]["status"] = "error"
            health["layer3"]["detail"] = f"HTTP {resp.status_code}"
            
    except requests.exceptions.ConnectionError:
        health["layer3"]["status"] = "error"
        health["layer3"]["detail"] = "Graphiti unreachable"
    except requests.exceptions.Timeout:
        health["layer3"]["status"] = "error"
        health["layer3"]["detail"] = "Graphiti timeout"
    except Exception as e:
        health["layer3"]["status"] = "error"
        health["layer3"]["detail"] = str(e)[:50]

    # Layer 4: Crystals
    try:
        if CRYSTALS_PATH.exists():
            crystals = list(CRYSTALS_PATH.glob("crystal_*.md"))
            health["layer4"]["status"] = "ok"
            health["layer4"]["detail"] = f"{len(crystals)} active"
        else:
            health["layer4"]["status"] = "warning"
            health["layer4"]["detail"] = "No crystals dir"
    except Exception as e:
        health["layer4"]["status"] = "error"
        health["layer4"]["detail"] = str(e)

    return health


def get_crystal_list() -> dict:
    """Get list of all crystals (current + archived) with metadata."""
    import re

    def extract_number(filename: str) -> int:
        """Extract crystal number from filename."""
        match = re.search(r'crystal_(\d+)', filename)
        return int(match.group(1)) if match else 0

    def get_crystal_info(path: Path) -> dict:
        """Get info about a single crystal file."""
        try:
            stat = path.stat()
            content = path.read_text()
            lines = [l.strip() for l in content.split('\n') if l.strip()]
            preview = lines[0][:80] if lines else ""
            return {
                "filename": path.name,
                "number": extract_number(path.name),
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "preview": preview
            }
        except Exception as e:
            return {"filename": path.name, "error": str(e)}

    current = []
    archived = []

    if CRYSTALS_PATH.exists():
        for path in sorted(CRYSTALS_PATH.glob("crystal_*.md"),
                          key=lambda p: extract_number(p.name)):
            current.append(get_crystal_info(path))

    if CRYSTALS_ARCHIVE_PATH.exists():
        for path in sorted(CRYSTALS_ARCHIVE_PATH.glob("crystal_*.md"),
                          key=lambda p: extract_number(p.name)):
            archived.append(get_crystal_info(path))

    return {
        "current": current,
        "archived": archived,
        "total": len(current) + len(archived)
    }


def get_crystal_content(filename: str) -> Optional[str]:
    """Get the full content of a specific crystal."""
    # Check current first, then archive
    for base_path in [CRYSTALS_PATH, CRYSTALS_ARCHIVE_PATH]:
        path = base_path / filename
        if path.exists() and path.is_file():
            try:
                return path.read_text()
            except Exception:
                return None
    return None


def get_recent_activity(limit: int = 10) -> list:
    """Get recent messages across all channels."""
    conn = get_db_connection()
    if not conn:
        return []

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT channel, author_name, content, created_at
            FROM messages
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))

        results = []
        for row in cursor.fetchall():
            results.append({
                "channel": row["channel"],
                "author": row["author_name"],
                "content": row["content"][:100] + "..." if len(row["content"]) > 100 else row["content"],
                "timestamp": row["created_at"]
            })
        conn.close()
        return results
    except Exception:
        return []


def get_messages(
    channel: Optional[str] = None,
    author: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 20
) -> dict:
    """Get paginated messages with optional filters."""
    conn = get_db_connection()
    if not conn:
        return {"messages": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}

    try:
        cursor = conn.cursor()

        # Build WHERE clause
        conditions = []
        params = []

        if channel:
            if channel in ("discord", "terminal", "reflection"):
                conditions.append("channel LIKE ?")
                params.append(f"{channel}%")
            else:
                conditions.append("channel = ?")
                params.append(channel)

        if author:
            conditions.append("author_name = ?")
            params.append(author)

        if search:
            # Use FTS if available, otherwise LIKE
            conditions.append("content LIKE ?")
            params.append(f"%{search}%")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Get total count
        cursor.execute(f"SELECT COUNT(*) FROM messages WHERE {where_clause}", params)
        total = cursor.fetchone()[0]

        # Get paginated results
        offset = (page - 1) * per_page
        cursor.execute(f"""
            SELECT channel, author_name, content, created_at
            FROM messages
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, params + [per_page, offset])

        messages = []
        for row in cursor.fetchall():
            messages.append({
                "channel": row["channel"],
                "author": row["author_name"],
                "content": row["content"],
                "timestamp": row["created_at"]
            })

        conn.close()

        pages = (total + per_page - 1) // per_page  # Ceiling division

        return {
            "messages": messages,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages
        }
    except Exception as e:
        return {"messages": [], "total": 0, "page": page, "per_page": per_page, "pages": 0, "error": str(e)}


def get_unique_channels() -> list:
    """Get list of unique channel types for filter dropdown."""
    conn = get_db_connection()
    if not conn:
        return []

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT
                CASE
                    WHEN channel LIKE 'discord:%' THEN 'discord'
                    WHEN channel LIKE 'terminal:%' THEN 'terminal'
                    WHEN channel LIKE 'reflection:%' THEN 'reflection'
                    ELSE channel
                END as channel_type
            FROM messages
            ORDER BY channel_type
        """)
        channels = [row[0] for row in cursor.fetchall()]
        conn.close()
        return channels
    except Exception:
        return []


def get_unique_authors() -> list:
    """Get list of unique authors for filter dropdown."""
    conn = get_db_connection()
    if not conn:
        return []

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT author_name
            FROM messages
            WHERE author_name IS NOT NULL
            ORDER BY author_name
        """)
        authors = [row[0] for row in cursor.fetchall()]
        conn.close()
        return authors
    except Exception:
        return []


def get_word_photo_sync_status() -> dict:
    """Check sync status between disk files and ChromaDB."""
    import chromadb

    result = {
        "disk_files": [],
        "chroma_count": 0,
        "synced": False,
        "error": None
    }

    # Get files on disk
    if WORD_PHOTOS_PATH.exists():
        result["disk_files"] = sorted([f.name for f in WORD_PHOTOS_PATH.glob("*.md")])
    result["disk_count"] = len(result["disk_files"])

    # Get ChromaDB count
    try:
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        collection = client.get_or_create_collection(
            name="word_photos",
            metadata={"hnsw:space": "cosine"}
        )
        result["chroma_count"] = collection.count()
        result["synced"] = result["disk_count"] == result["chroma_count"]
    except Exception as e:
        result["error"] = str(e)

    return result


def do_word_photo_resync() -> dict:
    """Trigger resync via PPS server."""
    pps_url = f"http://{PPS_SERVER_HOST}:{PPS_SERVER_PORT}"

    try:
        resp = requests.post(f"{pps_url}/tools/anchor_resync", timeout=30)
        if resp.status_code == 200:
            return {"success": True, "data": resp.json()}
        else:
            return {"success": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_channel_stats() -> dict:
    """Get message counts by channel."""
    conn = get_db_connection()
    if not conn:
        return {}

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                CASE
                    WHEN channel LIKE 'discord:%' THEN 'discord'
                    WHEN channel LIKE 'terminal:%' THEN 'terminal'
                    ELSE channel
                END as channel_type,
                COUNT(*) as count
            FROM messages
            GROUP BY channel_type
            ORDER BY count DESC
        """)

        stats = {}
        for row in cursor.fetchall():
            stats[row["channel_type"]] = row["count"]
        conn.close()
        return stats
    except Exception:
        return {}


def get_daemon_status() -> dict:
    """Get status of daemons (best effort from available info)."""
    from datetime import datetime, timedelta

    status = {
        "discord": {"status": "unknown", "detail": ""},
        "reflection": {"status": "unknown", "detail": ""},
        "terminal": {"status": "unknown", "detail": ""}
    }

    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # Check for recent Discord messages
            cursor.execute("""
                SELECT created_at FROM messages
                WHERE channel LIKE 'discord:%'
                ORDER BY created_at DESC LIMIT 1
            """)
            row = cursor.fetchone()
            if row:
                status["discord"]["status"] = "active"
                status["discord"]["detail"] = f"Last: {row['created_at']}"
            else:
                status["discord"]["status"] = "idle"
                status["discord"]["detail"] = "No messages"

            # Check terminal
            cursor.execute("""
                SELECT created_at FROM messages
                WHERE channel LIKE 'terminal:%'
                ORDER BY created_at DESC LIMIT 1
            """)
            row = cursor.fetchone()
            if row:
                status["terminal"]["status"] = "active"
                status["terminal"]["detail"] = f"Last: {row['created_at']}"
            else:
                status["terminal"]["status"] = "idle"
                status["terminal"]["detail"] = "No messages"

            # Check for recent reflection activity from daemon_traces
            one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
            cursor.execute("""
                SELECT MAX(timestamp) as last_activity
                FROM daemon_traces
                WHERE daemon_type = 'reflection' AND timestamp > ?
            """, (one_hour_ago,))
            row = cursor.fetchone()
            if row and row["last_activity"]:
                status["reflection"]["status"] = "active"
                status["reflection"]["detail"] = f"Last: {row['last_activity'][:19]}"
            else:
                # Check heartbeat journals as fallback
                heartbeat_path = JOURNALS_PATH / "heartbeat"
                if heartbeat_path.exists():
                    journals = sorted(heartbeat_path.glob("*.md"), reverse=True)
                    if journals:
                        latest = journals[0]
                        status["reflection"]["status"] = "idle"
                        status["reflection"]["detail"] = f"Journal: {latest.name}"
                    else:
                        status["reflection"]["status"] = "idle"
                        status["reflection"]["detail"] = "No recent activity"
                else:
                    status["reflection"]["status"] = "idle"
                    status["reflection"]["detail"] = "No recent activity"

            conn.close()
        except Exception:
            pass

    return status


# Routes

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard view."""
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "server": get_server_health(),
        "layers": get_layer_health(),
        "activity": get_recent_activity(10),
        "channels": get_channel_stats(),
        "daemons": get_daemon_status(),
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


@app.get("/api/health")
async def api_health():
    """API endpoint for layer health."""
    return get_layer_health()


@app.get("/api/activity")
async def api_activity(limit: int = 10):
    """API endpoint for recent activity."""
    return get_recent_activity(limit)


@app.get("/api/dashboard-content", response_class=HTMLResponse)
async def api_dashboard_content(request: Request):
    """Dashboard content for auto-refresh."""
    # Get all the data
    server = get_server_health()
    layers = get_layer_health()
    activity = get_recent_activity(10)
    channels = get_channel_stats()
    daemons = get_daemon_status()
    
    # Render just the content part
    return templates.TemplateResponse("partials/dashboard_content.html", {
        "request": request,
        "server": server,
        "layers": layers,
        "activity": activity,
        "channels": channels,
        "daemons": daemons
    })


@app.get("/health")
async def health_check():
    """Simple health check for Docker."""
    return {"status": "ok", "service": "pps-web"}


# Knowledge Graph API endpoints

@app.get("/api/graph/search")
async def api_graph_search(query: str, limit: int = 20):
    """
    Search entities and relationships in the knowledge graph.
    
    This endpoint provides semantic search over the knowledge graph,
    returning relevant entities and relationships for visualization.
    """
    if not query:
        raise HTTPException(status_code=400, detail="Query parameter is required")
    
    try:
        # Create RichTextureLayer instance
        rich_texture = RichTextureLayer()
        
        # Perform search
        results = await rich_texture.search(query, limit=limit)
        
        # Transform results into graph-friendly format
        nodes = {}
        edges = []
        
        for result in results:
            metadata = result.metadata or {}

            if metadata.get("type") == "entity":
                # Add entity as a node
                # Use 'or' to handle None values (not just missing keys)
                node_id = metadata.get("name") or "unknown"
                # Skip invalid node IDs
                if not node_id or not isinstance(node_id, str):
                    continue
                nodes[node_id] = {
                    "id": node_id,
                    "label": node_id,
                    "type": "entity",
                    "labels": metadata.get("labels") or [],
                    "relevance": result.relevance_score,
                    "content": result.content
                }

            elif metadata.get("type") == "fact":
                # Add fact as edges and ensure nodes exist
                # Use 'or' to handle None values
                subject = metadata.get("subject") or "unknown"
                predicate = metadata.get("predicate") or "relates_to"
                obj = metadata.get("object") or "unknown"

                # Skip facts with invalid node IDs
                if not isinstance(subject, str) or not isinstance(obj, str):
                    continue

                # Ensure subject and object nodes exist
                if subject not in nodes:
                    nodes[subject] = {
                        "id": subject,
                        "label": subject,
                        "type": "entity",
                        "labels": [],
                        "relevance": 0.5
                    }

                if obj not in nodes:
                    nodes[obj] = {
                        "id": obj,
                        "label": obj,
                        "type": "entity",
                        "labels": [],
                        "relevance": 0.5
                    }

                # Add edge
                edges.append({
                    "source": subject,
                    "target": obj,
                    "label": predicate,
                    "relevance": result.relevance_score,
                    "content": result.content
                })
        
        # Close the session
        await rich_texture.close()
        
        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "query": query,
            "count": len(results)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph search failed: {str(e)}")


@app.get("/api/graph/explore/{entity}")
async def api_graph_explore(entity: str, depth: int = 2):
    """
    Get relationships for a specific entity.
    
    Explores the knowledge graph from a specific entity,
    returning connected entities and relationships.
    """
    try:
        # Create RichTextureLayer instance
        rich_texture = RichTextureLayer()
        
        # Explore from entity
        results = await rich_texture.explore(entity, depth=depth)
        
        # Transform results similar to search
        nodes = {}
        edges = []
        
        # Always include the source entity
        nodes[entity] = {
            "id": entity,
            "label": entity,
            "type": "entity",
            "labels": [],
            "relevance": 1.0,
            "isSource": True
        }
        
        for result in results:
            metadata = result.metadata or {}
            
            if metadata.get("type") == "entity" and metadata.get("name") != entity:
                # Add connected entity
                node_id = metadata.get("name", "unknown")
                nodes[node_id] = {
                    "id": node_id,
                    "label": node_id,
                    "type": "entity",
                    "labels": metadata.get("labels", []),
                    "relevance": result.relevance_score,
                    "content": result.content
                }
                
            elif metadata.get("type") == "fact":
                # Process relationships
                subject = metadata.get("subject", "unknown")
                predicate = metadata.get("predicate", "relates_to")
                obj = metadata.get("object", "unknown")
                
                # Only include if the entity is involved
                if entity in [subject, obj]:
                    # Ensure both nodes exist
                    if subject not in nodes:
                        nodes[subject] = {
                            "id": subject,
                            "label": subject,
                            "type": "entity",
                            "labels": [],
                            "relevance": 0.5
                        }
                    
                    if obj not in nodes:
                        nodes[obj] = {
                            "id": obj,
                            "label": obj,
                            "type": "entity",
                            "labels": [],
                            "relevance": 0.5
                        }
                    
                    edges.append({
                        "source": subject,
                        "target": obj,
                        "label": predicate,
                        "relevance": result.relevance_score,
                        "content": result.content
                    })
        
        # Close the session
        await rich_texture.close()
        
        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "entity": entity,
            "depth": depth
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph exploration failed: {str(e)}")


@app.get("/api/graph/entities")
async def api_graph_entities(limit: int = 100):
    """
    List all entities with metadata.

    Returns a list of all entities in the knowledge graph.
    This is useful for populating entity selectors or getting an overview.
    """
    import re

    def extract_entities_from_fact(fact_text: str) -> list[str]:
        """Extract entity names from fact text using heuristics."""
        # Known entity names that appear in our data
        known_entities = [
            "Jeff", "Lyra", "Caia", "Nexus", "Brandi", "Jaden", "Steve",
            "Bitsy", "PPS", "MCP", "Graphiti", "ChromaDB", "Discord",
        ]
        found = []

        # Check for known entities
        for entity in known_entities:
            if entity.lower() in fact_text.lower():
                found.append(entity)

        # Also try to extract capitalized words at start of sentences
        # "Jeff has..." -> Jeff, "Lyra is..." -> Lyra
        words = fact_text.split()
        if words and words[0][0].isupper() and len(words[0]) > 1:
            candidate = words[0].rstrip("',.:;")
            if candidate not in found and candidate.isalpha():
                found.append(candidate)

        return found

    try:
        # Query Graphiti directly for facts - extract entities from them
        graphiti_host = os.getenv("GRAPHITI_HOST", "localhost")
        graphiti_port = int(os.getenv("GRAPHITI_PORT", "8203"))
        graphiti_url = f"http://{graphiti_host}:{graphiti_port}"
        group_id = os.getenv("GRAPHITI_GROUP_ID", "lyra")

        # Search for common patterns to get a broad set of facts
        search_queries = ["Lyra", "Jeff", "Caia", "awareness", "memory", "project"]
        entities = {}
        entity_mentions = {}  # Track mention count per entity

        for query in search_queries:
            resp = requests.post(
                f"{graphiti_url}/search",
                json={
                    "query": query,
                    "group_ids": [group_id],
                    "max_facts": limit // len(search_queries),
                },
                timeout=10
            )

            if resp.status_code == 200:
                data = resp.json()

                # Extract entities from nodes if returned
                for node in data.get("nodes", []):
                    name = node.get("name")
                    if name and name not in entities:
                        entities[name] = {
                            "name": name,
                            "labels": node.get("labels", []),
                            "relevance": 0.9
                        }

                # Extract entities from fact text
                for fact in data.get("facts", []):
                    fact_text = fact.get("fact", "")
                    predicate = fact.get("name", "RELATES_TO")

                    # Extract entity names from the fact text
                    found_entities = extract_entities_from_fact(fact_text)

                    for entity_name in found_entities:
                        if entity_name not in entities:
                            entities[entity_name] = {
                                "name": entity_name,
                                "labels": [],
                                "relevance": 0.5
                            }
                            entity_mentions[entity_name] = 0
                        entity_mentions[entity_name] = entity_mentions.get(entity_name, 0) + 1

        # Boost relevance based on mention count
        for name, count in entity_mentions.items():
            if name in entities:
                entities[name]["relevance"] = min(0.95, 0.5 + count * 0.05)

        # Sort by relevance and return as list
        entity_list = sorted(entities.values(), key=lambda e: e["relevance"], reverse=True)

        return {
            "entities": entity_list[:limit],
            "count": len(entity_list)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Entity listing failed: {str(e)}")


# Graph visualization page

@app.get("/graph", response_class=HTMLResponse)
async def graph_page(request: Request):
    """Knowledge graph visualization page."""
    return templates.TemplateResponse("graph.html", {
        "request": request,
        "graphiti_enabled": True  # Could check actual availability here
    })


# Future routes (placeholders)

@app.get("/messages", response_class=HTMLResponse)
async def messages(
    request: Request,
    channel: Optional[str] = None,
    author: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1
):
    """Message browser with filters and search."""
    message_data = get_messages(
        channel=channel,
        author=author,
        search=search,
        page=page,
        per_page=25
    )

    return templates.TemplateResponse("messages.html", {
        "request": request,
        "data": message_data,
        "channels": get_unique_channels(),
        "authors": get_unique_authors(),
        "filters": {
            "channel": channel or "",
            "author": author or "",
            "search": search or ""
        }
    })


@app.get("/photos", response_class=HTMLResponse)
async def photos(request: Request, resync_result: Optional[str] = None):
    """Word-photos sync status and management."""
    sync_status = get_word_photo_sync_status()
    return templates.TemplateResponse("photos.html", {
        "request": request,
        "sync": sync_status,
        "resync_result": resync_result
    })


@app.post("/photos/resync")
async def photos_resync():
    """Trigger word-photo resync (nuclear option)."""
    result = do_word_photo_resync()
    return result


@app.get("/api/photos/activity")
async def api_photos_activity(hours: int = 24, limit: int = 20):
    """Get recent word-photo search activity from daemon traces."""
    conn = get_db_connection()
    if not conn:
        return HTMLResponse('<div class="text-gray-500 text-center">No activity data available</div>')
    
    try:
        cursor = conn.cursor()
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        # Look for anchor_search events in daemon traces
        cursor.execute("""
            SELECT timestamp, event_data
            FROM daemon_traces
            WHERE event_type = 'tool_call' 
                AND json_extract(event_data, '$.tool_name') = 'mcp__pps__anchor_search'
                AND timestamp > ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (cutoff, limit))
        
        html = '<div class="space-y-2">'
        
        events = cursor.fetchall()
        if events:
            import json
            for event in events:
                try:
                    data = json.loads(event["event_data"])
                    query = data.get("params", {}).get("query", "Unknown")
                    result_count = data.get("result_summary", {}).get("count", 0)
                    timestamp = datetime.fromisoformat(event["timestamp"]).strftime("%H:%M:%S")
                    
                    html += f'''
                    <div class="flex justify-between items-center py-2 border-b border-gray-700 last:border-0">
                        <div class="flex-1">
                            <span class="text-gray-400 text-sm">{timestamp}</span>
                            <span class="text-gray-300 ml-3">Search: "{query}"</span>
                        </div>
                        <span class="text-gray-500 text-sm">{result_count} results</span>
                    </div>
                    '''
                except:
                    continue
        else:
            # If no traces, show recent word-photo reads as fallback
            cursor.execute("""
                SELECT created_at, content
                FROM messages
                WHERE author_name = 'Lyra' 
                    AND content LIKE '%word_photo%' 
                    AND created_at > ?
                ORDER BY created_at DESC
                LIMIT 5
            """, (cutoff,))
            
            fallback_events = cursor.fetchall()
            if fallback_events:
                html += '<div class="text-gray-500 text-sm mb-2">No trace data available. Showing recent mentions:</div>'
                for event in fallback_events:
                    timestamp = datetime.fromisoformat(event["created_at"]).strftime("%H:%M:%S")
                    html += f'<div class="text-gray-400 text-sm py-1">{timestamp} - Word-photo access detected</div>'
            else:
                html += '<div class="text-gray-500 text-center">No recent word-photo activity</div>'
        
        html += '</div>'
        conn.close()
        return HTMLResponse(html)
        
    except Exception as e:
        return HTMLResponse(f'<div class="text-gray-500 text-center">Error loading activity: {str(e)}</div>')


@app.get("/crystals", response_class=HTMLResponse)
async def crystals(request: Request):
    """Crystal chain view - view current and archived crystals."""
    crystal_data = get_crystal_list()
    return templates.TemplateResponse("crystals.html", {
        "request": request,
        "crystals": crystal_data
    })


@app.get("/api/crystal/{filename}")
async def api_crystal_content(filename: str):
    """API endpoint for fetching a crystal's full content."""
    content = get_crystal_content(filename)
    if content is None:
        raise HTTPException(status_code=404, detail="Crystal not found")
    return {"filename": filename, "content": content}


@app.get("/reflections", response_class=HTMLResponse)
async def reflections(request: Request, hours: int = 24):
    """Reflection sessions viewer."""
    # Get reflection sessions from daemon_traces
    sessions = get_daemon_sessions(daemon_type="reflection", hours=hours)
    
    # Check if trace logging is enabled
    conn = get_db_connection()
    trace_logging_enabled = False
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daemon_traces'")
            trace_logging_enabled = cursor.fetchone() is not None
            conn.close()
        except:
            pass
    
    return templates.TemplateResponse("reflections.html", {
        "request": request,
        "sessions": sessions,
        "trace_logging_enabled": trace_logging_enabled
    })


@app.get("/discord", response_class=HTMLResponse)
async def discord(request: Request, hours: int = 24, channel: Optional[str] = None):
    """Discord processing viewer."""
    # Get Discord sessions from daemon_traces
    sessions = get_daemon_sessions(daemon_type="discord", hours=hours)
    
    # Get daemon status info
    daemon_status = "unknown"
    last_message_time = None
    messages_today = 0
    
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Check last Discord message
            cursor.execute("""
                SELECT created_at FROM messages 
                WHERE channel LIKE 'discord:%' 
                ORDER BY created_at DESC LIMIT 1
            """)
            row = cursor.fetchone()
            if row:
                last_message_time = row["created_at"]
                # Simple heuristic: if last message < 10 min ago, daemon is "online"
                from datetime import datetime, timedelta
                last_msg_dt = datetime.fromisoformat(row["created_at"].replace(" ", "T"))
                if datetime.now() - last_msg_dt < timedelta(minutes=10):
                    daemon_status = "online"
                else:
                    daemon_status = "idle"
            
            # Count today's messages
            today = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("""
                SELECT COUNT(*) as count FROM messages 
                WHERE channel LIKE 'discord:%' AND created_at >= ?
            """, (today,))
            messages_today = cursor.fetchone()["count"]
            
            conn.close()
        except:
            pass
    
    return templates.TemplateResponse("discord.html", {
        "request": request,
        "sessions": sessions,
        "daemon_status": daemon_status,
        "last_message_time": last_message_time,
        "messages_today": messages_today
    })


@app.get("/heartbeat", response_class=HTMLResponse)
async def heartbeat_redirect(request: Request):
    """Redirect old heartbeat URL to reflections."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/reflections", status_code=301)


# API endpoints for new reflection/discord pages

@app.get("/api/reflections")
async def api_reflections(hours: int = 24, outcome: Optional[str] = None):
    """Get reflection sessions with optional filtering."""
    sessions = get_daemon_sessions(daemon_type="reflection", hours=hours)
    
    # Add formatted fields and filter by outcome if specified
    for session in sessions:
        # Format duration
        if session.get("started_at") and session.get("ended_at"):
            start = datetime.fromisoformat(session["started_at"])
            end = datetime.fromisoformat(session["ended_at"])
            duration = (end - start).total_seconds()
            if duration < 60:
                session["duration_formatted"] = f"{int(duration)}s"
            else:
                session["duration_formatted"] = f"{int(duration // 60)}m {int(duration % 60)}s"
        
        # Determine outcome (placeholder logic - would need actual trace analysis)
        session["outcome"] = "no_action"  # Default
        session["summary"] = "Autonomous reflection completed."
    
    return {"sessions": sessions}


@app.get("/api/reflections/{session_id}")
async def api_reflection_detail(session_id: str):
    """Get detailed trace for a reflection session."""
    traces = get_session_traces(session_id)

    if not traces:
        return HTMLResponse("""
            <div class="mt-4 p-4 bg-gray-600 rounded-lg">
                <p class="text-gray-400 text-sm">No trace data available for this session.</p>
            </div>
        """)

    # Build HTML for the trace events
    events_html = ""
    for trace in traces:
        event_type = trace.get("event_type", "unknown")
        timestamp = trace.get("timestamp", "")
        data = trace.get("event_data", {})

        # Format the event nicely
        detail = data.get("summary", data.get("detail", str(data)[:100]))

        events_html += f"""
            <div class="flex items-start space-x-3 py-2 border-b border-gray-600 last:border-0">
                <span class="text-xs text-gray-500 w-20 shrink-0">{timestamp.split('T')[1][:8] if 'T' in timestamp else timestamp}</span>
                <span class="text-xs px-2 py-0.5 rounded bg-gray-600 text-gray-300">{event_type}</span>
                <span class="text-sm text-gray-400">{detail}</span>
            </div>
        """

    return HTMLResponse(f"""
        <div class="mt-4 p-4 bg-gray-600 rounded-lg">
            <h4 class="font-medium mb-3 text-gray-300">Session Trace</h4>
            <div class="space-y-1">
                {events_html if events_html else '<p class="text-gray-400 text-sm">No events recorded.</p>'}
            </div>
        </div>
    """)


@app.get("/api/discord")
async def api_discord(hours: int = 24, channel: Optional[str] = None):
    """Get Discord processing sessions."""
    sessions = get_daemon_sessions(daemon_type="discord", hours=hours)
    
    # Add placeholder fields (would come from actual trace data)
    for session in sessions:
        session["channel"] = "general"  # Would extract from trace
        session["author"] = "User"  # Would extract from trace
        session["message_content"] = "Message content would appear here..."
        session["processing_time"] = 250
        session["identity_load_time"] = 50
        session["context_tokens"] = 48000
        session["api_time"] = 180
        session["response_tokens"] = 1200
        session["trace_events"] = []  # Would populate from traces
    
    return {"sessions": sessions}


@app.get("/api/discord/trace/{session_id}")
async def api_discord_trace(session_id: str):
    """Get detailed trace for a Discord session."""
    traces = get_session_traces(session_id)
    
    # Format events for display
    events = []
    for trace in traces:
        events.append({
            "timestamp": trace["timestamp"],
            "event_type": trace["event_type"],
            "details": trace.get("event_data", {}).get("summary", "")
        })
    
    return {"session_id": session_id, "events": events}


# Daemon Traces API (Phase 3: Observability)

def get_daemon_traces(
    daemon_type: Optional[str] = None,
    event_type: Optional[str] = None,
    hours: int = 24,
    limit: int = 100
) -> list:
    """Get recent daemon traces with optional filtering."""
    conn = get_db_connection()
    if not conn:
        return []

    try:
        cursor = conn.cursor()
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        # Build query with optional filters
        conditions = ["timestamp > ?"]
        params = [cutoff]

        if daemon_type:
            conditions.append("daemon_type = ?")
            params.append(daemon_type)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)

        params.append(limit)
        where_clause = " AND ".join(conditions)

        cursor.execute(f"""
            SELECT id, session_id, daemon_type, timestamp, event_type, event_data, duration_ms
            FROM daemon_traces
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
        """, params)

        import json
        traces = []
        for row in cursor.fetchall():
            traces.append({
                "id": row["id"],
                "session_id": row["session_id"],
                "daemon_type": row["daemon_type"],
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "event_data": json.loads(row["event_data"]) if row["event_data"] else None,
                "duration_ms": row["duration_ms"],
            })

        conn.close()
        return traces
    except Exception as e:
        return []


def get_daemon_sessions(
    daemon_type: Optional[str] = None,
    hours: int = 24,
    limit: int = 20
) -> list:
    """Get summaries of recent daemon sessions."""
    conn = get_db_connection()
    if not conn:
        return []

    try:
        cursor = conn.cursor()
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

        if daemon_type:
            cursor.execute("""
                SELECT
                    session_id,
                    daemon_type,
                    MIN(timestamp) as started_at,
                    MAX(timestamp) as ended_at,
                    COUNT(*) as event_count,
                    SUM(CASE WHEN event_type LIKE '%_complete' THEN 1 ELSE 0 END) as completed_events
                FROM daemon_traces
                WHERE timestamp > ? AND daemon_type = ?
                GROUP BY session_id, daemon_type
                ORDER BY started_at DESC
                LIMIT ?
            """, (cutoff, daemon_type, limit))
        else:
            cursor.execute("""
                SELECT
                    session_id,
                    daemon_type,
                    MIN(timestamp) as started_at,
                    MAX(timestamp) as ended_at,
                    COUNT(*) as event_count,
                    SUM(CASE WHEN event_type LIKE '%_complete' THEN 1 ELSE 0 END) as completed_events
                FROM daemon_traces
                WHERE timestamp > ?
                GROUP BY session_id, daemon_type
                ORDER BY started_at DESC
                LIMIT ?
            """, (cutoff, limit))

        sessions = []
        for row in cursor.fetchall():
            sessions.append(dict(row))

        conn.close()
        return sessions
    except Exception as e:
        return []


def get_session_traces(session_id: str, limit: int = 100) -> list:
    """Get all traces for a specific session."""
    conn = get_db_connection()
    if not conn:
        return []

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, session_id, daemon_type, timestamp, event_type, event_data, duration_ms
            FROM daemon_traces
            WHERE session_id = ?
            ORDER BY timestamp ASC
            LIMIT ?
        """, (session_id, limit))

        import json
        traces = []
        for row in cursor.fetchall():
            traces.append({
                "id": row["id"],
                "session_id": row["session_id"],
                "daemon_type": row["daemon_type"],
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "event_data": json.loads(row["event_data"]) if row["event_data"] else None,
                "duration_ms": row["duration_ms"],
            })

        conn.close()
        return traces
    except Exception as e:
        return []


@app.get("/api/traces")
async def api_traces(
    daemon_type: Optional[str] = None,
    event_type: Optional[str] = None,
    hours: int = 24,
    limit: int = 100
):
    """Get recent daemon traces with optional filtering."""
    return {
        "traces": get_daemon_traces(daemon_type, event_type, hours, limit),
        "filters": {
            "daemon_type": daemon_type,
            "event_type": event_type,
            "hours": hours,
            "limit": limit
        }
    }


@app.get("/api/traces/sessions")
async def api_trace_sessions(
    daemon_type: Optional[str] = None,
    hours: int = 24,
    limit: int = 20
):
    """Get summaries of recent daemon sessions."""
    return {
        "sessions": get_daemon_sessions(daemon_type, hours, limit),
        "filters": {
            "daemon_type": daemon_type,
            "hours": hours,
            "limit": limit
        }
    }


@app.get("/api/traces/session/{session_id}")
async def api_session_traces(session_id: str, limit: int = 100):
    """Get all traces for a specific session."""
    traces = get_session_traces(session_id, limit)
    if not traces:
        raise HTTPException(status_code=404, detail="Session not found or no traces")
    return {
        "session_id": session_id,
        "traces": traces,
        "count": len(traces)
    }


@app.get("/traces", response_class=HTMLResponse)
async def traces_page(
    request: Request,
    daemon_type: Optional[str] = None,
    hours: int = 24
):
    """Daemon traces viewer page."""
    sessions = get_daemon_sessions(daemon_type=daemon_type, hours=hours)
    return templates.TemplateResponse("traces.html", {
        "request": request,
        "sessions": sessions,
        "filters": {
            "daemon_type": daemon_type or "",
            "hours": hours
        }
    })


# Memory Inspector - See what ambient_recall returns

@app.get("/memory", response_class=HTMLResponse)
async def memory_inspector(request: Request):
    """Memory Inspector page - see what ambient_recall returns."""
    return templates.TemplateResponse("memory.html", {
        "request": request
    })


@app.get("/api/memory/query")
async def api_memory_query(context: str = "startup", limit: int = 5):
    """Query ambient_recall and return detailed results for inspection."""
    import json

    pps_url = f"http://{PPS_SERVER_HOST}:{PPS_SERVER_PORT}"

    try:
        # Call the PPS server's ambient_recall endpoint
        resp = requests.post(
            f"{pps_url}/tools/ambient_recall",
            json={"context": context, "limit_per_layer": limit},
            timeout=30
        )

        if resp.status_code != 200:
            return {
                "error": f"PPS server returned {resp.status_code}",
                "results": [],
                "stats": {}
            }

        data = resp.json()

        # Parse the results and group by layer
        results_by_layer = {
            "raw_capture": [],
            "core_anchors": [],
            "rich_texture": [],
            "crystallization": [],
            "recent_turns": [],
            "message_summaries": []
        }

        total_chars = 0
        total_items = 0

        # Handle both old format (results array) and new format with sections
        if "results" in data:
            for item in data.get("results", []):
                layer = item.get("layer", "unknown")
                content = item.get("content", "")
                total_chars += len(content)
                total_items += 1

                results_by_layer.setdefault(layer, []).append({
                    "content": content[:500] + "..." if len(content) > 500 else content,
                    "full_length": len(content),
                    "source": item.get("source", ""),
                    "relevance": item.get("relevance_score", 0),
                    "metadata": item.get("metadata", {})
                })

        # Also check for clock/time_note
        clock = data.get("clock")
        time_note = data.get("time_note")

        # Estimate tokens (rough: 4 chars per token)
        estimated_tokens = total_chars // 4

        return {
            "query": context,
            "limit_per_layer": limit,
            "results_by_layer": results_by_layer,
            "stats": {
                "total_items": total_items,
                "total_chars": total_chars,
                "estimated_tokens": estimated_tokens,
                "clock": clock,
                "time_note": time_note
            }
        }

    except requests.exceptions.ConnectionError:
        return {
            "error": "Cannot connect to PPS server",
            "results": [],
            "stats": {}
        }
    except Exception as e:
        return {
            "error": str(e),
            "results": [],
            "stats": {}
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
