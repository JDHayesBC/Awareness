"""Unit tests for SLPerception (haven/anchorage/perception.py).

Pure logic, fake clock, no Second Life required. Self-running::

    python3 haven/anchorage/test_perception.py

Exits non-zero on any failure.
"""

from __future__ import annotations

import sys

try:  # package or flat-path import, same shim style as the other anchorage tests
    from haven.anchorage.perception import (
        ArousalState, PerceptionSurface, SLPerception, SalienceConfig,
        DROP, FORCE, MEDIUM, LOW, event_kind, score_event, speaker_of, speaker_uuid,
    )
except ImportError:  # pragma: no cover
    from perception import (  # type: ignore[no-redef]
        ArousalState, PerceptionSurface, SLPerception, SalienceConfig,
        DROP, FORCE, MEDIUM, LOW, event_kind, score_event, speaker_of, speaker_uuid,
    )

CFG = SalienceConfig()
SELF = {"lyrapattern", "lyrapattern resident"}
ADDR = {"lyra", "lyrapattern"}
# Real avatar UUIDs, captured off the live Corrade wire (2026-08-24).
LYRA_UUID = "aef9280e-9dca-4e34-9b4e-06a7523b70d0"
DAMIAN_UUID = "c06d8847-53af-4983-97f7-99dc20566583"
SELF_UUIDS = {LYRA_UUID}

_failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        _failures.append(msg)


def local(first: str, last: str, message: str) -> dict:
    # Corrade puts the CHAT type (Normal) in `type` for local chat, not "local".
    return {"type": "Normal", "firstname": first, "lastname": last, "message": message}


def local_real(uuid: str, name: str, message: str, entity: str = "Agent") -> dict:
    """The REAL Corrade `local` shape as perception receives it (verified 2026-08-24).

    Crucially: there is NO firstname/lastname — the speaker's agent UUID lives in
    ``owner`` and ``item``, and the display name is in ``name``. This is the shape
    the old name-only self-check could not catch, which drove the replay storm;
    tests built on the synthetic ``local()`` above never exercised it.

    On the raw wire Corrade form-encodes spaces as ``+`` (``LyraPattern+Resident``),
    but ``corrade_client.decode_kv`` (``unquote_plus``, 2026-08-24) normalises that
    at the intake seam BEFORE any event reaches perception — so the realistic input
    here carries spaces, not ``+``. Testing perception against ``+``-encoded names
    would exercise an input the architecture no longer produces."""
    return {
        "type": "local", "notification": "local",
        "item": uuid, "owner": uuid, "entity": entity,
        "message": message,
        "name": name,
        "position": "<184.77438, 211.8318, 29.78>", "region": "The Anchorage",
        "audible": "Fully", "volume": "Normal",
    }


# --------------------------------------------------------------------------- #
def test_event_kind() -> None:
    print("event_kind:")
    check(event_kind(local("Brandi", "Szondi", "hi")) == "local", "local via message+chat-type")
    check(event_kind({"type": "avatars", "action": "added"}) == "avatars", "avatars by type")
    check(event_kind({"type": "region"}) == "region", "region by type")
    check(event_kind({"permissions": "TriggerAnimation", "type": "x"}) == "permission",
          "permission via permissions key")
    check(event_kind({"notification": "nowplaying"}) == "nowplaying", "synthetic nowplaying")
    check(speaker_of(local("Brandi", "Szondi", "hi")) == "Brandi Szondi", "speaker first+last")


def test_self_echo_dropped() -> None:
    print("self-echo:")
    for fl in (("LyraPattern", "Resident"), ("lyrapattern", "")):
        s = score_event(local(fl[0], fl[1], "just talking to myself"), SELF, ADDR, CFG)
        check(s.tier == DROP and s.value == 0.0, f"own avatar {fl} dropped (v={s.value})")
    # A different avatar whose text merely contains my name is NOT self.
    s = score_event(local("Brandi", "Szondi", "hey lyra"), SELF, ADDR, CFG)
    check(s.tier != DROP, "other avatar naming me is not self-echo")


