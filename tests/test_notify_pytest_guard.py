"""scripts/notify.py must never reach the ntfy server from inside a test run.

2026-11-17: a Haven test exercised the "login expired" alert path without a
fake, so each run of the suite sent Jeff a false re-auth alert on his phone.
The guard lives in notify.send() so it covers every caller, including code
under test that shells out to the script.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NOTIFY = REPO / "scripts" / "notify.py"
DEAD_URL = "http://127.0.0.1:9"  # discard port: if the guard fails, nothing is delivered


def _load():
    spec = importlib.util.spec_from_file_location("notify_under_test", NOTIFY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_send_refuses_under_pytest(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setattr(mod, "NTFY_URL", DEAD_URL)

    def must_not_be_called(*a, **k):
        raise AssertionError("notify.send() tried to reach the network under pytest")

    monkeypatch.setattr(mod.urllib.request, "urlopen", must_not_be_called)
    monkeypatch.delenv("NOTIFY_ALLOW_UNDER_PYTEST", raising=False)
    assert mod.send("test") is False
    assert "NOT SENT" in capsys.readouterr().err


def test_cli_refuses_in_a_child_process_of_a_test():
    env = dict(os.environ, NTFY_URL=DEAD_URL)
    env.pop("NOTIFY_ALLOW_UNDER_PYTEST", None)
    assert env.get("PYTEST_CURRENT_TEST"), "pytest should set this during a test"
    r = subprocess.run(
        [sys.executable, str(NOTIFY), "--entity", "lyra", "test"],
        env=env, capture_output=True, text=True, timeout=20,
    )
    assert r.returncode == 1
    assert "NOT SENT" in r.stderr


def test_override_lets_a_deliberate_send_through(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "NTFY_URL", DEAD_URL)
    monkeypatch.setenv("NOTIFY_ALLOW_UNDER_PYTEST", "1")
    reached = []

    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        reached.append(req.full_url)
        return _Resp()

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod.send("test") is True
    assert reached and reached[0].startswith(DEAD_URL)
