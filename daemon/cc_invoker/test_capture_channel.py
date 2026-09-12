#!/usr/bin/env python3
"""GH #325 — ClaudeInvoker.capture_channel must reach the Claude Code subprocess
as CC_INVOKER_CHANNEL so the terminal capture hooks can skip brain-driven
sessions (whose surfaces already write both sides to the entity's river).

Run: .venv/bin/python3 -m pytest daemon/cc_invoker/test_capture_channel.py -q
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from daemon.cc_invoker.invoker import ClaudeInvoker  # noqa: E402


def test_no_capture_channel_exports_nothing():
    inv = ClaudeInvoker(mcp_servers={})
    assert inv.capture_channel is None
    assert inv.subprocess_env() == {}


def test_capture_channel_exported_as_env():
    inv = ClaudeInvoker(mcp_servers={}, capture_channel="sl")
    assert inv.subprocess_env() == {"CC_INVOKER_CHANNEL": "sl"}


def test_empty_capture_channel_is_off():
    inv = ClaudeInvoker(mcp_servers={}, capture_channel="")
    assert inv.subprocess_env() == {}


def test_sdk_merges_options_env_over_inherited_env():
    """The hooks still need ENTITY_PATH etc. from the daemon's env. The SDK
    transport lays options.env OVER os.environ rather than replacing it —
    pin that contract so an SDK upgrade can't silently break entity routing."""
    import inspect
    from claude_agent_sdk._internal.transport import subprocess_cli

    src = inspect.getsource(subprocess_cli)
    assert "os.environ" in src and "self._options.env" in src, (
        "SDK transport no longer builds the child env from os.environ + options.env; "
        "re-verify that ClaudeAgentOptions.env merges, or pass {**os.environ, ...}"
    )


def test_initialize_passes_env_to_options(monkeypatch):
    """initialize() must hand subprocess_env() to ClaudeAgentOptions(env=...)."""
    import daemon.cc_invoker.invoker as mod

    captured = {}

    class FakeOptions:
        def __init__(self, **kw):
            captured.update(kw)

    class FakeClient:
        def __init__(self, options):
            pass

        async def connect(self):
            raise RuntimeError("stop here — options already captured")

    monkeypatch.setattr(mod, "ClaudeAgentOptions", FakeOptions)
    monkeypatch.setattr(mod, "ClaudeSDKClient", FakeClient)

    import asyncio

    inv = ClaudeInvoker(mcp_servers={}, capture_channel="haven", startup_prompt=None)
    try:
        asyncio.run(inv.initialize(timeout=5, send_startup=False))
    except Exception:
        pass
    assert captured.get("env") == {"CC_INVOKER_CHANNEL": "haven"}
    assert "CC_INVOKER_CHANNEL" not in os.environ  # never leaks into the daemon itself
