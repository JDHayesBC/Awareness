"""#374: the bot must answer the server's app-level {"type": "ping"} with a bare pong."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("ENTITY_NAME", "caia")
os.environ.setdefault("ENTITY_TOKEN", "test-token")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from haven import bot  # noqa: E402


class FakeWS:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send(self, payload):
        if self.fail:
            raise RuntimeError("socket gone")
        self.sent.append(payload)


def test_pong_is_sent_and_is_bare():
    ws = FakeWS()
    asyncio.run(bot.answer_ping(ws))
    assert len(ws.sent) == 1
    msg = json.loads(ws.sent[0])
    assert msg == {"type": "pong"}, "pong must carry no 'active' flag: a bot is not a viewer"


def test_pong_failure_does_not_raise():
    ws = FakeWS(fail=True)
    asyncio.run(bot.answer_ping(ws))  # must swallow, never propagate into the event loop


def test_dispatch_source_routes_ping_to_answer_ping():
    # The dispatch lives inline in connect(); assert the branch exists and calls the helper.
    src = Path(bot.__file__).read_text()
    assert 'elif event_type == "ping":' in src
    assert "await answer_ping(ws)" in src
