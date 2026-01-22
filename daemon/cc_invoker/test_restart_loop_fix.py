#!/usr/bin/env python3
"""
Test script for restart loop bug fix (Issue #TBD).

The bug: When context limit is hit and restart() is called, initialize()
resets counters to zero, then sends startup_prompt which adds tokens back,
causing immediate restart loop.

The fix: Added count_tokens parameter to query() that defaults to True.
The startup prompt is sent with count_tokens=False so it doesn't count
toward the conversation context limit.

Tests:
1. Startup prompt doesn't count toward context limit
2. Regular queries DO count toward context limit
3. restart() doesn't trigger immediate loop
4. Artificial context simulation works
5. Multiple restarts work correctly
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


async def test_startup_prompt_not_counted():
    """Test that startup prompt doesn't count toward context limit."""
    logger.info("TEST: Startup prompt should not count toward context limit")

    # Create invoker with startup prompt and very low limit
    invoker = ClaudeInvoker(
        max_context_tokens=1000,
        max_turns=100,
        startup_prompt="Hello, please reconstruct your identity.",
        mcp_servers={}  # Disable MCP for faster test
    )

    await invoker.initialize()

    # After initialization with startup prompt, context should still be zero
    stats = invoker.context_stats
    logger.info(f"  Post-init stats: {stats}")
    assert stats['total_tokens'] == 0, f"Startup prompt should not count toward context: {stats}"
    assert stats['turn_count'] == 0, f"Startup prompt should not count as a turn: {stats}"

    await invoker.shutdown()
    logger.info("  ✓ PASSED")


async def test_regular_queries_counted():
    """Test that regular queries DO count toward context limit."""
    logger.info("TEST: Regular queries should count toward context limit")

    invoker = ClaudeInvoker(
        max_context_tokens=10000,
        startup_prompt="Init prompt (not counted)",
        mcp_servers={}
    )

    await invoker.initialize()

    # Context should be zero after init
    assert invoker.context_size == 0, "Should start with zero context"

    # Send a regular query
    response = await invoker.query("What is 2+2?")
    logger.info(f"  Response: {response[:50]}...")

    # Now context should be > 0
    stats = invoker.context_stats
    logger.info(f"  Post-query stats: {stats}")
    assert stats['total_tokens'] > 0, f"Regular query should count toward context: {stats}"
    assert stats['turn_count'] == 1, f"Should have 1 turn: {stats}"

    await invoker.shutdown()
    logger.info("  ✓ PASSED")


async def test_restart_no_loop():
    """Test that restart doesn't trigger immediate loop."""
    logger.info("TEST: Restart should not trigger immediate restart loop")

    # Create invoker with low limit and startup prompt
    invoker = ClaudeInvoker(
        max_context_tokens=1000,  # Low limit for testing
        max_turns=100,
        startup_prompt="Reconstruct identity (this should not count)",
        mcp_servers={}
    )

    await invoker.initialize()

    # Verify we start clean
    assert invoker.context_size == 0, "Should start with zero context"
    assert not invoker.needs_restart()[0], "Fresh session should not need restart"

    # Simulate hitting context limit
    invoker.simulate_context_usage(1100)  # Over the 1000 limit

    # Verify restart is needed
    needs_it, reason = invoker.needs_restart()
    logger.info(f"  Before restart - needs_restart: {needs_it}, reason: '{reason}'")
    assert needs_it, "Should need restart after simulating context usage"

    # Perform restart
    await invoker.restart(reason="simulated context limit")

    # After restart, context should be zero again (startup prompt not counted)
    stats = invoker.context_stats
    logger.info(f"  Post-restart stats: {stats}")
    assert stats['total_tokens'] == 0, f"After restart, context should be zero: {stats}"

    # Should NOT immediately need another restart
    needs_it, reason = invoker.needs_restart()
    logger.info(f"  After restart - needs_restart: {needs_it}, reason: '{reason}'")
    assert not needs_it, "Should NOT need restart immediately after restart"

    await invoker.shutdown()
    logger.info("  ✓ PASSED")


