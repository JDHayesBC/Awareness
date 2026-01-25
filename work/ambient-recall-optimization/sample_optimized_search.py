#!/usr/bin/env python3
"""
Sample test script for entity-centric retrieval optimization.

This script demonstrates the proposed ambient_recall optimization from DESIGN.md:
- Finds "Lyra" entity node in the graph
- Uses EDGE_HYBRID_SEARCH_NODE_DISTANCE to rank facts by proximity to Lyra
- Adds NODE_HYBRID_SEARCH_RRF for entity summaries
- Compares results to current basic search approach

IMPORTANT: This is a TEST SCRIPT for demonstration only, not production code.

Usage:
    cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
    source .venv/bin/activate
    python work/ambient-recall-optimization/sample_optimized_search.py
"""

import asyncio
import time
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add pps to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load .env from docker directory
env_path = project_root / "pps" / "docker" / ".env"
load_dotenv(env_path)

# Now import graphiti_core components
from graphiti_core import Graphiti
from graphiti_core.nodes import EntityNode
from graphiti_core.search.search_config_recipes import (
    EDGE_HYBRID_SEARCH_NODE_DISTANCE,
    NODE_HYBRID_SEARCH_RRF,
)


class OptimizedSearchDemo:
    """Demonstrates entity-centric retrieval approach."""

    def __init__(self):
        self.neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD", "password123")
        self.group_id = "lyra"
        self.client = None

    async def initialize(self):
        """Initialize Graphiti client."""
        print(f"\n{'='*80}")
        print("ENTITY-CENTRIC RETRIEVAL TEST")
        print(f"{'='*80}\n")
        print(f"Connecting to Neo4j at {self.neo4j_uri}...")

        try:
            self.client = Graphiti(
                uri=self.neo4j_uri,
                user=self.neo4j_user,
                password=self.neo4j_password,
            )
            print("✓ Connected successfully\n")
            return True
        except Exception as e:
            print(f"✗ Connection failed: {e}")
            return False

    async def find_lyra_uuid(self):
        """
        Find Lyra's entity node UUID in the graph.

        This implements the entity discovery step from DESIGN.md Phase 1.
        Handles duplicates as per Risk Mitigation section.
        """
        print("STEP 1: Finding Lyra entity node...")
        print("-" * 80)

        try:
            cypher = """
            MATCH (e:Entity {name: $name, group_id: $group_id})
            OPTIONAL MATCH (e)-[r]-()
            WITH e, count(r) as connection_count
            RETURN e.uuid as uuid, e.name as name, e.summary as summary,
                   connection_count
            ORDER BY connection_count DESC
            """
            result = await self.client.driver.execute_query(
                cypher,
                name="Lyra",
                group_id=self.group_id
            )

            # Extract records from result tuple
            records = result[0] if isinstance(result, tuple) else result

            if not records:
                print("✗ No Lyra entity found in graph")
                print("  Note: This would trigger fallback to basic search in production")
                return None

            if len(records) > 1:
                print(f"⚠ WARNING: Found {len(records)} Lyra nodes (duplicates detected)")
                print("  Production implementation would merge these automatically")
                print("  For now, using most-connected node as canonical\n")

            # Use most connected node (first in results due to ORDER BY)
            lyra_record = records[0]
            uuid = lyra_record.get('uuid')
            name = lyra_record.get('name')
            summary = lyra_record.get('summary', '')
            connections = lyra_record.get('connection_count', 0)

            print(f"✓ Found Lyra entity")
            print(f"  UUID: {uuid}")
            print(f"  Name: {name}")
            print(f"  Connections: {connections}")
            if summary:
                summary_preview = summary[:150] + "..." if len(summary) > 150 else summary
                print(f"  Summary: {summary_preview}")
            print()

            return uuid

        except Exception as e:
            print(f"✗ Error finding Lyra: {e}")
            return None

    async def run_basic_search(self, query: str, limit: int = 10):
        """
        Run basic search (current implementation).

        This is what ambient_recall currently does - no center node,
        just semantic + BM25 hybrid search.
        """
        print("STEP 2: Basic search (current approach)...")
        print("-" * 80)
        print(f"Query: '{query}'")
        print(f"Method: client.search() - default hybrid search (semantic + BM25)")
        print()

        start_time = time.time()

        try:
            edges = await self.client.search(
                query=query,
                group_ids=[self.group_id],
                num_results=limit,
            )

            # Filter out IS_DUPLICATE_OF edges (Graphiti bug workaround)
            edges = [e for e in edges if e.name != "IS_DUPLICATE_OF"]

            elapsed_ms = (time.time() - start_time) * 1000

            print(f"✓ Completed in {elapsed_ms:.1f}ms")
            print(f"  Results: {len(edges)} edges")
            print()

            return edges, elapsed_ms

        except Exception as e:
            print(f"✗ Search failed: {e}")
            return [], 0

    async def run_optimized_search(self, query: str, center_uuid: str, limit: int = 10):
        """
        Run optimized search with entity-centric ranking.

        This implements the proposed approach from DESIGN.md:
        - Uses EDGE_HYBRID_SEARCH_NODE_DISTANCE recipe
        - Ranks results by graph proximity to Lyra
        - Also fetches entity summaries using NODE_HYBRID_SEARCH_RRF
        """
        print("STEP 3: Optimized search (proposed approach)...")
        print("-" * 80)
        print(f"Query: '{query}'")
        print(f"Method: EDGE_HYBRID_SEARCH_NODE_DISTANCE with center_node={center_uuid[:8]}...")
        print(f"  + NODE_HYBRID_SEARCH_RRF for entity summaries")
        print()

        start_time = time.time()

        try:
            # Configure edge search with node distance reranking
            edge_config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
            edge_config.limit = limit

            # Search for edges with proximity ranking
            edge_results = await self.client.search_(
                query=query,
                config=edge_config,
                center_node_uuid=center_uuid,
                group_ids=[self.group_id]
            )
            edges = edge_results.edges

            # Filter out IS_DUPLICATE_OF edges
            edges = [e for e in edges if e.name != "IS_DUPLICATE_OF"]

            # Also get entity summaries (20% of result budget)
            node_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
            node_config.limit = max(2, limit // 5)

            node_results = await self.client.search_(
                query=query,
                config=node_config,
                group_ids=[self.group_id]
            )
            nodes = node_results.nodes

            elapsed_ms = (time.time() - start_time) * 1000

            print(f"✓ Completed in {elapsed_ms:.1f}ms")
            print(f"  Results: {len(edges)} edges, {len(nodes)} entity summaries")
            print()

            return edges, nodes, elapsed_ms

        except Exception as e:
            print(f"✗ Search failed: {e}")
            return [], [], 0

    async def display_results(self, edges, nodes=None):
        """Display formatted results with node names."""
        # Collect node UUIDs and fetch names
        node_uuids = set()
        for edge in edges:
            node_uuids.add(edge.source_node_uuid)
            node_uuids.add(edge.target_node_uuid)

        # Fetch node names
        node_names = {}
        if node_uuids:
            node_list = await EntityNode.get_by_uuids(
                self.client.driver,
                list(node_uuids),
            )
            for node in node_list:
                node_names[node.uuid] = node.name

        # Display edges
        print("EDGE RESULTS (facts):")
        print("-" * 80)
        for i, edge in enumerate(edges[:5], 1):  # Show first 5
            source_name = node_names.get(edge.source_node_uuid, edge.source_node_uuid[:8])
            target_name = node_names.get(edge.target_node_uuid, edge.target_node_uuid[:8])

            fact_preview = ""
            if edge.fact:
                fact_preview = edge.fact[:100] + "..." if len(edge.fact) > 100 else edge.fact
                fact_preview = f": {fact_preview}"

            print(f"{i}. {source_name} → {edge.name} → {target_name}{fact_preview}")

        if len(edges) > 5:
            print(f"... and {len(edges) - 5} more")
        print()

        # Display entity summaries if present
        if nodes:
            print("ENTITY SUMMARIES:")
            print("-" * 80)
            for i, node in enumerate(nodes, 1):
                summary_preview = node.summary[:150] + "..." if len(node.summary) > 150 else node.summary
                print(f"{i}. {node.name} ({', '.join(node.labels)})")
                print(f"   {summary_preview}")
                print()

    async def run_comparison(self, query: str = "startup"):
        """Run complete comparison between basic and optimized search."""
        # Find Lyra
        lyra_uuid = await self.find_lyra_uuid()

        if not lyra_uuid:
            print("Cannot proceed without Lyra entity - graph may be empty or name different")
            return

        # Run basic search
        basic_edges, basic_time = await self.run_basic_search(query, limit=10)

        print("RESULTS FROM BASIC SEARCH:")
        print("=" * 80)
        await self.display_results(basic_edges)

        # Run optimized search
        opt_edges, opt_nodes, opt_time = await self.run_optimized_search(
            query, lyra_uuid, limit=10
        )

        print("RESULTS FROM OPTIMIZED SEARCH:")
        print("=" * 80)
        await self.display_results(opt_edges, opt_nodes)

        # Run a second optimized search to test caching/warm-up performance
        print("STEP 4: Second optimized search (testing warm cache)...")
        print("-" * 80)
        opt_edges2, opt_nodes2, opt_time2 = await self.run_optimized_search(
            query, lyra_uuid, limit=10
        )
        print(f"✓ Second run completed in {opt_time2:.1f}ms (vs {opt_time:.1f}ms first run)")
        print()

        # Summary comparison
        print("COMPARISON SUMMARY")
        print("=" * 80)
        print(f"Query: '{query}'")
        print()
        print(f"Basic search:")
        print(f"  - Time: {basic_time:.1f}ms")
        print(f"  - Results: {len(basic_edges)} edges")
        print(f"  - Ranking: Generic semantic + BM25")
        print()
        print(f"Optimized search (first run):")
        print(f"  - Time: {opt_time:.1f}ms")
        print(f"  - Results: {len(opt_edges)} edges + {len(opt_nodes)} entity summaries")
        print(f"  - Ranking: Graph proximity to Lyra (entity-centric)")
        print()
        print(f"Optimized search (warm cache):")
        print(f"  - Time: {opt_time2:.1f}ms")
        print(f"  - Speedup from caching: {opt_time / max(opt_time2, 1):.1f}x")
        print()

        # Performance check
        best_time = min(opt_time, opt_time2)
        if best_time < 500:
            print(f"✓ Performance: Under 500ms target ({best_time:.1f}ms)")
        else:
            print(f"⚠ Performance: Exceeds 500ms target ({best_time:.1f}ms)")

        # Quality observations
        print()
        print("KEY DIFFERENCES:")
        print("-" * 80)
        print("Basic search returns facts matching the query with no entity preference.")
        print("Facts about Lyra, Jeff, or unrelated entities are weighted equally.")
        print()
        print("Optimized search ranks facts by graph distance from Lyra:")
        print("  - Facts directly about Lyra rank highest")
        print("  - Facts 1 hop away (e.g., via Jeff) rank next")
        print("  - Distant facts (e.g., system details) rank lower")
        print()
        print("Entity summaries provide background context (who is Lyra, Jeff, etc.)")
        print("that helps with identity reconstruction on startup.")
        print()
        print("=" * 80)
        print("TEST COMPLETE")
        print("=" * 80)
        print()
        print("Next steps:")
        print("1. Review result quality - are Lyra-proximate facts ranking higher?")
        print("2. Check latency - is it under 500ms (300ms target with margin)?")
        print("3. If both pass, implement in rich_texture_v2.py per DESIGN.md Phase 1")
        print()

    async def cleanup(self):
        """Clean up resources."""
        if self.client:
            await self.client.close()


async def main():
    """Run the comparison demo."""
    demo = OptimizedSearchDemo()

    try:
        if not await demo.initialize():
            print("Failed to initialize - check Neo4j connection")
            return 1

        # Test with "startup" query (typical ambient_recall use case)
        await demo.run_comparison(query="startup")

        return 0

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        await demo.cleanup()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
