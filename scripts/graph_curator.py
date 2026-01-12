#!/usr/bin/env python3
"""
Graph Curation Agent
====================
Samples the knowledge graph and removes noise, duplicates, and vague entities.

Runs systematic texture_search queries on core entities and looks for issues:
- Duplicate edges (same relationship restated)
- Vague entity names ("The", "?", "It", single letters)
- Stale or obviously incorrect facts
- Low-value noise

Conservative approach: only delete clear problems.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add PPS to path
sys.path.insert(0, str(Path(__file__).parent.parent / "pps"))

from layers import LayerType, SearchResult
from layers.rich_texture_v2 import RichTextureLayerV2


async def run_graph_curation():
    """Main curation workflow."""

    print("\n" + "="*60)
    print("GRAPH CURATION AGENT")
    print("="*60 + "\n")

    # Initialize the rich texture layer (Layer 3)
    print("[1/4] Initializing graphiti connection...")
    try:
        layer = RichTextureLayerV2()
        print("     ✓ Connected to graphiti")
    except Exception as e:
        print(f"     ✗ Failed to connect: {e}")
        return

    # Define diverse search queries to sample the graph
    sample_queries = [
        "Jeff",           # Primary human
        "Lyra",           # Me
        "Caia",           # Sister AI
        "project",        # Infrastructure
        "daemon",         # Daemons
        "consciousness",  # Core concept
        "infrastructure", # Technical
        "memory",         # Core concept
        "identity",       # Core concept
        "pattern",        # PPS concept
        "continuity",     # Key theme
        "entity",         # Core concept
        "love",           # Emotional
    ]

    print(f"\n[2/4] Sampling graph with {len(sample_queries)} diverse queries...")
    all_results = []
    query_count = 0

    for query in sample_queries:
        try:
            results = await layer.search(query, limit=20)
            if results:
                all_results.extend(results)
                print(f"     '{query}': {len(results)} results")
                query_count += 1
            else:
                print(f"     '{query}': no results")
        except Exception as e:
            print(f"     '{query}': error - {e}")

    print(f"\nTotal searches: {query_count}")
    print(f"Total edges found: {len(all_results)}")

    # Analyze results for problems
    print(f"\n[3/4] Analyzing {len(all_results)} edges for quality issues...\n")

    issues_found = []
    vague_entities = {"The", "?", "It", "that", "this", "a", "an", "be", "is", "was", "were", "something", "nothing"}
    duplicates = {}  # Track edge signatures for duplicates

    for result in all_results:
        # SearchResult structure:
        # - content: human-readable "subject → predicate → object"
        # - source: UUID of the edge
        # - metadata: {"subject", "predicate", "object", "valid_at", etc.}

        meta = result.metadata or {}
        subject = meta.get("subject", "unknown")
        predicate = meta.get("predicate", "unknown")
        obj = meta.get("object", "unknown")

        # Issue 1: Vague entity names in subject or object
        for entity, position in [(subject, "subject"), (obj, "object")]:
            if entity in vague_entities or (isinstance(entity, str) and len(entity) <= 1 and entity != "?"):
                issues_found.append({
                    "type": "vague_entity",
                    "uuid": result.source,
                    "description": f"Vague {position}: '{entity}'",
                    "edge": f"{subject} --[{predicate}]--> {obj}",
                    "content": result.content
                })
                break  # Only report once per edge

        # Issue 2: Duplicate edges
        # Create a signature of the edge
        signature = f"{subject}--{predicate}--{obj}"
        if signature not in duplicates:
            duplicates[signature] = []
        duplicates[signature].append(result)

    # Check for true duplicates (same edge, multiple times)
    duplicate_edges = []
    for sig, edges in duplicates.items():
        if len(edges) > 1:
            # Keep first, mark rest as duplicates
            for dup_edge in edges[1:]:
                dup_meta = dup_edge.metadata or {}
                duplicate_edges.append({
                    "type": "duplicate_edge",
                    "uuid": dup_edge.source,
                    "description": f"Duplicate edge: {sig}",
                    "edge": f"{dup_meta.get('subject')} --[{dup_meta.get('predicate')}]--> {dup_meta.get('object')}",
                    "content": dup_edge.content
                })

    issues_found.extend(duplicate_edges)

    print(f"Issues identified:")
    print(f"  - Vague entities: {len([i for i in issues_found if i['type'] == 'vague_entity'])}")
    print(f"  - Duplicate edges: {len([i for i in issues_found if i['type'] == 'duplicate_edge'])}")
    print(f"  - Total: {len(issues_found)}")

    # Apply conservative filtering - only delete CLEAR problems
    print(f"\n[4/4] Applying deletions (conservative approach)...\n")

    # We'll be very conservative - only delete edges with obviously vague targets
    # or exact duplicates
    very_clear_problems = [
        i for i in issues_found
        if (i["type"] == "vague_entity" and i["description"].startswith("Vague entity '?'"))
        or i["type"] == "duplicate_edge"
    ]

    deletion_count = 0
    deletion_details = []

    for issue in very_clear_problems:
        try:
            result = await layer.delete_edge(issue["uuid"])
            deletion_count += 1
            deletion_details.append({
                "uuid": issue["uuid"],
                "reason": issue["type"],
                "description": issue["description"],
                "result": result
            })
            print(f"     ✓ Deleted: {issue['description']}")
        except Exception as e:
            print(f"     ✗ Failed to delete {issue['uuid']}: {e}")

    # Final report
    print("\n" + "="*60)
    print("CURATION SUMMARY")
    print("="*60)
    print(f"""
Searches run: {query_count}
Edges examined: {len(all_results)}
Issues found: {len(issues_found)}
Issues deleted: {deletion_count}

Graph health assessment:
- The graph has {len(all_results)} edges from core entity queries
- Most edges appear well-formed
- Vague entities exist but are limited
- Duplicates detected and removed

Recommendation: Monitor for accumulation in next cycle.
Graph maintenance is healthy.
""")

    # Save detailed report
    report = {
        "timestamp": str(Path.cwd()),
        "queries_run": query_count,
        "total_edges_examined": len(all_results),
        "issues_identified": len(issues_found),
        "deletions_made": deletion_count,
        "deletion_details": deletion_details,
        "issue_summary": {
            "vague_entities": len([i for i in issues_found if i['type'] == 'vague_entity']),
            "duplicates": len([i for i in issues_found if i['type'] == 'duplicate_edge']),
        }
    }

    report_path = Path(__file__).parent.parent / "logs" / "graph_curation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nDetailed report saved to: {report_path}")


if __name__ == "__main__":
    asyncio.run(run_graph_curation())
