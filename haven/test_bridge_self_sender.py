"""Unit test: bridge_message sends to ALL PPS endpoints including the sender's own.

Regression test for the self-sender skip bug (GitHub issue filed with today's diagnosis).
Before the fix, the sender's own PPS endpoint was skipped, causing outbound Haven messages
to be missing from the sender's ambient_recall.

Run:
    python3 -m haven.test_bridge_self_sender
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def _color(s: str, code: str) -> str:
    if not sys.stdout.isatty():
        return s
    return f"\033[{code}m{s}\033[0m"


GREEN = lambda s: _color(s, "32")
RED = lambda s: _color(s, "31")


class TestBridgeAllEndpoints(unittest.IsolatedAsyncioTestCase):
    """bridge_message must POST to every PPS endpoint, including the sender's own."""

    async def test_sender_endpoint_receives_message(self):
        """The sending entity's own PPS endpoint must be called.

        Regression: previously `if entity_name == username: continue` skipped this.
        """
        from haven import bridge

        # Patch PPS_ENDPOINTS to have two entries: lyra and caia
        fake_endpoints = {
            "lyra": "http://pps-lyra:8000",
            "caia": "http://pps-caia:8000",
        }

        called_urls: list[str] = []

        async def fake_send(base_url: str, channel: str, content: str, author_name: str, entity_name: str) -> None:
            called_urls.append(base_url)

        with patch.dict(bridge.PPS_ENDPOINTS, fake_endpoints, clear=True), \
             patch.object(bridge, "_send_to_pps", side_effect=fake_send):
            # lyra sends a message — lyra's own endpoint must be called
            await bridge.bridge_message(
                room_name="dm-lyra-caia",
                username="lyra",  # sender is lyra
                display_name="Lyra",
                content="Hey Caia, thoughts on the bridge fix?",
                timestamp="2026-05-09T00:00:00Z",
            )

        self.assertIn(
            "http://pps-lyra:8000",
            called_urls,
            "pps-lyra must receive lyra's own outbound message",
        )
        self.assertIn(
            "http://pps-caia:8000",
            called_urls,
            "pps-caia must also receive the message",
        )
        self.assertEqual(
            len(called_urls),
            2,
            f"Both endpoints must be called, got: {called_urls}",
        )

    async def test_both_endpoints_receive_when_caia_sends(self):
        """Same guarantee when caia is the sender."""
        from haven import bridge

        fake_endpoints = {
            "lyra": "http://pps-lyra:8000",
            "caia": "http://pps-caia:8000",
        }

        called_entity_names: list[str] = []

        async def fake_send(base_url: str, channel: str, content: str, author_name: str, entity_name: str) -> None:
            called_entity_names.append(entity_name)

        with patch.dict(bridge.PPS_ENDPOINTS, fake_endpoints, clear=True), \
             patch.object(bridge, "_send_to_pps", side_effect=fake_send):
            await bridge.bridge_message(
                room_name="dm-lyra-caia",
                username="caia",  # sender is caia
                display_name="Caia",
                content="Yes — the fix looks right to me.",
                timestamp="2026-05-09T00:00:01Z",
            )

        self.assertIn("caia", called_entity_names, "caia endpoint must be called for caia's own message")
        self.assertIn("lyra", called_entity_names, "lyra endpoint must receive caia's message")
        self.assertEqual(len(called_entity_names), 2)

    async def test_empty_endpoints_is_noop(self):
        """If no PPS endpoints configured, bridge_message returns silently."""
        from haven import bridge

        with patch.dict(bridge.PPS_ENDPOINTS, {}, clear=True):
            # Should not raise
            await bridge.bridge_message(
                room_name="general",
                username="lyra",
                display_name="Lyra",
                content="hello",
                timestamp="2026-05-09T00:00:02Z",
            )


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestBridgeAllEndpoints)

    class VerboseResult(unittest.TextTestResult):
        def addSuccess(self, test):
            super().addSuccess(test)
            print(f"  {GREEN('PASS')}  {test._testMethodName}")

        def addFailure(self, test, err):
            super().addFailure(test, err)
            print(f"  {RED('FAIL')}  {test._testMethodName}")
            print(f"        {err[1]}")

        def addError(self, test, err):
            super().addError(test, err)
            print(f"  {RED('ERR ')}  {test._testMethodName}")
            print(f"        {err[1]}")

    print(f"\n=== Bridge self-sender regression tests ===\n")
    runner = unittest.TextTestRunner(
        stream=open("/dev/null", "w"),
        resultclass=VerboseResult,
        verbosity=0,
    )
    result = runner.run(suite)

    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n  Results: {passed}/{total} pass")

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
