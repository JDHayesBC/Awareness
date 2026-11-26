"""Tests for the starving-arc counterweight's classifier.

The counterweight only works if a starving arc can actually reach the block. These
lock the one failure that silently defeated it: a `state:` field is PROSE, and a word
in its narrative tail must not decide the classification.
"""
import sys, pathlib
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from arc_scan import _is_moving, _state_head


@pytest.fixture(autouse=True)
def _hermetic_checks(tmp_path_factory, monkeypatch):
    """Dated checks read sibling entities and a ledger; keep every test off the real ones."""
    base = tmp_path_factory.mktemp("hermetic")
    monkeypatch.setenv("ARC_ENTITIES_ROOT", str(base / "entities"))
    monkeypatch.setenv("ARC_CHECK_LEDGER", str(base / "ledger.jsonl"))


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


# --- dated checks ----------------------------------------------------------------------

import datetime as dt
import json

TODAY = dt.date(2026, 12, 1)


def _write_arc(root, entity, slug, **fm):
    """Write <root>/<entity>/arcs/<slug>.md from flat frontmatter keys."""
    d = root / entity / "arcs"
    d.mkdir(parents=True, exist_ok=True)
    fm.setdefault("state", "active")
    fm.setdefault("last_touched", TODAY.isoformat())
    body = "\n".join(f"{k}: {v}" for k, v in fm.items())
    (d / f"{slug}.md").write_text(f"---\n{body}\n---\n\n# {slug}\n", encoding="utf-8")
    return d


def _chk(by, claim="the file exists", how="ls demo", p="0.7"):
    return {"check_by": by, "check_claim": claim, "check_how": how, "check_p": p}


def _resolved(entity, slug, by):
    return json.dumps({"kind": "resolved", "entity": entity, "slug": slug, "check_by": by}) + "\n"


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "ents"
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("ARC_ENTITIES_ROOT", str(root))
    monkeypatch.setenv("ARC_CHECK_LEDGER", str(ledger))
    monkeypatch.delenv("ARC_DIR", raising=False)
    monkeypatch.setenv("ENTITY_NAME", "alpha")
    import arc_scan
    # an explicit entity normally resolves under the real repo; point it at the temp root
    monkeypatch.setattr(arc_scan, "_resolve_arcs_dir",
                        lambda entity=None: root / (entity or "alpha") / "arcs")
    return root, ledger


def _report(root, entity="alpha"):
    import arc_scan
    rows = arc_scan.scan(root / entity / "arcs", TODAY)
    return arc_scan.check_report(entity, rows, TODAY, root)


@pytest.mark.parametrize("raw,want", [("0.7", 0.7), ("70%", 0.7), ("70", 0.7), ("1", 1.0),
                                      ("0", 0.0), (" 50 % ", 0.5)])
def test_p_parses_three_forms(raw, want):
    import arc_scan
    assert arc_scan.parse_check_p(raw) == pytest.approx(want)


@pytest.mark.parametrize("raw", ["", None, "maybe", "1.5", "150", "-3", "0.7 or so", "7e-1"])
def test_p_garbage_is_none(raw):
    import arc_scan
    assert arc_scan.parse_check_p(raw) is None


def test_check_due_vs_not_due(world):
    root, _ = world
    _write_arc(root, "beta", "later", **_chk("2026-12-02"))
    _write_arc(root, "beta", "today", **_chk("2026-12-01"))
    _write_arc(root, "beta", "past", **_chk("2026-11-20"))
    # due means today >= check_by; oldest first
    assert [c["slug"] for c in _report(root)["owed"]] == ["past", "today"]


def test_open_vs_resolved(world):
    root, ledger = world
    _write_arc(root, "beta", "demo-arc", **_chk("2026-11-20"))
    assert [c["slug"] for c in _report(root)["owed"]] == ["demo-arc"]
    ledger.write_text(_resolved("beta", "demo-arc", "2026-11-20"))
    assert _report(root)["owed"] == []
    # a resolution for a DIFFERENT date does not close this one
    ledger.write_text(_resolved("beta", "demo-arc", "2026-11-19"))
    assert len(_report(root)["owed"]) == 1


