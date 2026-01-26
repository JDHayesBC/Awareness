#!/usr/bin/env python3
"""Analyze tuning test results for ambient recall optimization."""

import json
import statistics
from pathlib import Path
from collections import defaultdict

def main():
    results_file = Path(__file__).parent / 'tuning_results.json'

    with open(results_file) as f:
        data = json.load(f)

    # Group results by config
    by_config = defaultdict(list)
    for result in data['results']:
        by_config[result['config']].append(result)

    print("=" * 80)
    print("DETAILED ANALYSIS")
    print("=" * 80)
    print()

    # Analyze each config
    for config_name in sorted(by_config.keys()):
        runs = by_config[config_name]
        config_info = data['configs'][config_name]

        times = [r['elapsed_ms'] for r in runs]
        contexts = [r['context_type'] for r in runs]
        edge_counts = [r['edge_count'] for r in runs]
        node_counts = [r['node_count'] for r in runs]
        explore_counts = [r['explore_count'] for r in runs]

        print(f"\n{'=' * 80}")
        print(f"Config {config_name}: {config_info['desc']}")
        print(f"{'=' * 80}")
        print(f"Timing: {statistics.mean(times):.0f}ms avg (min: {min(times)}, max: {max(times)})")
        print(f"Content: {statistics.mean(edge_counts):.1f} edges, {statistics.mean(explore_counts):.1f} explore, {statistics.mean(node_counts):.1f} nodes")
        print(f"Contexts tested: {', '.join(contexts)}")

        # Show sample content for technical context
        sample = None
        for run in runs:
            if run['context_type'] == 'technical':
                sample = run
                break

        if sample:
            print(f"\nSample content (technical context):")
            print(f"Context preview: {sample['context_preview'][:150]}...")

            if sample['edge_facts']:
                print(f"\n  Edge Facts (first 5):")
                for fact in sample['edge_facts'][:5]:
                    print(f"    - {fact}")

            if sample['explore_facts']:
                print(f"\n  Explore Facts (first 5):")
                for fact in sample['explore_facts'][:5]:
                    print(f"    - {fact}")

            if sample['node_summaries']:
                print(f"\n  Node Summaries (first 3):")
                for summary in sample['node_summaries'][:3]:
                    print(f"    - {summary}")

if __name__ == '__main__':
    main()
