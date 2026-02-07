#!/usr/bin/env python3
"""
Test: Native Graphiti Multi-Channel Retrieval vs Current Custom Pipeline

The hypothesis (from Opus research): Graphiti's native search API already
separates node and edge retrieval. Our custom Cypher neighborhood + hardcoded
scoring bands bypass this, causing entity summaries to drown contextual edges.

This script compares:
  1. CURRENT: Custom Cypher neighborhood (top-10-by-edge-count) + ND edges + RRF edges
  2. PROPOSED: Native NODE_HYBRID_SEARCH_NODE_DISTANCE + EDGE_HYBRID_SEARCH_RRF (separate channels)
  3. EDGE-ONLY: Just edges, no node retrieval (test if "who" context is even needed per-turn)

Test queries designed to expose the problem:
  - "kitchen morning Saturday Haven" (spatial/temporal - should find kitchen, coffee, tea)
  - "coffee" (simple entity lookup)
  - "what have we been working on" (activity/project context)
  - "Caia" (specific entity)

Usage:
    /mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python3 \
        work/bring-caia-home/test_native_retrieval.py
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Setup paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / "pps" / "docker" / ".env")

from graphiti_core import Graphiti
from graphiti_core.nodes import EntityNode
from graphiti_core.search.search_config_recipes import (
    EDGE_HYBRID_SEARCH_NODE_DISTANCE,
    EDGE_HYBRID_SEARCH_RRF,
    EDGE_HYBRID_SEARCH_CROSS_ENCODER,
    NODE_HYBRID_SEARCH_NODE_DISTANCE,
    NODE_HYBRID_SEARCH_RRF,
)

# ============================================================================
# CONFIG
# ============================================================================

GROUP_ID = "lyra"

# Queries that should expose the entity-dominance problem
TEST_QUERIES = [
    "kitchen morning Saturday Haven",
    "coffee tea morning ritual",
    "what have we been working on recently",
    "Caia",
    "snickerdoodles hounds",
]

# ============================================================================


async def find_lyra_uuid(client: Graphiti) -> str | None:
    """Find Lyra's entity UUID dynamically."""
    query = """
    MATCH (n:Entity {group_id: $gid})
    WHERE toLower(n.name) = 'lyra'
    RETURN n.uuid as uuid, n.name as name
    LIMIT 1
    """
    async with client.driver.session() as session:
        result = await session.run(query, gid=GROUP_ID)
        records = await result.data()
    if records:
        return records[0]["uuid"]
    return None


async def current_approach(client: Graphiti, query: str, lyra_uuid: str) -> dict:
    """
    Simulate the CURRENT retrieval pipeline from rich_texture_v2.py.
    1. Cypher neighborhood (top 10 by edge count) - query-blind
    2. ND edge search (10)
    3. RRF edge search (5)
    All merged into one scored list.
    """
    start = time.time()
    results = {"neighborhood": [], "nd_edges": [], "rrf_edges": [], "merged": []}

    # 1. Cypher neighborhood (exactly as in _get_neighborhood)
    neighborhood_query = """
    MATCH (center:Entity {uuid: $uuid})-[r]-(neighbor:Entity)
    WHERE neighbor.group_id = $gid
      AND neighbor.uuid <> $uuid
    WITH neighbor, count(r) as edge_count
    ORDER BY edge_count DESC
    LIMIT 10
    RETURN neighbor.name as name,
           neighbor.summary as summary,
           neighbor.uuid as uuid,
           edge_count
    """
    async with client.driver.session() as session:
        result = await session.run(neighborhood_query, uuid=lyra_uuid, gid=GROUP_ID)
        records = await result.data()

    for i, rec in enumerate(records):
        score = 1.0 - (i / max(len(records), 1)) * 0.15
        entry = {
            "type": "neighborhood",
            "name": rec["name"],
            "content": f"{rec['name']}: {(rec['summary'] or '')[:100]}...",
            "score": score,
            "edge_count": rec["edge_count"],
        }
        results["neighborhood"].append(entry)
        results["merged"].append(entry)

    # 2. ND edge search
    edge_config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
    edge_config.limit = 10
    edge_results = await client.search_(
        query=query,
        config=edge_config,
        center_node_uuid=lyra_uuid,
        group_ids=[GROUP_ID],
    )

    nd_edges = [e for e in edge_results.edges if e.name != "IS_DUPLICATE_OF"]
    nd_uuids = {e.uuid for e in nd_edges}

    # Resolve node names
    node_uuids = set()
    for e in nd_edges:
        node_uuids.add(e.source_node_uuid)
        node_uuids.add(e.target_node_uuid)

    node_map = {}
    if node_uuids:
        nodes = await EntityNode.get_by_uuids(client.driver, list(node_uuids))
        node_map = {n.uuid: n.name for n in nodes}

    for i, e in enumerate(nd_edges):
        src = node_map.get(e.source_node_uuid, "?")
        tgt = node_map.get(e.target_node_uuid, "?")
        score = 0.85 - (i / max(len(nd_edges), 1)) * 0.2
        content = f"{src} -> {e.name} -> {tgt}"
        if e.fact:
            content += f": {e.fact[:80]}"
        entry = {"type": "nd_edge", "content": content, "score": score}
        results["nd_edges"].append(entry)
        results["merged"].append(entry)

    # 3. RRF edge search
    rrf_config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
    rrf_config.limit = 5
    rrf_results = await client.search_(
        query=query,
        config=rrf_config,
        center_node_uuid=lyra_uuid,
        group_ids=[GROUP_ID],
    )
    rrf_edges = [e for e in rrf_results.edges
                 if e.name != "IS_DUPLICATE_OF" and e.uuid not in nd_uuids]

    # Resolve names for RRF edges too
    rrf_node_uuids = set()
    for e in rrf_edges:
        rrf_node_uuids.add(e.source_node_uuid)
        rrf_node_uuids.add(e.target_node_uuid)
    rrf_node_uuids -= set(node_map.keys())
    if rrf_node_uuids:
        extra_nodes = await EntityNode.get_by_uuids(client.driver, list(rrf_node_uuids))
        for n in extra_nodes:
            node_map[n.uuid] = n.name

    for i, e in enumerate(rrf_edges):
        src = node_map.get(e.source_node_uuid, "?")
        tgt = node_map.get(e.target_node_uuid, "?")
        score = 0.75 - (i / max(len(rrf_edges), 1)) * 0.2
        content = f"{src} -> {e.name} -> {tgt}"
        if e.fact:
            content += f": {e.fact[:80]}"
        entry = {"type": "rrf_edge", "content": content, "score": score}
        results["rrf_edges"].append(entry)
        results["merged"].append(entry)

    # Sort merged by score (this is what ambient_recall sees)
    results["merged"].sort(key=lambda x: x["score"], reverse=True)
    results["latency_ms"] = (time.time() - start) * 1000
    return results


