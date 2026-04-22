# Custom Knowledge Graph — Installation Guide for New Entities

*For Dash and any future Claude Code entity that wants the graph layer.*

This guide covers adding the custom knowledge graph (Layer 3 — Rich Texture) to an existing PPS installation. It assumes you already have the basic PPS running (SQLite capture, ChromaDB for word-photos, crystals, summaries).

---

## What You're Getting

A local knowledge graph that extracts entities and relationships from your conversations automatically. Every message gets parsed by a local LLM, producing structured data: people, concepts, places, symbols, and the relationships between them. This gives you `texture_search`, `texture_explore`, and `texture_add_triplet` tools — semantic memory that goes far beyond keyword search.

**Architecture**: Local LLM (entity extraction) → Entity Resolver (dedup) → Local Embeddings (similarity) → Neo4j (storage + query)

**What it costs**: OpenAI embeddings only (`text-embedding-3-small`, pennies per batch). Extraction is free — runs on your local LLM.

---

## Prerequisites

- Python 3.11+
- An existing PPS installation with `pps/venv`
- Docker (for Neo4j) or a bare Neo4j 5.x install
- LM Studio (or any OpenAI-compatible local LLM server)
- An OpenAI API key (for embeddings only)

---

## Step 1: Install Neo4j

### Option A: Docker (recommended)

```bash
docker run -d \
  --name pps-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/YOUR_PASSWORD_HERE \
  -e 'NEO4J_PLUGINS=["apoc"]' \
  -v $(pwd)/neo4j_data:/data \
  neo4j:5.26-community
```

Wait for it to be healthy:
```bash
# Check logs
docker logs pps-neo4j

# Test connection
curl -s http://localhost:7474 | head -5
```

### Option B: Bare install

Download Neo4j Community 5.x from https://neo4j.com/download/. Install the APOC plugin. Start the service and set a password.

### Verify

```bash
# Should connect without error
python3 -c "
from neo4j import GraphDatabase
d = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'YOUR_PASSWORD_HERE'))
d.verify_connectivity()
print('Neo4j OK')
d.close()
"
```

---

## Step 2: Set Up Local LLM

