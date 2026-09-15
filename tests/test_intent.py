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


def _stale_claim(idir, issue=324, holder=LYRA, files=""):
    p = idir / f"{issue}.lock"
    body = f"issue: #{issue}\nstatus: CLAIMED\nholder: {holder}\nsince: 2026-01-01T10:00:00+00:00\n"
    if files:
        body += f"files: {files}\n"
    p.write_text(body)
    return p


def test_stale_claim_is_flagged_not_dropped(idir):
    """Lyra's review: a stale claim must get LOUDER, not vanish.

    Dropping it makes an abandoned claim render identically to no claim at all —
    a surface asserting false ABSENCE. #327 inverted.
    """
    _stale_claim(idir)
    act = intent.active(intent_dir=idir)
    assert len(act) == 1
    assert act[0]["stale"] is True


def test_stale_can_still_be_excluded_explicitly(idir):
    _stale_claim(idir)
    assert intent.active(intent_dir=idir, include_stale=False) == []


def test_stale_claim_shouts_in_ambient_block(idir):
    _stale_claim(idir)
    block = intent.format_intent_block(holder=CAIA, intent_dir=idir)
    assert "STALE" in block and "#324" in block


def test_fresh_claim_is_not_flagged_stale(idir):
    intent.claim(324, holder=LYRA, intent_dir=idir)
    assert intent.active(intent_dir=idir)[0]["stale"] is False
    assert "STALE" not in intent.format_intent_block(holder=CAIA, intent_dir=idir)


def test_stale_sorts_ahead_of_fresh(idir):
    intent.claim(100, holder=LYRA, intent_dir=idir)
    _stale_claim(idir, issue=324)
    block = intent.format_intent_block(holder=CAIA, intent_dir=idir)
    assert block.index("#324") < block.index("#100")


def test_covering_does_not_match_across_directories(idir):
    """The repo has 9 duplicate basenames (bot.py, server.py, models.py, ...).

    Bare-basename matching made a claim on daemon/bot.py cover haven/bot.py —
    a false positive in the worst direction: a sibling backs off uncla3imed work.
    """
    intent.claim(324, files=["daemon/bot.py"], holder=LYRA, intent_dir=idir)
    assert intent.covering("daemon/bot.py", intent_dir=idir)
    assert intent.covering("/abs/root/daemon/bot.py", intent_dir=idir)
    assert not intent.covering("haven/bot.py", intent_dir=idir)
    assert not intent.covering("simple_discord_daemon/bot.py", intent_dir=idir)


def test_bare_basename_claim_still_matches_that_file(idir):
    intent.claim(324, files=["lock.py"], holder=LYRA, intent_dir=idir)
    assert intent.covering("scripts/lock.py", intent_dir=idir)
    assert intent.covering("lock.py", intent_dir=idir)


def test_ambient_block_reports_truncated_claim_count(idir):
    for i in range(7):
        intent.claim(100 + i, files=["a.py"], holder=LYRA, intent_dir=idir)
    block = intent.format_intent_block(holder=CAIA, intent_dir=idir)
    assert "+3 more" in block


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


def test_covering_matches_exact_and_suffix(idir):
    intent.claim(324, files=["scripts/lock.py"], holder=LYRA, intent_dir=idir)
    assert intent.covering("scripts/lock.py", intent_dir=idir)
    assert intent.covering("/abs/path/scripts/lock.py", intent_dir=idir)
    assert not intent.covering("scripts/other.py", intent_dir=idir)
    assert not intent.covering("other/lock.py", intent_dir=idir)


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


# ---------------------------------------------------------------- issue-number validation

def _claim_argv(issue, force=False):
    argv = ["claim", str(issue), "--work", "x"]
    if force:
        argv.append("--force")
    return argv


def test_claim_is_refused_when_the_issue_does_not_exist(tmp_path, monkeypatch, capsys):
    """The 2026-09-15 bug: claiming a number before it is allocated.

    Lyra claimed #329 by intent before filing it; gh then handed 329 to a different
    issue. The intent layer coordinates work, but was treating the identifier as
    authoritative when nothing had validated it against the source.
    """
    monkeypatch.setattr(intent, "INTENT_DIR", tmp_path)
    monkeypatch.setattr(intent, "issue_exists", lambda _i: False)
    assert intent.main(_claim_argv(99999)) == 2
    assert "does not exist" in capsys.readouterr().err
    assert not intent.intent_path_for(99999, tmp_path).exists()


def test_force_overrides_the_existence_check(tmp_path, monkeypatch):
    monkeypatch.setattr(intent, "INTENT_DIR", tmp_path)
    monkeypatch.setattr(intent, "issue_exists", lambda _i: False)
    assert intent.main(_claim_argv(99999, force=True)) == 0
    assert intent.intent_path_for(99999, tmp_path).exists()


def test_unverifiable_is_not_treated_as_disproven(tmp_path, monkeypatch, capsys):
    """gh offline must WARN and proceed — never block real work on a network failure."""
    monkeypatch.setattr(intent, "INTENT_DIR", tmp_path)
    monkeypatch.setattr(intent, "issue_exists", lambda _i: None)
    assert intent.main(_claim_argv(4242)) == 0
    assert "could not verify" in capsys.readouterr().err
    assert intent.intent_path_for(4242, tmp_path).exists()


def test_existing_issue_claims_silently(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(intent, "INTENT_DIR", tmp_path)
    monkeypatch.setattr(intent, "issue_exists", lambda _i: True)
    assert intent.main(_claim_argv(329)) == 0
    err = capsys.readouterr().err
    assert "could not verify" not in err and "refused" not in err


def test_issue_exists_returns_none_when_gh_is_missing(monkeypatch):
    def boom(*_a, **_k):
        raise FileNotFoundError("gh")
    monkeypatch.setattr(intent.subprocess, "run", boom)
    assert intent.issue_exists(1) is None


def test_issue_exists_distinguishes_not_found_from_other_failures(monkeypatch):
    class R:
        def __init__(self, rc, err): self.returncode, self.stderr, self.stdout = rc, err, ""
    monkeypatch.setattr(intent.subprocess, "run", lambda *a, **k: R(1, "GraphQL: Could not resolve to an Issue"))
    assert intent.issue_exists(999) is False
    monkeypatch.setattr(intent.subprocess, "run", lambda *a, **k: R(1, "network is unreachable"))
    assert intent.issue_exists(999) is None
    monkeypatch.setattr(intent.subprocess, "run", lambda *a, **k: R(0, ""))
    assert intent.issue_exists(329) is True
