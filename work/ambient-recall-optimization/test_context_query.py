#!/usr/bin/env python3
"""
Context-aware retrieval test with configurable parameters.

Usage:
    python test_context_query.py                    # defaults
    python test_context_query.py --edges 30         # 30 edges
    python test_context_query.py --edges 50 --explore 3  # 50 edges + explore depth 3
    python test_context_query.py --edges 0 --explore 2   # explore only
    python test_context_query.py --nodes 5          # 5 entity summaries
    python test_context_query.py --turns 6          # 6 turns (12 messages)
"""

import argparse
import asyncio
import random
import sqlite3
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
from graphiti_core.nodes import EntityNode
import os

# Config
DB_PATH = "/home/jeff/.claude/data/lyra_conversations.db"
LYRA_UUID = "5bd21fca-52de-41fd-a6b1-c78371d77a36"  # Known canonical


def get_random_messages(count: int = 8) -> list[dict]:
    """Get random consecutive messages from the database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get total count
    cur.execute("SELECT COUNT(*) FROM messages")
    total = cur.fetchone()[0]

    # Pick random start point (leave room for count messages)
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
        # Truncate long messages
        content = msg['content'][:500] + "..." if len(msg['content']) > 500 else msg['content']
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def extract_potential_entities(messages: list[dict]) -> list[str]:
    """Extract potential entity names from messages for explore().

    Simple heuristic: look for capitalized words and known patterns.
    """
    import re
    entities = set()

    # Always include Lyra
    entities.add("Lyra")

    # Common words to skip (expanded list)
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

        # Find capitalized words (potential names) - must be 3+ chars
        caps = re.findall(r'\b[A-Z][a-z]{2,}\b', content)
        for cap in caps:
            if cap not in skip_words:
                entities.add(cap)

        # Find issue references like #77, Issue #58
        issues = re.findall(r'#(\d+)', content)
        for issue in issues:
            entities.add(f"#{issue}")
            entities.add(f"Issue #{issue}")

        # Find known entity patterns
        if 'Jeff' in content:
            entities.add('Jeff')
        if 'Carol' in content:
            entities.add('Carol')
        if 'Discord' in content:
            entities.add('Discord')
        if 'Brandi' in content:
            entities.add('Brandi')

    # Prioritize known important entities
    priority = ['Lyra', 'Jeff', 'Carol', 'Brandi', 'Discord']
    result = [e for e in priority if e in entities]
    result += [e for e in entities if e not in priority]

    return result[:5]  # Limit to top 5


async def run_context_search(
    context_query: str,
    edge_limit: int = 30,
    node_limit: int = 3,
    explore_depth: int = 0,
    explore_entities: list[str] = None
):
    """Run Lyra-centered search with configurable parameters."""
    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "password123")

    client = Graphiti(
        neo4j_uri,
        neo4j_user,
        neo4j_password,
    )

    edge_results = None
    node_results = None
    explore_results = []

    try:
        # Edge search with node distance (Lyra-centered)
        if edge_limit > 0:
            edge_config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
            edge_config.limit = edge_limit

            edge_results = await client.search_(
                query=context_query,
                config=edge_config,
                center_node_uuid=LYRA_UUID,
                group_ids=["lyra"],
            )

        # Node search for entity summaries
        if node_limit > 0:
            node_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
            node_config.limit = node_limit

            node_results = await client.search_(
                query=context_query,
                config=node_config,
                group_ids=["lyra"],
            )

        # Explore from mentioned entities
        if explore_depth > 0 and explore_entities:
            for entity_name in explore_entities[:3]:  # Limit to 3 entities
                try:
                    # Find entity node by name
                    query = """
                    MATCH (n:Entity {group_id: $group_id})
                    WHERE toLower(n.name) CONTAINS toLower($name)
                    RETURN n.uuid as uuid, n.name as name
                    LIMIT 1
                    """
                    async with client.driver.session() as session:
                        result = await session.run(
                            query,
                            group_id="lyra",
                            name=entity_name
                        )
                        records = await result.data()

                    if records:
                        entity_uuid = records[0]['uuid']
                        entity_actual_name = records[0]['name']

                        # Get edges connected to this entity (simple BFS)
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
                                limit=explore_depth * 10
                            )
                            edge_records = await result.data()

                        for rec in edge_records:
                            explore_results.append({
                                "from_entity": entity_actual_name,
                                "rel_type": rec['rel_type'],
                                "fact": rec['fact'],
                                "source": rec['source'],
                                "target": rec['target']
                            })
                except Exception as e:
                    print(f"  (explore failed for '{entity_name}': {e})")

        return edge_results, node_results, explore_results

    finally:
        await client.close()


async def main():
    parser = argparse.ArgumentParser(description='Context-aware retrieval test')
    parser.add_argument('--edges', type=int, default=30, help='Edge search limit (0 to disable)')
    parser.add_argument('--nodes', type=int, default=3, help='Node/entity summary limit (0 to disable)')
    parser.add_argument('--explore', type=int, default=0, help='Explore depth (0 to disable)')
    parser.add_argument('--turns', type=int, default=4, help='Number of conversation turns (x2 for messages)')
    parser.add_argument('--show-all', action='store_true', help='Show all results, not just top 10')
    args = parser.parse_args()

    print("=" * 70)
    print("CONTEXT-AWARE RETRIEVAL TEST")
    print(f"  edges={args.edges}, nodes={args.nodes}, explore={args.explore}, turns={args.turns}")
    print("=" * 70)
    print()

    # Get random messages
    messages = get_random_messages(args.turns * 2)

    print(f"SAMPLE MESSAGES (IDs {messages[0]['id']} - {messages[-1]['id']}):")
    print("-" * 70)
    for msg in messages:
        speaker = "Lyra" if msg['is_lyra'] else msg['author_name']
        content = msg['content'][:100] + "..." if len(msg['content']) > 100 else msg['content']
        print(f"  [{msg['id']}] {speaker}: {content}")
    print()

    # Build context query
    context_query = format_messages_as_context(messages)
    print(f"CONTEXT QUERY LENGTH: {len(context_query)} chars")

    # Extract entities for explore
    entities = []
    if args.explore > 0:
        entities = extract_potential_entities(messages)
        print(f"EXTRACTED ENTITIES: {entities}")
    print()

    # Run search
    print("Running Lyra-centered search...")
    print()

    edge_results, node_results, explore_results = await run_context_search(
        context_query,
        edge_limit=args.edges,
        node_limit=args.nodes,
        explore_depth=args.explore,
        explore_entities=entities
    )

    # Print edge results
    if edge_results and edge_results.edges:
        display_limit = len(edge_results.edges) if args.show_all else min(10, len(edge_results.edges))
        print(f"EDGE RESULTS ({len(edge_results.edges)} total, showing {display_limit}):")
        print("-" * 70)
        for i, edge in enumerate(edge_results.edges[:display_limit], 1):
            fact = edge.fact[:100] + "..." if len(edge.fact) > 100 else edge.fact
            print(f"  {i}. [{edge.name}]")
            print(f"     Fact: {fact}")
        print()

    # Print node results (entity summaries)
    if node_results and node_results.nodes:
        print(f"ENTITY SUMMARIES ({len(node_results.nodes)} total):")
        print("-" * 70)
        for i, node in enumerate(node_results.nodes, 1):
            summary = node.summary[:200] + "..." if len(node.summary) > 200 else node.summary
            print(f"  {i}. {node.name} ({', '.join(node.labels)})")
            print(f"     {summary}")
        print()

    # Print explore results
    if explore_results:
        print(f"EXPLORE RESULTS ({len(explore_results)} edges from graph walk):")
        print("-" * 70)
        for i, exp in enumerate(explore_results[:15], 1):
            fact = exp['fact'][:80] + "..." if exp['fact'] and len(exp['fact']) > 80 else (exp['fact'] or "no fact")
            print(f"  {i}. {exp['source']} --[{exp['rel_type']}]--> {exp['target']}")
            print(f"     {fact}")
        print()

    print("=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
