"""Tests for scripts/arc_check.py: resolving dated checks into the append-only ledger.

Everything runs against temp directories; ARC_ENTITIES_ROOT and ARC_CHECK_LEDGER keep the
real arcs and the real ledger out of reach.
"""
import datetime as dt
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import arc_check  # noqa: E402

TODAY = dt.date(2026, 12, 1)


def _arc(root, entity, slug, **fm):
    d = root / entity / "arcs"
    d.mkdir(parents=True, exist_ok=True)
    fm.setdefault("state", "active")
    body = "\n".join(f"{k}: {v}" for k, v in fm.items())
    (d / f"{slug}.md").write_text(f"---\n{body}\n---\n\n# {slug}\n", encoding="utf-8")
    return d / f"{slug}.md"


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "ents"
    ledger = tmp_path / "ledger" / "arc-checks.jsonl"
    ledger.parent.mkdir()
    monkeypatch.setenv("ARC_ENTITIES_ROOT", str(root))
    monkeypatch.setenv("ARC_CHECK_LEDGER", str(ledger))
    monkeypatch.delenv("ENTITY_NAME", raising=False)
    monkeypatch.delenv("ENTITY_PATH", raising=False)
    arc = _arc(root, "alpha", "demo-arc", check_by="2026-11-20", check_claim="the file exists",
               check_how="ls demo", check_p="70%")
    return root, ledger, arc


def _resolve(**kw):
    args = dict(owner="alpha", slug="demo-arc", outcome="true", evidence="looked: it is there",
                by="beta", today=TODAY)
    args.update(kw)
    return arc_check.resolve(**args)


def _lines(ledger):
    return ledger.read_text().splitlines() if ledger.exists() else []


def test_successful_resolve_appends_exactly_one_full_row(world):
    root, ledger, arc = world
    before = arc.read_text()
    row = _resolve()
    lines = _lines(ledger)
    assert len(lines) == 1
    got = json.loads(lines[0])
    assert got == row
    assert got["kind"] == "resolved" and got["entity"] == "alpha" and got["slug"] == "demo-arc"
    assert got["check_by"] == "2026-11-20" and got["claim"] == "the file exists"
    assert got["how"] == "ls demo" and got["p"] == pytest.approx(0.7)
    assert got["outcome"] == "true" and got["resolved_by"] == "beta"
    assert got["self_checked"] is False and got["early"] is False
    assert got["evidence"] == "looked: it is there"
    assert dt.datetime.fromisoformat(got["resolved_at"]).utcoffset() is not None
    assert arc.read_text() == before  # never touches the arc file


def test_second_attempt_is_refused_and_writes_nothing(world):
    _, ledger, _ = world
    _resolve()
    with pytest.raises(arc_check.Refusal, match="already has a resolution"):
        _resolve(outcome="false")
    assert len(_lines(ledger)) == 1


def test_a_new_check_date_on_the_same_arc_is_a_new_key(world):
    root, ledger, _ = world
    _resolve()
    _arc(root, "alpha", "demo-arc", check_by="2026-11-25", check_claim="next claim")
    _resolve()
    assert len(_lines(ledger)) == 2


@pytest.mark.parametrize("kw,match", [
    ({"slug": "missing"}, "no arc file"),
    ({"evidence": "   "}, "evidence"),
    ({"by": "alpha"}, "owner is resolving"),
    ({"today": dt.date(2026, 11, 19)}, "not reached yet"),
    ({"slug": "../alpha/demo-arc"}, "bad owner/slug"),
    ({"outcome": "maybe"}, "outcome"),
])
def test_refusals_write_nothing(world, kw, match):
    _, ledger, _ = world
    with pytest.raises(arc_check.Refusal, match=match):
        _resolve(**kw)
    assert _lines(ledger) == [] and not ledger.exists()


def test_no_well_formed_check_is_refused(world):
    root, ledger, _ = world
    _arc(root, "alpha", "no-check")
    _arc(root, "alpha", "half", check_by="2026-11-20")
    for slug in ("no-check", "half"):
        with pytest.raises(arc_check.Refusal, match="no well-formed check"):
            _resolve(slug=slug)
    assert not ledger.exists()


def test_missing_ledger_directory_is_refused_and_not_created(world, monkeypatch, tmp_path):
    monkeypatch.setenv("ARC_CHECK_LEDGER", str(tmp_path / "nope" / "l.jsonl"))
    with pytest.raises(arc_check.Refusal, match="ledger directory"):
        _resolve()
    assert not (tmp_path / "nope").exists()


