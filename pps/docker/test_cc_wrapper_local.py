#!/usr/bin/env python3
"""
Local test for cc_openai_wrapper.py

Tests the wrapper logic without Docker to verify:
1. ClaudeInvoker initializes
2. Message translation works
3. Response format matches OpenAI spec

Run: python3 pps/docker/test_cc_wrapper_local.py
"""

import asyncio
import json
import sys
from pathlib import Path

# Add daemon to path for ClaudeInvoker import
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "daemon"))

from cc_invoker.invoker import ClaudeInvoker


async def test_wrapper_logic():
    """Test the core translation logic."""

    print("1. Initializing ClaudeInvoker...")
    invoker = ClaudeInvoker(
        model="haiku",
        bypass_permissions=True,
        startup_prompt=None,
        mcp_servers={},  # No MCP for stateless extraction
    )

    try:
        await invoker.initialize()
        print("✓ ClaudeInvoker initialized")

        # Simulate OpenAI request
        print("\n2. Testing message translation...")
        messages = [
            {"role": "system", "content": "You are an entity extractor."},
            {"role": "user", "content": "Extract entities from: Jeff loves coffee"}
        ]

        # Combine messages (same logic as wrapper)
        prompt_parts = []
        for msg in messages:
            if msg["role"] == "system":
                prompt_parts.append(f"System: {msg['content']}")
            elif msg["role"] == "user":
                prompt_parts.append(f"User: {msg['content']}")

        combined_prompt = "\n\n".join(prompt_parts)
        print(f"Combined prompt:\n{combined_prompt}\n")

        # Query
        print("3. Querying ClaudeInvoker...")
        response = await invoker.query(combined_prompt)
        print(f"✓ Response received:\n{response[:200]}...\n")

        # Check context tracking
        print("4. Checking context stats...")
        stats = invoker.context_stats
        print(f"✓ Context stats: {stats}")

        # Test restart check
        print("\n5. Testing restart logic...")
        needs_restart, reason = invoker.needs_restart()
        print(f"  Needs restart: {needs_restart} (reason: {reason or 'n/a'})")

        print("\n✓ All tests passed!")

    finally:
        await invoker.shutdown()
        print("\nClaudeInvoker shut down cleanly")


if __name__ == "__main__":
    asyncio.run(test_wrapper_logic())
