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
from layers.rich_texture import RichTextureLayer

# Configuration from environment
CLAUDE_HOME = Path(os.getenv("CLAUDE_HOME", "/home/jeff/.claude"))
CHROMA_HOST = os.getenv("CHROMA_HOST", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", 8000))
PPS_SERVER_HOST = os.getenv("PPS_SERVER_HOST", "pps-server")
PPS_SERVER_PORT = int(os.getenv("PPS_SERVER_PORT", 8000))
DB_PATH = CLAUDE_HOME / "data" / "lyra_conversations.db"
WORD_PHOTOS_PATH = CLAUDE_HOME / "memories" / "word_photos"
CRYSTALS_PATH = CLAUDE_HOME / "crystals" / "current"
CRYSTALS_ARCHIVE_PATH = CLAUDE_HOME / "crystals" / "archive"
JOURNALS_PATH = CLAUDE_HOME / "journals"

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
    status = {
        "discord": {"status": "unknown", "detail": ""},
        "heartbeat": {"status": "unknown", "detail": ""},
        "terminal": {"status": "unknown", "detail": ""}
    }

    # Check for recent Discord messages
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
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

            conn.close()
        except Exception:
            pass

    # Check for recent heartbeat journals
    heartbeat_path = JOURNALS_PATH / "heartbeat"
    if heartbeat_path.exists():
        journals = sorted(heartbeat_path.glob("*.md"), reverse=True)
        if journals:
            latest = journals[0]
            status["heartbeat"]["status"] = "active"
            status["heartbeat"]["detail"] = latest.name

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
                # Add fact as edges and ensure nodes exist
                subject = metadata.get("subject", "unknown")
                predicate = metadata.get("predicate", "relates_to")
                obj = metadata.get("object", "unknown")
                
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
        await rich_texture._close_session()
        
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
        await rich_texture._close_session()
        
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
    try:
        # For now, we'll use a broad search to get entities
        # In the future, this could be optimized with a dedicated endpoint
        rich_texture = RichTextureLayer()
        
        # Search with an empty-ish query to get a broad set of results
        results = await rich_texture.search("", limit=limit)
        
        # Extract unique entities
        entities = {}
        
        for result in results:
            metadata = result.metadata or {}
            
            if metadata.get("type") == "entity":
                name = metadata.get("name", "unknown")
                if name not in entities:
                    entities[name] = {
                        "name": name,
                        "labels": metadata.get("labels", []),
                        "relevance": result.relevance_score
                    }
            elif metadata.get("type") == "fact":
                # Extract entities from facts
                for entity_name in [metadata.get("subject"), metadata.get("object")]:
                    if entity_name and entity_name not in entities:
                        entities[entity_name] = {
                            "name": entity_name,
                            "labels": [],
                            "relevance": 0.5
                        }
        
        # Close the session
        await rich_texture._close_session()
        
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
async def messages(request: Request):
    """Message browser - coming soon."""
    return templates.TemplateResponse("coming_soon.html", {
        "request": request,
        "page": "Messages"
    })


@app.get("/photos", response_class=HTMLResponse)
async def photos(request: Request):
    """Word-photo gallery - coming soon."""
    return templates.TemplateResponse("coming_soon.html", {
        "request": request,
        "page": "Word-Photos"
    })


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


@app.get("/heartbeat", response_class=HTMLResponse)
async def heartbeat(request: Request):
    """Heartbeat log viewer - coming soon."""
    return templates.TemplateResponse("coming_soon.html", {
        "request": request,
        "page": "Heartbeat Log"
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
