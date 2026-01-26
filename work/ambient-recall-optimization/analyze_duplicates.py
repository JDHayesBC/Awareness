#!/usr/bin/env python3
"""
Analyze and clean duplicate edges in Graphiti graph.

Usage:
  # Dry run (report only):
  docker exec pps-server python3 /app/analyze_duplicates.py

  # Execute cleanup:
  docker exec pps-server python3 /app/analyze_duplicates.py --execute
"""

import asyncio
import sys
from collections import defaultdict
from neo4j import AsyncGraphDatabase

NEO4J_URI = "bolt://neo4j:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password123"

EXECUTE_MODE = "--execute" in sys.argv


async def analyze_and_clean():
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    async with driver.session() as session:
        # Get all edges with their source/target names and facts
        result = await session.run("""
            MATCH (source)-[r]->(target)
            WHERE r.fact IS NOT NULL
            RETURN
                source.name as source_name,
                type(r) as relationship,
                target.name as target_name,
                r.fact as fact,
                r.uuid as uuid,
                r.created_at as created_at
            ORDER BY source_name, target_name, fact, r.created_at
        """)

        edges = await result.data()
        print(f"\nTotal edges with facts: {len(edges)}")

        # Group by (source, relationship, target, fact)
        groups = defaultdict(list)
        for edge in edges:
            key = (
                edge['source_name'],
                edge['relationship'],
                edge['target_name'],
                edge['fact']
            )
            groups[key].append(edge)

        # Find duplicates (groups with more than 1 edge)
        duplicates = {k: v for k, v in groups.items() if len(v) > 1}

        print(f"Unique edge patterns: {len(groups)}")
        print(f"Patterns with duplicates: {len(duplicates)}")

        # Calculate potential savings
        total_dupes = sum(len(v) - 1 for v in duplicates.values())
        print(f"Duplicate edges to remove: {total_dupes}")

        if not EXECUTE_MODE:
            print("\n" + "="*60)
            print("DRY RUN - No changes made")
            print("Run with --execute to delete duplicates")
            print("="*60)

            # Show top 10 offenders
            sorted_dupes = sorted(duplicates.items(), key=lambda x: len(x[1]), reverse=True)
            print("\nTop 10 duplicate patterns:")
            for i, (key, edges_list) in enumerate(sorted_dupes[:10]):
                source, rel, target, fact = key
                print(f"  {i+1}. [{len(edges_list)} copies] {source} -> {target}: {fact[:60]}...")

        else:
            print("\n" + "="*60)
            print("EXECUTING CLEANUP")
            print("="*60)

            # Collect UUIDs to delete (keep first/oldest of each group)
            uuids_to_delete = []
            for key, edges_list in duplicates.items():
                # Keep the first one (oldest by created_at due to ORDER BY)
                # Delete the rest
                for edge in edges_list[1:]:
                    if edge['uuid']:
                        uuids_to_delete.append(edge['uuid'])

            print(f"Deleting {len(uuids_to_delete)} duplicate edges...")

            # Delete in batches of 100
            deleted = 0
            batch_size = 100
            for i in range(0, len(uuids_to_delete), batch_size):
                batch = uuids_to_delete[i:i+batch_size]
                result = await session.run("""
                    MATCH ()-[r]->()
                    WHERE r.uuid IN $uuids
                    DELETE r
                    RETURN count(r) as deleted
                """, uuids=batch)
                data = await result.single()
                deleted += data['deleted']
                print(f"  Deleted batch {i//batch_size + 1}: {data['deleted']} edges")

            print(f"\nTotal deleted: {deleted} edges")
            print(f"Remaining edges: {len(edges) - deleted}")

    await driver.close()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(analyze_and_clean())