def test_self_checked_and_early_are_recorded(world):
    row = _resolve(by="alpha", self_checked=True, today=dt.date(2026, 11, 1), early=True)
    assert row["self_checked"] is True and row["early"] is True


def test_early_flag_on_a_date_that_has_passed_is_not_recorded_as_early(world):
    assert _resolve(early=True)["early"] is False


def test_resolver_name_falls_back_to_env(world, monkeypatch):
    monkeypatch.setenv("ENTITY_NAME", "Beta")
    assert _resolve(by=None)["resolved_by"] == "beta"
    monkeypatch.delenv("ENTITY_NAME")
    _arc(world[0], "alpha", "other", check_by="2026-11-20", check_claim="x")
    monkeypatch.setenv("ENTITY_PATH", "entities/beta")
    assert _resolve(slug="other", by=None)["resolved_by"] == "beta"


def test_no_resolver_name_exits_2(world, capsys):
    _, ledger, _ = world
    code = arc_check.main(["resolve", "alpha", "demo-arc", "true", "--evidence", "x"])
    assert code == 2 and "--by" in capsys.readouterr().err
    assert not ledger.exists()


def test_cli_main_success_and_refusal_exit_codes(world, capsys):
    _, ledger, _ = world
    argv = ["resolve", "alpha", "demo-arc", "false", "--evidence", "gone", "--by", "beta"]
    assert arc_check.main(argv) == 0
    assert arc_check.main(argv) == 2
    assert len(_lines(ledger)) == 1


def test_row_is_appended_after_a_line_missing_its_newline(world):
    _, ledger, _ = world
    ledger.write_text('{"kind": "note"}')  # hand-edited, no trailing newline
    _resolve()
    lines = _lines(ledger)
    assert len(lines) == 2 and json.loads(lines[1])["kind"] == "resolved"


def test_malformed_ledger_lines_are_skipped_when_deciding_openness(world):
    _, ledger, _ = world
    ledger.write_text("garbage\n{\"kind\": \n")
    _resolve()
    assert len(_lines(ledger)) == 3  # nothing was rewritten; the new row went on the end


def test_list_shows_open_checks_and_score(world, capsys):
    root, ledger, _ = world
    _arc(root, "beta", "theirs", check_by="2099-01-01", check_claim="future thing")
    _arc(root, "_template", "tmpl", check_by="2020-01-01", check_claim="template")
    _resolve()
    _arc(root, "alpha", "second", check_by="2026-11-20", check_claim="two")
    _resolve(slug="second", by="alpha", self_checked=True, outcome="void")
    _arc(root, "alpha", "third", check_by="2026-11-20", check_claim="three")
    lines = arc_check.list_checks(TODAY)
    assert any(l.startswith("alpha/third  by 2026-11-20") and l.endswith("(due)") for l in lines)
    assert any(l.startswith("beta/theirs  by 2099-01-01  p=?") for l in lines)
    assert not any("template" in l or "demo-arc" in l for l in lines)
    assert lines[-1] == "resolved 2 · true 1 · false 0 · void 1 · self-checked 1"



def test_by_that_disagrees_with_the_session_is_refused(world, monkeypatch):
    """A lyra session typing --by caia must not turn a self-grade into a cross-check."""
    _, ledger, _ = world
    monkeypatch.setenv("ENTITY_NAME", "alpha")          # the owner's own session
    with pytest.raises(arc_check.Refusal, match="does not match this session"):
        _resolve(by="beta")
    assert not ledger.exists()
    monkeypatch.delenv("ENTITY_NAME")
    monkeypatch.setenv("ENTITY_PATH", "entities/alpha")
    with pytest.raises(arc_check.Refusal, match="does not match this session"):
        _resolve(by="beta")
    assert not ledger.exists()


def test_resolver_source_says_where_the_name_came_from(world, monkeypatch):
    root, _, _ = world
    assert _resolve(by="beta")["resolver_source"] == "flag"     # no session name at all
    _arc(root, "alpha", "two", check_by="2026-11-20", check_claim="two")
    monkeypatch.setenv("ENTITY_NAME", "Beta")
    row = _resolve(slug="two", by=None)
    assert (row["resolved_by"], row["resolver_source"]) == ("beta", "env")
    _arc(root, "alpha", "three", check_by="2026-11-20", check_claim="three")
    row = _resolve(slug="three", by="beta")                     # typed, and it agrees
    assert (row["resolved_by"], row["resolver_source"]) == ("beta", "env")
