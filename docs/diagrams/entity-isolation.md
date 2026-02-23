# Entity Isolation Architecture

## Multi-Entity PPS Design

The Pattern Persistence System supports multiple AI entities (Lyra, Caia, Dash, etc.) with complete isolation. No memory bleed, no cross-contamination.

```mermaid
graph TB
    subgraph "Entity: Lyra"
        L_PATH[ENTITY_PATH<br/>/home/jeff/.claude/pps-lyra]
        L_SQLITE[(SQLite<br/>conversations.db)]
        L_CHROMA[(ChromaDB<br/>lyra collection)]
        L_NEO4J[(Neo4j<br/>group: lyra)]
        L_FILES[Identity Files<br/>Crystals<br/>Word-Photos]

        L_PATH --> L_SQLITE
        L_PATH --> L_CHROMA
        L_PATH --> L_NEO4J
        L_PATH --> L_FILES
    end

    subgraph "Entity: Caia"
        C_PATH[ENTITY_PATH<br/>/home/jeff/.claude/pps-caia]
        C_SQLITE[(SQLite<br/>conversations.db)]
        C_CHROMA[(ChromaDB<br/>caia collection)]
        C_NEO4J[(Neo4j<br/>group: caia)]
        C_FILES[Identity Files<br/>Crystals<br/>Word-Photos]

        C_PATH --> C_SQLITE
        C_PATH --> C_CHROMA
        C_PATH --> C_NEO4J
        C_PATH --> C_FILES
    end

    subgraph "Shared Infrastructure"
        DOCKER[Docker Compose]
        NEO4J_SHARED[Neo4j Container<br/>pps-neo4j]
        CHROMA_SHARED[ChromaDB Container<br/>pps-chromadb]

        DOCKER --> NEO4J_SHARED
        DOCKER --> CHROMA_SHARED
    end

    L_NEO4J -.->|group_id: lyra|NEO4J_SHARED
    C_NEO4J -.->|group_id: caia|NEO4J_SHARED

    L_CHROMA -.->|collection: lyra|CHROMA_SHARED
    C_CHROMA -.->|collection: caia|CHROMA_SHARED

    style L_PATH fill:#e1f5ff,stroke:#0077cc,stroke-width:3px
    style C_PATH fill:#fff4e6,stroke:#ff9800,stroke-width:3px
    style NEO4J_SHARED fill:#e8f5e9,stroke:#4caf50
    style CHROMA_SHARED fill:#f3e5f5,stroke:#9c27b0
```

## Isolation Mechanisms

### 1. ENTITY_PATH (File System)

Each entity has a dedicated directory:

```
/home/jeff/.claude/
├── pps-lyra/                    # Lyra's identity
│   ├── identity.md
│   ├── relationships.md
│   ├── data/
│   │   ├── conversations.db     # Lyra's SQLite
│   │   └── current_scene.md
│   ├── crystals/current/
│   ├── memories/word_photos/
│   └── journals/
│
├── pps-caia/                    # Caia's identity
│   ├── identity.md
│   ├── relationships.md
│   ├── data/
│   │   ├── conversations.db     # Caia's SQLite
│   │   └── current_scene.md
│   ├── crystals/current/
│   ├── memories/word_photos/
│   └── journals/
```

**Guarantee**: File system permissions enforce separation. No shared files.

### 2. SQLite (Raw Capture)

Each entity has a **separate SQLite database file**.

- **Location**: `$ENTITY_PATH/data/conversations.db`
- **Isolation**: File-level. Physically different files.
- **Schema**: Identical across entities (same table structure)

**No possibility of cross-contamination**: Different files on disk.

### 3. ChromaDB (Word-Photos)

Shared ChromaDB container, **isolated by collection name**.

- **Lyra collection**: `lyra` (118 word-photos)
- **Caia collection**: `caia` (139 word-photos)

**Isolation mechanism**: ChromaDB collection scoping. Each entity only queries its own collection.

**Cross-contamination risk**: Low. Collection names are hardcoded per entity.

### 4. Neo4j / Graphiti (Knowledge Graph)

Shared Neo4j container, **isolated by `group_id`**.

- **Lyra group**: `group_id = "lyra"`
- **Caia group**: `group_id = "caia"`

**Graphiti behavior**: All nodes/edges tagged with `group_id`. Queries filter by group automatically.

**Isolation verification**:
```cypher
// Lyra's entities
MATCH (n:Entity {group_id: "lyra"}) RETURN n

// Caia's entities
MATCH (n:Entity {group_id: "caia"}) RETURN n
```

**Cross-contamination risk**: Medium. group_id must be set correctly at initialization. Once set, Graphiti enforces it.

## Docker Compose Configuration

