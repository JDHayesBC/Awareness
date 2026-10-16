"""Tests for the outgoing credential redactor (GH #372). Fake values only."""

import pytest

from haven import redact as R

FAKE_KEY = "fakeKEY1234567890abcdefGHIJ"
FAKE_HA = "fakeHAtoken9876543210zyxwvuTSRQ"
FAKE_EXPORT = "exportedSecretValue123456"
FAKE_QUOTED = "quotedSecretValue987654321"


@pytest.fixture
def env_file(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "# a comment\n\n"
        f"VOICESTUDIO_API_KEY={FAKE_KEY}\n"
        f"HA_TOKEN={FAKE_HA}\n"
        f"export MY_SECRET={FAKE_EXPORT}\n"
        f'DB_PASSWORD="{FAKE_QUOTED}"\n'
        "SHORT_TOKEN=abc123\n"
        "NOT_A_CREDENTIAL=thisisalongbutharmlessvalue\n"
    )
    return p


@pytest.fixture
def known(env_file):
    return R.load_secret_values(env_file, environ={})


def test_load_secret_values(env_file):
    k = R.load_secret_values(env_file, environ={"OTHER_API_KEY": "envsecretvalue12345", "X_TOKEN": "short"})
    assert {FAKE_KEY, FAKE_HA, FAKE_EXPORT, FAKE_QUOTED, "envsecretvalue12345"} == k


def test_load_missing_file(tmp_path):
    assert R.load_secret_values(tmp_path / "nope", environ={}) == set()


def test_known_redacted_in_shared_room(known):
    r = R.redact_for_room(f"the key is {FAKE_KEY} ok", is_private_human_dm=False, known=known)
    assert FAKE_KEY not in r.text and "[redacted]" in r.text
    assert [h.kind for h in r.hits] == ["known"] and r.hits[0].length == len(FAKE_KEY)


def test_known_allowed_but_logged_in_private_dm(known):
    t = f"the key is {FAKE_KEY}"
    r = R.redact_for_room(t, is_private_human_dm=True, known=known)
    assert r.text == t and len(r.hits) == 1


def test_generic_token_redacted():
    tok = "Ab3" * 12
    r = R.redact(f"here {tok} there", known=set(), allow=False)
    assert tok not in r.text and r.hits[0].kind == "generic"


def test_sha_and_prose_untouched():
    sha = "a" * 20 + "1" * 20
    t = f"commit {sha} abc1234 and Pneumonoultramicroscopicsilicovolcanoconiosisandmore plus " + "word " * 20
    r = R.redact(t, known=set(), allow=False)
    assert r.text == t and not r.hits


def test_prefixed_tokens():
    r = R.redact("sk-abcdefghijklmnopqrstuvwx", known=set(), allow=False)
    assert r.text == "[redacted]" and r.hits[0].kind == "prefixed"
    r = R.redact("Authorization: Bearer abcDEF1234567890xyzQ", known=set(), allow=False)
    assert r.text == "Authorization: Bearer [redacted]"
    r = R.redact("Bearer authentication is used", known=set(), allow=False)
    assert not r.hits


def test_multiple_hits(known):
    t = f"a {FAKE_KEY} b {FAKE_HA} c sk-abcdefghijklmnopqrstuvwx"
    r = R.redact(t, known=known, allow=False)
    assert len(r.hits) == 3 and r.text == "a [redacted] b [redacted] c [redacted]"


def test_empty_text(known):
    r = R.redact("", known=known, allow=False)
    assert r.text == "" and r.hits == []


def test_code_span_and_url(known):
    r = R.redact(f"`{FAKE_KEY}` and https://x.example/api?key={FAKE_KEY}&a=1", known=known, allow=False)
    assert FAKE_KEY not in r.text and len(r.hits) == 2


def test_idempotent(known):
    once = R.redact(f"{FAKE_KEY} sk-abcdefghijklmnopqrstuvwx", known=known, allow=False)
    twice = R.redact(once.text, known=known, allow=False)
    assert twice.text == once.text and not twice.hits


def test_mode_resolution():
    assert R.resolve_redact_mode({}) == "strict"
    assert R.resolve_redact_mode({"HAVEN_REDACT_MODE": "LOG"}) == "log"
    assert R.resolve_redact_mode({"HAVEN_REDACT_MODE": "off"}) == "off"
    assert R.resolve_redact_mode({"HAVEN_REDACT_MODE": "bogus"}) == "strict"