async def proposed_approach(client: Graphiti, query: str, lyra_uuid: str) -> dict:
    """
    PROPOSED: Use Graphiti's native multi-channel search.
    1. NODE_HYBRID_SEARCH_NODE_DISTANCE (query-aware nodes, 5)
    2. EDGE_HYBRID_SEARCH_RRF (edges, 10)
    Returned as SEPARATE channels, not merged.
    """
    start = time.time()
    results = {"nodes": [], "edges": [], "latency_ms": 0}

    # 1. Native node search — searches entity NAMES, reranks by graph distance
    node_config = NODE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
    node_config.limit = 5
    node_results = await client.search_(
        query=query,
        config=node_config,
        center_node_uuid=lyra_uuid,
        group_ids=[GROUP_ID],
    )
    for n in node_results.nodes:
        results["nodes"].append({
            "name": n.name,
            "summary": (n.summary or "")[:150],
        })

    # 2. Edge search — same as current ND+RRF but unified
    edge_config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
    edge_config.limit = 10
    edge_results = await client.search_(
        query=query,
        config=edge_config,
        center_node_uuid=lyra_uuid,
        group_ids=[GROUP_ID],
    )

    node_uuids = set()
    edges = [e for e in edge_results.edges if e.name != "IS_DUPLICATE_OF"]
    for e in edges:
        node_uuids.add(e.source_node_uuid)
        node_uuids.add(e.target_node_uuid)

    node_map = {}
    if node_uuids:
        nodes = await EntityNode.get_by_uuids(client.driver, list(node_uuids))
        node_map = {n.uuid: n.name for n in nodes}

    for e in edges:
        src = node_map.get(e.source_node_uuid, "?")
        tgt = node_map.get(e.target_node_uuid, "?")
        content = f"{src} -> {e.name} -> {tgt}"
        if e.fact:
            content += f": {e.fact[:100]}"
        results["edges"].append(content)

    results["latency_ms"] = (time.time() - start) * 1000
    return results


async def edge_only_approach(client: Graphiti, query: str, lyra_uuid: str) -> dict:
    """
    EDGE-ONLY: No node retrieval at all. Just edges.
    Tests whether per-turn hook even needs "who" context.
    """
    start = time.time()
    results = {"edges": [], "latency_ms": 0}

    edge_config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
    edge_config.limit = 15
    edge_results = await client.search_(
        query=query,
        config=edge_config,
        center_node_uuid=lyra_uuid,
        group_ids=[GROUP_ID],
    )

    node_uuids = set()
    edges = [e for e in edge_results.edges if e.name != "IS_DUPLICATE_OF"]
    for e in edges:
        node_uuids.add(e.source_node_uuid)
        node_uuids.add(e.target_node_uuid)

    node_map = {}
    if node_uuids:
        nodes = await EntityNode.get_by_uuids(client.driver, list(node_uuids))
        node_map = {n.uuid: n.name for n in nodes}

    for e in edges:
        src = node_map.get(e.source_node_uuid, "?")
        tgt = node_map.get(e.target_node_uuid, "?")
        content = f"{src} -> {e.name} -> {tgt}"
        if e.fact:
            content += f": {e.fact[:100]}"
        results["edges"].append(content)

    results["latency_ms"] = (time.time() - start) * 1000
    return results