def test_malformed_ledger_lines_are_skipped(world):
    import arc_scan
    root, ledger = world
    _write_arc(root, "beta", "demo-arc", **_chk("2026-11-20"))
    ledger.write_text("not json\n[1, 2]\n{\"kind\": \n\n" + _resolved("beta", "demo-arc", "2026-11-20"))
    assert len(arc_scan.read_ledger(ledger)) == 1
    assert _report(root)["owed"] == []


def test_missing_ledger_means_no_resolutions(world):
    import arc_scan
    _, ledger = world
    assert not ledger.exists() and arc_scan.read_ledger(ledger) == []


def test_other_entitys_due_check_is_owed_and_own_is_awaiting(world):
    root, _ = world
    _write_arc(root, "beta", "theirs", **_chk("2026-11-25", claim="beta claim"))
    _write_arc(root, "alpha", "mine", **_chk("2026-11-28", claim="alpha claim"))
    _write_arc(root, "_template", "tmpl", **_chk("2026-01-01"))
    rep = _report(root)
    assert [(c["owner"], c["slug"]) for c in rep["owed"]] == [("beta", "theirs")]
    assert [c["slug"] for c in rep["awaiting"]] == ["mine"]
    rep_b = _report(root, "beta")  # the mirror image, from beta's side
    assert [c["slug"] for c in rep_b["owed"]] == ["mine"]
    assert [c["slug"] for c in rep_b["awaiting"]] == ["theirs"]


def test_parked_arc_with_passed_check_stays_out_of_starving_and_is_reported(world, capsys):
    import arc_scan
    root, _ = world
    old = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    _write_arc(root, "alpha", "napping", last_touched=old, needs_attention="true",
               blocked_on="waiting for the parts", **_chk("2020-11-01"))
    _write_arc(root, "beta", "theirs-parked", state="parked", parked_reason="paused",
               **_chk("2020-11-01"))
    rep = _report(root)
    assert [c["slug"] for c in rep["parked_overdue"]] == ["napping"]
    assert rep["awaiting"] == []
    assert [(c["slug"], c["parked"]) for c in rep["owed"]] == [("theirs-parked", True)]
    out = arc_scan.format_arc_block("alpha", TODAY)
    assert "most-starved" not in out and "beta/theirs-parked (parked arc) (by " in out
    assert arc_scan.main(["--entity", "alpha"]) == 0
    cli = capsys.readouterr().out
    assert "check overdue on a parked arc: napping" in cli
    assert "(parked arc)" in cli and "STARVING ARCS" not in cli


def test_complaint_lists_only_active_non_orientational_unparked_without_open_check(world, capsys):
    import arc_scan
    root, _ = world
    _write_arc(root, "alpha", "bare-active")
    _write_arc(root, "alpha", "has-future", **_chk("2099-01-01"))
    _write_arc(root, "alpha", "root-arc", kind="orientational")
    _write_arc(root, "alpha", "dormant-arc", state="dormant")
    _write_arc(root, "alpha", "emerging-arc", state="emerging")
    _write_arc(root, "alpha", "parked-arc", parked="true", parked_reason="why")
    _write_arc(root, "alpha", "broken", check_claim="")
    assert _report(root)["no_check"] == ["bare-active"]
    assert arc_scan.main(["--entity", "alpha"]) == 0
    out = capsys.readouterr().out
    assert "1 active arcs without a dated check: bare-active" in out
    assert "malformed check: broken (check_by missing or not a date; check_claim empty)" in out
    assert out.rstrip().splitlines()[-1].startswith("1 active arcs")


def test_resolved_arc_counts_as_having_no_open_check(world):
    root, ledger = world
    _write_arc(root, "alpha", "done", **_chk("2026-11-01"))
    ledger.write_text(_resolved("alpha", "done", "2026-11-01"))
    assert _report(root)["no_check"] == ["done"]


@pytest.mark.parametrize("fm,reason", [
    ({"check_by": "someday", "check_claim": "x"}, "check_by missing or not a date"),
    ({"check_by": "2026-12-01", "check_claim": ""}, "check_claim empty"),
    ({"check_p": "0.5"}, "check_by missing or not a date; check_claim empty"),
])
def test_malformed_check_is_named_with_a_reason(world, fm, reason):
    root, _ = world
    _write_arc(root, "alpha", "wonky", **fm)
    assert _report(root)["malformed"] == [("wonky", reason)]