def test_cache_reload(monkeypatch):
    monkeypatch.setattr(R, "load_secret_values", lambda: {"one-secret-value"})
    assert R.reload_known_secrets() == {"one-secret-value"}
    monkeypatch.setattr(R, "load_secret_values", lambda: {"two-secret-value"})
    assert R.get_known_secrets() == {"one-secret-value"}
    assert R.reload_known_secrets() == {"two-secret-value"}
    R._known_cache = None


def test_allow_mode_leaves_text_but_reports_hits(monkeypatch, known):
    # log mode: allow=True path never alters text
    r = R.redact(f"x {FAKE_KEY}", known=known, allow=True)
    assert FAKE_KEY in r.text and r.hits


ME = "caia"
DM = {"is_dm": True}


@pytest.mark.parametrize(
    "room,members,bots,expected",
    [
        (DM, [{"username": ME}, {"username": "jeff", "is_bot": False}], set(), True),
        (DM, [{"username": ME}, {"username": "lyra", "is_bot": True}], set(), False),
        (DM, [{"username": ME}, {"username": "lyra", "is_bot": False}], {"lyra"}, False),
        (DM, [{"username": ME}, {"username": "a"}, {"username": "b"}], set(), False),
        (DM, None, set(), False),
        ({"is_dm": False}, [{"username": ME}, {"username": "jeff"}], set(), False),
        (None, [{"username": ME}, {"username": "jeff"}], set(), False),
    ],
)
def test_is_private_human_dm(room, members, bots, expected):
    assert R.is_private_human_dm(room, members, ME, bots) is expected


def test_uuid_and_slug_untouched():
    t = (
        "room c27e739f-20ee-4365-a458-df7c9cd9bda0 session, edge 3f9c2a1e-8b7d-4c6a-9e2f-1a2b3c4d5e6f, "
        "file arcs/embodiment-practice-2026-10-16-v2.md and model qwen2.5-coder-14b-instruct-q4_k_m-2026"
    )
    r = R.redact(t, known=set(), allow=False)
    assert r.text == t and not r.hits


def test_known_uuid_still_redacted_and_random_tokens_still_caught():
    tok = "c27e739f-20ee-4365-a458-df7c9cd9bda0"
    r = R.redact(f"token {tok}", known={tok}, allow=False)
    assert r.text == "token [redacted]" and r.hits[0].kind == "known"
    # a base62 key with a separator but no 4+ letter plain word segment
    r = R.redact("key a9Zk3-Q7m2Lp8x4Vn1Rt6Yw0Bc5Hd3Jf9", known=set(), allow=False)
    assert r.text == "key [redacted]"
    # 64-hex stays redacted (could be a key); only the 40-hex git SHA shape is exempt
    r = R.redact("x " + "ab12" * 16, known=set(), allow=False)
    assert r.text == "x [redacted]"


def test_private_dm_allowlist_is_jeff_only_by_default():
    me = "caia"
    room = {"is_dm": True}
    jeff = [{"username": "caia", "is_bot": True}, {"username": "jeff", "is_bot": False}]
    crusher = [{"username": "caia", "is_bot": True}, {"username": "crusher", "is_bot": False}]
    lyra = [{"username": "caia", "is_bot": True}, {"username": "lyra", "is_bot": True}]
    assert R.is_private_human_dm(room, jeff, me)
    assert not R.is_private_human_dm(room, crusher, me)          # human, but not Jeff
    assert not R.is_private_human_dm(room, lyra, me)             # sister bot
    assert not R.is_private_human_dm({"is_dm": False}, jeff, me)  # shared room
    assert not R.is_private_human_dm(room, jeff + [{"username": "x", "is_bot": False}], me)
    # allow-list is configurable
    assert R.is_private_human_dm(room, crusher, me, allowed=frozenset({"jeff", "crusher"}))
    assert R.allowed_humans({}) == frozenset({"jeff"})
    assert R.allowed_humans({"HAVEN_REDACT_ALLOW_USERS": "Jeff, carol"}) == frozenset({"jeff", "carol"})
