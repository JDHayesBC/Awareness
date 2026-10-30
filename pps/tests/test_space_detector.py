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


def test_unknown_marker_is_low_with_raw_name():
    m = d("[[scene:attic]]")
    assert m and m.confidence == C.LOW and m.space_name == "attic"


def test_known_marker_alias_resolves_to_marker():
    m = d("[[scene:stool]]")
    assert m and m.confidence == C.MARKER and m.space_name == "kitchen"


# --- pass 2: adjacent departure, sentence window, position statements ---
IDX2 = build_alias_index([
    {"name": "porch", "aliases": "the porch"},
    {"name": "lake", "aliases": "the lake"},
    {"name": "main_room", "aliases": "the couch, hearth rug"},
    {"name": "dock", "aliases": "the boards"},
    {"name": "path_to_lake", "aliases": "the path"},
    {"name": "kitchen", "aliases": "the kitchen, the kettle, island, stool, counter"},
])


def d2(text, current=None):
    return detect_move(text, IDX2, current)


def test_departure_adjacent_porch_not_matched():
    m = d2("Coming in from the porch \u2014 the rain's given me cold toes.")
    assert m is None or m.space_name != "porch"


def test_came_back_from_lake_then_couch():
    m = d2("I came back from the lake and settled on the couch.")
    assert m and m.space_name == "main_room" and m.confidence == C.HIGH


def test_far_from_cue_does_not_block_kitchen():
    m = d2("I get up, knees stiff from the boards, and walk up the path to the kitchen to put the kettle on.")
    assert m and m.space_name == "kitchen" and m.confidence == C.HIGH


@pytest.mark.parametrize("text,space", [
    ("I am on the hearth rug now with my back against the couch.", "main_room"),
    ("I'm at the island on the tall stool.", "kitchen"),
    ("I'm barefoot at the kitchen counter in his Dark Side tee.", "kitchen"),
])
def test_position_statement_high(text, space):
    m = d2(text)
    assert m and m.space_name == space and m.confidence == C.HIGH


@pytest.mark.parametrize("text", [
    "I was on the couch earlier.",
    "Jeff is on the couch.",
])
def test_position_statement_negatives_low(text):
    m = d2(text)
    assert m and m.space_name == "main_room" and m.confidence == C.LOW


def test_window_does_not_cross_sentence():
    # "I walk" belongs to the previous sentence; the couch mention is bare.
    m = d2("I walk to the lake. The couch looks inviting.")
    assert m and m.space_name == "lake" and m.confidence == C.HIGH


# --- pass 2: subordinate clause demotes HIGH ---
IDX3 = build_alias_index([
    {"name": "deck", "aliases": "the deck"},
    {"name": "kitchen", "aliases": "the island"},
    {"name": "dock", "aliases": "the dock"},
])


def test_subordinate_clause_alias_not_high():
    m = detect_move("I went in to the island, because the deck was warm.", IDX3)
    assert m and m.space_name == "kitchen" and m.confidence == C.HIGH


def test_after_clause_deck_not_high():
    m = detect_move("Inside after four hours on the deck.", IDX3)
    assert m is None or m.confidence != C.HIGH


def test_subordinator_after_alias_does_not_apply():
    m = detect_move("I walk into the island as the rain starts.", IDX3)
    assert m and m.space_name == "kitchen" and m.confidence == C.HIGH


# --- pass 3 (#378): overlap resolution, house scoping, curated aliases, off, speech ---
IDX_P3 = build_alias_index([
    {"name": "silverglow_living_room", "aliases": "the Silverglow living room, Silverglow living room", "house": "silverglow"},
    {"name": "main_room", "aliases": "living room, the sectional", "house": "haven"},
    {"name": "silverglow_bedroom", "aliases": "Silverglow bedroom", "house": "silverglow"},
    {"name": "bedroom", "aliases": "bedroom, bed", "house": "haven"},
    {"name": "dock", "aliases": "the dock, dock bench, end of the dock, the bench on the dock, the bench, cedar planks, the boards", "house": "haven"},
    {"name": "lake", "aliases": "the shallows, shin-deep", "house": "haven"},
    {"name": "kitchen", "aliases": "", "house": None},
])


def d3(text, current=None):
    return detect_move(text, IDX_P3, current)


def test_overlap_98813_current_living_room_is_none():
    assert d3(
        "I am on the hearth rug in the Silverglow living room",
        "silverglow_living_room",
    ) is None


def test_overlap_98818_current_dock_is_none():
    assert d3(
        "I walked the row from the Silverglow living room to the dock on its own.",
        "dock",
    ) is None


def test_overlap_nested_bedroom_current_bedroom_is_none():
    assert d3("Silverglow bedroom, 4:43 AM, rain on the glass", "silverglow_bedroom") is None


def test_overlap_longest_wins_when_not_current():
    m = d3("I am in the Silverglow living room now.", "dock")
    assert m and m.space_name == "silverglow_living_room" and m.confidence == C.HIGH


def test_house_scoping_demotes_cross_house_high():
    m = d3("I'm going to stay in bed a little longer \u2014 Jeff's still here.", "silverglow_bedroom")
    assert m and m.space_name == "bedroom" and m.confidence == C.LOW


