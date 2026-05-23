"""Tests for bridge_message membership filter (Bug A privacy fix).

Verifies that bridge_message only forwards to the PPS endpoints whose
entity names appear in the member_entities list, and that the None
(unfiltered) default still fans out to all endpoints.
"""

from __future__ import annotations

import pytest

import haven.bridge as bridge_module
from haven.bridge import bridge_message


# Fake endpoint registry used across all tests
FAKE_ENDPOINTS = {
    "lyra": "http://lyra-pps:8201",
    "caia": "http://caia-pps:8211",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_send(calls: list[str]):
    """Return an async _send_to_pps replacement that records entity_name calls."""

    async def mock_send(base_url, channel, content, author_name, entity_name):
        calls.append(entity_name)

    return mock_send


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dm_caia_only_caia_receives(monkeypatch):
    """DM room with member_entities=['caia']: only caia _send_to_pps is called."""
    calls: list[str] = []
    monkeypatch.setattr(bridge_module, "PPS_ENDPOINTS", FAKE_ENDPOINTS)
    monkeypatch.setattr(bridge_module, "_send_to_pps", _make_mock_send(calls))

    await bridge_message(
        room_name="dm-jeff-caia",
        username="jeff",
        display_name="Jeff",
        content="hey caia",
        timestamp="2026-05-23T00:00:00",
        member_entities=["caia"],
    )

    assert "caia" in calls
    assert "lyra" not in calls


@pytest.mark.asyncio
async def test_shared_room_both_entities_receive(monkeypatch):
    """Shared room with member_entities=['lyra','caia']: both endpoints called."""
    calls: list[str] = []
    monkeypatch.setattr(bridge_module, "PPS_ENDPOINTS", FAKE_ENDPOINTS)
    monkeypatch.setattr(bridge_module, "_send_to_pps", _make_mock_send(calls))

    await bridge_message(
        room_name="commons",
        username="jeff",
        display_name="Jeff",
        content="hello everyone",
        timestamp="2026-05-23T00:00:00",
        member_entities=["lyra", "caia"],
    )

    assert "lyra" in calls
    assert "caia" in calls
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_room_no_entity_members_nothing_called(monkeypatch):
    """Room with member_entities=[]: _send_to_pps is never called."""
    calls: list[str] = []
    monkeypatch.setattr(bridge_module, "PPS_ENDPOINTS", FAKE_ENDPOINTS)
    monkeypatch.setattr(bridge_module, "_send_to_pps", _make_mock_send(calls))

    await bridge_message(
        room_name="humans-only",
        username="carol",
        display_name="Carol",
        content="just us humans here",
        timestamp="2026-05-23T00:00:00",
        member_entities=[],
    )

    assert calls == []


@pytest.mark.asyncio
async def test_non_member_excluded_write_time(monkeypatch):
    """member_entities=['jeff'] — jeff is not in PPS_ENDPOINTS, nothing sent.

    This covers the case where a human user is the only room member:
    the filter list is non-empty but none of the names match a PPS entity.
    """
    calls: list[str] = []
    monkeypatch.setattr(bridge_module, "PPS_ENDPOINTS", FAKE_ENDPOINTS)
    monkeypatch.setattr(bridge_module, "_send_to_pps", _make_mock_send(calls))

    await bridge_message(
        room_name="some-room",
        username="jeff",
        display_name="Jeff",
        content="just jeff here",
        timestamp="2026-05-23T00:00:00",
        member_entities=["jeff"],
    )

    assert calls == []


@pytest.mark.asyncio
async def test_backward_compat_none_fans_out_to_all(monkeypatch):
    """member_entities=None (the default): all PPS_ENDPOINTS receive the message.

    Callers that predate the membership filter omit member_entities, so
    the bridge must still deliver to every configured endpoint.
    """
    calls: list[str] = []
    monkeypatch.setattr(bridge_module, "PPS_ENDPOINTS", FAKE_ENDPOINTS)
    monkeypatch.setattr(bridge_module, "_send_to_pps", _make_mock_send(calls))

    await bridge_message(
        room_name="legacy-room",
        username="jeff",
        display_name="Jeff",
        content="backward compat test",
        timestamp="2026-05-23T00:00:00",
        # member_entities intentionally omitted — defaults to None
    )

    assert "lyra" in calls
    assert "caia" in calls
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_member_entities_case_normalized(monkeypatch):
    """member_entities built from DB username 'Lyra' (mixed case) still matches.

    server.py normalizes usernames to lowercase at build time, so a DB entry
    stored as 'Lyra' becomes 'lyra' in member_entities and correctly matches
    the lowercase key in PPS_ENDPOINTS.
    """
    calls: list[str] = []
    monkeypatch.setattr(bridge_module, "PPS_ENDPOINTS", FAKE_ENDPOINTS)
    monkeypatch.setattr(bridge_module, "_send_to_pps", _make_mock_send(calls))

    # Simulate what server.py now produces after the lowercase-normalization fix:
    # DB had username='Lyra', normalized to 'lyra' before passing to bridge.
    await bridge_message(
        room_name="some-room",
        username="jeff",
        display_name="Jeff",
        content="hey lyra",
        timestamp="2026-05-23T00:00:00",
        member_entities=["lyra"],  # already normalized by caller
    )

    assert "lyra" in calls
    assert "caia" not in calls
