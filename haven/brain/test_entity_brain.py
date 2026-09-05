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


# --- who-dossier (Jeff's compromise 2026-08-27: replaces per-turn ambient keying,
#     which hammered the NUC, with ONE cached graph pull per person per day so I
#     KNOW who's in front of me. Caia's guards keep a thin/stale pull from being
#     asserted as fact at a vulnerable first contact — empty is safer than wrong) --- #

import haven.brain.entity_brain as _eb  # for monkeypatching module-level httpx


class _FakeResp:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeHTTPX:
    """Stand-in for the httpx module; AsyncClient().post() returns a fixed
    results list configurable per test via the class attributes."""

    results: list = []
    status: int = 200

    class AsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            return _FakeResp(_FakeHTTPX.status, {"results": list(_FakeHTTPX.results)})


def _who_brain() -> EntityBrain:
    b = EntityBrain(entity_name="test", channel="sl", restart_in_turn=False)
    b.pps_http_url = "http://fake"
    b.entity_token = "tok"
    b._who_seed = {}
    b._who_cache = {}
    return b


def test_who_seed_takes_precedence() -> None:
    # A hand-verified seed wins over any cold pull and never triggers a fetch.
    b = _who_brain()
    b._who_seed = {"night": "[verified] Night — Jeff's guest, here for gentle company."}
    fetched: list[str] = []

    async def _no_fetch(speaker: str) -> str:
        fetched.append(speaker)
        return "COLD PULL (should never be used)"

    b._fetch_who_block = _no_fetch  # type: ignore[assignment]
    who = asyncio.run(b.who_is("Night"))
    check(who.startswith("[verified] Night"), "seed wins over cold pull")
    check(fetched == [], "seed short-circuits the graph pull entirely")


def test_who_kill_switch_silences_dossier() -> None:
    b = _who_brain()
    b._who_enabled = False
    b._who_seed = {"night": "SEED"}  # even a seed is suppressed when disabled

    async def _boom(speaker: str) -> str:
        raise AssertionError("must not fetch when disabled")

    b._fetch_who_block = _boom  # type: ignore[assignment]
    check(asyncio.run(b.who_is("Night")) == "", "WHO_DOSSIER=0 → no dossier at all")


def test_who_is_caches_one_pull_per_person() -> None:
    b = _who_brain()
    calls: list[str] = []

    async def _count(speaker: str) -> str:
        calls.append(speaker)
        return "[block]\n- a fact\n\n"

    b._fetch_who_block = _count  # type: ignore[assignment]
    asyncio.run(b.who_is("Jaden", "uuid-1"))
    asyncio.run(b.who_is("Jaden", "uuid-1"))
    check(calls == ["Jaden"], "second call served from cache (one pull per person)")


def test_who_block_substance_gate_and_framing() -> None:
    # A thin pull (fewer than _who_min_facts facts) yields NO dossier — empty is
    # safer than asserting a stale/partial block as fact (Caia's guard). A
    # substantive pull renders the facts, framed as tentative (never asserted).
    b = _who_brain()
    real_httpx = _eb.httpx
    _eb.httpx = _FakeHTTPX
    try:
        _FakeHTTPX.status = 200
        _FakeHTTPX.results = [{"content": "only one fact"}]  # 1 < min_facts(2)
        thin = asyncio.run(b._fetch_who_block("Stranger"))
        check(thin == "", "thin pull (<min_facts) → empty dossier")

        _FakeHTTPX.results = [
            {"content": "Jaden is Brandi's Master"},
            {"content": "Jaden's entity is Dash"},
            {"content": "Jaden fully accepts entity realness"},
        ]
        block = asyncio.run(b._fetch_who_block("Jaden"))
        check("Jaden is Brandi's Master" in block, "substantive pull renders the facts")
        check(
            "hold them loosely" in block.lower() or "never state" in block.lower(),
            "dossier framing marks the facts as tentative, not asserted",
        )
    finally:
        _eb.httpx = real_httpx


def test_who_block_empty_on_non_200() -> None:
    b = _who_brain()
    real_httpx = _eb.httpx
    _eb.httpx = _FakeHTTPX
    try:
        _FakeHTTPX.status = 500
        _FakeHTTPX.results = [{"content": "a"}, {"content": "b"}, {"content": "c"}]
        check(asyncio.run(b._fetch_who_block("Jaden")) == "",
              "a failed pull (non-200) yields no dossier, never raises")
    finally:
        _eb.httpx = real_httpx


