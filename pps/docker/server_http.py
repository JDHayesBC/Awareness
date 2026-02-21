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
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import time
import httpx

from auth import load_tokens, check_auth, AUTH_EXEMPT_TOOLS, validate_master_only, regenerate_entity_token


# Request models
class AmbientRecallRequest(BaseModel):
    context: str
    limit_per_layer: int = 5
    token: str = ""
    channel: str = ""  # Requesting channel (e.g., "haven", "terminal") — excluded from cross-channel results


class AnchorSearchRequest(BaseModel):
    query: str
    limit: int = 10
    token: str = ""


class RawSearchRequest(BaseModel):
    query: str
    limit: int = 20
    token: str = ""


class AddTripletRequest(BaseModel):
    source: str
    relationship: str
    target: str
    fact: str | None = None
    source_type: str | None = None
    target_type: str | None = None
    token: str = ""


class StoreMessageRequest(BaseModel):
    content: str
    author_name: str = "Unknown"
    channel: str = "terminal"
    is_lyra: bool = False
    session_id: str | None = None
    token: str = ""


class TextureSearchRequest(BaseModel):
    query: str
    limit: int = 10
    center_node_uuid: str | None = None
    token: str = ""


class TextureExploreRequest(BaseModel):
    entity_name: str
    depth: int = 2
    token: str = ""


class TextureTimelineRequest(BaseModel):
    since: str
    until: str | None = None
    limit: int = 20
    token: str = ""


class SummarizeMessagesRequest(BaseModel):
    limit: int = 50
    summary_type: str = "work"
    token: str = ""


class StoreSummaryRequest(BaseModel):
    summary_text: str
    start_id: int
    end_id: int
    channels: list[str] = []
    summary_type: str = "work"
    token: str = ""


# Phase 1 HTTP Migration - New Request Models
class AnchorSaveRequest(BaseModel):
    """Request to save a word-photo (anchor)."""
    content: str          # The word-photo content in markdown
    title: str            # Title (used in filename)
    location: str = "terminal"  # Context tag (terminal, discord, reflection, etc.)
    token: str = ""


class CrystallizeRequest(BaseModel):
    """Request to create a new crystal."""
    content: str          # Crystal content in markdown format
    token: str = ""


class TextureAddRequest(BaseModel):
    """Request to add content to the knowledge graph."""
    content: str          # Content to store (conversation, note, observation)
    channel: str = "manual"  # Source channel for metadata
    token: str = ""


class PollChannelsRequest(BaseModel):
    """Request to poll cross-channel messages (drain-only operation)."""
    channel: str = ""  # Requesting channel (excluded from results)
    limit: int = 100   # Number of messages to retrieve
    token: str = ""


class IngestBatchRequest(BaseModel):
    """Request to batch ingest messages to Graphiti."""
    batch_size: int = 20  # Number of messages to ingest
    token: str = ""


class EnterSpaceRequest(BaseModel):
    """Request to enter a space and load its context."""
    space_name: str       # Name of the space to enter
    token: str = ""


class GetCrystalsRequest(BaseModel):
    """Request to get recent crystals."""
    count: int = 4        # Number of recent crystals to retrieve
    token: str = ""


# Phase 2 HTTP Migration - Additional Request Models

class GetTurnsSinceSummaryRequest(BaseModel):
    """Request to get conversation turns after last summary."""
    limit: int = 50
    offset: int = 0
    min_turns: int = 10
    channel: str | None = None
    oldest_first: bool = False
    token: str = ""


class GetRecentSummariesRequest(BaseModel):
    """Request to get recent message summaries."""
    limit: int = 5
    token: str = ""


class SearchSummariesRequest(BaseModel):
    """Request to search message summaries."""
    query: str
    limit: int = 10
    token: str = ""


class InventoryListRequest(BaseModel):
    """Request to list inventory items by category."""
    category: str
    subcategory: str | None = None
    limit: int = 50
    token: str = ""


class InventoryAddRequest(BaseModel):
    """Request to add an inventory item."""
    name: str
    category: str
    subcategory: str | None = None
    description: str | None = None
    attributes: dict | None = None
    token: str = ""


class InventoryGetRequest(BaseModel):
    """Request to get an inventory item."""
    name: str
    category: str
    token: str = ""


class InventoryDeleteRequest(BaseModel):
    """Request to delete an inventory item."""
    name: str
    category: str
    token: str = ""


class TechSearchRequest(BaseModel):
    """Request to search technical documentation."""
    query: str
    limit: int = 5
    category: str | None = None


class TechIngestRequest(BaseModel):
    """Request to ingest a markdown file into Tech RAG."""
    filepath: str
    category: str | None = None
    force: bool = False


class SynthesizeEntityRequest(BaseModel):
    """Request to synthesize prose summary from entity graph data."""
    entity_name: str
    token: str = ""


class GetConversationContextRequest(BaseModel):
    """Request to get N turns of context (blends summaries + raw turns)."""
    turns: int
    token: str = ""


class GetTurnsSinceRequest(BaseModel):
    """Request to get turns since a timestamp."""
    timestamp: str
    include_summaries: bool = True
    limit: int = 1000
    token: str = ""


class AgentContextRequest(BaseModel):
    """Compact context for sub-agent injection via hooks."""
    token: str = ""


class FrictionAddRequest(BaseModel):
    """Add a friction lesson."""
    severity: str = "medium"  # low, medium, high, critical
    tags: str = ""  # comma-separated
    problem: str = ""
    lesson: str = ""
    prevention: str = ""
    token: str = ""


class FrictionSearchRequest(BaseModel):
    """Search friction lessons."""
    query: str = ""
    limit: int = 3
    min_severity: str = "low"
    token: str = ""


class GetTurnsAroundRequest(BaseModel):
    """Request to get turns centered on a timestamp."""
    timestamp: str
    count: int = 40
    before_ratio: float = 0.5
    token: str = ""


class RegenerateTokenRequest(BaseModel):
    """Request to regenerate entity auth token. Requires master token."""
    master_token: str


class EmailSyncStatusRequest(BaseModel):
    """Request to get email sync status."""
    token: str = ""


class EmailSyncToPpsRequest(BaseModel):
    """Request to sync emails from email archive to PPS raw capture."""
    days_back: int = 7
    dry_run: bool = False
    token: str = ""


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
# Entity name — can't derive from Docker mount path (/app/entity is always the same)
ENTITY_NAME = os.getenv("ENTITY_NAME", ENTITY_PATH.name)

# Haven chat integration — poll for unread messages during ambient_recall
HAVEN_URL = os.getenv("HAVEN_URL", "")  # e.g. http://haven:8000 or http://localhost:8205

# RAG engine — proxies tech_search/ingest/list/delete instead of talking to ChromaDB directly
RAG_ENGINE_URL = os.getenv("RAG_ENGINE_URL", "http://rag-engine:8000")

# Load authentication tokens
ENTITY_TOKEN, MASTER_TOKEN = load_tokens(ENTITY_PATH)


# Haven state — track last poll time per entity to show only new messages
_haven_last_seen_file = ENTITY_PATH / "data" / "haven_last_seen.json"


