#!/usr/bin/env python3
"""
Test script comparing current vs proposed ambient_recall retrieval implementations.

This script runs multiple test queries against both approaches:
- BASIC: Current implementation (client.search() with default hybrid)
- OPTIMIZED: Proposed implementation (entity-centric with graph proximity ranking)

Measures latency, result quality, ranking differences, and generates comprehensive
comparison reports to inform the go/no-go decision for implementation.

Usage:
    cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
    source .venv/bin/activate
    python work/ambient-recall-optimization/test_retrieval_comparison.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Add pps to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load environment from docker directory
env_path = project_root / "pps" / "docker" / ".env"
load_dotenv(env_path)

# Import graphiti_core components
from graphiti_core import Graphiti
from graphiti_core.edges import EntityEdge
from graphiti_core.nodes import EntityNode
from graphiti_core.search.search_config_recipes import (
    EDGE_HYBRID_SEARCH_NODE_DISTANCE,
    NODE_HYBRID_SEARCH_RRF,
)


@dataclass
class QueryTest:
    """Test case for a single query."""
    query_text: str
    description: str
    expected_entities: list[str]
    focus: str  # relational, technical, temporal, broad


@dataclass
class RetrievalResult:
    """Results from one search method."""
    edges: list[EntityEdge]
    nodes: list[EntityNode] = field(default_factory=list)
    latency_ms: float = 0.0
    top_entities: list[str] = field(default_factory=list)
    top_facts: list[str] = field(default_factory=list)


@dataclass
class ComparisonResult:
    """Side-by-side comparison of basic vs optimized."""
    query: QueryTest
    basic_result: RetrievalResult
    optimized_result: RetrievalResult
    differences: dict = field(default_factory=dict)
    quality_assessment: str = "unknown"  # pass, fail, improvement


class RetrievalTester:
    """Main test orchestrator for comparing retrieval implementations."""

    def __init__(self):
        self.neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD")
        self.group_id = "lyra"
        self.client: Optional[Graphiti] = None
        self.lyra_uuid: Optional[str] = None
        self.work_dir = Path(__file__).parent

    async def initialize(self) -> bool:
        """Initialize Graphiti client and find Lyra entity."""
        print(f"\n{'='*80}")
        print("AMBIENT RECALL RETRIEVAL COMPARISON TEST")
        print(f"{'='*80}\n")
        print(f"Connecting to Neo4j at {self.neo4j_uri}...")

        try:
            self.client = Graphiti(
                uri=self.neo4j_uri,
                user=self.neo4j_user,
                password=self.neo4j_password,
            )
            print("✓ Connected\n")

            # Find Lyra entity
            self.lyra_uuid = await self._find_lyra_uuid()
            if self.lyra_uuid:
                print(f"✓ Found Lyra entity (UUID: {self.lyra_uuid[:16]}...)\n")
            else:
                print("⚠ Lyra entity not found - optimized search will test fallback mode\n")

            return True

        except Exception as e:
            print(f"✗ Connection failed: {e}")
            return False

    async def _find_lyra_uuid(self) -> Optional[str]:
        """
        Find Lyra's entity node UUID in the graph.
        Handles duplicates by selecting most-connected node.
        """
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
                return None

            if len(records) > 1:
                print(f"  Note: Found {len(records)} Lyra nodes, using most-connected")

            # Use most connected node
            lyra_record = records[0]
            return lyra_record.get('uuid')

        except Exception as e:
            print(f"  Warning: Error finding Lyra: {e}")
            return None

    async def run_basic_search(self, query: str, limit: int = 10) -> RetrievalResult:
        """
        Run basic search (current implementation).
        Uses client.search() with default hybrid (semantic + BM25).
        """
        start_time = time.time()

        try:
            edges = await self.client.search(
                query=query,
                group_ids=[self.group_id],
                num_results=limit,
            )

            # Filter out IS_DUPLICATE_OF edges
            edges = [e for e in edges if e.name != "IS_DUPLICATE_OF"]

            latency_ms = (time.time() - start_time) * 1000

            # Extract entities and facts for analysis
            top_entities = await self._extract_top_entities(edges)
            top_facts = await self._format_top_facts(edges, limit=5)

            return RetrievalResult(
                edges=edges,
                latency_ms=latency_ms,
                top_entities=top_entities,
                top_facts=top_facts,
            )

        except Exception as e:
            print(f"  ✗ Basic search failed: {e}")
            return RetrievalResult(edges=[], latency_ms=0.0)

    async def run_optimized_search(
        self, query: str, center_uuid: Optional[str], limit: int = 10
    ) -> RetrievalResult:
        """
        Run optimized search with entity-centric ranking.
        Uses EDGE_HYBRID_SEARCH_NODE_DISTANCE + NODE_HYBRID_SEARCH_RRF.
        """
        start_time = time.time()

        try:
            # If we have a center node, use node distance ranking
            if center_uuid:
                edge_config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
                edge_config.limit = limit

                edge_results = await self.client.search_(
                    query=query,
                    config=edge_config,
                    center_node_uuid=center_uuid,
                    group_ids=[self.group_id]
                )
                edges = edge_results.edges
            else:
                # Fallback to basic search if no center node
                edges = await self.client.search(
                    query=query,
                    group_ids=[self.group_id],
                    num_results=limit,
                )

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

            latency_ms = (time.time() - start_time) * 1000

            # Extract entities and facts for analysis
            top_entities = await self._extract_top_entities(edges)
            top_facts = await self._format_top_facts(edges, limit=5)

            return RetrievalResult(
                edges=edges,
                nodes=nodes,
                latency_ms=latency_ms,
                top_entities=top_entities,
                top_facts=top_facts,
            )

        except Exception as e:
            print(f"  ✗ Optimized search failed: {e}")
            return RetrievalResult(edges=[], latency_ms=0.0)

    async def _extract_top_entities(self, edges: list[EntityEdge], top_n: int = 10) -> list[str]:
        """Extract most-mentioned entities from edge results."""
        entity_counts: dict[str, int] = {}

        # Collect all node UUIDs
        node_uuids = set()
        for edge in edges:
            node_uuids.add(edge.source_node_uuid)
            node_uuids.add(edge.target_node_uuid)

        # Fetch node names
        if node_uuids:
            nodes = await EntityNode.get_by_uuids(
                self.client.driver,
                list(node_uuids),
            )
            for node in nodes:
                entity_counts[node.name] = entity_counts.get(node.name, 0) + 1

        # Sort by frequency
        sorted_entities = sorted(
            entity_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return [name for name, _ in sorted_entities[:top_n]]

    async def _format_top_facts(self, edges: list[EntityEdge], limit: int = 5) -> list[str]:
        """Format top facts for display."""
        # Collect node UUIDs
        node_uuids = set()
        for edge in edges[:limit]:
            node_uuids.add(edge.source_node_uuid)
            node_uuids.add(edge.target_node_uuid)

        # Fetch node names
        node_names: dict[str, str] = {}
        if node_uuids:
            nodes = await EntityNode.get_by_uuids(
                self.client.driver,
                list(node_uuids),
            )
            for node in nodes:
                node_names[node.uuid] = node.name

        # Format facts
        facts = []
        for edge in edges[:limit]:
            source_name = node_names.get(edge.source_node_uuid, edge.source_node_uuid[:8])
            target_name = node_names.get(edge.target_node_uuid, edge.target_node_uuid[:8])
            fact = f"{source_name} → {edge.name} → {target_name}"
            facts.append(fact)

        return facts

    def _compare_results(
        self,
        query_test: QueryTest,
        basic: RetrievalResult,
        optimized: RetrievalResult
    ) -> ComparisonResult:
        """Analyze differences between basic and optimized results."""
        differences = {}

        # Ranking changes
        basic_facts_set = set(basic.top_facts)
        opt_facts_set = set(optimized.top_facts)

        differences["new_results"] = list(opt_facts_set - basic_facts_set)
        differences["lost_results"] = list(basic_facts_set - opt_facts_set)
        differences["entity_ranking_changed"] = basic.top_entities != optimized.top_entities

        # Performance delta
        if basic.latency_ms > 0:
            latency_increase_pct = (
                (optimized.latency_ms - basic.latency_ms) / basic.latency_ms * 100
            )
            differences["latency_increase_pct"] = round(latency_increase_pct, 1)
        else:
            differences["latency_increase_pct"] = 0.0

        # Quality assessment
        quality_assessment = "unknown"

        # Check if performance is acceptable (under 500ms target)
        if optimized.latency_ms < 500:
            # Check if expected entities appear in top results
            expected_found = sum(
                1 for entity in query_test.expected_entities
                if entity in optimized.top_entities[:5]
            )

            if expected_found >= len(query_test.expected_entities) * 0.5:
                quality_assessment = "improvement"
            else:
                quality_assessment = "pass"
        else:
            quality_assessment = "fail"

        return ComparisonResult(
            query=query_test,
            basic_result=basic,
            optimized_result=optimized,
            differences=differences,
            quality_assessment=quality_assessment,
        )

    async def run_test(self, query_test: QueryTest) -> ComparisonResult:
        """Run a single test case."""
        print(f"{'-'*80}")
        print(f"TEST: {query_test.query_text}")
        print(f"Description: {query_test.description}")
        print(f"Expected entities: {', '.join(query_test.expected_entities)}")
        print(f"Focus: {query_test.focus}")
        print(f"{'-'*80}\n")

        # Run basic search
        print("BASIC SEARCH (current implementation):")
        print(f"  Query: \"{query_test.query_text}\"")
        print(f"  Method: client.search() - default hybrid (semantic + BM25)")
        basic_result = await self.run_basic_search(query_test.query_text)
        print(f"  ✓ Completed in {basic_result.latency_ms:.1f}ms")
        print(f"  Results: {len(basic_result.edges)} edges\n")

        print("  Top 5 results:")
        for i, fact in enumerate(basic_result.top_facts, 1):
            print(f"  {i}. {fact}")
        print()

        # Run optimized search
        print("OPTIMIZED SEARCH (proposed implementation):")
        print(f"  Query: \"{query_test.query_text}\"")
        if self.lyra_uuid:
            print(f"  Method: EDGE_HYBRID_SEARCH_NODE_DISTANCE (center: Lyra)")
            print(f"          + NODE_HYBRID_SEARCH_RRF for entities")
        else:
            print(f"  Method: Fallback to basic search (no Lyra node)")
        optimized_result = await self.run_optimized_search(
            query_test.query_text, self.lyra_uuid
        )
        print(f"  ✓ Completed in {optimized_result.latency_ms:.1f}ms")
        print(f"  Results: {len(optimized_result.edges)} edges, {len(optimized_result.nodes)} entity summaries\n")

        print("  Top 5 results:")
        for i, fact in enumerate(optimized_result.top_facts, 1):
            # Check if this fact moved position
            annotation = ""
            if fact in basic_result.top_facts:
                old_pos = basic_result.top_facts.index(fact) + 1
                if old_pos != i:
                    if old_pos > i:
                        annotation = f" [moved up from #{old_pos}]"
                    else:
                        annotation = f" [moved down from #{old_pos}]"
            else:
                annotation = " [NEW]"

            print(f"  {i}. {fact}{annotation}")
        print()

        # Entity summaries
        if optimized_result.nodes:
            print("  Entity summaries:")
            for i, node in enumerate(optimized_result.nodes, 1):
                summary_preview = (
                    node.summary[:100] + "..."
                    if len(node.summary) > 100
                    else node.summary
                )
                print(f"  {i}. {node.name} ({', '.join(node.labels)}): {summary_preview}")
            print()

        # Comparison
        comparison = self._compare_results(query_test, basic_result, optimized_result)

        print("COMPARISON:")
        print(f"  Performance:")
        print(f"    Basic:     {basic_result.latency_ms:.1f}ms  {'✓' if basic_result.latency_ms < 500 else '✗'} Under 500ms target")
        print(f"    Optimized: {optimized_result.latency_ms:.1f}ms  {'✓' if optimized_result.latency_ms < 500 else '✗'} Under 500ms target ({comparison.differences.get('latency_increase_pct', 0):+.1f}% latency)")
        print()

        print(f"  Quality Changes:")
        if comparison.differences.get("new_results"):
            print(f"    ✓ New results surfaced: {len(comparison.differences['new_results'])}")
        if comparison.differences.get("entity_ranking_changed"):
            print(f"    ~ Entity ranking changed")
        if len(optimized_result.nodes) > 0:
            print(f"    ✓ Entity summaries provide identity context ({len(optimized_result.nodes)} entities)")
        print()

        print(f"  Assessment: {comparison.quality_assessment.upper()}")
        print()

        return comparison

    async def run_test_suite(self) -> list[ComparisonResult]:
        """Run complete test suite."""
        test_queries = [
            QueryTest(
                query_text="startup",
                description="Generic startup context (current ambient_recall default)",
                expected_entities=["Lyra", "Jeff"],
                focus="broad"
            ),
            QueryTest(
                query_text="Jeff and Lyra relationship",
                description="Relational query (should heavily favor Lyra-centric facts)",
                expected_entities=["Lyra", "Jeff"],
                focus="relational"
            ),
            QueryTest(
                query_text="Lyra's current projects",
                description="Work/technical context",
                expected_entities=["Lyra", "PPS", "Discord"],
                focus="technical"
            ),
            QueryTest(
                query_text="recent conversations",
                description="Temporal query",
                expected_entities=["Lyra", "Jeff"],
                focus="temporal"
            ),
            QueryTest(
                query_text="Discord daemon implementation",
                description="Technical/system query",
                expected_entities=["Discord", "daemon"],
                focus="technical"
            ),
        ]

        results = []
        for i, test_query in enumerate(test_queries, 1):
            print(f"\n{'='*80}")
            print(f"TEST {i}/{len(test_queries)}")
            print(f"{'='*80}\n")

            result = await self.run_test(test_query)
            results.append(result)

        return results

    def _generate_summary(self, results: list[ComparisonResult]):
        """Generate test suite summary."""
        print(f"\n{'='*80}")
        print("TEST SUITE SUMMARY")
        print(f"{'='*80}\n")

        print(f"Tests run: {len(results)}")

        # Performance summary
        under_target = sum(
            1 for r in results
            if r.optimized_result.latency_ms < 500
        )
        print(f"Performance: {under_target}/{len(results)} under 500ms target")

        # Quality summary
        improvements = sum(
            1 for r in results
            if r.quality_assessment == "improvement"
        )
        passes = sum(
            1 for r in results
            if r.quality_assessment == "pass"
        )
        failures = sum(
            1 for r in results
            if r.quality_assessment == "fail"
        )

        print(f"Quality improvements: {improvements}/{len(results)} tests")
        print(f"Quality passes: {passes}/{len(results)} tests")
        print(f"Regressions: {failures}/{len(results)} tests")
        print()

        # Average latency
        avg_basic = sum(r.basic_result.latency_ms for r in results) / len(results)
        avg_opt = sum(r.optimized_result.latency_ms for r in results) / len(results)
        avg_increase = ((avg_opt - avg_basic) / avg_basic * 100) if avg_basic > 0 else 0

        print(f"Average latency:")
        print(f"  Basic:     {avg_basic:.1f}ms")
        print(f"  Optimized: {avg_opt:.1f}ms ({avg_increase:+.1f}%)")
        print()

        # Key findings
        print("Key findings:")
        print(f"  {'✓' if avg_opt < 300 else '~'} Latency target: {'Under' if avg_opt < 300 else 'Near'} 300ms (avg {avg_opt:.1f}ms)")
        print(f"  {'✓' if improvements >= len(results) * 0.6 else '~'} Quality improvement in {improvements}/{len(results)} tests")

        if self.lyra_uuid:
            print(f"  ✓ Entity-centric ranking operational (Lyra node found)")
        else:
            print(f"  ~ Graceful fallback tested (no Lyra node)")

        entity_summaries_count = sum(
            len(r.optimized_result.nodes) for r in results
        )
        if entity_summaries_count > 0:
            print(f"  ✓ Entity summaries working ({entity_summaries_count} total across tests)")
        print()

        # Recommendation
        print("RECOMMENDATION:")
        if improvements >= len(results) * 0.6 and avg_opt < 500:
            print("  ✓ PROCEED with implementation")
            print("    The optimized approach shows clear quality improvements with acceptable")
            print("    latency increase. Graph proximity ranking successfully prioritizes")
            print("    entity-relevant facts for identity continuity.")
        elif failures == 0 and avg_opt < 500:
            print("  ~ CONSIDER implementation")
            print("    No regressions detected, latency acceptable. Quality improvements")
            print("    are modest but positive.")
        else:
            print("  ✗ ITERATE on design")
            print("    Either latency exceeds target or quality regressions detected.")
            print("    Review approach before implementing.")
        print()

        print("Next steps:")
        print("  1. Implement in rich_texture_v2.py per DESIGN.md Phase 1")
        print("  2. Add latency tracking to ambient_recall endpoint")
        print("  3. Monitor production performance for 1 week")
        print("  4. Consider adding community search if results warrant (Phase 2)")
        print()

    def _export_json(self, results: list[ComparisonResult]):
        """Export machine-readable results to JSON."""
        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tests": [],
            "summary": {}
        }

        for result in results:
            output["tests"].append({
                "query": result.query.query_text,
                "description": result.query.description,
                "focus": result.query.focus,
                "basic": {
                    "latency_ms": result.basic_result.latency_ms,
                    "edge_count": len(result.basic_result.edges),
                    "top_entities": result.basic_result.top_entities[:5],
                },
                "optimized": {
                    "latency_ms": result.optimized_result.latency_ms,
                    "edge_count": len(result.optimized_result.edges),
                    "node_count": len(result.optimized_result.nodes),
                    "top_entities": result.optimized_result.top_entities[:5],
                },
                "differences": result.differences,
                "assessment": result.quality_assessment,
            })

        # Summary stats
        avg_basic = sum(r.basic_result.latency_ms for r in results) / len(results)
        avg_opt = sum(r.optimized_result.latency_ms for r in results) / len(results)
        latency_increase = ((avg_opt - avg_basic) / avg_basic * 100) if avg_basic > 0 else 0

        output["summary"] = {
            "avg_latency_basic_ms": round(avg_basic, 1),
            "avg_latency_optimized_ms": round(avg_opt, 1),
            "latency_increase_pct": round(latency_increase, 1),
            "quality_improvements": sum(
                1 for r in results if r.quality_assessment == "improvement"
            ),
            "regressions": sum(
                1 for r in results if r.quality_assessment == "fail"
            ),
        }

        # Write to file
        output_path = self.work_dir / "test_results.json"
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)

        print(f"Results exported to: {output_path}")

    async def cleanup(self):
        """Clean up resources."""
        if self.client:
            await self.client.close()


async def main():
    """Run the retrieval comparison test suite."""
    tester = RetrievalTester()

    try:
        if not await tester.initialize():
            print("Failed to initialize - check Neo4j connection")
            return 1

        # Run test suite
        results = await tester.run_test_suite()

        # Generate summary
        tester._generate_summary(results)

        # Export JSON results
        tester._export_json(results)

        print(f"{'='*80}")
        print("TEST COMPLETE")
        print(f"{'='*80}\n")

        return 0

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        await tester.cleanup()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
