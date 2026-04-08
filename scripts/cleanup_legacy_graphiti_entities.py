#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
Clean up legacy Graphiti entities from neo4j

The custom graph uses entity_name and entity_type properties.
Old Graphiti entities have name/summary/group_id but no entity_type.
These legacy entities are dead weight — safe to remove.

This script:
1. Counts legacy entities (entity_type IS NULL)
2. Confirms they're truly legacy (have Graphiti properties)
3. Deletes them in batches to avoid memory issues
"""

from neo4j import GraphDatabase
import os
import time

# Neo4j connection
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def count_legacy_entities(tx):
    """Count entities without entity_type (legacy Graphiti)."""
    result = tx.run("""
        MATCH (n:Entity)
        WHERE n.entity_type IS NULL
        RETURN count(n) as count
    """)
    return result.single()["count"]


def count_custom_entities(tx):
    """Count entities WITH entity_type (custom pipeline)."""
    result = tx.run("""
        MATCH (n:Entity)
        WHERE n.entity_type IS NOT NULL
        RETURN count(n) as count
    """)
    return result.single()["count"]


def sample_legacy_entities(tx, limit=10):
    """Sample legacy entities to verify they're truly legacy."""
    result = tx.run("""
        MATCH (n:Entity)
        WHERE n.entity_type IS NULL
        RETURN
            n.name as name,
            n.entity_name as entity_name,
            n.summary as summary,
            n.group_id as group_id,
            keys(n) as properties
        LIMIT $limit
    """, limit=limit)
    return list(result)


def delete_legacy_entities_batch(tx, batch_size=1000):
    """Delete a batch of legacy entities."""
    result = tx.run("""
        MATCH (n:Entity)
        WHERE n.entity_type IS NULL
        WITH n LIMIT $batch_size
        DETACH DELETE n
        RETURN count(n) as deleted
    """, batch_size=batch_size)
    return result.single()["deleted"]


def main():
    print("\n" + "="*60)
    print("LEGACY GRAPHITI ENTITY CLEANUP")
    print("="*60 + "\n")

    with driver.session() as session:
        # Step 1: Count entities
        print("[1/5] Counting entities...")
        legacy_count = session.execute_read(count_legacy_entities)
        custom_count = session.execute_read(count_custom_entities)

        print(f"  Legacy Graphiti entities (no entity_type): {legacy_count}")
        print(f"  Custom pipeline entities (has entity_type): {custom_count}")
        print(f"  Total: {legacy_count + custom_count}")

        if legacy_count == 0:
            print("\n✓ No legacy entities found. Graph is clean!")
            return

        # Step 2: Sample legacy entities
        print(f"\n[2/5] Sampling {min(10, legacy_count)} legacy entities...")
        samples = session.execute_read(sample_legacy_entities)

        for i, sample in enumerate(samples[:5], 1):
            props = sample["properties"]
            print(f"\n  Sample {i}:")
            print(f"    name: {sample['name']}")
            print(f"    entity_name: {sample['entity_name']}")
            print(f"    summary: {sample['summary'][:60] if sample['summary'] else None}...")
            print(f"    group_id: {sample['group_id']}")
            print(f"    properties: {', '.join(sorted(props))}")

        # Step 3: Confirm deletion
        print(f"\n[3/5] Ready to delete {legacy_count} legacy entities")
        print("  These entities have NO entity_type (legacy Graphiti)")
        print("  Custom entities (WITH entity_type) will be preserved")
        print()

        response = input("  Proceed with deletion? (yes/no): ").strip().lower()

        if response != "yes":
            print("\n  Cancelled. No changes made.")
            return

        # Step 4: Delete in batches
        print(f"\n[4/5] Deleting {legacy_count} entities in batches of 1000...")
        total_deleted = 0
        batch_num = 0

        while True:
            batch_num += 1
            deleted = session.execute_write(delete_legacy_entities_batch)

            if deleted == 0:
                break

            total_deleted += deleted
            print(f"  Batch {batch_num}: deleted {deleted} entities (total: {total_deleted}/{legacy_count})")
            time.sleep(0.1)  # Brief pause between batches

        # Step 5: Verify
        print(f"\n[5/5] Verifying cleanup...")
        remaining_legacy = session.execute_read(count_legacy_entities)
        final_custom = session.execute_read(count_custom_entities)

        print(f"  Legacy entities remaining: {remaining_legacy}")
        print(f"  Custom entities remaining: {final_custom}")
        print(f"  Total deleted: {total_deleted}")

        if remaining_legacy == 0:
            print(f"\n✓ Cleanup complete! Graph now contains only custom entities.")
        else:
            print(f"\n⚠ Warning: {remaining_legacy} legacy entities still present")

    driver.close()


if __name__ == "__main__":
    main()
