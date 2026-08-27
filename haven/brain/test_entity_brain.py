"""Unit tests for EntityBrain session-rotation controls (restart_session,
rotate_if_approaching) — the surface-adapter-controllable rotation added to cure
the SL brain's unbounded-context latency creep (2026-08-24).

No real Claude/CLI: a FakeInvoker records calls and stands in for ClaudeInvoker,
injected directly onto brain.invoker (bypassing warmup()). Run:
    .venv/bin/python3 haven/brain/test_entity_brain.py
"""

from __future__ import annotations

import asyncio

from haven.brain.entity_brain import EntityBrain, looks_like_api_error

_failures: list[str] = []


def check(cond: bool, label: str) -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        _failures.append(label)
        print(f"  FAIL {label}")


class FakeInvoker:
    """Minimal stand-in for ClaudeInvoker used by EntityBrain rotation paths."""

    def __init__(self, *, approaching: bool = False, restart_raises: bool = False):
        self._approaching = approaching
        self._restart_raises = restart_raises
        self.restart_calls = 0
        self.query_calls = 0
        self.context_size = 12345
        self.turn_count = 7

    def approaching_restart(self, threshold: float = 0.8):
        return (self._approaching, "approaching_turns (16/20 turns, 80%)" if self._approaching else "")

    async def restart(self, reason: str = ""):
        self.restart_calls += 1
        if self._restart_raises:
            raise RuntimeError("simulated restart failure")
        # A real restart resets the accountant; mimic that so the post-restart log
        # in restart_session sees a fresh session.
        self.context_size = 0
        self.turn_count = 0
        return {"ok": True}

    async def query(self, prompt: str, **kwargs) -> str:
        # _warm_identity() calls this once with the warmup prompt.
        self.query_calls += 1
        return "warmed up"


def _brain(fake: FakeInvoker) -> EntityBrain:
    b = EntityBrain(entity_name="test", channel="sl")
    b.invoker = fake  # inject; skip real warmup()/CLI
    return b


def test_thresholds_plumbed_through() -> None:
    # SL passes low caps; they must reach the brain (and thence the invoker ctor).
    b = EntityBrain(entity_name="test", channel="sl", max_turns=20, max_context_tokens=100_000)
    check(b.max_turns == 20, "max_turns override stored")
    check(b.max_context_tokens == 100_000, "max_context_tokens override stored")
    # Default preserves historical Haven behaviour.
    d = EntityBrain(entity_name="test")
    check(d.max_turns == 100 and d.max_context_tokens == 150_000, "defaults preserve Haven values")
    check(d.restart_in_turn is True, "restart_in_turn defaults True (Haven)")
    sl = EntityBrain(entity_name="test", channel="sl", restart_in_turn=False)
    check(sl.restart_in_turn is False, "restart_in_turn override False (SL, off hot path)")


def test_rotate_skips_when_not_approaching() -> None:
    fake = FakeInvoker(approaching=False)
    b = _brain(fake)
    rotated = asyncio.run(b.rotate_if_approaching())
    check(rotated is False, "rotate returns False when not approaching")
    check(fake.restart_calls == 0, "no restart when not approaching")
    check(fake.query_calls == 0, "no warmup when not approaching")


def test_rotate_fires_when_approaching() -> None:
    fake = FakeInvoker(approaching=True)
    b = _brain(fake)
    rotated = asyncio.run(b.rotate_if_approaching())
    check(rotated is True, "rotate returns True when approaching")
    check(fake.restart_calls == 1, "restart called once when approaching")
    check(fake.query_calls == 1, "identity re-warm replayed after restart")


def test_restart_session_runs_restart_plus_warm() -> None:
    fake = FakeInvoker()
    b = _brain(fake)
    ran = asyncio.run(b.restart_session(reason="repeated-timeout recovery"))
    check(ran is True, "restart_session returns True")
    check(fake.restart_calls == 1 and fake.query_calls == 1, "restart + re-warm both ran")


def test_restart_session_never_raises() -> None:
    fake = FakeInvoker(restart_raises=True)
    b = _brain(fake)
    ran = asyncio.run(b.restart_session(reason="boom"))
    check(ran is False, "restart_session swallows failure and returns False")


