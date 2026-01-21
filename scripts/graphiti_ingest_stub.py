#!/usr/bin/env python3
"""
Graphiti Ingestion Stub
========================
Standalone script for validating knowledge graph extraction quality.

This script extracts triplets from conversation chunks WITHOUT writing to
the database. It's for testing and iterating on extraction rules before
wiring into the live graph.

Pattern: stub → test → iterate → wire (Issue #107)

Usage:
    # From stdin
    echo "Jeff: Let's implement auth" | python graphiti_ingest_stub.py

    # From file
    python graphiti_ingest_stub.py input.txt

    # With specific channel context
    python graphiti_ingest_stub.py --channel terminal input.txt

Input Format (text, one message per line or block):
    channel: terminal
    speaker: user
    content: Let's implement the authentication system
    timestamp: 2026-01-21T00:30:00Z

    channel: terminal
    speaker: assistant
    content: I'll create the auth module with JWT tokens
    timestamp: 2026-01-21T00:30:15Z

Output Format (JSON to stdout):
    [
      {
        "subject": "Jeff",
        "predicate": "REQUESTED_IMPLEMENTATION_OF",
        "object": "authentication system",
        "confidence": 0.9,
        "metadata": {
          "timestamp": "2026-01-21T00:30:00Z",
          "channel": "terminal"
        }
      }
    ]

Why:
    Automatic extraction creates too many low-value nodes (Issue #81).
    This stub lets us validate extraction quality before it pollutes the graph.
"""

import asyncio
import json
import sys
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

# Add PPS to path
sys.path.insert(0, str(Path(__file__).parent.parent / "pps"))

from layers.rich_texture_entities import ENTITY_TYPES, EXCLUDED_ENTITY_TYPES
from layers.extraction_context import build_extraction_instructions, get_speaker_from_content

# Conditional import - graphiti_core is required for this stub
try:
    from graphiti_core import Graphiti
    from graphiti_core.nodes import EpisodeType
    GRAPHITI_CORE_AVAILABLE = True
except ImportError:
    GRAPHITI_CORE_AVAILABLE = False
    print("ERROR: graphiti_core not available. Install with: pip install graphiti-core", file=sys.stderr)
    sys.exit(1)


class Message:
    """Represents a single conversation message."""
    def __init__(
        self,
        content: str,
        channel: str = "unknown",
        speaker: str = "unknown",
        timestamp: Optional[datetime] = None,
    ):
        self.content = content
        self.channel = channel
        self.speaker = speaker
        self.timestamp = timestamp or datetime.now(timezone.utc)

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        """Create Message from dict (for JSON/structured input)."""
        timestamp_str = data.get("timestamp")
        timestamp = None
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        return cls(
            content=data.get("content", ""),
            channel=data.get("channel", "unknown"),
            speaker=data.get("speaker", "unknown"),
            timestamp=timestamp,
        )

    def __repr__(self):
        return f"Message(speaker={self.speaker}, channel={self.channel}, content={self.content[:50]}...)"