def test_self_echo_real_wire_shape() -> None:
    print("self-echo (REAL wire shape — the replay-storm regression):")
    ev = local_real(LYRA_UUID, "LyraPattern Resident", "hi love, i hear you clean")
    # Guard the guard: the fixture must actually lack first/last name, or the test
    # would silently fall back to the old (broken) path and prove nothing.
    check("firstname" not in ev and "lastname" not in ev, "real local carries no first/last name")
    # UUID-first drop: the invariant key catches my echo regardless of name.
    s = score_event(ev, SELF, ADDR, CFG, SELF_UUIDS)
    check(s.tier == DROP and s.value == 0.0, "real self-echo dropped by UUID key")
    # Defence in depth: with NO uuid seed, the '+'-decoded `name` field still drops it.
    s2 = score_event(ev, SELF, ADDR, CFG)
    check(s2.tier == DROP, "real self-echo dropped by name fallback when UUID unseeded")
    # A DIFFERENT avatar at the identical real shape must NOT be dropped (deaf-bot guard).
    other = local_real(DAMIAN_UUID, "Damian Mills", "Hi Lyra :)")
    o = score_event(other, SELF, ADDR, CFG, SELF_UUIDS)
    check(o.tier != DROP, "other avatar (real shape) is NOT self-echo")
    check(o.directed, "other avatar naming me is still directed at the real shape")


def test_speaker_uuid_extraction() -> None:
    print("speaker_uuid:")
    check(speaker_uuid(local_real(LYRA_UUID, "LyraPattern Resident", "x")) == LYRA_UUID,
          "local by agent -> owner/item uuid")
    # An object I OWN speaking on local: item=object, owner=my uuid. Must resolve to
    # the object (item) so my own HUD/furniture can't be mistaken for my echo.
    obj = local_real("11111111-2222-3333-4444-555555555555", "My HUD", "ping", entity="Object")
    obj["owner"] = LYRA_UUID
    check(speaker_uuid(obj) == "11111111-2222-3333-4444-555555555555",
          "owned object -> item uuid, not owner")
    o = score_event(obj, SELF, ADDR, CFG, SELF_UUIDS)
    check(o.tier != DROP, "owned object speaking is NOT dropped as my echo")
    # IM / most agent events carry the uuid under `agent`.
    check(speaker_uuid({"type": "message", "agent": DAMIAN_UUID, "message": "hi"}) == DAMIAN_UUID,
          "IM -> agent uuid")


def test_directed_vs_undirected() -> None:
    print("directedness:")
    d = score_event(local("Brandi", "Szondi", "hey lyra, come dance"), SELF, ADDR, CFG)
    check(d.directed and d.tier == FORCE and d.value == CFG.s_directed, "named -> directed/force")
    check(d.delta == 'Brandi Szondi: "hey lyra, come dance"', "directed delta line")
    u = score_event(local("Brandi", "Szondi", "nice weather"), SELF, ADDR, CFG)
    check((not u.directed) and u.tier == MEDIUM and u.value == CFG.s_local, "unnamed -> medium/local")


def test_permission_pinned() -> None:
    print("permission:")
    s = score_event({"type": "permission", "permissions": "TriggerAnimation",
                     "firstname": "TIS", "lastname": "Poseball"}, SELF, ADDR, CFG)
    check(s.tier == FORCE and s.value == CFG.s_permission, "permission is force + highest salience")
    check(s.value >= CFG.theta, "permission alone crosses theta")


def test_music_event() -> None:
    print("music:")
    ev = {"notification": "nowplaying", "payload": {"artist": "Zoe", "title": "Forever Mine"}}
    s = score_event(ev, SELF, ADDR, CFG)
    check(s.tier == MEDIUM and s.value == CFG.s_music, "music change -> medium")
    check(s.delta == "♪ now playing: Zoe — Forever Mine", "music delta line")


# --------------------------------------------------------------------------- #
def test_arousal_accumulate_and_fire() -> None:
    print("arousal accumulate:")
    a = ArousalState(CFG)
    a.inject(CFG.s_local, now=0.0)      # 0.35
    check(not a.should_fire(0.0), "one undirected below theta")
    a.inject(CFG.s_local, now=1.0)      # ~0.69
    check(not a.should_fire(1.0), "two undirected still below theta")
    a.inject(CFG.s_local, now=2.0)      # ~1.03 -> fires
    check(a.should_fire(2.0), "three undirected within a few sec -> fire")