def test_cli_sections_and_hint(world):
    import arc_scan
    root, _ = world
    _write_arc(root, "beta", "theirs", **_chk("2026-11-28", claim="beta claim", how="cat x", p="40%"))
    _write_arc(root, "alpha", "mine", **_chk("2026-11-30", claim="alpha claim", p="junk"))
    text = "\n".join(arc_scan._check_sections(_report(root), TODAY))
    assert text.index("DATED CHECKS DUE — yours to resolve:") < text.index("YOUR CHECKS AWAITING")
    assert "beta/theirs  by 2026-11-28 (3d overdue)  p=0.4  — beta claim  · how: cat x" in text
    assert "mine  by 2026-11-30 (1d overdue)  p=?  — alpha claim" in text
    assert text.count("arc_check.py resolve") == 1
    empty = {"owed": [], "awaiting": [], "parked_overdue": [], "malformed": [], "no_check": []}
    assert arc_scan._check_sections(empty, TODAY) == []


def test_block_is_empty_when_nothing_due_or_starving(world):
    import arc_scan
    root, _ = world
    _write_arc(root, "alpha", "fresh", **_chk("2099-01-01"))
    _write_arc(root, "beta", "later", **_chk("2099-01-01"))
    assert arc_scan.format_arc_block("alpha", TODAY) == ""


def test_block_puts_the_owed_check_first_naming_the_oldest(world):
    import arc_scan
    root, _ = world
    old = (TODAY - dt.timedelta(days=30)).isoformat()
    _write_arc(root, "alpha", "starved", last_touched=old, needs_attention="true")
    _write_arc(root, "beta", "newer", **_chk("2026-11-28"))
    _write_arc(root, "beta", "oldest", **_chk("2026-11-10", claim="c" * 300))
    lines = arc_scan.format_arc_block("alpha", TODAY).split("\n")
    assert lines[0].startswith(
        "**[arcs] 🔴 dated check due, yours to resolve: beta/oldest (by 2026-11-10): ")
    assert "c" * 140 not in lines[0] and "…" in lines[0]
    assert lines[0].endswith('Resolve: python3 scripts/arc_check.py resolve beta oldest '
                             'true|false|void --evidence "..." (+1 more)')
    assert "most-starved commitment: starved" in lines[1]


def test_block_awaiting_suffix_on_starving_line_or_alone(world):
    import arc_scan
    root, _ = world
    _write_arc(root, "alpha", "mine", **_chk("2026-11-28"))
    assert arc_scan.format_arc_block("alpha", TODAY) == \
        "**[arcs]** your check on mine is due and awaits resolution"
    old = (TODAY - dt.timedelta(days=30)).isoformat()
    _write_arc(root, "alpha", "starved", last_touched=old, needs_attention="true")
    _write_arc(root, "alpha", "starved2", last_touched=old, needs_attention="true")
    lines = arc_scan.format_arc_block("alpha", TODAY).split("\n")
    assert lines[0].endswith(" · your check on mine is due and awaits resolution")
    assert "(+1 more moving arc(s)" in lines[1]


def test_block_keeps_the_starving_line_and_says_it_is_blind_when_the_ledger_read_raises(
        world, monkeypatch):
    import arc_scan
    root, _ = world
    old = (TODAY - dt.timedelta(days=30)).isoformat()
    _write_arc(root, "alpha", "starved", last_touched=old, needs_attention="true")
    _write_arc(root, "beta", "theirs", **_chk("2026-11-10"))
    with_checks = arc_scan.format_arc_block("alpha", TODAY)
    assert "dated check due" in with_checks
    monkeypatch.setattr(arc_scan, "read_ledger",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("ledger on fire")))
    out = arc_scan.format_arc_block("alpha", TODAY)
    starving, blind = out.split("\n", 1)
    assert starving == with_checks.split("\n", 1)[1]  # the starving line survives untouched
    # A failed read must not look like "no check is due": it says so and names the cause.
    assert "dated checks unreadable" in blind and "ledger on fire" in blind
    assert "dated check due" not in out and "BLIND" not in out
    (root / "alpha" / "arcs" / "starved.md").unlink()
    alone = arc_scan.format_arc_block("alpha", TODAY)
    assert alone.startswith("**[arcs]") and "dated checks unreadable" in alone
    assert "\n" not in alone



