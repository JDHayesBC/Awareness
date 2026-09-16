"""Tests for scripts/light_journal.py — the append-only record of what each bulb said.

These exist because the module's entire value is *being right about what a colour was*,
and because a test suite that lives only in a scratchpad guards nothing in this tree
(Caia's review, 2026-09-16).

The load-bearing cases, in order of how much they'd cost to get wrong:

* ``record`` NEVER raises — it's called from the send path, and a journal that can break
  a light is worse than no journal.
* ``is_novel`` returns None for genuine ignorance (empty journal) but a real answer for
  an uncatalogued colour — keying novelty on the base NAME rather than the sent VALUES
  was the manufactured-ignorance bug.
* ``resolve_base`` never snaps an unknown colour to the nearest familiar name.
* the palette is imported, not retyped, so the two tables cannot drift apart.
"""

import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import light_journal as lj          # noqa: E402
import light_palette as lp          # noqa: E402


@pytest.fixture
def journal(tmp_path, monkeypatch):
    """Point the journal at a temp tree so tests never touch a real entity's river."""
    monkeypatch.setattr(lj, "_REPO_ROOT", tmp_path)
    return tmp_path / "entities" / "testent" / "light_journal.jsonl"


# ---------------------------------------------------------------- resolve_base

def test_resolves_known_rgb_bases():
    assert lj.resolve_base("rgb", [3, 74, 252]) == "cobalt"
    assert lj.resolve_base("rgb", [252, 215, 3]) == "gold"


def test_resolves_known_rgbww_and_temp_and_off():
    assert lj.resolve_base("rgbww", [255, 130, 165, 100, 80]) == "soft-pink"
    assert lj.resolve_base("color_temp", 4115) == "pearl-white"
    assert lj.resolve_base("off", None) == "off"


def test_unknown_colour_is_not_snapped_to_nearest():
    """An uncatalogued colour must stay uncatalogued. This is the August case."""
    assert lj.resolve_base("rgb", [5, 76, 250]) is None      # a near-miss on cobalt
    assert lj.resolve_base("rgb", [17, 200, 90]) is None
    assert lj.resolve_base("color_temp", 2700) is None


def test_garbage_values_resolve_to_none_without_raising():
    assert lj.resolve_base("rgb", ["x", "y", "z"]) is None
    assert lj.resolve_base("rgb", None) is None


# ---------------------------------------------------------------------- record

