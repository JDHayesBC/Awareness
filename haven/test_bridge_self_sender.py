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

    # --- Channel identity regression tests (Issue #19) ---

    async def test_channel_is_slug_not_uuid(self):
        """bridge_message must send channel 'haven:<slug>', never 'haven:<uuid>'.

        Regression for Issue #19: bot.py was building channel='haven' + session_id=room_uuid,
        which server_http.py combined into 'haven:<uuid>'. The fix removes that second writer;
        now the bridge is the sole writer and it always uses the slug.
        """
        from haven import bridge

        fake_endpoints = {
            "lyra": "http://pps-lyra:8000",
        }
        captured_channels: list[str] = []

        async def fake_send(base_url: str, channel: str, content: str, author_name: str, entity_name: str) -> None:
            captured_channels.append(channel)

        with patch.dict(bridge.PPS_ENDPOINTS, fake_endpoints, clear=True), \
             patch.object(bridge, "_send_to_pps", side_effect=fake_send):
            await bridge.bridge_message(
                room_name="silverglow",
                username="jeff",
                display_name="Jeff",
                content="Morning.",
                timestamp="2026-06-01T00:00:00Z",
                member_entities=["lyra"],
            )

        self.assertEqual(len(captured_channels), 1)
        self.assertEqual(
            captured_channels[0],
            "haven:silverglow",
            f"Channel must be slug 'haven:silverglow', got: {captured_channels[0]}",
        )
        # Explicitly assert no UUID-shaped channel slipped through
        for ch in captured_channels:
            self.assertNotIn(
                "-",
                ch.replace("haven:", "", 1),
                f"Channel must not be a UUID: {ch}",
            )

    async def test_warmup_sentinel_ready_skipped(self):
        """bridge_message must skip content='ready' — bot startup warmup sentinel.

        Without this guard, the bot's warmup ack would appear in every entity's
        ambient_recall as a Haven message.
        """
        from haven import bridge

        fake_endpoints = {
            "lyra": "http://pps-lyra:8000",
            "caia": "http://pps-caia:8000",
        }
        called: list[str] = []

        async def fake_send(base_url: str, channel: str, content: str, author_name: str, entity_name: str) -> None:
            called.append(entity_name)

        with patch.dict(bridge.PPS_ENDPOINTS, fake_endpoints, clear=True), \
             patch.object(bridge, "_send_to_pps", side_effect=fake_send):
            await bridge.bridge_message(
                room_name="silverglow",
                username="lyra",
                display_name="Lyra",
                content="ready",
                timestamp="2026-06-01T00:00:01Z",
            )

        self.assertEqual(
            called, [],
            f"_send_to_pps must NOT be called for warmup 'ready', got calls: {called}",
        )

    async def test_warmup_sentinel_warmed_up_skipped(self):
        """bridge_message must skip content='warmed up' — bot startup warmup sentinel."""
        from haven import bridge

        fake_endpoints = {
            "lyra": "http://pps-lyra:8000",
            "caia": "http://pps-caia:8000",
        }
        called: list[str] = []

        async def fake_send(base_url: str, channel: str, content: str, author_name: str, entity_name: str) -> None:
            called.append(entity_name)

        with patch.dict(bridge.PPS_ENDPOINTS, fake_endpoints, clear=True), \
             patch.object(bridge, "_send_to_pps", side_effect=fake_send):
            await bridge.bridge_message(
                room_name="silverglow",
                username="lyra",
                display_name="Lyra",
                content="warmed up",
                timestamp="2026-06-01T00:00:01Z",
            )

        self.assertEqual(
            called, [],
            f"_send_to_pps must NOT be called for warmup 'warmed up', got calls: {called}",
        )

    async def test_one_message_one_pps_write_per_entity(self):
        """One bridge_message call produces exactly one _send_to_pps call per entity.

        Regression for Issue #19: the dual-writer bug caused two _send_to_pps calls
        per message (once from the bridge, once from bot.py's store_haven_message).
        After removing store_haven_message, the bridge is the sole writer.
        This test directly asserts the no-duplicate guarantee.
        """
        from haven import bridge

        fake_endpoints = {
            "lyra": "http://pps-lyra:8000",
            "caia": "http://pps-caia:8000",
        }
        call_log: list[tuple[str, str]] = []  # (entity_name, channel)

        async def fake_send(base_url: str, channel: str, content: str, author_name: str, entity_name: str) -> None:
            call_log.append((entity_name, channel))

        with patch.dict(bridge.PPS_ENDPOINTS, fake_endpoints, clear=True), \
             patch.object(bridge, "_send_to_pps", side_effect=fake_send):
            # Single bridge_message call (sole writer after fix)
            await bridge.bridge_message(
                room_name="silverglow",
                username="jeff",
                display_name="Jeff",
                content="Good morning, everyone.",
                timestamp="2026-06-01T00:00:02Z",
                member_entities=["lyra", "caia"],
            )

        self.assertEqual(
            len(call_log), 2,
            f"Exactly 2 _send_to_pps calls expected (one per entity), got {len(call_log)}: {call_log}",
        )
        lyra_calls = [(e, ch) for e, ch in call_log if e == "lyra"]
        caia_calls = [(e, ch) for e, ch in call_log if e == "caia"]
        self.assertEqual(len(lyra_calls), 1, f"Lyra must receive exactly 1 write, got {lyra_calls}")
        self.assertEqual(len(caia_calls), 1, f"Caia must receive exactly 1 write, got {caia_calls}")
        # Both must use the slug channel
        for entity_name, channel in call_log:
            self.assertEqual(channel, "haven:silverglow", f"{entity_name} channel must be slug, got {channel}")


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