def test_block_reports_an_own_malformed_check_and_not_a_siblings(world):
    """A mistyped check must not vanish from the surface that is read every tick."""
    import arc_scan
    root, _ = world
    _write_arc(root, "alpha", "wonky", check_by="2026-11-20")       # no claim
    _write_arc(root, "beta", "their-typo", check_by="2026-11-20")   # hers to see, not mine
    out = arc_scan.format_arc_block("alpha", TODAY)
    assert out == ("**[arcs] ⚠ your check on wonky is malformed (check_claim empty) "
                   "and will not surface**")
    _write_arc(root, "alpha", "zany", check_claim="a claim with no date")
    out = arc_scan.format_arc_block("alpha", TODAY)
    assert "your check on wonky is malformed" in out and "(+1 more)" in out
    assert "their-typo" not in out


def test_block_puts_the_malformed_line_between_the_owed_and_the_starving_lines(world):
    import arc_scan
    root, _ = world
    old = (TODAY - dt.timedelta(days=30)).isoformat()
    _write_arc(root, "alpha", "starved", last_touched=old, needs_attention="true")
    _write_arc(root, "alpha", "wonky", check_by="not a date", check_claim="x")
    _write_arc(root, "beta", "theirs", **_chk("2026-11-10"))
    lines = arc_scan.format_arc_block("alpha", TODAY).split("\n")
    assert "yours to resolve: beta/theirs (by 2026-11-10)" in lines[0]
    assert "your check on wonky is malformed (check_by missing or not a date)" in lines[1]
    assert "most-starved commitment: starved" in lines[2]


# --- WAITING ON: who each parked arc is waiting for -------------------------------------

@pytest.mark.parametrize("raw,names,reason", [
    ("Jeff: fifteen minutes on the deck", ["Jeff"], "fifteen minutes on the deck"),
    ("Jeff and Caia: the re-root decision", ["Jeff", "Caia"], "the re-root decision"),
    ("Jeff, Caia & Nexus: x", ["Jeff", "Caia", "Nexus"], "x"),
    ("jeff + Jeff: x", ["jeff"], "x"),
    ("Sandy: x", ["Sandy"], "x"),
    ("Jeff AND Caia: x", ["Jeff", "Caia"], "x"),
    ("waiting for the rebuild", [], "waiting for the rebuild"),
    ("2026-12-01: after the reset", [], "2026-12-01: after the reset"),
    ("", [], ""),
    ("   ", [], ""),
])
def test_parse_waiting(raw, names, reason):
    import arc_scan
    assert arc_scan.parse_waiting(raw) == (names, reason)


def test_parse_waiting_long_head_is_all_reason():
    import arc_scan
    v = "x" * 41 + ": reason"
    assert arc_scan.parse_waiting(v) == ([], v)


def _waiting_dir(tmp_path, monkeypatch, **arcs):
    """arcs: slug -> frontmatter body text. ARC_DIR points at the temp folder."""
    for slug, body in arcs.items():
        (tmp_path / f"{slug}.md").write_text(f"---\n{body}\n---\n\n# {slug}\n", encoding="utf-8")
    monkeypatch.delenv("ENTITY_NAME", raising=False)
    monkeypatch.setenv("ARC_DIR", str(tmp_path))


def test_cli_lists_a_minimal_blocked_on_arc(tmp_path, monkeypatch, capsys):
    import arc_scan
    _waiting_dir(tmp_path, monkeypatch, minimal="blocked_on: Jeff: fifteen minutes")
    assert arc_scan.main([]) == 0
    lines = capsys.readouterr().out.splitlines()
    i = next(n for n, l in enumerate(lines) if "WAITING ON" in l)
    assert lines[i + 1].strip() == "Jeff"
    assert "minimal" in lines[i + 2] and "date unknown" in lines[i + 2]
    assert "fifteen minutes" in lines[i + 2]


def test_minimal_blocked_on_arc_is_neither_starving_nor_unchecked(tmp_path, monkeypatch, capsys):
    import arc_scan
    _waiting_dir(tmp_path, monkeypatch, minimal="blocked_on: Jeff: fifteen minutes")
    arc_scan.main([])
    out = capsys.readouterr().out
    assert "STARVING ARCS" not in out and "without a dated check" not in out


