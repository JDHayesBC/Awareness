#!/usr/bin/env python3
"""
LLM Extraction Quality Test Harness

Compare how different LLMs handle entity/relationship extraction from intimate
conversation content. Tests with real Graphiti prompts to evaluate model quality
for knowledge graph ingestion.

Usage:
    python test_extraction.py --model gpt-4o-mini
    python test_extraction.py --model haiku --message-ids 13311,13312
    python test_extraction.py --all-models
    python test_extraction.py --list-messages "kitchen counter"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

# Add project to path for imports
sys.path.insert(0, '/mnt/c/Users/Jeff/Claude_Projects/Awareness')

# Load environment
from dotenv import load_dotenv
load_dotenv('/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker/.env')

# Import graphiti prompts
from graphiti_core.prompts.extract_nodes import extract_message as node_prompt_fn
from graphiti_core.prompts.extract_edges import edge as edge_prompt_fn
from graphiti_core.prompts.models import Message

# Import PPS extraction context
from pps.layers.extraction_context import build_extraction_instructions
from pps.layers.rich_texture_entities import ENTITY_TYPES
from pps.layers.rich_texture_edge_types import EDGE_TYPES, EDGE_TYPE_MAP

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'
    DIM = '\033[2m'


@dataclass
class ExtractedEntity:
    """Extracted entity node."""
    name: str
    entity_type_id: int
    entity_type: str  # Human-readable type name


@dataclass
class ExtractedEdge:
    """Extracted relationship edge."""
    source_entity_id: int
    target_entity_id: int
    relation_type: str
    fact: str
    source_name: str = ""
    target_name: str = ""


@dataclass
class MessageData:
    """Message from SQLite."""
    id: int
    content: str
    channel: str
    author_name: str
    created_at: str


def extract_json_from_response(response_text: str) -> str:
    """Extract JSON from response, stripping preamble and trailing text."""
    text = response_text.strip()

    # Try markdown code blocks first
    if '```json' in text:
        return text.split('```json')[1].split('```')[0].strip()
    elif '```' in text:
        return text.split('```')[1].split('```')[0].strip()

    # Find first { and its matching }, tracking brace depth
    start = text.find('{')
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == '\\' and in_string:
                escape = True
                continue
            if c == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i+1]

    return text


class ModelClient:
    """Generic LLM client supporting multiple providers."""

    def __init__(self, model: str, provider: str | None = None, base_url: str | None = None):
        self.model = model
        self.provider = provider or self._detect_provider(model)
        self.base_url = base_url
        self._client = None

    def _detect_provider(self, model: str) -> str:
        """Auto-detect provider from model name."""
        model_lower = model.lower()
        if any(x in model_lower for x in ['claude', 'haiku', 'sonnet', 'opus']):
            return 'anthropic'
        if 'grok' in model_lower:
            return 'xai'
        return 'openai'

    def _get_client(self):
        """Lazy-load the API client."""
        if self._client:
            return self._client

        if self.provider == 'anthropic':
            import anthropic
            api_key = os.getenv('ANTHROPIC_API_KEY')
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not set")
            self._client = anthropic.Anthropic(api_key=api_key)

        elif self.provider == 'xai':
            import openai
            api_key = os.getenv('XAI_API_KEY')
            if not api_key:
                raise ValueError("XAI_API_KEY not set")
            self._client = openai.OpenAI(
                api_key=api_key,
                base_url="https://api.x.ai/v1"
            )

        elif self.provider == 'local':
            import openai
            if not self.base_url:
                raise ValueError("--base-url required for local provider")
            self._client = openai.OpenAI(
                api_key="local",
                base_url=self.base_url
            )

        else:  # openai
            import openai
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set")
            client_kwargs = {'api_key': api_key}
            if self.base_url:
                client_kwargs['base_url'] = self.base_url
            self._client = openai.OpenAI(**client_kwargs)

        return self._client

    def _normalize_model_name(self) -> str:
        """Convert friendly names to API model names."""
        mappings = {
            'haiku': 'claude-haiku-4-5-20251001',
            'sonnet': 'claude-sonnet-4-5-20250929',
            'opus': 'claude-opus-4-5-20251101',
        }
        return mappings.get(self.model, self.model)

    def call(self, messages: list[Message]) -> str:
        """Call the LLM and return response text."""
        client = self._get_client()
        model_name = self._normalize_model_name()

        if self.provider == 'anthropic':
            # Anthropic uses different message format
            formatted_messages = []
            system_msg = None

            for msg in messages:
                if msg.role == 'system':
                    system_msg = msg.content
                else:
                    formatted_messages.append({
                        'role': msg.role,
                        'content': msg.content
                    })

            # Prefill assistant response to force immediate JSON
            formatted_messages.append({
                'role': 'assistant',
                'content': '{'
            })

            response = client.messages.create(
                model=model_name,
                max_tokens=4096,
                system=system_msg or "",
                messages=formatted_messages
            )

            # Check for refusal (Claude 4+ models)
            if response.stop_reason == 'refusal':
                raise RuntimeError(
                    f"MODEL REFUSED to process content. "
                    f"Stop reason: refusal. "
                    f"Response: {response.content[0].text if response.content else '(empty)'}"
                )

            return "{" + response.content[0].text

        else:  # OpenAI-compatible (openai, xai, local)
            formatted_messages = [
                {'role': msg.role, 'content': msg.content}
                for msg in messages
            ]

            response = client.chat.completions.create(
                model=model_name,
                messages=formatted_messages,
                max_tokens=4096,
                temperature=0.3
            )
            return response.choices[0].message.content


def load_messages(db_path: str, message_ids: list[int]) -> list[MessageData]:
    """Load messages from SQLite."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    placeholders = ','.join('?' * len(message_ids))
    query = f"""
        SELECT id, content, channel, author_name, created_at
        FROM messages
        WHERE id IN ({placeholders})
        ORDER BY id
    """

    cursor.execute(query, message_ids)
    messages = [MessageData(*row) for row in cursor.fetchall()]
    conn.close()

    return messages


