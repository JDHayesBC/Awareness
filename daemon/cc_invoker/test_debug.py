#!/usr/bin/env python3
"""
Debug MCP server connection.
"""

import asyncio
import logging
import json

logging.basicConfig(level=logging.DEBUG)

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk.types import SystemMessage
from invoker import get_default_mcp_servers, PROJECT_ROOT

async def main():
    print("=" * 60)
    print("MCP Debug Test")
    print("=" * 60)

    mcp_servers = get_default_mcp_servers()
    print(f"\nMCP config:\n{json.dumps(mcp_servers, indent=2)}")

    options = ClaudeAgentOptions(
        cwd=str(PROJECT_ROOT),
        mcp_servers=mcp_servers,
        allowed_tools=["mcp__pps__*"],
        permission_mode="bypassPermissions",
    )

    print("\nConnecting...")
    client = ClaudeSDKClient(options)

    await client.connect()

    print("\nGetting server info...")
    server_info = await client.get_server_info()
    print(f"Server info: {json.dumps(server_info, indent=2) if server_info else 'None'}")

    print("\nSending test query to trigger init message...")
    await client.query("What tools do you have access to? List any that start with 'mcp'")

    print("\nReceiving response...")
    async for msg in client.receive_response():
        msg_type = type(msg).__name__
        print(f"  Message type: {msg_type}")

        if hasattr(msg, 'subtype'):
            print(f"    subtype: {msg.subtype}")

        if hasattr(msg, 'data'):
            if 'mcp_servers' in msg.data:
                print(f"    MCP servers from init: {msg.data['mcp_servers']}")

        if hasattr(msg, 'content'):
            for block in msg.content:
                if hasattr(block, 'text'):
                    print(f"    Text: {block.text[:200]}...")
                    break

        if msg_type == "ResultMessage":
            break

    print("\nShutting down...")
    await client.disconnect()

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