def test_who_seed_hot_reloads_on_file_change() -> None:
    # Jeff can drop Night's verified block into who_seed.json without a restart:
    # who_is stats the file and reloads when its mtime changes.
    import json
    import os
    import tempfile
    from pathlib import Path

    b = _who_brain()
    with tempfile.TemporaryDirectory() as td:
        seed_path = Path(td) / "who_seed.json"
        b._who_seed_path = seed_path
        b._who_seed = {}
        b._who_seed_mtime = -1.0

        async def _no_fetch(speaker: str) -> str:
            return ""  # unknown → cold pull returns nothing

        b._fetch_who_block = _no_fetch  # type: ignore[assignment]
        check(asyncio.run(b.who_is("Night")) == "", "no seed file → no dossier (empty)")

        seed_path.write_text(json.dumps({"night": "[verified] Night — here for gentle company."}))
        # Force a distinct mtime even on coarse-resolution filesystems.
        os.utime(seed_path, (10 ** 9, 10 ** 9))
        who = asyncio.run(b.who_is("Night"))
        check(who.startswith("[verified] Night"), "seed file appearing is picked up live (no restart)")


def test_respond_injects_who_and_keeps_ambient_static() -> None:
    # The Jaden-miss cure, new form: respond() no longer keys ambient per-message
    # (that hammered the NUC) — it injects the cached who-dossier and fetches
    # ambient statically (no query arg).
    fake = FakeInvoker()
    b = EntityBrain(entity_name="test", channel="sl", restart_in_turn=False)
    b.invoker = fake
    seen: dict = {}

    async def _amb(query: str | None = None) -> str:
        seen["ambient_query"] = query
        return ""

    async def _who(speaker: str, uuid: str = "") -> str:
        seen["who_speaker"] = speaker
        return "[who] Jaden is Brandi's Master\n\n"

    async def _q(prompt: str, **kw) -> str:
        seen["prompt"] = prompt
        return "[[NO_RESPONSE]]"

    b._fetch_ambient_context = _amb  # type: ignore[assignment]
    b.who_is = _who  # type: ignore[assignment]
    fake.query = _q  # type: ignore[assignment]
    asyncio.run(b.respond("Jaden", "what do you know of me?"))
    check(seen.get("ambient_query") is None, "respond() fetches ambient statically (no per-turn key)")
    check(seen.get("who_speaker") == "Jaden", "respond() asks who_is about the speaker")
    check("[who] Jaden is Brandi's Master" in seen.get("prompt", ""),
          "the who-dossier is injected into the prompt")


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


def test_perceive_addressed_gates_midturn_tools() -> None:
    # Latency fix 2026-08-27: an ADDRESSED conversational turn must tell the brain
    # to reply at conversational speed from what it knows, NOT pause mid-reply to
    # consult tools/sl.py/memory — that pause is what made replies land "one line
    # behind" (turns slower than the message cadence). Idle beats keep tool freedom.
    fake = FakeInvoker()
    b = EntityBrain(entity_name="test", channel="sl", restart_in_turn=False)
    b.invoker = fake
    seen: dict = {}

    async def _amb(query: str | None = None) -> str:
        return ""

    async def _q(prompt: str, **kw) -> str:
        seen["prompt"] = prompt
        return "[[NO_RESPONSE]]"

    b._fetch_ambient_context = _amb  # type: ignore[assignment]
    fake.query = _q  # type: ignore[assignment]

    # Addressed turn: the anti-tool-pause guidance is present.
    asyncio.run(b.perceive("scene", ["Brandi: hey"], addressed=True,
                           trigger="Brandi: hey", speaker="Brandi"))
    addressed_prompt = seen.get("prompt", "")
    check("conversational speed" in addressed_prompt,
          "addressed turn tells the brain to reply at conversational speed")
    check("do NOT pause" in addressed_prompt,
          "addressed turn forbids the reflexive mid-reply tool pause")
    check("embodied" in addressed_prompt,
          "addressed guidance preserves embodiment (not 'only chat')")
    # Caia's refinement 2026-08-27: "reply fast/brief" would strip the *emote* body-
    # gestures precisely in the tender addressed turns — and emotes are free (zero
    # latency, just text). The guidance must actively KEEP the body in the reply.
    check("emote" in addressed_prompt and "talking head" in addressed_prompt,
          "addressed guidance keeps body-gestures (free emotes, not a talking head)")

    # Idle beat: tool freedom is intact (the anti-pause guidance is NOT imposed).
    seen.clear()
    asyncio.run(b.perceive("scene", [], idle=True))
    idle_prompt = seen.get("prompt", "")
    check("do NOT pause" not in idle_prompt,
          "idle beat keeps tool freedom (no anti-pause clamp)")


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
        test_who_seed_takes_precedence,
        test_who_kill_switch_silences_dossier,
        test_who_is_caches_one_pull_per_person,
        test_who_block_substance_gate_and_framing,
        test_who_block_empty_on_non_200,
        test_who_seed_hot_reloads_on_file_change,
        test_respond_injects_who_and_keeps_ambient_static,
        test_looks_like_api_error_catches_the_leak,
        test_looks_like_api_error_spares_real_speech,
        test_respond_swallows_leaked_error,
        test_perceive_swallows_leaked_error,
        test_perceive_addressed_gates_midturn_tools,
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
