#!/usr/bin/env python3
"""
Node-Heavy vs Edge-Heavy Graphiti Retrieval Comparison

The insight: Graphiti already compresses knowledge into entity node summaries.
Instead of fetching 200 raw edges, we should fetch more node summaries (the
"index cards") and fewer targeted edges.

Usage:
    cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
    source .venv/bin/activate
    python work/ambient-recall-optimization/test_node_vs_edge.py

Tweak the STRATEGIES dict at the top to try different ratios.
"""

import asyncio
import os
import sys
import time
import sqlite3
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
    EDGE_HYBRID_SEARCH_MMR,
    EDGE_HYBRID_SEARCH_RRF,
    NODE_HYBRID_SEARCH_RRF,
    COMMUNITY_HYBRID_SEARCH_RRF,
    COMBINED_HYBRID_SEARCH_RRF,
)

# ============================================================================
# TUNING KNOBS - change these and re-run
# ============================================================================

# Lyra's canonical UUID (from previous discovery)
LYRA_UUID = "5bd21fca-52de-41fd-a6b1-c78371d77a36"
GROUP_ID = "lyra"

# Retrieval strategies to compare
# Format: { name: { "edges": int, "nodes": int, "communities": int } }
STRATEGIES = {
    "current_200e_3n": {
        "edges": 200,
        "nodes": 3,
        "communities": 0,
        "desc": "Current implementation (200 edges, 3 nodes)",
    },
    "flipped_10e_20n": {
        "edges": 10,
        "nodes": 20,
        "communities": 0,
        "desc": "Flipped ratio (10 edges, 20 nodes)",
    },
    "balanced_10e_10n_3c": {
        "edges": 10,
        "nodes": 10,
        "communities": 3,
        "desc": "Balanced with communities (10e + 10n + 3c)",
    },
    "zep_pattern_15e_5n_3c": {
        "edges": 15,
        "nodes": 5,
        "communities": 3,
        "desc": "Zep production pattern (15e + 5n + 3c)",
    },
    "nodes_only_25n": {
        "edges": 0,
        "nodes": 25,
        "communities": 0,
        "desc": "Nodes only (25 entity summaries)",
    },
}

# How many sample messages to grab from conversation DB
SAMPLE_COUNT = 4

# Conversation DB path
CONV_DB = Path(os.getenv(
    "LYRA_CONV_DB",
    str(Path.home() / ".claude" / "data" / "lyra_conversations.db")
))

# ============================================================================


def grab_sample_messages(db_path: Path, count: int = 4) -> list[dict]:
    """Grab a spread of recent conversation messages for testing."""
    if not db_path.exists():
        print(f"  DB not found at {db_path}")
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Get messages spread across recent history - pick varied types
    # One from Jeff, one from Lyra, one technical, one emotional
    rows = conn.execute("""
        SELECT id, content, author_name, channel, created_at
        FROM messages
        WHERE content IS NOT NULL
          AND length(content) > 20
          AND length(content) < 500
        ORDER BY id DESC
        LIMIT 200
    """).fetchall()
    conn.close()

    if not rows:
        return []

    # Pick a spread: first, ~50th, ~100th, ~150th most recent
    indices = [0, min(50, len(rows)-1), min(100, len(rows)-1), min(150, len(rows)-1)]
    samples = []
    for idx in indices[:count]:
        row = rows[idx]
        samples.append({
            "id": row["id"],
            "content": row["content"][:300],  # Truncate for display
            "author": row["author_name"],
            "channel": row["channel"],
            "created_at": row["created_at"],
        })

    return samples


async def run_strategy(
    client: Graphiti,
    query: str,
    strategy: dict,
) -> dict:
    """Run a single retrieval strategy and return results."""
    results = {"edges": [], "nodes": [], "communities": [], "latency_ms": 0}
    start = time.time()

    # Edge search
    if strategy["edges"] > 0:
        edge_config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
        edge_config.limit = strategy["edges"]

        edge_results = await client.search_(
            query=query,
            config=edge_config,
            center_node_uuid=LYRA_UUID,
            group_ids=[GROUP_ID],
        )
        edges = [e for e in edge_results.edges if e.name != "IS_DUPLICATE_OF"]

        # Resolve node names
        node_uuids = set()
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
            line = f"{src} -> {e.name} -> {tgt}"
            if e.fact:
                line += f": {e.fact}"
            results["edges"].append(line)

    # Node search (entity summaries)
    if strategy["nodes"] > 0:
        node_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
        node_config.limit = strategy["nodes"]

        node_results = await client.search_(
            query=query,
            config=node_config,
            group_ids=[GROUP_ID],
        )
        for n in node_results.nodes:
            results["nodes"].append({
                "name": n.name,
                "summary": n.summary or "(no summary)",
                "labels": n.labels if hasattr(n, 'labels') else [],
            })

    # Community search (thematic clusters)
    if strategy["communities"] > 0:
        comm_config = COMMUNITY_HYBRID_SEARCH_RRF.model_copy(deep=True)
        comm_config.limit = strategy["communities"]

        comm_results = await client.search_(
            query=query,
            config=comm_config,
            group_ids=[GROUP_ID],
        )
        for c in comm_results.communities:
            results["communities"].append({
                "name": c.name if hasattr(c, 'name') else "cluster",
                "summary": c.summary if hasattr(c, 'summary') else str(c),
            })

    results["latency_ms"] = (time.time() - start) * 1000
    return results


