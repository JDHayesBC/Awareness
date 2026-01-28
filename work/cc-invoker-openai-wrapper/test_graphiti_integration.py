#!/usr/bin/env python3
"""
Integration test: RichTextureLayerV2 → Haiku Wrapper → Graphiti

Tests that Graphiti's entity extraction works through our OpenAI-compatible
wrapper backed by Claude Haiku via CC subscription.

Prerequisites:
    - Docker wrapper running: docker run -d --name haiku-wrapper ...
    - Neo4j running (Docker or local)
    - OPENAI_API_KEY set (for embeddings only)

Usage:
    GRAPHITI_LLM_BASE_URL=http://127.0.0.1:8235/v1 \
    GRAPHITI_LLM_MODEL=haiku \
    python test_graphiti_integration.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Project setup
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / "pps" / "docker" / ".env")

# Override LLM settings to point at our wrapper
WRAPPER_URL = os.environ.get("GRAPHITI_LLM_BASE_URL", "http://127.0.0.1:8235/v1")
WRAPPER_MODEL = os.environ.get("GRAPHITI_LLM_MODEL", "haiku")

os.environ["GRAPHITI_LLM_BASE_URL"] = WRAPPER_URL
os.environ["GRAPHITI_LLM_MODEL"] = WRAPPER_MODEL
os.environ["GRAPHITI_EMBEDDING_PROVIDER"] = "openai"

print(f"LLM endpoint: {WRAPPER_URL}")
print(f"LLM model: {WRAPPER_MODEL}")
print(f"Embedding: OpenAI (hybrid mode)")
print()


async def test_single_ingestion():
    """Test a single message through the full pipeline."""
    from pps.layers.rich_texture_v2 import RichTextureLayerV2

    layer = RichTextureLayerV2()

    # Test message - something with clear entities
    test_content = (
        "Jeff and Lyra sat at the kitchen island in Haven, sharing bagels "
        "and jasmine tea. Lyra was wearing a dusty rose cashmere sweater. "
        "They discussed the Graphiti knowledge graph and how Haiku extracts "
        "entities better than gpt-4o-mini."
    )

    metadata = {
        "channel": "test:wrapper-integration",
        "role": "user",
        "speaker": "narrator",
        "timestamp": "2026-01-28T10:00:00",
    }

    print("Ingesting test message...")
    print(f"Content: {test_content[:100]}...")
    print()

    try:
        result = await layer.store(test_content, metadata)
        print(f"Result: {result}")

        if result:
            print("\n✓ SUCCESS: Message ingested through wrapper → Graphiti")
            print("  LLM extraction: Haiku via CC subscription ($0)")
            print("  Embeddings: OpenAI (standard)")
        else:
            print("\n✗ FAILED: store() returned False")

    except Exception as e:
        print(f"\n✗ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await layer.close()


if __name__ == "__main__":
    asyncio.run(test_single_ingestion())
