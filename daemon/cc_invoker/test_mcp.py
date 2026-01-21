#!/usr/bin/env python3
"""
Test MCP tool availability via ClaudeInvoker.
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)

from invoker import ClaudeInvoker


async def main():
    print("=" * 60)
    print("MCP Tool Test")
    print("=" * 60)

    invoker = ClaudeInvoker()

    print("\n[1] Initializing...")
    await invoker.initialize(timeout=60)
    print(f"    Connected: {invoker.is_connected}")

    print("\n[2] Testing MCP tool (pps_health)...")
    print("    Asking Claude to call mcp__pps__pps_health tool...")

    response = await invoker.query(
        "Call the mcp__pps__pps_health tool and tell me what layers are available. "
        "Just list the layer names and their status, nothing else."
    )
    print(f"    Response:\n{response}")

    print("\n[3] Shutting down...")
    await invoker.shutdown()

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