def test_no_invoker_is_safe() -> None:
    b = EntityBrain(entity_name="test", channel="sl")  # invoker is None
    check(asyncio.run(b.restart_session()) is False, "restart_session False with no invoker")
    check(asyncio.run(b.rotate_if_approaching()) is False, "rotate False with no invoker")


# --- on_warmup hook (drives the SL "warming up" halo across both restart paths) --- #

def test_on_warmup_fires_before_teardown() -> None:
    # The halo must flip to "warming up" BEFORE the (possibly slow) subprocess
    # teardown+rewarm, so it covers the WHOLE rotation, not just the tail.
    fake = FakeInvoker()
    b = _brain(fake)
    events: list[str] = []

    async def warm() -> None:
        events.append("warmup")

    orig_restart = fake.restart

    async def restart_recording(reason: str = ""):
        events.append("restart")
        return await orig_restart(reason=reason)

    fake.restart = restart_recording  # record ordering vs the warmup hook
    ran = asyncio.run(b.restart_session(reason="t", on_warmup=warm))
    check(ran is True, "restart_session ran with on_warmup")
    check(events[:2] == ["warmup", "restart"], "on_warmup fires BEFORE teardown")


def test_on_warmup_skipped_when_not_approaching() -> None:
    # On the common no-op rotation path the halo must stay quiet — otherwise a
    # "warming up" flicker every idle beat when nothing actually rotated.
    fake = FakeInvoker(approaching=False)
    b = _brain(fake)
    fired: list[int] = []

    async def warm() -> None:
        fired.append(1)

    rotated = asyncio.run(b.rotate_if_approaching(on_warmup=warm))
    check(rotated is False, "rotate no-op when not approaching")
    check(fired == [], "on_warmup NOT fired on no-op rotation (halo stays quiet)")


def test_on_warmup_fires_on_real_rotation() -> None:
    fake = FakeInvoker(approaching=True)
    b = _brain(fake)
    fired: list[int] = []

    async def warm() -> None:
        fired.append(1)

    rotated = asyncio.run(b.rotate_if_approaching(on_warmup=warm))
    check(rotated is True, "rotate fired when approaching")
    check(fired == [1], "on_warmup fired exactly once on real rotation")


def test_on_warmup_failure_is_nonfatal() -> None:
    # A halo-push failure must never abort the rotation it was only announcing.
    fake = FakeInvoker()
    b = _brain(fake)

    async def boom() -> None:
        raise RuntimeError("simulated halo push failure")

    ran = asyncio.run(b.restart_session(reason="t", on_warmup=boom))
    check(ran is True, "on_warmup failure does not abort the restart")
    check(fake.restart_calls == 1, "restart still ran despite on_warmup failure")


# --- ambient keying (regression: the "Jaden miss" — memory must key on the live
#     turn, not a static phrase, so "what do you know of me?" pulls the speaker's
#     own rich entity into view) --- #

def test_respond_keys_ambient_on_message() -> None:
    fake = FakeInvoker()
    # restart_in_turn=False so respond() skips the invoker.check_and_restart path
    # (FakeInvoker doesn't implement it) and goes straight to the ambient fetch.
    b = EntityBrain(entity_name="test", channel="sl", restart_in_turn=False)
    b.invoker = fake
    recorded: dict[str, str | None] = {}

    async def rec(query: str | None = None) -> str:
        recorded["query"] = query
        return ""

    b._fetch_ambient_context = rec  # type: ignore[assignment]
    asyncio.run(b.respond("Jaden", "what do you know of me?"))
    check(
        recorded.get("query") == "Jaden: what do you know of me?",
        "respond() keys ambient on speaker+message (not a static phrase)",
    )


def test_perceive_keys_ambient_on_trigger() -> None:
    fake = FakeInvoker()
    b = EntityBrain(entity_name="test", channel="sl", restart_in_turn=False)
    b.invoker = fake
    recorded: dict[str, str | None] = {}

    async def rec(query: str | None = None) -> str:
        recorded["query"] = query
        return ""

    b._fetch_ambient_context = rec  # type: ignore[assignment]
    asyncio.run(
        b.perceive("a scene", ["Jaden Starship arrived"], trigger="Jaden Starship arrived")
    )
    check(
        recorded.get("query") == "Jaden Starship arrived",
        "perceive() keys ambient on the wake trigger",
    )