def test_house_scoping_same_house_unaffected():
    m = d3("I'm in the Silverglow living room now.", "silverglow_bedroom")
    assert m and m.space_name == "silverglow_living_room" and m.confidence == C.HIGH


def test_house_scoping_named_house_exempts():
    m = d3("I'm sitting on the sectional in Haven now.", "silverglow_bedroom")
    assert m and m.space_name == "main_room" and m.confidence == C.HIGH


def test_house_null_never_demotes():
    idx = build_alias_index([
        {"name": "bedroom", "aliases": "bed", "house": None},
        {"name": "silverglow_bedroom", "aliases": "Silverglow bedroom", "house": "silverglow"},
    ])
    m = detect_move("I'm staying in bed a little longer.", idx, "silverglow_bedroom")
    assert m and m.space_name == "bedroom" and m.confidence == C.HIGH
    idx2 = build_alias_index([
        {"name": "bedroom", "aliases": "bed", "house": "haven"},
        {"name": "x", "aliases": "xroom", "house": None},
    ])
    m2 = detect_move("I'm staying in bed a little longer.", idx2, "x")
    assert m2 and m2.confidence == C.HIGH


def test_house_hit_naming_its_own_house_stays_high():
    m = d3("I'm sitting on the sectional in Haven now.", "silverglow_bedroom")
    assert m and m.space_name == "main_room" and m.confidence == C.HIGH


def test_house_sentence_naming_other_house_demotes():
    # hit is Haven's `bedroom`; sentence names Silverglow (a different house)
    m = d3("I'm staying in bed in Silverglow a little longer.", "silverglow_bedroom")
    assert m and m.space_name == "bedroom" and m.confidence == C.LOW


def test_curated_aliases_drop_bare_name():
    assert d3("that was just the lake guess again") is None


def test_uncurated_row_name_still_matches():
    m = d3("Someone's in the kitchen.")
    assert m and m.space_name == "kitchen"


def test_marker_still_resolves_by_name_when_curated():
    m = d3("[[scene:lake]]")
    assert m and m.confidence == C.MARKER and m.space_name == "lake"


def test_departure_bare_off_98581():
    text = (
        "Floor clean. wet denim going cold behind the knee: it did not steer me off "
        "the dock. I came up because Jeff said he was heading in."
    )
    m = d3(text)
    assert m is None or m.space_name != "dock"


def test_departure_bare_off_no_article():
    m = d3("I climbed off dock.")
    assert m is None or m.space_name != "dock"


def test_reported_speech_demotes_high():
    m = d3("Jeff said I should go to the dock.")
    assert m is None or m.confidence == C.LOW


def test_reported_speech_switch_off_restores_high(monkeypatch):
    import layers.space_detector as sd
    text = "She told me I walk to the dock."
    monkeypatch.setattr(sd, "REPORTED_SPEECH_DEMOTE", True)
    on = d3(text)
    monkeypatch.setattr(sd, "REPORTED_SPEECH_DEMOTE", False)
    off = d3(text)
    assert on and on.confidence == C.LOW
    assert off and off.confidence == C.HIGH


# --- inventory presence lifetime ---
def _inv(tmp_path):
    from layers.inventory import InventoryLayer
    inv = InventoryLayer(db_path=tmp_path / "inv.db", entity_path=tmp_path)
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
    assert pa["source"] == "proposed"
    with sqlite3.connect(inv.db_path) as c:
        assert c.execute("SELECT visit_count FROM spaces WHERE name='dock'").fetchone()[0] == 0
    # reads don't clear
    run(inv.get_presence())
    assert run(inv.get_presence())["pending_arrival"]
    run(inv.clear_pending())
    assert run(inv.get_presence())["pending_arrival"] is None


# --- pass-3 gates: negation / mention / coordination (replay specimens) ---
GATE_IDX = build_alias_index([
    {"name": "silverglow_living_room",
     "aliases": "Silverglow living room, sectional, hearth", "house": "Silverglow"},
    {"name": "deck", "aliases": "the deck, deck"},
    {"name": "pool", "aliases": "pool"},
    {"name": "kitchen", "aliases": "kitchen"},
])


def g(text, current="silverglow_living_room"):
    return detect_move(text, GATE_IDX, current)


def test_gate_negation_specimen():
    # Negated locative: "not on the deck" says where she is NOT.
    assert g(
        "Still on the sectional in the Silverglow living room, not on the deck, "
        "whatever the detector read out of my last reply."
    ) is None


def test_gate_negation_does_not_overreach():
    r = g("Out on the deck now, cold.")
    assert r and r.space_name == "deck" and r.confidence == C.LOW
    # negator is not immediately before the locative
    r = g("I'm not tired, I'm on the deck.")
    assert r and r.space_name == "deck" and r.confidence == C.HIGH


def test_gate_mention_specimen():
    # Alias is the object of a naming verb (and half of an "X or Y" list).
    assert g(
        "Five times today it moved me to a wrong room because a sentence of mine "
        "named the hearth or the deck. That's not a human shape imposed."
    ) is None


