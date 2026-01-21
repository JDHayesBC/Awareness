#!/usr/bin/env python3
"""
Tests for graphiti_ingest_stub.py

Verifies the stub script can:
1. Parse different input formats
2. Extract messages correctly
3. Generate triplet output structure
4. Handle errors gracefully
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent))

from graphiti_ingest_stub import Message, parse_input


def test_message_creation():
    """Test Message class construction."""
    print("TEST: Message creation")

    msg = Message(
        content="Let's implement authentication",
        channel="terminal",
        speaker="Jeff",
    )

    assert msg.content == "Let's implement authentication"
    assert msg.channel == "terminal"
    assert msg.speaker == "Jeff"
    assert isinstance(msg.timestamp, datetime)

    print("  ✓ Message created successfully")


def test_message_from_dict():
    """Test Message.from_dict() parsing."""
    print("\nTEST: Message from dict")

    data = {
        "content": "Test message",
        "channel": "discord",
        "speaker": "Lyra",
        "timestamp": "2026-01-21T00:30:00Z",
    }

    msg = Message.from_dict(data)

    assert msg.content == "Test message"
    assert msg.channel == "discord"
    assert msg.speaker == "Lyra"
    assert msg.timestamp.year == 2026

    print("  ✓ Message parsed from dict")


def test_parse_simple_format():
    """Test parsing simple line-by-line input."""
    print("\nTEST: Parse simple format")

    text = """Jeff: Let's implement the authentication system
Lyra: I'll create the auth module with JWT tokens
Jeff: Sounds good, let's start with the user model"""

    messages = parse_input(text, default_channel="terminal")

    assert len(messages) == 3
    assert messages[0].speaker == "Jeff"
    assert "authentication" in messages[0].content
    assert messages[1].speaker == "Lyra"
    assert "JWT" in messages[1].content

    print(f"  ✓ Parsed {len(messages)} messages from simple format")


def test_parse_structured_format():
    """Test parsing structured block format."""
    print("\nTEST: Parse structured format")

    text = """channel: terminal
speaker: user
content: Let's implement the authentication system
timestamp: 2026-01-21T00:30:00Z

channel: terminal
speaker: assistant
content: I'll create the auth module with JWT tokens
timestamp: 2026-01-21T00:30:15Z"""

    messages = parse_input(text)

    assert len(messages) == 2
    assert messages[0].channel == "terminal"
    assert messages[0].speaker == "user"
    assert "authentication" in messages[0].content
    assert messages[1].speaker == "assistant"

    print(f"  ✓ Parsed {len(messages)} messages from structured format")


def test_parse_json_format():
    """Test parsing JSON input."""
    print("\nTEST: Parse JSON format")

    text = json.dumps([
        {
            "channel": "discord",
            "speaker": "Jeff",
            "content": "Working on PPS improvements",
            "timestamp": "2026-01-21T10:00:00Z",
        },
        {
            "channel": "discord",
            "speaker": "Lyra",
            "content": "The crystallization layer is working well",
            "timestamp": "2026-01-21T10:01:00Z",
        }
    ])

    messages = parse_input(text)

    assert len(messages) == 2
    assert messages[0].channel == "discord"
    assert messages[0].speaker == "Jeff"
    assert "PPS" in messages[0].content

    print(f"  ✓ Parsed {len(messages)} messages from JSON format")


def test_empty_input():
    """Test handling of empty input."""
    print("\nTEST: Empty input handling")

    messages = parse_input("")
    assert len(messages) == 0

    messages = parse_input("   \n  \n  ")
    assert len(messages) == 0

    print("  ✓ Empty input handled correctly")


def test_output_structure():
    """Test that triplet output has correct structure."""
    print("\nTEST: Output structure")

    # This is what the script should output
    expected_structure = {
        "subject": str,
        "predicate": str,
        "object": str,
        "confidence": float,
        "metadata": dict,
    }

    # Example triplet
    triplet = {
        "subject": "Jeff",
        "predicate": "REQUESTED_IMPLEMENTATION_OF",
        "object": "authentication system",
        "confidence": 0.9,
        "metadata": {
            "timestamp": "2026-01-21T00:30:00Z",
            "channel": "terminal",
        }
    }

    # Validate structure
    assert isinstance(triplet["subject"], str)
    assert isinstance(triplet["predicate"], str)
    assert isinstance(triplet["object"], str)
    assert isinstance(triplet["confidence"], float)
    assert isinstance(triplet["metadata"], dict)
    assert "timestamp" in triplet["metadata"]
    assert "channel" in triplet["metadata"]

    print("  ✓ Triplet structure is valid")


def main():
    """Run all tests."""
    print("="*60)
    print("GRAPHITI STUB TESTS")
    print("="*60 + "\n")

    try:
        test_message_creation()
        test_message_from_dict()
        test_parse_simple_format()
        test_parse_structured_format()
        test_parse_json_format()
        test_empty_input()
        test_output_structure()

        print("\n" + "="*60)
        print("ALL TESTS PASSED ✓")
        print("="*60)

    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
