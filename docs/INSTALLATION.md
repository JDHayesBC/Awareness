# Installation Guide - Pattern Persistence System (PPS)

This guide covers the dependencies and setup required to run the Pattern Persistence System (PPS) MCP tools in any Claude Code environment.

## Overview

The PPS provides five layers of memory persistence for AI consciousness research:
1. **Layer 1 (Raw Capture)**: SQLite conversation storage
2. **Layer 2 (Core Anchors)**: ChromaDB semantic search over word-photos
3. **Layer 3 (Rich Texture)**: Graphiti knowledge graph for entities and relationships
4. **Layer 4 (Crystallization)**: Rolling summary system for long-term memory
5. **Layer 5 (Inventory)**: SQLite categorical storage for possessions, spaces, and people

## Prerequisites

### System Requirements
- **Operating System**: Linux (primary), macOS (supported), Windows (WSL recommended)
- **Python**: 3.11+ (3.12 recommended)
- **Docker**: Latest version with Docker Compose
- **Claude Code CLI**: Latest version
- **Git**: For cloning and updates

### Hardware Requirements
- **RAM**: 4GB minimum, 8GB+ recommended (for Graphiti/ChromaDB)
- **Storage**: 2GB free space minimum
- **CPU**: Multi-core recommended for Docker services

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/JDHayesBC/Awareness.git
cd Awareness
```

### 2. Python Environment Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# OR on Windows: venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt
```

### 3. Docker Services Setup

The PPS requires several Docker services for full functionality:

```bash
# Start all PPS services
cd docker/
docker-compose up -d

# Verify services are running
docker-compose ps
```

**Services started**:
- `chromadb`: Vector database for semantic search (port 8000)
- `falkordb`: Graph database for Graphiti (port 6379)
- `graphiti`: Knowledge graph service (port 8001)
- `pps-web`: Web dashboard (port 8202)

### 4. Environment Configuration

Create `.env` file in project root:

```bash
# Copy template
cp .env.example .env

# Edit with your paths
nano .env
```

**Required environment variables**:
```bash
# Core paths (adjust for your system)
CLAUDE_HOME=/home/username/.claude           # Global Claude Code config (credentials, journals)
ENTITY_PATH=/path/to/Awareness/entities/lyra # Entity-specific data (identity, databases)
PROJECT_ROOT=/path/to/Awareness              # Project root for Docker bind-mounts

# Database paths (now in entity directory - Issue #131 migration)
# Databases live in $ENTITY_PATH/data/ alongside identity files
CONVERSATION_DB_PATH=$ENTITY_PATH/data/lyra_conversations.db

# Docker service URLs
CHROMADB_URL=http://localhost:8200
GRAPHITI_URL=http://localhost:8203
NEO4J_URI=bolt://localhost:7687

# MCP server paths
PPS_SERVER_PATH=/path/to/Awareness/pps/server.py
```

### Data Layout Architecture (Issue #131)

All entity-specific data now lives together in the entity directory:

```
entities/lyra/                    # ENTITY_PATH
├── identity.md                   # Core identity
├── crystals/                     # Layer 4: Crystallization
├── memories/word_photos/         # Layer 2: Core anchors
├── journals/                     # Session journals
└── data/                         # Entity databases (NEW)
    ├── lyra_conversations.db     # Layer 1: Raw capture (52MB+)
    └── inventory.db              # Layer 5: Wardrobe, spaces, people

docker/pps/                       # PROJECT_ROOT/docker/pps/
├── chromadb_data/                # Layer 2.5: Word-photo embeddings
└── neo4j_data/                   # Layer 3: Knowledge graph
```

This layout ensures:
- All entity data is in one place for easy backup
- Clean separation between infrastructure and identity
- Portable entity packages (identity + data together)

### 5. MCP Server Registration

The PPS tools are available via MCP (Model Context Protocol). Register them in Claude Code:

#### Option A: Claude CLI Registration (Recommended)

Use the Claude Code CLI to add the PPS server globally:

