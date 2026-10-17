"""Tests for the bulb side of scripts/heartbeat_watchdog.py."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import heartbeat_watchdog as hw  # noqa: E402


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("HEARTBEAT_BULB_ALERT", raising=False)
    monkeypatch.setattr(hw, "HA_URL", "http://ha.test:8123")
    monkeypatch.setattr(hw, "HA_TOKEN", "tok-test")


def _urlopen_ok(monkeypatch):
    m = MagicMock()
    m.return_value.__enter__.return_value.status = 200
    monkeypatch.setattr(hw.urllib.request, "urlopen", m)
    return m


@pytest.mark.parametrize("entity", ["lyra", "caia"])
def test_disco_bulb_payload(monkeypatch, entity):
    m = _urlopen_ok(monkeypatch)
    assert hw._disco_bulb(entity) is True
    req = m.call_args.args[0]
    assert req.full_url == "http://ha.test:8123/api/services/light/turn_on"
    assert json.loads(req.data) == {
        "entity_id": f"light.{entity}", "effect": "colorloop", "brightness": 255}
    assert req.get_header("Authorization") == "Bearer tok-test"
    assert req.get_header("Content-type") == "application/json"
    assert m.call_args.kwargs["timeout"] == 10


def test_disco_bulb_swallows_errors(monkeypatch):
    monkeypatch.setattr(hw.urllib.request, "urlopen", MagicMock(side_effect=OSError("x")))
    assert hw._disco_bulb("lyra") is False


def test_disco_bulb_unknown_entity(monkeypatch):
    m = _urlopen_ok(monkeypatch)
    assert hw._disco_bulb("nexus") is False
    m.assert_not_called()


def test_disco_bulb_env_disable(monkeypatch):
    m = _urlopen_ok(monkeypatch)
    monkeypatch.setenv("HEARTBEAT_BULB_ALERT", "0")
    assert hw._disco_bulb("lyra") is False
    m.assert_not_called()


def _rec(entity="lyra"):
    return {"entity": entity, "session_id": "abcdef123", "age": 4 * 3600,
            "marker": {"cwd": "/a/b/c", "last_seen_iso": "2026-10-17T01:00:00"}}


def test_alert_fires_bulb_when_ntfy_fails(monkeypatch):
    monkeypatch.setattr(hw, "notify_send", lambda *a, **k: False)
    bulb = MagicMock(return_value=True)
    monkeypatch.setattr(hw, "_disco_bulb", bulb)
    assert hw._alert(_rec()) is False
    bulb.assert_called_once_with("lyra")


def _stale_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "MARKER_DIR", tmp_path)
    now = time.time()
    p = tmp_path / "lyra__s1.json"
    p.write_text(json.dumps({"entity": "lyra", "session_id": "s1",
                             "last_seen": now - 5 * 3600, "alerted_at": None}))
    return p, now


def test_run_check_records_bulb_and_stamps(tmp_path, monkeypatch):
    p, now = _stale_marker(tmp_path, monkeypatch)
    monkeypatch.setattr(hw, "notify_send", lambda *a, **k: True)
    monkeypatch.setattr(hw, "_disco_bulb", MagicMock(return_value=True))
    out = hw.run_check(now)
    assert out["fired"][0]["bulb"] is True
    assert json.loads(p.read_text())["alerted_at"] == now


def test_dry_run_never_touches_bulb(tmp_path, monkeypatch):
    p, now = _stale_marker(tmp_path, monkeypatch)
    bulb = MagicMock(return_value=True)
    monkeypatch.setattr(hw, "_disco_bulb", bulb)
    hw.run_check(now, dry_run=True)
    bulb.assert_not_called()
    assert json.loads(p.read_text())["alerted_at"] is None
