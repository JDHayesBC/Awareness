#!/usr/bin/env python3
"""
Verify summaries were written correctly.
"""

from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
AUTH = ("neo4j", "password123")
GROUP_ID = "lyra_v2"

def verify_summary(driver, entity_name):
    """Retrieve and display a summary."""
    query = """
    MATCH (e:Entity {name: $name, group_id: $group_id})
    RETURN e.name AS name,
           e.summary AS summary,
           e.summary_updated_at AS updated_at,
           e.summary_edge_count AS edge_count
    """

    with driver.session() as session:
        result = session.run(query, name=entity_name, group_id=GROUP_ID)
        return result.single()

def main():
    driver = GraphDatabase.driver(URI, auth=AUTH)

    try:
        # Check a few entities
        test_entities = ["Love", "The Hounds", "Coffee"]

        for entity_name in test_entities:
            print(f"\n{'='*60}")
            print(f"Entity: {entity_name}")
            print(f"{'='*60}")

            record = verify_summary(driver, entity_name)
            if record:
                print(f"Edge count: {record['edge_count']}")
                print(f"Updated: {record['updated_at']}")
                print(f"\nSummary:\n{record['summary']}")
            else:
                print(f"No record found for {entity_name}")

    finally:
        driver.close()

if __name__ == "__main__":
    main()
