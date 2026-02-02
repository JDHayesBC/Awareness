#!/usr/bin/env python3
"""
Test MCP tools to verify the stdio bug fixes.
Tests get_turns_since_summary and get_turns_since via direct function calls.
"""

import sys
import os
import asyncio
from pathlib import Path

# Add pps to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "pps"))

# Set required env vars
os.environ.setdefault("ENTITY_PATH", str(Path.home() / ".claude"))
os.environ.setdefault("CLAUDE_HOME", str(Path.home() / ".claude"))

async def test_tools():
    """Test the fixed MCP tools."""
    print("Importing server module...")
    try:
        from server import call_tool_impl
        print("✓ Import successful")
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False

    print("\nTest 1: get_turns_since_summary")
    print("-" * 40)
    try:
        result = await call_tool_impl("get_turns_since_summary", {
            "limit": 5,
            "offset": 0,
            "min_turns": 3
        })
        print(f"✓ Tool executed without errors")
        print(f"  Result type: {type(result)}")
        print(f"  Result length: {len(result)}")
        if result and hasattr(result[0], 'text'):
            preview = result[0].text[:200] if len(result[0].text) > 200 else result[0].text
            print(f"  Preview: {preview}...")
    except Exception as e:
        print(f"✗ Tool failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\nTest 2: get_turns_since")
    print("-" * 40)
    try:
        # Use a timestamp from 2 days ago
        from datetime import datetime, timedelta
        timestamp = (datetime.now() - timedelta(days=2)).isoformat()

        result = await call_tool_impl("get_turns_since", {
            "timestamp": timestamp,
            "limit": 5,
            "include_summaries": True
        })
        print(f"✓ Tool executed without errors")
        print(f"  Result type: {type(result)}")
        print(f"  Result length: {len(result)}")
        if result and hasattr(result[0], 'text'):
            preview = result[0].text[:200] if len(result[0].text) > 200 else result[0].text
            print(f"  Preview: {preview}...")
    except Exception as e:
        print(f"✗ Tool failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "=" * 40)
    print("✓ All tests passed!")
    return True

if __name__ == "__main__":
    success = asyncio.run(test_tools())
    sys.exit(0 if success else 1)
