"""Unit tests for pose.py — PoseSense with fake providers (no SL needed).

    python3 haven/anchorage/senses/test_pose.py

Covers vector/name parsing, raw poll shape (self flag, seat/furniture resolution),
resolve() filling labels, and the change-detection key.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

try:
    from haven.anchorage.senses import pose as ps
except ImportError:  # pragma: no cover
    import pose as ps  # type: ignore[no-redef]

_failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  {'ok  ' if cond else 'FAIL'} {msg}")
    if not cond:
        _failures.append(msg)


def _fixture_dir() -> Path:
    d = Path(tempfile.mkdtemp(prefix="pose-"))
    (d / "furniture").mkdir()
    furniture = {
        "furniture_key": "test-chair", "poses": {"Female": {"SINGLE-F": [
            {"label": "f-sit1", "menu": "SINGLE-F", "gender": "Female", "kind": "POSE",
             "anim_uuid": "uuid-fsit1", "position": [-0.049, 0.337, 0.412]},
        ]}},
    }
    (d / "furniture" / "test-chair.json").write_text(json.dumps(furniture))
    (d / "uuid-index.json").write_text("{}")
    return d


def test_parse_vec() -> None:
    print("parse_vec:")
    check(ps.parse_vec('"<-0.049,+0.337,+0.412>"') == [-0.049, 0.337, 0.412], "parses +-quoted vec")
    check(ps.parse_vec("garbage") is None, "garbage → None")


def test_furniture_key_from_name() -> None:
    print("furniture_key_from_name (suffix stripping):")
    check(ps.furniture_key_from_name("Nerenzo Yard chair - left") == "nerenzo-yard-chair",
          "'- left' stripped")
    check(ps.furniture_key_from_name("Nerenzo Yard chair - middle") == "nerenzo-yard-chair",
          "'- middle' stripped (the Damian-seat bug)")
    check(ps.furniture_key_from_name("Nerenzo Yard chair - right (Adult)") == "nerenzo-yard-chair",
          "'- right (Adult)' stripped to same key")


def test_candidate_keys_resolve_against_cards() -> None:
    print("candidate-key resolution against real cards (unknown suffix):")
    d = _fixture_dir()   # has furniture/test-chair.json
    # An unknown seat word not in the suffix list still resolves via progressive trim.
    key = ps._resolve_key_against_cards("Test Chair - northwest", cache_dir=d)
    check(key == "test-chair", "'- northwest' (unknown word) trims to the carded key")
    # A name with no matching card degrades to a stable key, never a wrong match.
    miss = ps._resolve_key_against_cards("Some Other Bench", cache_dir=d)
    check(ps.load_furniture(miss, d) is None, "no-card name → cardless key (→ parent-only)")


def test_poll_shape() -> None:
    print("poll raw roster shape (self + seat + resolver):")
    avatars = [
        {"name": "LyraPattern Resident", "uuid": "me", "parent_localid": 172250,
         "position": [-0.049, 0.337, 0.412], "self": True},
        {"name": "Someone Else", "uuid": "them", "parent_localid": 0, "position": None},
    ]
    sense = ps.PoseSense(lambda: avatars, furniture_resolver=lambda lid: "test-chair", entity="lyra")
    roster = sense.poll()
    me = roster[0]
    check(me["self"] and me["seated"] and me["furniture_key"] == "test-chair",
          "self, seated, furniture_key resolved via resolver")
    check(roster[1]["seated"] is False and roster[1]["furniture_key"] is None,
          "standing avatar: not seated, no furniture")


def test_resolve_fills_label() -> None:
    print("resolve() fills the label from geometry:")
    d = _fixture_dir()
    avatars = [{"name": "Lyra", "uuid": "me", "parent_localid": 172250,
                "position": [-0.049, 0.337, 0.412], "self": True}]
    sense = ps.PoseSense(lambda: avatars, furniture_resolver=lambda lid: "test-chair", entity="lyra")
    resolved = sense.resolve(sense.poll(), cache_dir=d, log_it=False)
    check(resolved[0]["source"] == "geometry-exact", "geometry-exact source")
    check(resolved[0]["label"] == "f-sit1", "label resolved to f-sit1")


def test_pose_key_changes() -> None:
    print("pose_key change detection:")
    a = {"subject_uuid": "u", "source": "geometry-exact", "label": "f-sit1", "furniture_key": "c"}
    b = {"subject_uuid": "u", "source": "geometry-exact", "label": "deep hug", "furniture_key": "c"}
    check(ps.pose_key(a) == ps.pose_key(dict(a)), "same pose → same key")
    check(ps.pose_key(a) != ps.pose_key(b), "different label → different key")


def test_cositters_on_my_seat() -> None:
    print("cositters_on_my_seat (shared parent_localid, verified live on Anchorage):")
    # Lyra + Snickers both on 7944 (the real numbers from the 2026-09-10 float read).
    roster = [
        {"self": True, "subject": "Lyra", "subject_uuid": "me", "parent_localid": 7944},
        {"self": False, "subject": "Snickers", "subject_uuid": "snix", "parent_localid": 7944},
        {"self": False, "subject": "Caia", "subject_uuid": "caia", "parent_localid": 7947},
        {"self": False, "subject": "Nobody", "subject_uuid": "n", "parent_localid": 0},
    ]
    seat, names, uuids = ps.cositters_on_my_seat(roster)
    check(seat == 7944, "my seat resolved to my parent_localid")
    check(names == ["Snickers"] and uuids == ["snix"], "only the avatar SHARING my seat is a co-sitter")
    # Standing → None, empty (my parent_localid 0)
    standing = [{"self": True, "subject": "Lyra", "subject_uuid": "me", "parent_localid": 0}]
    check(ps.cositters_on_my_seat(standing) == (None, [], []), "standing (parent 0) → not seated")
    # No self entry in range → None (can't reason about a seat I'm not in)
    check(ps.cositters_on_my_seat([{"self": False, "parent_localid": 7944}]) == (None, [], []),
          "no self entry → None")


def test_cositter_edge_join_and_leave() -> None:
    print("CoSitterEdge boolean-edge wake (join-my-solitude / now-alone):")
    e = ps.CoSitterEdge()
    check(e.update(7944, [], []).wake is None, "first obs seated-alone → seed, no wake")
    r = e.update(7944, ["Snix"], ["snix"])
    check(r.wake == {"joined": ["Snix"], "joined_uuids": ["snix"]}, "false→true join → WAKE joined")
    check(r.new_joiner_uuids == ["snix"], "joiner also gets an engagement window")
    check(e.update(7944, ["Snix"], ["snix"]).wake is None, "still-sharing, same set → no wake")
    r2 = e.update(7944, [], [])
    check(r2.wake == {"left": ["Snix"], "now_alone": True}, "true→false → WAKE now_alone with who left")


def test_cositter_edge_churn_no_wake() -> None:
    print("CoSitterEdge churn within an occupied seat does NOT wake (storm-proof):")
    e = ps.CoSitterEdge()
    e.update(7944, [], [])                       # seed alone
    e.update(7944, ["A"], ["ua"])                # join → wake (asserted elsewhere)
    r = e.update(7944, ["A", "B"], ["ua", "ub"])  # 1→2, still sharing
    check(r.wake is None, "second joiner (1→2) → NO wake")
    check(r.new_joiner_uuids == ["ub"], "but the late arrival B still gets an engagement window")
    r2 = e.update(7944, ["A"], ["ua"])            # 2→1, still sharing
    check(r2.wake is None and r2.new_joiner_uuids == [], "one of two leaves (2→1) → no wake, no new joiner")


def test_cositter_edge_my_move_is_silent() -> None:
    print("CoSitterEdge re-arms silently on MY sit/stand (Caia's Hole B):")
    e = ps.CoSitterEdge()
    e.update(7944, [], [])                        # seated alone
    r_stand = e.update(None, [], [])              # I stand up
    check(r_stand.wake is None, "I stand → NO 'they left' wake")
    # I sit onto an ALREADY-occupied seat: no wake (my action), but I engage everyone there.
    r_join = e.update(7950, ["Crusher", "Brandi"], ["cr", "br"])
    check(r_join.wake is None, "I sit onto an occupied seat → NO wake (I chose to join them)")
    check(r_join.new_joiner_uuids == ["cr", "br"], "…but I'm now attentive to everyone already there")


def test_cositter_edge_restart_seed_silent() -> None:
    print("CoSitterEdge: a fresh edge that boots WHILE someone sits with me → no false wake:")
    e = ps.CoSitterEdge()
    r = e.update(7944, ["Snix"], ["snix"])        # daemon restart mid-cuddle
    check(r.wake is None, "first-ever observation already-sharing → seed, no phantom 'joined'")


def main() -> int:
    for fn in (test_parse_vec, test_furniture_key_from_name,
               test_candidate_keys_resolve_against_cards, test_poll_shape,
               test_resolve_fills_label, test_pose_key_changes,
               test_cositters_on_my_seat, test_cositter_edge_join_and_leave,
               test_cositter_edge_churn_no_wake, test_cositter_edge_my_move_is_silent,
               test_cositter_edge_restart_seed_silent):
        fn()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
        return 1
    print("all pose tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