def test_record_writes_one_line_with_meaning_inline(journal):
    assert lj.record("rgb", [3, 74, 252], 90, entity="testent", source="t") is True
    entries = [json.loads(x) for x in journal.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["base"] == "cobalt"
    assert "I need you" in entries[0]["meaning"]
    assert entries[0]["values"] == [3, 74, 252]


def test_record_stores_unrecognized_base_as_null_but_keeps_values(journal):
    lj.record("rgb", [17, 200, 90], 40, entity="testent")
    e = json.loads(journal.read_text().strip())
    assert e["base"] is None and e["meaning"] is None
    assert e["values"] == [17, 200, 90]      # the answer survives even unnamed


def test_record_never_raises_on_garbage(journal):
    assert lj.record("rgb", object(), entity="testent") is False


def test_record_never_raises_when_path_unwritable(tmp_path, monkeypatch):
    """The bulb always wins. An unwritable journal is silent, not fatal."""
    monkeypatch.setattr(lj, "_REPO_ROOT", tmp_path / "nope")
    monkeypatch.setattr(lj, "journal_path", lambda e=None: tmp_path / "nope" / "x.jsonl")
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
    assert lj.record("rgb", [3, 74, 252], entity="testent") is False


def test_record_is_per_entity_never_pooled(tmp_path, monkeypatch):
    monkeypatch.setattr(lj, "_REPO_ROOT", tmp_path)
    lj.record("rgb", [252, 215, 3], entity="ent_a")
    lj.record("rgb", [3, 74, 252], entity="ent_b")
    assert len(lj.read("ent_a")) == 1
    assert lj.read("ent_a")[0]["base"] == "gold"
    assert lj.read("ent_b")[0]["base"] == "cobalt"


# ------------------------------------------------------------------------ read

def test_read_skips_malformed_lines_without_dying(journal):
    journal.parent.mkdir(parents=True)
    journal.write_text(
        json.dumps({"base": "gold"}) + "\n"
        + "{ this is not json\n"
        + json.dumps({"base": "cobalt"}) + "\n"
    )
    got = lj.read("testent")
    assert [e["base"] for e in got] == ["gold", "cobalt"]


def test_read_missing_file_is_empty_not_error(journal):
    assert lj.read("testent") == []


# -------------------------------------------------------------------- is_novel

def test_empty_journal_returns_none_not_true(journal):
    """Everything looks novel in an empty room — that's ignorance, not novelty."""
    assert lj.is_novel("rgb", [3, 74, 252], entity="testent") is None


def test_novelty_is_answerable_for_an_uncatalogued_colour(journal):
    """The fix for the manufactured-ignorance bug: key on values, not the base name.

    An off-palette colour has no base name, but 'have I sent this before?' is still
    perfectly answerable — and it is exactly the question August raised.
    """
    lj.record("rgb", [252, 215, 3], entity="testent")        # some history exists
    assert lj.is_novel("rgb", [17, 200, 90], entity="testent") is True
    lj.record("rgb", [17, 200, 90], entity="testent")
    assert lj.is_novel("rgb", [17, 200, 90], entity="testent") is False


def test_known_colour_novelty_round_trip(journal):
    lj.record("rgb", [252, 215, 3], entity="testent")
    assert lj.is_novel("rgb", [252, 215, 3], entity="testent") is False
    assert lj.is_novel("rgb", [3, 74, 252], entity="testent") is True


def test_pink_and_cobalt_are_distinguishable(journal):
    """The whole point. These two mean very different things and must never merge."""
    lj.record("rgbww", [255, 130, 165, 100, 80], entity="testent")
    assert lj.is_novel("rgbww", [255, 130, 165, 100, 80], entity="testent") is False
    assert lj.is_novel("rgb", [3, 74, 252], entity="testent") is True


def test_unkeyable_values_return_none(journal):
    lj.record("rgb", [252, 215, 3], entity="testent")
    assert lj.is_novel("rgb", object(), entity="testent") is None


def test_modes_do_not_collide(journal):
    lj.record("rgb", [252, 215, 3], entity="testent")
    assert lj.is_novel("css", "gold", entity="testent") is True   # different send form


# ----------------------------------------------------------------- no drift

def test_palette_is_imported_not_retyped():
    """Guards Caia's catch: two hand-maintained copies of the anchors can drift.

    Checked against the AST, not the raw text — a base value quoted in a docstring
    example is prose and cannot go stale in a way that misreports a colour. What must
    never come back is a *literal* in executable code.
    """
    import ast

    src_path = Path(__file__).resolve().parent.parent / "scripts" / "light_journal.py"
    src = src_path.read_text()
    assert "from light_palette import" in src

    known = {tuple(v) for v in lp.PEGGED_BASES.values()}
    known |= {tuple(v) for v in lp.RGBWW_BASES.values()}

    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.List, ast.Tuple)):
            try:
                literal = tuple(ast.literal_eval(node))
            except (ValueError, SyntaxError):
                continue
            assert literal not in known, (
                f"base values {literal} re-typed as a literal in light_journal.py "
                f"(line {node.lineno}) — import from light_palette instead"
            )


def test_light_py_uses_the_shared_palette():
    src = (Path(__file__).resolve().parent.parent / "scripts" / "light.py").read_text()
    assert "light_palette" in src, "light.py still holds its own copy of the anchors"


def test_every_known_base_has_a_meaning():
    for name in list(lp.PEGGED_BASES) + list(lp.RGBWW_BASES):
        assert name in lp.BASE_MEANING


# ------------------------------------------------- every send path is instrumented

SEND_PATHS = ["light.py", "light_send.py", "light_lib.py"]


def test_all_known_send_paths_journal():
    """A send that isn't recorded is indistinguishable from no send at all.

    This is the day's recurring defect shape — one signal standing for two conditions
    that can disagree — so it gets a guard rather than a promise. `light_lib.py` was
    found bypassing the journal *after* the first three files were wired.
    """
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    for name in SEND_PATHS:
        src = (scripts / name).read_text()
        assert "light_journal" in src, f"{name} sends to HA without journaling"


def test_no_unaudited_send_path_exists():
    """Any other file POSTing to light/turn_on must be a known, audited path."""
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    known = set(SEND_PATHS) | {"light_breathe.py"}   # breathe journals the statement
    offenders = []
    for py in scripts.rglob("*.py"):
        src = py.read_text(errors="ignore")
        if "services/light/turn_on" not in src:
            continue
        if py.name in known or "probe" in py.name:
            continue
        if "light_journal" not in src:
            offenders.append(str(py.relative_to(scripts)))
    assert not offenders, f"uninstrumented light send paths: {offenders}"


def test_light_lib_opt_out_is_explicit(journal, monkeypatch):
    """Animation frames may opt out — but only by saying so."""
    import light_lib
    monkeypatch.setattr(light_lib, "_post", lambda *a, **k: 200)
    light_lib.set_light(color="gold", brightness=30, entity="testent", journal=False)
    assert lj.read("testent") == []
    light_lib.set_light(color="gold", brightness=30, entity="testent")
    assert len(lj.read("testent")) == 1


def test_light_lib_records_off_as_a_real_signal(journal, monkeypatch):
    import light_lib
    monkeypatch.setattr(light_lib, "_post", lambda *a, **k: 200)
    light_lib.turn_off(entity="testent")
    e = lj.read("testent")[0]
    assert e["base"] == "off" and "absent" in e["meaning"]
