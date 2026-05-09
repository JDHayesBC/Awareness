"""Tests for issue #198: configurable init_timeout that survives restart.

Pre-#198, ClaudeInvoker.initialize() had a hard-coded 60s default. The Haven
and Discord bots called initialize(timeout=180.0) explicitly to allow time
for the full identity-reconstruction startup ritual — but restart() called
initialize() with NO arguments, so the restart path silently reverted to
the 60s default and dropped the first message after a long idle period.

The fix: add init_timeout to the constructor, store on the instance, and
have initialize() use it when no explicit timeout is passed. restart()
then inherits the same generous timeout that initial startup used.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from invoker import ClaudeInvoker


# ----------------------------------------------------------------------------
# Constructor wiring
# ----------------------------------------------------------------------------


def test_init_timeout_default_is_60s():
    """Backward compat: callers that don't set init_timeout get the historical
    60s default."""
    inv = ClaudeInvoker(mcp_servers={})
    assert inv.init_timeout == 60.0


def test_init_timeout_can_be_overridden_at_construction():
    """Bots that need a longer startup ritual set init_timeout once at
    construction so it survives restart."""
    inv = ClaudeInvoker(mcp_servers={}, init_timeout=180.0)
    assert inv.init_timeout == 180.0


def test_init_timeout_independent_of_other_timeouts():
    """init_timeout is for connect+startup; max_idle_seconds is for live-session
    idle detection. They must not be confused."""
    inv = ClaudeInvoker(
        mcp_servers={},
        init_timeout=180.0,
        max_idle_seconds=4 * 3600,
    )
    assert inv.init_timeout == 180.0
    assert inv.max_idle_seconds == 4 * 3600


# ----------------------------------------------------------------------------
# initialize() picks up self.init_timeout when no explicit timeout passed
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_no_args_uses_configured_init_timeout():
    """When initialize() is called with no timeout (the path restart() takes),
    the configured init_timeout must be used — not the historical 60s default.
    This is the core regression for #198."""
    inv = ClaudeInvoker(mcp_servers={}, init_timeout=180.0)

    # Capture what value is passed to asyncio.timeout(...) inside initialize().
    captured = {}
    real_timeout = asyncio.timeout

    def spy_timeout(value):
        captured["value"] = value
        return real_timeout(value)

    # Mock the SDK client so we never actually connect, and force
    # initialize() to bail before doing real network work — but only AFTER
    # asyncio.timeout(value) has been called with the timeout we want to
    # observe.
    fake_client = MagicMock()
    fake_client.connect = AsyncMock(side_effect=RuntimeError("stop here"))

    with patch("invoker.ClaudeSDKClient", return_value=fake_client), \
         patch("invoker.asyncio.timeout", side_effect=spy_timeout):
        with pytest.raises(RuntimeError, match="Failed to initialize"):
            await inv.initialize()

    assert captured["value"] == 180.0, (
        "initialize() with no explicit timeout must use self.init_timeout, "
        "not the function-signature default — restart() relies on this"
    )


@pytest.mark.asyncio
async def test_initialize_explicit_timeout_overrides_init_timeout():
    """An explicit timeout argument still overrides the configured value
    (backward compat: existing callers passing timeout=180.0 keep working)."""
    inv = ClaudeInvoker(mcp_servers={}, init_timeout=60.0)

    captured = {}
    real_timeout = asyncio.timeout

    def spy_timeout(value):
        captured["value"] = value
        return real_timeout(value)

    fake_client = MagicMock()
    fake_client.connect = AsyncMock(side_effect=RuntimeError("stop here"))

    with patch("invoker.ClaudeSDKClient", return_value=fake_client), \
         patch("invoker.asyncio.timeout", side_effect=spy_timeout):
        with pytest.raises(RuntimeError, match="Failed to initialize"):
            await inv.initialize(timeout=300.0)

    assert captured["value"] == 300.0, (
        "Explicit timeout must override init_timeout — preserves old call sites"
    )


@pytest.mark.asyncio
async def test_initialize_default_invoker_uses_60s():
    """No init_timeout configured + no explicit timeout = historical 60s.
    This is the path stateless API-mode invokers take."""
    inv = ClaudeInvoker(mcp_servers={})  # default init_timeout=60.0

    captured = {}
    real_timeout = asyncio.timeout

    def spy_timeout(value):
        captured["value"] = value
        return real_timeout(value)

    fake_client = MagicMock()
    fake_client.connect = AsyncMock(side_effect=RuntimeError("stop here"))

    with patch("invoker.ClaudeSDKClient", return_value=fake_client), \
         patch("invoker.asyncio.timeout", side_effect=spy_timeout):
        with pytest.raises(RuntimeError, match="Failed to initialize"):
            await inv.initialize()

    assert captured["value"] == 60.0