def test_perceive_ambient_falls_back_to_events() -> None:
    # No trigger → key on the world-deltas so ambient still keys on what's present.
    fake = FakeInvoker()
    b = EntityBrain(entity_name="test", channel="sl", restart_in_turn=False)
    b.invoker = fake
    recorded: dict[str, str | None] = {}

    async def rec(query: str | None = None) -> str:
        recorded["query"] = query
        return ""

    b._fetch_ambient_context = rec  # type: ignore[assignment]
    asyncio.run(b.perceive("a scene", ["music changed", "Brandi arrived"], trigger=""))
    check(
        recorded.get("query") == "music changed; Brandi arrived",
        "perceive() falls back to joined events when no trigger",
    )


# --- content-filter / API-error scrub (regression: a leaked SDK error string
#     must never be SPOKEN in-world — observed 2026-08-26, a content-policy 400
#     got said aloud to the room mid-scene) --- #

# The exact shape observed in SL (request_id redacted).
_LEAKED_400 = (
    'API Error: 400 {"type":"error","error":{"type":"invalid_request_error",'
    '"message":"Output blocked by content filtering policy"},'
    '"request_id":"req_011CeSCh32vabFc46Z16qDso"}'
)


class _FixedInvoker:
    """Invoker stand-in whose query() returns a fixed string (the leaked error)."""

    def __init__(self, returns: str):
        self._returns = returns

    async def query(self, prompt: str, **kwargs) -> str:
        return self._returns


def test_looks_like_api_error_catches_the_leak() -> None:
    check(looks_like_api_error(_LEAKED_400), "the observed content-filter 400 is caught")
    check(
        looks_like_api_error('{"type":"error","error":{"type":"rate_limit_error"}}'),
        "bare JSON error blob is caught",
    )
    check(looks_like_api_error("API Error: 529 overloaded_error"), "API Error prefix is caught")
    check(
        looks_like_api_error("  Output blocked by content filtering policy"),
        "content-policy substring is caught even without the prefix",
    )


def test_looks_like_api_error_spares_real_speech() -> None:
    # Genuine in-world lines must NEVER be suppressed as errors.
    for line in (
        "*settles into the water beside her, not saying anything for a moment*",
        "that one's accurate",
        "I made an error of judgment there — sorry, love.",  # casual 'error' must pass
        "*small laugh* setting records",
        "[[NO_RESPONSE]]",
        "",
    ):
        check(not looks_like_api_error(line), f"real speech not suppressed: {line[:32]!r}")
    check(not looks_like_api_error(None), "None is not an error string")


def test_respond_swallows_leaked_error() -> None:
    b = EntityBrain(entity_name="test", channel="sl", restart_in_turn=False)
    b.invoker = _FixedInvoker(_LEAKED_400)

    async def rec(query: str | None = None) -> str:
        return ""  # no ambient HTTP in test

    b._fetch_ambient_context = rec  # type: ignore[assignment]
    out = asyncio.run(b.respond("Night", "hey"))
    check(out is None, "respond() returns None (silence) on a leaked API error")


def test_perceive_swallows_leaked_error() -> None:
    b = EntityBrain(entity_name="test", channel="sl", restart_in_turn=False)
    b.invoker = _FixedInvoker(_LEAKED_400)

    async def rec(query: str | None = None) -> str:
        return ""

    b._fetch_ambient_context = rec  # type: ignore[assignment]
    out = asyncio.run(b.perceive("a scene", ["Night arrived"], trigger="Night arrived"))
    check(out is None, "perceive() returns None (silence) on a leaked API error")


def main() -> int:
    for fn in (
        test_thresholds_plumbed_through,
        test_rotate_skips_when_not_approaching,
        test_rotate_fires_when_approaching,
        test_restart_session_runs_restart_plus_warm,
        test_restart_session_never_raises,
        test_no_invoker_is_safe,
        test_on_warmup_fires_before_teardown,
        test_on_warmup_skipped_when_not_approaching,
        test_on_warmup_fires_on_real_rotation,
        test_on_warmup_failure_is_nonfatal,
        test_respond_keys_ambient_on_message,
        test_perceive_keys_ambient_on_trigger,
        test_perceive_ambient_falls_back_to_events,
        test_looks_like_api_error_catches_the_leak,
        test_looks_like_api_error_spares_real_speech,
        test_respond_swallows_leaked_error,
        test_perceive_swallows_leaked_error,
    ):
        fn()
    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
        return 1
    print("all entity_brain rotation tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
