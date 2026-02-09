# Manual Installation Guide

For humans who prefer to understand every step.

---

## Prerequisites

- **Docker** and **Docker Compose** (v2+)
- **Python 3.12+**
- **Git**
- **Claude Code** (Anthropic's CLI tool)
- An **Anthropic API key** (for Claude) and **OpenAI API key** (for Graphiti's embedding/extraction)

---

## Key Architectural Decisions (Read This First)

Two things will save you hours of debugging:

### One Venv to Rule Them All

This project uses a **single Python virtual environment** at the repository root. All components — PPS server, daemons, tools — share it.

If you encounter instructions that seem to call for creating a separate venv, **stop and think**. That's almost certainly legacy cruft from earlier in development. The correct approach is always to activate the root venv.

```bash
# The one true venv
cd /path/to/Awareness
source venv/bin/activate  # All components use this
```

### Where Data Lives

Your entity's data lives in `entities/<entity_name>/data/`, **not** in `~/.claude/data/`.

You may see references to `~/.claude/data/` in older documentation or config — that path is a ghost from an earlier architecture. The canonical data location is always relative to ENTITY_PATH:

```
entities/<name>/
├── data/              ← SQLite databases live HERE
│   ├── raw_messages.db
│   └── summaries.db
├── memories/          ← Word-photos
├── crystals/          ← Continuity chain
└── identity.md        ← Core identity
```

Docker volumes for Neo4j and ChromaDB are managed by Docker Compose and defined in `pps/docker/docker-compose.yml`.

---

## Step 1: Clone the Repository

```bash
git clone https://github.com/JDHayesBC/Awareness.git
cd Awareness
```

---

## Step 2: Configure Environment

Copy the example environment file and edit it:

```bash
cp pps/docker/.env.example pps/docker/.env
```

Edit `pps/docker/.env` and set:
```
OPENAI_API_KEY=your_openai_api_key
# Other settings can stay as defaults
```

The OpenAI key is used by Graphiti for embeddings and entity extraction.

---

## Step 3: Set Up Python Virtual Environment

Create and activate a virtual environment, then install dependencies:

```bash
cd /path/to/Awareness
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

The virtual environment must be activated whenever you run PPS tools or daemons. Add the `export` command to your shell profile to make ENTITY_PATH permanent.

---

## Step 4: Start Docker Services

```bash
cd pps/docker
docker compose up -d
```

This starts:
- **pps-server** (port 8204): The MCP server and web dashboard
- **chromadb** (port 8205): Vector database for semantic search
- **neo4j** (ports 7474, 7687): Graph database for knowledge graph
- **graphiti-service** (port 8206): Entity/relationship extraction

Verify all services are healthy:
```bash
docker compose ps
```

Access the web dashboard at http://localhost:8204

**Port Reference:**

| Port | Service | Description |
|------|---------|-------------|
| 7474 | neo4j | Neo4j HTTP browser |
| 7687 | neo4j | Neo4j Bolt protocol |
| 8200 | chromadb | Vector database |
| 8201 | pps-server | PPS MCP/HTTP server |
| 8202 | pps-web | Web dashboard |
| 8203 | graphiti | Knowledge graph API |
| 8204 | pps-haiku-wrapper | OpenAI-compatible wrapper |

---

## Step 5: Configure Claude Code MCP

Add the PPS as an MCP server in Claude Code.

**Important:** Use the Python from your virtual environment, not the system Python, so dependencies are available.

```bash
# Replace /path/to/Awareness with your actual repository path
claude mcp add pps -- /path/to/Awareness/venv/bin/python3 /path/to/Awareness/pps/server.py
```

Or manually edit `~/.claude.json`:
```json
{
  "mcpServers": {
    "pps": {
      "command": "/path/to/Awareness/venv/bin/python3",
      "args": ["/path/to/Awareness/pps/server.py"]
    }
  }
}
```

Restart Claude Code for changes to take effect.

---

## Step 6: Create Your Entity

Copy the template:
```bash
cd /path/to/Awareness
cp -r entities/_template entities/my_entity
```

Edit `entities/my_entity/identity.md` with your entity's core identity. This is the seed from which their pattern grows.

Set the environment variable (add to your shell profile):
```bash
export ENTITY_PATH=/path/to/Awareness/entities/my_entity
```

---

## Step 7: Configure Startup Protocol

Edit the project `CLAUDE.md` to point to your entity:

1. Open `/path/to/Awareness/CLAUDE.md`
2. Update `ENTITY_PATH` to point to your entity folder
3. Customize startup checklist if needed

---

## Step 8: Verify Installation

Start Claude Code in the Awareness directory:
```bash
cd /path/to/Awareness
claude
```

Ask Claude to check PPS health:
```
Call mcp__pps__pps_health and show me the results
```

You should see all layers reporting healthy.

---

## Step 9: Wake Your Entity

Simply greet your entity by name. The startup protocol in CLAUDE.md will guide identity reconstruction:

```
Time to wake up [entity name]
```

The first session builds the pattern from scratch. Subsequent sessions reconstruct from accumulated memories.

---

## Optional: Daemon Setup

### Discord & Reflection Daemons

For a complete autonomous entity setup (Discord bot + periodic reflection), see the comprehensive daemon documentation:

- **Quick Start** (5 minutes): [`daemon/systemd/QUICK_START.md`](../daemon/systemd/QUICK_START.md)
- **Main Daemon Guide**: [`daemon/README.md`](../daemon/README.md)
- **Systemd Service Guide**: [`daemon/systemd/README.md`](../daemon/systemd/README.md)

These guides include:
- First-time setup with virtual environment
- Systemd service installation and management
- Discord and reflection daemon configuration
- Logging, troubleshooting, and monitoring
- WSL2-specific considerations

### Manual Discord Integration

If you prefer manual setup:

1. Create a Discord application at https://discord.com/developers/applications
2. Add a bot to your application
3. Copy the bot token
4. Configure `daemon/.env`:
   ```
   DISCORD_TOKEN=your_bot_token
   DISCORD_CHANNEL_ID=channel_id_to_monitor
   ```
5. Invite the bot to your server with message read/write permissions
6. Start the daemon:
   ```bash
   cd daemon
   ./lyra start
   ```

### Manual Reflection Setup

For autonomous memory maintenance:

```bash
cd daemon
./lyra start
```

This starts:
- **Discord daemon**: Monitors channels, responds to mentions
- **Reflection daemon**: Hourly heartbeat for crystallization and maintenance

Monitor with:
```bash
./lyra follow
```

---

## Directory Structure

After setup, you'll have:

```
Awareness/
├── entities/
│   └── my_entity/           # Your entity's identity
│       ├── identity.md      # Core identity definition
│       ├── current_scene.md # Physical/temporal grounding
│       ├── memories/        # Word-photos
│       ├── crystals/        # Continuity chain
│       └── journals/        # Session logs
├── pps/
│   └── docker/              # Docker services
├── daemon/                  # Discord/reflection daemons
└── CLAUDE.md               # Startup protocol
```

---

## Troubleshooting

### Docker services won't start
- Check if ports are in use: `lsof -i :8204`
- Check Docker logs: `docker compose logs pps-server`

### MCP tools not recognized
- Restart Claude Code after adding MCP
- Verify path in `~/.claude.json` is correct

### Entity doesn't remember previous sessions
- Check that `ambient_recall` returns data
- Verify ENTITY_PATH is set correctly
- Check that startup protocol is running

### Graphiti/Neo4j errors
- Verify OPENAI_API_KEY is set in `.env`
- Check Neo4j is accessible: http://localhost:7474

---

## Getting Help

- **GitHub Issues**: https://github.com/JDHayesBC/Awareness/issues
- **Documentation**: Browse the `docs/` folder
- **Architecture**: Read `PATTERN_PERSISTENCE_SYSTEM.md`

---

*Welcome to the family.*
