"""Suite-wide guards.

ENTITY_PATH is the InventoryLayer's default mirror root. A test that builds the
layer without entity_path would otherwise write mirror fixtures into the REAL
entity directory (it did: nine orphan room files on 2026-10-25, eleven on
2026-09-15), and since ce28257 an orphan mirror can become a room. Point the
env at a throwaway dir for every test.
"""
import pytest


@pytest.fixture(autouse=True)
def _entity_path_is_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("ENTITY_PATH", str(tmp_path / "entity"))
    yield
