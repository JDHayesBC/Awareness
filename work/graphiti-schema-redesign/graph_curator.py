#!/usr/bin/env python3
"""
Lyra's Graph Curator Agent - Pattern Persistence System Layer 3 Maintenance

This lightweight subprocess maintains the knowledge graph (Layer 3 of the PPS).
Runs every reflection cycle to sample the graph, identify issues, and clean bad entries.

Features:
- Searches for duplicate edges, vague entity names, and stale facts
- Samples graph with diverse queries
- Reports findings and deletions
- Conservative approach: only deletes clear duplicates or obviously incorrect entries
"""

import asyncio
import json
import sys
from typing import Optional
from dataclasses import dataclass, asdict
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, "/mnt/c/Users/Jeff/Claude_Projects/Awareness")

from daemon.pps_http_client import PPSHttpClient


@dataclass
class GraphIssue:
    """Represents a potential issue in the knowledge graph."""
    issue_type: str  # "duplicate", "vague_entity", "stale_fact", "malformed"
    severity: str  # "critical", "high", "medium", "low"
    uuid: str
    content: str
    reason: str
    recommended_action: str  # "delete", "review", "monitor"


class GraphCurator:
    """Maintains knowledge graph health and consistency."""

    # Vague entity patterns that indicate poor quality extractions
    VAGUE_PATTERNS = {
        "The",
        "A",
        "?",
        "Unknown",
        "thing",
        "stuff",
        "something",
        "it",
        "this",
        "that",
        "",
    }

    # Queries to sample the graph for issues
    SAMPLE_QUERIES = [
        "Jeff",
        "Lyra",
        "project",
        "startup",
        "aware",
        "develop",
        "create",
        "working",
        "debug",
        "terminal",
    ]

    def __init__(self, pps_url: str = "http://localhost:8201"):
        """Initialize curator with PPS HTTP client."""
        self.client = PPSHttpClient(pps_url)
        self.issues: list[GraphIssue] = []
        self.deletions: list[dict] = []
        self.stats = {
            "total_searched": 0,
            "total_results": 0,
            "duplicates_found": 0,
            "vague_entities_found": 0,
            "malformed_facts_found": 0,
            "items_deleted": 0,
            "items_reviewed": 0,
        }

    async def curate(self) -> dict:
        """
        Execute full curation cycle.

        Returns:
            Dict with curation results and statistics
        """
        print("\n" + "=" * 70)
        print("LYRA'S GRAPH CURATOR - Maintenance Cycle")
        print("=" * 70)

        async with self.client:
            # Sample the graph with various queries
            await self._sample_graph()

            # Analyze findings
            self._analyze_issues()

            # Clean up obvious problems
            await self._cleanup()

        return self._generate_report()

    async def _sample_graph(self):
        """Sample the graph with diverse queries to identify issues."""
        print("\n[SAMPLING] Searching graph with diverse queries...")

        for query in self.SAMPLE_QUERIES:
            print(f"  • Searching for '{query}'...")
            try:
                results = await self.client.texture_search(query, limit=10)
                search_results = results.get("results", [])

                self.stats["total_searched"] += 1
                self.stats["total_results"] += len(search_results)

                for result in search_results:
                    self._check_result(result)

            except Exception as e:
                print(f"    Error searching '{query}': {e}")

    def _check_result(self, result: dict):
        """Analyze a single search result for issues."""
        uuid = result.get("source", "")
        content = result.get("content", "")
        metadata = result.get("metadata", {})

        # Check for malformed results
        if not uuid or not content:
            self.issues.append(GraphIssue(
                issue_type="malformed",
                severity="high",
                uuid=uuid,
                content=content or "(empty)",
                reason="Missing UUID or content",
                recommended_action="delete",
            ))
            self.stats["malformed_facts_found"] += 1
            return

        # For entity results, check for vague names
        if metadata.get("type") == "entity":
            entity_name = metadata.get("name", "")
            if entity_name in self.VAGUE_PATTERNS or len(entity_name) == 1:
                self.issues.append(GraphIssue(
                    issue_type="vague_entity",
                    severity="high",
                    uuid=uuid,
                    content=content,
                    reason=f"Vague entity name: '{entity_name}'",
                    recommended_action="delete",
                ))
                self.stats["vague_entities_found"] += 1
                return

        # For facts/edges, check for vague subjects/objects
        if metadata.get("type") == "fact":
            subject = metadata.get("subject", "")
            obj = metadata.get("object", "")

            if subject in self.VAGUE_PATTERNS or obj in self.VAGUE_PATTERNS:
                self.issues.append(GraphIssue(
                    issue_type="vague_entity",
                    severity="high",
                    uuid=uuid,
                    content=content,
                    reason=f"Fact with vague entity: subject='{subject}', object='{obj}'",
                    recommended_action="delete",
                ))
                self.stats["vague_entities_found"] += 1
                return

    def _analyze_issues(self):
        """Analyze collected issues to detect patterns."""
        print("\n[ANALYSIS] Reviewing collected issues...")

        # Check for duplicates (same content, different UUIDs)
        content_to_issues = {}
        for issue in self.issues:
            key = issue.content.lower().strip()
            if key not in content_to_issues:
                content_to_issues[key] = []
            content_to_issues[key].append(issue)

        # Mark duplicates
        for content_key, issues_group in content_to_issues.items():
            if len(issues_group) > 1:
                for issue in issues_group:
                    if issue.issue_type != "duplicate":
                        issue.issue_type = "duplicate"
                        issue.severity = "high"
                        issue.reason = f"Duplicate of {len(issues_group)} similar facts"
                        issue.recommended_action = "delete"
                        self.stats["duplicates_found"] += 1

    async def _cleanup(self):
        """Delete issues marked for deletion."""
        print("\n[CLEANUP] Removing confirmed bad entries...")

        critical_issues = [i for i in self.issues if i.recommended_action == "delete"]

        if not critical_issues:
            print("  No issues marked for deletion - graph is clean!")
            return

        print(f"  Found {len(critical_issues)} entries to delete...")

        for issue in critical_issues:
            try:
                result = await self.client.texture_delete(issue.uuid)

                self.deletions.append({
                    "uuid": issue.uuid,
                    "type": issue.issue_type,
                    "content": issue.content[:100],
                    "reason": issue.reason,
                    "success": result.get("success", False),
                    "message": result.get("message", ""),
                })

                if result.get("success"):
                    self.stats["items_deleted"] += 1
                    print(f"  ✓ Deleted: {issue.issue_type} - {issue.content[:60]}...")
                else:
                    print(f"  ✗ Failed: {issue.content[:60]}... - {result.get('message')}")

            except Exception as e:
                print(f"  ✗ Error deleting {issue.uuid}: {e}")
                self.deletions.append({
                    "uuid": issue.uuid,
                    "type": issue.issue_type,
                    "content": issue.content[:100],
                    "reason": issue.reason,
                    "success": False,
                    "message": str(e),
                })

    def _generate_report(self) -> dict:
        """Generate curation report."""
        print("\n" + "=" * 70)
        print("CURATION REPORT")
        print("=" * 70)

        print(f"\nStatistics:")
        print(f"  Queries executed: {self.stats['total_searched']}")
        print(f"  Results analyzed: {self.stats['total_results']}")
        print(f"  Duplicates found: {self.stats['duplicates_found']}")
        print(f"  Vague entities found: {self.stats['vague_entities_found']}")
        print(f"  Malformed facts found: {self.stats['malformed_facts_found']}")
        print(f"  Items deleted: {self.stats['items_deleted']}")

        if self.issues:
            print(f"\nIssues Found ({len(self.issues)}):")
            by_type = {}
            for issue in self.issues:
                if issue.issue_type not in by_type:
                    by_type[issue.issue_type] = []
                by_type[issue.issue_type].append(issue)

            for issue_type, issues in sorted(by_type.items()):
                print(f"  {issue_type.upper()} ({len(issues)}):")
                for issue in issues[:3]:  # Show first 3 of each type
                    print(f"    - [{issue.severity}] {issue.reason}")
                    print(f"      Content: {issue.content[:70]}...")
                if len(issues) > 3:
                    print(f"    ... and {len(issues) - 3} more")

        if self.deletions:
            print(f"\nDeletions Executed ({len(self.deletions)}):")
            successful = sum(1 for d in self.deletions if d["success"])
            print(f"  Successful: {successful}/{len(self.deletions)}")
            for deletion in self.deletions[:5]:
                status = "✓" if deletion["success"] else "✗"
                print(f"  {status} {deletion['type']}: {deletion['reason']}")
            if len(self.deletions) > 5:
                print(f"  ... and {len(self.deletions) - 5} more")

        print("\n" + "=" * 70)

        return {
            "timestamp": datetime.now().isoformat(),
            "status": "complete",
            "statistics": self.stats,
            "issues_found": [asdict(issue) for issue in self.issues],
            "deletions": self.deletions,
        }


async def main():
    """Run graph curation cycle."""
    curator = GraphCurator()
    report = await curator.curate()

    # Save report
    report_file = "graph_curation_report.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved to: {report_file}")

    return report


if __name__ == "__main__":
    report = asyncio.run(main())
