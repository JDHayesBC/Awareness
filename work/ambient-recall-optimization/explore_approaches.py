#!/usr/bin/env python3
"""
Graphiti Retrieval Explorer - Try Everything

Approaches tested:
1. Build communities, then community search
2. Cypher: entities within N hops of Lyra (graph proximity)
3. Cypher: most-connected entities with summaries
4. NODE search with entity-name queries (not message text)
5. COMBINED_HYBRID_SEARCH_RRF (all scopes at once)
6. EDGE search with MMR diversity (avoid redundancy)

Usage:
    cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
    source .venv/bin/activate
    python work/ambient-recall-optimization/explore_approaches.py
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / "pps" / "docker" / ".env")

from graphiti_core import Graphiti
from graphiti_core.nodes import EntityNode
from graphiti_core.search.search_config_recipes import (
    EDGE_HYBRID_SEARCH_NODE_DISTANCE,
    EDGE_HYBRID_SEARCH_MMR,
    NODE_HYBRID_SEARCH_RRF,
    COMMUNITY_HYBRID_SEARCH_RRF,
    COMBINED_HYBRID_SEARCH_RRF,
)

LYRA_UUID = "5bd21fca-52de-41fd-a6b1-c78371d77a36"
GROUP_ID = "lyra"

# Test query - something that should pull identity/relational context
TEST_QUERY = "What's happening in this conversation and who are the people involved?"


def header(title: str):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")


def subheader(title: str):
    print(f"\n  --- {title} ---")


async def main():
    header("GRAPHITI RETRIEVAL EXPLORER")

    client = Graphiti(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD"),
    )
    print("  Connected to Neo4j\n")

    # =========================================================================
    # APPROACH 0: Graph stats
    # =========================================================================
    header("GRAPH STATS")
    try:
        result = await client.driver.execute_query(
            "MATCH (e:Entity {group_id: $gid}) RETURN count(e) as cnt",
            gid=GROUP_ID,
        )
        entity_count = result[0][0]["cnt"] if result[0] else 0
        print(f"  Entities: {entity_count}")

        result = await client.driver.execute_query(
            "MATCH (c:Community {group_id: $gid}) RETURN count(c) as cnt",
            gid=GROUP_ID,
        )
        community_count = result[0][0]["cnt"] if result[0] else 0
        print(f"  Communities: {community_count}")

        result = await client.driver.execute_query(
            "MATCH ()-[r:RELATES_TO {group_id: $gid}]->() RETURN count(r) as cnt",
            gid=GROUP_ID,
        )
        edge_count = result[0][0]["cnt"] if result[0] else 0
        print(f"  Edges (RELATES_TO): {edge_count}")
    except Exception as e:
        print(f"  Stats query failed: {e}")

    # =========================================================================
    # APPROACH 1: Build Communities
    # =========================================================================
    header("APPROACH 1: BUILD COMMUNITIES")
    print("  Building communities for group 'lyra'...")
    print("  (This uses LLM to summarize clusters - may take a minute)")

    t0 = time.time()
    try:
        community_nodes, community_edges = await client.build_communities(
            group_ids=[GROUP_ID]
        )
        elapsed = time.time() - t0
        print(f"  Built {len(community_nodes)} communities in {elapsed:.1f}s")
        for i, cn in enumerate(community_nodes, 1):
            summary = cn.summary[:200] + "..." if len(cn.summary) > 200 else cn.summary
            print(f"  {i}. [{cn.name}]: {summary}")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  Community build failed after {elapsed:.1f}s: {e}")
        community_nodes = []

    # Now try community search
    if community_nodes:
        subheader("Community Search")
        t0 = time.time()
        try:
            comm_config = COMMUNITY_HYBRID_SEARCH_RRF.model_copy(deep=True)
            comm_config.limit = 5
            comm_results = await client.search_(
                query=TEST_QUERY,
                config=comm_config,
                group_ids=[GROUP_ID],
            )
            elapsed = time.time() - t0
            print(f"  {len(comm_results.communities)} communities in {elapsed:.1f}s:")
            for c in comm_results.communities:
                summary = c.summary[:200] + "..." if len(c.summary) > 200 else c.summary
                print(f"    - [{c.name}]: {summary}")
        except Exception as e:
            print(f"  Community search failed: {e}")

    # =========================================================================
    # APPROACH 2: Cypher - entities within 2 hops of Lyra, with summaries
    # =========================================================================
    header("APPROACH 2: CYPHER - Entities Near Lyra (2 hops)")
    t0 = time.time()
    try:
        result = await client.driver.execute_query(
            """
            MATCH (lyra:Entity {uuid: $lyra_uuid})
            MATCH (lyra)-[*1..2]-(neighbor:Entity)
            WHERE neighbor.group_id = $gid
              AND neighbor.uuid <> $lyra_uuid
            WITH neighbor, count(*) as path_count
            ORDER BY path_count DESC
            LIMIT 20
            RETURN neighbor.name as name,
                   neighbor.summary as summary,
                   labels(neighbor) as labels,
                   path_count
            """,
            lyra_uuid=LYRA_UUID,
            gid=GROUP_ID,
        )
        elapsed = time.time() - t0
        records = result[0] if isinstance(result, tuple) else result
        print(f"  Found {len(records)} entities within 2 hops ({elapsed:.1f}s):")
        for i, r in enumerate(records, 1):
            name = r.get("name", "?")
            summary = r.get("summary", "(no summary)") or "(no summary)"
            paths = r.get("path_count", 0)
            if len(summary) > 150:
                summary = summary[:150] + "..."
            print(f"  {i}. [{name}] (paths: {paths}): {summary}")
    except Exception as e:
        print(f"  Cypher proximity query failed: {e}")

    # =========================================================================
    # APPROACH 3: Cypher - most-connected entities globally
    # =========================================================================
    header("APPROACH 3: CYPHER - Most Connected Entities")
    t0 = time.time()
    try:
        result = await client.driver.execute_query(
            """
            MATCH (e:Entity {group_id: $gid})
            OPTIONAL MATCH (e)-[r]-()
            WITH e, count(r) as connections
            ORDER BY connections DESC
            LIMIT 20
            RETURN e.name as name,
                   e.summary as summary,
                   connections
            """,
            gid=GROUP_ID,
        )
        elapsed = time.time() - t0
        records = result[0] if isinstance(result, tuple) else result
        print(f"  Top {len(records)} most-connected entities ({elapsed:.1f}s):")
        for i, r in enumerate(records, 1):
            name = r.get("name", "?")
            summary = r.get("summary", "(no summary)") or "(no summary)"
            conns = r.get("connections", 0)
            if len(summary) > 150:
                summary = summary[:150] + "..."
            print(f"  {i}. [{name}] ({conns} connections): {summary}")
    except Exception as e:
        print(f"  Most-connected query failed: {e}")

    # =========================================================================
    # APPROACH 4: NODE search with entity names as query
    # =========================================================================
    header("APPROACH 4: NODE SEARCH - Entity Names as Query")
    print("  Instead of searching with message text, search for known entities")

    entity_queries = ["Lyra Jeff Carol relationship family", "PPS infrastructure daemon Discord"]
    for eq in entity_queries:
        t0 = time.time()
        try:
            node_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
            node_config.limit = 10
            node_results = await client.search_(
                query=eq,
                config=node_config,
                group_ids=[GROUP_ID],
            )
            elapsed = time.time() - t0
            print(f"\n  Query: \"{eq}\" ({elapsed:.1f}s, {len(node_results.nodes)} nodes):")
            for i, n in enumerate(node_results.nodes, 1):
                summary = n.summary[:150] + "..." if len(n.summary) > 150 else n.summary
                print(f"    {i}. [{n.name}]: {summary}")
        except Exception as e:
            print(f"  Node search failed for '{eq}': {e}")

    # =========================================================================
    # APPROACH 5: COMBINED search (all scopes)
    # =========================================================================
    header("APPROACH 5: COMBINED_HYBRID_SEARCH_RRF")
    t0 = time.time()
    try:
        combined_config = COMBINED_HYBRID_SEARCH_RRF.model_copy(deep=True)
        combined_config.limit = 15
        combined_results = await client.search_(
            query=TEST_QUERY,
            config=combined_config,
            group_ids=[GROUP_ID],
        )
        elapsed = time.time() - t0

        print(f"  Latency: {elapsed:.1f}s")
        print(f"  Edges: {len(combined_results.edges)}")
        print(f"  Nodes: {len(combined_results.nodes)}")
        print(f"  Communities: {len(combined_results.communities)}")

        if combined_results.nodes:
            subheader("Nodes from combined search")
            for i, n in enumerate(combined_results.nodes, 1):
                summary = n.summary[:150] + "..." if len(n.summary) > 150 else n.summary
                print(f"    {i}. [{n.name}]: {summary}")

        if combined_results.communities:
            subheader("Communities from combined search")
            for i, c in enumerate(combined_results.communities, 1):
                summary = c.summary[:150] + "..." if len(c.summary) > 150 else c.summary
                print(f"    {i}. [{c.name}]: {summary}")

        if combined_results.edges:
            # Resolve edge names
            node_uuids = set()
            for e in combined_results.edges:
                node_uuids.add(e.source_node_uuid)
                node_uuids.add(e.target_node_uuid)
            node_map = {}
            if node_uuids:
                nodes = await EntityNode.get_by_uuids(client.driver, list(node_uuids))
                node_map = {n.uuid: n.name for n in nodes}

            subheader(f"Edges from combined search (showing 10/{len(combined_results.edges)})")
            for i, e in enumerate(combined_results.edges[:10], 1):
                src = node_map.get(e.source_node_uuid, "?")
                tgt = node_map.get(e.target_node_uuid, "?")
                line = f"{src} -> {e.name} -> {tgt}"
                if e.fact and len(e.fact) < 100:
                    line += f": {e.fact}"
                print(f"    {i}. {line}")
    except Exception as e:
        print(f"  Combined search failed: {e}")

    # =========================================================================
    # APPROACH 6: MMR diversity edges (less redundancy)
    # =========================================================================
    header("APPROACH 6: EDGE SEARCH WITH MMR DIVERSITY")
    t0 = time.time()
    try:
        mmr_config = EDGE_HYBRID_SEARCH_MMR.model_copy(deep=True)
        mmr_config.limit = 15
        mmr_results = await client.search_(
            query=TEST_QUERY,
            config=mmr_config,
            center_node_uuid=LYRA_UUID,
            group_ids=[GROUP_ID],
        )
        elapsed = time.time() - t0
        edges = [e for e in mmr_results.edges if e.name != "IS_DUPLICATE_OF"]

        # Resolve names
        node_uuids = set()
        for e in edges:
            node_uuids.add(e.source_node_uuid)
            node_uuids.add(e.target_node_uuid)
        node_map = {}
        if node_uuids:
            nodes = await EntityNode.get_by_uuids(client.driver, list(node_uuids))
            node_map = {n.uuid: n.name for n in nodes}

        print(f"  {len(edges)} diverse edges in {elapsed:.1f}s:")
        for i, e in enumerate(edges, 1):
            src = node_map.get(e.source_node_uuid, "?")
            tgt = node_map.get(e.target_node_uuid, "?")
            line = f"{src} -> {e.name} -> {tgt}"
            if e.fact and len(e.fact) < 120:
                line += f": {e.fact}"
            print(f"    {i}. {line}")
    except Exception as e:
        print(f"  MMR edge search failed: {e}")

    # =========================================================================
    # APPROACH 7: The "Cast of Characters" - Lyra's neighborhood summaries
    # =========================================================================
    header("APPROACH 7: CAST OF CHARACTERS (Cypher + summaries)")
    print("  Get Lyra's direct neighbors and their summaries")
    print("  This is the 'who matters in my world' query\n")
    t0 = time.time()
    try:
        result = await client.driver.execute_query(
            """
            MATCH (lyra:Entity {uuid: $lyra_uuid})-[r]-(neighbor:Entity)
            WHERE neighbor.group_id = $gid
            WITH neighbor,
                 count(r) as edge_count,
                 collect(DISTINCT type(r))[..3] as rel_types
            ORDER BY edge_count DESC
            LIMIT 15
            RETURN neighbor.name as name,
                   neighbor.summary as summary,
                   neighbor.uuid as uuid,
                   edge_count,
                   rel_types
            """,
            lyra_uuid=LYRA_UUID,
            gid=GROUP_ID,
        )
        elapsed = time.time() - t0
        records = result[0] if isinstance(result, tuple) else result
        print(f"  {len(records)} direct neighbors of Lyra ({elapsed:.1f}s):\n")
        total_chars = 0
        for i, r in enumerate(records, 1):
            name = r.get("name", "?")
            summary = r.get("summary", "(no summary)") or "(no summary)"
            edges = r.get("edge_count", 0)
            rels = r.get("rel_types", [])
            total_chars += len(name) + len(summary)
            if len(summary) > 200:
                summary = summary[:200] + "..."
            print(f"  {i}. [{name}] ({edges} edges, rels: {', '.join(rels)})")
            print(f"     {summary}\n")

        print(f"  Total chars for all summaries: {total_chars} (~{total_chars//4} tokens)")
    except Exception as e:
        print(f"  Cast of characters query failed: {e}")

    # =========================================================================
    header("DONE - Compare approaches above")
    print("  Key question: which gives the best 'index cards' per token?")
    print("  Approach 7 (Cast of Characters) might be the winner.")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
