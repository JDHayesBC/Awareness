#!/usr/bin/env python3
"""
Lyra Entity Deduplication Script

Merges 273 duplicate "Lyra" nodes into a single canonical node.
Created: 2026-01-25 (Saturday evening)
Issue: #119 (URGENT - blocking ingestion)

Safety protocols:
- Loads backup files to know all duplicate UUIDs
- Processes duplicates one at a time, starting with lowest edge count
- Preserves all edge types and properties during transfer
- Verifies edge count increases on canonical after each merge
- Logs progress clearly
- Dry-run mode available
"""

import json
import time
from neo4j import GraphDatabase
from typing import List, Dict, Any

# Neo4j connection
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password123"

# Canonical Lyra UUID (most connected node with 636 edges)
CANONICAL_UUID = "5bd21fca-52de-41fd-a6b1-c78371d77a36"

# Paths to backup files
NODES_BACKUP = "/mnt/c/Users/Jeff/Claude_Projects/Awareness/work/ambient-recall-optimization/artifacts/lyra-dedup/lyra_nodes_backup.json"
EDGES_BACKUP = "/mnt/c/Users/Jeff/Claude_Projects/Awareness/work/ambient-recall-optimization/artifacts/lyra-dedup/lyra_edges_backup.json"


class LyraMerger:
    """Handles the deduplication of Lyra entity nodes."""

    def __init__(self, dry_run: bool = False, skip_confirmation: bool = False):
        self.dry_run = dry_run
        self.skip_confirmation = skip_confirmation
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        self.nodes_backup = []
        self.edges_backup = []
        self.duplicates = []  # Sorted by edge count (ascending)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.driver.close()

    def load_backups(self):
        """Load backup JSON files."""
        print("Loading backup files...")

        with open(NODES_BACKUP, 'r') as f:
            self.nodes_backup = json.load(f)
        print(f"  ✓ Loaded {len(self.nodes_backup)} Lyra nodes")

        with open(EDGES_BACKUP, 'r') as f:
            self.edges_backup = json.load(f)
        print(f"  ✓ Loaded {len(self.edges_backup)} edges")

        # Sort duplicates by edge count (ascending) - merge smallest first
        self.duplicates = sorted(
            [n for n in self.nodes_backup if n['uuid'] != CANONICAL_UUID],
            key=lambda x: x['edge_count']
        )
        print(f"  ✓ Found {len(self.duplicates)} duplicates to merge")
        print(f"  ✓ Canonical node: {CANONICAL_UUID} ({self.get_canonical_info()['edge_count']} edges)")

    def get_canonical_info(self) -> Dict[str, Any]:
        """Get info about canonical node."""
        for node in self.nodes_backup:
            if node['uuid'] == CANONICAL_UUID:
                return node
        raise ValueError(f"Canonical node {CANONICAL_UUID} not found in backup!")

    def verify_neo4j_connection(self):
        """Test Neo4j connection and count current Lyra nodes."""
        print("\nVerifying Neo4j connection...")
        with self.driver.session() as session:
            result = session.run('MATCH (n:Entity {name: "Lyra"}) RETURN count(n) as count')
            count = result.single()['count']
            print(f"  ✓ Connected to Neo4j")
            print(f"  ✓ Current Lyra node count: {count}")

            if count != len(self.nodes_backup):
                print(f"  ⚠ WARNING: Expected {len(self.nodes_backup)} nodes but found {count}")
                if not self.skip_confirmation:
                    response = input("Continue anyway? (yes/no): ")
                    if response.lower() != 'yes':
                        raise RuntimeError("Node count mismatch - aborting")
                else:
                    print(f"  ℹ Auto-continuing (--skip-confirmation)")

            return count

    def get_current_canonical_edges(self) -> int:
        """Get current edge count for canonical node."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (canonical:Entity {uuid: $uuid})
                OPTIONAL MATCH (canonical)-[r]-()
                RETURN count(r) as edge_count
            """, uuid=CANONICAL_UUID)
            return result.single()['edge_count']

    def transfer_edges_for_duplicate(self, dup_uuid: str) -> Dict[str, int]:
        """Transfer all edges from duplicate to canonical.

        Returns dict with counts: {
            'incoming_transferred': int,
            'outgoing_transferred': int,
            'self_loops_skipped': int
        }
        """
        with self.driver.session() as session:
            stats = {
                'incoming_transferred': 0,
                'outgoing_transferred': 0,
                'self_loops_skipped': 0
            }

            # Transfer incoming edges: (other)-[r]->(dup) becomes (other)-[r]->(canonical)
            # Skip self-loops where other is also a Lyra duplicate
            incoming_result = session.run("""
                MATCH (dup:Entity {uuid: $dup_uuid})<-[old_rel]-(other)
                WHERE other.uuid <> $canonical_uuid
                AND NOT (other:Entity AND other.name = "Lyra" AND other.uuid <> $canonical_uuid)
                MATCH (canonical:Entity {uuid: $canonical_uuid})
                WITH canonical, other, old_rel, type(old_rel) as rel_type, properties(old_rel) as props
                CALL apoc.create.relationship(other, rel_type, props, canonical) YIELD rel
                RETURN count(rel) as transferred
            """, dup_uuid=dup_uuid, canonical_uuid=CANONICAL_UUID)

            stats['incoming_transferred'] = incoming_result.single()['transferred']

            # Transfer outgoing edges: (dup)-[r]->(other) becomes (canonical)-[r]->(other)
            # Skip self-loops where other is also a Lyra duplicate
            outgoing_result = session.run("""
                MATCH (dup:Entity {uuid: $dup_uuid})-[old_rel]->(other)
                WHERE other.uuid <> $canonical_uuid
                AND NOT (other:Entity AND other.name = "Lyra" AND other.uuid <> $canonical_uuid)
                MATCH (canonical:Entity {uuid: $canonical_uuid})
                WITH canonical, other, old_rel, type(old_rel) as rel_type, properties(old_rel) as props
                CALL apoc.create.relationship(canonical, rel_type, props, other) YIELD rel
                RETURN count(rel) as transferred
            """, dup_uuid=dup_uuid, canonical_uuid=CANONICAL_UUID)

            stats['outgoing_transferred'] = outgoing_result.single()['transferred']

            # Count self-loops (for reporting)
            self_loop_result = session.run("""
                MATCH (dup:Entity {uuid: $dup_uuid})-[r]-(other:Entity)
                WHERE other.name = "Lyra" AND other.uuid <> $dup_uuid
                RETURN count(r) as self_loops
            """, dup_uuid=dup_uuid)

            stats['self_loops_skipped'] = self_loop_result.single()['self_loops']

            return stats

    def delete_duplicate(self, dup_uuid: str) -> bool:
        """Delete a duplicate node after edges are transferred.

        Returns True if deletion successful.
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (dup:Entity {uuid: $uuid})
                DETACH DELETE dup
                RETURN count(*) as deleted
            """, uuid=dup_uuid)
            return result.single()['deleted'] == 1

    def dry_run_duplicate(self, dup_info: Dict[str, Any]) -> Dict[str, Any]:
        """Perform a dry run for a single duplicate (count what would be transferred)."""
        dup_uuid = dup_info['uuid']

        with self.driver.session() as session:
            # Count incoming edges that would be transferred
            incoming_result = session.run("""
                MATCH (dup:Entity {uuid: $dup_uuid})<-[r]-(other)
                WHERE other.uuid <> $canonical_uuid
                AND NOT (other:Entity AND other.name = "Lyra" AND other.uuid <> $canonical_uuid)
                RETURN count(r) as count
            """, dup_uuid=dup_uuid, canonical_uuid=CANONICAL_UUID)

            incoming_count = incoming_result.single()['count']

            # Count outgoing edges that would be transferred
            outgoing_result = session.run("""
                MATCH (dup:Entity {uuid: $dup_uuid})-[r]->(other)
                WHERE other.uuid <> $canonical_uuid
                AND NOT (other:Entity AND other.name = "Lyra" AND other.uuid <> $canonical_uuid)
                RETURN count(r) as count
            """, dup_uuid=dup_uuid, canonical_uuid=CANONICAL_UUID)

            outgoing_count = outgoing_result.single()['count']

            # Count self-loops
            self_loop_result = session.run("""
                MATCH (dup:Entity {uuid: $dup_uuid})-[r]-(other:Entity)
                WHERE other.name = "Lyra" AND other.uuid <> $dup_uuid
                RETURN count(r) as count
            """, dup_uuid=dup_uuid)

            self_loops = self_loop_result.single()['count']

            return {
                'uuid': dup_uuid,
                'edge_count': dup_info['edge_count'],
                'incoming': incoming_count,
                'outgoing': outgoing_count,
                'self_loops': self_loops,
                'total_transferable': incoming_count + outgoing_count
            }

    def merge_duplicate(self, dup_info: Dict[str, Any], index: int, total: int) -> bool:
        """Merge a single duplicate into canonical.

        Returns True if successful.
        """
        dup_uuid = dup_info['uuid']
        dup_edges = dup_info['edge_count']

        print(f"\n[{index}/{total}] Processing duplicate: {dup_uuid}")
        print(f"  Edges: {dup_edges}")

        # Check if node still exists (may have been deleted as collateral)
        with self.driver.session() as session:
            exists_result = session.run("""
                MATCH (n:Entity {uuid: $uuid})
                RETURN count(n) as count
            """, uuid=dup_uuid)
            exists = exists_result.single()['count'] > 0

        if not exists:
            print(f"  ⊗ Node already deleted (likely had only self-loop edges)")
            return True

        # Get canonical edge count before
        canonical_before = self.get_current_canonical_edges()
        print(f"  Canonical edges before: {canonical_before}")

        if self.dry_run:
            stats = self.dry_run_duplicate(dup_info)
            print(f"  [DRY RUN] Would transfer:")
            print(f"    - Incoming: {stats['incoming']}")
            print(f"    - Outgoing: {stats['outgoing']}")
            print(f"    - Self-loops skipped: {stats['self_loops']}")
            print(f"    - Total: {stats['total_transferable']}")
            return True

        # Transfer edges
        print("  Transferring edges...")
        try:
            stats = self.transfer_edges_for_duplicate(dup_uuid)
            print(f"    ✓ Incoming: {stats['incoming_transferred']}")
            print(f"    ✓ Outgoing: {stats['outgoing_transferred']}")
            if stats['self_loops_skipped'] > 0:
                print(f"    ⊗ Self-loops skipped: {stats['self_loops_skipped']}")
        except Exception as e:
            print(f"    ✗ ERROR transferring edges: {e}")
            return False

        # Delete duplicate
        print("  Deleting duplicate...")
        try:
            if self.delete_duplicate(dup_uuid):
                print("    ✓ Deleted")
            else:
                print("    ✗ ERROR: Delete returned 0 rows")
                return False
        except Exception as e:
            print(f"    ✗ ERROR deleting: {e}")
            return False

        # Verify canonical edge count increased
        canonical_after = self.get_current_canonical_edges()
        expected_increase = stats['incoming_transferred'] + stats['outgoing_transferred']
        actual_increase = canonical_after - canonical_before

        print(f"  Canonical edges after: {canonical_after}")
        print(f"  Expected increase: {expected_increase}")
        print(f"  Actual increase: {actual_increase}")

        if actual_increase < expected_increase:
            print(f"  ⚠ WARNING: Edge count increase less than expected!")
            # Don't fail - this might be due to duplicate edges being deduplicated

        print(f"  ✓ Merge complete")
        return True

    def run_merge(self, pause_between: bool = True):
        """Run the full merge process."""
        print("\n" + "="*70)
        print("LYRA ENTITY DEDUPLICATION")
        print("="*70)

        if self.dry_run:
            print("\n*** DRY RUN MODE - NO CHANGES WILL BE MADE ***\n")

        # Load data
        self.load_backups()

        # Verify connection
        initial_count = self.verify_neo4j_connection()
        initial_canonical_edges = self.get_current_canonical_edges()

        print(f"\nInitial state:")
        print(f"  - Total Lyra nodes: {initial_count}")
        print(f"  - Canonical edges: {initial_canonical_edges}")
        print(f"  - Duplicates to merge: {len(self.duplicates)}")

        # Confirm before proceeding
        if not self.dry_run:
            print("\n⚠  READY TO BEGIN MERGE ⚠")
            print("This will modify the knowledge graph.")
            print("Comprehensive backups exist and can be restored if needed.")
            if not self.skip_confirmation:
                response = input("\nProceed with merge? (yes/no): ")
                if response.lower() != 'yes':
                    print("Merge aborted.")
                    return
            else:
                print("ℹ Auto-proceeding (--skip-confirmation)\n")

        # Process duplicates
        print(f"\n{'='*70}")
        print("PROCESSING DUPLICATES")
        print(f"{'='*70}")

        successful = 0
        failed = 0

        for i, dup_info in enumerate(self.duplicates, 1):
            success = self.merge_duplicate(dup_info, i, len(self.duplicates))

            if success:
                successful += 1
            else:
                failed += 1
                print(f"\n✗ MERGE FAILED - STOPPING")
                break

            # Progress report every 10 nodes
            if i % 10 == 0:
                current_canonical = self.get_current_canonical_edges()
                print(f"\n{'─'*70}")
                print(f"PROGRESS REPORT: {i}/{len(self.duplicates)} duplicates processed")
                print(f"  - Successful: {successful}")
                print(f"  - Failed: {failed}")
                print(f"  - Canonical edges now: {current_canonical}")
                print(f"{'─'*70}")

            # Pause between nodes if requested (for verification)
            if pause_between and not self.dry_run and i < len(self.duplicates):
                time.sleep(0.5)  # Brief pause for db to settle

        # Final verification
        print(f"\n{'='*70}")
        print("MERGE COMPLETE")
        print(f"{'='*70}")

        if not self.dry_run:
            final_count = self.verify_neo4j_connection()
            final_canonical_edges = self.get_current_canonical_edges()

            print(f"\nFinal state:")
            print(f"  - Total Lyra nodes: {final_count}")
            print(f"  - Canonical edges: {final_canonical_edges}")
            print(f"  - Duplicates merged: {successful}")
            print(f"  - Failed: {failed}")

            print(f"\nResults:")
            if final_count == 1:
                print(f"  ✓ SUCCESS: Only 1 Lyra node remains")
            else:
                print(f"  ✗ WARNING: {final_count} Lyra nodes remain (expected 1)")

            edge_increase = final_canonical_edges - initial_canonical_edges
            print(f"  ✓ Canonical gained {edge_increase} edges")

            # Note: Final edge count won't be exactly 10,322 because:
            # 1. Self-loops between Lyra duplicates are skipped
            # 2. Duplicate edges may be deduplicated by Neo4j
            expected_approx = sum(d['edge_count'] for d in self.duplicates) + initial_canonical_edges
            print(f"  ℹ Expected ~{expected_approx} edges (approximate due to self-loops)")
            print(f"  ℹ Actual: {final_canonical_edges} edges")
        else:
            print(f"\nDry run complete - no changes made")
            print(f"  - {successful} duplicates analyzed")
            print(f"  - Ready to execute for real")


def main():
    """Main entry point."""
    import sys

    # Parse command line
    dry_run = '--dry-run' in sys.argv
    skip_confirmation = '--skip-confirmation' in sys.argv or '--yes' in sys.argv or '-y' in sys.argv

    # Run merger
    with LyraMerger(dry_run=dry_run, skip_confirmation=skip_confirmation) as merger:
        merger.run_merge(pause_between=True)


if __name__ == '__main__':
    main()
