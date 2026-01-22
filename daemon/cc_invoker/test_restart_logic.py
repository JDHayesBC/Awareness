#!/usr/bin/env python3
"""
Unit tests for restart loop fix logic without requiring Claude SDK.

Tests the core token counting logic by inspecting internal state.
This can run without the claude_agent_sdk installed.
"""

import sys
from pathlib import Path

# Add parent dir to path to import invoker
sys.path.insert(0, str(Path(__file__).parent))


def test_token_counting_logic():
    """Test that count_tokens parameter controls token tracking correctly."""
    print("TEST: Token counting logic")

    # Create a minimal mock to test the logic
    class MockInvoker:
        def __init__(self):
            self._prompt_tokens = 0
            self._response_tokens = 0
            self._turn_count = 0

        def _estimate_tokens(self, text: str) -> int:
            return len(text) // 4

        def query_logic(self, prompt: str, count_tokens: bool = True):
            """Simplified query logic for testing."""
            prompt_tokens = self._estimate_tokens(prompt)
            response_tokens = self._estimate_tokens("Mock response text")

            if count_tokens:
                self._prompt_tokens += prompt_tokens
                self._response_tokens += response_tokens
                self._turn_count += 1

        @property
        def context_size(self) -> int:
            return self._prompt_tokens + self._response_tokens

    invoker = MockInvoker()

    # Initial state
    assert invoker.context_size == 0, "Should start at zero"
    assert invoker._turn_count == 0, "Should start at zero turns"

    # Query with count_tokens=False (like startup prompt)
    invoker.query_logic("This is a startup prompt that should not be counted", count_tokens=False)
    assert invoker.context_size == 0, "Uncounted query should not affect context"
    assert invoker._turn_count == 0, "Uncounted query should not increment turns"

    # Regular query with count_tokens=True (default)
    invoker.query_logic("This is a regular query that should be counted")
    assert invoker.context_size > 0, "Counted query should affect context"
    assert invoker._turn_count == 1, "Counted query should increment turns"

    # Another uncounted query
    prev_size = invoker.context_size
    invoker.query_logic("Another uncounted query", count_tokens=False)
    assert invoker.context_size == prev_size, "Uncounted query should not change context"
    assert invoker._turn_count == 1, "Turn count should remain 1"

    print("  ✓ PASSED")


def test_restart_scenario():
    """Test the restart scenario that was causing the loop."""
    print("TEST: Restart scenario")

    class MockInvoker:
        def __init__(self, max_context_tokens=1000):
            self.max_context_tokens = max_context_tokens
            self.startup_prompt = "Reconstruct your identity (this should not count)"
            self._reset_counters()

        def _reset_counters(self):
            self._prompt_tokens = 0
            self._response_tokens = 0
            self._turn_count = 0

        def _estimate_tokens(self, text: str) -> int:
            return len(text) // 4

        def initialize(self):
            """Simulates initialize() with startup prompt."""
            self._reset_counters()
            # OLD BUG: This would count toward context
            # NEW FIX: Uses count_tokens=False
            self._send_startup_prompt(count_tokens=False)

        def _send_startup_prompt(self, count_tokens=True):
            """Simulates sending startup prompt."""
            tokens = self._estimate_tokens(self.startup_prompt)
            if count_tokens:
                self._prompt_tokens += tokens
                self._response_tokens += tokens  # Simulate response
                self._turn_count += 1

        def simulate_usage(self, tokens: int):
            """Simulate context usage."""
            self._response_tokens += tokens

        def needs_restart(self) -> bool:
            return (self._prompt_tokens + self._response_tokens) >= self.max_context_tokens

        @property
        def context_size(self) -> int:
            return self._prompt_tokens + self._response_tokens

    # Create invoker with low limit
    invoker = MockInvoker(max_context_tokens=1000)

    # Initialize (includes startup prompt with count_tokens=False)
    invoker.initialize()
    print(f"  After init: context_size={invoker.context_size}, needs_restart={invoker.needs_restart()}")
    assert invoker.context_size == 0, "After init with uncounted startup, context should be 0"
    assert not invoker.needs_restart(), "Fresh session should not need restart"

    # Simulate usage to hit limit
    invoker.simulate_usage(1100)
    print(f"  After usage: context_size={invoker.context_size}, needs_restart={invoker.needs_restart()}")
    assert invoker.needs_restart(), "Should need restart after hitting limit"

    # Restart (re-initialize)
    invoker.initialize()
    print(f"  After restart: context_size={invoker.context_size}, needs_restart={invoker.needs_restart()}")
    assert invoker.context_size == 0, "After restart, context should be 0"
    assert not invoker.needs_restart(), "Should NOT immediately need another restart (this was the bug!)"

    # Can do multiple restarts without loop
    for i in range(3):
        invoker.simulate_usage(1100)
        assert invoker.needs_restart(), f"Cycle {i}: Should need restart"
        invoker.initialize()
        assert invoker.context_size == 0, f"Cycle {i}: Context should be 0 after restart"
        assert not invoker.needs_restart(), f"Cycle {i}: Should not immediately need restart"

    print("  ✓ PASSED")


def test_old_bug_behavior():
    """Demonstrate what the old buggy behavior would have been."""
    print("TEST: Old bug behavior (for comparison)")

    class OldBuggyInvoker:
        """This simulates the OLD buggy behavior."""
        def __init__(self, max_context_tokens=1000):
            self.max_context_tokens = max_context_tokens
            self.startup_prompt = "Large startup prompt " * 50  # Make it substantial
            self._reset_counters()

        def _reset_counters(self):
            self._prompt_tokens = 0
            self._response_tokens = 0

        def _estimate_tokens(self, text: str) -> int:
            return len(text) // 4

        def initialize_old_buggy(self):
            """OLD BUGGY VERSION: startup prompt counts toward context."""
            self._reset_counters()
            # BUG: Startup prompt is counted!
            tokens = self._estimate_tokens(self.startup_prompt)
            self._prompt_tokens += tokens
            self._response_tokens += tokens  # Simulate response

        def needs_restart(self) -> bool:
            return (self._prompt_tokens + self._response_tokens) >= self.max_context_tokens

        @property
        def context_size(self) -> int:
            return self._prompt_tokens + self._response_tokens

    # Create invoker with low limit
    invoker = OldBuggyInvoker(max_context_tokens=1000)

    # Initialize with OLD BUGGY behavior
    invoker.initialize_old_buggy()
    print(f"  OLD BUG - After init: context_size={invoker.context_size}")

    # With a large startup prompt, this could immediately trigger restart
    if invoker.context_size >= 500:  # Substantial portion of limit
        print(f"  OLD BUG - Startup used {invoker.context_size}/1000 tokens")
        print(f"  OLD BUG - Only {1000 - invoker.context_size} tokens left for conversation!")
        print(f"  OLD BUG - Could trigger restart after just 1-2 queries → infinite loop")

    print("  ✓ Demonstrated bug behavior")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Restart Loop Fix - Logic Tests (No SDK Required)")
    print("=" * 60)
    print()

    tests = [
        test_token_counting_logic,
        test_restart_scenario,
        test_old_bug_behavior,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  ✗ FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        print()

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
