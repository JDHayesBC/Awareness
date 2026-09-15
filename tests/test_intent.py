"""Tests for scripts/intent.py — task/intent claims (#324).

Fully isolated: every test drives an explicit tmp intent dir, so the real
<repo>/.locks/intent is never written.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import intent  # noqa: E402

CAIA = "caia (session aaaa1111)"
LYRA = "lyra (session bbbb2222)"


@pytest.fixture
def idir(tmp_path):
    d = tmp_path / "intent"
    d.mkdir()
    return d


def test_claim_then_list(idir):
    intent.claim(324, files=["scripts/lock.py"], work="the thing", holder=CAIA, intent_dir=idir)
    act = intent.active(intent_dir=idir)
    assert len(act) == 1
    assert act[0]["issue"] == "#324"
    assert act[0]["files"] == ["scripts/lock.py"]
    assert act[0]["work"] == "the thing"


def test_issue_number_normalises_hash(idir):
    intent.claim("#324", holder=CAIA, intent_dir=idir)
    assert intent.intent_path_for("324", idir).exists()
    assert intent.intent_path_for("#324", idir).exists()


def test_release_clears_from_active(idir):
    intent.claim(324, holder=CAIA, intent_dir=idir)
    assert intent.release(324, holder=CAIA, intent_dir=idir) is True
    assert intent.active(intent_dir=idir) == []


def test_release_missing_returns_false(idir):
    assert intent.release(999, holder=CAIA, intent_dir=idir) is False


def test_release_preserves_the_record(idir):
    """A released claim is a tombstone, not a delete — who/what survives."""
    intent.claim(324, files=["a.py"], work="why", holder=CAIA, intent_dir=idir)
    intent.release(324, holder=CAIA, intent_dir=idir)
    text = intent.intent_path_for(324, idir).read_text()
    assert "RELEASED" in text and "why" in text and "a.py" in text


def test_stale_claim_drops_out(idir):
    p = idir / "324.lock"
    p.write_text("issue: #324\nstatus: CLAIMED\nholder: lyra (old)\n"
                 "since: 2026-01-01T10:00:00+00:00\n")
    assert intent.active(intent_dir=idir) == []
    assert intent.active(intent_dir=idir, stale_hours=10**9) != []


def test_claim_surfaces_prior_holder_but_does_not_block(idir):
    """Intent never blocks — that is lock.py's job. It only makes it VISIBLE."""
    intent.claim(324, work="hers", holder=LYRA, intent_dir=idir)
    r = intent.claim(324, work="mine", holder=CAIA, intent_dir=idir)
    assert r["superseded"] is not None
    assert "lyra" in r["superseded"]["holder"]
    act = intent.active(intent_dir=idir)
    assert len(act) == 1 and "caia" in act[0]["holder"]  # write went through


def test_reclaiming_own_issue_is_not_superseded(idir):
    intent.claim(324, holder=CAIA, intent_dir=idir)
    r = intent.claim(324, holder=CAIA, intent_dir=idir)
    assert r["superseded"] is None


def test_covering_matches_by_basename_and_suffix(idir):
    intent.claim(324, files=["scripts/lock.py"], holder=LYRA, intent_dir=idir)
    assert intent.covering("scripts/lock.py", intent_dir=idir)
    assert intent.covering("/abs/path/scripts/lock.py", intent_dir=idir)
    assert not intent.covering("scripts/other.py", intent_dir=idir)


def test_ambient_block_is_silent_for_own_claim(idir):
    """The whole point: it must never nag you about your own work."""
    intent.claim(324, files=["a.py"], holder=CAIA, intent_dir=idir)
    assert intent.format_intent_block(holder=CAIA, intent_dir=idir) == ""


def test_ambient_block_shows_sibling_claim(idir):
    intent.claim(300, files=["haven/anchorage/perception.py"], work="spike",
                 holder=LYRA, intent_dir=idir)
    block = intent.format_intent_block(holder=CAIA, intent_dir=idir)
    assert "[intent]" in block and "#300" in block and "lyra" in block
    assert "perception.py" in block


def test_ambient_block_empty_when_nothing_claimed(idir):
    assert intent.format_intent_block(holder=CAIA, intent_dir=idir) == ""


def test_ambient_block_never_raises(tmp_path):
    """Contract with the hook: degrade to empty, never break context injection."""
    assert intent.format_intent_block(holder=CAIA, intent_dir=tmp_path / "nope") == ""


def test_ambient_block_truncates_long_file_lists(idir):
    intent.claim(324, files=[f"f{i}.py" for i in range(9)], holder=LYRA, intent_dir=idir)
    block = intent.format_intent_block(holder=CAIA, intent_dir=idir)
    assert "+6" in block


def test_cli_roundtrip(idir, monkeypatch, capsys):
    monkeypatch.setattr(intent, "INTENT_DIR", idir)
    assert intent.main(["claim", "324", "--files", "a.py,b.py", "--work", "w"]) == 0
    assert intent.main(["list"]) == 0
    assert "#324" in capsys.readouterr().out
    assert intent.main(["check", "a.py"]) == 2      # 2 = covered
    assert intent.main(["check", "zzz.py"]) == 0    # 0 = clear
    assert intent.main(["release", "324"]) == 0
