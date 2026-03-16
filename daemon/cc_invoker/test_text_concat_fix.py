#!/usr/bin/env python3
"""
Unit tests for the text concatenation fix in ClaudeInvoker.

Tests that:
1. receive_messages() is used instead of receive_response() — handles multi-turn flows
2. TextBlocks from AssistantMessages that contain ToolUseBlocks are skipped (filler)
3. TextBlocks from tool-free AssistantMessages are collected (real response)

Does NOT require a live Claude connection — mocks _client.receive_messages().
"""

import asyncio
import sys
from pathlib import Path

# Add invoker directory to path
sys.path.insert(0, str(Path(__file__).parent))

from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)
from invoker import ClaudeInvoker


# ==================== Mock infrastructure ====================


class MockClient:
    """Mock ClaudeSDKClient that returns pre-programmed messages."""

    def __init__(self, messages):
        self._messages = messages

    async def query(self, prompt):
        pass  # No-op

    async def receive_messages(self):
        for msg in self._messages:
            yield msg


def make_result_message(num_turns=1):
    """Create a ResultMessage."""
    return ResultMessage(
        subtype="success",
        duration_ms=100,
        duration_api_ms=50,
        is_error=False,
        num_turns=num_turns,
        session_id="test-session",
        total_cost_usd=0.001,
    )


def make_invoker_with_messages(messages):
    """Create a ClaudeInvoker with a mocked _client returning given messages."""
    invoker = ClaudeInvoker(mcp_servers={})
    invoker._connected = True
    invoker._client = MockClient(messages)
    return invoker


# ==================== Tests ====================


async def test_no_tool_calls():
    """Single AssistantMessage with one TextBlock — returned as-is."""
    print("TEST: No tool calls")
    messages = [
        AssistantMessage(
            content=[TextBlock("Hello, I'm here.")],
            model="claude-test",
        ),
        make_result_message(num_turns=1),
    ]
    invoker = make_invoker_with_messages(messages)
    response = await invoker.query("Hello")
    assert response == "Hello, I'm here.", f"Expected 'Hello, I'm here.' got {response!r}"
    print("  PASSED")


async def test_single_tool_call_returns_post_tool_text():
    """
    AssistantMessage with [TextBlock+ToolUseBlock] followed by
    AssistantMessage with [TextBlock] — only post-tool text returned.
    """
    print("TEST: Single tool call — post-tool text returned")
    messages = [
        # Turn 1: pre-tool filler + tool call
        AssistantMessage(
            content=[
                TextBlock("Let me check the bedroom..."),
                ToolUseBlock(id="tu_1", name="enter_space", input={"space": "bedroom"}),
            ],
            model="claude-test",
        ),
        make_result_message(num_turns=1),  # intermediate ResultMessage
        # Turn 2: real response after tool result
        AssistantMessage(
            content=[TextBlock("The bedroom is cozy and warm.")],
            model="claude-test",
        ),
        make_result_message(num_turns=2),  # final ResultMessage
    ]
    invoker = make_invoker_with_messages(messages)
    response = await invoker.query("Describe the bedroom")
    assert response == "The bedroom is cozy and warm.", f"Got unexpected response: {response!r}"
    print("  PASSED")


async def test_filler_text_not_in_response():
    """Pre-tool filler text must NOT appear in the response."""
    print("TEST: Filler text excluded from response")
    messages = [
        AssistantMessage(
            content=[
                TextBlock("Let me search for that..."),
                ToolUseBlock(id="tu_1", name="search", input={"query": "test"}),
            ],
            model="claude-test",
        ),
        make_result_message(num_turns=1),
        AssistantMessage(
            content=[TextBlock("I found the answer: 42.")],
            model="claude-test",
        ),
        make_result_message(num_turns=2),
    ]
    invoker = make_invoker_with_messages(messages)
    response = await invoker.query("What is the answer?")
    assert "Let me search" not in response, f"Filler text leaked into response: {response!r}"
    assert "42" in response, f"Real answer missing from response: {response!r}"
    print("  PASSED")


