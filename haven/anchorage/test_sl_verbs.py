"""Unit tests for four small sl.py/sl_bus.py fixes (issues #321, #316, #312, #311).

Pure logic + mocked `SL.cmd` — no live Corrade/SL needed. Constructs SL instances
via ``object.__new__`` (skips ``__init__``'s group-password requirement) and
monkeypatches only what each verb touches, matching the mocking style used
elsewhere in this test suite (test_prettify_speaker.py, test_halo_status.py).

Run:
    PYTHONPATH=<repo> pps/venv/bin/python3 -m pytest haven/anchorage/test_sl_verbs.py
"""

from __future__ import annotations

import os

os.environ.setdefault("ENTITY_NAME", "lyra")

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sl  # noqa: E402


def _bare_sl() -> sl.SL:
    """A SL instance with none of __init__'s network/secret requirements."""
    return object.__new__(sl.SL)


# --------------------------------------------------------------------------- #
# #312 — throttle-aware teleport backoff (pure helpers)
# --------------------------------------------------------------------------- #
def test_is_throttled_matches_corrade_wording():
    assert sl._is_throttled("teleport throttled")
    assert sl._is_throttled("Teleport Throttled")  # case-insensitive
    assert sl._is_throttled("request throttled, try later")  # substring
    assert not sl._is_throttled("teleport failed")
    assert not sl._is_throttled(None)
    assert not sl._is_throttled("")


def test_tp_backoff_schedule_starts_6s_doubles_caps_3_retries():
    delays = sl._tp_backoff_delays()
    assert delays[0] == 6.0
    assert len(delays) <= 3
    # strictly doubling until the total cap trims the last step
    for a, b in zip(delays, delays[1:]):
        assert b == a * 2 or a + b <= 30.0 + 1e-9


def test_tp_backoff_schedule_never_exceeds_total_cap():
    assert sum(sl._tp_backoff_delays()) <= 30.0 + 1e-9
    # a tiny cap truncates the schedule rather than overshooting
    assert sum(sl._tp_backoff_delays(cap_total=10.0)) <= 10.0 + 1e-9


