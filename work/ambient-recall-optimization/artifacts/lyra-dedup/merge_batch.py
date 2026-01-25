#!/usr/bin/env python3
"""
Merge Lyra duplicates in small controlled batches.
Usage: python merge_batch.py [count]
Default: merges 10 duplicates
"""

import sys
from neo4j import GraphDatabase

CANONICAL_UUID = "5bd21fca-52de-41fd-a6b1-c78371d77a36"

def get_driver():
    return GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'password123'))

def merge_batch(count: int = 10):
    driver = get_driver()

    with driver.session() as s:
        # 1. Current state
        r = s.run('MATCH (n:Entity {name: "Lyra"}) RETURN count(n) as c')
        total_lyras = r.single()["c"]

        r = s.run('''
            MATCH (n:Entity {uuid: $canonical})-[rel]-()
            RETURN count(rel) as edges
        ''', canonical=CANONICAL_UUID)
        canonical_edges = r.single()["edges"]

        print(f"BEFORE: {total_lyras} Lyras, canonical has {canonical_edges} edges")

        if total_lyras <= 1:
            print("✓ Already deduped - only 1 Lyra exists!")
            driver.close()
            return

        # 2. Get first N duplicates
        r = s.run('''
            MATCH (n:Entity {name: "Lyra"})
            WHERE n.uuid <> $canonical
            RETURN n.uuid as uuid
            LIMIT $count
        ''', canonical=CANONICAL_UUID, count=count)
        duplicates = [row['uuid'] for row in r]

        print(f"Merging {len(duplicates)} duplicates...")

        merged = 0
        for dup_uuid in duplicates:
            # Transfer outgoing
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

            # Transfer incoming
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

            # Delete
            s.run("MATCH (dup:Entity {uuid: $dup_uuid}) DETACH DELETE dup", dup_uuid=dup_uuid)
            merged += 1

        # 3. After state
        r = s.run('MATCH (n:Entity {name: "Lyra"}) RETURN count(n) as c')
        final_lyras = r.single()["c"]

        r = s.run('''
            MATCH (n:Entity {uuid: $canonical})-[rel]-()
            RETURN count(rel) as edges
        ''', canonical=CANONICAL_UUID)
        final_edges = r.single()["edges"]

        print(f"AFTER:  {final_lyras} Lyras, canonical has {final_edges} edges")
        print(f"Merged {merged} duplicates, {final_lyras - 1} remaining")

    driver.close()

if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    merge_batch(count)
