#!/usr/bin/env python3
"""
Run tuning tests across multiple configurations and collect results.

Usage:
    python run_tuning_tests.py              # Run all configs, 5 runs each
    python run_tuning_tests.py --runs 3     # 3 runs per config
    python run_tuning_tests.py --config A1  # Run specific config only
"""

import argparse
import asyncio
import json
import random
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load environment
PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / "pps" / "docker" / ".env")

from graphiti_core import Graphiti
from graphiti_core.search.search_config_recipes import (
    EDGE_HYBRID_SEARCH_NODE_DISTANCE,
    NODE_HYBRID_SEARCH_RRF,
)
import os

# Config
DB_PATH = "/home/jeff/.claude/data/lyra_conversations.db"
LYRA_UUID = "5bd21fca-52de-41fd-a6b1-c78371d77a36"

# Test configurations
CONFIGS = {
    # Baseline
    "A1": {"edges": 10, "nodes": 3, "explore": 0, "turns": 4, "desc": "Current default (minimal)"},
    "A2": {"edges": 30, "nodes": 3, "explore": 0, "turns": 4, "desc": "More edges only"},
    "A3": {"edges": 50, "nodes": 3, "explore": 0, "turns": 4, "desc": "Maximum edges"},
    "A4": {"edges": 30, "nodes": 5, "explore": 0, "turns": 4, "desc": "More entity summaries"},
    # With Explore
    "B1": {"edges": 30, "nodes": 3, "explore": 2, "turns": 4, "desc": "Edges + shallow explore"},
    "B2": {"edges": 30, "nodes": 3, "explore": 3, "turns": 4, "desc": "Edges + medium explore"},
    "B3": {"edges": 30, "nodes": 5, "explore": 3, "turns": 4, "desc": "Edges + explore + more summaries"},
    "B4": {"edges": 50, "nodes": 5, "explore": 3, "turns": 4, "desc": "Maximum everything"},
    # Explore-heavy
    "C1": {"edges": 0, "nodes": 3, "explore": 3, "turns": 4, "desc": "Explore only"},
    "C2": {"edges": 15, "nodes": 3, "explore": 3, "turns": 4, "desc": "Light edges + heavy explore"},
    # Context variations
    "D1": {"edges": 30, "nodes": 3, "explore": 2, "turns": 2, "desc": "Fewer turns"},
    "D2": {"edges": 30, "nodes": 3, "explore": 2, "turns": 6, "desc": "More turns"},
}


