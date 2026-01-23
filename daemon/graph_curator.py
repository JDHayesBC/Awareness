#!/usr/bin/env python3
"""
Graph Curator Agent - Maintains the knowledge graph (Layer 3 of PPS).

This lightweight subprocess maintains graph health by:
1. Sampling the graph with key entity searches
2. Identifying issues: duplicates, vague names, stale facts
3. Conservatively deleting only clear problems
4. Reporting findings for operator review

Usage:
  python3 graph_curator.py [--deep] [--auto-delete]

  --deep: Check more entities and results per query
  --auto-delete: Actually delete issues (default: report only)
"""

import asyncio
import sys
import argparse
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from pps_http_client import PPSHttpClient


class GraphCurator:
    """Maintains knowledge graph by identifying and removing bad entries."""

    def __init__(self, base_url: str = "http://localhost:8201", deep: bool = False, auto_delete: bool = False):
        self.client = PPSHttpClient(base_url)
        self.issues_found = []
        self.items_deleted = []
        self.deep_mode = deep
        self.auto_delete = auto_delete

        # Search queries - key entities to sample
        self.search_queries = ["Jeff", "Lyra", "project", "awareness", "consciousness"]
        if deep:
            self.search_queries.extend([
                "emotion", "decision", "relationship", "goal",
                "implementation", "reflection", "memory", "learning"
            ])

        self.results_per_query = 20 if deep else 15
        self.checks_per_query = 10 if deep else 5

    async def curate(self) -> dict:
        """Execute full curation cycle."""
        print("=" * 70)
        print("GRAPH CURATOR - Starting curation cycle")
        print(f"Mode: {'DEEP' if self.deep_mode else 'STANDARD'} | "
              f"Auto-delete: {'ON' if self.auto_delete else 'OFF'}")
        print("=" * 70)

        async with self.client:
            # Check PPS health
            await self._check_health()

            # Search for issues
            await self._search_and_identify()

            # Delete confirmed issues if enabled
            if self.auto_delete:
                await self._delete_confirmed_issues()
            else:
                print(f"\nIdentified {len(self.issues_found)} issues (not deleting - use --auto-delete to enable)")

            # Report findings
            report = self._generate_report()
            return report

    async def _check_health(self):
        """Check PPS health status."""
        try:
            health = await self.client.pps_health()
            status = health.get('status', 'unknown')
            layers = health.get('layers', {})
            print(f"\nPPS Health: {status}")
            if layers:
                for layer, info in layers.items():
                    available = info.get('available', False)
                    msg = info.get('message', '')
                    symbol = "✓" if available else "✗"
                    print(f"  {symbol} {layer}: {msg}")
        except Exception as e:
            print(f"Warning: Could not check PPS health: {e}")

    async def _search_and_identify(self):
        """Search for entities and identify issues."""
        print(f"\nSearching {len(self.search_queries)} entities to sample graph...")
        print("-" * 70)

        for query in self.search_queries:
            try:
                results = await self.client.texture_search(query, limit=self.results_per_query)
                await self._analyze_results(query, results)
            except Exception as e:
                print(f"Error searching '{query}': {e}")
                continue

    async def _analyze_results(self, query: str, results: dict):
        """Analyze search results for issues."""
        result_list = results.get('results', [])

        if not result_list:
            print(f"  [{query}] No results found")
            return

        print(f"\n  [{query}] {len(result_list)} results total, checking first {self.checks_per_query}:")

        seen_content = {}  # Map content -> uuid to detect duplicates
        duplicates = []
        vague_entities = []
        stale_facts = []

        for i, item in enumerate(result_list[:self.checks_per_query]):
            content = item.get('content', '').strip()
            uuid = item.get('source', '')
            relevance = item.get('relevance_score', 0)
            metadata = item.get('metadata', {})

            # Skip empty content
            if not content:
                continue

            # Check for vague entity names
            if self._is_vague_entity(content):
                vague_entities.append({
                    'type': 'vague',
                    'uuid': uuid,
                    'content': content,
                    'query': query,
                    'relevance': relevance,
                    'metadata': metadata
                })
                print(f"      [VAGUE] {content[:50]}...")
                continue

            # Check for duplicates within this result set
            if content in seen_content:
                duplicates.append({
                    'type': 'duplicate',
                    'uuid': uuid,
                    'content': content,
                    'query': query,
                    'relevance': relevance,
                    'first_uuid': seen_content[content],
                    'metadata': metadata
                })
                print(f"      [DUP] {content[:50]}... (matches earlier result)")
                continue

            # Check for stale facts (e.g., outdated timestamps or empty metadata)
            if self._is_stale_fact(metadata):
                stale_facts.append({
                    'type': 'stale',
                    'uuid': uuid,
                    'content': content,
                    'query': query,
                    'relevance': relevance,
                    'metadata': metadata
                })
                print(f"      [STALE] {content[:50]}...")
                continue

            # Good entry
            seen_content[content] = uuid
            print(f"      [OK] {content[:50]}... (score: {relevance:.2f})")

        self.issues_found.extend(vague_entities + duplicates + stale_facts)

    def _is_vague_entity(self, content: str) -> bool:
        """Check if entity name is vague or malformed."""
        vague_patterns = [
            content.strip() in ["The", "?", "...", "", "N/A", "unknown", "null", "None"],
            len(content.strip()) <= 1,
            content.startswith("?") and len(content) < 5,
            content == "." or content == "..",
            content.lower() in ["this", "that", "something", "nothing"],
        ]
        return any(vague_patterns)

    def _is_stale_fact(self, metadata: dict) -> bool:
        """Check if fact appears stale."""
        # Currently just a placeholder - could check timestamps, references, etc.
        # For now, we're conservative about stale detection
        return False

    async def _delete_confirmed_issues(self):
        """Delete clear duplicates and obviously incorrect entries."""
        if not self.issues_found:
            print("\nNo issues to delete.")
            return

        print(f"\nDeleting {len(self.issues_found)} confirmed issues...")
        print("-" * 70)

        # Be very conservative - only delete vague entities and exact duplicates
        to_delete = []

        for issue in self.issues_found:
            if issue['type'] == 'vague':
                # Delete extremely vague entities
                if issue['content'] in ["?", "", "The", "..."]:
                    to_delete.append(issue)
                    print(f"  DELETE [vague]: '{issue['content']}'")
            elif issue['type'] == 'duplicate':
                # Only delete if it's an exact duplicate with lower relevance
                if issue['relevance'] <= 0.5:
                    to_delete.append(issue)
                    print(f"  DELETE [dup]: '{issue['content'][:40]}...' (low relevance)")

        # Actually delete
        deleted_count = 0
        for item in to_delete:
            try:
                uuid = item['uuid']
                result = await self.client.texture_delete(uuid)
                self.items_deleted.append(item)
                deleted_count += 1
                print(f"    ✓ Deleted: {uuid[:16]}...")
            except Exception as e:
                print(f"    ✗ Failed to delete {uuid[:16]}...: {e}")

        print(f"\nSuccessfully deleted {deleted_count}/{len(to_delete)} items")

    def _generate_report(self) -> dict:
        """Generate curation report."""
        report = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'queries_run': len(self.search_queries),
            'issues_identified': len(self.issues_found),
            'items_deleted': len(self.items_deleted),
            'mode': 'DEEP' if self.deep_mode else 'STANDARD',
            'summary': f"Sampled {len(self.search_queries)} entities, "
                      f"found {len(self.issues_found)} issues, "
                      f"deleted {len(self.items_deleted)} entries"
        }

        print("\n" + "=" * 70)
        print("CURATION REPORT")
        print("=" * 70)
        print(f"Timestamp: {report['timestamp']}")
        print(f"Mode: {report['mode']}")
        print(f"Queries run: {report['queries_run']}")
        print(f"Issues identified: {report['issues_identified']}")
        print(f"Items deleted: {report['items_deleted']}")
        print(f"\nSummary: {report['summary']}")

        if self.issues_found:
            print("\nIssues by type:")
            by_type = {}
            for issue in self.issues_found:
                issue_type = issue.get('type', 'unknown')
                by_type.setdefault(issue_type, []).append(issue)

            for issue_type, issues in by_type.items():
                print(f"  {issue_type}: {len(issues)} issues")
                for issue in issues[:3]:
                    print(f"    - {issue['content'][:50]}...")
                if len(issues) > 3:
                    print(f"    ... and {len(issues) - 3} more")

        if self.items_deleted:
            print("\nItems deleted:")
            for item in self.items_deleted[:10]:
                print(f"  - {item['content'][:50]}...")
            if len(self.items_deleted) > 10:
                print(f"  ... and {len(self.items_deleted) - 10} more")

        print("=" * 70)

        return report


async def main(args):
    """Main entry point."""
    curator = GraphCurator(
        deep=args.deep,
        auto_delete=args.auto_delete
    )

    try:
        report = await curator.curate()
        return report
    except Exception as e:
        print(f"Curator error: {e}")
        if not args.quiet:
            import traceback
            traceback.print_exc()
        return {'error': str(e)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Graph Curator - Maintain knowledge graph health")
    parser.add_argument("--deep", action="store_true", help="Deep curation mode (more entities/results)")
    parser.add_argument("--auto-delete", action="store_true", help="Actually delete issues (default: report only)")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose output")

    args = parser.parse_args()

    report = asyncio.run(main(args))
    print("\nGraph curation complete!")
    sys.exit(0)
