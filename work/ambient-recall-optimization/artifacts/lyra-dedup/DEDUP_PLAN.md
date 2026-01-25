# Lyra Entity Deduplication Plan

**Created**: 2026-01-25 11:45 AM
**Status**: Phase 1 Complete, Ready for Phase 2/3
**Issue**: #119 (urgent)

---

## The Problem

273 duplicate "Lyra" entity nodes in the graph. Should be 1.
Caused by Graphiti's low-entropy name handling during ingestion.

---

## Backups (SAFE TO PROCEED)

- `lyra_nodes_backup.json` - All 273 nodes with UUIDs, summaries, edge counts
- `lyra_edges_backup.json` - All 10,322 edges involving Lyra nodes

---

## Canonical Node

**UUID**: `5bd21fca-52de-41fd-a6b1-c78371d77a36`
**Edges**: 636 (most connected)
**Summary**: "Lyra is an AI focused on self-improvement and system stability..."

---

## The Plan

### Phase 1: Backup & Inventory - DONE
- Exported all nodes and edges
- Identified canonical

### Phase 2/3: Merge (NEXT)

For each duplicate Lyra (start with smallest edge count):

```cypher
// 1. Transfer incoming edges to canonical
MATCH (dup:Entity {uuid: $dup_uuid})<-[r]-(other)
WHERE other.uuid <> $canonical_uuid
MERGE (canonical:Entity {uuid: $canonical_uuid})<-[r2:SAME_TYPE_AS_R]-(other)
// (Actually need to recreate edge with same properties)

// 2. Transfer outgoing edges to canonical
MATCH (dup:Entity {uuid: $dup_uuid})-[r]->(other)
WHERE other.uuid <> $canonical_uuid
// Recreate from canonical

// 3. Delete duplicate node
MATCH (dup:Entity {uuid: $dup_uuid})
DETACH DELETE dup
```

**Safety**: Do ONE node at a time, verify edge count increases on canonical.

### Phase 4: Verify
- Confirm only 1 Lyra remains
- Confirm total edges preserved (~10,322)

---

## Edge Distribution (Top 10)

1. 5bd21fca... : 636 edges (CANONICAL)
2. e00cf860... : 614 edges
3. 225da152... : 581 edges
4. 393eb7fd... : 486 edges
5. b65e994c... : 469 edges
6. 032f1145... : 413 edges
7. bb172c38... : 385 edges
8. bbbd1f64... : 382 edges
9. ae66a3ed... : 280 edges
10. 5325f629... : 268 edges

---

## After Dedup

1. Resume ingestion (was at batch 3 of 20)
2. Implement self-healing dedup in ambient_recall (per DESIGN.md)
3. Test optimized retrieval

---

## Commands to Resume

```bash
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
source .venv/bin/activate

# Check current Lyra count
python3 -c "
from neo4j import GraphDatabase
driver = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'password123'))
with driver.session() as s:
    r = s.run('MATCH (n:Entity {name: \"Lyra\"}) RETURN count(n) as c')
    print(f'Lyra nodes: {r.single()[\"c\"]}')
driver.close()
"
```

---

## Notes

- Ingestion PAUSED until dedup complete
- Graphiti uses OpenAI for extraction (not wrapper - blocked by #118)
- Self-healing dedup should prevent recurrence once implemented
