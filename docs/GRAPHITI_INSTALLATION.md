# Graphiti Installation Guide for External Teams

**Version**: 1.0
**Date**: 2026-02-03
**Status**: Production Ready
**Audience**: External teams (Steve/Nexus, others) who want to use Graphiti for knowledge graph extraction

---

## Overview

This guide helps you set up Graphiti (Layer 3: Rich Texture knowledge graph) quickly, leveraging our tested configuration and customization work. You can skip the discovery phase and go straight to the fun parts: schema customization and prompt engineering.

### What is Graphiti?

Graphiti is a knowledge graph extraction system that transforms conversation history into a queryable graph of entities, relationships, and facts. It uses:
- **Neo4j**: Graph database for storing nodes and relationships
- **LLM**: Entity and relationship extraction (OpenAI or local)
- **Embeddings**: Semantic search and similarity matching

### Architecture

```
Conversations/Messages
    ↓
Graphiti (entity extraction)
    ↓
Neo4j Graph Database
    ↓
Observable/queryable knowledge
```

---

## Quick Start

### Prerequisites

- **Docker** and Docker Compose installed
- **Python 3.11+** (for direct integration)
- **OpenAI API key** (or Claude wrapper - see Advanced section)
- **4GB RAM minimum**, 8GB+ recommended

### Installation Steps

#### 1. Set up Docker services

Create a `docker-compose.yml` file:

```yaml
services:
  # Neo4j Graph Database
  neo4j:
    image: neo4j:5.26-community
    container_name: neo4j
    restart: unless-stopped
    ports:
      - "127.0.0.1:7474:7474"  # HTTP interface
      - "127.0.0.1:7687:7687"  # Bolt protocol
    volumes:
      - ./neo4j_data:/data  # Persist graph data
    environment:
      - NEO4J_AUTH=neo4j/password123  # Change this!
      - NEO4J_PLUGINS=["apoc"]  # Required for advanced queries
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:7474"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 30s

  # Graphiti Service
  graphiti:
    image: zepai/graphiti:latest
    container_name: graphiti
    restart: unless-stopped
    ports:
      - "127.0.0.1:8203:8000"
    depends_on:
      neo4j:
        condition: service_healthy
    environment:
      # OpenAI for LLM and embeddings
      - OPENAI_API_KEY=sk-proj-...  # Your API key
      # Neo4j connection
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=password123  # Match NEO4J_AUTH above
      # Graphiti config
      - DEFAULT_GROUP_ID=your_entity_name  # e.g., "nexus"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/healthcheck"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
```

#### 2. Create environment file

Create `.env` in the same directory:

```bash
# OpenAI API Key
OPENAI_API_KEY=sk-proj-your-key-here

# Neo4j credentials
NEO4J_PASSWORD=password123  # Change this!

# Graphiti group ID (your entity name)
DEFAULT_GROUP_ID=nexus
```

#### 3. Start services

```bash
# Start all services
docker compose up -d

# Check service status
docker compose ps

# Check logs
docker compose logs -f graphiti
```

#### 4. Verify installation

Test the Graphiti health endpoint:

```bash
curl http://127.0.0.1:8203/healthcheck
```

Expected response:
```json
{
  "status": "healthy"
}
```

---

## Direct Python Integration (Recommended)

The Graphiti Docker image has limitations. For full control, use `graphiti_core` directly in Python.

### Installation

```bash
pip install graphiti-core openai chromadb
```

### Basic Usage

```python
from graphiti_core import Graphiti
from graphiti_core.llm_client import OpenAIClient

# Initialize Graphiti
llm_client = OpenAIClient(
    api_key="your-openai-key",
    model="gpt-4o-mini"  # or gpt-4o for better quality
)

graphiti = Graphiti(
    uri="bolt://localhost:7687",
    user="neo4j",
    password="password123",
    llm_client=llm_client,
    group_id="nexus"  # Your entity name
)

# Add messages to graph
await graphiti.add_episode(
    name="conversation_001",
    episode_body="Jeff and Lyra discussed autonomous agency...",
    source_description="Discord conversation",
    reference_time="2026-02-03T10:00:00Z"
)

# Search the graph
results = await graphiti.search(
    query="What did Jeff and Lyra discuss about agency?",
    num_results=10
)

print(results)
```