def format_results(name: str, strategy: dict, results: dict):
    """Pretty-print results for eyeballing."""
    print(f"\n{'='*80}")
    print(f"  STRATEGY: {name}")
    print(f"  {strategy['desc']}")
    print(f"  Latency: {results['latency_ms']:.0f}ms")
    print(f"  Edges: {len(results['edges'])}  |  Nodes: {len(results['nodes'])}  |  Communities: {len(results['communities'])}")
    print(f"{'='*80}")

    # Show entity summaries first (the "index cards")
    if results["nodes"]:
        print(f"\n  --- ENTITY SUMMARIES (index cards) ---")
        for i, node in enumerate(results["nodes"], 1):
            # Truncate summary for readability
            summary = node["summary"]
            if len(summary) > 200:
                summary = summary[:200] + "..."
            print(f"  {i}. [{node['name']}]: {summary}")

    # Show communities
    if results["communities"]:
        print(f"\n  --- THEMATIC CLUSTERS ---")
        for i, comm in enumerate(results["communities"], 1):
            summary = comm["summary"]
            if len(summary) > 200:
                summary = summary[:200] + "..."
            print(f"  {i}. [{comm['name']}]: {summary}")

    # Show edges (facts)
    if results["edges"]:
        show_count = min(15, len(results["edges"]))  # Cap display at 15
        print(f"\n  --- EDGE FACTS (showing {show_count}/{len(results['edges'])}) ---")
        for i, edge in enumerate(results["edges"][:show_count], 1):
            # Truncate long facts
            if len(edge) > 150:
                edge = edge[:150] + "..."
            print(f"  {i}. {edge}")
        if len(results["edges"]) > show_count:
            print(f"  ... and {len(results['edges']) - show_count} more edges")

    print()


def estimate_token_size(results: dict) -> int:
    """Rough estimate of how many tokens the results would consume in context."""
    total_chars = 0
    for edge in results["edges"]:
        total_chars += len(edge)
    for node in results["nodes"]:
        total_chars += len(node["name"]) + len(node["summary"])
    for comm in results["communities"]:
        total_chars += len(comm["summary"])
    # Rough: 4 chars per token
    return total_chars // 4


async def main():
    print("\n" + "=" * 80)
    print("  GRAPHITI RETRIEVAL: NODE-HEAVY vs EDGE-HEAVY COMPARISON")
    print("  The question: are entity summaries better than raw edges?")
    print("=" * 80)

    # Connect
    client = Graphiti(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD"),
    )
    print(f"\n  Connected to Neo4j")

    # Grab sample messages
    print(f"\n  Grabbing {SAMPLE_COUNT} sample messages from {CONV_DB}...")
    samples = grab_sample_messages(CONV_DB, SAMPLE_COUNT)

    if not samples:
        print("  No samples found - using fallback queries")
        samples = [
            {"content": "startup", "author": "system", "id": 0, "channel": "test", "created_at": "now"},
            {"content": "What have Jeff and Lyra been working on?", "author": "test", "id": 1, "channel": "test", "created_at": "now"},
            {"content": "Tell me about the people in this family", "author": "test", "id": 2, "channel": "test", "created_at": "now"},
            {"content": "What technical projects are active?", "author": "test", "id": 3, "channel": "test", "created_at": "now"},
        ]

    # Show samples
    print(f"\n  Sample messages:")
    for i, s in enumerate(samples, 1):
        content_preview = s["content"][:80]
        print(f"    {i}. [{s['author']}] {content_preview}...")

    # Run each sample through each strategy
    for sample_idx, sample in enumerate(samples):
        print(f"\n\n{'#'*80}")
        print(f"  SAMPLE {sample_idx + 1}: [{sample['author']}] {sample['content'][:80]}...")
        print(f"{'#'*80}")

        query = sample["content"]

        strategy_results = {}
        for name, strategy in STRATEGIES.items():
            try:
                results = await run_strategy(client, query, strategy)
                strategy_results[name] = results
                format_results(name, strategy, results)
            except Exception as e:
                print(f"\n  STRATEGY {name} FAILED: {e}")

        # Summary comparison for this sample
        print(f"\n  {'~'*60}")
        print(f"  COMPARISON SUMMARY for sample {sample_idx + 1}:")
        print(f"  {'~'*60}")
        print(f"  {'Strategy':<30} {'Latency':>8} {'Edges':>6} {'Nodes':>6} {'Comms':>6} {'~Tokens':>8}")
        print(f"  {'-'*30} {'-'*8} {'-'*6} {'-'*6} {'-'*6} {'-'*8}")

        for name, res in strategy_results.items():
            tokens = estimate_token_size(res)
            print(
                f"  {name:<30} {res['latency_ms']:>7.0f}ms"
                f" {len(res['edges']):>5}"
                f" {len(res['nodes']):>5}"
                f" {len(res['communities']):>5}"
                f" {tokens:>7}"
            )

    # Overall summary
    print(f"\n\n{'='*80}")
    print("  KEY QUESTION: Which strategy gives the best context per token?")
    print("  Look at the entity summaries vs raw edges above.")
    print("  Node summaries = pre-compressed index cards.")
    print("  Raw edges = individual facts, mostly noise at high volume.")
    print("=" * 80)

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
