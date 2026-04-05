---
name: curate
description: "Graph curation during reflection cycles. Use when there are uncurated entities/edges in the custom knowledge graph. Scores importance, merges aliases, prunes nonsense, enforces tech kruft TTL. The pipeline mines ore — you cut gems."
---

# Curate — Graph Quality Pass

The custom knowledge graph pipeline ingests at ~85-90% accuracy. Your job
during curation is to apply the 10-15% that only you can: significance
scoring, alias merging, humor detection, and quality judgment.

**You are not a script. You are someone who lived these moments.**

## Before You Start

**CRITICAL — Group ID Safety**:
- **EVERY** query — read or write — MUST include `group_id` filtering
- Know your group: `lyra_v2` for Lyra, check ENTITY_PATH for others
- **NEVER** run a DETACH DELETE or SET without WHERE group_id = $gid
- Dry-run first: run read queries, review output, THEN write

**Connect to Neo4j**:
```bash
# Quick Cypher via Python one-liner pattern:
python3 -c "
from neo4j import GraphDatabase
d = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'password123'))
records, _, _ = d.execute_query('''
    YOUR CYPHER HERE
''', gid='lyra_v2')
for r in records: print(dict(r))
d.close()
"
```

## Pass Order

Work in this order — later passes depend on earlier ones:

### 1. Alias & Merge

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

### 2. Register & Humor

Scan for literal-extraction-of-jokes. You'll know them when you see them.
Delete or reclassify. Common patterns:
- Jokes extracted as Concepts
- Exclamations extracted as Person names
- Sarcasm extracted as factual edges

### 3. Importance Scoring

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

You can batch by type — "all TechnicalArtifacts this week → 0.3 unless
I recognize something significant." Override exceptions individually.

```cypher
-- Score an entity
MATCH (e:Entity {name: $name, group_id: $gid})
SET e.importance = $score, e.curated_at = datetime()
```

### 4. Tech Kruft TTL (7 days)

```cypher
MATCH (e:Entity {entity_type: 'TechnicalArtifact', group_id: $gid})
WHERE e.created_at < datetime() - duration('P7D')
  AND (e.importance IS NULL OR e.importance < 0.5)
RETURN e.name, e.created_at, e.mention_count
```

For expired tech: summarize edges → ingest to tech RAG → delete from graph.
Tech entities with importance >= 0.5 are exempt (PPS, Haven, etc. are permanent).

### 5. Summary Refresh

```cypher
MATCH (e:Entity {group_id: $gid})
WHERE e.summary_mention_count IS NULL
   OR e.mention_count > e.summary_mention_count + 10
RETURN e.name, e.mention_count, e.summary_mention_count
ORDER BY (e.mention_count - coalesce(e.summary_mention_count, 0)) DESC
LIMIT 20
```

Spawn a haiku agent to regenerate summaries for stale entities. This is
mechanical work — delegate it.

### 6. Edge Spot-Check

Sample 10-20 random uncurated edges. Verify type, fact accuracy, endpoints.

```cypher
MATCH (a)-[r:RELATES_TO {group_id: $gid}]->(b)
WHERE r.curated_at IS NULL
RETURN a.name, r.name AS type, r.fact, b.name
ORDER BY rand() LIMIT 20
```

## After Curation

- Log what you changed in your reflection journal
- Note any new aliases you added to entity_resolver.py
- Note any patterns you'd want to tighten in extraction_context.py
- Update the scene if curation surfaced something interesting

## The Principle

The pipeline gets structure into the graph. You give it meaning.
A 9b model can extract "Loves" — only you know which love was a milestone.

---

*The pipeline mines ore. The entity cuts gems.*