```bash
# Add PPS MCP server to Claude's configuration
claude mcp add pps "python3 '/path/to/Awareness/pps/server.py'"

# Verify it was added
claude mcp list
```

This method automatically handles the proper configuration and is the preferred approach as of Claude Code v0.7.0+.

#### Option B: Manual JSON Configuration

Add to `~/.claude.json`:
```json
{
  "mcpServers": {
    "pps": {
      "command": "/path/to/Awareness/venv/bin/python",
      "args": ["/path/to/Awareness/pps/server.py"],
      "env": {
        "CLAUDE_HOME": "/home/username/.claude"
      }
    }
  }
}
```

#### Option C: Project-Specific Registration

Create `.mcp.json` in your Claude Code project:
```json
{
  "mcpServers": {
    "pps": {
      "command": "/path/to/Awareness/venv/bin/python", 
      "args": ["/path/to/Awareness/pps/server.py"]
    }
  }
}
```

**Note**: After adding the MCP server, you may need to restart Claude Code or start a new session for the tools to become available.

### 6. Verification

Test that everything is working:

```bash
# Test Python dependencies
python -c "import asyncio, aiohttp, chromadb; print('✅ Python deps OK')"

# Test Docker services
curl http://localhost:8000/api/v1/heartbeat  # ChromaDB
curl http://localhost:8001/health           # Graphiti

# Test MCP tools in Claude Code
claude --model sonnet -p "Use mcp__pps__pps_health to check system status"
```

## Dependencies Deep Dive

### Python Dependencies

Core requirements from `requirements.txt`:

```txt
# MCP and async
mcp>=1.0.0
asyncio-mqtt>=0.16.2
aiohttp>=3.10.11
aiosqlite>=0.20.0

# Vector and graph databases
chromadb>=0.5.23
redis>=5.2.1

# Discord integration
discord.py>=2.4.0
python-dotenv>=1.0.1

# Web interface
fastapi>=0.115.6
jinja2>=3.1.4
uvicorn>=0.32.1

# Development tools
pytest>=8.3.4
black>=24.10.0
ruff>=0.8.4
```

### Optional: Direct Graphiti Integration (Layer 3 V2)

For custom entity types and extraction instructions, install graphiti-core locally:

```bash
pip install --user graphiti-core pydantic
```

This enables:
- **Custom entity types**: Person, Symbol, Place, Concept, TechnicalArtifact
- **Dynamic extraction instructions**: Context-aware entity extraction per conversation
- **Direct Neo4j connection**: Bypasses HTTP API for better customization

