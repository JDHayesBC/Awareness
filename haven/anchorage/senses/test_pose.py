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


def main() -> int:
    for fn in (test_parse_vec, test_furniture_key_from_name,
               test_candidate_keys_resolve_against_cards, test_poll_shape,
               test_resolve_fills_label, test_pose_key_changes):
        fn()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
        return 1
    print("all pose tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