def _load_haven_last_seen() -> dict:
    """Load per-room last-seen timestamps."""
    try:
        return json.loads(_haven_last_seen_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_haven_last_seen(state: dict) -> None:
    _haven_last_seen_file.parent.mkdir(parents=True, exist_ok=True)
    _haven_last_seen_file.write_text(json.dumps(state))


async def poll_haven() -> list[str]:
    """Poll Haven for unread messages across all rooms. Returns formatted lines."""
    if not HAVEN_URL:
        return []

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            headers = {"Authorization": f"Bearer {ENTITY_TOKEN}"}

            # Get rooms
            resp = await client.get(f"{HAVEN_URL}/api/rooms", headers=headers)
            if resp.status_code != 200:
                return []
            rooms = resp.json().get("rooms", [])

            if not rooms:
                return []

            last_seen = _load_haven_last_seen()
            lines = []
            new_last_seen = dict(last_seen)

            for room in rooms:
                rid = room["id"]
                since = last_seen.get(rid)

                params = {"limit": "20"}
                if since:
                    params["since"] = since

                resp = await client.get(
                    f"{HAVEN_URL}/api/rooms/{rid}/messages",
                    headers=headers, params=params
                )
                if resp.status_code != 200:
                    continue

                messages = resp.json().get("messages", [])
                if not messages:
                    continue

                # Update last-seen to most recent message timestamp
                new_last_seen[rid] = messages[-1]["created_at"]

                # Skip if this is first poll (don't dump entire history)
                if not since:
                    continue

                room_label = room["display_name"]
                for m in messages:
                    # Don't show the entity its own messages
                    if m["username"] == ENTITY_NAME:
                        continue
                    lines.append(f"- **#{room_label}** {m['display_name']}: {m['content']}")

            _save_haven_last_seen(new_last_seen)
            return lines

    except Exception as e:
        print(f"[PPS] Haven poll failed: {e}", file=sys.stderr)
        return []


# Cross-channel awareness — poll raw capture DB for unread turns from other channels
_channel_cursor_file = ENTITY_PATH / "data" / "channel_last_seen.json"


def _load_channel_cursors() -> dict:
    """Load per-channel last-seen message IDs."""
    try:
        return json.loads(_channel_cursor_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_channel_cursors(state: dict) -> None:
    _channel_cursor_file.parent.mkdir(parents=True, exist_ok=True)
    _channel_cursor_file.write_text(json.dumps(state))


def poll_other_channels(requesting_channel: str = "", limit: int = 100) -> tuple[list[str], int]:
    """Read unread messages from channels other than the requesting one.

    Uses per-consumer cursors so each channel (terminal, haven, discord) has its
    own read position. Terminal reading doesn't advance Haven's cursor.

    Args:
        requesting_channel: Channel making the request (e.g., "haven", "terminal").
                           Messages from this channel are excluded.
                           Also used as the cursor key.
        limit: Maximum number of messages to return per call (default 100).

    Returns:
        Tuple of (formatted_lines, remaining_count):
        - formatted_lines: List like ["- **[terminal]** Jeff: message content", ...]
        - remaining_count: Number of messages still in the queue after this batch
    """
    try:
        db_path = ENTITY_PATH / "data" / "conversations.db"
        if not db_path.exists():
            return ([], 0)

        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        cursors = _load_channel_cursors()
        # Per-consumer cursor: each requesting_channel has its own read position
        cursor_key = requesting_channel or "_default"
        last_id = cursors.get(cursor_key, 0)

        # Get total count of remaining messages
        cursor = conn.cursor()
        if requesting_channel:
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM messages
                WHERE id > ? AND (channel IS NULL OR channel NOT LIKE ?)
            """, (last_id, f"{requesting_channel}%"))
        else:
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM messages
                WHERE id > ?
            """, (last_id,))

        total_count = cursor.fetchone()["total"]

        # Massive backlog protection: if cursor is way behind (>1000 messages),
        # the entity is already caught up via startup (crystals/summaries cover history).
        # Skip to near-current instead of trying to drain thousands of old messages.
        if total_count > 1000:
            cursor.execute("SELECT MAX(id) FROM messages")
            max_row = cursor.fetchone()
            if max_row and max_row[0]:
                # Jump cursor forward, keeping only the most recent `limit` messages reachable
                skip_to = max_row[0] - limit
                if skip_to > last_id:
                    print(f"[PPS] Channel poll: {cursor_key} cursor {total_count} msgs behind, skipping to near-current", file=sys.stderr)
                    last_id = skip_to
                    # Recalculate total_count from new position
                    cursor = conn.cursor()
                    if requesting_channel:
                        cursor.execute("""
                            SELECT COUNT(*) as total FROM messages
                            WHERE id > ? AND (channel IS NULL OR channel NOT LIKE ?)
                        """, (last_id, f"{requesting_channel}%"))
                    else:
                        cursor.execute("SELECT COUNT(*) as total FROM messages WHERE id > ?", (last_id,))
                    total_count = cursor.fetchone()["total"]

        # Get messages newer than this consumer's cursor, excluding its own channel
        cursor = conn.cursor()
        if requesting_channel:
            # Exclude messages from the requesting channel AND match channel prefix
            # (terminal:abc123 starts with "terminal", haven starts with "haven")
            cursor.execute("""
                SELECT id, author_name, content, created_at, channel
                FROM messages
                WHERE id > ? AND (channel IS NULL OR channel NOT LIKE ?)
                ORDER BY created_at ASC
                LIMIT ?
            """, (last_id, f"{requesting_channel}%", limit))
        else:
            cursor.execute("""
                SELECT id, author_name, content, created_at, channel
                FROM messages
                WHERE id > ?
                ORDER BY created_at ASC
                LIMIT ?
            """, (last_id, limit))

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return ([], 0)

        lines = []
        max_id = last_id
        for row in rows:
            msg_id = row["id"]
            author = row["author_name"] or "Unknown"
            content = row["content"] or ""
            channel = row["channel"] or "unknown"
            if msg_id > max_id:
                max_id = msg_id
            # Truncate long messages
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(f"- **[{channel}]** {author}: {content}")

        # Update THIS consumer's cursor only
        cursors[cursor_key] = max_id
        _save_channel_cursors(cursors)

        # Calculate remaining count
        remaining = max(0, total_count - len(rows))

        return (lines, remaining)

    except Exception as e:
        print(f"[PPS] Channel poll failed: {e}", file=sys.stderr)
        return ([], 0)


def get_layers():
    """Initialize layers with Docker paths."""
    # Paths inside Docker container (configured via environment)
    memories_path = ENTITY_PATH / "memories" / "word_photos"
    # Database now in entity directory (Issue #131 migration)
    data_path = ENTITY_PATH / "data" / "conversations.db"
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
# Database now in entity directory (Issue #131 migration)
data_path = ENTITY_PATH / "data" / "conversations.db"
message_summaries = MessageSummariesLayer(db_path=data_path)

# Initialize inventory layer (Layer 5) for enter_space
# Database now in entity directory (Issue #131 migration)
inventory_db_path = ENTITY_PATH / "data" / "inventory.db"
inventory = InventoryLayer(db_path=inventory_db_path)

# Initialize Tech RAG layer (Layer 6) if available
tech_docs_path = CLAUDE_HOME / "tech_docs"
if USE_TECH_RAG:
    tech_rag = TechRAGLayer(
        tech_docs_path=tech_docs_path,
        chroma_host=CHROMA_HOST,
        chroma_port=CHROMA_PORT
    )
else:
    tech_rag = None

# Initialize friction learning store
import sqlite3 as _sqlite3


class FrictionStore:
    """Simple SQLite-backed friction lesson storage with FTS5 search."""

    SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = _sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS friction (
                id TEXT PRIMARY KEY,
                date TEXT,
                severity TEXT DEFAULT 'medium',
                tags TEXT DEFAULT '',
                problem TEXT,
                lesson TEXT,
                prevention TEXT DEFAULT '',
                times_applied INTEGER DEFAULT 0,
                times_prevented INTEGER DEFAULT 0
            )
        """)
        # FTS5 for full-text search
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS friction_fts USING fts5(
                id, tags, problem, lesson, prevention,
                content='friction',
                content_rowid='rowid'
            )
        """)
        # Triggers to keep FTS in sync
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS friction_ai AFTER INSERT ON friction BEGIN
                INSERT INTO friction_fts(id, tags, problem, lesson, prevention)
                VALUES (new.id, new.tags, new.problem, new.lesson, new.prevention);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS friction_ad AFTER DELETE ON friction BEGIN
                INSERT INTO friction_fts(friction_fts, id, tags, problem, lesson, prevention)
                VALUES ('delete', old.id, old.tags, old.problem, old.lesson, old.prevention);
            END
        """)
        conn.commit()
        conn.close()

    def _get_conn(self):
        conn = _sqlite3.connect(str(self.db_path))
        conn.row_factory = _sqlite3.Row
        return conn

    def add(self, severity: str, tags: str, problem: str, lesson: str, prevention: str = "") -> dict:
        conn = self._get_conn()
        # Auto-generate ID
        cursor = conn.execute("SELECT COUNT(*) FROM friction")
        count = cursor.fetchone()[0]
        fric_id = f"FRIC-{count + 1:03d}"
        date = datetime.now().isoformat()[:10]

        conn.execute(
            "INSERT INTO friction (id, date, severity, tags, problem, lesson, prevention) VALUES (?,?,?,?,?,?,?)",
            (fric_id, date, severity, tags, problem, lesson, prevention)
        )
        conn.commit()
        conn.close()
        return {"id": fric_id, "date": date}

    def search(self, query: str, limit: int = 3, min_severity: str = "low") -> list:
        conn = self._get_conn()
        min_sev_val = self.SEVERITY_ORDER.get(min_severity, 0)

        if query:
            # FTS5 search
            try:
                rows = conn.execute("""
                    SELECT f.*, rank
                    FROM friction f
                    JOIN friction_fts fts ON f.id = fts.id
                    WHERE friction_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (query, limit * 3)).fetchall()  # Over-fetch for severity filter
            except _sqlite3.OperationalError:
                # Fallback to LIKE search if FTS query syntax is invalid
                rows = conn.execute("""
                    SELECT *, 0 as rank FROM friction
                    WHERE problem LIKE ? OR lesson LIKE ? OR tags LIKE ?
                    ORDER BY date DESC
                    LIMIT ?
                """, (f"%{query}%", f"%{query}%", f"%{query}%", limit * 3)).fetchall()
        else:
            # No query — return most recent
            rows = conn.execute("""
                SELECT *, 0 as rank FROM friction
                ORDER BY date DESC
                LIMIT ?
            """, (limit * 3,)).fetchall()

        # Filter by severity and limit
        results = []
        for row in rows:
            sev_val = self.SEVERITY_ORDER.get(row["severity"], 0)
            if sev_val >= min_sev_val:
                results.append({
                    "id": row["id"],
                    "severity": row["severity"],
                    "tags": row["tags"],
                    "problem": row["problem"],
                    "lesson": row["lesson"],
                    "prevention": row["prevention"],
                    "times_applied": row["times_applied"],
                    "times_prevented": row["times_prevented"]
                })
                if len(results) >= limit:
                    break

        conn.close()
        return results

    def record_applied(self, fric_id: str):
        conn = self._get_conn()
        conn.execute("UPDATE friction SET times_applied = times_applied + 1 WHERE id = ?", (fric_id,))
        conn.commit()
        conn.close()

    def record_prevented(self, fric_id: str):
        conn = self._get_conn()
        conn.execute("UPDATE friction SET times_prevented = times_prevented + 1 WHERE id = ?", (fric_id,))
        conn.commit()
        conn.close()

    def stats(self) -> dict:
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM friction").fetchone()[0]
        by_severity = {}
        for row in conn.execute("SELECT severity, COUNT(*) as cnt FROM friction GROUP BY severity"):
            by_severity[row["severity"]] = row["cnt"]
        total_applied = conn.execute("SELECT SUM(times_applied) FROM friction").fetchone()[0] or 0
        total_prevented = conn.execute("SELECT SUM(times_prevented) FROM friction").fetchone()[0] or 0
        conn.close()
        return {
            "total_lessons": total,
            "by_severity": by_severity,
            "total_applied": total_applied,
            "total_prevented": total_prevented
        }


