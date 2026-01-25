#!/usr/bin/env python3
"""
Merge ONE duplicate Lyra node into the canonical.
Run this carefully, one at a time, verify after each.
"""

import sys
from neo4j import GraphDatabase

CANONICAL_UUID = "5bd21fca-52de-41fd-a6b1-c78371d77a36"

def get_driver():
    return GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'password123'))

def get_edge_count(session, uuid: str) -> int:
    """Count edges involving a node."""
    result = session.run("""
        MATCH (n:Entity {uuid: $uuid})-[r]-()
        RETURN count(r) as c
    """, uuid=uuid)
    return result.single()["c"]

def merge_duplicate(dup_uuid: str, dry_run: bool = True):
    """Merge a duplicate Lyra into the canonical."""
    driver = get_driver()

    with driver.session() as s:
        # 1. Get current state
        canonical_edges_before = get_edge_count(s, CANONICAL_UUID)
        dup_edges = get_edge_count(s, dup_uuid)

        print(f"=== Merging {dup_uuid[:12]}... into canonical ===")
        print(f"Canonical edges before: {canonical_edges_before}")
        print(f"Duplicate edges: {dup_edges}")

        if dry_run:
            print("\n[DRY RUN - not actually merging]")

        # 2. Find all edges FROM duplicate TO other nodes
        outgoing = s.run("""
            MATCH (dup:Entity {uuid: $dup_uuid})-[r]->(other)
            WHERE other.uuid <> $canonical_uuid
            RETURN type(r) as rel_type, r.uuid as edge_uuid, r.fact as fact,
                   other.uuid as other_uuid, other.name as other_name
        """, dup_uuid=dup_uuid, canonical_uuid=CANONICAL_UUID).data()

        print(f"\nOutgoing edges: {len(outgoing)}")
        for e in outgoing[:3]:  # Show first 3
            print(f"  -> {e['other_name']}: {e['rel_type']}")

        # 3. Find all edges FROM other nodes TO duplicate
        incoming = s.run("""
            MATCH (other)-[r]->(dup:Entity {uuid: $dup_uuid})
            WHERE other.uuid <> $canonical_uuid
            RETURN type(r) as rel_type, r.uuid as edge_uuid, r.fact as fact,
                   other.uuid as other_uuid, other.name as other_name
        """, dup_uuid=dup_uuid, canonical_uuid=CANONICAL_UUID).data()

        print(f"Incoming edges: {len(incoming)}")
        for e in incoming[:3]:
            print(f"  <- {e['other_name']}: {e['rel_type']}")

        if dry_run:
            print("\nWould transfer these edges and delete duplicate.")
            driver.close()
            return

        # 4. ACTUALLY MERGE - Create edges from canonical
        transferred = 0

        # Transfer outgoing
        for e in outgoing:
            # Create new edge from canonical to other
            s.run(f"""
                MATCH (c:Entity {{uuid: $canonical_uuid}})
                MATCH (other:Entity {{uuid: $other_uuid}})
                MERGE (c)-[r:{e['rel_type']}]->(other)
                SET r.fact = $fact, r.migrated_from = $dup_uuid
            """, canonical_uuid=CANONICAL_UUID, other_uuid=e['other_uuid'],
                fact=e['fact'], dup_uuid=dup_uuid)
            transferred += 1

        # Transfer incoming
        for e in incoming:
            s.run(f"""
                MATCH (other:Entity {{uuid: $other_uuid}})
                MATCH (c:Entity {{uuid: $canonical_uuid}})
                MERGE (other)-[r:{e['rel_type']}]->(c)
                SET r.fact = $fact, r.migrated_from = $dup_uuid
            """, other_uuid=e['other_uuid'], canonical_uuid=CANONICAL_UUID,
                fact=e['fact'], dup_uuid=dup_uuid)
            transferred += 1

        print(f"\nTransferred {transferred} edges")

        # 5. Delete the duplicate
        s.run("""
            MATCH (dup:Entity {uuid: $dup_uuid})
            DETACH DELETE dup
        """, dup_uuid=dup_uuid)
        print(f"Deleted duplicate node")

        # 6. Verify
        canonical_edges_after = get_edge_count(s, CANONICAL_UUID)
        remaining_lyras = s.run('MATCH (n:Entity {name: "Lyra"}) RETURN count(n) as c').single()["c"]

        print(f"\n=== RESULT ===")
        print(f"Canonical edges after: {canonical_edges_after} (was {canonical_edges_before})")
        print(f"Remaining Lyra nodes: {remaining_lyras}")

    driver.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python merge_one.py <dup_uuid> [--execute]")
        print("  Without --execute, does a dry run")
        sys.exit(1)

    dup_uuid = sys.argv[1]
    dry_run = "--execute" not in sys.argv

    merge_duplicate(dup_uuid, dry_run=dry_run)
