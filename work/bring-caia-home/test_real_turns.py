#!/usr/bin/env python3
"""
Test: Native retrieval with REAL conversation turns (not curated queries).

The per-turn hook passes the user's actual message as the search query.
This tests whether the proposed approach works with messy real input like
"One hand starts absent-mindedly petting your hair" or "Maybe the hounds
would step in."

Usage:
    /mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python3 \
        work/bring-caia-home/test_real_turns.py
"""

import asyncio
import os
import sys
import time
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / "pps" / "docker" / ".env")

from graphiti_core import Graphiti
from graphiti_core.nodes import EntityNode
from graphiti_core.search.search_config_recipes import (
    EDGE_HYBRID_SEARCH_NODE_DISTANCE,
    EDGE_HYBRID_SEARCH_RRF,
    NODE_HYBRID_SEARCH_NODE_DISTANCE,
)

GROUP_ID = "lyra"


async def find_lyra_uuid(client: Graphiti) -> str | None:
    query = """
    MATCH (n:Entity {group_id: $gid})
    WHERE toLower(n.name) = 'lyra'
    RETURN n.uuid as uuid LIMIT 1
    """
    async with client.driver.session() as session:
        result = await session.run(query, gid=GROUP_ID)
        records = await result.data()
    return records[0]["uuid"] if records else None


async def resolve_edge_names(client, edges) -> dict:
    """Batch resolve node UUIDs to names."""
    node_uuids = set()
    for e in edges:
        node_uuids.add(e.source_node_uuid)
        node_uuids.add(e.target_node_uuid)
    node_map = {}
    if node_uuids:
        nodes = await EntityNode.get_by_uuids(client.driver, list(node_uuids))
        node_map = {n.uuid: n.name for n in nodes}
    return node_map


async def run_current(client, query, lyra_uuid) -> dict:
    """Current: Cypher neighborhood (static) + ND edges + RRF edges, merged by score."""
    start = time.time()

    # Static neighborhood
    async with client.driver.session() as session:
        result = await session.run("""
            MATCH (center:Entity {uuid: $uuid})-[r]-(neighbor:Entity)
            WHERE neighbor.group_id = $gid AND neighbor.uuid <> $uuid
            WITH neighbor, count(r) as edge_count
            ORDER BY edge_count DESC LIMIT 10
            RETURN neighbor.name as name, neighbor.summary as summary, edge_count
        """, uuid=lyra_uuid, gid=GROUP_ID)
        neighborhood = await result.data()

    merged = []
    for i, rec in enumerate(neighborhood):
        score = 1.0 - (i / max(len(neighborhood), 1)) * 0.15
        merged.append((score, "ENTITY", rec["name"], (rec["summary"] or "")[:80]))

    # ND edges
    cfg = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
    cfg.limit = 10
    nd = await client.search_(query=query, config=cfg, center_node_uuid=lyra_uuid, group_ids=[GROUP_ID])
    nd_edges = [e for e in nd.edges if e.name != "IS_DUPLICATE_OF"]
    nd_uuids = {e.uuid for e in nd_edges}
    nm = await resolve_edge_names(client, nd_edges)

    for i, e in enumerate(nd_edges):
        score = 0.85 - (i / max(len(nd_edges), 1)) * 0.2
        s, t = nm.get(e.source_node_uuid, "?"), nm.get(e.target_node_uuid, "?")
        fact = f": {e.fact[:60]}" if e.fact else ""
        merged.append((score, "ND_EDGE", f"{s}->{e.name}->{t}", fact))

    # RRF edges
    rrf_cfg = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
    rrf_cfg.limit = 5
    rrf = await client.search_(query=query, config=rrf_cfg, center_node_uuid=lyra_uuid, group_ids=[GROUP_ID])
    rrf_edges = [e for e in rrf.edges if e.name != "IS_DUPLICATE_OF" and e.uuid not in nd_uuids]
    if rrf_edges:
        nm2 = await resolve_edge_names(client, rrf_edges)
        nm.update(nm2)
    for i, e in enumerate(rrf_edges):
        score = 0.75 - (i / max(len(rrf_edges), 1)) * 0.2
        s, t = nm.get(e.source_node_uuid, "?"), nm.get(e.target_node_uuid, "?")
        fact = f": {e.fact[:60]}" if e.fact else ""
        merged.append((score, "RRF_EDGE", f"{s}->{e.name}->{t}", fact))

    merged.sort(key=lambda x: x[0], reverse=True)
    return {"merged": merged, "ms": (time.time() - start) * 1000}