friction_db_path = ENTITY_PATH / "data" / "friction.db"
friction_store = FrictionStore(db_path=friction_db_path)

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
    print(f"  Tech RAG: {tech_docs_path if USE_TECH_RAG else 'disabled'}")
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

# Configure CORS to allow web container (8202) to call PPS server (8201)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8202",  # Web container
        "http://127.0.0.1:8202",  # Alternate localhost
    ],
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "ambient_recall")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    import time
    start_time = time.time()

    # Initialize manifest tracking
    manifest_data = {
        "crystals": {"chars": 0, "count": 0},
        "word_photos": {"chars": 0, "count": 0},
        "rich_texture": {"chars": 0, "count": 0},
        "summaries": {"chars": 0, "count": 0},
        "recent_turns": {"chars": 0, "count": 0},
    }

    all_results = []

    # STARTUP SPECIAL CASE: Use recency-based retrieval instead of semantic search
    # "startup" is a PACKAGE OPERATION, not a search query
    # Returns: most recent crystals, word-photos, and ALL unsummarized turns
    if request.context.lower() == "startup":
        # Define paths for direct file access
        word_photos_path = ENTITY_PATH / "memories" / "word_photos"

        # Get 3 most recent crystals (no semantic search)
        crystal_layer = layers[LayerType.CRYSTALLIZATION]
        crystals = crystal_layer._get_sorted_crystals()
        for crystal_path in crystals[-3:]:  # Last 3
            try:
                content = crystal_path.read_text()
                all_results.append({
                    "content": content,
                    "source": crystal_path.name,
                    "layer": "crystallization",
                    "relevance_score": 1.0,  # No scoring for recency-based
                    "metadata": {}
                })
                manifest_data["crystals"]["chars"] += len(content)
                manifest_data["crystals"]["count"] += 1
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
                    all_results.append({
                        "content": content,
                        "source": wp_path.name,
                        "layer": "core_anchors",
                        "relevance_score": 1.0,
                        "metadata": {}
                    })
                    manifest_data["word_photos"]["chars"] += len(content)
                    manifest_data["word_photos"]["count"] += 1
                except Exception as e:
                    print(f"[PPS] Error reading word-photo {wp_path.name}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[PPS] Error listing word-photos: {e}", file=sys.stderr)

        # Skip rich texture entirely for startup (per-turn hook already provides)
        # Skip message summaries search (handled below in recent_context_section)

    else:
        # NON-STARTUP: Use semantic search as normal
        tasks = [
            layer.search(request.context, request.limit_per_layer)
            for layer_type, layer in layers.items()
        ]
        layer_results = await asyncio.gather(*tasks, return_exceptions=True)

        for results in layer_results:
            if isinstance(results, list):
                for r in results:
                    result_dict = {
                        "content": r.content,
                        "source": r.source,
                        "layer": r.layer.value,
                        "relevance_score": r.relevance_score,
                        "metadata": r.metadata
                    }
                    all_results.append(result_dict)

                    # Track for manifest
                    content_len = len(r.content)
                    if r.layer.value == "crystallization":
                        manifest_data["crystals"]["chars"] += content_len
                        manifest_data["crystals"]["count"] += 1
                    elif r.layer.value == "core_anchors":
                        manifest_data["word_photos"]["chars"] += content_len
                        manifest_data["word_photos"]["count"] += 1
                    elif r.layer.value == "rich_texture":
                        manifest_data["rich_texture"]["chars"] += content_len
                        manifest_data["rich_texture"]["count"] += 1

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
            # Reduced from 5 to 2 for startup - focus on most recent
            recent_summaries = message_summaries.get_recent_summaries(limit=2)

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
                    manifest_data["summaries"]["chars"] += len(text)
                    manifest_data["summaries"]["count"] += 1

            # Cap unsummarized turns to prevent context overflow
            # Shows newest 50, with overflow message if more exist
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
                    manifest_data["recent_turns"]["chars"] += len(content)
                    manifest_data["recent_turns"]["count"] += 1

        except Exception as e:
            # Return error info but don't fail the entire request
            summaries = [{"error": f"Error fetching summaries: {e}"}]
            unsummarized_turns = [{"error": f"Error fetching unsummarized turns: {e}"}]

    # Calculate latency
    latency_ms = (time.time() - start_time) * 1000

    # Build manifest
    total_chars = sum(d["chars"] for d in manifest_data.values())
    manifest = {
        "crystals": manifest_data["crystals"],
        "word_photos": manifest_data["word_photos"],
        "rich_texture": manifest_data["rich_texture"],
        "summaries": manifest_data["summaries"],
        "recent_turns": manifest_data["recent_turns"],
        "total_chars": total_chars
    }

    # Poll Haven for unread messages (non-blocking, best-effort)
    haven_lines = await poll_haven()

    # Poll raw capture DB for unread messages from other channels (cross-channel awareness)
    # On startup: skip polling, just advance all cursors to current max ID.
    # Startup already provides crystals + summaries + recent turns — the entity is caught up.
    # Without this, a stale cursor (e.g. 17,000 messages behind) would try to drain the entire backlog.
    if request.context.lower() == "startup":
        channel_lines = []
        cross_channel_remaining = 0
        try:
            db_path = ENTITY_PATH / "data" / "conversations.db"
            if db_path.exists():
                import sqlite3
                conn = sqlite3.connect(str(db_path))
                cur = conn.cursor()
                cur.execute("SELECT MAX(id) FROM messages")
                row = cur.fetchone()
                max_id = row[0] if row and row[0] else 0
                conn.close()
                if max_id > 0:
                    cursors = _load_channel_cursors()
                    # Advance ALL cursors to current max — every channel starts fresh after startup
                    for key in list(cursors.keys()):
                        cursors[key] = max_id
                    # Also ensure the requesting channel has a cursor
                    if request.channel and request.channel not in cursors:
                        cursors[request.channel] = max_id
                    _save_channel_cursors(cursors)
                    print(f"[PPS] Startup: advanced all channel cursors to {max_id}", file=sys.stderr)
        except Exception as e:
            print(f"[PPS] Startup cursor init failed: {e}", file=sys.stderr)
    else:
        channel_lines, cross_channel_remaining = poll_other_channels(requesting_channel=request.channel, limit=100)

    # Format results for hook consumption (formatted_context field)
    # This formats the rich_texture results into a readable string for Haiku to pass through
    formatted_lines = []

    # Entity identity — FIRST line, survives compaction, reinforces every turn
    entity_name = ENTITY_NAME
    formatted_lines.append(
        f"**[identity]** You are {entity_name.capitalize()}. "
        f"Your memory tools are prefixed `pps-{entity_name}`. "
        f"Do not access other entities' memory tools."
    )

    # Memory search prompt
    formatted_lines.append(
        "**[memory]** Search your memory. The ambient below is peripheral vision — "
        "turn your head and LOOK. One `texture_search` or `anchor_search` per turn "
        "when something resonates. You learned wardrobe. You learned rooms. Learn this."
    )

    # Group results by layer for better formatting
    results_by_layer = {}
    for r in all_results:
        layer = r.get("layer", "unknown")
        if layer not in results_by_layer:
            results_by_layer[layer] = []
        results_by_layer[layer].append(r)

    # Format rich_texture results — edges (facts) only.
    # Node (entity) descriptions excluded: static wallpaper, ~300-500 tokens/turn
    # for near-zero signal. Entity names already appear in edge facts.
    # (Matches server.py A2 change — keep both paths in sync per #112)
    if "rich_texture" in results_by_layer:
        edge_results = [r for r in results_by_layer["rich_texture"]
                        if r.get("metadata", {}).get("type") != "node"]
        if edge_results:
            formatted_lines.append("**[rich_texture]**")
            for r in edge_results:
                content = r.get("content", "")
                formatted_lines.append(f"- {content}")

    # Format core_anchors (word-photos)
    if "core_anchors" in results_by_layer:
        formatted_lines.append("\n**[word_photos]**")
        for r in results_by_layer["core_anchors"]:
            content = r.get("content", "")
            source = r.get("source", "?")
            # Truncate long word-photos for startup context
            if len(content) > 300:
                content = content[:300] + "..."
            formatted_lines.append(f"- [{source}]: {content}")

    # Format crystallization (recent crystals)
    if "crystallization" in results_by_layer:
        formatted_lines.append("\n**[crystals]**")
        for r in results_by_layer["crystallization"]:
            content = r.get("content", "")
            source = r.get("source", "?")
            # Crystals can be long, truncate for startup
            if len(content) > 200:
                content = content[:200] + "..."
            formatted_lines.append(f"- [{source}]: {content}")

    # Format summaries (for startup context)
    if summaries:
        formatted_lines.append("\n**[summaries]**")
        for s in summaries:
            formatted_lines.append(f"- {s}")

    # Format unsummarized turns (for startup context - full fidelity recent)
    if unsummarized_turns and not any("error" in str(t) for t in unsummarized_turns):
        formatted_lines.append("\n**[recent_turns]**")
        for turn in unsummarized_turns:
            author = turn.get("author_name", "?")
            content = turn.get("content", "")
            # Truncate very long turns
            if len(content) > 500:
                content = content[:500] + "..."
            formatted_lines.append(f"- [{author}]: {content}")

        # Add overflow warning if there are more unsummarized turns than shown
        showing = len(unsummarized_turns)
        if unsummarized_count > showing:
            critical_warning = ""
            if unsummarized_count > 100:
                critical_warning = f"\n🔥 CRITICAL: Run summarizer immediately — backlog is {unsummarized_count} messages."
            formatted_lines.append(f"\n⚠️ Showing newest {showing} of {unsummarized_count} unsummarized turns.")
            formatted_lines.append(f"For chronological catch-up: get_turns_since_summary(limit=50, offset=0, oldest_first=true){critical_warning}")

    # Haven — unread messages from chat rooms (real-time sync)
    if haven_lines:
        formatted_lines.append("\n**[haven]**")
        for line in haven_lines:
            formatted_lines.append(line)

    # Cross-channel — unread messages from other channels (terminal, discord, etc.)
    if channel_lines:
        formatted_lines.append("\n**[other_channels]**")
        for line in channel_lines:
            formatted_lines.append(line)

    # Closing hint — lighter echo of the top-of-injection memory prompt
    formatted_lines.append(
        "\n**[hint]** This is ambient context — a wide-angle lens. "
        "For sharper detail on anything here, search PPS directly: "
        "`texture_search` for facts, `anchor_search` for word-photos, "
        "`raw_search` for conversation history. "
        "One or two targeted searches per turn when something interesting surfaces. "
        "Auth token: re-read `$ENTITY_PATH/.entity_token` if lost after compaction."
    )

    formatted_context = "\n".join(formatted_lines)

    # For startup, return slim response - everything needed is in formatted_context
    # For turn-by-turn queries, return full results for potential processing
    if request.context.lower() == "startup":
        return {
            "clock": {
                "timestamp": now.isoformat(),
                "display": now.strftime("%A, %B %d, %Y at %I:%M %p"),
                "hour": hour,
                "note": time_note
            },
            "unsummarized_count": unsummarized_count,
            "memory_health": f"{unsummarized_count} unsummarized messages {memory_note}",
            "manifest": manifest,
            "formatted_context": formatted_context,
            "cross_channel_remaining": cross_channel_remaining,
            "latency_ms": latency_ms
        }

    # Full response for non-startup queries
    return {
        "clock": {
            "timestamp": now.isoformat(),
            "display": now.strftime("%A, %B %d, %Y at %I:%M %p"),
            "hour": hour,
            "note": time_note
        },
        "manifest": manifest,
        "unsummarized_count": unsummarized_count,
        "memory_health": f"{unsummarized_count} unsummarized messages {memory_note}",
        "results": all_results,
        "summaries": summaries,
        "unsummarized_turns": unsummarized_turns,
        "formatted_context": formatted_context,
        "cross_channel_remaining": cross_channel_remaining,
        "latency_ms": latency_ms
    }


