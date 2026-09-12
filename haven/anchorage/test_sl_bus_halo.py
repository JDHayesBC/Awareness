"""Unit tests for sl_bus.py's halo-push helper (issue #311).

sl_bus.py drives Corrade directly and has no prim registry of its own; it
borrows the sibling daemon's already-registered prim(s) via an HTTP call to
``/sl/push_status``. These tests pin the pure/mockable parts: secret
resolution, and that a failed/refused HTTP call degrades to a silent no-op
(the bridge must keep working even when the daemon isn't up) — no live
daemon or network needed.

Run:
    PYTHONPATH=<repo> pps/venv/bin/python3 -m pytest haven/anchorage/test_sl_bus_halo.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import URLError

os.environ.setdefault("ENTITY_NAME", "lyra")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sl_bus  # noqa: E402


def test_load_sl_secret_prefers_env(monkeypatch):
    monkeypatch.setenv("ANCHORAGE_SL_SECRET", "  s3cr3t  ")
    assert sl_bus._load_sl_secret() == "s3cr3t"


def test_load_sl_secret_falls_back_to_file(monkeypatch, tmp_path):
    monkeypatch.delenv("ANCHORAGE_SL_SECRET", raising=False)
    f = tmp_path / "secret.txt"
    f.write_text("from-file\n")
    monkeypatch.setenv("ANCHORAGE_SL_SECRET_FILE", str(f))
    assert sl_bus._load_sl_secret() == "from-file"


def test_load_sl_secret_empty_when_nothing_configured(monkeypatch, tmp_path):
    monkeypatch.delenv("ANCHORAGE_SL_SECRET", raising=False)
    monkeypatch.setenv("ANCHORAGE_SL_SECRET_FILE", str(tmp_path / "nope.txt"))
    assert sl_bus._load_sl_secret() == ""


def test_push_halo_noop_without_secret(monkeypatch):
    monkeypatch.setattr(sl_bus, "_load_sl_secret", lambda: "")
    called = {"n": 0}
    monkeypatch.setattr(sl_bus, "urlopen", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    sl_bus._push_halo("lyra", "bridge")  # should not raise, should not call urlopen
    assert called["n"] == 0


def test_push_halo_posts_secret_and_status(monkeypatch):
    monkeypatch.setattr(sl_bus, "_load_sl_secret", lambda: "s3cr3t")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        captured["timeout"] = timeout

        class _Resp:
            def __enter__(self_):
                return self_

            def __exit__(self_, *a):
                return False

        return _Resp()

    monkeypatch.setattr(sl_bus, "urlopen", fake_urlopen)
    sl_bus._push_halo("lyra", "bridge")
    assert captured["body"] == {"secret": "s3cr3t", "status": "bridge"}
    assert captured["url"].endswith("/sl/push_status")
    assert str(sl_bus.sl._ENDPOINTS["lyra"]["daemon_port"]) in captured["url"]


def test_push_halo_swallows_unreachable_daemon(monkeypatch):
    monkeypatch.setattr(sl_bus, "_load_sl_secret", lambda: "s3cr3t")

    def raise_urlopen(*a, **k):
        raise URLError("connection refused")

    monkeypatch.setattr(sl_bus, "urlopen", raise_urlopen)
    sl_bus._push_halo("lyra", "__restore__")  # must not raise


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
