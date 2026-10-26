"""Tests for the scene-sense presence gate (#378 pass 3): ack_space, chain completion.

Run: pps/venv/bin/python3 -m pytest pps/tests/test_presence_gate.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from layers.inventory import InventoryLayer  # noqa: E402

run = asyncio.run


@pytest.fixture
def inv(tmp_path):
    layer = InventoryLayer(db_path=tmp_path / "inv.db", entity_path=tmp_path)
    with sqlite3.connect(layer.db_path) as c:
        c.execute("INSERT OR IGNORE INTO spaces (name, description) VALUES ('kitchen', 'KITCHEN FULL')")
        c.execute("INSERT OR IGNORE INTO spaces (name, description) VALUES ('dock', 'DOCK FULL')")
        c.commit()
    return layer


def _visits(inv, name):
    with sqlite3.connect(inv.db_path) as c:
        return c.execute("SELECT visit_count FROM spaces WHERE name=?", (name,)).fetchone()[0]


def test_enter_space_sets_ack_and_writes_no_pending(inv):
    desc = run(inv.enter_space("kitchen"))
    assert desc == "KITCHEN FULL"
    p = run(inv.get_presence())
    assert p["current_space"] == "kitchen"
    assert p["ack_space"] == "kitchen"
    assert p["source"] == "enter_space"
    assert p["pending_arrival"] is None
    assert _visits(inv, "kitchen") == 1


def test_reentering_current_room_is_not_a_visit_and_keeps_since(inv):
    run(inv.enter_space("kitchen"))
    before = run(inv.get_presence())
    run(inv.enter_space("kitchen"))
    after = run(inv.get_presence())
    assert _visits(inv, "kitchen") == 1
    assert after["since"] == before["since"]


def test_detected_move_leaves_ack_unchanged(inv):
    run(inv.enter_space("kitchen"))
    run(inv.set_presence("dock", "detected", "kitchen", "DOCK FULL"))
    p = run(inv.get_presence())
    assert p["current_space"] == "dock"
    assert p["ack_space"] == "kitchen"
    assert json.loads(p["pending_arrival"])["to"] == "dock"


def test_proposed_pending_clears_on_store_real_pending_survives(inv):
    run(inv.set_presence("kitchen", "detected"))
    run(inv.propose_presence("dock", "kitchen", "d"))
    run(inv.clear_pending(only_proposed=True))
    assert run(inv.get_presence())["pending_arrival"] is None

    run(inv.set_presence("dock", "detected", "kitchen", "DOCK FULL"))
    run(inv.clear_pending(only_proposed=True))
    pa = json.loads(run(inv.get_presence())["pending_arrival"])
    assert pa["to"] == "dock" and not pa.get("proposed")


def test_chain_complete_requires_ack_and_fresh_scene(inv, tmp_path):
    scene = tmp_path / "current_scene.md"
    scene.write_text("old portrait")
    old = time.time() - 3600
    os.utime(scene, (old, old))

    run(inv.set_presence("dock", "detected", "kitchen", "DOCK FULL"))
    st = run(inv.chain_status(scene))
    assert (st["ack_ok"], st["scene_ok"], st["complete"]) == (False, False, False)

    run(inv.enter_space("dock"))  # ack only; same room, pending survives
    st = run(inv.chain_status(scene))
    assert (st["ack_ok"], st["scene_ok"], st["complete"]) == (True, False, False)
    assert run(inv.get_presence())["pending_arrival"] is not None

    scene.write_text("fresh portrait")  # mtime = now >= since
    st = run(inv.chain_status(scene))
    assert st["complete"] is True
    # ambient_recall clears the pending when complete
    run(inv.clear_pending())
    assert run(inv.get_presence())["pending_arrival"] is None


def test_chain_scene_only_names_ack_missing(inv, tmp_path):
    scene = tmp_path / "current_scene.md"
    run(inv.set_presence("dock", "detected", "kitchen", "DOCK FULL"))
    scene.write_text("fresh")
    st = run(inv.chain_status(scene))
    assert (st["ack_ok"], st["scene_ok"]) == (False, True)


def test_ack_only_changes_ack_not_move_or_visits(inv):
    run(inv.set_presence("kitchen", "detected", "dock", "K"))
    before = run(inv.get_presence())
    v = _visits(inv, "kitchen")
    desc = run(inv.enter_space("kitchen", ack_only=True))
    assert desc == "KITCHEN FULL"
    after = run(inv.get_presence())
    assert after["ack_space"] == "kitchen"
    assert after["current_space"] == before["current_space"]
    assert after["since"] == before["since"]
    assert after["source"] == before["source"]
    assert after["pending_arrival"] == before["pending_arrival"]
    assert _visits(inv, "kitchen") == v


def test_ack_only_other_room_does_not_move(inv):
    run(inv.set_presence("kitchen", "detected"))
    v = _visits(inv, "dock")
    run(inv.enter_space("dock", ack_only=True))
    p = run(inv.get_presence())
    assert p["current_space"] == "kitchen" and p["ack_space"] == "dock"
    assert _visits(inv, "dock") == v


def test_house_column_migrates_idempotently(tmp_path):
    InventoryLayer(db_path=tmp_path / "a.db", entity_path=tmp_path)
    inv2 = InventoryLayer(db_path=tmp_path / "a.db", entity_path=tmp_path)
    with sqlite3.connect(inv2.db_path) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(spaces)")}
        pcols = {r[1] for r in c.execute("PRAGMA table_info(entity_presence)")}
    assert "house" in cols and "ack_space" in pcols


def test_same_space_detected_does_not_touch_real_state(inv):
    run(inv.set_presence("dock", "detected", "kitchen", "DOCK FULL"))
    before = run(inv.get_presence())
    v = _visits(inv, "dock")
    run(inv.set_presence("dock", "marker", "dock", "DOCK FULL"))
    after = run(inv.get_presence())
    assert after["since"] == before["since"]
    assert after["source"] == before["source"]
    assert after["pending_arrival"] == before["pending_arrival"]
    assert _visits(inv, "dock") == v


def test_same_space_marker_clears_proposed_only(inv):
    run(inv.set_presence("dock", "detected"))
    run(inv.propose_presence("kitchen", "dock", "k"))
    run(inv.set_presence("dock", "marker", "dock", "d"))
    p = run(inv.get_presence())
    assert p["pending_arrival"] is None and p["current_space"] == "dock"


def test_propose_does_not_overwrite_real_pending(inv):
    run(inv.set_presence("dock", "detected", "kitchen", "DOCK FULL"))
    run(inv.propose_presence("kitchen", "dock", "k"))
    pa = json.loads(run(inv.get_presence())["pending_arrival"])
    assert pa["to"] == "dock" and not pa.get("proposed")


def test_chain_mtime_slack_two_seconds(inv, tmp_path):
    scene = tmp_path / "current_scene.md"
    scene.write_text("x")
    run(inv.set_presence("dock", "detected", "kitchen", "D"))
    run(inv.enter_space("dock"))
    since = run(inv.get_presence())["since"]
    from datetime import datetime
    t = datetime.fromisoformat(since).timestamp()
    os.utime(scene, (t - 1.5, t - 1.5))
    assert run(inv.chain_status(scene))["scene_ok"] is True
    os.utime(scene, (t - 5, t - 5))
    assert run(inv.chain_status(scene))["scene_ok"] is False