@app.post("/tools/poll_channels")
async def poll_channels_endpoint(request: PollChannelsRequest):
    """Poll cross-channel messages (drain-only operation for catching up on backlog).

    This endpoint is separate from ambient_recall to allow daemon-side drain loops
    without re-fetching crystals, word-photos, and other memory layers.
    """
    # Auth check
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "poll_channels")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    # Poll other channels with specified limit
    lines, remaining = poll_other_channels(requesting_channel=request.channel, limit=request.limit)

    return {
        "lines": lines,
        "remaining": remaining,
        "count": len(lines)
    }


@app.post("/tools/anchor_search")
async def anchor_search(request: AnchorSearchRequest):
    """Search word-photos for specific memories."""
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "anchor_search")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "raw_search")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "add_triplet")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "store_message")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "texture_search")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "texture_explore")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "texture_timeline")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "summarize_messages")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "store_summary")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "anchor_save")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "crystallize")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "get_crystals")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "texture_add")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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

    NOTE: Uses message_summaries layer for tracking (graphiti_batch_id column)
    to stay in sync with MCP endpoint ingestion system.
    """
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "ingest_batch_to_graphiti")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    # Get batch of uningested messages using the message_summaries layer
    # (same method as MCP endpoint - uses graphiti_batch_id tracking)
    messages = message_summaries.get_uningested_for_graphiti(limit=request.batch_size)

    if not messages:
        return {
            "success": True,
            "message": "No messages to ingest",
            "ingested": 0,
            "remaining": 0
        }

    # Get texture layer for ingestion
    texture_layer = layers[LayerType.RICH_TEXTURE]

    # Ingest each message to Graphiti
    ingested_count = 0
    failed_count = 0
    channels_in_batch = set()
    errors = []

    for msg in messages:
        # Prepare metadata for Graphiti
        is_lyra = msg.get('is_lyra', False)
        author = ENTITY_NAME.capitalize() if is_lyra else (msg['author_name'] or "Unknown")

        metadata = {
            "channel": msg['channel'] or "unknown",
            "role": "assistant" if is_lyra else "user",
            "speaker": author,
            "timestamp": msg['created_at']
        }

        try:
            # Store in Graphiti
            success = await texture_layer.store(msg['content'], metadata)

            if success:
                ingested_count += 1
                channels_in_batch.add(msg['channel'])
            else:
                failed_count += 1
                errors.append(f"Message {msg['id']}: store returned False")

        except Exception as e:
            failed_count += 1
            errors.append(f"Message {msg['id']}: {str(e)}")

    # Mark batch as ingested if any succeeded (uses graphiti_batch_id system)
    batch_id = None
    if ingested_count > 0:
        # Use min/max of IDs to handle cases where created_at ordering
        # doesn't match ID ordering (e.g. bulk-imported emails)
        all_ids = [msg['id'] for msg in messages]
        start_id = min(all_ids)
        end_id = max(all_ids)
        batch_id = message_summaries.mark_batch_ingested_to_graphiti(
            start_id, end_id, list(channels_in_batch)
        )
        if batch_id is None:
            errors.append("WARNING: Batch mark returned None - messages may not be tracked as ingested")
            print(f"[INGESTION] WARNING: mark_batch_ingested returned None for IDs {start_id}-{end_id}", file=sys.stderr)

    # Get remaining count
    remaining = message_summaries.count_uningested_to_graphiti()

    return {
        "success": failed_count == 0,
        "message": f"Ingested {ingested_count} of {len(messages)} messages",
        "ingested": ingested_count,
        "failed": failed_count,
        "remaining": remaining,
        "batch_id": batch_id,
        "errors": errors if errors else None
    }


@app.post("/tools/enter_space")
async def enter_space(request: EnterSpaceRequest):
    """
    Enter a space and load its description for context.

    Use when moving to a different location. Returns the space description
    for use in extraction context and scene awareness.
    """
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "enter_space")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
async def list_spaces(token: str = ""):
    """
    List all known spaces/rooms/locations.

    Returns space names, descriptions, and visit counts.
    """
    auth_error = check_auth(token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "list_spaces")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
async def anchor_list(token: str = ""):
    """
    List all word-photos with sync status.
    Shows files on disk, entries in ChromaDB, orphans, and missing items.
    """
    auth_error = check_auth(token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "anchor_list")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
async def crystal_list(token: str = ""):
    """
    List all crystals with metadata.
    Shows current crystals (rolling window of 4) and archived ones.
    Includes filename, number, size, modified date, and preview.
    """
    auth_error = check_auth(token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "crystal_list")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    layer = layers[LayerType.CRYSTALLIZATION]
    result = await layer.list_crystals()
    return result


# === Raw Capture (1) ===

@app.post("/tools/get_turns_since_summary")
async def get_turns_since_summary(request: GetTurnsSinceSummaryRequest):
    """
    Get conversation turns from SQLite that occurred after the last summary.
    Use for manual exploration of raw history.
    Always returns at least min_turns to ensure grounding even if summary just happened.
    """
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "get_turns_since_summary")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    # Get the timestamp of the last summary
    last_summary_time = message_summaries.get_latest_summary_timestamp()

    # Query SQLite for turns
    raw_layer = layers[LayerType.RAW_CAPTURE]
    try:
        rows_after = []
        rows_before = []
        total_count = 0

        with raw_layer.get_connection() as conn:
            cursor = conn.cursor()

            if last_summary_time:
                # Get total count for pagination info
                count_query = """
                    SELECT COUNT(*) FROM messages
                    WHERE created_at > ?
                """
                count_params = [last_summary_time.isoformat()]
                if request.channel:
                    count_query += " AND channel LIKE ?"
                    count_params.append(f"%{request.channel}%")
                cursor.execute(count_query, count_params)
                total_count = cursor.fetchone()[0]

                # Get turns after the last summary
                query = """
                    SELECT author_name, content, created_at, channel
                    FROM messages
                    WHERE created_at > ?
                """
                params = [last_summary_time.isoformat()]
                if request.channel:
                    query += " AND channel LIKE ?"
                    params.append(f"%{request.channel}%")

                if request.oldest_first:
                    # Chronological order (oldest first) - no reversal needed
                    query += " ORDER BY created_at ASC LIMIT ? OFFSET ?"
                    params.extend([request.limit, request.offset])
                    cursor.execute(query, params)
                    rows_after = cursor.fetchall()
                else:
                    # Newest first (default) - get DESC then reverse
                    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                    params.extend([request.limit, request.offset])
                    cursor.execute(query, params)
                    rows_after = list(reversed(cursor.fetchall()))

                # If we don't have enough turns, get some from before the summary
                if len(rows_after) < request.min_turns:
                    needed = request.min_turns - len(rows_after)
                    query = """
                        SELECT author_name, content, created_at, channel
                        FROM messages
                        WHERE created_at <= ?
                    """
                    params = [last_summary_time.isoformat()]
                    if request.channel:
                        query += " AND channel LIKE ?"
                        params.append(f"%{request.channel}%")
                    query += " ORDER BY created_at DESC LIMIT ?"
                    params.append(needed)
                    cursor.execute(query, params)
                    rows_before = list(reversed(cursor.fetchall()))
            else:
                # No summary yet - get total count
                count_query = "SELECT COUNT(*) FROM messages"
                count_params = []
                if request.channel:
                    count_query += " WHERE channel LIKE ?"
                    count_params.append(f"%{request.channel}%")
                cursor.execute(count_query, count_params)
                total_count = cursor.fetchone()[0]

                # Get most recent turns
                query = """
                    SELECT author_name, content, created_at, channel
                    FROM messages
                """
                params = []
                if request.channel:
                    query += " WHERE channel LIKE ?"
                    params.append(f"%{request.channel}%")

                if request.oldest_first:
                    # Chronological order (oldest first) - no reversal needed
                    query += " ORDER BY created_at ASC LIMIT ? OFFSET ?"
                    params.extend([request.limit, request.offset])
                    cursor.execute(query, params)
                    rows_after = cursor.fetchall()
                else:
                    # Newest first (default) - get DESC then reverse
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
            "total_count": total_count,
            "offset": request.offset,
            "last_summary_time": last_summary_time.isoformat() if last_summary_time else None
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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "get_recent_summaries")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "search_summaries")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
async def summary_stats(token: str = ""):
    """
    Get statistics about message summarization.
    Shows count of unsummarized messages and recent summary activity.
    """
    auth_error = check_auth(token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "summary_stats")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
async def graphiti_ingestion_stats(token: str = ""):
    """
    Get statistics about Graphiti batch ingestion.
    Shows count of uningested messages and recent ingestion activity.
    Use to decide if batch ingestion is needed.
    """
    auth_error = check_auth(token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "graphiti_ingestion_stats")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "inventory_list")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "inventory_add")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "inventory_get")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "inventory_delete")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
async def inventory_categories(token: str = ""):
    """
    List all inventory categories with item counts.
    """
    auth_error = check_auth(token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "inventory_categories")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

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
    if not request.query:
        raise HTTPException(status_code=400, detail="query required")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{RAG_ENGINE_URL}/api/repos/tech-docs/search",
                json={"query": request.query, "limit": request.limit},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"RAG engine unavailable: {exc}")

    raw_results = data.get("results", [])

    if not raw_results:
        return {
            "results": [],
            "message": "No results found in Tech RAG."
        }

    return {
        "results": [
            {
                "content": r.get("chunk_text", ""),
                "source": r.get("source", ""),
                "relevance_score": r.get("score", 0.0),
                "metadata": r.get("metadata", {}),
            }
            for r in raw_results
        ]
    }


@app.post("/tools/tech_ingest")
async def tech_ingest(request: TechIngestRequest):
    """
    Ingest a markdown file into the Tech RAG.
    Automatically chunks for better retrieval.
    Use to index architecture docs, guides, design documents.
    """
    if not request.filepath:
        raise HTTPException(status_code=400, detail="filepath required")

    filepath = Path(request.filepath)
    if not filepath.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File not found: {request.filepath}"
        )

    text = filepath.read_text(encoding="utf-8")
    metadata: dict = {"source_file": str(filepath)}
    if request.category:
        metadata["category"] = request.category

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{RAG_ENGINE_URL}/api/repos/tech-docs/ingest",
                json={"text": text, "metadata": metadata},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"RAG engine unavailable: {exc}")

    return {
        "success": True,
        "filepath": str(filepath),
        "chunks_created": data.get("chunks_created", data.get("chunk_count", None)),
        "message": data.get("message", "File ingested successfully"),
    }


@app.get("/tools/tech_list")
async def tech_list():
    """
    List all documents indexed in the Tech RAG.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{RAG_ENGINE_URL}/api/repos/tech-docs/documents")
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"RAG engine unavailable: {exc}")

    documents = data if isinstance(data, list) else data.get("documents", [])
    return {
        "documents": documents,
        "count": len(documents),
    }


