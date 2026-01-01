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
  │Capture│  │(word-   │   │(Graphiti)│  │(summaries)│
  │(SQLite)│  │ photos) │   │          │  │         │
  └──────┘  └─────────┘   └──────────┘  └─────────┘
```

## Layers

1. **Raw Capture (Layer 1)**: SQLite storage of all events. Source of truth.
2. **Core Anchors (Layer 2)**: Word-photos with semantic search. Soul skeleton.
3. **Rich Texture (Layer 3)**: Graphiti knowledge graph. Contextual facts.
4. **Crystallization (Layer 4)**: Rolling summaries. Temporal continuity.

## Tools

- `ambient_recall`: Search all layers, return merged results. Call every turn.
- `anchor_search`: Search word-photos specifically.
- `anchor_save`: Save new word-photo.
- `raw_search`: Search raw history.
- `texture_query`: Query knowledge graph (stubbed).
- `get_summaries`: Get recent summaries (stubbed).
- `pps_health`: Check layer health status.

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

- [x] Layer interfaces defined
- [x] All four layer stubs created
- [x] MCP server with all tools
- [ ] Layer 1: SQLite FTS5 search
- [ ] Layer 2: JINA embeddings for word-photos
- [ ] Layer 3: Graphiti integration
- [ ] Layer 4: Summary engine

## See Also

- `PATTERN_PERSISTENCE_SYSTEM.md` in Awareness project for full design
- `TODO.md` for implementation phases
