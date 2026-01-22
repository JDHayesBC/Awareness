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
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk import (
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    ClaudeSDKError,
    ProcessError,
)
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

logger = logging.getLogger(__name__)


# Custom exceptions for invoker
class InvokerConnectionError(Exception):
    """Connection to Claude Code failed."""
    def __init__(self, message: str, attempts: int = 0, last_error: Optional[Exception] = None):
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error


class InvokerQueryError(Exception):
    """Query execution failed."""
    def __init__(self, message: str, retried: bool = False, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.retried = retried
        self.original_error = original_error

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
        max_context_tokens: int = 150_000,
        max_turns: int = 100,
        max_idle_seconds: int = 4 * 3600,
        max_reconnect_attempts: int = 5,
        max_backoff_seconds: float = 30.0,
        startup_prompt: Optional[str] = None,
    ):
        """
        Initialize invoker configuration.

        Args:
            working_dir: Working directory for Claude Code (defaults to Awareness project root)
            bypass_permissions: If True, skip permission prompts (headless mode)
            model: Model to use (e.g., 'claude-sonnet-4-5', 'opus')
            mcp_servers: MCP server configuration dict. Defaults to PPS via stdio.
                         Set to {} to disable MCP servers.
            max_context_tokens: Maximum context tokens before restart (default 150k)
            max_turns: Maximum query turns before restart (default 100)
            max_idle_seconds: Maximum idle time before restart (default 4 hours)
            max_reconnect_attempts: Maximum reconnection attempts (default 5)
            max_backoff_seconds: Maximum backoff time between reconnects (default 30s)
            startup_prompt: Optional prompt to send after initialization for identity
                            reconstruction. Sent automatically after init() and restart().
        """
        self.working_dir = working_dir or PROJECT_ROOT
        self.bypass_permissions = bypass_permissions
        self.model = model
        self.mcp_servers = mcp_servers if mcp_servers is not None else get_default_mcp_servers()

        # Session limits
        self.max_context_tokens = max_context_tokens
        self.max_turns = max_turns
        self.max_idle_seconds = max_idle_seconds

        # Error recovery configuration
        self.max_reconnect_attempts = max_reconnect_attempts
        self.max_backoff_seconds = max_backoff_seconds

        # Startup protocol
        self.startup_prompt = startup_prompt

        self._client: Optional[ClaudeSDKClient] = None
        self._connected = False
        self._mcp_ready = False

        # Context tracking
        self._prompt_tokens = 0      # Tokens sent (estimated)
        self._response_tokens = 0    # Tokens received (estimated)
        self._turn_count = 0         # Number of query/response cycles
        self._session_start_time: Optional[datetime] = None
        self._last_activity_time: Optional[datetime] = None

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected

    @property
    def is_mcp_ready(self) -> bool:
        """Check if MCP servers are ready."""
        return self._mcp_ready

    @property
    def context_size(self) -> int:
        """Total estimated tokens used in session."""
        return self._prompt_tokens + self._response_tokens

    @property
    def turn_count(self) -> int:
        """Number of query/response turns in session."""
        return self._turn_count

    @property
    def context_stats(self) -> dict:
        """Full context statistics."""
        return {
            "prompt_tokens": self._prompt_tokens,
            "response_tokens": self._response_tokens,
            "total_tokens": self.context_size,
            "turn_count": self._turn_count,
        }

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate: ~4 chars per token."""
        return len(text) // 4

    def set_startup_prompt(self, prompt: str) -> None:
        """
        Update the startup prompt for future initializations.

        This prompt will be sent automatically after initialize() and restart()
        to re-establish identity context.

        Args:
            prompt: The startup prompt to use (e.g., identity reconstruction command)
        """
        self.startup_prompt = prompt

    def simulate_context_usage(self, tokens: int) -> None:
        """
        Artificially inflate token counter for testing.

        Useful for testing restart behavior without sending actual queries.

        Args:
            tokens: Number of tokens to add to response counter
        """
        self._response_tokens += tokens
        logger.debug(f"Simulated {tokens} tokens of context usage (total: {self.context_size})")

    async def force_restart(self, reason: str = "forced for testing") -> dict:
        """
        Force a restart for testing purposes.

        This is just an alias for restart() with a default testing reason.

        Args:
            reason: Why we're restarting (default: "forced for testing")

        Returns:
            Server info from initialize()
        """
        return await self.restart(reason=reason)

    def _is_connection_healthy(self) -> bool:
        """
        Check if connection appears healthy.

        Returns:
            True if connected and client exists, False otherwise
        """
        return self._connected and self._client is not None

    async def _reconnect_with_backoff(self, timeout: float = 60.0) -> bool:
        """
        Attempt reconnection with exponential backoff.

        Tries to re-establish connection after a drop. Uses exponential backoff
        pattern: 1s, 2s, 4s, 8s, etc. up to max_backoff_seconds.

        Args:
            timeout: Maximum time to wait for each reconnection attempt

        Returns:
            True if reconnection succeeded, False otherwise

        Raises:
            InvokerConnectionError: If all reconnection attempts fail
        """
        logger.warning("Connection lost, attempting reconnection with backoff...")

        last_error = None
        for attempt in range(1, self.max_reconnect_attempts + 1):
            # Calculate backoff: 2^(attempt-1), capped at max_backoff_seconds
            backoff = min(2 ** (attempt - 1), self.max_backoff_seconds)

            logger.info(f"Reconnection attempt {attempt}/{self.max_reconnect_attempts} (backoff: {backoff}s)")

            try:
                # Wait before attempting (skip on first attempt)
                if attempt > 1:
                    await asyncio.sleep(backoff)

                # Clear existing state
                if self._client:
                    try:
                        await self._client.disconnect()
                    except Exception as e:
                        logger.debug(f"Error during disconnect before reconnect: {e}")
                    finally:
                        self._client = None
                        self._connected = False
                        self._mcp_ready = False

                # Attempt initialization
                await self.initialize(timeout=timeout)

                logger.info(f"Reconnection successful on attempt {attempt}")
                return True

            except Exception as e:
                last_error = e
                logger.warning(f"Reconnection attempt {attempt} failed: {e}")

        # All attempts exhausted
        error_msg = f"Failed to reconnect after {self.max_reconnect_attempts} attempts"
        logger.error(error_msg)
        raise InvokerConnectionError(
            error_msg,
            attempts=self.max_reconnect_attempts,
            last_error=last_error
        )

    async def initialize(self, timeout: float = 60.0, send_startup: bool = True) -> dict:
        """
        Initialize the persistent connection.

        This is the one-time startup cost (~12s). After this completes,
        subsequent queries are fast (~0.6s).

        Args:
            timeout: Maximum time to wait for initialization
            send_startup: If True and startup_prompt is configured, send it after
                          connection is established (default True)

        Returns:
            Server info dict including MCP server status

        Raises:
            TimeoutError: If initialization takes too long
            RuntimeError: If connection fails
        """
        logger.info("Initializing Claude Code connection...")

        # Reset context tracking for fresh session
        self._prompt_tokens = 0
        self._response_tokens = 0
        self._turn_count = 0
        self._session_start_time = datetime.now()
        self._last_activity_time = datetime.now()

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

                # Send startup prompt if configured (for identity reconstruction)
                # Don't count startup tokens toward context limit
                if send_startup and self.startup_prompt:
                    logger.info("Sending startup prompt for identity reconstruction")
                    await self.query(self.startup_prompt, count_tokens=False)

                return server_info or {}

        except asyncio.TimeoutError:
            logger.error(f"Initialization timed out after {timeout}s")
            await self.shutdown()
            raise TimeoutError(f"Claude Code initialization timed out after {timeout}s")
        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            await self.shutdown()
            raise RuntimeError(f"Failed to initialize Claude Code: {e}")

    async def query(
        self,
        prompt: str,
        retry_on_connection_error: bool = True,
        count_tokens: bool = True
    ) -> str:
        """
        Send a query and get the response.

        Handles connection errors with automatic reconnection and retry.
        If a connection error occurs mid-query, attempts to reconnect and
        retry the query once.

        Args:
            prompt: The prompt to send
            retry_on_connection_error: If True, attempt reconnect and retry on connection errors
            count_tokens: If True, count tokens toward context limit (default True).
                          Set to False for internal queries like startup prompts that
                          shouldn't count toward the conversation context limit.

        Returns:
            The assistant's text response

        Raises:
            RuntimeError: If not connected
            InvokerConnectionError: If connection fails and cannot recover
            InvokerQueryError: If query fails after retry
        """
        if not self._is_connection_healthy():
            raise RuntimeError("Not connected. Call initialize() first.")

        # Track prompt tokens and update activity time
        prompt_tokens = self._estimate_tokens(prompt)
        if count_tokens:
            self._prompt_tokens += prompt_tokens
        self._last_activity_time = datetime.now()
        logger.debug(f"Sending query: {prompt[:100]}... (+{prompt_tokens} tokens, counted={count_tokens})")

        try:
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

            # Track response tokens and turn count
            response_tokens = self._estimate_tokens(response)
            if count_tokens:
                self._response_tokens += response_tokens
                self._turn_count += 1

            logger.debug(f"Received response: {response[:100]}... (+{response_tokens} tokens, counted={count_tokens})")
            if count_tokens:
                logger.debug(f"Context: {self.context_size} tokens, {self._turn_count} turns")

            return response

        except (CLIConnectionError, ProcessError, ConnectionError) as e:
            # Connection-level errors - attempt recovery if enabled
            logger.error(f"Connection error during query: {e}")

            if not retry_on_connection_error:
                raise InvokerQueryError(
                    f"Query failed with connection error: {e}",
                    retried=False,
                    original_error=e
                )

            # Attempt reconnection
            try:
                await self._reconnect_with_backoff()
            except InvokerConnectionError as reconnect_error:
                # Reconnection failed - surface to caller
                raise InvokerQueryError(
                    f"Query failed and reconnection unsuccessful: {reconnect_error}",
                    retried=True,
                    original_error=e
                )

            # Reconnection successful - retry query once
            logger.info("Reconnected successfully, retrying query...")
            try:
                # Recursive call with retry disabled to prevent infinite loop
                return await self.query(
                    prompt,
                    retry_on_connection_error=False,
                    count_tokens=count_tokens
                )
            except Exception as retry_error:
                raise InvokerQueryError(
                    f"Query failed after successful reconnection: {retry_error}",
                    retried=True,
                    original_error=e
                )

        except Exception as e:
            # Other errors - surface without retry
            logger.error(f"Query failed with non-connection error: {e}")
            raise InvokerQueryError(
                f"Query failed: {e}",
                retried=False,
                original_error=e
            )

    async def query_stream(self, prompt: str) -> AsyncIterator[str]:
        """
        Send a query and stream the response.

        Note: Streaming does not support automatic reconnection. If connection
        is critical, use query() instead.

        Args:
            prompt: The prompt to send

        Yields:
            Text chunks as they arrive

        Raises:
            RuntimeError: If not connected
            InvokerQueryError: If query fails
        """
        if not self._is_connection_healthy():
            raise RuntimeError("Not connected. Call initialize() first.")

        try:
            await self._client.query(prompt)

            async for msg in self._client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            yield block.text
                elif isinstance(msg, ResultMessage):
                    break

        except (CLIConnectionError, ProcessError, ConnectionError) as e:
            logger.error(f"Connection error during streaming query: {e}")
            raise InvokerQueryError(
                f"Streaming query failed with connection error: {e}",
                retried=False,
                original_error=e
            )
        except Exception as e:
            logger.error(f"Streaming query failed: {e}")
            raise InvokerQueryError(
                f"Streaming query failed: {e}",
                retried=False,
                original_error=e
            )

    async def shutdown(self) -> None:
        """
        Cleanly disconnect from Claude Code.

        This is the equivalent of /quit - allows hooks and cleanup to run.
        """
        logger.info("Shutting down Claude Code connection...")

        # Log final context stats
        if self._turn_count > 0:
            stats = self.context_stats
            logger.info(
                f"Session stats: {stats['total_tokens']} tokens "
                f"({stats['prompt_tokens']} prompt + {stats['response_tokens']} response), "
                f"{stats['turn_count']} turns"
            )

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

    def needs_restart(self) -> tuple[bool, str]:
        """
        Check if session should be restarted.

        Returns:
            (should_restart, reason) tuple
        """
        # Check context size
        if self.context_size >= self.max_context_tokens:
            return True, f"context_limit ({self.context_size}/{self.max_context_tokens} tokens)"

        # Check turn count
        if self._turn_count >= self.max_turns:
            return True, f"turn_limit ({self._turn_count}/{self.max_turns} turns)"

        # Check idle time
        if self._last_activity_time:
            idle_seconds = (datetime.now() - self._last_activity_time).total_seconds()
            if idle_seconds >= self.max_idle_seconds:
                return True, f"idle_timeout ({idle_seconds/3600:.1f}h idle)"

        return False, ""

    async def restart(self, reason: str = "", startup_prompt: Optional[str] = None) -> dict:
        """
        Gracefully restart the session.

        This shuts down cleanly and re-initializes. If startup_prompt is provided,
        it overrides the configured startup_prompt for this restart. Otherwise,
        the stored startup_prompt (if any) is used automatically via initialize().

        Args:
            reason: Why we're restarting (for logging)
            startup_prompt: Optional prompt to send after reinitializing. If provided,
                            overrides the stored startup_prompt for this restart only.
                            If None, uses stored startup_prompt (via initialize()).

        Returns:
            Server info from initialize()
        """
        logger.info(f"Restarting session: {reason}")

        # Log final stats before shutdown
        stats = self.context_stats
        logger.info(f"Pre-restart stats: {stats}")

        # Shutdown existing connection
        await self.shutdown()

        # Determine which startup prompt to use
        # If override provided, temporarily swap it in
        if startup_prompt is not None:
            original_prompt = self.startup_prompt
            self.startup_prompt = startup_prompt
            try:
                # Re-initialize (will send the overridden prompt)
                server_info = await self.initialize()
            finally:
                # Restore original prompt
                self.startup_prompt = original_prompt
        else:
            # Use stored startup_prompt via initialize()
            server_info = await self.initialize()

        logger.info("Session restarted successfully")
        return server_info

    async def check_and_restart_if_needed(self, startup_prompt: Optional[str] = None) -> bool:
        """
        Check if restart is needed and perform it if so.

        Args:
            startup_prompt: Prompt to send after restart for identity

        Returns:
            True if restart was performed, False otherwise
        """
        needs_it, reason = self.needs_restart()
        if needs_it:
            await self.restart(reason=reason, startup_prompt=startup_prompt)
            return True
        return False

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