async def test_simulate_context_usage():
    """Test that simulate_context_usage() helper works correctly."""
    logger.info("TEST: simulate_context_usage() helper function")

    invoker = ClaudeInvoker(
        max_context_tokens=5000,
        mcp_servers={}
    )

    await invoker.initialize()

    # Start at zero
    assert invoker.context_size == 0

    # Simulate 1000 tokens
    invoker.simulate_context_usage(1000)
    assert invoker.context_size == 1000, f"Expected 1000 tokens, got {invoker.context_size}"

    # Simulate another 2500 tokens
    invoker.simulate_context_usage(2500)
    assert invoker.context_size == 3500, f"Expected 3500 tokens, got {invoker.context_size}"

    # Not over limit yet
    needs_it, _ = invoker.needs_restart()
    assert not needs_it, "Should not need restart yet"

    # Push over limit
    invoker.simulate_context_usage(2000)
    assert invoker.context_size == 5500, f"Expected 5500 tokens, got {invoker.context_size}"

    # Should trigger restart now
    needs_it, reason = invoker.needs_restart()
    logger.info(f"  needs_restart: {needs_it}, reason: '{reason}'")
    assert needs_it, "Should need restart after exceeding limit"

    await invoker.shutdown()
    logger.info("  ✓ PASSED")


async def test_multiple_restarts():
    """Test that multiple restarts work correctly without loops."""
    logger.info("TEST: Multiple restarts should work without loops")

    invoker = ClaudeInvoker(
        max_context_tokens=500,  # Very low for rapid testing
        startup_prompt="Init (not counted)",
        mcp_servers={}
    )

    await invoker.initialize()

    for i in range(3):
        logger.info(f"  Restart cycle {i+1}/3")

        # Verify we're at zero
        assert invoker.context_size == 0, f"Cycle {i+1}: Should start at zero"

        # Simulate usage to trigger restart
        invoker.simulate_context_usage(600)

        # Verify restart needed
        needs_it, reason = invoker.needs_restart()
        assert needs_it, f"Cycle {i+1}: Should need restart"
        logger.info(f"    Pre-restart: {reason}")

        # Perform restart
        await invoker.restart(reason=f"cycle {i+1}")

        # Verify clean state
        stats = invoker.context_stats
        logger.info(f"    Post-restart stats: {stats}")
        assert stats['total_tokens'] == 0, f"Cycle {i+1}: Context should be zero after restart"

        # Should NOT immediately need another restart
        needs_it, _ = invoker.needs_restart()
        assert not needs_it, f"Cycle {i+1}: Should NOT need immediate restart"

    await invoker.shutdown()
    logger.info("  ✓ PASSED")


async def test_count_tokens_parameter():
    """Test that count_tokens parameter works correctly."""
    logger.info("TEST: count_tokens parameter controls token counting")

    invoker = ClaudeInvoker(mcp_servers={})
    await invoker.initialize()

    # Query with count_tokens=False should not affect context
    await invoker.query("This should not be counted", count_tokens=False)
    assert invoker.context_size == 0, "Query with count_tokens=False should not affect context"
    assert invoker.turn_count == 0, "Query with count_tokens=False should not increment turns"

    # Query with count_tokens=True (default) should affect context
    await invoker.query("This should be counted")
    assert invoker.context_size > 0, "Query with count_tokens=True should affect context"
    assert invoker.turn_count == 1, "Query with count_tokens=True should increment turns"

    # Another query with count_tokens=False
    prev_size = invoker.context_size
    await invoker.query("This also should not be counted", count_tokens=False)
    assert invoker.context_size == prev_size, "Second uncounted query should not change context"
    assert invoker.turn_count == 1, "Turn count should still be 1"

    await invoker.shutdown()
    logger.info("  ✓ PASSED")


async def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("Restart Loop Fix Tests")
    logger.info("=" * 60)

    tests = [
        test_startup_prompt_not_counted,
        test_regular_queries_counted,
        test_restart_no_loop,
        test_simulate_context_usage,
        test_multiple_restarts,
        test_count_tokens_parameter,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            logger.error(f"  ✗ FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        logger.info("")

    logger.info("=" * 60)
    logger.info(f"Results: {passed} passed, {failed} failed")
    logger.info("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
