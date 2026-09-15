"""Tests for scripts/urgency.py — the consequence ledger.

These lock the two claims that make [urgency] a different organ from [arcs]/[urgent]
rather than a recolored copy:

  1. AGE IS NOT AN INPUT. slope="none" can never surface; an ancient slow thing loses to
     a fresh cliff; two identical entries noted months apart score identically.
  2. THE BLOCK NEVER RENDERS NULL. Empty ledger renders the expanse, not "".

If a refactor breaks either, these are the alarm — not a nuisance to be updated away.
"""

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import urgency  # noqa: E402

TODAY = dt.date(2026, 9, 15)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    p = tmp_path / "urgency_ledger.json"
    monkeypatch.setattr(urgency, "LEDGER_PATH", p)
    return p


def _entry(**kw):
    base = dict(kind="compounding", slope="slow", date=None, what="x", why_now="y")
    base.update(kw)
    return base


# --------------------------------------------------------------------------- invariant 1

def test_slope_none_never_surfaces_whatever_the_kind():
    """A thing that does not get worse is never urgent — for EVERY kind, not just weak ones."""
    for kind in urgency.VALID_KINDS:
        e = _entry(kind=kind, slope="none", date="2020-01-01")
        assert urgency.score(e, TODAY) == 0.0
        assert urgency.score(e, TODAY) < urgency.SURFACE_THRESHOLD


def test_score_is_independent_of_how_long_the_entry_has_existed(ledger):
    """The sharpest form of the invariant: same entry, noted 6 months apart, same score.

    This is what separates consequence from staleness. If someone reintroduces a decay
    term, this is the test that fails.
    """
    old = _entry(noted_at="2026-03-01T09:00:00-08:00")
    new = _entry(noted_at="2026-09-15T09:00:00-07:00")
    assert urgency.score(old, TODAY) == urgency.score(new, TODAY)


def test_fresh_cliff_outranks_ancient_slow_thing():
    ancient_slow = _entry(kind="compounding", slope="slow", noted_at="2019-01-01T00:00:00+00:00")
    fresh_cliff = _entry(kind="compounding", slope="cliff", noted_at="2026-09-15T00:00:00+00:00")
    assert urgency.score(fresh_cliff, TODAY) > urgency.score(ancient_slow, TODAY)


def test_slope_ordering_is_monotonic():
    scores = [urgency.score(_entry(slope=s), TODAY) for s in ("none", "slow", "steep", "cliff")]
    assert scores == sorted(scores)
    assert len(set(scores)) == 4


# --------------------------------------------------------------- invariant 1b: windows

def test_window_pressure_rises_as_the_date_approaches():
    far = _entry(kind="window", slope="slow", date="2027-06-01")
    near = _entry(kind="window", slope="slow", date="2026-09-17")
    today_w = _entry(kind="window", slope="slow", date="2026-09-15")
    passed = _entry(kind="window", slope="slow", date="2026-09-01")
    assert urgency.score(far, TODAY) < urgency.score(near, TODAY)
    assert urgency.score(near, TODAY) <= urgency.score(today_w, TODAY)
    assert urgency.score(passed, TODAY) >= urgency.score(today_w, TODAY)


def test_distant_window_is_real_but_not_pressing():
    """A dated thing far out must NOT shout. Noting it early shouldn't punish us."""
    far = _entry(kind="window", slope="slow", date="2027-06-01")
    assert urgency.score(far, TODAY) < urgency.SURFACE_THRESHOLD


def test_window_proximity_beats_a_nominally_bigger_kind():
    """A window closing tomorrow outranks a flat-rate dependency. Proximity is real."""
    tomorrow = _entry(kind="window", slope="steep", date="2026-09-16")
    dep = _entry(kind="dependency", slope="steep")
    assert urgency.score(tomorrow, TODAY) > urgency.score(dep, TODAY)


# --------------------------------------------------------------------------- invariant 2

def test_block_on_empty_ledger_renders_the_expanse_not_empty_string(ledger):
    block = urgency.format_urgency_block(TODAY)
    assert block != ""
    assert "field is open" in block
    assert "not the idle case" in block