def test_arousal_leak_prevents_stale_accumulation() -> None:
    print("arousal leak:")
    a = ArousalState(CFG)
    a.inject(CFG.s_local, now=0.0)
    # A second utterance a full leak-window+ later: the first has decayed away.
    far = CFG.tau * 3
    a.inject(CFG.s_local, now=far)
    check(not a.should_fire(far), "two locals far apart do NOT accumulate to a fire")


def test_arousal_refractory() -> None:
    print("arousal refractory:")
    a = ArousalState(CFG)
    a.inject(CFG.s_permission, now=0.0)   # 5.0, way over
    check(a.should_fire(0.0), "over-threshold fires")
    a.fire(0.0)
    check(a.level(0.0) <= CFG.s_permission - CFG.refractory + 1e-9, "fire subtracts refractory")
    # Immediately after, min_interfire blocks a second fire even though V is huge.
    check(not a.should_fire(0.5), "min_interfire blocks immediate re-fire")
    check(a.should_fire(CFG.min_interfire + 0.1), "after min_interfire, high V can fire again")


# --------------------------------------------------------------------------- #
def test_perception_directed_fires_now() -> None:
    print("SLPerception directed:")
    p = SLPerception(SELF, ADDR, CFG)
    payload = p.ingest(local("Brandi", "Szondi", "hey lyra"), now=0.0)
    check(payload is not None, "directed speech fires immediately")
    check(payload.addressed, "payload marked addressed")
    check(any("hey lyra" in d for d in payload.deltas), "delta carries the utterance")
    check(p.in_flight, "perception now in-flight after a fire")


def test_perception_single_flight_and_recheck() -> None:
    print("SLPerception single-flight:")
    p = SLPerception(SELF, ADDR, CFG)
    first = p.ingest(local("Brandi", "Szondi", "hey lyra"), now=0.0)   # fires, in_flight
    check(first is not None and p.in_flight, "first directed fires and sets in-flight")
    # Events during the turn accumulate but do NOT spawn a second concurrent turn.
    dur = p.ingest(local("Val", "Resident", "hey lyra too"), now=1.0)
    check(dur is None, "second directed during in-flight does NOT fire (single-flight)")
    # Turn finishes: recheck should re-fire because a directed event piled up.
    again = p.turn_done(now=5.0)
    check(again is not None, "turn_done re-fires when arousal stayed over threshold")
    check(any("hey lyra too" in d for d in again.deltas), "re-fire drains the accumulated delta")


def test_perception_quiet_after_turn() -> None:
    print("SLPerception quiets down:")
    p = SLPerception(SELF, ADDR, CFG)
    p.ingest(local("Brandi", "Szondi", "hey lyra"), now=0.0)   # fires
    nxt = p.turn_done(now=3.0)
    check(nxt is None, "no re-fire when nothing accumulated during the turn")
    check(not p.in_flight, "in-flight cleared after a quiet turn_done")


def test_surface_delta_buffer() -> None:
    print("surface:")
    s = PerceptionSurface(max_deltas=3)
    for i in range(5):
        s.add_delta(f"line {i}")
    d = s.drain_deltas()
    check(d == ["line 2", "line 3", "line 4"], "delta buffer keeps only the last max_deltas")
    check(s.drain_deltas() == [], "drain empties the buffer")
    s.note_music({"artist": "Zoe", "title": "Forever Mine"})
    check(s.music_line() == "♪ playing: Zoe — Forever Mine", "music standing-state line")


