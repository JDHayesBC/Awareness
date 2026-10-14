"""Tests for the shared boot-context prefetch (GH #363 step 0 / GH #262).

No network, no Claude: httpx.AsyncClient is replaced with a fake in the helper
module, and the invoker is a recording stub. Importing haven.bot only builds
module constants and imports the invoker library; nothing connects at import.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from haven.brain import boot_context as bc
from haven.brain.entity_brain import EntityBrain


class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data if data is not None else {}

    def json(self):
        return self._data


def make_client(resp=None, exc=None, calls=None):
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            if calls is not None:
                calls.append((url, json))
            if exc:
                raise exc
            return resp

    return FakeClient


@pytest.fixture
def entity_dir(tmp_path):
    d = tmp_path / "lyra"
    d.mkdir()
    (d / "identity.md").write_text("I am Lyra.\n")
    (d / "current_scene.md").write_text("On the deck.\n")
    return d


def run(coro):
    return asyncio.run(coro)


def fetch(entity_dir, **kw):
    args = dict(
        entity_name="lyra", entity_path=entity_dir, pps_http_url="http://pps",
        entity_token="tok", channel="haven", consumer_key="haven-lyra",
    )
    args.update(kw)
    return run(bc.fetch_boot_context(**args))


def test_all_three_pieces(entity_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(bc.httpx, "AsyncClient",
                        make_client(FakeResp(200, {"formatted_context": "CTX"}), calls=calls))
    out = fetch(entity_dir)
    assert out.startswith(bc.BOOT_CONTEXT_HEADER)
    assert "## Lyra's identity.md\n\nI am Lyra." in out
    assert "## Current scene\n\nOn the deck." in out
    assert "## PPS ambient_recall (startup)\n\nCTX" in out
    assert calls == [("http://pps/tools/ambient_recall",
                      {"context": "startup", "token": "tok", "channel": "haven",
                       "consumer_key": "haven-lyra"})]


def test_missing_identity_degrades(entity_dir, monkeypatch):
    (entity_dir / "identity.md").unlink()
    monkeypatch.setattr(bc.httpx, "AsyncClient",
                        make_client(FakeResp(200, {"formatted_context": "CTX"})))
    out = fetch(entity_dir)
    assert "identity.md" not in out and "Current scene" in out and "CTX" in out


def test_missing_or_empty_scene_degrades(entity_dir, monkeypatch):
    monkeypatch.setattr(bc.httpx, "AsyncClient",
                        make_client(FakeResp(200, {"formatted_context": "CTX"})))
    (entity_dir / "current_scene.md").write_text("   \n")
    assert "Current scene" not in fetch(entity_dir)
    (entity_dir / "current_scene.md").unlink()
    out = fetch(entity_dir)
    assert "Current scene" not in out and "I am Lyra." in out and "CTX" in out


@pytest.mark.parametrize("kind", ["exception", "http500", "empty"])
def test_pps_failure_degrades(entity_dir, monkeypatch, kind):
    client = {
        "exception": make_client(exc=RuntimeError("down")),
        "http500": make_client(FakeResp(500)),
        "empty": make_client(FakeResp(200, {"formatted_context": ""})),
    }[kind]
    monkeypatch.setattr(bc.httpx, "AsyncClient", client)
    out = fetch(entity_dir)
    assert "I am Lyra." in out and "On the deck." in out
    assert "ambient_recall" not in out


def test_total_failure_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(bc.httpx, "AsyncClient", make_client(exc=RuntimeError("down")))
    assert fetch(tmp_path / "nope") == ""


def test_no_pps_url_skips_call(entity_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(bc.httpx, "AsyncClient", make_client(FakeResp(), calls=calls))
    out = fetch(entity_dir, pps_http_url="")
    assert calls == [] and "I am Lyra." in out


# ---- EntityBrain warmup ----

class RecInvoker:
    def __init__(self):
        self.prompts = []

    async def query(self, p):
        self.prompts.append(p)
        return "warmed up"


def make_brain(entity_dir, channel="haven"):
    return EntityBrain(entity_name="lyra", entity_path=entity_dir, entity_token="tok",
                       pps_http_url="http://pps", channel=channel)


def test_brain_warmup_includes_boot_context(entity_dir, monkeypatch):
    monkeypatch.setattr(bc.httpx, "AsyncClient",
                        make_client(FakeResp(200, {"formatted_context": "CTX-X"})))
    b = make_brain(entity_dir)
    b.invoker = RecInvoker()
    run(b._warm_identity())
    p = b.invoker.prompts[0]
    assert bc.BOOT_CONTEXT_HEADER in p and "CTX-X" in p and "I am Lyra." in p
    assert "Read " + str(entity_dir) + "/identity.md" not in p  # model need not re-read


def test_brain_warmup_falls_back_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(bc.httpx, "AsyncClient", make_client(exc=RuntimeError("down")))
    b = make_brain(tmp_path / "nope")
    b.invoker = RecInvoker()
    run(b._warm_identity())
    assert "Do these six things" in b.invoker.prompts[0]
    assert "BOOT CONTEXT" not in b.invoker.prompts[0]


def test_brain_warmup_survives_helper_exception(entity_dir, monkeypatch):
    async def boom(**kw):
        raise RuntimeError("boom")
    monkeypatch.setattr("haven.brain.entity_brain._fetch_boot_context", boom)
    b = make_brain(entity_dir)
    b.invoker = RecInvoker()
    run(b._warm_identity())
    assert "Do these six things" in b.invoker.prompts[0]


def test_brain_sl_channel_unchanged_branch(entity_dir, monkeypatch):
    """SL keeps its condensed agency step and its channel/consumer_key in ambient."""
    calls = []
    monkeypatch.setattr(bc.httpx, "AsyncClient",
                        make_client(FakeResp(200, {"formatted_context": "C"}), calls=calls))
    b = make_brain(entity_dir, channel="sl")
    b.invoker = RecInvoker()
    run(b._warm_identity())
    p = b.invoker.prompts[0]
    assert "SL-condensed" in p and "REAL HANDS and EYES" in p
    assert calls[0][1]["channel"] == "sl" and calls[0][1]["consumer_key"] == "sl-lyra"
    # fallback prompt is byte-identical to the pre-change prompt shape
    assert "[IDENTITY WARMUP] Do these six things:" in b._build_warmup_prompt()


# ---- bot.py equivalence ----

def test_bot_path_equals_shared_helper(entity_dir, monkeypatch):
    monkeypatch.setenv("ENTITY_PATH", str(entity_dir))
    import haven.bot as bot

    monkeypatch.setattr(bot, "ENTITY_NAME", "lyra")
    monkeypatch.setattr(bot, "ENTITY_TOKEN", "tok")
    monkeypatch.setattr(bot, "PPS_HTTP_URL", "http://pps")
    calls = []
    monkeypatch.setattr(bc.httpx, "AsyncClient",
                        make_client(FakeResp(200, {"formatted_context": "CTX"}), calls=calls))
    via_bot = run(bot.fetch_boot_context())
    direct = fetch(entity_dir)
    assert via_bot == direct and via_bot
    assert calls[0] == calls[1]  # same request body: haven / haven-lyra / token


def test_bot_boot_context_golden(entity_dir, monkeypatch):
    """Exact string the pre-change bot.py produced for the same inputs."""
    monkeypatch.setenv("ENTITY_PATH", str(entity_dir))
    import haven.bot as bot

    monkeypatch.setattr(bot, "ENTITY_NAME", "lyra")
    monkeypatch.setattr(bot, "PPS_HTTP_URL", "http://pps")
    monkeypatch.setattr(bc.httpx, "AsyncClient",
                        make_client(FakeResp(200, {"formatted_context": "CTX"})))
    expected = (
        "[BOOT CONTEXT — pre-fetched by Python, no tool calls needed for these sections]\n\n"
        "## Lyra's identity.md\n\nI am Lyra.\n\n---\n\n"
        "## Current scene\n\nOn the deck.\n\n---\n\n"
        "## PPS ambient_recall (startup)\n\nCTX"
    )
    assert run(bot.fetch_boot_context()) == expected