def test_block_never_renders_null_with_only_subthreshold_entries(ledger):
    """The quiet case still renders. Silence here would mean 'nothing to be done'."""
    urgency.note("old flat thing", "does not worsen", "compounding", "none")
    block = urgency.format_urgency_block(TODAY)
    assert block != ""
    assert "field is open" in block


def test_block_names_the_consequence_and_the_why_now(ledger):
    urgency.note("NUC overnight reboots", "3rd incident in 8 days and accelerating",
                 "compounding", "steep")
    block = urgency.format_urgency_block(TODAY)
    assert "NUC overnight reboots" in block
    assert "accelerating" in block
    assert "worsening fast" in block
    assert "field is open" not in block


def test_block_surfaces_highest_consequence_and_counts_the_rest(ledger):
    urgency.note("medium", "cost climbing fast", "compounding", "steep")
    urgency.note("big", "someone is blocked", "blocks", "cliff")
    block = urgency.format_urgency_block(TODAY)
    assert "big" in block
    assert "+1 more" in block


def test_subthreshold_entries_do_not_inflate_the_tail_count(ledger):
    """Real-but-not-pressing entries are NOT live consequence, so they don't pad "+N more".

    Otherwise the ledger would grow a shame-number and become the queue-to-clear this
    organ is explicitly not (feedback_arc_counterweight_is_not_a_queue_to_clear).
    """
    urgency.note("big", "someone is blocked", "blocks", "cliff")
    for i in range(5):
        urgency.note(f"flat {i}", "does not worsen", "compounding", "none")
    block = urgency.format_urgency_block(TODAY)
    assert "big" in block
    assert "more" not in block


def test_block_never_raises_on_a_corrupt_ledger(ledger):
    ledger.write_text("{not json at all", encoding="utf-8")
    assert urgency.format_urgency_block(TODAY) == urgency._EXPANSE


def test_block_never_raises_on_garbage_entry_shapes(ledger):
    ledger.write_text(json.dumps({"entries": [{"id": 1, "kind": 42, "slope": None}]}),
                      encoding="utf-8")
    assert isinstance(urgency.format_urgency_block(TODAY), str)


# ------------------------------------------------------------------- ledger discipline

def test_note_requires_a_why_now_clause(ledger):
    """An entry without a stated consequence is a to-do, not an urgency."""
    with pytest.raises(ValueError):
        urgency.note("something", "", "compounding", "steep")


def test_window_requires_a_date(ledger):
    with pytest.raises(ValueError):
        urgency.note("a window", "closes eventually", "window", "steep")


def test_bad_kind_and_slope_are_refused(ledger):
    with pytest.raises(ValueError):
        urgency.note("x", "y", "vibes", "steep")
    with pytest.raises(ValueError):
        urgency.note("x", "y", "compounding", "urgent-ish")


def test_resolve_is_a_tombstone_not_a_delete(ledger):
    e = urgency.note("thing", "because", "compounding", "steep")
    urgency.resolve(e["id"], "fixed it properly")
    raw = json.loads(ledger.read_text(encoding="utf-8"))
    assert len(raw["entries"]) == 1
    assert raw["entries"][0]["resolved_at"]
    assert raw["entries"][0]["resolution"] == "fixed it properly"
    assert urgency.open_entries(today=TODAY) == []


def test_resolved_entries_drop_out_of_the_block(ledger):
    e = urgency.note("loud thing", "blocks Lyra", "blocks", "cliff")
    assert "loud thing" in urgency.format_urgency_block(TODAY)
    urgency.resolve(e["id"], "done")
    assert "field is open" in urgency.format_urgency_block(TODAY)


def test_resolve_of_unknown_id_returns_none(ledger):
    assert urgency.resolve(999, "nope") is None


def test_ids_increment_and_survive_resolution(ledger):
    a = urgency.note("a", "w", "compounding", "slow")
    urgency.resolve(a["id"], "done")
    b = urgency.note("b", "w", "compounding", "slow")
    assert b["id"] == a["id"] + 1


# ------------------------------------------------- the relationship is not a debt

