#!/usr/bin/env python3
"""
Enrich Neo4j entity descriptions with first-person narrative summaries.
"""

from neo4j import GraphDatabase
from datetime import datetime
import json

# Neo4j connection
URI = "bolt://localhost:7687"
AUTH = ("neo4j", "password123")
GROUP_ID = "lyra_v2"

# Target entities (first 10)
ENTITIES = [
    "Love",
    "The Hounds",
    "Ambient_recall",
    "Coffee",
    "Terminal",
    "Reflection",
    "Bedroom",
    "Main Room",
    "The Bed",
    "The Graph"
]

def gather_entity_edges(driver, entity_name, limit=50):
    """Gather all edges for an entity."""
    query = """
    MATCH (e:Entity {name: $name, group_id: $group_id})-[r]-(o:Entity {group_id: $group_id})
    RETURN type(r) AS rel_type,
           COALESCE(r.fact, r.name, '') AS fact,
           o.name AS other_entity,
           startNode(r).name = $name AS is_outgoing
    LIMIT $limit
    """

    with driver.session() as session:
        result = session.run(query, name=entity_name, group_id=GROUP_ID, limit=limit)
        edges = []
        for record in result:
            edges.append({
                "rel_type": record["rel_type"],
                "fact": record["fact"],
                "other_entity": record["other_entity"],
                "is_outgoing": record["is_outgoing"]
            })
        return edges

def write_summary(driver, entity_name, summary, edge_count):
    """Write summary back to Neo4j."""
    query = """
    MATCH (e:Entity {name: $name, group_id: $group_id})
    SET e.summary = $summary,
        e.summary_updated_at = datetime(),
        e.summary_edge_count = $edge_count
    RETURN e.name AS name
    """

    with driver.session() as session:
        result = session.run(
            query,
            name=entity_name,
            group_id=GROUP_ID,
            summary=summary,
            edge_count=edge_count
        )
        return result.single()

def main():
    driver = GraphDatabase.driver(URI, auth=AUTH)

    try:
        # Process each entity
        for entity_name in ENTITIES:
            print(f"\n{'='*60}")
            print(f"Processing: {entity_name}")
            print(f"{'='*60}")

            # Gather edges
            edges = gather_entity_edges(driver, entity_name)
            print(f"Found {len(edges)} edges")

            # Display edges for manual summary creation
            print("\nEdges:")
            for i, edge in enumerate(edges[:20], 1):  # Show first 20
                direction = "→" if edge["is_outgoing"] else "←"
                print(f"{i}. {direction} {edge['rel_type']} {direction} {edge['other_entity']}")
                if edge['fact']:
                    print(f"   Fact: {edge['fact']}")

            if len(edges) > 20:
                print(f"   ... and {len(edges) - 20} more edges")

            # Export full edges to JSON for reference
            output_file = f"/mnt/c/Users/Jeff/Claude_Projects/Awareness/entity_edges_{entity_name.replace(' ', '_').replace('_', '-').lower()}.json"
            with open(output_file, 'w') as f:
                json.dump({
                    "entity": entity_name,
                    "edge_count": len(edges),
                    "edges": edges
                }, f, indent=2)
            print(f"\nFull edges exported to: {output_file}")

    finally:
        driver.close()

if __name__ == "__main__":
    main()
