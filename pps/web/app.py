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

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Configuration from environment
CLAUDE_HOME = Path(os.getenv("CLAUDE_HOME", "/home/jeff/.claude"))
CHROMA_HOST = os.getenv("CHROMA_HOST", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", 8000))
DB_PATH = CLAUDE_HOME / "data" / "lyra_conversations.db"
WORD_PHOTOS_PATH = CLAUDE_HOME / "memories" / "word_photos"
SUMMARIES_PATH = CLAUDE_HOME / "summaries" / "current"
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

    # Layer 4: Summaries
    try:
        if SUMMARIES_PATH.exists():
            summaries = list(SUMMARIES_PATH.glob("summary_*.md"))
            health["layer4"]["status"] = "ok"
            health["layer4"]["detail"] = f"{len(summaries)} active"
        else:
            health["layer4"]["status"] = "warning"
            health["layer4"]["detail"] = "No summaries dir"
    except Exception as e:
        health["layer4"]["status"] = "error"
        health["layer4"]["detail"] = str(e)

    return health


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


@app.get("/summaries", response_class=HTMLResponse)
async def summaries(request: Request):
    """Summary chain view - coming soon."""
    return templates.TemplateResponse("coming_soon.html", {
        "request": request,
        "page": "Summaries"
    })


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
