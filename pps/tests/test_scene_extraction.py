#!/usr/bin/env python3
"""
Tests for the [scene] line in ambient_recall (Issue #256).

The scene-extraction logic in server_http.py (the ambient_recall handler,
just after the [location] line) reads the entity's current_scene.md and
surfaces the first prose sentence as a short narrative-location line.

Per the project's established pattern for testing server_http helpers
(see test_truncation.py's TestTruncateWithFollowonUnit), the logic is
mirrored here as a pure function rather than importing the heavy FastAPI
module. If you change the extraction in server_http.py, mirror it here.

Run:
  /mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python3 \
      -m pytest pps/tests/test_scene_extraction.py -v
"""
from pathlib import Path

import pytest


def extract_scene(content: str) -> str:
    """Mirror of the extraction in server_http.py's ambient_recall handler.

    Skips blank lines and markdown headers; takes the first prose line,
    truncated to its first sentence (split on ". ") and ≤200 chars.
    Returns "" if no prose is found (all headers/blank).
    """
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ". " in stripped:
            scene_text = stripped.split(". ", 1)[0] + "."
        else:
            scene_text = stripped
        if len(scene_text) > 200:
            scene_text = scene_text[:200] + "…"
        return scene_text
    return ""


# --- Deterministic synthetic cases (the real contract) ---------------------

def test_prose_no_header():
    assert extract_scene("Some prose sentence. More text here.") == "Some prose sentence."


def test_header_then_prose():
    assert extract_scene("# Current Scene\n\nProse here. More.") == "Prose here."


def test_multiple_headers_before_prose():
    content = "# Header 1\n## Header 2\n\n\nFinally prose. More text."
    assert extract_scene(content) == "Finally prose."


def test_empty_file():
    assert extract_scene("") == ""


def test_header_only():
    assert extract_scene("# Header\n\n") == ""


def test_no_period_space():
    # No ". " present → take whole line.
    assert extract_scene("No period space sentence") == "No period space sentence"


def test_truncation():
    result = extract_scene(("A" * 250) + ". rest")
    assert result.endswith("…")
    assert len(result) == 201  # 200 chars + ellipsis


def test_em_dash_location_phrase_survives():
    # The scene convention leads with "<time> — <place>, <rest>." — the whole
    # first sentence (incl. the place) should be surfaced.
    content = "Monday night, ~10:45 PM — our bedroom, on the night-watch. Jeff asleep."
    assert extract_scene(content) == "Monday night, ~10:45 PM — our bedroom, on the night-watch."


# --- Real-file smoke (loose: must not crash, returns a sane str) -----------
# current_scene.md is mutable, so we assert SHAPE not content.

_ROOT = Path("/mnt/c/Users/Jeff/Claude_Projects/Awareness")


@pytest.mark.parametrize("entity", ["lyra", "caia"])
def test_real_scene_file_is_sane(entity):
    scene_file = _ROOT / "entities" / entity / "current_scene.md"
    if not scene_file.exists():
        pytest.skip(f"{entity} scene file absent")
    result = extract_scene(scene_file.read_text(encoding="utf-8"))
    assert isinstance(result, str)
    assert len(result) <= 201
    assert not result.startswith("#")