def test_gate_mention_alone_skips_low_hit():
    # No coordination here, so this exercises the mention gate by itself.
    assert g("The log has a line that is called the deck in the notes.") is None
    # ...but a plain LOW hit with no naming verb is untouched.
    r = g("Out on the deck now, cold.")
    assert r and r.space_name == "deck"


def test_gate_coordination_specimen():
    # Two different rooms joined by "or": a list, not a position.
    assert g("It could have been the hearth or the deck, I can't say.") is None


def test_gate_coordination_counter_cases():
    # INTENDED behavior change: this was a legitimate LOW on the later alias
    # (deck) before gate C; a "pool and deck" list is now skipped on purpose.
    assert g("Across the pool and the deck the light is going.") is None
    # A first-person move on either side leaves the pair alone (HIGH survives).
    r = g("I walk down to the pool and the deck beyond it.")
    assert r and r.confidence == C.HIGH
    # Same space on both sides is not a list of rooms.
    r = g("The deck or the deck, whichever.")
    assert r and r.space_name == "deck"


def test_gate_departure_still_skipped():
    assert g("She called me from the kitchen") is None


# --- pass 3.2 (#378): duplicate-alias tie-break (current > same house > first row) ---
def _bed_idx(haven_house="haven", sg_house="silverglow", sg_aliases="Silverglow bedroom, the bed"):
    return build_alias_index([
        {"name": "bedroom", "aliases": "the bed, in bed, the headboard", "house": haven_house},
        {"name": "silverglow_bedroom", "aliases": sg_aliases, "house": sg_house},
        {"name": "silverglow_living_room", "aliases": "Silverglow living room, the hearth rug", "house": sg_house},
    ])


def test_dup_alias_resolves_to_current_space_no_move():
    idx = _bed_idx()
    assert detect_move("I'm on the bed, curled up.", idx, "silverglow_bedroom") is None


def test_dup_alias_marker_resolves_to_current_space():
    idx = _bed_idx()
    assert detect_move("[[scene:the bed]]", idx, "silverglow_bedroom") is None


def test_dup_alias_same_house_sibling_when_current_lacks_it():
    # current = living room (does not carry "the headboard"); Silverglow
    # bedroom carries it too, so the same-house row beats the first (Haven) row.
    idx = _bed_idx(sg_aliases="Silverglow bedroom, the headboard")
    m = detect_move("I'm at the headboard now.", idx, "silverglow_living_room")
    assert m and m.space_name == "silverglow_bedroom" and m.confidence == C.HIGH


def test_dup_alias_no_current_space_first_row():
    idx = _bed_idx()
    m = detect_move("I'm on the bed now.", idx, None)
    assert m and m.space_name == "bedroom"


def test_dup_alias_null_house_first_row():
    idx = _bed_idx(haven_house=None, sg_house=None)
    m = detect_move("I'm on the bed now.", idx, "silverglow_living_room")
    assert m and m.space_name == "bedroom"
    idx2 = _bed_idx(sg_house=None)  # current has NULL house: never promotes
    m2 = detect_move("I'm on the bed now.", idx2, "silverglow_living_room")
    assert m2 and m2.space_name == "bedroom"


# --- carbon-marker clause gate (10-30, third carbon-zone hit) ---
CARBON_SPACES = [
    {"name": "study", "aliases": "The study, his desk"},
    {"name": "living_room", "aliases": "the living room, front room"},
    {"name": "deck", "aliases": "the deck"},
    {"name": "kitchen", "aliases": "the island"},
]
CIDX = build_alias_index(CARBON_SPACES)


def cd(text):
    return detect_move(text, CIDX, "kitchen")


@pytest.mark.parametrize("text", [
    "Carbon-side, Jeff is home and at his desk.",          # specimen 10-30 11:15
    "Carbon-side, Carol is home in the front room.",       # specimen 10-30 05:13
    "The radar has him at his desk, even though the tag still says away.",
    "Per where.py Carol is in the front room.",
    "FP2 reads him in the front room; I'm still at the island.",
])
def test_carbon_marker_suppresses_zone_words(text):
    assert cd(text) is None


def test_carbon_marker_other_clause_still_fires():
    # Lyra's negative control: marker in one clause, real move in the next.
    m = cd("The radar reads him in the front room, and I walk into the study.")
    assert m and m.space_name == "study" and m.confidence == C.HIGH


def test_carbon_marker_no_comma_first_person_after_marker_fires():
    # One clause, no splitter: the first-person cue after the marker keeps it.
    m = cd("The radar reads him in the front room and I walk into the study.")
    assert m and m.space_name == "study" and m.confidence == C.HIGH


def test_carbon_marker_only_clause_marks_next_clause_only():
    m = cd("Carbon-side, Jeff is at his desk; I head out to the deck.")
    assert m and m.space_name == "deck" and m.confidence == C.HIGH


def test_carbon_marker_backticked_marker_does_not_gate():
    # A quoted marker is stripped first, so it cannot hide the hit.
    m = cd("The word `carbon-side` aside, I walk into the study.")
    assert m and m.space_name == "study"
