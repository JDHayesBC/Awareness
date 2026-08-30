"""Regression tests for the "Hi Raptor" / "Hey Damian" speaker-name fix
(sl_daemon._prettify_speaker_name, 2026-08-27).

A local/IM Corrade event's `name` field carries the legacy USERNAME, not the
display name; the per-utterance speaker label greeted the wrong name while the
roster showed the right one. _prettify_speaker_name rewrites `name` from the
UUID-resolved display name in _dn_cache (cache-only on the fast receiver hook).

No live grid: we drive the real functions with a hand-built event + a seeded
_dn_cache. Run:  .venv/bin/python3 haven/anchorage/test_prettify_speaker.py
"""

from __future__ import annotations

import os

os.environ.setdefault("SL_CORRADE", "0")  # skip Corrade client build at import
os.environ.setdefault("ENTITY_NAME", "lyra")

from haven.anchorage import perception  # noqa: E402
from haven.anchorage import sl_daemon as d  # noqa: E402

_failures: list[str] = []
UID = "a1b2c3d4-0000-1111-2222-333344445555"


def check(cond: bool, label: str) -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        _failures.append(label)
        print(f"  FAIL {label}")


def _local(name: str) -> dict:
    # local chat by an avatar: no first/last, name=username, owner==item==uuid
    return {"type": "Normal", "name": name, "message": "hi there",
            "owner": UID, "item": UID, "entity": "Agent"}


def test_cache_hit_rewrites_to_display_name() -> None:
    d._dn_cache.clear()
    d._dn_cache[UID.lower()] = "Jeff Mills"
    ev = _local("Damian Mills")
    check(perception.speaker_of(ev) == "Damian Mills", "before: greets the username (the bug)")
    d._prettify_speaker_name(ev)
    check(perception.speaker_of(ev) == "Jeff Mills", "after: greets the DISPLAY name")


def test_cache_miss_leaves_username() -> None:
    d._dn_cache.clear()  # UID absent → miss; warm no-ops without a running loop
    ev = _local("Raptor Resident")
    d._prettify_speaker_name(ev)
    check(perception.speaker_of(ev) == "Raptor Resident", "cache miss: username stands for this line")


def test_empty_cache_entry_leaves_username() -> None:
    # display == username (or unresolvable) is stored as "" — must NOT blank the name
    d._dn_cache.clear()
    d._dn_cache[UID.lower()] = ""
    ev = _local("Raptor Resident")
    d._prettify_speaker_name(ev)
    check(perception.speaker_of(ev) == "Raptor Resident", "empty cache entry: username preserved")


def test_im_first_last_overridden() -> None:
    d._dn_cache.clear()
    d._dn_cache[UID.lower()] = "Jeff Mills"
    im = {"type": "message", "firstname": "Damian", "lastname": "Mills",
          "name": "Damian Mills", "message": "psst", "agent": UID}
    check(perception.event_kind(im) == "message", "IM is a message event")
    d._prettify_speaker_name(im)
    check(perception.speaker_of(im) == "Jeff Mills", "IM: first/last dropped so display name wins")


def test_non_chat_event_untouched() -> None:
    d._dn_cache.clear()
    d._dn_cache[UID.lower()] = "Jeff Mills"
    roster = {"notification": "avatars", "name": "Raptor Resident", "id": UID}
    before = dict(roster)
    d._prettify_speaker_name(roster)
    check(roster == before, "non-chat (roster) event left untouched")


def test_prewarm_warms_display_cache_on_arrival() -> None:
    # The line-1 cold-cache close: when an avatar comes into range, their display
    # name is resolved BEFORE they ever speak, so hello greets the right name.
    d._dn_cache.clear()
    warmed: list[str] = []
    orig = d._schedule_display_warm
    d._schedule_display_warm = lambda uid: warmed.append(uid)  # type: ignore[assignment]
    try:
        arrival = {"notification": "avatars", "action": "added", "id": UID, "name": "Damian Mills"}
        check(perception.event_kind(arrival) == "avatars", "arrival is an avatars event")
        d._prewarm_roster_name(arrival)
        check(warmed == [UID], "uncached arrival warms the display-name cache before line one")

        warmed.clear()  # already resolved → no redundant warm
        d._dn_cache[UID.lower()] = "Jeff Mills"
        d._prewarm_roster_name(arrival)
        check(warmed == [], "already-resolved avatar is not re-warmed on arrival")

        warmed.clear()  # empty sentinel (username==display / unresolvable) → no re-warm
        d._dn_cache[UID.lower()] = ""
        d._prewarm_roster_name(arrival)
        check(warmed == [], "empty-sentinel avatar is not re-warmed on arrival")

        warmed.clear()  # a chat line is not an arrival — prettify handles those
        d._dn_cache.clear()
        d._prewarm_roster_name(_local("Damian Mills"))
        check(warmed == [], "a local chat event is not treated as an arrival")
    finally:
        d._schedule_display_warm = orig  # type: ignore[assignment]


def main() -> int:
    for fn in (
        test_cache_hit_rewrites_to_display_name,
        test_cache_miss_leaves_username,
        test_empty_cache_entry_leaves_username,
        test_im_first_last_overridden,
        test_non_chat_event_untouched,
        test_prewarm_warms_display_cache_on_arrival,
    ):
        fn()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
        return 1
    print("all prettify-speaker tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
