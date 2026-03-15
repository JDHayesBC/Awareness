#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
Bulk Duplicate Entity Merger

Finds all duplicate entity nodes in the lyra group and merges them into
canonical nodes (the most connected one wins).

This is a cleanup script for the known issue where Graphiti creates a new
entity node per episode instead of resolving to existing ones.

Safe to run repeatedly — idempotent after first pass.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / "pps" / "docker" / ".env")

from neo4j import GraphDatabase


def get_neo4j_driver():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "password123")
    return GraphDatabase.driver(uri, auth=(user, password))


def find_all_duplicates(driver, group_id="lyra") -> list[tuple[str, int]]:
    """Find all entity names with more than one node."""
    with driver.session() as s:
        r = s.run("""
            MATCH (n:Entity {group_id: $group_id})
            WITH n.name as name, count(n) as cnt
            WHERE cnt > 1
            RETURN name, cnt
            ORDER BY cnt DESC
        """, group_id=group_id)
        return [(row['name'], row['cnt']) for row in r]


def merge_entity(driver, entity_name: str, group_id: str = "lyra") -> int:
    """
    Merge all duplicate nodes for entity_name into the most-connected one.
    Returns number of duplicates merged.
    """
    with driver.session() as s:
        # Find canonical (most connected)
        r = s.run("""
            MATCH (n:Entity {name: $name, group_id: $group_id})
            OPTIONAL MATCH (n)-[r]-()
            RETURN n.uuid as uuid, count(r) as edges
            ORDER BY edges DESC
        """, name=entity_name, group_id=group_id)

        nodes = list(r)
        if len(nodes) <= 1:
            return 0

        canonical_uuid = nodes[0]['uuid']
        duplicates = [n['uuid'] for n in nodes[1:]]

        merged = 0
        for dup_uuid in duplicates:
            # Transfer outgoing edges (dup -> other) to (canonical -> other)
            outgoing = s.run("""
                MATCH (dup:Entity {uuid: $dup_uuid})-[r]->(other)
                WHERE other.uuid <> $canonical_uuid
                RETURN type(r) as rel_type, properties(r) as props, other.uuid as other_uuid
            """, dup_uuid=dup_uuid, canonical_uuid=canonical_uuid).data()

            for e in outgoing:
                rel_type = e['rel_type']
                props = e['props']
                s.run(f"""
                    MATCH (dup:Entity {{uuid: $dup_uuid}})-[old_r:{rel_type}]->(other:Entity {{uuid: $other_uuid}})
                    MATCH (c:Entity {{uuid: $canonical_uuid}})
                    CREATE (c)-[new_r:{rel_type}]->(other)
                    SET new_r = $props
                    DELETE old_r
                """, dup_uuid=dup_uuid, canonical_uuid=canonical_uuid,
                     other_uuid=e['other_uuid'], props=props)

            # Transfer incoming edges (other -> dup) to (other -> canonical)
            incoming = s.run("""
                MATCH (other)-[r]->(dup:Entity {uuid: $dup_uuid})
                WHERE other.uuid <> $canonical_uuid
                RETURN type(r) as rel_type, properties(r) as props, other.uuid as other_uuid
            """, dup_uuid=dup_uuid, canonical_uuid=canonical_uuid).data()

            for e in incoming:
                rel_type = e['rel_type']
                props = e['props']
                s.run(f"""
                    MATCH (other:Entity {{uuid: $other_uuid}})-[old_r:{rel_type}]->(dup:Entity {{uuid: $dup_uuid}})
                    MATCH (c:Entity {{uuid: $canonical_uuid}})
                    CREATE (other)-[new_r:{rel_type}]->(c)
                    SET new_r = $props
                    DELETE old_r
                """, dup_uuid=dup_uuid, canonical_uuid=canonical_uuid,
                     other_uuid=e['other_uuid'], props=props)

            # Delete duplicate
            s.run("MATCH (dup:Entity {uuid: $dup_uuid}) DETACH DELETE dup", dup_uuid=dup_uuid)
            merged += 1

    return merged


def get_graph_stats(driver, group_id="lyra"):
    with driver.session() as s:
        nodes = s.run("MATCH (n:Entity {group_id: $g}) RETURN count(n) as c", g=group_id).single()['c']
        edges = s.run("MATCH ()-[e:RELATES_TO {group_id: $g}]->() RETURN count(e) as c", g=group_id).single()['c']
        return nodes, edges


def main():
    print("=== Bulk Duplicate Entity Merger ===\n")

    driver = get_neo4j_driver()

    # Stats before
    nodes_before, edges_before = get_graph_stats(driver)
    print(f"Before: {nodes_before} entity nodes, {edges_before} edges")

    # Find all duplicates
    duplicates = find_all_duplicates(driver)
    if not duplicates:
        print("No duplicates found. Graph is clean.")
        driver.close()
        return

    total_dups = sum(cnt - 1 for _, cnt in duplicates)
    print(f"Found {len(duplicates)} entity names with duplicates ({total_dups} excess nodes):\n")
    for name, cnt in duplicates[:20]:
        print(f"  {name}: {cnt} nodes ({cnt-1} to merge)")
    if len(duplicates) > 20:
        print(f"  ... and {len(duplicates) - 20} more")

    print(f"\nMerging {total_dups} duplicate nodes into canonical ones...")
    print("(This may take a few minutes for dense nodes like Jeff)\n")

    total_merged = 0
    for i, (name, cnt) in enumerate(duplicates):
        print(f"  [{i+1}/{len(duplicates)}] {name} ({cnt} nodes)...", end='', flush=True)
        merged = merge_entity(driver, name)
        total_merged += merged
        print(f" merged {merged}")

    # Stats after
    nodes_after, edges_after = get_graph_stats(driver)
    print(f"\nDone. Merged {total_merged} duplicate nodes.")
    print(f"Before: {nodes_before} nodes, {edges_before} edges")
    print(f"After:  {nodes_after} nodes, {edges_after} edges")
    print(f"Removed: {nodes_before - nodes_after} nodes")

    driver.close()


if __name__ == "__main__":
    main()