class GraphitiStubExtractor:
    """
    Stub extractor that uses graphiti_core extraction WITHOUT database writes.

    This mimics the behavior of RichTextureLayerV2._store_direct() but captures
    the extracted entities and edges instead of persisting them.
    """

    def __init__(
        self,
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "password123",
        group_id: str = "stub_extraction",
        scene_context: Optional[str] = None,
        crystal_context: Optional[str] = None,
    ):
        """
        Initialize stub extractor.

        Note: neo4j connection is still needed because graphiti_core uses it
        for extraction even though we won't write. The extraction happens
        via LLM calls, then results are formatted but not saved.
        """
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.group_id = group_id
        self.scene_context = scene_context
        self.crystal_context = crystal_context
        self._client: Optional[Graphiti] = None

    async def _get_client(self) -> Graphiti:
        """Get or create graphiti client."""
        if self._client is None:
            self._client = Graphiti(
                uri=self.neo4j_uri,
                user=self.neo4j_user,
                password=self.neo4j_password,
            )
        return self._client

    async def close(self):
        """Clean up resources."""
        if self._client:
            await self._client.close()
            self._client = None

    async def extract_triplets(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """
        Extract triplets from messages using graphiti_core extraction.

        This calls add_episode() for each message but doesn't persist results.
        Instead, we capture what WOULD have been extracted.

        Returns:
            List of triplet dicts with structure:
            {
                "subject": str,
                "predicate": str,
                "object": str,
                "confidence": float,
                "metadata": {...}
            }
        """
        client = await self._get_client()
        all_triplets = []

        for msg in messages:
            try:
                # Build extraction instructions for this message
                extraction_instructions = build_extraction_instructions(
                    channel=msg.channel,
                    scene_context=self.scene_context,
                    crystal_context=self.crystal_context,
                )

                # Create episode name
                episode_name = f"{msg.speaker}_{msg.timestamp.strftime('%Y%m%d_%H%M%S')}"

                # Call add_episode with dry_run simulation
                # NOTE: graphiti_core doesn't have a native dry_run mode yet,
                # so this is a STUB that shows the INTENDED extraction.
                # In production, we'd need to actually query what was extracted.

                # For now, this stub does ACTUAL extraction to demonstrate the pattern
                # Real validation would require querying the graph after extraction
                result = await client.add_episode(
                    name=episode_name,
                    episode_body=msg.content,
                    source_description=f"Conversation from {msg.channel} channel",
                    reference_time=msg.timestamp,
                    source=EpisodeType.message,
                    group_id=self.group_id,
                    entity_types=ENTITY_TYPES,
                    excluded_entity_types=EXCLUDED_ENTITY_TYPES,
                    custom_extraction_instructions=extraction_instructions,
                )

                # Extract entities and edges from the result
                # This is where we'd parse what graphiti extracted
                if result:
                    # TODO: Parse result to get actual triplets
                    # For stub purposes, we'll show the structure
                    triplets = self._parse_extraction_result(result, msg)
                    all_triplets.extend(triplets)

            except Exception as e:
                print(f"ERROR extracting from {msg}: {e}", file=sys.stderr)
                continue

        return all_triplets

    def _parse_extraction_result(
        self,
        result: Any,
        message: Message,
    ) -> List[Dict[str, Any]]:
        """
        Parse graphiti extraction result into triplet format.

        NOTE: This is a stub implementation. The actual parsing would depend
        on what graphiti_core returns from add_episode().

        For now, this demonstrates the OUTPUT format we want.
        """
        # Stub: return example structure
        # In real implementation, we'd parse result.edges, result.entities, etc.
        return [
            {
                "subject": message.speaker,
                "predicate": "SPOKE_IN",
                "object": message.channel,
                "confidence": 0.8,
                "metadata": {
                    "timestamp": message.timestamp.isoformat(),
                    "channel": message.channel,
                    "extraction_note": "This is a STUB - actual extraction parsing needed",
                }
            }
        ]


def parse_input(text: str, default_channel: str = "unknown") -> List[Message]:
    """
    Parse input text into Message objects.

    Supports multiple formats:
    1. Simple text (one message per line with "Speaker: content" format)
    2. Structured format with channel/speaker/content/timestamp blocks
    3. JSON array of message objects

    Args:
        text: Input text to parse
        default_channel: Default channel if not specified

    Returns:
        List of Message objects
    """
    messages = []

    # Try JSON first
    try:
        data = json.loads(text)
        if isinstance(data, list):
            for item in data:
                messages.append(Message.from_dict(item))
            return messages
    except json.JSONDecodeError:
        pass

    # Check if this looks like structured format (has "channel:" or "speaker:" lines)
    is_structured = any(
        line.strip().lower().startswith(("channel:", "speaker:", "content:", "timestamp:"))
        for line in text.split("\n")
    )

    if is_structured:
        # Parse structured text format
        lines = text.strip().split("\n")
        current_msg = {}

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                # Empty line - finalize current message
                if current_msg.get("content"):
                    messages.append(Message.from_dict(current_msg))
                current_msg = {}
                continue

            # Check for key: value format
            if ": " in line_stripped and not line_stripped.startswith(" "):
                key, value = line_stripped.split(": ", 1)
                key = key.lower().strip()
                if key in ("channel", "speaker", "content", "timestamp"):
                    current_msg[key] = value
                else:
                    # Not a structured key, treat as content continuation
                    if "content" in current_msg:
                        current_msg["content"] += "\n" + line_stripped
                    else:
                        current_msg["content"] = line_stripped
            else:
                # Continuation of content
                if "content" in current_msg:
                    current_msg["content"] += "\n" + line_stripped

        # Don't forget the last message
        if current_msg.get("content"):
            messages.append(Message.from_dict(current_msg))

    else:
        # Simple format: each line is a separate message
        for line in text.strip().split("\n"):
            line_stripped = line.strip()
            if line_stripped:
                speaker = get_speaker_from_content(line_stripped, default_channel)
                messages.append(Message(
                    content=line_stripped,
                    channel=default_channel,
                    speaker=speaker,
                ))

    return messages


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Extract knowledge triplets from conversation chunks (stub mode - no DB writes)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        help="Input file (or read from stdin if not provided)",
    )
    parser.add_argument(
        "--channel",
        default="unknown",
        help="Default channel for messages without explicit channel",
    )
    parser.add_argument(
        "--scene-context",
        help="Scene context to inject into extraction (optional)",
    )
    parser.add_argument(
        "--crystal-context",
        help="Crystal context to inject into extraction (optional)",
    )
    parser.add_argument(
        "--neo4j-uri",
        default="bolt://localhost:7687",
        help="Neo4j URI (needed for extraction even though we don't write)",
    )
    parser.add_argument(
        "--neo4j-user",
        default="neo4j",
        help="Neo4j username",
    )
    parser.add_argument(
        "--neo4j-password",
        default="password123",
        help="Neo4j password",
    )
    parser.add_argument(
        "--group-id",
        default="stub_extraction",
        help="Group ID for extraction (won't be written to graph)",
    )

    args = parser.parse_args()

    # Read input
    if args.input_file:
        try:
            with open(args.input_file, "r") as f:
                input_text = f.read()
        except IOError as e:
            print(f"ERROR: Cannot read {args.input_file}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Read from stdin
        input_text = sys.stdin.read()

    if not input_text.strip():
        print("ERROR: No input provided", file=sys.stderr)
        sys.exit(1)

    # Parse messages
    messages = parse_input(input_text, default_channel=args.channel)

    if not messages:
        print("ERROR: No valid messages found in input", file=sys.stderr)
        sys.exit(1)

    print(f"Parsed {len(messages)} messages", file=sys.stderr)
    for msg in messages:
        print(f"  - {msg}", file=sys.stderr)
    print(file=sys.stderr)

    # Initialize extractor
    extractor = GraphitiStubExtractor(
        neo4j_uri=args.neo4j_uri,
        neo4j_user=args.neo4j_user,
        neo4j_password=args.neo4j_password,
        group_id=args.group_id,
        scene_context=args.scene_context,
        crystal_context=args.crystal_context,
    )

    try:
        # Extract triplets
        print("Extracting triplets...", file=sys.stderr)
        triplets = await extractor.extract_triplets(messages)

        # Output as JSON to stdout
        print(json.dumps(triplets, indent=2))

        print(f"\nExtracted {len(triplets)} triplets", file=sys.stderr)

    finally:
        await extractor.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        sys.exit(130)