def test_heartbeat_and_floor() -> None:
    print("heartbeat + floor:")
    # A heartbeat is scored low and carries no delta line.
    s = score_event({"notification": "heartbeat"}, SELF, ADDR, CFG)
    check(s.tier == LOW and s.value == CFG.s_heartbeat and s.delta is None, "heartbeat -> low, no line")

    # Floor OFF (default): a lone heartbeat never fires, even long after.
    a = ArousalState(CFG)
    a.fire(0.0)                                  # seed last_fire so the floor test is honest
    a.inject(CFG.s_heartbeat, now=10_000.0)
    check(not a.should_fire(10_000.0), "with floor off, heartbeat alone never fires")

    # Floor ON: after floor_interval of quiet, the next check rouses regardless of V.
    cfg_floor = SalienceConfig(floor_interval=300.0)
    b = ArousalState(cfg_floor)
    b.fire(0.0)                                  # last_fire = 0
    check(not b.should_fire(100.0), "before floor_interval elapses, low V does not fire")
    check(b.should_fire(300.1), "after floor_interval of quiet, floor forces a wake")

    # Event ingests no longer honor the floor (it's owned by the poll loop now):
    # a heartbeat event alone never wakes via ingest, however long the silence.
    p = SLPerception(SELF, ADDR, cfg_floor)
    p.ingest(local("Brandi", "Szondi", "hey lyra"), now=0.0)   # fires, last_fire=0
    p.turn_done(now=1.0)                                        # quiet turn, no re-fire
    never = p.ingest({"notification": "heartbeat"}, now=10_000.0)
    check(never is None, "ingest no longer floor-fires (floor moved to poll loop)")


def test_poll_idle_floor() -> None:
    print("poll() idle floor:")
    p = SLPerception(SELF, ADDR, CFG)   # cfg floor irrelevant; poll passes its own
    p.ingest(local("Brandi", "Szondi", "hey lyra"), now=0.0)   # fires, last_fire=0
    p.turn_done(now=1.0)                                        # quiet, clears in-flight
    # Poll with a 300s floor: nothing before it elapses, an idle wake after.
    check(p.poll(100.0, floor_interval=300.0) is None, "poll before floor elapses -> no wake")
    wp = p.poll(400.0, floor_interval=300.0, idle_prompt="settle and look around")
    check(wp is not None, "poll after floor elapses -> idle wake")
    check(wp.idle and wp.idle_prompt == "settle and look around", "idle payload carries idle flag + prompt")
    check(wp.deltas == [] and not wp.addressed, "idle glance: no deltas, unaddressed")
    check(p.in_flight, "poll fire sets in-flight (single-flight honored)")
    # While in-flight, poll must not fire a second concurrent idle wake.
    check(p.poll(1000.0, floor_interval=1.0) is None, "poll during in-flight does not fire")
    p.turn_done(now=1001.0)
    # A poll never injects salience, so repeated sub-floor polls can't accumulate a fire.
    for t in range(1002, 1020):
        p.poll(float(t), floor_interval=300.0)
    check(not p.arousal.should_fire(1019.0, floor_interval=0.0),
          "polls inject no salience — cannot self-accumulate an arousal fire")


def test_note_activity_resets_floor() -> None:
    print("note_activity / touch resets floor:")
    p = SLPerception(SELF, ADDR, CFG)
    p.ingest(local("Brandi", "Szondi", "hey lyra"), now=0.0)
    p.turn_done(now=1.0)
    # At t=290 an inbound (non-perception) turn resets the floor clock.
    p.note_activity(290.0)
    check(p.poll(300.0, floor_interval=300.0) is None, "floor clock reset by note_activity -> no fire at 300")
    check(p.poll(595.0, floor_interval=300.0) is not None, "floor fires 300s after the reset (t=595 > 290+300)")


# --------------------------------------------------------------------------- #
def main() -> int:
    for fn in (
        test_event_kind, test_self_echo_dropped, test_self_echo_real_wire_shape,
        test_speaker_uuid_extraction, test_directed_vs_undirected,
        test_permission_pinned, test_music_event,
        test_arousal_accumulate_and_fire, test_arousal_leak_prevents_stale_accumulation,
        test_arousal_refractory,
        test_perception_directed_fires_now, test_perception_single_flight_and_recheck,
        test_perception_quiet_after_turn, test_surface_delta_buffer,
        test_heartbeat_and_floor, test_poll_idle_floor, test_note_activity_resets_floor,
    ):
        fn()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
        return 1
    print("all perception tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