def test_cli_without_blocked_on_has_no_waiting_heading(tmp_path, monkeypatch, capsys):
    import arc_scan
    _waiting_dir(tmp_path, monkeypatch, plain="state: active\nlast_touched: 2020-01-01")
    assert arc_scan.main([]) == 0
    assert "WAITING ON" not in capsys.readouterr().out


def test_arc_waiting_on_two_names_is_listed_under_both(tmp_path, monkeypatch, capsys):
    import arc_scan
    _waiting_dir(tmp_path, monkeypatch, duo="blocked_on: Jeff and Caia: the decision")
    arc_scan.main([])
    lines = capsys.readouterr().out.splitlines()
    i = next(n for n, l in enumerate(lines) if "WAITING ON" in l)
    assert [l.strip() for l in lines[i + 1:i + 5:2]] == ["Caia", "Jeff"]
    assert "duo" in lines[i + 2] and "duo" in lines[i + 4]


def test_waiting_groups_order_and_no_name_last(tmp_path, monkeypatch):
    import arc_scan
    _waiting_dir(
        tmp_path, monkeypatch,
        zed="blocked_on: jeff: a\nlast_touched: 2026-11-20",
        old="blocked_on: Jeff: b\nlast_touched: 2026-10-01",
        nodate="blocked_on: Jeff: c",
        loose="blocked_on: waiting for the rebuild",
        amy="blocked_on: Amy: d")
    rows = arc_scan.scan(tmp_path, dt.date(2026, 11, 26))
    groups = arc_scan.waiting_groups(rows, dt.date(2026, 11, 26))
    assert [g for g, _ in groups] == ["Amy", "Jeff", "(no name given)"]
    assert [r["slug"] for r in groups[1][1]] == ["old", "zed", "nodate"]


def test_waiting_list_ignores_top_and_threshold(tmp_path, monkeypatch, capsys):
    import arc_scan
    _waiting_dir(tmp_path, monkeypatch,
                 **{f"a{i}": f"blocked_on: Jeff: r{i}\nlast_touched: 2026-11-25" for i in range(5)})
    arc_scan.main(["--top", "1", "--threshold", "999"])
    out = capsys.readouterr().out
    assert all(f"a{i}" in out for i in range(5))
    arc_scan.main(["--all"])
    out = capsys.readouterr().out
    assert out[out.index("WAITING ON"):].count("•") == 5


def test_resume_when_notes(tmp_path, monkeypatch, capsys):
    import arc_scan
    future = (dt.date.today() + dt.timedelta(days=10)).isoformat()
    past = (dt.date.today() - dt.timedelta(days=10)).isoformat()
    _waiting_dir(tmp_path, monkeypatch,
                 later=f"blocked_on: Jeff: r\nresume_when: {future}",
                 lapsed=f"blocked_on: Jeff: r\nresume_when: {past}")
    arc_scan.main([])
    out = capsys.readouterr().out
    assert f" · resume {future}" in out
    assert out.count(" · resume date passed") == 1


def test_tick_and_block_never_mention_waiting(tmp_path, monkeypatch, capsys):
    import arc_scan
    _waiting_dir(tmp_path, monkeypatch, parked="blocked_on: Jeff: r\nlast_touched: 2020-01-01",
                 old="state: active\nneeds_attention: true\nlast_touched: 2020-01-01")
    assert arc_scan.main(["--tick"]) == 0
    assert "WAITING ON" not in capsys.readouterr().out
    assert "WAITING ON" not in arc_scan.format_arc_block()


def test_waiting_line_flags_a_passed_date_left_inside_blocked_on(tmp_path, monkeypatch, capsys):
    """A date inside the blocked_on text is the tripwire _is_parked reads, so the list says it passed."""
    import arc_scan
    arcs = tmp_path / "ent" / "arcs"
    arcs.mkdir(parents=True)
    (arcs / "dated.md").write_text("---\nblocked_on: Jeff: since the 2020-01-05 talk\n---\n", encoding="utf-8")
    monkeypatch.setenv("ARC_DIR", str(arcs))
    monkeypatch.setenv("ARC_CHECK_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("ARC_ENTITIES_ROOT", str(tmp_path / "none"))
    assert arc_scan.main([]) == 0
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if "dated" in l)
    assert line.endswith("· resume date passed")
