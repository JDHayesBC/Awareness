"""Regression tests for issue #404 — a perception turn must never query a brain
session that is mid-rotation.

Before the fix, ``_handle_perception`` called ``_perception.turn_done()`` (clearing
``in_flight``) and THEN rotated the session (~100s). The next chat line made
``ingest()`` return a payload and a second turn ran against a session that had only
its light startup. These tests drive the real ``_handle_perception`` /
``_on_corrade_event`` with a stub brain whose ``rotate_if_approaching`` blocks until
the test releases it.

Run: PYTHONPATH=<repo> pps/venv/bin/python3 -m pytest haven/anchorage -q
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("SL_CORRADE", "0")  # skip Corrade client build at import
os.environ.setdefault("ENTITY_NAME", "lyra")

import pytest

from haven.anchorage import perception
from haven.anchorage import sl_daemon as d

SELF = {"lyrapattern", "lyrapattern resident", "lyra"}
ADDR = {"lyra", "lyrapattern"}


def _line(text: str, who: str = "Damian") -> dict:
    return {"type": "Normal", "firstname": who, "lastname": "Resident",
            "agent": "c06d8847-53af-4983-97f7-99dc20566583", "message": text}


class StubBrain:
    """perceive() records (event-log position, deltas); rotate blocks on a gate."""

    def __init__(self, log: list, rotate_raises: bool = False):
        self.log = log
        self.release = asyncio.Event()
        self.rotate_calls = 0
        self.rotate_raises = rotate_raises
        self.perceive_deltas: list[list[str]] = []
        self.invoker = None

    async def perceive(self, scene, deltas, **kw):
        self.log.append("perceive")
        self.perceive_deltas.append(list(deltas))
        return None   # silence; nothing to deliver

    async def rotate_if_approaching(self, threshold=None, on_warmup=None, room_context=None):
        self.rotate_calls += 1
        if self.rotate_calls == 1:        # only the first rotation is slow
            self.log.append("rotate-start")
            await self.release.wait()
            self.log.append("rotate-end")
            if self.rotate_raises:
                raise RuntimeError("rotation blew up")
            return True
        return False


@pytest.fixture
def env(monkeypatch):
    perc = perception.SLPerception(SELF, ADDR, perception.SalienceConfig())
    monkeypatch.setattr(d, "_perception", perc)
    monkeypatch.setattr(d, "_hb", None)
    monkeypatch.setattr(d, "_idle_backoff", None)
    monkeypatch.setattr(d, "_rotation_lock", None, raising=False)
    monkeypatch.setattr(d, "_brain_busy", False)
    monkeypatch.setattr(d, "_consec_timeouts", 0)
    monkeypatch.setattr(d, "_force_restart_pending", False)
    monkeypatch.setattr(d, "_bg_tasks", set())

    async def _noop(*a, **k):
        return None

    async def _scene():
        return "scene"
    monkeypatch.setattr(d, "_live_scene", _scene)
    monkeypatch.setattr(d, "_push_status", _noop)
    monkeypatch.setattr(d, "_halo_debug", _noop)
    monkeypatch.setattr(d, "_capture", _noop)
    log: list = []
    brain = StubBrain(log)
    monkeypatch.setattr(d, "_get_brain", lambda: brain)
    return perc, brain, log


async def _first_turn_into_rotation(perc, brain, log):
    """Fire turn 1 and park it inside its rotation. Returns its task."""
    # A directed first line fires; later lines are scored by the live ingest path.
    p1 = perc.ingest(_line("Lyra, hello there"), now=1000.0)
    assert p1 is not None
    t1 = asyncio.create_task(d._handle_perception(p1))
    for _ in range(50):
        await asyncio.sleep(0)
        if "rotate-start" in log:
            break
    assert "rotate-start" in log, "turn 1 never reached its rotation"
    return t1


async def _drain(*tasks):
    await asyncio.gather(*tasks)
    while d._bg_tasks:
        await asyncio.gather(*list(d._bg_tasks))


def test_line_during_rotation_does_not_reach_brain_until_rotation_returns(env):
    perc, brain, log = env

    async def go():
        t1 = await _first_turn_into_rotation(perc, brain, log)
        # Directed line lands mid-rotation: must NOT start a second turn.
        d._on_corrade_event(_line("Lyra, who is she?"))
        for _ in range(20):
            await asyncio.sleep(0)
        assert log.count("perceive") == 1, f"turn ran mid-rotation: {log}"
        brain.release.set()
        await _drain(t1)
        return log

    out = asyncio.run(go())
    assert out == ["perceive", "rotate-start", "rotate-end", "perceive"]


def test_lines_ingested_during_rotation_reach_the_next_turn_promptly(env):
    perc, brain, log = env

    async def go():
        t1 = await _first_turn_into_rotation(perc, brain, log)
        d._on_corrade_event(_line("Lyra, remember Sarah?"))
        d._on_corrade_event(_line("she was here earlier"))
        brain.release.set()
        # No further inbound line: the follow-up must fire on its own.
        await _drain(t1)

    asyncio.run(go())
    assert len(brain.perceive_deltas) == 2
    joined = "\n".join(brain.perceive_deltas[1])
    assert "remember Sarah" in joined and "she was here earlier" in joined
    assert perc.in_flight is False


def test_wait_for_rotation_is_not_charged_to_turn_timeout(env, monkeypatch):
    perc, brain, log = env
    monkeypatch.setattr(d, "SL_TURN_TIMEOUT", 0.2)

    async def go():
        t1 = await _first_turn_into_rotation(perc, brain, log)
        # A payload minted outside the ingest path (idle watchdog, or one created
        # just before the rotation began) runs while the rotation is in progress.
        p2 = perception.WakePayload(trigger="idle", addressed=False, deltas=["x"])
        t2 = asyncio.create_task(d._handle_perception(p2))
        await asyncio.sleep(0.5)          # well past SL_TURN_TIMEOUT
        assert log.count("perceive") == 1, f"turn queried mid-rotation: {log}"
        brain.release.set()
        await _drain(t1, t2)

    asyncio.run(go())
    assert d._consec_timeouts == 0
    assert d._force_restart_pending is False
    assert log.count("perceive") >= 2


def test_rotation_that_raises_does_not_leave_gate_held(env):
    perc, brain, log = env
    brain.rotate_raises = True

    async def go():
        t1 = await _first_turn_into_rotation(perc, brain, log)
        d._on_corrade_event(_line("Lyra, still there?"))
        brain.release.set()
        await _drain(t1)
        assert not d._get_rotation_lock().locked()
        # And single-flight is free again for later lines / idle polls.
        assert perc.in_flight is False

    asyncio.run(go())
    assert log.count("perceive") == 2


def test_no_rotation_means_no_change(env):
    perc, brain, log = env
    brain.rotate_calls = 1   # make every rotate a fast no-op

    async def go():
        p = perc.ingest(_line("Lyra, hi"), now=1000.0)
        await _drain(asyncio.create_task(d._handle_perception(p)))

    asyncio.run(go())
    assert log == ["perceive"]
    assert perc.in_flight is False