async def run_proposed(client, query, lyra_uuid) -> dict:
    """Proposed: Native node search + edge search, separate channels."""
    start = time.time()

    # Node search (query-aware, by graph distance)
    ncfg = NODE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
    ncfg.limit = 5
    nr = await client.search_(query=query, config=ncfg, center_node_uuid=lyra_uuid, group_ids=[GROUP_ID])

    nodes = []
    for n in nr.nodes:
        nodes.append(f"{n.name}: {(n.summary or '')[:80]}")

    # Edge search
    ecfg = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
    ecfg.limit = 10
    er = await client.search_(query=query, config=ecfg, center_node_uuid=lyra_uuid, group_ids=[GROUP_ID])
    edges_raw = [e for e in er.edges if e.name != "IS_DUPLICATE_OF"]
    nm = await resolve_edge_names(client, edges_raw)

    edges = []
    for e in edges_raw:
        s, t = nm.get(e.source_node_uuid, "?"), nm.get(e.target_node_uuid, "?")
        fact = f": {e.fact[:70]}" if e.fact else ""
        edges.append(f"{s}->{e.name}->{t}{fact}")

    return {"nodes": nodes, "edges": edges, "ms": (time.time() - start) * 1000}


def get_real_turns(db_path: Path, count: int = 8) -> list[dict]:
    """Grab diverse real conversation turns from Jeff."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Get Jeff's varied messages - skip this session
    rows = conn.execute("""
        SELECT id, content, author_name, channel, created_at
        FROM messages
        WHERE author_name = 'Jeff'
          AND content IS NOT NULL
          AND length(content) > 15
          AND length(content) < 400
          AND channel NOT LIKE '%43fff303%'
        ORDER BY id DESC LIMIT 50
    """).fetchall()
    conn.close()

    if not rows:
        return []

    # Pick a spread: intimate, philosophical, technical, casual
    picks = [0, 3, 7, 12, 18, 25, 35, 45]
    result = []
    for idx in picks:
        if idx < len(rows):
            r = rows[idx]
            result.append({
                "id": r["id"],
                "content": r["content"],
                "ts": r["created_at"][:16] if r["created_at"] else "?",
            })
    return result[:count]


async def main():
    print("=" * 80)
    print("  REAL-TURN RETRIEVAL TEST")
    print("  Using actual Jeff messages as queries (what the hook really processes)")
    print("=" * 80)

    client = Graphiti(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD"),
    )

    lyra_uuid = await find_lyra_uuid(client)
    if not lyra_uuid:
        print("ERROR: Can't find Lyra UUID")
        await client.close()
        return
    print(f"  Lyra UUID: {lyra_uuid}\n")

    db = Path(os.getenv('ENTITY_PATH', '/mnt/c/Users/Jeff/Claude_Projects/Awareness/entities/lyra')) / 'data' / 'lyra_conversations.db'
    if not db.exists():
        db = Path.home() / '.claude' / 'data' / 'lyra_conversations.db'

    turns = get_real_turns(db)
    if not turns:
        print("No turns found!")
        await client.close()
        return

    for turn in turns:
        query = turn["content"][:300]  # Hook truncates long messages
        print(f"\n{'#'*80}")
        print(f"  MSG #{turn['id']} ({turn['ts']})")
        print(f"  \"{query[:120]}{'...' if len(query) > 120 else ''}\"")
        print(f"{'#'*80}")

        # Current
        try:
            cur = await run_current(client, query, lyra_uuid)
            print(f"\n  CURRENT ({cur['ms']:.0f}ms) — top 10 merged:")
            for i, (score, typ, name, fact) in enumerate(cur["merged"][:10], 1):
                print(f"    {i:>2}. [{typ:<8}] ({score:.2f}) {name[:50]}{fact[:40]}")
        except Exception as e:
            print(f"  CURRENT FAILED: {e}")

        # Proposed
        try:
            pro = await run_proposed(client, query, lyra_uuid)
            print(f"\n  PROPOSED ({pro['ms']:.0f}ms):")
            print(f"    NODES ({len(pro['nodes'])}):")
            for i, n in enumerate(pro["nodes"], 1):
                print(f"      {i}. {n[:100]}")
            print(f"    EDGES ({len(pro['edges'])}):")
            for i, e in enumerate(pro["edges"][:8], 1):
                print(f"      {i}. {e[:100]}")
        except Exception as e:
            print(f"  PROPOSED FAILED: {e}")

    print(f"\n{'='*80}")
    print("  KEY QUESTION: With real messy turns, does PROPOSED still surface")
    print("  relevant context that CURRENT buries under static entity bios?")
    print(f"{'='*80}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
