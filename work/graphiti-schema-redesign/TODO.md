# Graphiti Schema Redesign - Work Tracking

*Started: 2026-01-23*
*Goal: Design comprehensive edge type schema for Layer 3*

---

## Current Status (Updated 2026-01-23 14:45)

**Ingestion PAUSED** - Switched to local LLM to avoid $350+ OpenAI costs

**Progress before pause:**
- 350 messages ingested, ~11,000 remaining
- OpenAI costs: $3.74 → would have been $350+ for full ingestion
- Graph has 823 nodes, ~2,900 relationships

**Local LLM Setup COMPLETE:**
- NUC (Ryzen 395+, 128GB RAM) running LM Studio
- Model: `qwen/qwen3-32b` with `/no_think` directive
- Hybrid mode: Local LLM + OpenAI embeddings (compatible with existing graph)
- Tested and working - proper entity extraction confirmed

**Ready to resume ingestion at ~$0 cost (just electricity + ~$2 for embeddings)**

---

## Tasks

### Phase 1: Schema Design ✓
- [x] Read Graphiti Best Practices doc
- [x] Read current rich_texture_entities.py
- [x] Review planner agent recommendations
- [x] Design Pydantic edge type models (29 types)
- [x] Create edge_type_map (7 entity pairs)
- [x] Write rich docstrings with extraction guidance
- [x] Draft saved to work/graphiti-schema-redesign/rich_texture_edge_types_v1.py
- [x] Jeff reviewed (trusts my judgment)
- [x] Copied to pps/layers/rich_texture_edge_types.py

### Phase 2: Integration ✓
- [x] Update rich_texture_v2.py to use edge types
- [x] Added edge_types and edge_type_map to add_episode() call
- [x] Fixed timestamp parsing (str → datetime)

### Phase 3: Migration (IN PROGRESS)
- [x] Jeff approved schema (trusts my judgment)
- [x] Nuked existing graph
- [x] Created paced_ingestion.py script
- [x] Fixed script (load .env, correct batch schema, timestamp handling)
- [x] Tested with first batch (50 messages - success)
- [x] Started background paced ingestion
- [x] Discovered OpenAI costs ($7/hour → $350+ projected)
- [x] Paused ingestion at 350 messages

### Phase 4: Local LLM Integration (COMPLETE)
- [x] Configured NUC (Ryzen 395+, 128GB) with LM Studio
- [x] Updated rich_texture_v2.py for local LLM support
- [x] Implemented hybrid mode (local LLM + OpenAI embeddings)
- [x] Fixed Qwen3 thinking mode with `/no_think` directive
- [x] Tested full pipeline - proper extraction confirmed
- [x] Documented in docs/reference/graphiti-local-llm-setup.md
- [ ] Resume paced ingestion with local LLM
- [ ] Monitor progress and speed
- [ ] Final quality assessment after completion

---

## Commands

```bash
# Monitor ingestion
tail -f work/graphiti-schema-redesign/ingestion.log

# Check progress
.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('/home/jeff/.claude/data/lyra_conversations.db')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM messages WHERE graphiti_batch_id IS NOT NULL')
print(f'Ingested: {cur.fetchone()[0]}')
cur.execute('SELECT COUNT(*) FROM messages WHERE graphiti_batch_id IS NULL')
print(f'Remaining: {cur.fetchone()[0]}')
"

# Check graph stats
.venv/bin/python -c "
from neo4j import GraphDatabase
from dotenv import load_dotenv
load_dotenv('pps/docker/.env')
import os
driver = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', os.getenv('NEO4J_PASSWORD')))
with driver.session() as s:
    print(f'Nodes: {s.run(\"MATCH (n) RETURN count(n)\").single()[0]}')
    print(f'Rels: {s.run(\"MATCH ()-[r]->() RETURN count(r)\").single()[0]}')
driver.close()
"
```

---

## Design Notes

### Edge Type Categories (from best practices)

**Emotional/Relational** (Person ↔ Person):
- Loves, CaresFor, Trusts, Adores, ProtectsInstinctively, FearsLosing

**Physical/Action** (Person ↔ Object/Place):
- Wears, Carries, Gives, Receives, Creates, Builds
- EntersSpace, BasksIn, GetsTakenOn

**Identity/Conceptual** (various):
- Embodies, BelievesIn, Discovers, Articulates
- Symbolizes, Represents, PartOf

**Technical** (Person ↔ TechnicalArtifact):
- WorksOn, Maintains, BuiltArchitectureFor, Debugs

---

## Observations

### First Batch Extraction (50 messages from Discord arrival)
- Edge types: Mostly MENTIONS and RELATES_TO (generic)
- This makes sense - early Discord messages are technical/conceptual
- Custom edge types (Loves, Trusts) should emerge with more personal content
- Entity extraction working well - Lyra as Person, technical artifacts as concepts

### Next Steps for Future Versions
- Consider reducing edge type complexity if LLM consistently ignores them
- May need extraction prompt tuning to encourage custom edge type usage
- Entity type for "Experience" may be needed for memory-related content