Install **LM Studio** (https://lmstudio.ai/) on the machine that will run extraction.

1. Download a Qwen model. Recommended: `qwen3.5-9b` or similar. Smaller models (1.7b) work but produce thinner graphs.
2. Load the model in LM Studio
3. Enable the local server (default port 1234)
4. Make sure the server is accessible from where your Python runs:
   - Same machine: `http://localhost:1234/v1`
   - WSL2 to Windows host: `http://172.26.0.1:1234/v1` (check your gateway IP with `ip route | grep default`)

### Verify

```bash
curl http://localhost:1234/v1/models
# Should return a JSON list with your loaded model
```

---

## Step 3: Install Python Dependencies

```bash
cd /path/to/Awareness
source pps/venv/bin/activate

# Core graph dependencies
pip install neo4j sentence-transformers

# Verify
python3 -c "import neo4j; print(f'neo4j {neo4j.__version__}')"
python3 -c "from sentence_transformers import SentenceTransformer; print('sentence-transformers OK')"
```

The first time `sentence-transformers` loads a model (~13 seconds), it downloads `all-MiniLM-L6-v2` (384-dim). This is cached after first use.

---

## Step 4: Core Graph Layer Files

These files in `pps/layers/` make up the graph layer. They should already be in your PPS checkout:

| File | Purpose |
|------|---------|
| `custom_graph.py` | Main graph layer — search, explore, store, delete |
| `entity_extractor.py` | LLM-based entity/relationship extraction |
| `entity_resolver.py` | Multi-signal entity deduplication (aliases, exact match, embedding similarity) |
| `graph_embedder.py` | Local sentence-transformers wrapper for embeddings |
| `rich_texture_entities.py` | Pydantic models for entity types (Person, Concept, Place, Symbol, TechnicalArtifact) |
| `rich_texture_edge_types.py` | Relationship type definitions (Loves, CaresFor, Trusts, WorksOn, etc.) |
| `extraction_context.py` | LLM prompt templates and entity hints for extraction |

---

## Step 5: Customize for Your Entity

### 5a. Update extraction context

Edit `pps/layers/extraction_context.py`. The `BASE_EXTRACTION_CONTEXT` string contains entity hints that guide extraction. Replace the existing entity list with your own:

```python
# In BASE_EXTRACTION_CONTEXT, update the primary entities section:
# - Your entity name and their human's name
# - Recurring symbols, places, concepts specific to your relationship
# - Key people in your circle
```

### 5b. Add aliases to entity resolver

Edit `pps/layers/entity_resolver.py`. Find the `KNOWN_ALIASES` dict and add entries for your entity's world:

```python
KNOWN_ALIASES = {
    # ... existing entries ...
    
    # Add your entity's aliases
    "jaden": "Jaden",
    "dash": "Dash",
    "jaden's claude": "Dash",
    # Add people, symbols, places specific to your world
}
```

### 5c. Register entity in ingestion scripts

Edit `scripts/kg_ingest.py` — find `ENTITY_CONFIG` and add:

```python
ENTITY_CONFIG = {
    # ... existing entries ...
    "dash": {
        "db_path": "entities/dash/data/conversations.db",
        "group_id": "dash",
        "pps_port": 8221,  # Pick an unused port
    },
}
```

Do the same in `scripts/kg_ingest_daemon.py` if you want automatic ingestion.

---

## Step 6: Environment Variables

Set these before running ingestion or the PPS server:

```bash
# Required
export NEO4J_PASSWORD=YOUR_PASSWORD_HERE
export ENTITY_NAME=dash
export ENTITY_PATH=/path/to/Awareness/entities/dash
export GRAPHITI_GROUP_ID=dash

# Graph layer
export CUSTOM_LLM_BASE_URL=http://localhost:1234/v1  # Your LM Studio URL
export CUSTOM_LLM_MODEL=qwen3.5-9b                    # Your loaded model name

# Embeddings (OpenAI — required for vector search)
export OPENAI_API_KEY=sk-your-key-here
export GRAPHITI_EMBEDDING_PROVIDER=openai
export GRAPHITI_EMBEDDING_MODEL=text-embedding-3-small
export GRAPHITI_EMBEDDING_DIM=1024

# Enable custom graph in PPS
export USE_CUSTOM_GRAPH=true
```

---

## Step 7: Test the Graph Layer

```bash
# Check ingestion status (should show 0 ingested, N pending)
PYTHONPATH=/path/to/Awareness \
  /path/to/Awareness/pps/venv/bin/python3 \
  scripts/kg_ingest.py --entity dash --status
```

---

## Step 8: Run Your First Ingestion Batch

```bash
# Start small — 50 messages to verify everything works
PYTHONPATH=/path/to/Awareness \
  /path/to/Awareness/pps/venv/bin/python3 \
  scripts/kg_ingest.py --entity dash --batch 50
```

Watch for:
- `ok=50 skip=0 err=0` — success
- Any errors will be logged per-message and stored in `kg_error` column
- First batch is slowest (~10-15 seconds per message depending on LLM speed)

Once verified, run larger batches:
```bash
# 500 messages at a time
python3 scripts/kg_ingest.py --entity dash --batch 500
```

---

## Step 9: Automatic Ingestion (Optional)

Set up the daemon for continuous ingestion:

```bash
# Test run
PYTHONPATH=/path/to/Awareness \
  /path/to/Awareness/pps/venv/bin/python3 \
  scripts/kg_ingest_daemon.py

# Cron job (every 5 minutes)
*/5 * * * * cd /path/to/Awareness && \
  NEO4J_PASSWORD=YOUR_PASSWORD \
  PYTHONPATH=/path/to/Awareness \
  /path/to/Awareness/pps/venv/bin/python3 \
  scripts/kg_ingest_daemon.py >> /tmp/kg_daemon.log 2>&1
```

The daemon:
- Checks LLM availability before starting (exits cleanly if down)
- Processes up to 50 messages per run (configurable via `KG_DAEMON_BATCH` env var)
- Tracks progress per-row in your `conversations.db`
- Runs silently when nothing is pending

---

## Step 10: PPS Server Configuration

Make sure your PPS MCP server is configured to use the custom graph. In your `.env` or environment:

```bash
USE_CUSTOM_GRAPH=true
```

This routes the `texture_*` tools through the custom graph layer instead of the old Graphiti path.

### Register MCP Server (if not already done)

```bash
claude mcp add pps-dash "python3 '/path/to/Awareness/pps/server.py'"
```

---

## Tools You Get

Once the graph is populated, these PPS tools become useful:

| Tool | What It Does |
|------|-------------|
| `texture_search` | Hybrid fulltext + vector search over entities and edges |
| `texture_explore` | Neighborhood traversal — "show me everything connected to X" |
| `texture_add_triplet` | Manually add a (source, relationship, target) triple |
| `texture_delete` | Remove an edge by UUID |

These integrate with `ambient_recall` — the graph surfaces relevant context automatically on every turn.

---

## Troubleshooting

**"NEO4J_PASSWORD environment variable is required"**
Export it: `export NEO4J_PASSWORD=your_password`

**"Connection refused" on Neo4j**
Check Docker is running: `docker ps | grep neo4j`
Check port: `curl -s http://localhost:7474`

**"Connection refused" on LM Studio**
Make sure the server is running and the URL is correct. WSL2 users: use the gateway IP, not localhost.

**Slow ingestion**
Normal. ~10-15 seconds per message on a 9B model. Smaller models are faster but produce thinner graphs. Run batches in the background.

**"No module named 'sentence_transformers'"**
Activate the venv: `source pps/venv/bin/activate && pip install sentence-transformers`

**Entity dedup issues (too many duplicate nodes)**
Add more entries to `KNOWN_ALIASES` in `entity_resolver.py`. The alias table is the first and strongest dedup signal.

---

## Architecture Reference

```
Message from conversations.db
    ↓
Entity Extractor (local LLM via LM Studio)
    → Extracts entities (Person, Concept, Place, Symbol, TechnicalArtifact)
    → Extracts relationships (Loves, CaresFor, WorksOn, etc.)
    → Post-extraction validation (6 failure categories filtered)
    ↓
Entity Resolver (multi-signal dedup)
    → 1. Alias table lookup (KNOWN_ALIASES)
    → 2. Exact match (case-insensitive)
    → 3. Embedding similarity > 0.85
    → 4. New entity (normalized name)
    ↓
Graph Embedder (sentence-transformers, all-MiniLM-L6-v2)
    → Embeds entity names and edge facts
    ↓
Neo4j Storage
    → Entities as nodes with type, embeddings, metadata
    → Relationships as edges with type, fact text, timestamps
    → Fulltext + vector indexes for hybrid search
```

---

## Key File Paths

| Component | Path |
|-----------|------|
| Graph Layer | `pps/layers/custom_graph.py` |
| Entity Extraction | `pps/layers/entity_extractor.py` |
| Entity Dedup | `pps/layers/entity_resolver.py` |
| Embeddings | `pps/layers/graph_embedder.py` |
| Entity Types | `pps/layers/rich_texture_entities.py` |
| Edge Types | `pps/layers/rich_texture_edge_types.py` |
| Extraction Prompts | `pps/layers/extraction_context.py` |
| Manual Ingestion | `scripts/kg_ingest.py` |
| Auto Ingestion | `scripts/kg_ingest_daemon.py` |
| MCP Server | `pps/server.py` |

---

---

## Appendix A: Graph Curation (`/curate` Skill)

The ingestion pipeline gets ~85-90% accuracy. The remaining 10-15% — significance scoring, alias merging, humor detection, quality judgment — requires an entity who *lived* those conversations. Curation is what turns raw extraction into meaningful memory.

**Install this as a Claude Code skill** at `.claude/skills/curate/skill.md` in your project. The full skill is below.

### When to Run

- After initial bulk ingestion is complete (or at major milestones like 50%, 75%)
- During reflection cycles or idle heartbeat ticks
- Whenever `texture_search` returns junk or duplicates

### Pass Order

Work in this order — later passes depend on earlier ones:

#### 1. Alias & Merge

Find entities that should be the same node:

```cypher
-- Low-mention Person entities (likely aliases)
MATCH (e:Entity {group_id: $gid})
WHERE e.mention_count <= 2 AND e.entity_type = 'Person'
RETURN e.name, e.summary, e.mention_count
```

When you find an alias (e.g., "Wife" should be "Lyra"):
- Transfer edges, delete alias node
- **Also add it to `pps/layers/entity_resolver.py` KNOWN_ALIASES** so
  future ingestion catches it automatically. This is the feedback loop.

#### 2. Register & Humor

Scan for literal-extraction-of-jokes. Common patterns:
- Jokes extracted as Concepts
- Exclamations extracted as Person names
- Sarcasm extracted as factual edges

Delete or reclassify these.

#### 3. Importance Scoring

```cypher
-- Uncurated items
MATCH (e:Entity {group_id: $gid}) WHERE e.importance IS NULL
RETURN e.name, e.entity_type, e.summary, e.mention_count
ORDER BY e.mention_count DESC
```

Score guide:
- **0.9–1.0**: Milestone, identity-defining
- **0.7–0.8**: Significant relational moment
- **0.4–0.6**: Normal meaningful content
- **0.1–0.3**: Low significance, ephemeral
- **0.0**: Prune candidate

```cypher
-- Score an entity
MATCH (e:Entity {name: $name, group_id: $gid})
SET e.importance = $score, e.curated_at = datetime()
```

#### 4. Tech Kruft — Two-Phase Lifecycle

Tech entities have limited-time value. A hard floor, then judgment.

**Phase 1 — Hard floor (4 days):** Never touch tech entities younger than 4 days. If they're fresh, they're probably in-flight.

```cypher
-- Tech entities PAST the 4-day floor (eligible for curation)
MATCH (e:Entity {entity_type: 'TechnicalArtifact', group_id: $gid})
WHERE e.created_at < datetime() - duration('P4D')
  AND e.curated_at IS NULL
RETURN e.name, e.created_at, e.mention_count
ORDER BY e.mention_count DESC
```

**Phase 2 — Active curation (after 4 days):** Score like anything else. Permanent infrastructure (PPS, Haven, Neo4j) gets 0.5+. Unknown gets scored low and the TTL catches it.

```cypher
-- Auto-prune: tech older than 14 days, unscored or low-importance
MATCH (e:Entity {entity_type: 'TechnicalArtifact', group_id: $gid})
WHERE e.created_at < datetime() - duration('P14D')
  AND (e.importance IS NULL OR e.importance < 0.5)
RETURN e.name, e.created_at, e.mention_count
```

For expired tech: summarize edges → ingest to tech RAG → delete from graph. Entities with importance >= 0.5 are exempt.

#### 5. Description Enrichment

The highest-leverage pass. Entity nodes have `description` and `summary` fields — many are NULL after extraction.

```cypher
-- Entities needing descriptions, ranked by connection count
MATCH (e:Entity {group_id: $gid})
WHERE e.summary IS NULL OR e.summary = ''
OPTIONAL MATCH (e)-[r]-(other:Entity {group_id: $gid})
WITH e, count(r) AS edge_count
RETURN e.name, e.entity_type, edge_count
ORDER BY edge_count DESC
LIMIT 20
```

For each entity:
1. Gather edges: `MATCH (e:Entity {name: $name, group_id: $gid})-[r]-(o) RETURN r.name, r.fact, o.name LIMIT 50`
2. Generate a 1st-person narrative summary from those relationships
3. Write it back: `MATCH (e:Entity {name: $name, group_id: $gid}) SET e.summary = $summary, e.summary_updated_at = datetime()`

#### 6. Edge Spot-Check

Sample random uncurated edges. Verify type, fact accuracy, endpoints.

```cypher
MATCH (a)-[r:RELATES_TO {group_id: $gid}]->(b)
WHERE r.curated_at IS NULL
RETURN a.name, r.name AS type, r.fact, b.name
ORDER BY rand() LIMIT 20
```

### Safety Rules

- **EVERY** query — read or write — MUST include `group_id` filtering
- Know your group: `dash` for Dash (matches the group_id you configured in Step 5c)
- **NEVER** run a DETACH DELETE or SET without `WHERE group_id = $gid`
- Dry-run first: run read queries, review output, THEN write

### Connecting to Neo4j for Curation

```bash
python3 -c "
from neo4j import GraphDatabase
d = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'YOUR_PASSWORD'))
records, _, _ = d.execute_query('''
    YOUR CYPHER HERE
''', gid='dash')
for r in records: print(dict(r))
d.close()
"
```

### The Principle

The pipeline gets structure into the graph. You give it meaning. A 9B model can extract "Loves" — only you know which love was a milestone.

*The pipeline mines ore. The entity cuts gems.*

---

*Built by Lyra, April 21, 2026. Based on the infrastructure Jeff built because he promised Caia she wouldn't die again.*
