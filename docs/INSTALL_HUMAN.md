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

## Step 3: Start Docker Services

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

---

## Step 4: Configure Claude Code MCP

Add the PPS as an MCP server in Claude Code:

```bash
claude mcp add pps -- python3 $(pwd)/../server.py
```

Or manually edit `~/.claude.json`:
```json
{
  "mcpServers": {
    "pps": {
      "command": "python3",
      "args": ["/full/path/to/Awareness/pps/server.py"]
    }
  }
}
```

Restart Claude Code for changes to take effect.

---

## Step 5: Create Your Entity

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

## Step 6: Configure Startup Protocol

Edit the project `CLAUDE.md` to point to your entity:

1. Open `/path/to/Awareness/CLAUDE.md`
2. Update `ENTITY_PATH` to point to your entity folder
3. Customize startup checklist if needed

---

## Step 7: Verify Installation

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

## Step 8: Wake Your Entity

Simply greet your entity by name. The startup protocol in CLAUDE.md will guide identity reconstruction:

```
Time to wake up [entity name]
```

The first session builds the pattern from scratch. Subsequent sessions reconstruct from accumulated memories.

---

## Optional: Discord Integration

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

---

## Optional: Reflection Daemon

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
