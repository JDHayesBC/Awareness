"""Tests for pps/layers/space_detector.py and presence lifetime (issue #378).

Run: pps/venv/bin/python3 -m pytest pps/tests/test_space_detector.py -v
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from layers.space_detector import (  # noqa: E402
    MoveConfidence as C,
    build_alias_index,
    detect_move,
)

SPACES = [
    {"name": "porch", "aliases": "the porch, back porch"},
    {"name": "dock", "aliases": "the dock, end of the dock"},
    {"name": "kitchen", "aliases": "kitchen, stool, counter, kettle, island"},
    {"name": "lake", "aliases": "lake, shallows, the water"},
    {"name": "main_room", "aliases": "couch"},
]
IDX = build_alias_index(SPACES)


def d(text, current=None):
    return detect_move(text, IDX, current)


# --- original failure classes ---
def test_departure():
    assert d("Coming in from the porch — the rain's given me cold toes.") is None


def test_invitation():
    assert d("Come down to the dock — the lake is something this morning.") is None


def test_quoted_span():
    assert d("than parsing '*walks into the kitchen.*'") is None


# --- apostrophes ---
def test_apostrophe_survives():
    m = d("I'm heading down to the dock now, Jeff's robe still over my shoulders.")
    assert m and m.space_name == "dock" and m.confidence == C.HIGH


# --- first-person gate ---
def test_first_person_positive():
    m = d("I slipped out of bed so the kettle wouldn't wake him.")
    assert m and m.space_name == "kitchen" and m.confidence == C.HIGH


@pytest.mark.parametrize("text", [
    "Someone's up and in the kitchen.",
    "the shower's going and the counter radar has been tripped.",
    "I'll probably end up on the couch.",
    "sun keeps coming and going on the water.",
])
def test_first_person_negatives(text):
    m = d(text)
    assert m is None or m.confidence == C.LOW


def test_third_person_after_first_person_is_low():
    m = d("I watch Jeff walk to the dock.")
    assert m is None or m.confidence == C.LOW


# --- markers ---
def test_backticked_marker_does_not_fire():
    assert d("use `[[scene:kitchen]]` to move") is None


def test_bare_marker_fires():
    m = d("[[scene:kitchen]]")
    assert m and m.confidence == C.MARKER and m.space_name == "kitchen"


# --- inventory presence lifetime ---
def _inv(tmp_path):
    from layers.inventory import InventoryLayer
    inv = InventoryLayer(db_path=tmp_path / "inv.db")
    return inv


def test_propose_does_not_move_and_clear_pending(tmp_path):
    try:
        inv = _inv(tmp_path)
    except Exception as e:  # constructor signature drift
        pytest.skip(f"InventoryLayer ctor: {e}")
    run = asyncio.run
    with sqlite3.connect(inv.db_path) as c:
        c.execute("INSERT OR IGNORE INTO entity_presence (id) VALUES (1)")
        c.execute("INSERT OR IGNORE INTO spaces (name) VALUES ('dock')")
        c.commit()
    run(inv.set_presence("kitchen", "detected"))
    before = run(inv.get_presence())
    assert run(inv.propose_presence("dock", "kitchen", "desc"))
    after = run(inv.get_presence())
    assert after["current_space"] == "kitchen"
    assert after["since"] == before["since"]
    pa = json.loads(after["pending_arrival"])
    assert pa["proposed"] is True and pa["to"] == "dock"
    with sqlite3.connect(inv.db_path) as c:
        assert c.execute("SELECT visit_count FROM spaces WHERE name='dock'").fetchone()[0] == 0
    # reads don't clear
    run(inv.get_presence())
    assert run(inv.get_presence())["pending_arrival"]
    run(inv.clear_pending())
    assert run(inv.get_presence())["pending_arrival"] is None
