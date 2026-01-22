#!/usr/bin/env python3
"""
Test script for Phase 1.2 - Graceful Restart functionality.

Tests:
1. needs_restart() returns False on fresh session
2. needs_restart() triggers on context limit
3. needs_restart() triggers on turn limit
4. restart() works correctly
5. check_and_restart_if_needed() convenience method
"""

import asyncio
import logging

from invoker import ClaudeInvoker

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_needs_restart_fresh():
    """Test that fresh session doesn't need restart."""
    logger.info("TEST: Fresh session should not need restart")

    # Create invoker with low limits for testing
    invoker = ClaudeInvoker(
        max_context_tokens=100_000,
        max_turns=50,
        max_idle_seconds=3600,
        mcp_servers={}  # Disable MCP for faster test
    )

    await invoker.initialize()

    needs_it, reason = invoker.needs_restart()
    logger.info(f"  needs_restart: {needs_it}, reason: '{reason}'")
    assert not needs_it, "Fresh session should not need restart"

    await invoker.shutdown()
    logger.info("  ✓ PASSED")


async def test_context_limit():
    """Test that context limit triggers restart."""
    logger.info("TEST: Context limit should trigger restart")

    # Very low limit for testing
    invoker = ClaudeInvoker(
        max_context_tokens=100,  # Very low
        max_turns=1000,
        mcp_servers={}
    )

    await invoker.initialize()

    # Simulate token accumulation using test harness
    invoker.simulate_context_usage(110)  # Over the 100 limit

    needs_it, reason = invoker.needs_restart()
    logger.info(f"  needs_restart: {needs_it}, reason: '{reason}'")
    assert needs_it, "Should need restart due to context limit"
    assert "context_limit" in reason, f"Reason should mention context_limit: {reason}"

    await invoker.shutdown()
    logger.info("  ✓ PASSED")


async def test_turn_limit():
    """Test that turn limit triggers restart."""
    logger.info("TEST: Turn limit should trigger restart")

    invoker = ClaudeInvoker(
        max_context_tokens=100_000,
        max_turns=5,  # Very low
        mcp_servers={}
    )

    await invoker.initialize()

    # Simulate turns
    invoker._turn_count = 6  # Over limit

    needs_it, reason = invoker.needs_restart()
    logger.info(f"  needs_restart: {needs_it}, reason: '{reason}'")
    assert needs_it, "Should need restart due to turn limit"
    assert "turn_limit" in reason, f"Reason should mention turn_limit: {reason}"

    await invoker.shutdown()
    logger.info("  ✓ PASSED")


async def test_context_stats():
    """Test that context stats are tracked correctly."""
    logger.info("TEST: Context stats tracking")

    invoker = ClaudeInvoker(mcp_servers={})
    await invoker.initialize()

    # Simulate some activity
    invoker._prompt_tokens = 1000
    invoker._response_tokens = 2000
    invoker._turn_count = 3

    stats = invoker.context_stats
    logger.info(f"  Stats: {stats}")

    assert stats['prompt_tokens'] == 1000
    assert stats['response_tokens'] == 2000
    assert stats['total_tokens'] == 3000
    assert stats['turn_count'] == 3

    await invoker.shutdown()
    logger.info("  ✓ PASSED")


async def test_check_and_restart_if_needed():
    """Test convenience method for checking and restarting."""
    logger.info("TEST: check_and_restart_if_needed() convenience method")

    # Create invoker with low turn limit
    invoker = ClaudeInvoker(
        max_turns=2,
        mcp_servers={}
    )

    await invoker.initialize()

    # First check - should not restart
    restarted = await invoker.check_and_restart_if_needed()
    logger.info(f"  First check - restarted: {restarted}")
    assert not restarted, "Should not restart on fresh session"

    # Simulate turns exceeding limit
    invoker._turn_count = 3

    # Second check - should restart
    restarted = await invoker.check_and_restart_if_needed()
    logger.info(f"  Second check - restarted: {restarted}")
    assert restarted, "Should restart when limit exceeded"

    # After restart, turn count should be reset
    assert invoker._turn_count == 0, "Turn count should reset after restart"

    await invoker.shutdown()
    logger.info("  ✓ PASSED")


async def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("Phase 1.2 - Graceful Restart Tests")
    logger.info("=" * 60)

    tests = [
        test_needs_restart_fresh,
        test_context_limit,
        test_turn_limit,
        test_context_stats,
        test_check_and_restart_if_needed,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            logger.error(f"  ✗ FAILED: {e}")
            failed += 1
        logger.info("")

    logger.info("=" * 60)
    logger.info(f"Results: {passed} passed, {failed} failed")
    logger.info("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
