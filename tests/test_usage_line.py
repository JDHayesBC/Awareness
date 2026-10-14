"""Tests for get_usage_line() in the inject_context hook (#370)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".claude" / "hooks"))
import inject_context as ic  # noqa: E402

TOKEN = "sk-ant-oat01-SECRETTOKEN"


def _raw(five=5, seven=39, scoped=55, active=False, benign_active=False, spend_reached=False, extra=True):
    r = {
        "five_hour": {"utilization": five, "resets_at": "2026-10-14T18:19:00+00:00"},
        "seven_day": {"utilization": seven, "resets_at": "2026-10-14T18:59:00+00:00"},
        "limits": [
            {"kind": "session", "percent": five, "is_active": False},
            {"kind": "weekly_all", "percent": seven, "is_active": False},
            {"kind": "weekly_scoped", "percent": scoped, "is_active": active or benign_active,
             "severity": "critical" if active else "normal",
             "resets_at": "2026-10-14T18:59:00+00:00",
             "scope": {"model": {"display_name": "Fable"}}},
        ],
    }
    if extra:
        r["extra_usage"] = {"is_enabled": True, "monthly_limit": 2000,
                            "used_credits": 0, "currency": "CAD",
                            "spend_limit_reached": spend_reached}
    return r


@pytest.fixture
def cache(tmp_path, monkeypatch):
    f = tmp_path / "usage_cache.json"
    monkeypatch.setattr(ic, "_USAGE_CACHE_FILE", f)
    return f


def _boom():
    raise RuntimeError(f"offline {TOKEN}")


def test_happy_path(cache, monkeypatch):
    monkeypatch.setattr(ic, "_fetch_usage", lambda: _raw())
    line = ic.get_usage_line()
    assert line.startswith("[usage] session 5% (resets ")
    assert " · week 39% · week/Fable 55% (resets " in line
    assert line.endswith("· extra 0/2000 CAD")
    assert "⚠" not in line and "🔴" not in line
    assert json.loads(cache.read_text())["line"] == line


def test_fresh_cache_skips_fetch(cache, monkeypatch):
    cache.write_text(json.dumps({"ts": time.time(), "line": "[usage] cached", "raw": {}}))
    monkeypatch.setattr(ic, "_fetch_usage", _boom)
    assert ic.get_usage_line() == "[usage] cached"


def test_warning_at_80(cache, monkeypatch):
    monkeypatch.setattr(ic, "_fetch_usage", lambda: _raw(scoped=80))
    line = ic.get_usage_line()
    assert "⚠ week/Fable 80%" in line
    assert "⚠ week 39%" not in line and "🔴" not in line


def test_red_on_active(cache, monkeypatch):
    monkeypatch.setattr(ic, "_fetch_usage", lambda: _raw(active=True))
    assert ic.get_usage_line().startswith("🔴 [usage]")


def test_red_on_spend_limit(cache, monkeypatch):
    monkeypatch.setattr(ic, "_fetch_usage", lambda: _raw(spend_reached=True))
    assert ic.get_usage_line().startswith("🔴 [usage]")


def test_no_extra_segment_when_missing(cache, monkeypatch):
    monkeypatch.setattr(ic, "_fetch_usage", lambda: _raw(extra=False))
    assert "extra" not in ic.get_usage_line()


def test_stale_with_age_on_failure(cache, monkeypatch):
    cache.write_text(json.dumps({"ts": time.time() - 42 * 60, "line": "[usage] old", "raw": {}}))
    monkeypatch.setattr(ic, "_fetch_usage", _boom)
    assert ic.get_usage_line() == "[usage] old (stale 42m)"
    cache.write_text(json.dumps({"ts": time.time() - 3 * 3600 - 5, "line": "[usage] old", "raw": {}}))
    assert ic.get_usage_line() == "[usage] old (stale 3h)"


def test_unavailable_without_cache(cache, monkeypatch):
    monkeypatch.setattr(ic, "_fetch_usage", _boom)
    assert ic.get_usage_line() == "[usage] (unavailable)"


def test_cache_never_contains_token(cache, monkeypatch, tmp_path):
    creds = tmp_path / "creds.json"
    creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": TOKEN}}))
    monkeypatch.setattr(ic, "_USAGE_CREDS_FILE", creds)

    class Resp:
        def read(self): return json.dumps(_raw()).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    seen = {}
    def fake_urlopen(req, timeout=None):
        seen["auth"] = req.get_header("Authorization")
        seen["timeout"] = timeout
        return Resp()
    monkeypatch.setattr(ic.urllib.request, "urlopen", fake_urlopen)

    line = ic.get_usage_line()
    assert seen["auth"] == f"Bearer {TOKEN}" and seen["timeout"] == 10
    assert TOKEN not in cache.read_text() and TOKEN not in line


def test_benign_is_active_is_not_red(cache, monkeypatch):
    """Live API reports is_active=True on weekly_scoped at severity normal."""
    monkeypatch.setattr(ic, "_fetch_usage", lambda: _raw(benign_active=True))
    assert not ic.get_usage_line().startswith("🔴")
