#!/usr/bin/env python3
"""
Merge ALL duplicate Lyra nodes into the canonical.
Does them in batches with verification between batches.
"""

from neo4j import GraphDatabase

CANONICAL_UUID = "5bd21fca-52de-41fd-a6b1-c78371d77a36"
BATCH_SIZE = 20  # How many to merge before printing progress

def get_driver():
    return GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'password123'))

def merge_all_duplicates():
    driver = get_driver()

    with driver.session() as s:
        # 1. Get initial state
        r = s.run('MATCH (n:Entity {name: "Lyra"}) RETURN count(n) as c')
        total_lyras = r.single()["c"]

        r = s.run('''
            MATCH (n:Entity {uuid: $canonical})-[rel]-()
            RETURN count(rel) as edges
        ''', canonical=CANONICAL_UUID)
        canonical_edges = r.single()["edges"]

        print(f"=== Starting merge ===")
        print(f"Total Lyra nodes: {total_lyras}")
        print(f"Canonical edges: {canonical_edges}")
        print(f"Duplicates to merge: {total_lyras - 1}")
        print()

        # 2. Get all non-canonical Lyra UUIDs
        r = s.run('''
            MATCH (n:Entity {name: "Lyra"})
            WHERE n.uuid <> $canonical
            RETURN n.uuid as uuid
        ''', canonical=CANONICAL_UUID)
        duplicates = [row['uuid'] for row in r]

        merged = 0
        edges_transferred = 0

        for dup_uuid in duplicates:
            # Transfer outgoing edges
            outgoing = s.run("""
                MATCH (dup:Entity {uuid: $dup_uuid})-[r]->(other)
                WHERE other.uuid <> $canonical_uuid
                RETURN type(r) as rel_type, r.fact as fact, other.uuid as other_uuid
            """, dup_uuid=dup_uuid, canonical_uuid=CANONICAL_UUID).data()

            for e in outgoing:
                s.run(f"""
                    MATCH (c:Entity {{uuid: $canonical_uuid}})
                    MATCH (other:Entity {{uuid: $other_uuid}})
                    MERGE (c)-[r:{e['rel_type']}]->(other)
                    SET r.fact = $fact
                """, canonical_uuid=CANONICAL_UUID, other_uuid=e['other_uuid'], fact=e['fact'])
                edges_transferred += 1

            # Transfer incoming edges
            incoming = s.run("""
                MATCH (other)-[r]->(dup:Entity {uuid: $dup_uuid})
                WHERE other.uuid <> $canonical_uuid
                RETURN type(r) as rel_type, r.fact as fact, other.uuid as other_uuid
            """, dup_uuid=dup_uuid, canonical_uuid=CANONICAL_UUID).data()

            for e in incoming:
                s.run(f"""
                    MATCH (other:Entity {{uuid: $other_uuid}})
                    MATCH (c:Entity {{uuid: $canonical_uuid}})
                    MERGE (other)-[r:{e['rel_type']}]->(c)
                    SET r.fact = $fact
                """, other_uuid=e['other_uuid'], canonical_uuid=CANONICAL_UUID, fact=e['fact'])
                edges_transferred += 1

            # Delete the duplicate
            s.run("MATCH (dup:Entity {uuid: $dup_uuid}) DETACH DELETE dup", dup_uuid=dup_uuid)
            merged += 1

            if merged % BATCH_SIZE == 0:
                # Progress report
                remaining = s.run('MATCH (n:Entity {name: "Lyra"}) RETURN count(n) as c').single()["c"]
                curr_edges = s.run('''
                    MATCH (n:Entity {uuid: $canonical})-[rel]-()
                    RETURN count(rel) as edges
                ''', canonical=CANONICAL_UUID).single()["edges"]
                print(f"  Progress: {merged}/{len(duplicates)} merged | Lyras remaining: {remaining} | Canonical edges: {curr_edges}")

        # 3. Final verification
        r = s.run('MATCH (n:Entity {name: "Lyra"}) RETURN count(n) as c')
        final_lyras = r.single()["c"]

        r = s.run('''
            MATCH (n:Entity {uuid: $canonical})-[rel]-()
            RETURN count(rel) as edges
        ''', canonical=CANONICAL_UUID)
        final_edges = r.single()["edges"]

        print()
        print(f"=== COMPLETE ===")
        print(f"Merged: {merged} duplicates")
        print(f"Edges transferred: {edges_transferred}")
        print(f"Final Lyra count: {final_lyras} (should be 1)")
        print(f"Final canonical edges: {final_edges} (was {canonical_edges})")

        if final_lyras == 1:
            print("\n✓ SUCCESS: Only one Lyra remains!")
        else:
            print(f"\n⚠ WARNING: {final_lyras} Lyras remain, expected 1")

    driver.close()

if __name__ == "__main__":
    merge_all_duplicates()