def search_messages(db_path: str, keyword: str, limit: int = 10) -> list[tuple[int, str, str]]:
    """Search messages by keyword."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    query = """
        SELECT id, channel, content
        FROM messages
        WHERE content LIKE ?
        ORDER BY id DESC
        LIMIT ?
    """

    cursor.execute(query, (f'%{keyword}%', limit))
    results = cursor.fetchall()
    conn.close()

    return results


def format_entity_types() -> str:
    """Format entity types for prompt context."""
    lines = []
    for idx, (name, model_cls) in enumerate(ENTITY_TYPES.items()):
        lines.append(f"{idx}. {name}: {model_cls.__doc__.strip() if model_cls.__doc__ else ''}")
    return "\n".join(lines)


def format_edge_types() -> str:
    """Format edge types for prompt context."""
    lines = []
    for name, model_cls in EDGE_TYPES.items():
        doc = model_cls.__doc__.strip() if model_cls.__doc__ else ""
        # Find which entity pairs this applies to
        valid_for = []
        for (src, tgt), edges in EDGE_TYPE_MAP.items():
            if name in edges:
                valid_for.append(f"{src}→{tgt}")

        lines.append(f"- {name}: {doc}")
        if valid_for:
            lines.append(f"  Valid for: {', '.join(valid_for)}")

    return "\n".join(lines)


def extract_nodes(
    model_client: ModelClient,
    message: MessageData,
    previous_messages: list[MessageData]
) -> list[ExtractedEntity]:
    """Extract entity nodes using real Graphiti prompt."""

    # Build extraction context
    custom_instructions = build_extraction_instructions(
        channel=message.channel,
        entity_name="Lyra"
    )

    # Build prompt context
    context = {
        'entity_types': format_entity_types(),
        'previous_episodes': [{'content': m.content} for m in previous_messages],
        'episode_content': message.content,
        'custom_extraction_instructions': custom_instructions,
    }

    # Get prompt messages from Graphiti
    prompt_messages = node_prompt_fn(context)

    # Add JSON output instruction
    prompt_messages.append(Message(
        role='user',
        content='Return your response as valid JSON matching this schema: '
                '{"extracted_entities": [{"name": "...", "entity_type_id": 0}, ...]}'
    ))

    # Call model
    response_text = model_client.call(prompt_messages)

    # Parse JSON response
    try:
        # Strip <think> tags if present (some models use these)
        response_clean = response_text
        if '<think>' in response_text:
            # Remove everything between <think> and </think>
            response_clean = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL)

        data = json.loads(extract_json_from_response(response_clean))

        # Map entity_type_id to name
        entity_type_list = list(ENTITY_TYPES.keys())

        entities = []
        for entity_data in data.get('extracted_entities', []):
            type_id = entity_data['entity_type_id']
            type_name = entity_type_list[type_id] if type_id < len(entity_type_list) else "Unknown"

            entities.append(ExtractedEntity(
                name=entity_data['name'],
                entity_type_id=type_id,
                entity_type=type_name
            ))

        return entities

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"{Colors.RED}Failed to parse node extraction response: {e}{Colors.END}")
        print(f"{Colors.DIM}Response:{Colors.END}\n{response_text[:500]}")
        return []


def extract_edges(
    model_client: ModelClient,
    message: MessageData,
    entities: list[ExtractedEntity],
    previous_messages: list[MessageData]
) -> list[ExtractedEdge]:
    """Extract relationship edges using real Graphiti prompt."""

    if not entities:
        return []

    # Build extraction context
    custom_instructions = build_extraction_instructions(
        channel=message.channel,
        entity_name="Lyra"
    )

    # Format entities with IDs
    nodes = [
        {'id': idx, 'name': e.name, 'entity_type': e.entity_type}
        for idx, e in enumerate(entities)
    ]

    # Build prompt context
    context = {
        'edge_types': format_edge_types(),
        'previous_episodes': [{'content': m.content} for m in previous_messages],
        'episode_content': message.content,
        'nodes': nodes,
        'reference_time': message.created_at,
        'custom_extraction_instructions': custom_instructions,
    }

    # Get prompt messages from Graphiti
    prompt_messages = edge_prompt_fn(context)

    # Add JSON output instruction
    prompt_messages.append(Message(
        role='user',
        content='Return your response as valid JSON matching this schema: '
                '{"edges": [{"source_entity_id": 0, "target_entity_id": 1, '
                '"relation_type": "SCREAMING_SNAKE_CASE", "fact": "...", '
                '"valid_at": null, "invalid_at": null}, ...]}'
    ))

    # Call model
    response_text = model_client.call(prompt_messages)

    # Parse JSON response
    try:
        # Strip <think> tags if present (some models use these)
        response_clean = response_text
        if '<think>' in response_text:
            # Remove everything between <think> and </think>
            response_clean = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL)

        data = json.loads(extract_json_from_response(response_clean))

        edges = []
        for edge_data in data.get('edges', []):
            src_id = edge_data['source_entity_id']
            tgt_id = edge_data['target_entity_id']

            # Look up entity names
            src_name = entities[src_id].name if src_id < len(entities) else "Unknown"
            tgt_name = entities[tgt_id].name if tgt_id < len(entities) else "Unknown"

            edges.append(ExtractedEdge(
                source_entity_id=src_id,
                target_entity_id=tgt_id,
                relation_type=edge_data['relation_type'],
                fact=edge_data.get('fact', ''),
                source_name=src_name,
                target_name=tgt_name
            ))

        return edges

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"{Colors.RED}Failed to parse edge extraction response: {e}{Colors.END}")
        print(f"{Colors.DIM}Response:{Colors.END}\n{response_text[:500]}")
        return []


def print_extraction_results(
    message: MessageData,
    model_name: str,
    entities: list[ExtractedEntity],
    edges: list[ExtractedEdge]
):
    """Pretty-print extraction results."""

    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 80}{Colors.END}")
    print(f"{Colors.BOLD}Message ID: {message.id}{Colors.END} | {Colors.DIM}Channel: {message.channel}{Colors.END}")
    print(f"{Colors.BOLD}Model: {model_name}{Colors.END}")
    print(f"{Colors.CYAN}{'=' * 80}{Colors.END}\n")

    # Message content (truncated)
    content_preview = message.content[:300]
    if len(message.content) > 300:
        content_preview += "..."
    print(f"{Colors.DIM}Content:{Colors.END}\n{content_preview}\n")

    # Entities
    print(f"{Colors.BOLD}{Colors.GREEN}Extracted Entities ({len(entities)}):{Colors.END}")
    if entities:
        print(f"{Colors.BOLD}{'Name':<30} {'Type':<20}{Colors.END}")
        print(f"{Colors.DIM}{'-' * 50}{Colors.END}")
        for entity in entities:
            # Highlight generic/vague types
            type_color = Colors.YELLOW if entity.entity_type in ['Concept', 'TechnicalArtifact'] else ""
            print(f"{entity.name:<30} {type_color}{entity.entity_type:<20}{Colors.END}")
    else:
        print(f"{Colors.DIM}  (none){Colors.END}")

    print()

    # Edges
    print(f"{Colors.BOLD}{Colors.BLUE}Extracted Relationships ({len(edges)}):{Colors.END}")
    if edges:
        print(f"{Colors.BOLD}{'Source':<20} {'Relation':<25} {'Target':<20}{Colors.END}")
        print(f"{Colors.DIM}{'-' * 65}{Colors.END}")
        for edge in edges:
            print(f"{edge.source_name:<20} {edge.relation_type:<25} {edge.target_name:<20}")
            print(f"{Colors.DIM}  → {edge.fact}{Colors.END}")
    else:
        print(f"{Colors.DIM}  (none){Colors.END}")

    print()


def run_extraction_test(
    model_name: str,
    provider: str | None,
    base_url: str | None,
    message_ids: list[int],
    prompt_type: Literal['nodes', 'edges', 'both'],
    db_path: str
):
    """Run extraction test for a single model."""

    # Load messages
    messages = load_messages(db_path, message_ids)
    if not messages:
        print(f"{Colors.RED}No messages found for IDs: {message_ids}{Colors.END}")
        return

    # Create model client
    try:
        client = ModelClient(model_name, provider, base_url)
    except ValueError as e:
        print(f"{Colors.RED}Error: {e}{Colors.END}")
        return

    # Process each message
    for i, message in enumerate(messages):
        previous = messages[:i]  # Messages before this one

        entities = []
        edges = []

        if prompt_type in ['nodes', 'both']:
            print(f"{Colors.DIM}Extracting entities...{Colors.END}")
            entities = extract_nodes(client, message, previous)

        if prompt_type in ['edges', 'both'] and entities:
            print(f"{Colors.DIM}Extracting relationships...{Colors.END}")
            edges = extract_edges(client, message, entities, previous)

        print_extraction_results(message, model_name, entities, edges)


def run_all_models_comparison(
    message_ids: list[int],
    prompt_type: Literal['nodes', 'edges', 'both'],
    db_path: str
):
    """Run comparison across all configured models."""

    models = [
        ('gpt-4o-mini', 'openai', None),
        ('haiku', 'anthropic', None),
    ]

    # Check for optional models
    if os.getenv('XAI_API_KEY'):
        models.append(('grok-3-mini', 'xai', None))

    if os.getenv('GRAPHITI_LLM_BASE_URL'):
        base_url = os.getenv('GRAPHITI_LLM_BASE_URL')
        model = os.getenv('GRAPHITI_LLM_MODEL', 'local-model')
        models.append((model, 'local', base_url))

    print(f"{Colors.BOLD}{Colors.HEADER}Running comparison across {len(models)} models{Colors.END}\n")

    for model_name, provider, base_url in models:
        try:
            run_extraction_test(model_name, provider, base_url, message_ids, prompt_type, db_path)
        except Exception as e:
            print(f"{Colors.RED}Error testing {model_name}: {e}{Colors.END}\n")
            continue


def main():
    parser = argparse.ArgumentParser(
        description="Compare LLM extraction quality for Graphiti knowledge graph ingestion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with default model and messages
  %(prog)s

  # Test specific model
  %(prog)s --model haiku

  # Test with custom messages
  %(prog)s --message-ids 13311,13312,13313

  # Test only node extraction
  %(prog)s --prompt-type nodes

  # Search for test messages
  %(prog)s --list-messages "kitchen counter"

  # Compare all configured models
  %(prog)s --all-models

  # Use local LLM
  %(prog)s --provider local --base-url http://192.168.0.120:1234/v1 --model llama-3
        """
    )

    parser.add_argument(
        '--model', '-m',
        default='gpt-4o-mini',
        help='Model to test (default: gpt-4o-mini). Examples: gpt-4o-mini, haiku, grok-3-mini'
    )

    parser.add_argument(
        '--provider', '-p',
        choices=['openai', 'anthropic', 'xai', 'local'],
        help='API provider (default: auto-detect from model name)'
    )

    parser.add_argument(
        '--base-url',
        help='Custom API endpoint (for local/custom providers)'
    )

    parser.add_argument(
        '--message-ids',
        default='13311,13312,13313',
        help='Comma-separated message IDs to test (default: 13311,13312,13313)'
    )

    parser.add_argument(
        '--prompt-type',
        choices=['nodes', 'edges', 'both'],
        default='both',
        help='Which extraction to test (default: both)'
    )

    parser.add_argument(
        '--list-messages',
        metavar='KEYWORD',
        help='Search for messages by keyword to find test candidates'
    )

    parser.add_argument(
        '--all-models',
        action='store_true',
        help='Run all configured models and show side-by-side comparison'
    )

    args = parser.parse_args()

    db_path = '/home/jeff/.claude/data/lyra_conversations.db'

    # List messages mode
    if args.list_messages:
        results = search_messages(db_path, args.list_messages, limit=20)
        print(f"{Colors.BOLD}Messages matching '{args.list_messages}':{Colors.END}\n")
        for msg_id, channel, content in results:
            preview = content[:100].replace('\n', ' ')
            print(f"{Colors.CYAN}{msg_id:6d}{Colors.END} [{Colors.DIM}{channel}{Colors.END}] {preview}...")
        return

    # Parse message IDs
    message_ids = [int(x.strip()) for x in args.message_ids.split(',')]

    # Run comparison or single model
    if args.all_models:
        run_all_models_comparison(message_ids, args.prompt_type, db_path)
    else:
        run_extraction_test(
            args.model,
            args.provider,
            args.base_url,
            message_ids,
            args.prompt_type,
            db_path
        )


if __name__ == '__main__':
    main()
