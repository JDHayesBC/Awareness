#!/usr/bin/env python3
"""
Test script for ClaudeInvoker.

Run from project root with venv activated:
    source .venv/bin/activate
    python daemon/cc_invoker/test_invoker.py
"""

import asyncio
import time
import logging

logging.basicConfig(level=logging.INFO)

from invoker import ClaudeInvoker


async def main():
    print("=" * 60)
    print("ClaudeInvoker Test")
    print("=" * 60)

    invoker = ClaudeInvoker()

    # Test initialization
    print("\n[1] Initializing (expect ~12s startup cost)...")
    start = time.time()
    try:
        server_info = await invoker.initialize(timeout=60)
        init_time = time.time() - start
        print(f"    Initialized in {init_time:.2f}s")
        print(f"    Connected: {invoker.is_connected}")
        print(f"    MCP Ready: {invoker.is_mcp_ready}")

        if server_info:
            mcp_servers = server_info.get("mcp_servers", [])
            print(f"    MCP Servers: {len(mcp_servers)}")
            for s in mcp_servers[:5]:  # Show first 5
                print(f"      - {s.get('name')}: {s.get('status')}")

    except Exception as e:
        print(f"    FAILED: {e}")
        return

    # Test first query
    print("\n[2] First query (should be fast now)...")
    start = time.time()
    try:
        response = await invoker.query("Say 'Hello from cc_invoker test!' and nothing else.")
        query_time = time.time() - start
        print(f"    Response in {query_time:.2f}s")
        print(f"    Response: {response[:200]}")
    except Exception as e:
        print(f"    FAILED: {e}")

    # Test second query
    print("\n[3] Second query (should also be fast)...")
    start = time.time()
    try:
        response = await invoker.query("What is 2 + 2? Just the number.")
        query_time = time.time() - start
        print(f"    Response in {query_time:.2f}s")
        print(f"    Response: {response[:200]}")
    except Exception as e:
        print(f"    FAILED: {e}")

    # Test shutdown
    print("\n[4] Shutting down...")
    start = time.time()
    await invoker.shutdown()
    shutdown_time = time.time() - start
    print(f"    Shutdown in {shutdown_time:.2f}s")
    print(f"    Connected: {invoker.is_connected}")

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