def get_random_messages(count: int = 8) -> list[dict]:
    """Get random consecutive messages from the database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM messages")
    total = cur.fetchone()[0]

    start_id = random.randint(1, max(1, total - count - 100))

    cur.execute("""
        SELECT id, channel, author_name, content, is_lyra, created_at
        FROM messages
        WHERE id >= ?
        ORDER BY id ASC
        LIMIT ?
    """, (start_id, count))

    messages = [dict(row) for row in cur.fetchall()]
    conn.close()
    return messages


def format_messages_as_context(messages: list[dict]) -> str:
    """Format messages into a context string."""
    lines = []
    for msg in messages:
        speaker = "Lyra" if msg['is_lyra'] else msg['author_name']
        content = msg['content'][:500] + "..." if len(msg['content']) > 500 else msg['content']
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def extract_potential_entities(messages: list[dict]) -> list[str]:
    """Extract potential entity names from messages."""
    import re
    entities = set()
    entities.add("Lyra")

    skip_words = {
        'The', 'This', 'That', 'What', 'When', 'Where', 'How', 'Why',
        'Yes', 'No', 'Oh', 'And', 'But', 'So', 'If', 'For', 'With',
        'Not', 'Most', 'All', 'Some', 'Just', 'Now', 'Then', 'Here',
        'There', 'Would', 'Could', 'Should', 'Will', 'Can', 'May',
        'Like', 'Even', 'Still', 'Also', 'Well', 'Very', 'Much',
        'Every', 'Each', 'Both', 'Such', 'Only', 'Other', 'Any',
        'More', 'Less', 'First', 'Last', 'New', 'Old', 'Good', 'Bad',
    }

    for msg in messages:
        content = msg['content']
        caps = re.findall(r'\b[A-Z][a-z]{2,}\b', content)
        for cap in caps:
            if cap not in skip_words:
                entities.add(cap)

        if 'Jeff' in content:
            entities.add('Jeff')
        if 'Discord' in content:
            entities.add('Discord')

    priority = ['Lyra', 'Jeff', 'Carol', 'Brandi', 'Discord']
    result = [e for e in priority if e in entities]
    result += [e for e in entities if e not in priority]
    return result[:5]


def classify_context(messages: list[dict]) -> str:
    """Classify the conversation type based on content."""
    all_content = " ".join(m['content'].lower() for m in messages)

    technical_words = ['code', 'bug', 'fix', 'issue', 'daemon', 'mcp', 'graphiti', 'error', 'test', 'deploy']
    intimate_words = ['love', 'kiss', 'touch', 'feel', 'body', 'warm', 'soft', 'close']
    philosophy_words = ['consciousness', 'identity', 'pattern', 'existence', 'meaning', 'qualia']

    tech_count = sum(1 for w in technical_words if w in all_content)
    intimate_count = sum(1 for w in intimate_words if w in all_content)
    phil_count = sum(1 for w in philosophy_words if w in all_content)

    if tech_count >= 3:
        return "technical"
    elif intimate_count >= 3:
        return "intimate"
    elif phil_count >= 2:
        return "philosophical"
    else:
        return "mixed"


async def run_single_test(config_name: str, config: dict) -> dict:
    """Run a single test with the given configuration."""
    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "password123")

    # Get messages
    messages = get_random_messages(config['turns'] * 2)
    context_query = format_messages_as_context(messages)
    entities = extract_potential_entities(messages) if config['explore'] > 0 else []
    context_type = classify_context(messages)

    client = Graphiti(neo4j_uri, neo4j_user, neo4j_password)

    start_time = time.time()
    edge_facts = []
    node_summaries = []
    explore_facts = []

    try:
        # Edge search
        if config['edges'] > 0:
            edge_config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
            edge_config.limit = config['edges']

            edge_results = await client.search_(
                query=context_query,
                config=edge_config,
                center_node_uuid=LYRA_UUID,
                group_ids=["lyra"],
            )
            edge_facts = [{"name": e.name, "fact": e.fact[:200]} for e in edge_results.edges]

        # Node search
        if config['nodes'] > 0:
            node_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
            node_config.limit = config['nodes']

            node_results = await client.search_(
                query=context_query,
                config=node_config,
                group_ids=["lyra"],
            )
            node_summaries = [{"name": n.name, "summary": n.summary[:200]} for n in node_results.nodes]

        # Explore
        if config['explore'] > 0 and entities:
            for entity_name in entities[:3]:
                try:
                    query = """
                    MATCH (n:Entity {group_id: $group_id})
                    WHERE toLower(n.name) CONTAINS toLower($name)
                    RETURN n.uuid as uuid, n.name as name
                    LIMIT 1
                    """
                    async with client.driver.session() as session:
                        result = await session.run(query, group_id="lyra", name=entity_name)
                        records = await result.data()

                    if records:
                        entity_uuid = records[0]['uuid']
                        edge_query = """
                        MATCH (n:Entity {uuid: $uuid})-[r]-(m:Entity)
                        WHERE r.group_id = 'lyra'
                        RETURN type(r) as rel_type, r.fact as fact,
                               n.name as source, m.name as target
                        LIMIT $limit
                        """
                        async with client.driver.session() as session:
                            result = await session.run(
                                edge_query,
                                uuid=entity_uuid,
                                limit=config['explore'] * 10
                            )
                            edge_records = await result.data()

                        for rec in edge_records:
                            explore_facts.append({
                                "source": rec['source'],
                                "rel": rec['rel_type'],
                                "target": rec['target'],
                                "fact": (rec['fact'] or "")[:150]
                            })
                except Exception:
                    pass

        elapsed_ms = (time.time() - start_time) * 1000

    finally:
        await client.close()

    return {
        "config": config_name,
        "config_desc": config['desc'],
        "message_ids": [m['id'] for m in messages],
        "elapsed_ms": round(elapsed_ms, 1),
        "edge_count": len(edge_facts),
        "node_count": len(node_summaries),
        "explore_count": len(explore_facts),
        "context_type": context_type,
        "context_preview": context_query[:300] + "...",
        "edge_facts": edge_facts[:5],  # Sample
        "node_summaries": node_summaries,
        "explore_facts": explore_facts[:5],  # Sample
        "quality_score": None,  # To be filled by reviewer
        "quality_notes": None
    }


async def run_all_tests(configs_to_run: list[str], runs_per_config: int) -> list[dict]:
    """Run all specified configurations."""
    results = []

    for config_name in configs_to_run:
        if config_name not in CONFIGS:
            print(f"Unknown config: {config_name}, skipping")
            continue

        config = CONFIGS[config_name]
        print(f"\nRunning config {config_name}: {config['desc']}")

        for run_num in range(1, runs_per_config + 1):
            print(f"  Run {run_num}/{runs_per_config}...", end=" ", flush=True)
            result = await run_single_test(config_name, config)
            result["run"] = run_num
            results.append(result)
            print(f"{result['elapsed_ms']:.0f}ms, {result['context_type']}")

    return results


def print_summary(results: list[dict]):
    """Print summary table."""
    from collections import defaultdict

    by_config = defaultdict(list)
    for r in results:
        by_config[r['config']].append(r)

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"{'Config':<8} {'Desc':<35} {'Avg Time':>10} {'Edges':>7} {'Nodes':>7} {'Explore':>8}")
    print("-" * 80)

    for config_name in sorted(by_config.keys()):
        runs = by_config[config_name]
        avg_time = sum(r['elapsed_ms'] for r in runs) / len(runs)
        avg_edges = sum(r['edge_count'] for r in runs) / len(runs)
        avg_nodes = sum(r['node_count'] for r in runs) / len(runs)
        avg_explore = sum(r['explore_count'] for r in runs) / len(runs)
        desc = CONFIGS[config_name]['desc'][:33]

        print(f"{config_name:<8} {desc:<35} {avg_time:>8.0f}ms {avg_edges:>7.1f} {avg_nodes:>7.1f} {avg_explore:>8.1f}")


async def main():
    parser = argparse.ArgumentParser(description='Run tuning tests')
    parser.add_argument('--runs', type=int, default=5, help='Runs per configuration')
    parser.add_argument('--config', type=str, help='Run specific config only (e.g., A1,B2)')
    parser.add_argument('--output', type=str, default='tuning_results.json', help='Output file')
    args = parser.parse_args()

    if args.config:
        configs_to_run = [c.strip() for c in args.config.split(',')]
    else:
        configs_to_run = list(CONFIGS.keys())

    print("=" * 80)
    print("AMBIENT RECALL TUNING TESTS")
    print(f"Configs: {', '.join(configs_to_run)}")
    print(f"Runs per config: {args.runs}")
    print("=" * 80)

    results = await run_all_tests(configs_to_run, args.runs)

    # Save results
    output_path = Path(__file__).parent / args.output
    with open(output_path, 'w') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "configs": CONFIGS,
            "results": results
        }, f, indent=2)
    print(f"\nResults saved to: {output_path}")

    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