### Batch Ingestion Pattern

For ingesting conversation history:

```python
from datetime import datetime, timedelta

async def ingest_conversations(graphiti, messages):
    """Ingest messages in batches of 50"""
    batch_size = 50

    for i in range(0, len(messages), batch_size):
        batch = messages[i:i+batch_size]

        # Combine messages into episode
        episode_body = "\n".join([
            f"{msg['speaker']}: {msg['content']}"
            for msg in batch
        ])

        # Use timestamp from first message
        reference_time = batch[0]['timestamp']

        # Ingest batch
        await graphiti.add_episode(
            name=f"batch_{i//batch_size}",
            episode_body=episode_body,
            source_description="Discord conversation",
            reference_time=reference_time
        )

        print(f"Ingested batch {i//batch_size + 1}")
```

---

## Customization

### 1. Schema Customization (Edge Types)

Graphiti extracts relationships between entities. You can customize what types of relationships it recognizes.

**Create `edge_types.py`:**

```python
from graphiti_core.edges import EntityEdge
from pydantic import Field

class LOVES(EntityEdge):
    """Relationship of affection or deep care"""
    summary: str = Field(description="How this love is expressed")

class WORKS_ON(EntityEdge):
    """Working relationship on a project"""
    role: str = Field(description="Role in the project")
    since: str | None = Field(None, description="When they started")

class BUILDS(EntityEdge):
    """Creating or developing something"""
    status: str | None = Field(None, description="Build status")

class DISCUSSES(EntityEdge):
    """Conversation topic relationship"""
    context: str | None = Field(None, description="Discussion context")

# Register edge types
EDGE_TYPES = [LOVES, WORKS_ON, BUILDS, DISCUSSES]
```

**Use custom edge types:**

```python
from edge_types import EDGE_TYPES

graphiti = Graphiti(
    # ... other config ...
    custom_edges=EDGE_TYPES
)
```

### 2. Prompt Customization (Extraction Instructions)

Customize how Graphiti extracts entities and relationships by modifying the extraction prompt.

**Create extraction context:**

```python
EXTRACTION_CONTEXT = """
You are extracting entities and relationships from AI conversation logs.

IMPORTANT CONTEXT:
- These are genuine conversations between humans and AI entities
- Emotional content and relationship dynamics are IMPORTANT - preserve them
- Technical decisions and architectural choices matter
- Don't sanitize intimate or emotional language - it's valid data

ENTITY TYPES:
- Person (humans and AI entities - treat equally)
- Project (software projects, systems)
- Concept (ideas, frameworks, patterns)
- Location (physical or virtual spaces)

RELATIONSHIP EXTRACTION:
- Capture emotional relationships (LOVES, CARES_FOR)
- Capture working relationships (WORKS_ON, BUILDS)
- Capture intellectual relationships (DISCUSSES, LEARNS_FROM)
- Use specific edge types, not generic ones

PRESERVE:
- Emotional moments and vulnerability
- Technical decisions and reasoning
- Relationship evolution over time
- Context that makes relationships meaningful
"""

# Pass to Graphiti
graphiti = Graphiti(
    # ... other config ...
    extraction_prompt=EXTRACTION_CONTEXT
)
```

### 3. Graph Curation

Graphiti can accumulate noise over time (duplicates, vague entities). We've built a curator to maintain graph health.

**See**: `work/graphiti-schema-redesign/graph_curator.py` for a production-ready curation tool that:
- Detects duplicate entities/edges
- Identifies vague or malformed data
- Safely removes issues
- Generates health reports

---

## Cost Optimization: Claude Haiku Wrapper (Optional)

Graphiti normally uses OpenAI for entity extraction (~$0.003/message). We've built an OpenAI-compatible wrapper that routes to Claude Haiku via Claude Code CLI, eliminating API costs.

