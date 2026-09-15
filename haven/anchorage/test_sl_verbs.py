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


# --------------------------------------------------------------------------- #
# GH#298 — new _sit_social: 4-step region-aware sit
# --------------------------------------------------------------------------- #

# Corrade CSV format for getavatarpositions data response:
_AV_POS_DATA = '"Crusher Braveheart",aef9280e-9dca-4e34-9b4e-06a7523b70d0,"<128, 64, 22>"'

# getavatarsdata range=512 data=FirstName,LastName,ParentID,Position — target seated on LocalID 7950
_AV_DATA_SEATED = (
    "FirstName,Crusher,LastName,Braveheart,ParentID,7950,"
    'Position,"<128.1, 64.1, 22.0>"'
)

# getobjectsdata range=512 data=Name,LocalID,ID — seat resolves to a UUID
_OBJ_DATA = (
    'Name,,LocalID,7950,ID,bbbbbbbb-0000-0000-0000-000000000001'
)


def _make_cmd_map(**overrides):
    """Return a fake cmd() that dispatches by ``command`` kwarg."""
    defaults = {
        "getavatarpositions": {"data": _AV_POS_DATA, "success": "True"},
        "getavatarsdata": {"data": _AV_DATA_SEATED, "success": "True"},
        "getobjectsdata": {"data": _OBJ_DATA, "success": "True"},
        "sit": {"success": "True", "error": None},
        "getselfdata": {"data": "SittingOn,7950", "success": "True"},
        "stand": {"success": "True"},
    }
    defaults.update(overrides)

    def fake_cmd(command, **kw):
        return defaults.get(command, {})

    return fake_cmd


def test_sit_social_with_finds_avatar_and_sits(monkeypatch):
    """WITH mode: region scan → ParentID → seat UUID → sit, no TP needed (nearby)."""
    me = _bare_sl()
    calls = []

    def fake_cmd(command, **kw):
        calls.append(command)
        return _make_cmd_map()(command, **kw)

    monkeypatch.setattr(me, "cmd", fake_cmd)
    monkeypatch.setattr(me, "where", lambda: {"position": (130.0, 64.0, 22.0)})
    monkeypatch.setattr(me, "_sitting_on", lambda: 7950)
    monkeypatch.setattr(me, "_grant_pending", lambda: None)
    monkeypatch.setattr(me, "_pick_unoccupied_slot", lambda *a, **k: {"picked": None, "how": "no-sitter-menu"})
    monkeypatch.setattr(sl.time, "sleep", lambda *_: None)

    res = me._sit_social("Crusher", "with", 15.0)
    assert res["success"] is True
    assert res["mode"] == "with"
    assert res["uuid"] == "bbbbbbbb-0000-0000-0000-000000000001"
    assert res["with"] == "Crusher Braveheart"
    assert "getavatarpositions" in calls
    assert "getavatarsdata" in calls
    assert "getobjectsdata" in calls
    assert "sit" in calls


def test_sit_social_with_tps_first_when_far(monkeypatch):
    """WITH mode: target > 96 m away → teleport fires before sit."""
    me = _bare_sl()
    tp_calls = []

    def fake_cmd(command, **kw):
        return _make_cmd_map()(command, **kw)

    def fake_tp(pos, **kw):
        tp_calls.append(pos)
        return {"success": True, "arrived": True}

    monkeypatch.setattr(me, "cmd", fake_cmd)
    # Place me far from the target (128, 64, 22).
    monkeypatch.setattr(me, "where", lambda: {"position": (0.0, 0.0, 22.0)})
    monkeypatch.setattr(me, "tp", fake_tp)
    monkeypatch.setattr(me, "_sitting_on", lambda: 7950)
    monkeypatch.setattr(me, "_grant_pending", lambda: None)
    monkeypatch.setattr(me, "_pick_unoccupied_slot", lambda *a, **k: {"picked": None, "how": "no-sitter-menu"})
    monkeypatch.setattr(sl.time, "sleep", lambda *_: None)

    res = me._sit_social("Crusher", "with", 15.0)
    assert res["success"] is True
    # TP must have fired (distance ≈ 147 m >> 96 m threshold).
    assert len(tp_calls) == 1


def test_sit_social_with_target_not_found(monkeypatch):
    """WITH mode: avatar not in region → honest failure, no sit attempt."""
    me = _bare_sl()
    sit_calls = []

    def fake_cmd(command, **kw):
        if command == "sit":
            sit_calls.append(True)
        if command == "getavatarpositions":
            return {"data": ""}   # nobody in region
        return {}

    monkeypatch.setattr(me, "cmd", fake_cmd)
    monkeypatch.setattr(sl.time, "sleep", lambda *_: None)

    res = me._sit_social("Ghost", "with", 15.0)
    assert res["success"] is False
    assert "Ghost" in res["error"]
    assert not sit_calls


def test_sit_social_with_target_standing(monkeypatch):
    """WITH mode: target found but not seated → honest failure."""
    me = _bare_sl()
    av_data_standing = (
        "FirstName,Crusher,LastName,Braveheart,ParentID,0,"
        'Position,"<128.1, 64.1, 22.0>"'
    )

    def fake_cmd(command, **kw):
        if command == "getavatarpositions":
            return {"data": _AV_POS_DATA}
        if command == "getavatarsdata":
            return {"data": av_data_standing}
        return {}

    monkeypatch.setattr(me, "cmd", fake_cmd)
    monkeypatch.setattr(me, "where", lambda: {"position": (130.0, 64.0, 22.0)})
    monkeypatch.setattr(sl.time, "sleep", lambda *_: None)

    res = me._sit_social("Crusher", "with", 15.0)
    assert res["success"] is False
    assert "isn't sitting" in res["error"]


def test_sit_social_near_tps_to_target_and_scans(monkeypatch):
    """NEAR mode: target found, > 96 m away → TP fires, then local scan."""
    me = _bare_sl()
    tp_calls = []

    def fake_cmd(command, **kw):
        if command == "getavatarpositions":
            return {"data": _AV_POS_DATA}
        if command == "getavatarsdata":
            return {"data": "FirstName,Crusher,LastName,Braveheart,ParentID,0"}
        if command == "getobjectsdata":
            # scripted chair right beside the target
            return {"data": 'ID,cccccccc-0000-0000-0000-000000000001,Flags,Scripted,Position,"<128.5, 64.5, 22>"'}
        if command == "sit":
            return {"success": "True", "error": None}
        if command == "getselfdata":
            return {"data": "SittingOn,5555"}
        return {}

    def fake_tp(pos, **kw):
        tp_calls.append(pos)
        return {"success": True, "arrived": True}

    monkeypatch.setattr(me, "cmd", fake_cmd)
    monkeypatch.setattr(me, "where", lambda: {"position": (0.0, 0.0, 22.0)})
    monkeypatch.setattr(me, "tp", fake_tp)
    monkeypatch.setattr(me, "_sitting_on", lambda: 5555)
    monkeypatch.setattr(me, "_roster_flags", lambda r: [
        ("cccccccc-0000-0000-0000-000000000001", (128.5, 64.5, 22.0), True)
    ])
    monkeypatch.setattr(me, "_is_occupied", lambda u, r: False)
    monkeypatch.setattr(me, "_grant_pending", lambda: None)
    monkeypatch.setattr(me, "name_of", lambda u: "Comfy Chair")
    monkeypatch.setattr(sl.time, "sleep", lambda *_: None)

    res = me._sit_social("Crusher", "near", 15.0)
    assert res["success"] is True
    assert res["mode"] == "near"
    assert res["near"] == "Crusher Braveheart"
    assert len(tp_calls) == 1


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