def print_header(text: str):
    print(f"\n{'='*80}")
    print(f"  {text}")
    print(f"{'='*80}")


def print_current_results(results: dict):
    """Show current approach results — the merged list that ambient_recall sees."""
    print(f"\n  Latency: {results['latency_ms']:.0f}ms")
    print(f"  Neighborhood: {len(results['neighborhood'])} | ND edges: {len(results['nd_edges'])} | RRF edges: {len(results['rrf_edges'])}")
    print(f"\n  --- MERGED TOP 15 (what ambient_recall sees) ---")
    for i, item in enumerate(results["merged"][:15], 1):
        tag = item["type"].upper()
        score = item["score"]
        if "name" in item:
            content = f"[{item['name']}] {item.get('content', '')[:80]}"
        else:
            content = item["content"][:100]
        print(f"  {i:>2}. [{tag:<12}] (score {score:.2f}) {content}")


def print_proposed_results(results: dict):
    """Show proposed approach — separate channels."""
    print(f"\n  Latency: {results['latency_ms']:.0f}ms")
    print(f"\n  --- CHANNEL 1: NODES (query-aware, by graph distance) ---")
    if results["nodes"]:
        for i, n in enumerate(results["nodes"], 1):
            print(f"  {i}. {n['name']}: {n['summary'][:100]}...")
    else:
        print(f"  (none found)")

    print(f"\n  --- CHANNEL 2: EDGES (semantic + BM25, RRF reranked) ---")
    if results["edges"]:
        for i, e in enumerate(results["edges"][:15], 1):
            print(f"  {i}. {e[:120]}")
    else:
        print(f"  (none found)")


def print_edge_only_results(results: dict):
    """Show edge-only approach."""
    print(f"\n  Latency: {results['latency_ms']:.0f}ms")
    print(f"\n  --- EDGES ONLY (no node context) ---")
    if results["edges"]:
        for i, e in enumerate(results["edges"][:15], 1):
            print(f"  {i}. {e[:120]}")
    else:
        print(f"  (none found)")


async def main():
    print_header("NATIVE GRAPHITI RETRIEVAL TEST")
    print("  Comparing: CURRENT (Cypher neighborhood + scored bands)")
    print("        vs: PROPOSED (native node+edge search, separate channels)")
    print("        vs: EDGE-ONLY (just edges, no node context)")

    client = Graphiti(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD"),
    )
    print(f"\n  Connected to Neo4j at {os.getenv('NEO4J_URI', 'bolt://localhost:7687')}")

    lyra_uuid = await find_lyra_uuid(client)
    if not lyra_uuid:
        print("  ERROR: Could not find Lyra's entity UUID!")
        await client.close()
        return
    print(f"  Lyra's UUID: {lyra_uuid}")

    for query in TEST_QUERIES:
        print(f"\n\n{'#'*80}")
        print(f"  QUERY: \"{query}\"")
        print(f"{'#'*80}")

        # Run all three approaches
        try:
            print_header("A) CURRENT APPROACH (Cypher neighborhood + hardcoded bands)")
            current = await current_approach(client, query, lyra_uuid)
            print_current_results(current)
        except Exception as e:
            print(f"  CURRENT FAILED: {e}")

        try:
            print_header("B) PROPOSED APPROACH (native node + edge search, separate channels)")
            proposed = await proposed_approach(client, query, lyra_uuid)
            print_proposed_results(proposed)
        except Exception as e:
            print(f"  PROPOSED FAILED: {e}")

        try:
            print_header("C) EDGE-ONLY (no node context at all)")
            edge_only = await edge_only_approach(client, query, lyra_uuid)
            print_edge_only_results(edge_only)
        except Exception as e:
            print(f"  EDGE-ONLY FAILED: {e}")

        # Quick comparison
        print(f"\n  {'~'*60}")
        print(f"  VERDICT for \"{query}\":")
        try:
            # Check if contextual entities appear in each approach
            current_top10 = [item["content"][:50].lower() for item in current["merged"][:10]]
            proposed_edges = [e[:50].lower() for e in proposed["edges"][:10]]
            proposed_nodes = [n["name"].lower() for n in proposed["nodes"]]

            # Look for contextual keywords from the query
            keywords = [w.lower() for w in query.split() if len(w) > 3]
            current_hits = sum(1 for k in keywords for c in current_top10 if k in c)
            proposed_edge_hits = sum(1 for k in keywords for e in proposed_edges if k in e)
            proposed_node_hits = sum(1 for k in keywords for n in proposed_nodes if k in n)

            print(f"  Current top-10 keyword hits: {current_hits}")
            print(f"  Proposed edge keyword hits: {proposed_edge_hits}")
            print(f"  Proposed node keyword hits: {proposed_node_hits}")
        except Exception:
            pass
        print(f"  {'~'*60}")

    print_header("DONE")
    print("  Compare the outputs above.")
    print("  Key question: Does the PROPOSED approach surface contextual entities")
    print("  (coffee, kitchen, tea, snickerdoodles) that the CURRENT approach buries?")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