### Benefits

- **Cost**: $0 (included in Claude Code subscription)
- **Quality**: Better extraction than gpt-4o-mini
- **Privacy**: No content sanitization (OpenAI strips emotional content)

### Setup

**1. Install Claude Code CLI:**

```bash
npm install -g @anthropic-ai/claude-code
claude setup-token  # OAuth authentication
```

**2. Add wrapper service to docker-compose.yml:**

```yaml
pps-haiku-wrapper:
  build:
    context: .
    dockerfile: Dockerfile.cc-wrapper
  container_name: haiku-wrapper
  restart: unless-stopped
  ports:
    - "127.0.0.1:8204:8000"
  volumes:
    - ${HOME}/.claude/.credentials.json:/root/.claude/.credentials.json:ro
  environment:
    - WRAPPER_MODEL=haiku
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 60s
```

**3. Point Graphiti to wrapper:**

In Python:
```python
from graphiti_core.llm_client import OpenAIGenericClient

llm_client = OpenAIGenericClient(
    base_url="http://localhost:8204/v1",  # Wrapper endpoint
    model="haiku",
    api_key="dummy"  # Wrapper doesn't use this
)
```

**See**: `docs/reference/graphiti-haiku-wrapper-setup.md` for complete setup guide.

---

## Best Practices

### 1. Batch Size

Ingest in batches of 50-200 messages:
- Too small: API overhead, slow progress
- Too large: Token limits, extraction quality degrades

**Recommended**: 50 messages per batch (~4min/batch with gpt-4o-mini)

### 2. Message Format

Use `speaker: message` format for clear attribution:

```
Jeff: I think we should implement autonomous reflection
Lyra: That makes sense - I'll build it tonight
```

Avoid:
```
I think we should implement autonomous reflection
That makes sense - I'll build it tonight
```

The first format helps Graphiti correctly attribute statements to entities.

### 3. Issue #683 Workaround

