"""
Claude Code Invoker - Persistent CC connection for low-latency daemon use.

Uses the Claude Agent SDK to maintain a persistent connection to Claude Code,
avoiding the ~20s startup cost on each invocation.

Usage:
    invoker = ClaudeInvoker()
    await invoker.initialize()  # One-time ~12s cost

    response = await invoker.query("Hello")  # ~0.6s
    response = await invoker.query("Follow-up")  # ~0.6s

    await invoker.shutdown()  # Clean disconnect

See: docs/reference/Keeping Claude Code CLI Persistent for Low-Latency Interactive Use.md
Related: Issue #103 (MCP stdio servers in subprocess contexts)
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import AsyncIterator, Optional

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

logger = logging.getLogger(__name__)

# Project root for locating PPS server
PROJECT_ROOT = Path(__file__).parent.parent.parent


def get_default_mcp_servers(entity_path: Optional[Path] = None) -> dict:
    """
    Get default MCP server configuration for PPS.

    Uses stdio transport - the SDK spawns PPS as a child process.
    This is portable: anyone who clones the repo gets working MCP tools.

    Args:
        entity_path: Path to entity folder (e.g., entities/lyra).
                     Defaults to entities/lyra in project root.
    """
    entity_path = entity_path or PROJECT_ROOT / "entities" / "lyra"
    claude_home = Path.home() / ".claude"

    return {
        "pps": {
            # stdio is default - no type field needed
            "command": sys.executable,  # Use same Python as invoker
            "args": [str(PROJECT_ROOT / "pps" / "server.py")],
            "env": {
                "ENTITY_PATH": str(entity_path),
                "CLAUDE_HOME": str(claude_home),
                "CHROMA_HOST": os.getenv("CHROMA_HOST", "localhost"),
                "CHROMA_PORT": os.getenv("CHROMA_PORT", "8200"),
            }
        }
    }


class ClaudeInvoker:
    """
    Persistent Claude Code connection for daemon use.

    Wraps ClaudeSDKClient to provide:
    - One-time initialization with MCP server readiness check
    - Fast query interface for subsequent prompts
    - Clean shutdown
    """

    def __init__(
        self,
        working_dir: Optional[Path] = None,
        bypass_permissions: bool = True,
        model: Optional[str] = None,
        mcp_servers: Optional[dict] = None,
    ):
        """
        Initialize invoker configuration.

        Args:
            working_dir: Working directory for Claude Code (defaults to Awareness project root)
            bypass_permissions: If True, skip permission prompts (headless mode)
            model: Model to use (e.g., 'claude-sonnet-4-5', 'opus')
            mcp_servers: MCP server configuration dict. Defaults to PPS via stdio.
                         Set to {} to disable MCP servers.
        """
        self.working_dir = working_dir or PROJECT_ROOT
        self.bypass_permissions = bypass_permissions
        self.model = model
        self.mcp_servers = mcp_servers if mcp_servers is not None else get_default_mcp_servers()

        self._client: Optional[ClaudeSDKClient] = None
        self._connected = False
        self._mcp_ready = False

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected

    @property
    def is_mcp_ready(self) -> bool:
        """Check if MCP servers are ready."""
        return self._mcp_ready

    async def initialize(self, timeout: float = 60.0) -> dict:
        """
        Initialize the persistent connection.

        This is the one-time startup cost (~12s). After this completes,
        subsequent queries are fast (~0.6s).

        Args:
            timeout: Maximum time to wait for initialization

        Returns:
            Server info dict including MCP server status

        Raises:
            TimeoutError: If initialization takes too long
            RuntimeError: If connection fails
        """
        logger.info("Initializing Claude Code connection...")

        # Configure options with inline MCP servers for portability
        # allowed_tools grants permission for MCP tools (required!)
        options = ClaudeAgentOptions(
            cwd=str(self.working_dir),
            mcp_servers=self.mcp_servers,
            allowed_tools=["mcp__pps__*"],  # Allow all PPS tools
            permission_mode="bypassPermissions" if self.bypass_permissions else None,
        )

        # Create and connect client
        self._client = ClaudeSDKClient(options)

        try:
            async with asyncio.timeout(timeout):
                await self._client.connect()
                self._connected = True

                # Set model if specified (permission_mode already set in options)
                if self.model:
                    await self._client.set_model(self.model)

                # Get server info (note: MCP status comes from init message, not here)
                server_info = await self._client.get_server_info()

                # server_info contains commands, models, account info
                # MCP server status will be visible in query response init message
                # We assume MCP is ready if we configured servers
                self._mcp_ready = bool(self.mcp_servers)

                logger.info("Claude Code connection initialized successfully")
                logger.info(f"MCP servers configured: {list(self.mcp_servers.keys()) if self.mcp_servers else 'none'}")
                return server_info or {}

        except asyncio.TimeoutError:
            logger.error(f"Initialization timed out after {timeout}s")
            await self.shutdown()
            raise TimeoutError(f"Claude Code initialization timed out after {timeout}s")
        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            await self.shutdown()
            raise RuntimeError(f"Failed to initialize Claude Code: {e}")

    async def query(self, prompt: str) -> str:
        """
        Send a query and get the response.

        Args:
            prompt: The prompt to send

        Returns:
            The assistant's text response

        Raises:
            RuntimeError: If not connected
        """
        if not self._connected or not self._client:
            raise RuntimeError("Not connected. Call initialize() first.")

        logger.debug(f"Sending query: {prompt[:100]}...")

        await self._client.query(prompt)

        # Collect response
        response_parts = []
        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        response_parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                # Final message - conversation turn complete
                break

        response = "".join(response_parts)
        logger.debug(f"Received response: {response[:100]}...")
        return response

    async def query_stream(self, prompt: str) -> AsyncIterator[str]:
        """
        Send a query and stream the response.

        Args:
            prompt: The prompt to send

        Yields:
            Text chunks as they arrive
        """
        if not self._connected or not self._client:
            raise RuntimeError("Not connected. Call initialize() first.")

        await self._client.query(prompt)

        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        yield block.text
            elif isinstance(msg, ResultMessage):
                break

    async def shutdown(self) -> None:
        """
        Cleanly disconnect from Claude Code.

        This is the equivalent of /quit - allows hooks and cleanup to run.
        """
        logger.info("Shutting down Claude Code connection...")

        if self._client:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._client = None
                self._connected = False
                self._mcp_ready = False

        logger.info("Claude Code connection shut down")

    async def __aenter__(self) -> "ClaudeInvoker":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.shutdown()


# Convenience function for simple usage
async def quick_query(prompt: str, **kwargs) -> str:
    """
    One-shot query with automatic setup/teardown.

    Note: This incurs the full startup cost. For multiple queries,
    use ClaudeInvoker directly.
    """
    async with ClaudeInvoker(**kwargs) as invoker:
        return await invoker.query(prompt)
