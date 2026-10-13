"""Tests for the starving-arc counterweight's classifier.

The counterweight only works if a starving arc can actually reach the block. These
lock the one failure that silently defeated it: a `state:` field is PROSE, and a word
in its narrative tail must not decide the classification.
"""
import sys, pathlib
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from arc_scan import _is_moving, _state_head


def st(state):
    return {"state": state}


# --- the regression ------------------------------------------------------------------

def test_shipping_arc_with_published_in_its_history_still_moves():
    """Foundation Series: state 'shipping', 102 days stale, Article 3 outstanding —
    invisible to the pointer because 'PUBLISHED' appeared later in the same line."""
    assert _is_moving(st("shipping — Articles 1 & 2 PUBLISHED (caia2025): #1 2026-05-23")) is True


def test_a_genuinely_published_arc_does_not_move():
    assert _is_moving(st("PUBLISHED")) is False
    assert _is_moving(st("PUBLISHED 2026-06-05 on caia2025; reposted by Jeff")) is False


def test_head_wins_over_tail_in_both_directions():
    assert _is_moving(st("dormant — was active until 2026-05")) is False
    assert _is_moving(st("active — dormant through the summer, picked back up")) is True


# --- head parsing --------------------------------------------------------------------

def test_state_head_splits_on_emdash_colon_and_paren():
    assert _state_head("shipping — Articles 1 & 2 PUBLISHED") == "shipping"
    assert _state_head("active: the build") == "active"
    assert _state_head("active (with Lyra)") == "active"


def test_state_head_does_not_split_on_plain_hyphen():
    """Hyphens are load-bearing inside real state names."""
    assert _state_head("active-strategic-P0") == "active-strategic-p0"
    assert _state_head("write-when-whim") == "write-when-whim"


def test_hyphenated_states_classify_as_before():
    assert _is_moving(st("active-strategic-P0")) is True
    assert _is_moving(st("write-when-whim")) is False


def test_empty_state_is_not_moving():
    assert _is_moving(st("")) is False
    assert _is_moving({}) is False


# --- fallback and precedence ---------------------------------------------------------

def test_silent_head_falls_back_to_the_full_string():
    """A head that names no known state shouldn't blank the arc — read the rest."""
    assert _is_moving(st("v0.3 — active build")) is True
    assert _is_moving(st("v0.3 — archived")) is False


def test_explicit_needs_attention_field_still_wins_outright():
    """Lyra's convention is verbatim and must not be second-guessed by the heuristic."""
    assert _is_moving({"needs_attention": "true", "state": "PUBLISHED"}) is True
    assert _is_moving({"needs_attention": "false", "state": "active"}) is False


def test_known_moving_states_all_still_move():
    for s in ("active", "shipping", "meta", "active-P0", "needs attention", "load-bearing"):
        assert _is_moving(st(s)) is True, s


def test_known_not_moving_states_all_still_rest():
    for s in ("dormant", "archived", "legacy", "complete", "outline", "published"):
        assert _is_moving(st(s)) is False, s


# --- blindness must not look like calm ------------------------------------------------

def test_a_crashed_scan_says_so_instead_of_rendering_silence(monkeypatch):
    """Silence in this block means "nothing starving". A crash that ALSO renders as
    silence is a lie in the one direction nobody checks: a broken sense is
    indistinguishable from a tended board. The hook must survive — but it must say so."""
    import arc_scan
    monkeypatch.setattr(arc_scan, "_resolve_arcs_dir",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk on fire")))
    out = arc_scan.format_arc_block()
    assert out != ""
    assert "BLIND" in out and "RuntimeError" in out


def test_a_healthy_scan_with_nothing_starving_is_still_silent(tmp_path, monkeypatch):
    """The fix must not make the block chatty — empty-when-served is the design."""
    import arc_scan, datetime as dt
    (tmp_path / "a.md").write_text(
        "---\ntitle: Fresh\nstate: active\nlast_touched: "
        f"{dt.date.today().isoformat()}\n---\n\n# Fresh\n")
    monkeypatch.setattr(arc_scan, "_resolve_arcs_dir", lambda *a, **k: tmp_path)
    assert arc_scan.format_arc_block() == ""


# --- ARC_DIR: arcs kept outside entities/ ----------------------------------------------

def _arc(path, slug, touched, flag="true"):
    (path / f"{slug}.md").write_text(
        f"---\ntitle: {slug}\nstate: active\nneeds_attention: {flag}\n"
        f"last_touched: {touched}\n---\n\n# {slug}\n\n## Open Threads\n- do the thing\n",
        encoding="utf-8")


def test_arc_dir_env_points_the_scan_outside_entities(tmp_path, monkeypatch):
    """An entity whose arcs live beside her runtime state, not under entities/, sets ARC_DIR."""
    import arc_scan, datetime as dt
    _arc(tmp_path, "starving", (dt.date.today() - dt.timedelta(days=30)).isoformat())
    monkeypatch.delenv("ENTITY_NAME", raising=False)
    monkeypatch.setenv("ARC_DIR", str(tmp_path))
    assert arc_scan._resolve_arcs_dir(None) == tmp_path
    out = arc_scan.format_arc_block()
    assert "starving" in out and "30d" in out and "do the thing" in out


def test_explicit_entity_still_beats_arc_dir(tmp_path, monkeypatch):
    import arc_scan
    monkeypatch.setenv("ARC_DIR", str(tmp_path))
    assert arc_scan._resolve_arcs_dir("caia") == arc_scan.PROJECT_ROOT / "entities" / "caia" / "arcs"


def test_more_hint_names_arc_dir_when_that_is_what_found_them(tmp_path, monkeypatch):
    """The '+N more' hint is a command to run; it must reproduce the scan that produced it."""
    import arc_scan, datetime as dt
    old = (dt.date.today() - dt.timedelta(days=20)).isoformat()
    _arc(tmp_path, "one", old)
    _arc(tmp_path, "two", old)
    monkeypatch.delenv("ENTITY_NAME", raising=False)
    monkeypatch.setenv("ARC_DIR", str(tmp_path))
    out = arc_scan.format_arc_block()
    assert f"ARC_DIR={tmp_path}" in out and "--top 2" in out