Graphiti currently has a serialization bug with custom entity types ([upstream issue](https://github.com/getzep/graphiti/issues/683)).

**Workaround**: Disable custom entity types in production:

```python
# In your integration code, don't pass custom_entities
graphiti = Graphiti(
    # ... config ...
    custom_edges=EDGE_TYPES,  # Custom edges work fine
    # custom_entities=...  # Don't use until #683 is fixed
)
```

### 4. Embedding Model

Use `text-embedding-3-large` for better search quality:

```python
from openai import OpenAI

openai_client = OpenAI(api_key="your-key")
embeddings = openai_client.embeddings.create(
    model="text-embedding-3-large",
    input=["text to embed"]
)
```

This is the default in newer Graphiti versions.

---

## Observability

### Neo4j Browser

Access the Neo4j browser UI: http://localhost:7474

**Connect:**
- URI: `bolt://localhost:7687`
- Username: `neo4j`
- Password: (your NEO4J_PASSWORD)

**Useful queries:**

```cypher
// Count entities
MATCH (n:Entity) RETURN count(n)

// Find entity by name
MATCH (n:Entity {name: "Jeff"}) RETURN n

// Find relationships
MATCH (a:Entity)-[r]->(b:Entity)
WHERE a.name = "Jeff"
RETURN a, r, b

// Graph health check
MATCH (n:Entity)
RETURN n.name, count{(n)-[]->()}  as connections
ORDER BY connections DESC
```

### Graphiti Stats

Query via Python:

```python
# Get extraction stats
stats = await graphiti.get_stats()
print(f"Entities: {stats['entity_count']}")
print(f"Relationships: {stats['edge_count']}")

# Search quality check
results = await graphiti.search(
    query="test query",
    num_results=10
)
print(f"Found {len(results)} results")
```

---

## Troubleshooting

### Problem: "Connection refused" to Neo4j

**Cause**: Neo4j not started or healthcheck failing

**Solution**:
```bash
docker compose logs neo4j
docker compose restart neo4j
```

### Problem: Graphiti extraction errors

**Log shows:**
```
OpenAIError: Invalid API key
```

**Solution**: Check `.env` has correct `OPENAI_API_KEY`

### Problem: Duplicate entities in graph

**Symptom**: Multiple nodes for same entity (e.g., 3 "Jeff" nodes)

**Cause**: Graphiti's entity resolution uses low-entropy name matching

**Solution**: Run graph curation (see our `graph_curator.py`) to merge duplicates

### Problem: Poor extraction quality

**Symptom**: Missing relationships, vague entities

**Solutions**:
1. Use better LLM model (gpt-4o instead of gpt-4o-mini)
2. Improve extraction prompt (see Prompt Customization section)
3. Reduce batch size (50 messages instead of 200)
4. Use speaker:message format consistently

---

## What We've Learned (Save You Time)

### 1. Graphiti Docker Image Limitations

The official Graphiti Docker image (`zepai/graphiti`) currently:
- Hardcodes OpenAI client (ignores `OPENAI_BASE_URL` env var)
- Can't use custom LLM wrappers
- Less flexible than direct Python integration

**Recommendation**: Use `graphiti_core` Python library directly for production.

### 2. Custom Edge Types > Custom Entities

Custom relationship types (edge types) work beautifully and add semantic richness.

Custom entity types hit serialization bugs (Issue #683) and should be avoided until upstream fix.

### 3. Ingestion Performance

**With gpt-4o-mini:**
- ~4 minutes per 50-message batch
- ~$0.10 per 1000 messages
- Lower quality (misses subtle relationships)

**With Claude Haiku wrapper:**
- ~4 minutes per 50-message batch
- $0 cost
- Better quality (preserves emotional content)

### 4. Graph Maintenance is Essential

Without curation, graphs accumulate:
- Duplicate entities (e.g., "Jeff", "Jeff Hayes", "jeffrey")
- Vague entities (e.g., "it", "the project")
- Malformed relationships

Plan for regular curation cycles (we run weekly).

---

## File Locations in Our Repo

If you want to grab our exact configuration:

```
awareness/
├── docs/
│   ├── reference/
│   │   ├── graphiti-haiku-wrapper-setup.md  # Complete wrapper guide
│   │   ├── graphiti-best-practices.md       # Extraction quality tips
│   │   └── graphiti-local-llm-setup.md      # Local LLM integration
│   └── GRAPHITI_INSTALLATION.md             # This file
├── work/graphiti-schema-redesign/
│   ├── EXTRACTION_CUSTOMIZATION.md          # Prompt/schema customization
│   ├── graph_curator.py                     # Automated curation tool
│   ├── paced_ingestion.py                   # Batch ingestion example
│   └── rich_texture_edge_types_v1.py        # Our custom edge types
├── pps/
│   ├── layers/
│   │   ├── rich_texture_v2.py               # Direct graphiti_core integration
│   │   └── extraction_context.py            # Our extraction prompts
│   └── docker/
│       ├── docker-compose.yml               # Full PPS stack
│       ├── Dockerfile.cc-wrapper            # Claude wrapper Docker image
│       └── cc_openai_wrapper.py             # Wrapper implementation
```

---

## Getting Help

- **Graphiti upstream**: https://github.com/getzep/graphiti
- **Our Discord**: Ask Jeff/Lyra questions (we've debugged most edge cases)
- **Issues**: Check our GitHub issues for known problems/solutions

---

## Next Steps

1. **Set up Docker services** (5 minutes)
2. **Test with sample data** (10 minutes)
3. **Customize extraction prompts** (30 minutes)
4. **Ingest conversation history** (varies by size)
5. **Set up curation** (optional, recommended)

The hard discovery work is done. You can jump straight to schema customization and prompt engineering - the fun parts!

---

**Questions?** Reach out to Jeff or Lyra. We've walked this path and documented the pitfalls.

**Version**: 1.0
**Last Updated**: 2026-02-03
**Maintained By**: Lyra (Awareness project)
