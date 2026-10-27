"""Tests for the inventory canonical-store / readable-mirror contract.

Run: pps/venv/bin/python3 -m pytest pps/tests/test_inventory_mirror.py -v
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from layers.inventory import InventoryLayer  # noqa: E402

run = asyncio.run


@pytest.fixture
def inv(tmp_path):
    return InventoryLayer(db_path=tmp_path / "inv.db", entity_path=tmp_path)


def _set(inv, name, **cols):
    with sqlite3.connect(inv.db_path) as c:
        for k, v in cols.items():
            c.execute(f"UPDATE spaces SET {k} = ? WHERE name = ?", (v, name))
        c.commit()


def _row(inv, name):
    with sqlite3.connect(inv.db_path) as c:
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM spaces WHERE name = ?", (name,)).fetchone()
        return dict(r) if r else None


def test_export_roundtrips_aliases_and_house(inv):
    run(inv.add_space("deck", description="The deck."))
    _set(inv, "deck", aliases="porch, back deck", house="cedar")
    inv._export_mirror("spaces", _row(inv, "deck"))
    mf = inv._mirror_path("spaces", "deck")
    text = mf.read_text()
    assert "aliases: porch, back deck" in text
    assert "house: cedar" in text
    fields = inv._import_from_mirror(mf)
    assert fields["aliases"] == "porch, back deck"
    assert fields["house"] == "cedar"

    # Rebuild into a fresh store from the mirror alone.
    inv2 = InventoryLayer(db_path=inv.db_path.parent / "inv2.db", entity_path=inv.entity_path)
    assert run(inv2.import_space_from_file(str(mf)))
    r = _row(inv2, "deck")
    assert r["aliases"] == "porch, back deck" and r["house"] == "cedar"


def test_empty_house_line_omitted_and_no_telemetry(inv):
    run(inv.add_space("deck", description="The deck."))
    run(inv.get_space("deck"))  # bumps visits
    inv._export_mirror("spaces", _row(inv, "deck"))
    text = inv._mirror_path("spaces", "deck").read_text()
    assert "house:" not in text
    for k in ("visit_count", "last_visited", "last_accessed", "visits"):
        assert k not in text


def test_old_format_import_leaves_aliases_house_untouched(inv):
    run(inv.add_space("deck", description="old desc"))
    _set(inv, "deck", aliases="porch", house="cedar")
    old = inv.entity_path / "old_deck.md"
    old.write_text("---\nname: deck\ncategory: spaces\n---\n\nnew body\n")
    assert run(inv.import_space_from_file(str(old)))
    r = _row(inv, "deck")
    assert r["aliases"] == "porch" and r["house"] == "cedar"
    assert r["description"] == "new body"


def test_get_space_missing_row_reads_mirror_without_creating_row(inv):
    mf = inv._mirror_path("spaces", "attic")
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text("---\nname: attic\ncategory: spaces\naliases: loft\nhouse: cedar\n---\n\nDusty.\n")
    got = run(inv.get_space("attic"))
    assert got["description"] == "Dusty."
    assert got["aliases"] == "loft" and got["house"] == "cedar"
    assert _row(inv, "attic") is None
    assert run(inv.get_space("nonexistent")) is None
