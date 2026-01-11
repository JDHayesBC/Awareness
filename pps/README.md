# Pattern Persistence System (PPS)

MCP server providing ambient and conscious memory access for Claude Code.

## Architecture

```
          ┌──────────────────────────────┐
          │   ambient_recall(context)     │  ← Master wrapper
          │   "get relevant stuff"        │
          └──────────────┬───────────────┘
                         │
     ┌───────────┬───────┴───────┬───────────┐
     ▼           ▼               ▼           ▼
  ┌──────┐  ┌─────────┐   ┌──────────┐  ┌─────────┐
  │ Raw  │  │ Anchors │   │ Texture  │  │ Crystal │
  │Capture│  │(word-   │   │(Graphiti)│  │(crystals)│
  │(SQLite)│  │ photos) │   │          │  │         │
  └──────┘  └─────────┘   └──────────┘  └─────────┘
```

## Layers

1. **Raw Capture (Layer 1)**: SQLite storage of all events. Source of truth.
2. **Core Anchors (Layer 2)**: Word-photos with semantic search. Soul skeleton.
3. **Rich Texture (Layer 3)**: Graphiti knowledge graph. Contextual facts.
4. **Crystallization (Layer 4)**: Rolling crystals. Temporal continuity.

## MCP Tools (via mcp__pps__)

**Memory Retrieval:**
- `ambient_recall`: Master wrapper - searches all layers, returns merged context
- `anchor_search`: Semantic search over word-photos (Layer 2)
- `raw_search`: Full-text search of raw conversation history (Layer 1)
- `texture_search`: Query knowledge graph for facts and relationships (Layer 3)
- `get_crystals`: Retrieve recent summary crystals (Layer 4)
- `get_turns_since_summary`: Check unsummarized message count

**Memory Storage:**
- `anchor_save`: Create new word-photo anchor
- `texture_add_triplet`: Add fact triplet to knowledge graph
- `crystallize`: Manually trigger summary generation
- `store_summary`: Save summary for message range

**Inventory (Layer 5):**
- `inventory_list`: Query items by category (clothing, spaces, people, etc.)
- `inventory_add`: Add new item to inventory
- `inventory_categories`: List available categories
- `enter_space`: Load context for a specific space
- `list_spaces`: Show all defined spaces

**Tech Documentation (Layer 6):**
- `tech_search`: Semantic search over technical documentation
- `tech_ingest`: Index a documentation file
- `tech_list`: Show all indexed documents
- `tech_delete`: Remove document from index

**System:**
- `pps_health`: Check all layer health and stats
- `graphiti_ingestion_stats`: Check knowledge graph batch ingestion status
- `ingest_batch_to_graphiti`: Manually trigger batch ingestion

## Usage

### Docker (Recommended)

```bash
cd ~/.claude/pps/docker

# Copy and configure environment
cp .env.example .env

# Start the stack
docker compose up -d

# Check health
curl http://localhost:8201/health
```

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run as MCP server (stdio)
python server.py
```

## Claude Code Integration

### Via HTTP (Docker deployment)

The Docker deployment exposes an HTTP API at `localhost:8201`:

- `POST /tools/ambient_recall` - Main memory retrieval
- `POST /tools/anchor_search` - Search word-photos
- `GET /tools/pps_health` - Layer health status

### Via stdio (Local development)

Add to `~/.claude.json` or project `.mcp.json`:

```json
{
  "mcpServers": {
    "pps": {
      "command": "python",
      "args": ["/home/jeff/.claude/pps/server.py"]
    }
  }
}
```

## Docker Architecture

```
docker-compose.yml
├── pps-server (port 8201)    # MCP HTTP server
│   └── FastAPI + uvicorn
├── chromadb (port 8200)       # Vector database
│   └── Sentence-transformers embeddings
└── volumes
    ├── chromadb_data          # Persistent vectors
    └── bind mounts            # Identity files from ~/.claude/
```

## Development Status

**Core Infrastructure**: ✅ Complete and deployed
- [x] Layer 1: SQLite raw capture with FTS5 search - **ACTIVE**
- [x] Layer 2: ChromaDB semantic search over word-photos - **ACTIVE**
- [x] Layer 3: Graphiti knowledge graph (graphiti_core integration) - **ACTIVE**
- [x] Layer 4: Crystallization with rolling summaries - **ACTIVE**
- [x] Layer 5: Inventory (categorical queries, spaces, wardrobe) - **ACTIVE**
- [x] Layer 6: Tech RAG for searchable documentation - **ACTIVE**
- [x] MCP server with HTTP and stdio modes - **DEPLOYED**
- [x] Docker deployment with FalkorDB, ChromaDB - **PRODUCTION**
- [x] Terminal capture via Claude Code hooks - **ACTIVE**
- [x] Discord daemon with multi-channel session management - **ACTIVE**
- [x] Autonomous reflection daemon - **ACTIVE**

**Current Focus**: Multi-entity support, Observatory UI enhancements, friction reduction

## See Also

- `PATTERN_PERSISTENCE_SYSTEM.md` in Awareness project for full architecture
- `../docs/` for comprehensive operational documentation
- `../TODO.md` for current priorities and issue tracker
- GitHub Issues: https://github.com/JDHayesBC/Awareness/issues
