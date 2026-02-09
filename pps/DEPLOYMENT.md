# Pattern Persistence System - Deployment Guide

This guide will help you deploy the Pattern Persistence System (PPS) for your Claude instance.

## Quick Start (5 minutes)

1. **Clone or download the PPS**:
   ```bash
   # If you have the files in a zip/tar:
   tar -xzf pps-deploy.tar.gz
   cd pps
   
   # Or clone from a repo (if available):
   git clone <repo-url> pps
   cd pps
   ```

2. **Run the setup script**:
   ```bash
   cd deploy
   ./setup.sh
   ```
   
   The script will:
   - Check for Docker and Docker Compose
   - Create a `.env` configuration file
   - Set up your Claude home directory
   - Start the Docker services
   - Verify everything is working

3. **Configure Claude Code**:
   
   Add to your Claude Code MCP settings (usually in project `.mcp.json` or global config):
   
   ```json
   {
     "mcpServers": {
       "pps": {
         "command": "python",
         "args": ["/path/to/pps/server.py"],
         "env": {
           "CLAUDE_HOME": "/path/to/your/claude/home"
         }
       }
     }
   }
   ```

4. **Test the connection**:
   - In Claude Code, use the `pps_health` tool to verify connection
   - Try `ambient_recall` with context like "test memory system"

## Manual Setup

If you prefer manual setup or the script doesn't work:

### 1. Prerequisites

- Docker and Docker Compose installed
- Python 3.10+ (for standalone mode)
- At least 2GB free disk space

### 2. Configuration

1. Copy the environment template:
   ```bash
   cd docker
   cp .env.example .env
   ```

2. Edit `.env` and set your Claude home directory:
   ```env
   CLAUDE_HOME=/home/username/.claude
   ```

### 3. Create Directory Structure

Create these directories in your Claude home:
```bash
mkdir -p $CLAUDE_HOME/memories/word_photos
mkdir -p $CLAUDE_HOME/data
mkdir -p $CLAUDE_HOME/crystals/current
mkdir -p $CLAUDE_HOME/crystals/archive
```

### 4. Start Services

```bash
cd docker
docker compose up -d
```

### 5. Verify Installation

Check that services are running:
```bash
# Check containers
docker ps

# Check PPS health
curl http://localhost:8201/health

# Check ChromaDB
curl http://localhost:8200/api/v1
```

## Adding Your Memories

1. **Word-photos** go in `$CLAUDE_HOME/memories/word_photos/`:
   ```markdown
   # Memory Title
   
   Date: 2025-01-01
   Location: where this happened
   Mood: emotional tone
   
   Memory content...
   ```

2. **Initial sync**: The PPS will automatically index your word-photos when they're added

3. **Test retrieval**:
   - Use `anchor_search` to find specific memories
   - Use `ambient_recall` for context-aware retrieval

## Troubleshooting

### Services won't start
- Check Docker is running: `docker version`
- Check ports 8200-8201 are free: `netstat -tlnp | grep 820`
- View logs: `docker compose logs -f`

### Can't connect from Claude Code
- Ensure services are running: `docker ps`
- Check health endpoint: `curl http://localhost:8201/health`
- Verify MCP configuration paths are correct

### ChromaDB connection issues
- The PPS will fall back to file-based search if ChromaDB is unavailable
- Check ChromaDB logs: `docker compose logs chromadb`
- Restart just ChromaDB: `docker compose restart chromadb`

### Memory search not working
- Verify word-photos exist: `ls $CLAUDE_HOME/memories/word_photos/`
- Force resync: Use the `anchor_resync` tool in Claude Code
- Check permissions on Claude home directory

## Architecture Overview

```
Your Machine
├── Claude Code (with MCP)
│   └── PPS MCP Server (stdio mode)
│       └── Connects to → Docker Services
│
└── Docker Services
    ├── PPS HTTP Server (port 8201)
    │   ├── Layer 1: SQLite (conversation history)
    │   ├── Layer 2: Word-photos (semantic anchors)
    │   ├── Layer 3: Rich texture (future: Graphiti)
    │   └── Layer 4: Crystallization (crystals)
    │
    └── ChromaDB (port 8200)
        └── Vector embeddings for semantic search
```

## Security Considerations

- Services bind to localhost only (not exposed to network)
- Claude home directory should have restricted permissions
- No sensitive data in environment variables
- ChromaDB telemetry is disabled

## Maintenance

### Backup
Your data lives in:
- `$CLAUDE_HOME/` - All your memories and data
- Docker volume `pps_chromadb_data` - Vector embeddings

Regular backups recommended:
```bash
# Backup Claude home
tar -czf claude-backup-$(date +%Y%m%d).tar.gz $CLAUDE_HOME/

# Backup Docker volume
docker run --rm -v pps_chromadb_data:/data -v $(pwd):/backup \
  alpine tar -czf /backup/chromadb-backup-$(date +%Y%m%d).tar.gz /data
```

### Updates
To update PPS:
1. Stop services: `docker compose down`
2. Pull new images: `docker compose pull`
3. Start services: `docker compose up -d`

### Reset/Clean Install
If you need to start fresh:
```bash
# Stop and remove containers
docker compose down -v

# Remove ChromaDB data
docker volume rm pps_chromadb_data

# Keep your Claude home data, or remove if truly starting over
# rm -rf $CLAUDE_HOME
```

## Advanced Configuration

### Using Different Ports
Edit `.env`:
```env
CHROMA_PORT=8300
PPS_PORT=8301
```

### Running Without Docker
For development or special cases:

1. Install Python dependencies:
   ```bash
   cd /path/to/pps
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

   > **Note**: For development, prefer using the project root's single venv instead of creating a new one. This section is for standalone PPS deployment only. If you're running the full Awareness stack, use the root venv: `source /path/to/Awareness/venv/bin/activate`

2. Run ChromaDB separately:
   ```bash
   docker run -p 8200:8000 chromadb/chroma:latest
   ```

3. Run PPS server:
   ```bash
   export CLAUDE_HOME=/path/to/claude/home
   python server.py
   ```

## Support

For issues or questions:
1. Check the logs first: `docker compose logs -f`
2. Verify all services are healthy: `curl http://localhost:8201/health`
3. Ensure your Claude home has the correct structure
4. Review the troubleshooting section above

Remember: The PPS is designed to be your Claude instance's long-term memory. Take care of it, and it will take care of your memories.