def test_tp_retries_on_throttle_then_succeeds_and_reports_attempts(monkeypatch):
    me = _bare_sl()
    calls = {"n": 0}

    def fake_cmd(command, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            return {"success": False, "error": "teleport throttled"}
        return {"success": True, "error": None}

    monkeypatch.setattr(me, "cmd", fake_cmd)
    monkeypatch.setattr(me, "region", lambda: "The Anchorage")
    monkeypatch.setattr(me, "where", lambda: {"position": (1.0, 1.0, 1.0)})
    monkeypatch.setattr(sl.time, "sleep", lambda *_: None)  # no real waiting in tests

    res = me.tp((1.0, 1.0, 1.0), timeout=5.0)
    assert res["success"] is True
    assert res["arrived"] is True
    assert res["attempts"] == 3
    assert calls["n"] == 3


def test_tp_gives_up_after_retry_budget_with_honest_failure(monkeypatch):
    me = _bare_sl()
    calls = {"n": 0}

    def fake_cmd(command, **kw):
        calls["n"] += 1
        return {"success": False, "error": "teleport throttled"}

    monkeypatch.setattr(me, "cmd", fake_cmd)
    monkeypatch.setattr(me, "region", lambda: "The Anchorage")
    monkeypatch.setattr(me, "where", lambda: {"position": None})
    monkeypatch.setattr(sl.time, "sleep", lambda *_: None)

    res = me.tp((1.0, 1.0, 1.0), timeout=0.1)
    assert res["success"] is False
    assert "throttled" in (res["error"] or "")
    # 1 initial try + up to 3 retries = at most 4 attempts, never more
    assert 1 < res["attempts"] <= 4
    assert calls["n"] == res["attempts"]


def test_tp_does_not_retry_a_non_throttle_failure(monkeypatch):
    me = _bare_sl()
    calls = {"n": 0}

    def fake_cmd(command, **kw):
        calls["n"] += 1
        return {"success": False, "error": "teleport failed"}

    monkeypatch.setattr(me, "cmd", fake_cmd)
    monkeypatch.setattr(me, "region", lambda: "The Anchorage")
    monkeypatch.setattr(me, "where", lambda: {"position": None})
    monkeypatch.setattr(sl.time, "sleep", lambda *_: None)

    res = me.tp((1.0, 1.0, 1.0), timeout=0.1)
    assert res["success"] is False
    assert res["attempts"] == 1
    assert calls["n"] == 1


# --------------------------------------------------------------------------- #
# #316 — attachments() body awareness + detach() name-to-slot resolution
# --------------------------------------------------------------------------- #
def test_attachments_returns_slot_name_uuid_dicts(monkeypatch):
    me = _bare_sl()
    monkeypatch.setattr(me, "_attachments_raw", lambda: "RightHip,Sarong,Skull,Nametag")
    monkeypatch.setattr(
        me, "worn_paths",
        lambda: [{"point": "RightHip", "path": "/My Inventory/Objects/Sarong"},
                 {"point": "Skull", "path": "/My Inventory/Objects/Nametag"}],
    )

    def fake_find_item(pattern, **kw):
        if "Sarong" in pattern:
            return [{"type": "Object", "name": "Sarong", "uuid": "uuid-sarong"}]
        if "Nametag" in pattern:
            return [{"type": "Object", "name": "Nametag", "uuid": "uuid-nametag"}]
        return []

    monkeypatch.setattr(me, "find_item", fake_find_item)

    rows = me.attachments()
    assert rows == [
        {"slot": "RightHip", "name": "Sarong", "uuid": "uuid-sarong"},
        {"slot": "Skull", "name": "Nametag", "uuid": "uuid-nametag"},
    ]


def test_attachments_uuid_none_when_unresolvable(monkeypatch):
    me = _bare_sl()
    monkeypatch.setattr(me, "_attachments_raw", lambda: "RightHip,Sarong")
    monkeypatch.setattr(me, "worn_paths", lambda: [])  # no path -> can't resolve uuid
    monkeypatch.setattr(me, "find_item", lambda *a, **k: (_ for _ in ()).throw(AssertionError))

    rows = me.attachments()
    assert rows == [{"slot": "RightHip", "name": "Sarong", "uuid": None}]


def test_attachments_empty_when_nothing_worn(monkeypatch):
    me = _bare_sl()
    monkeypatch.setattr(me, "_attachments_raw", lambda: "")
    assert me.attachments() == []


def test_detach_kind_slot_bypasses_resolution_entirely(monkeypatch):
    me = _bare_sl()
    seen = {}

    def fake_cmd(command, **kw):
        seen.update(kw)
        return {"success": True, "error": None}

    monkeypatch.setattr(me, "cmd", fake_cmd)
    # attachments() must NOT be consulted for the explicit slot path.
    monkeypatch.setattr(
        me, "attachments",
        lambda: (_ for _ in ()).throw(AssertionError("attachments() should not be called")),
    )
    res = me.detach("RightHip", kind="slot")
    assert res["success"] is True
    assert seen == {"attachments": "RightHip", "type": "slot"}


def test_detach_by_name_resolves_to_slot(monkeypatch):
    me = _bare_sl()
    monkeypatch.setattr(
        me, "attachments",
        lambda: [{"slot": "RightHip", "name": "Sarong Wrap", "uuid": "u1"},
                 {"slot": "Skull", "name": "Nametag", "uuid": "u2"}],
    )
    seen = {}

    def fake_cmd(command, **kw):
        seen.update(kw)
        return {"success": True, "error": None}

    monkeypatch.setattr(me, "cmd", fake_cmd)
    res = me.detach("Sarong")  # substring match, default kind='path'
    assert res["success"] is True
    assert res["slot"] == "RightHip"
    assert seen == {"attachments": "RightHip", "type": "slot"}


def test_detach_by_uuid_resolves_to_slot(monkeypatch):
    me = _bare_sl()
    monkeypatch.setattr(
        me, "attachments",
        lambda: [{"slot": "Skull", "name": "Nametag", "uuid": "463abff9-a89f-a031-b5f2-7436565218b8"}],
    )
    seen = {}
    monkeypatch.setattr(me, "cmd", lambda command, **kw: (seen.update(kw), {"success": True, "error": None})[1])
    res = me.detach("463abff9-a89f-a031-b5f2-7436565218b8")
    assert res["slot"] == "Skull"
    assert seen["attachments"] == "Skull"


def test_detach_ambiguous_name_refuses_without_guessing(monkeypatch):
    me = _bare_sl()
    monkeypatch.setattr(
        me, "attachments",
        lambda: [{"slot": "RightHip", "name": "Bikini", "uuid": "u1"},
                 {"slot": "LeftHip", "name": "Bikini", "uuid": "u2"}],
    )
    monkeypatch.setattr(me, "cmd", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call cmd")))
    res = me.detach("Bikini")
    assert res["success"] is False
    assert "ambiguous" in res["error"]


def test_detach_falls_back_to_raw_form_when_not_a_worn_attachment(monkeypatch):
    me = _bare_sl()
    monkeypatch.setattr(me, "attachments", lambda: [])
    seen = {}

    def fake_cmd(command, **kw):
        seen.update(kw)
        return {"success": False, "error": "general error"}

    monkeypatch.setattr(me, "cmd", fake_cmd)
    res = me.detach("/My Inventory/Clothing/Sundress", kind="path")
    assert res["success"] is False
    assert seen == {"attachments": "/My Inventory/Clothing/Sundress", "type": "path"}


# --------------------------------------------------------------------------- #
# #321 — friend request verbs (payload shaping, mirrors friends()/accept_tp())
# --------------------------------------------------------------------------- #
def test_friend_requests_parses_name_uuid_csv(monkeypatch):
    me = _bare_sl()
    raw = "Crusher+Braveheart,aef9280e-9dca-4e34-9b4e-06a7523b70d0"
    monkeypatch.setattr(me, "cmd", lambda command, **kw: {"data": raw})
    reqs = me.friend_requests()
    assert reqs == [{"name": "Crusher Braveheart", "uuid": "aef9280e-9dca-4e34-9b4e-06a7523b70d0"}]


def test_friend_requests_empty_when_no_data(monkeypatch):
    me = _bare_sl()
    monkeypatch.setattr(me, "cmd", lambda command, **kw: {"data": ""})
    assert me.friend_requests() == []


def test_reply_friend_request_no_pending_is_honest_failure(monkeypatch):
    me = _bare_sl()
    monkeypatch.setattr(me, "friend_requests", lambda: [])
    res = me.reply_friend_request()
    assert res == {"success": False, "error": "no pending friend requests", "from": None}


def test_reply_friend_request_accepts_sole_pending(monkeypatch):
    me = _bare_sl()
    monkeypatch.setattr(
        me, "friend_requests",
        lambda: [{"name": "Crusher Braveheart", "uuid": "aef9280e-9dca-4e34-9b4e-06a7523b70d0"}],
    )
    seen = {}

    def fake_cmd(command, **kw):
        seen["command"] = command
        seen.update(kw)
        return {"success": True, "error": None}

    monkeypatch.setattr(me, "cmd", fake_cmd)
    res = me.reply_friend_request(accept=True)
    assert res == {"success": True, "error": None, "from": "Crusher Braveheart"}
    assert seen == {"command": "replytofriendshiprequest", "action": "accept",
                     "agent": "aef9280e-9dca-4e34-9b4e-06a7523b70d0", "entity": "agent"}


def test_reply_friend_request_declines_by_name(monkeypatch):
    me = _bare_sl()
    monkeypatch.setattr(
        me, "friend_requests",
        lambda: [{"name": "Crusher Braveheart", "uuid": "u1"},
                 {"name": "Damian Vyper", "uuid": "u2"}],
    )
    seen = {}

    def fake_cmd(command, **kw):
        seen.update(kw)
        return {"success": True, "error": None}

    monkeypatch.setattr(me, "cmd", fake_cmd)
    res = me.reply_friend_request("Damian", accept=False)
    assert res["from"] == "Damian Vyper"
    assert seen["action"] == "decline"
    assert seen["agent"] == "u2"


def test_reply_friend_request_multiple_pending_needs_a_name(monkeypatch):
    me = _bare_sl()
    monkeypatch.setattr(
        me, "friend_requests",
        lambda: [{"name": "Crusher Braveheart", "uuid": "u1"},
                 {"name": "Damian Vyper", "uuid": "u2"}],
    )
    monkeypatch.setattr(me, "cmd", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    res = me.reply_friend_request()
    assert res["success"] is False
    assert "multiple" in res["error"]


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