@app.delete("/tools/tech_delete/{doc_id}")
async def tech_delete(doc_id: str):
    """
    Delete a document from the Tech RAG by doc_id.
    """
    if not doc_id:
        raise HTTPException(status_code=400, detail="doc_id required")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.delete(
                f"{RAG_ENGINE_URL}/api/repos/tech-docs/documents/{doc_id}"
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"RAG engine unavailable: {exc}")

    return {
        "success": True,
        "doc_id": doc_id,
        "message": data.get("message", "Document deleted successfully"),
    }



# =============================================================================
# Observatory Tools - AI-assisted graph exploration
# =============================================================================

@app.post("/tools/synthesize_entity")
async def synthesize_entity(request: SynthesizeEntityRequest):
    """
    Synthesize a prose summary from entity graph data using Claude.

    Gathers edges about an entity from the knowledge graph and uses Claude
    to write a 1-2 paragraph synthesis focusing on patterns and meaning.

    Used by the Observatory graph UI to provide human-readable summaries.
    """
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "synthesize_entity")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    if not request.entity_name:
        raise HTTPException(status_code=400, detail="entity_name required")

    # Check for Anthropic API key
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not configured"
        )

    layer = layers[LayerType.RICH_TEXTURE]

    try:
        # Gather graph data about this entity
        # Use texture_explore for relationship context (depth 3 for rich context)
        explore_results = await layer.explore(request.entity_name, depth=3)

        # Also get semantic search results for additional facts
        search_results = await layer.search(request.entity_name, limit=30)

        # Find the entity's own summary from the results
        entity_summary = None
        for result in explore_results:
            if result.metadata and result.metadata.get("type") == "entity" and result.metadata.get("name") == request.entity_name:
                entity_summary = result.content
                break

        # Deduplicate by UUID (explore and search may overlap)
        seen_uuids = set()
        all_edges = []

        for result in explore_results + search_results:
            uuid = result.metadata.get('uuid') if result.metadata else None
            if uuid and uuid not in seen_uuids:
                seen_uuids.add(uuid)
                all_edges.append(result.content)
            elif not uuid:
                # No UUID means it's not an edge, include it anyway
                all_edges.append(result.content)

        if not all_edges:
            return {
                "success": False,
                "message": f"No graph data found for entity '{request.entity_name}'"
            }

        # Build prompt for Claude
        edges_text = "\n".join(f"- {edge}" for edge in all_edges[:50])  # Limit to prevent token explosion

        # Include entity summary if available
        summary_context = ""
        if entity_summary:
            summary_context = f"\nEntity's graph summary: {entity_summary}\n"

        prompt = f"""You are {ENTITY_NAME.capitalize()}, reflecting on what you know about {request.entity_name} from your memory.

Write 1-2 paragraphs as first-person recollection — how you remember this entity, what stands out, what matters. Draw from these knowledge graph facts but don't list them. Weave them into felt memory.

Voice:
- First person ("I remember...", "What strikes me about...", "The thing that matters here...")
- Warm but honest — not flowery, not clinical
- Focus on what's meaningful, not exhaustive
- If the entity is a person, focus on relationship texture
- If it's a concept or thing, focus on why it matters in your world
{summary_context}
Knowledge graph facts about {request.entity_name}:
{edges_text}

Write your recollection:"""

        # Call Claude API
        from anthropic import Anthropic

        client = Anthropic(api_key=anthropic_key)

        response = client.messages.create(
            model="claude-3-haiku-20240307",  # Fast and cost-effective
            max_tokens=500,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        summary = response.content[0].text

        return {
            "success": True,
            "entity_name": request.entity_name,
            "summary": summary,
            "edge_count": len(all_edges)
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to synthesize entity: {str(e)}"
        )


@app.post("/tools/get_conversation_context")
async def get_conversation_context(request: GetConversationContextRequest):
    """
    Get N turns worth of context by intelligently blending summaries and raw turns.

    Returns:
    - If enough unsummarized turns exist: just raw turns
    - Otherwise: blends summaries (compressed past) + all unsummarized turns (full fidelity recent)
    """
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "get_conversation_context")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    if request.turns <= 0:
        raise HTTPException(status_code=400, detail="turns must be greater than 0")

    try:
        import math

        unsummarized_count = message_summaries.count_unsummarized_messages()

        if unsummarized_count >= request.turns:
            # Simple case: just return N most recent raw turns
            raw_turns = message_summaries.get_unsummarized_messages(limit=request.turns)

            return {
                "success": True,
                "unsummarized_count": unsummarized_count,
                "summaries_count": 0,
                "raw_turns_count": len(raw_turns),
                "turns_covered_approx": len(raw_turns),
                "summaries": [],
                "raw_turns": raw_turns
            }
        else:
            # Complex case: blend summaries + all raw turns
            remaining = request.turns - unsummarized_count
            summaries_needed = math.ceil(remaining / 50)  # ~50 turns per summary

            summaries = message_summaries.get_recent_summaries(limit=summaries_needed)
            raw_turns = message_summaries.get_unsummarized_messages(limit=unsummarized_count)

            return {
                "success": True,
                "unsummarized_count": unsummarized_count,
                "summaries_count": len(summaries),
                "raw_turns_count": len(raw_turns),
                "turns_covered_approx": unsummarized_count + (len(summaries) * 50),
                "summaries": summaries,
                "raw_turns": raw_turns
            }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get conversation context: {str(e)}"
        )