async def test_multiple_tool_calls():
    """Multiple sequential tool calls — only final text-only AssistantMessage returned."""
    print("TEST: Multiple tool calls")
    messages = [
        # Turn 1: first tool call with filler
        AssistantMessage(
            content=[
                TextBlock("Let me first look here..."),
                ToolUseBlock(id="tu_1", name="read_file", input={"path": "a.txt"}),
            ],
            model="claude-test",
        ),
        make_result_message(num_turns=1),
        # Turn 2: second tool call, no text
        AssistantMessage(
            content=[
                ToolUseBlock(id="tu_2", name="read_file", input={"path": "b.txt"}),
            ],
            model="claude-test",
        ),
        make_result_message(num_turns=2),
        # Turn 3: final answer
        AssistantMessage(
            content=[TextBlock("Both files contain the configuration.")],
            model="claude-test",
        ),
        make_result_message(num_turns=3),
    ]
    invoker = make_invoker_with_messages(messages)
    response = await invoker.query("Read the config files")
    assert response == "Both files contain the configuration.", f"Got: {response!r}"
    assert "Let me first" not in response, f"Filler text in response: {response!r}"
    print("  PASSED")


async def test_empty_response_no_text_blocks():
    """No TextBlocks at all — returns empty string."""
    print("TEST: Empty response (no TextBlocks)")
    messages = [
        AssistantMessage(
            content=[
                ToolUseBlock(id="tu_1", name="bash", input={"command": "ls"}),
            ],
            model="claude-test",
        ),
        make_result_message(num_turns=1),
        # ResultMessage with no further AssistantMessage
        make_result_message(num_turns=1),
    ]
    invoker = make_invoker_with_messages(messages)
    response = await invoker.query("Run ls")
    assert response == "", f"Expected empty string, got: {response!r}"
    print("  PASSED")


async def test_tool_call_only_no_final_text():
    """Tool call with filler but no post-tool text — response is empty."""
    print("TEST: Tool call only, no post-tool response text")
    messages = [
        AssistantMessage(
            content=[
                TextBlock("Executing..."),
                ToolUseBlock(id="tu_1", name="bash", input={"command": "exit 0"}),
            ],
            model="claude-test",
        ),
        make_result_message(num_turns=1),
    ]
    invoker = make_invoker_with_messages(messages)
    response = await invoker.query("Do the thing")
    assert response == "", f"Expected empty (all filler), got: {response!r}"
    print("  PASSED")


async def test_multiple_text_only_messages_joined():
    """Multiple text-only AssistantMessages are joined together."""
    print("TEST: Multiple text-only messages joined")
    messages = [
        AssistantMessage(
            content=[TextBlock("Part one. ")],
            model="claude-test",
        ),
        AssistantMessage(
            content=[TextBlock("Part two.")],
            model="claude-test",
        ),
        make_result_message(num_turns=2),
    ]
    invoker = make_invoker_with_messages(messages)
    response = await invoker.query("Write in two parts")
    assert response == "Part one. Part two.", f"Got: {response!r}"
    print("  PASSED")


async def test_existing_restart_logic_unaffected():
    """Token counting still works correctly — existing behavior preserved."""
    print("TEST: Token counting unaffected")
    messages = [
        AssistantMessage(
            content=[TextBlock("Short response.")],
            model="claude-test",
        ),
        make_result_message(num_turns=1),
    ]
    invoker = make_invoker_with_messages(messages)

    assert invoker._turn_count == 0
    assert invoker._response_tokens == 0

    await invoker.query("Test", count_tokens=True)

    assert invoker._turn_count == 1, f"Turn count should be 1, got {invoker._turn_count}"
    assert invoker._response_tokens > 0, "Response tokens should be > 0"
    print("  PASSED")


async def test_count_tokens_false_unaffected():
    """count_tokens=False skips token counting (startup prompt behavior)."""
    print("TEST: count_tokens=False preserved")
    messages = [
        AssistantMessage(
            content=[TextBlock("Identity reconstructed.")],
            model="claude-test",
        ),
        make_result_message(num_turns=1),
    ]
    invoker = make_invoker_with_messages(messages)
    await invoker.query("Reconstruct identity", count_tokens=False)

    assert invoker._turn_count == 0, f"Turn count should stay 0, got {invoker._turn_count}"
    assert invoker._response_tokens == 0, "Response tokens should stay 0"
    print("  PASSED")


# ==================== Main ====================


async def run_all_tests():
    tests = [
        test_no_tool_calls,
        test_single_tool_call_returns_post_tool_text,
        test_filler_text_not_in_response,
        test_multiple_tool_calls,
        test_empty_response_no_text_blocks,
        test_tool_call_only_no_final_text,
        test_multiple_text_only_messages_joined,
        test_existing_restart_logic_unaffected,
        test_count_tokens_false_unaffected,
    ]

    print("=" * 60)
    print("Invoker Text Concat Fix — Unit Tests")
    print("=" * 60)
    print()

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
        except AssertionError as e:
            print(f"  FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        print()

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
