"""A skip must never be silent (#334).

On 2026-09-15 orphaned `messages.summary_id` pointers deflated the backlog count the
daemon gates on — 155 became 55 — and 55 fell under the threshold of 100. The entity
was skipped with no log line at all. The damage suppressed its own detection: the
messages that would have raised the count were exactly the ones being hidden.

The branch carried the comment "Silent skip — healthy". It was the only health
assertion in the chain and it was made about a number nothing validates.

The invariant: "nothing to do" and "nothing was checked" must be distinguishable from
outside the process. This is the same defect as the ambient organs returning "" on
crash (fixed in 64e5889) — silence must mean exactly one thing.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def daemon():
    spec = importlib.util.spec_from_file_location(
        "summarize_daemon", ROOT / "scripts" / "summarize_daemon.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["summarize_daemon"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_healthy_backlog_still_logs_count_and_threshold(daemon, monkeypatch):
    """The regression: a skip that says nothing is indistinguishable from a skipped check."""
    lines = []
    monkeypatch.setattr(daemon, "log", lines.append)
    monkeypatch.setattr(daemon, "SUMMARIZE_THRESHOLD", 100)

    async def fake_count(client, pps_url, token):
        return 55

    monkeypatch.setattr(daemon, "check_unsummarized_count", fake_count)
    monkeypatch.setattr(daemon, "get_token", lambda token_file: "tok")

    async def must_not_run(*a, **kw):
        raise AssertionError("summarizer ran on a healthy backlog")

    monkeypatch.setattr(daemon, "run_summarize", must_not_run)

    await daemon.process_entity(
        {"name": "probe", "pps_url": "http://localhost:9999", "token_file": "/dev/null"}
    )

    assert lines, "a healthy backlog produced NO log line — the skip is silent again"
    joined = " ".join(lines)
    assert "55" in joined, f"skip line omits the count: {lines}"
    assert "100" in joined, f"skip line omits the threshold: {lines}"


@pytest.mark.asyncio
async def test_the_deflated_count_that_caused_the_incident_is_now_audible(daemon, monkeypatch):
    """55 under a threshold of 100 is exactly the 2026-09-15 case. It must speak."""
    lines = []
    monkeypatch.setattr(daemon, "log", lines.append)
    monkeypatch.setattr(daemon, "SUMMARIZE_THRESHOLD", 100)
    monkeypatch.setattr(daemon, "get_token", lambda token_file: "tok")

    async def fake_count(client, pps_url, token):
        return 55

    monkeypatch.setattr(daemon, "check_unsummarized_count", fake_count)
    monkeypatch.setattr(daemon, "run_summarize", lambda *a, **kw: None)

    await daemon.process_entity(
        {"name": "lyra", "pps_url": "http://localhost:9999", "token_file": "/dev/null"}
    )

    assert any("lyra" in ln for ln in lines), (
        "the entity was skipped without naming itself — this is the line that was "
        "missing on 2026-09-15"
    )