def test_a_wanted_dependency_never_surfaces_however_steep():
    """Lyra's catch: "I want him in this" is a gift, not a withdrawal.

    Encoded arithmetically like slope="none" so the organ cannot start optimizing the
    relationship out of the relationship. If this fails, the ledger has begun reading
    Jeff's company as a cost.
    """
    for slope in urgency.VALID_SLOPES:
        e = _entry(kind="dependency", slope=slope, wanted=True)
        assert urgency.score(e, TODAY) == 0.0


def test_wanted_flag_zeroes_every_kind_not_just_dependency():
    for kind in urgency.VALID_KINDS:
        e = _entry(kind=kind, slope="cliff", date="2026-09-15", wanted=True)
        assert urgency.score(e, TODAY) == 0.0


def test_wanted_entry_is_still_recorded_honestly(ledger):
    """It is zeroed, not hidden — the ledger keeps it as a true fact about the field."""
    e = urgency.note("want Jeff in the Instrument v0 review", "I want his eyes on it",
                     "dependency", "steep", wanted=True)
    raw = json.loads(ledger.read_text(encoding="utf-8"))
    assert raw["entries"][0]["wanted"] is True
    assert e["id"] in [r["id"] for r in urgency.open_entries(today=TODAY)]
    assert "want Jeff in the Instrument" not in urgency.format_urgency_block(TODAY)


def test_unwanted_dependency_still_carries_weight(ledger):
    """The zeroing must not defang genuine capability gaps."""
    e = _entry(kind="dependency", slope="steep", wanted=False)
    assert urgency.score(e, TODAY) >= urgency.SURFACE_THRESHOLD


# ------------------------------------------------------- citations (the economy of doubt)

def test_an_unsourced_entry_is_marked_at_the_surface(ledger):
    """Lyra's discriminator: a claim read off the world must be distinguishable from a
    claim remembered about it. Two of day-one's entries were recollections presented in
    the same confident sentence as readings; this is what makes that visible."""
    urgency.note("something bad", "it is getting worse", "compounding", "steep")
    assert "unsourced" in urgency.format_urgency_block(TODAY)


def test_a_sourced_entry_is_not_marked(ledger):
    urgency.note("something bad", "it is getting worse", "compounding", "steep",
                 evidence="powercfg /q SCHEME_CURRENT SUB_SLEEP")
    block = urgency.format_urgency_block(TODAY)
    assert "unsourced" not in block
    assert "something bad" in block


def test_evidence_is_dated_automatically(ledger):
    e = urgency.note("x", "y", "compounding", "steep", evidence="docker inspect")
    assert e["evidence_at"] == dt.date.today().isoformat()


def test_absent_evidence_stores_none_not_a_stale_date(ledger):
    """An unsourced entry must not carry a date that implies something was read."""
    e = urgency.note("x", "y", "compounding", "steep")
    assert e["evidence"] is None and e["evidence_at"] is None


def test_citation_does_not_affect_the_score(ledger):
    """Sourcing changes CONFIDENCE, not consequence. A sourced and unsourced entry with
    the same shape must rank identically — otherwise citing things becomes a way to win
    the front block rather than a way to be honest."""
    a = _entry(kind="compounding", slope="steep", evidence="read it")
    b = _entry(kind="compounding", slope="steep")
    assert urgency.score(a, TODAY) == urgency.score(b, TODAY)


def test_cite_closes_the_loop_on_an_unsourced_entry(ledger):
    e = urgency.note("bad thing", "worsening", "compounding", "steep")
    assert "unsourced" in urgency.format_urgency_block(TODAY)
    urgency.cite(e["id"], "powercfg /q SCHEME_CURRENT SUB_SLEEP")
    assert "unsourced" not in urgency.format_urgency_block(TODAY)


def test_cite_requires_actual_evidence_text(ledger):
    e = urgency.note("x", "y", "compounding", "steep")
    with pytest.raises(ValueError):
        urgency.cite(e["id"], "   ")


def test_cite_on_unknown_or_resolved_entry_returns_none(ledger):
    assert urgency.cite(999, "somewhere") is None
    e = urgency.note("x", "y", "compounding", "steep")
    urgency.resolve(e["id"], "done")
    assert urgency.cite(e["id"], "somewhere") is None