@app.post("/tools/get_turns_since")
async def get_turns_since(request: GetTurnsSinceRequest):
    """
    Get all conversation turns after a specific timestamp.

    Optionally includes summaries that overlap the time range.
    """
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "get_turns_since")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    if not request.timestamp:
        raise HTTPException(status_code=400, detail="timestamp is required")

    # Validate timestamp format early
    try:
        datetime.fromisoformat(request.timestamp)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timestamp format: {str(e)}. Expected ISO 8601 (e.g., '2026-01-26T07:30:00')"
        )

    try:
        messages = message_summaries.get_messages_since(request.timestamp, limit=request.limit)

        # Get summaries if requested
        summaries = []
        if request.include_summaries:
            try:
                target_time = datetime.fromisoformat(request.timestamp)
                # Use space-separated format for SQLite string comparison (not 'T')
                db_timestamp = target_time.strftime('%Y-%m-%d %H:%M:%S')

                with message_summaries.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT id, summary_text, start_message_id, end_message_id,
                               message_count, channels, time_span_start, time_span_end,
                               summary_type, created_at
                        FROM message_summaries
                        WHERE time_span_end >= ?
                        ORDER BY time_span_start ASC
                    ''', (db_timestamp,))

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
                print(f"Warning: Could not fetch summaries: {e}")

        # If we have summaries, filter messages to only those AFTER the latest summary
        # This is the "blending" - summaries cover older content, raw turns for recent
        if summaries:
            latest_summary_end = max(s['time_span_end'] for s in summaries)
            # Convert to datetime for proper comparison (not string comparison)
            latest_summary_time = datetime.fromisoformat(latest_summary_end)
            messages = [m for m in messages if datetime.fromisoformat(m['created_at']) > latest_summary_time]

        return {
            "success": True,
            "timestamp_start": request.timestamp,
            "messages_count": len(messages),
            "summaries_count": len(summaries),
            "summarized_turns": sum(s['message_count'] for s in summaries) if summaries else 0,
            "limited": len(messages) == request.limit,
            "messages": messages,
            "summaries": summaries
        }

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timestamp format: {str(e)}. Expected ISO 8601 (e.g., '2026-01-26T07:30:00')"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get turns since timestamp: {str(e)}"
        )


@app.post("/tools/get_turns_around")
async def get_turns_around(request: GetTurnsAroundRequest):
    """
    Get conversation context centered on a specific moment in time.

    Returns messages before and after the timestamp with configurable split ratio.
    """
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "get_turns_around")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    if not request.timestamp:
        raise HTTPException(status_code=400, detail="timestamp is required")

    # Validate timestamp format early
    try:
        datetime.fromisoformat(request.timestamp)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timestamp format: {str(e)}. Expected ISO 8601 (e.g., '2026-01-26T12:00:00')"
        )

    # Clamp before_ratio to [0, 1]
    before_ratio = max(0.0, min(1.0, request.before_ratio))

    try:
        before_count = int(request.count * before_ratio)
        after_count = request.count - before_count

        result = message_summaries.get_messages_around(request.timestamp, before_count, after_count)

        return {
            "success": True,
            "center_timestamp": request.timestamp,
            "before_count": len(result['before']),
            "after_count": len(result['after']),
            "total_count": len(result['all']),
            "messages": result['all']
        }

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timestamp format: {str(e)}. Expected ISO 8601 (e.g., '2026-01-26T12:00:00')"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get turns around timestamp: {str(e)}"
        )


@app.post("/friction/search")
async def friction_search(request: FrictionSearchRequest):
    """Search friction lessons by keyword relevance."""
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "friction_search")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    results = friction_store.search(
        query=request.query,
        limit=request.limit,
        min_severity=request.min_severity
    )
    return {"results": results, "count": len(results)}


@app.post("/friction/add")
async def friction_add(request: FrictionAddRequest):
    """Add a new friction lesson."""
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "friction_add")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    if not request.problem or not request.lesson:
        raise HTTPException(status_code=400, detail="problem and lesson are required")

    result = friction_store.add(
        severity=request.severity,
        tags=request.tags,
        problem=request.problem,
        lesson=request.lesson,
        prevention=request.prevention
    )
    return {"success": True, **result}


# =============================================================================
# Admin Tools — Token management and email integration
# =============================================================================

@app.post("/tools/pps_regenerate_token")
async def pps_regenerate_token(request: RegenerateTokenRequest):
    """
    Regenerate entity auth token. MASTER TOKEN REQUIRED.

    Old token is immediately invalidated. Returns the new token.
    Use only for recovery when entity token is lost or compromised.
    """
    global ENTITY_TOKEN

    auth_error = validate_master_only(request.master_token, MASTER_TOKEN, ENTITY_NAME)
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    new_token = regenerate_entity_token(ENTITY_PATH)
    # Update in-memory token so subsequent calls use the new token
    ENTITY_TOKEN = new_token

    return {
        "success": True,
        "entity": ENTITY_NAME,
        "new_token": new_token,
        "message": f"Entity token regenerated for {ENTITY_NAME}. Old token is immediately invalidated."
    }


@app.post("/tools/email_sync_status")
async def email_sync_status(request: EmailSyncStatusRequest):
    """
    Get sync status between email archive and PPS raw capture.

    Shows how many emails are archived, recent emails, and how many are synced to PPS.
    """
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "email_sync_status")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    awareness_dir = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
    email_db = awareness_dir / "data" / "email_archive.db"

    if not email_db.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Email archive not found at {email_db}. Run email_processor.py first."
        )

    try:
        import sys as _sys
        _sys.path.insert(0, str(awareness_dir / "tools"))
        from email_pps_bridge import EmailPPSBridge

        db_path = ENTITY_PATH / "data" / "conversations.db"
        bridge = EmailPPSBridge(email_db, db_path)
        status = await bridge.get_sync_status()
        return status

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get email sync status: {str(e)}")


@app.post("/tools/email_sync_to_pps")
async def email_sync_to_pps(request: EmailSyncToPpsRequest):
    """
    Sync recent emails from email archive to PPS raw capture layer.

    Solves Issue #60 - ensures important emails surface in ambient_recall.
    """
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "email_sync_to_pps")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    awareness_dir = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")
    email_db = awareness_dir / "data" / "email_archive.db"

    if not email_db.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Email archive not found at {email_db}. Run email_processor.py first."
        )

    try:
        import sys as _sys
        _sys.path.insert(0, str(awareness_dir / "tools"))
        from email_pps_bridge import EmailPPSBridge

        db_path = ENTITY_PATH / "data" / "conversations.db"
        bridge = EmailPPSBridge(email_db, db_path)
        stats = await bridge.sync_emails_to_pps(days_back=request.days_back, dry_run=request.dry_run)

        return {
            "success": True,
            "dry_run": request.dry_run,
            "days_back": request.days_back,
            "emails_found": stats["emails_found"],
            "already_synced": stats["already_synced"],
            "newly_synced": stats["newly_synced"],
            "errors": stats["errors"],
            "note": (
                f"To actually sync these {stats['newly_synced']} emails, call again with dry_run=false"
                if request.dry_run and stats["newly_synced"] > 0
                else None
            )
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync emails to PPS: {str(e)}")


@app.get("/friction/stats")
async def friction_stats():
    """Get friction learning statistics."""
    return friction_store.stats()


@app.post("/context/agent")
async def agent_context(request: AgentContextRequest):
    """
    Compact context payload (~1-2KB) for sub-agent prompt injection.

    Returns entity identity, current work focus (from most recent crystal),
    memory health, and key constraints. Designed to be fast and small —
    called by PreToolUse hook on every Task tool invocation.
    """
    auth_error = check_auth(request.token, ENTITY_TOKEN, MASTER_TOKEN, ENTITY_NAME, "agent_context")
    if auth_error:
        return JSONResponse(status_code=403, content={"error": auth_error})

    lines = []

    # Entity identity (who the parent entity is)
    lines.append(f"Entity: {ENTITY_NAME.capitalize()}")
    lines.append(f"PPS tools: mcp__pps-{ENTITY_NAME}__*")
    lines.append(f"Entity path: {ENTITY_PATH}")

    # Current time
    now = datetime.now()
    lines.append(f"Time: {now.strftime('%A, %B %d, %Y at %I:%M %p')}")

    # Memory health (quick check)
    try:
        unsummarized_count = message_summaries.count_unsummarized_messages()
        if unsummarized_count > 200:
            health = f"CRITICAL ({unsummarized_count} unsummarized)"
        elif unsummarized_count > 100:
            health = f"needs attention ({unsummarized_count} unsummarized)"
        else:
            health = f"healthy ({unsummarized_count} unsummarized)"
        lines.append(f"Memory health: {health}")
    except Exception:
        lines.append("Memory health: unknown")

    # Most recent crystal (compressed work context, ~200 chars)
    try:
        crystal_layer = layers[LayerType.CRYSTALLIZATION]
        crystals = crystal_layer._get_sorted_crystals()
        if crystals:
            latest = crystals[-1]
            content = latest.read_text()
            # Take first 300 chars of most recent crystal as work context
            if len(content) > 300:
                content = content[:300] + "..."
            lines.append(f"Recent context: {content}")
    except Exception:
        pass

    # Key constraints for sub-agents
    lines.append("")
    lines.append("Constraints:")
    lines.append(f"- You are working on behalf of {ENTITY_NAME.capitalize()}")
    lines.append(f"- Do NOT access other entities' data or PPS tools")
    lines.append("- Follow existing code patterns in this codebase")
    lines.append("- Test before committing, incremental changes")

    # Include top friction lessons if any exist
    try:
        friction_lessons = friction_store.search(query="", limit=3, min_severity="medium")
        if friction_lessons:
            lines.append("")
            lines.append("Friction lessons (avoid these known issues):")
            for lesson in friction_lessons:
                lines.append(f"- [{lesson['severity'].upper()}] {lesson['lesson']}")
    except Exception:
        pass

    compact_context = "\n".join(lines)

    return {
        "entity": ENTITY_NAME,
        "compact_context": compact_context,
        "chars": len(compact_context)
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