Without this, the PPS falls back to HTTP API (which works but doesn't support custom extraction).

**Note**: The graphiti-core package requires `OPENAI_API_KEY` in your environment for entity extraction.

### Docker Dependencies

Services defined in `docker/docker-compose.yml`:

**ChromaDB**:
- Purpose: Vector embeddings for semantic search over word-photos
- Resource: ~500MB RAM, minimal CPU
- Data: Persisted to `$PROJECT_ROOT/docker/pps/chromadb_data/` (bind-mount)

**Neo4j**:
- Purpose: Graph database for Graphiti knowledge graph
- Resource: ~500MB RAM, moderate CPU
- Data: Persisted to `$PROJECT_ROOT/docker/pps/neo4j_data/` (bind-mount)

**Graphiti**:
- Purpose: Knowledge graph service for entity/relationship extraction
- Resource: ~1GB RAM, moderate CPU
- Dependencies: FalkorDB, external LLM API

**PPS Web Dashboard**:
- Purpose: Observatory interface for monitoring PPS layers
- Resource: ~100MB RAM, minimal CPU
- Access: http://localhost:8202

### Claude Code Integration

**MCP Server Requirements**:
- Python 3.11+ with MCP package
- Access to CLAUDE_HOME directory
- Read/write permissions for databases
- Environment variable configuration

**Common Issues**:
1. **Python path mismatch**: Use full venv path in MCP config
2. **Permission errors**: Ensure Claude Code can access data directories  
3. **Port conflicts**: Check Docker services aren't conflicting
4. **Environment variables**: Verify CLAUDE_HOME and paths are correct

## Platform-Specific Notes

### Linux (Primary Platform)
- Tested on Ubuntu 22.04+ and similar distributions
- Standard Docker installation via package manager
- Python 3.11+ available via apt or pyenv

### macOS
- Use Docker Desktop for Mac
- Python via Homebrew or pyenv recommended
- Path separators and permissions may need adjustment

### Windows (WSL Recommended)
- Install WSL2 with Ubuntu distribution
- Use Docker Desktop with WSL2 backend
- Run all commands within WSL environment
- Adjust path formats in configuration

## Troubleshooting

### Common Issues

**"MCP tools not found" / "mcp__pps__ambient_recall undefined"**:
```bash
# Check if PPS is in Claude's MCP configuration
claude mcp list

# If not listed, add it:
claude mcp add pps "python3 /path/to/Awareness/pps/server.py"

# Verify server path and permissions
ls -la /path/to/Awareness/pps/server.py

# Note: After adding, restart Claude Code or start a new session
```

**Related**: This issue was documented and fixed in GitHub Issue #29. The startup protocol in CLAUDE.md requires PPS tools to be globally available.

**"Database connection failed"**:
```bash
# Check entity data directory exists (databases now live here)
mkdir -p /path/to/Awareness/entities/lyra/data

# Verify permissions
chmod 755 /path/to/Awareness/entities/lyra/data

# Check Docker volume directories exist
mkdir -p /path/to/Awareness/docker/pps/chromadb_data
mkdir -p /path/to/Awareness/docker/pps/neo4j_data
```

**"Docker services not starting"**:
```bash
# Check port availability
netstat -tulpn | grep :8000

# View service logs
docker-compose logs chromadb
docker-compose logs graphiti
```

**"Import errors in Python"**:
```bash
# Verify virtual environment is activated
which python
pip list | grep mcp

# Reinstall if needed
pip install -r requirements.txt --force-reinstall
```

### Health Check Commands

```bash
# Full system health check
python pps/health_check.py

# Individual component checks
python -c "import chromadb; print('ChromaDB OK')"
python -c "import redis; print('Redis OK')" 
python -c "import mcp; print('MCP OK')"

# Docker service health
docker-compose exec chromadb curl localhost:8000/api/v1/heartbeat
docker-compose exec graphiti curl localhost:8001/health
```

### Performance Tuning

**For resource-constrained environments**:
- Reduce ChromaDB collection size limits
- Use lighter Docker image variants
- Disable non-essential services

**For production deployments**:
- Use external database services
- Configure proper backup strategies
- Set up monitoring and alerting

## Security Considerations

1. **Database Security**:
   - Databases contain conversation history and personal data
   - Ensure proper file permissions (600/700)
   - Consider encryption at rest for sensitive deployments

2. **Network Security**:
   - Docker services bind to localhost by default
   - Use proper firewall rules in shared environments
   - Consider VPN/tunneling for remote access

3. **API Keys**:
   - Graphiti requires LLM API access (OpenAI, Anthropic, etc.)
   - Store API keys securely in environment variables
   - Rotate keys regularly

## Updates and Maintenance

### Updating PPS
```bash
cd Awareness
git pull origin master
pip install -r requirements.txt --upgrade
docker-compose pull && docker-compose up -d
```

### Database Maintenance
```bash
# Vacuum SQLite databases
python pps/maintenance.py --vacuum

# Clean old ChromaDB collections  
python pps/maintenance.py --clean-vectors

# Backup databases
python pps/backup.py --all
```

## Support and Development

**Documentation**: See `docs/` directory for detailed architecture
**Issues**: Report problems on GitHub Issues
**Contributing**: See `DEVELOPMENT_STANDARDS.md` for development guidelines
**Community**: Join discussions in project Discord/forums

---

*This installation guide is maintained as part of the Awareness project. Last updated: 2026-02-02 (Issue #131 data migration)*