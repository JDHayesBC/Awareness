"""Unit tests for pose_cache.py — the pose library + bimodal resolver. No SL needed.

    python3 haven/anchorage/senses/test_pose_cache.py

Exits non-zero on any failure. Covers the bimodal matcher (exact / no-snap-to-nearest /
position-collision) and every recognize() path (self-anim, geometry-exact, blind-freeform,
parent-only, not-posed) plus the posed-log side effect.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

try:
    from haven.anchorage.senses import pose_cache as pc
except ImportError:  # pragma: no cover
    import pose_cache as pc  # type: ignore[no-redef]

_failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  {'ok  ' if cond else 'FAIL'} {msg}")
    if not cond:
        _failures.append(msg)


def _fixture_dir() -> Path:
    """A temp pose-cache with one furniture (two poses, plus a position-collision pair)."""
    d = Path(tempfile.mkdtemp(prefix="posecache-"))
    (d / "furniture").mkdir()
    furniture = {
        "furniture_key": "test-chair", "furniture": "Test Chair",
        "object_uuid": "0000-obj",
        "poses": {
            "Female": {
                "SINGLE-F": [
                    {"label": "f-sit1", "menu": "SINGLE-F", "gender": "Female", "kind": "POSE",
                     "anim_uuid": "uuid-fsit1", "position": [-0.049, 0.337, 0.412], "rotation": [0, 0, 0]},
                ],
                "CUDDLE": [
                    {"label": "deep hug", "menu": "CUDDLE", "gender": "Female", "kind": "SYNC",
                     "anim_uuid": "uuid-deephug", "position": [0.10, 0.20, 0.50], "rotation": [0, 0, 0]},
                ],
            },
            "Male": {
                "SINGLE-M": [
                    # position-collision: m-sit1 and m-sit3 share a position.
                    {"label": "m-sit1", "menu": "SINGLE-M", "gender": "Male", "kind": "POSE",
                     "anim_uuid": "uuid-msit1", "position": [0.02, 0.182, 0.556], "rotation": [0, 0, 0]},
                    {"label": "m-sit3", "menu": "SINGLE-M", "gender": "Male", "kind": "POSE",
                     "anim_uuid": "uuid-msit3", "position": [0.02, 0.182, 0.556], "rotation": [0, 0, 0]},
                ],
            },
        },
    }
    (d / "furniture" / "test-chair.json").write_text(json.dumps(furniture), encoding="utf-8")
    (d / "uuid-index.json").write_text(json.dumps({
        "uuid-fsit1": {"furniture_key": "test-chair", "label": "f-sit1", "menu": "SINGLE-F",
                       "gender": "Female", "kind": "POSE"},
    }), encoding="utf-8")
    return d


def test_match_exact() -> None:
    print("match_pose exact:")
    d = _fixture_dir()
    f = pc.load_furniture("test-chair", d)
    entry, alts = pc.match_pose(f, [-0.049, 0.337, 0.412])
    check(entry is not None and entry["label"] == "f-sit1", "exact position → f-sit1")
    check(alts == [], "no spurious alternates on a distinct pose")


def test_match_no_snap() -> None:
    print("match_pose never snaps to nearest (blind-freeform):")
    d = _fixture_dir()
    f = pc.load_furniture("test-chair", d)
    # A freeform position 30cm off every card entry must return NO match, not the nearest.
    entry, alts = pc.match_pose(f, [-0.049, 0.337, 0.712])
    check(entry is None, "off-card position → None (not snapped to f-sit1)")


def test_match_collision() -> None:
    print("match_pose position-collision → entry + alternates:")
    d = _fixture_dir()
    f = pc.load_furniture("test-chair", d)
    entry, alts = pc.match_pose(f, [0.02, 0.182, 0.556])
    check(entry is not None and entry["label"] in ("m-sit1", "m-sit3"), "collision returns one match")
    check(len(alts) == 1, "collision surfaces the other label as an alternate")


def test_recognize_self_anim() -> None:
    print("recognize self-anim (uuid in index):")
    d = _fixture_dir()
    p = pc.recognize({"subject": "me", "subject_uuid": "u", "self": True, "uuid": "uuid-fsit1"},
                     "lyra", cache_dir=d)
    check(p["source"] == "self-anim", "uuid hit → source self-anim")
    check(p["label"] == "f-sit1", "uuid resolved to label f-sit1")
    log = (d / "posed-lyra.jsonl").read_text().splitlines()
    check(len(log) == 1 and json.loads(log[0])["label"] == "f-sit1", "posed-log appended")


def test_recognize_geometry_exact() -> None:
    print("recognize geometry-exact:")
    d = _fixture_dir()
    p = pc.recognize({"subject": "Bee", "subject_uuid": "b", "furniture_key": "test-chair",
                      "position": [0.10, 0.20, 0.50]}, "lyra", cache_dir=d)
    check(p["source"] == "geometry-exact", "position hit → geometry-exact")
    check(p["label"] == "deep hug" and p["menu"] == "CUDDLE", "resolved to deep hug (CUDDLE)")


def test_recognize_blind_freeform() -> None:
    print("recognize geometry no-match → blind-freeform, label None:")
    d = _fixture_dir()
    p = pc.recognize({"subject": "Bee", "subject_uuid": "b", "furniture_key": "test-chair",
                      "position": [5.0, 5.0, 5.0]}, "lyra", cache_dir=d)
    check(p["source"] == "blind-freeform", "off-card → blind-freeform")
    check(p.get("label") is None, "blind never fabricates a label")


def test_recognize_parent_only() -> None:
    print("recognize seated-but-no-card → parent-only:")
    d = _fixture_dir()
    p = pc.recognize({"subject": "X", "subject_uuid": "x", "seated": True}, "lyra", cache_dir=d)
    check(p["source"] == "parent-only", "seated w/o furniture_key → parent-only")


def test_recognize_not_posed() -> None:
    print("recognize standing/not-seated → none, no log:")
    d = _fixture_dir()
    p = pc.recognize({"subject": "X", "subject_uuid": "x", "seated": False}, "lyra", cache_dir=d)
    check(p["source"] == "none", "not seated → source none")
    check(not (d / "posed-lyra.jsonl").exists(), "no posed-log line for a non-pose")


def main() -> int:
    for fn in (test_match_exact, test_match_no_snap, test_match_collision,
               test_recognize_self_anim, test_recognize_geometry_exact,
               test_recognize_blind_freeform, test_recognize_parent_only,
               test_recognize_not_posed):
        fn()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
        return 1
    print("all pose_cache tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