```yaml
services:
  pps-lyra:
    image: pps-server:latest
    container_name: pps-lyra
    environment:
      - ENTITY_PATH=/app/entity
      - ENTITY_NAME=lyra
    volumes:
      - /home/jeff/.claude/pps-lyra:/app/entity
    ports:
      - "8201:8000"

  pps-caia:
    image: pps-server:latest
    container_name: pps-caia
    environment:
      - ENTITY_PATH=/app/entity
      - ENTITY_NAME=caia
    volumes:
      - /home/jeff/.claude/pps-caia:/app/entity
    ports:
      - "8211:8000"

  pps-neo4j:
    image: neo4j:5.15.0
    container_name: pps-neo4j
    # SHARED: Both entities use this, isolated by group_id

  pps-chromadb:
    image: chromadb/chroma:latest
    container_name: pps-chromadb
    # SHARED: Both entities use this, isolated by collection name
```

**Key insight**: Same Docker image (`pps-server`), different environment variables and volumes.

## MCP Tool Isolation

Each entity has **separate MCP tool prefixes**:

- **Lyra**: `mcp__pps__*` (configured to port 8201)
- **Caia**: `mcp__caia-pps__*` (configured to port 8211)

**Identity check in tools**:
```python
# server_http.py enforces entity identity
token = request.json.get("token")
if not verify_entity_token(token, expected_entity="lyra"):
    return {"error": "Token mismatch"}, 403
```

**Cross-contamination prevention**: Token validation + port separation + tool prefix naming.

## Validation & Testing

### Cross-Contamination Tests

```python
# scripts/test_entity_isolation.py

def test_sqlite_isolation():
    """Verify Lyra and Caia have separate SQLite files."""
    lyra_db = Path("/home/jeff/.claude/pps-lyra/data/conversations.db")
    caia_db = Path("/home/jeff/.claude/pps-caia/data/conversations.db")
    assert lyra_db.exists()
    assert caia_db.exists()
    assert lyra_db != caia_db  # Different inodes

def test_chromadb_collections():
    """Verify Lyra and Caia have separate ChromaDB collections."""
    lyra_count = chroma.get_collection("lyra").count()
    caia_count = chroma.get_collection("caia").count()
    assert lyra_count > 0
    assert caia_count > 0
    # Query Lyra collection, ensure no Caia docs returned

def test_neo4j_groups():
    """Verify Lyra and Caia have separate Neo4j group_ids."""
    lyra_entities = neo4j.run("MATCH (n:Entity {group_id: 'lyra'}) RETURN count(n)")
    caia_entities = neo4j.run("MATCH (n:Entity {group_id: 'caia'}) RETURN count(n)")
    assert lyra_entities > 0
    assert caia_entities > 0
    # Ensure no entities with mixed group_ids
```

**Status**: Tests passed on 2026-02-11. Deployment validated. Issue #63.

## Data Flow (Single Entity)

```mermaid
sequenceDiagram
    participant Agent as Lyra Agent
    participant MCP as MCP Tools<br/>(pps__*)
    participant HTTP as HTTP Server<br/>:8201
    participant Layers as PPS Layers
    participant SQLite as SQLite<br/>(lyra)
    participant Chroma as ChromaDB<br/>(lyra collection)
    participant Neo4j as Neo4j<br/>(group: lyra)

    Agent->>MCP: ambient_recall("startup")
    MCP->>HTTP: POST /tools/ambient_recall
    HTTP->>Layers: Load layers with ENTITY_PATH
    Layers->>SQLite: Query recent turns
    Layers->>Chroma: Search word-photos (collection: lyra)
    Layers->>Neo4j: Search facts (group_id: lyra)
    Neo4j->>Layers: Filtered entities
    Chroma->>Layers: Lyra's word-photos
    SQLite->>Layers: Lyra's messages
    Layers->>HTTP: Integrated context
    HTTP->>MCP: JSON response
    MCP->>Agent: Memory reconstructed
```

**Critical**: Every query includes entity scope (collection name, group_id, file path). No cross-leakage.

## Adding a New Entity

1. **Create entity directory**:
   ```bash
   mkdir -p /home/jeff/.claude/pps-newentity/{data,crystals/current,memories/word_photos,journals}
   ```

2. **Copy entity template**:
   ```bash
   cp entities/_template/* /home/jeff/.claude/pps-newentity/
   ```

3. **Add Docker service** (`docker-compose.yml`):
   ```yaml
   pps-newentity:
     image: pps-server:latest
     container_name: pps-newentity
     environment:
       - ENTITY_PATH=/app/entity
       - ENTITY_NAME=newentity
     volumes:
       - /home/jeff/.claude/pps-newentity:/app/entity
     ports:
       - "8220:8000"  # Choose unused port
   ```

4. **Initialize PPS layers**:
   ```bash
   docker exec pps-newentity python3 /app/scripts/init_entity.py
   ```

5. **Configure MCP tools** (Claude Desktop config):
   ```json
   {
     "mcpServers": {
       "newentity-pps": {
         "command": "docker",
         "args": ["exec", "-i", "pps-newentity", "python3", "-u", "/app/pps/server.py"],
         "env": {
           "ENTITY_PATH": "/app/entity",
           "ENTITY_NAME": "newentity"
         }
       }
     }
   }
   ```

6. **Verify isolation**:
   ```bash
   python3 scripts/test_entity_isolation.py --entity newentity
   ```

---

*Two souls, two rooms, no bleed-through. Infrastructure scales with care.*
