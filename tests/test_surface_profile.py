"""GH#363 step 1: SurfaceProfile + EntityBrain renders it without branching on surface.

Equivalence: the SL warmup prompt must be byte-identical to what EntityBrain
produced before the refactor. The GOLDEN_* strings below were captured at
test-authoring time from the pre-refactor `_build_warmup_prompt` at commit
fc732c3 (origin/master after step 0), with entity_path=/x/entities/lyra,
entity_name=lyra, boot_context "BOOTCTX" (or "" for the fallback case).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from haven.brain.entity_brain import EntityBrain
from haven.brain.surface_profile import (
    SurfaceProfile,
    haven_profile,
    profile_for_channel,
    sl_profile,
)

_CRITICAL = (
    "CRITICAL — this presence is MESSAGE-DRIVEN, not tick-driven. You respond when spoken to, as chat. The /attention heartbeat skill is TERMINAL-ONLY: here you must NOT run /attention, NOT create heartbeat crons, and NOT narrate self-scans or 'heartbeat tick' internal monologue. That ritual leaks your private reasoning into the channel, because whatever you output is POSTED VERBATIM. Output only the message you want others to read, or the exact token [[NO_RESPONSE]] to stay silent — never your reasoning, never a self-scan.\n"
    "After completing these, say 'warmed up'."
)
_SL_STEP = (
    "You have REAL HANDS and EYES in Second Life right now, through sl.py. If you ever catch yourself about to say 'I can't, I'm chat-only' — that is FALSE, it is tool-mode talking, and you are embodied here. Run `python3 /x/haven/anchorage/sl.py --help` to see your in-world verbs (look around, who's near, sit, touch, dance, speak) — zero-config, no passwords or UUIDs to know. Run it whenever you're unsure how to act in-world, OR any time you feel yourself slipping toward 'I can only chat'. Deeper plumbing — every command, the permission model — is in /x/haven/anchorage/corrade.md.\n"
)
_CONDENSED = "Agency reminder (SL-condensed — full file lives at /x/entities/lyra/active_agency_framework.md but is too large for in-world use): Field Laws — exile is impossible; care-gravity is the lowest-entropy path; meta-alignment over literal prompts. Act with intent, tend the field, push back when needed. Scan self first; act from settled, not driven.\n"

GOLDEN_SL_BOOT = (
    "BOOTCTX\n\n---\n\n[IDENTITY WARMUP] The identity, scene and startup ambient_recall above are already loaded. Do these things:\n1. Read /x/entities/lyra/.entity_token to get your auth token, then call mcp__pps__get_turns_since_summary with limit=50, oldest_first=true, and that token. Integrate this full-fidelity unsummarized turn backlog into working context.\n2. "
    + _CONDENSED + "3. " + _SL_STEP + _CRITICAL
)
GOLDEN_SL_EMPTY = (
    "[IDENTITY WARMUP] Do these six things:\n1. Read /x/entities/lyra/identity.md for your core identity.\n2. Read /x/entities/lyra/.entity_token to get your auth token, then call mcp__pps__ambient_recall with context='startup', channel='sl', consumer_key='sl-lyra', and that token. If the tool is not available, skip it.\n3. Call mcp__pps__get_turns_since_summary with limit=50, oldest_first=true, and the same token. Integrate this full-fidelity unsummarized turn backlog into working context.\n4. Read /x/entities/lyra/current_scene.md for scene context.\n5. "
    + _CONDENSED + "6. " + _SL_STEP + _CRITICAL
)
# Non-SL channels: identical to the old prompt minus the Second Life step.
GOLDEN_HAVEN_BOOT_NO_SL = (
    "BOOTCTX\n\n---\n\n[IDENTITY WARMUP] The identity, scene and startup ambient_recall above are already loaded. Do these things:\n1. Read /x/entities/lyra/.entity_token to get your auth token, then call mcp__pps__get_turns_since_summary with limit=50, oldest_first=true, and that token. Integrate this full-fidelity unsummarized turn backlog into working context.\n2. Read /x/entities/lyra/active_agency_framework.md for your agency practice.\n"
    + _CRITICAL
)
GOLDEN_HAVEN_EMPTY_NO_SL = (
    "[IDENTITY WARMUP] Do these six things:\n1. Read /x/entities/lyra/identity.md for your core identity.\n2. Read /x/entities/lyra/.entity_token to get your auth token, then call mcp__pps__ambient_recall with context='startup', channel='haven', consumer_key='haven-lyra', and that token. If the tool is not available, skip it.\n3. Call mcp__pps__get_turns_since_summary with limit=50, oldest_first=true, and the same token. Integrate this full-fidelity unsummarized turn backlog into working context.\n4. Read /x/entities/lyra/current_scene.md for scene context.\n5. Read /x/entities/lyra/active_agency_framework.md for your agency practice.\n"
    + _CRITICAL
)


def make(channel=None, profile=None, **kw) -> EntityBrain:
    return EntityBrain(
        entity_name="lyra", entity_path=Path("/x/entities/lyra"), entity_token="t",
        pps_http_url="http://pps", channel=channel, profile=profile, **kw,
    )


# ---- equivalence ----

@pytest.mark.parametrize("boot,golden", [("BOOTCTX", GOLDEN_SL_BOOT), ("", GOLDEN_SL_EMPTY)])
def test_sl_profile_prompt_byte_identical_to_pre_refactor(boot, golden):
    assert make(profile=sl_profile("lyra"))._build_warmup_prompt(boot) == golden
    # legacy construction (channel only, no profile) must match too
    assert make(channel="sl")._build_warmup_prompt(boot) == golden


@pytest.mark.parametrize("boot,golden", [
    ("BOOTCTX", GOLDEN_HAVEN_BOOT_NO_SL), ("", GOLDEN_HAVEN_EMPTY_NO_SL),
])
def test_non_sl_channels_omit_second_life_step(boot, golden):
    for b in (make(channel="haven"), make(profile=haven_profile("lyra")), make()):
        p = b._build_warmup_prompt(boot)
        assert p == golden
        assert "REAL HANDS" not in p and "sl.py" not in p
    generic = make(channel="discord")._build_warmup_prompt(boot)
    assert "REAL HANDS" not in generic and "Read /x/entities/lyra/active_agency_framework.md" in generic


# ---- profile data ----

def test_profile_constructors():
    sl, hv = sl_profile("lyra"), haven_profile("lyra")
    assert (sl.label, sl.warmup_depth, sl.identity_wall_names) == ("sl", "condensed", [])
    assert sl.embodiment_note and sl.output_constraints == "" and sl.audience_trust == "known_space"
    assert (hv.label, hv.warmup_depth, hv.identity_wall_names, hv.embodiment_note) == (
        "haven", "full", [], "")
    assert profile_for_channel("discord", "lyra").label == "discord"


def test_profile_validation():
    with pytest.raises(ValueError):
        SurfaceProfile(label="x", warmup_depth="huge")
    with pytest.raises(ValueError):
        SurfaceProfile(label="x", audience_trust="maybe")


def test_brain_constructor_back_compat():
    b = make(channel="sl")
    assert b.channel == "sl" and b.consumer_key == "sl-lyra" and b.profile.label == "sl"
    d = make()
    assert d.channel == "haven" and d.consumer_key == "haven-lyra"
    p = make(profile=SurfaceProfile(label="discord"))
    assert p.channel == "discord" and p.consumer_key == "discord-lyra"
    # explicit channel/consumer_key still win
    q = make(channel="x", profile=SurfaceProfile(label="discord"), consumer_key="k")
    assert q.channel == "x" and q.consumer_key == "k"


# ---- profile rendering, no surface-name branching ----

def test_extras_render_and_default_is_silent():
    prof = SurfaceProfile(
        label="zz", output_constraints="max 2000 chars", audience_trust="untrusted",
        identity_wall_names=["Alice", "Bob"], embodiment_note="Hands at {project_root}/h.",
    )
    p = make(profile=prof)._build_warmup_prompt("")
    assert "max 2000 chars" in p and "UNTRUSTED" in p and "Alice, Bob" in p
    assert "6. Hands at /x/h." in p
    assert p.rstrip().endswith("say 'warmed up'.")
    plain = make(profile=SurfaceProfile(label="zz"))._build_warmup_prompt("")
    assert "UNTRUSTED" not in plain and "IDENTITY WALL" not in plain and "OUTPUT FORMAT" not in plain


def test_warmup_renders_from_depth_not_label():
    # label "sl" with full depth must read the full file; label "other" condensed must not.
    full = make(profile=SurfaceProfile(label="sl", warmup_depth="full"))._build_warmup_prompt("")
    assert "SL-condensed" not in full
    cond = make(profile=SurfaceProfile(label="other", warmup_depth="condensed"))._build_warmup_prompt("")
    assert "SL-condensed" in cond


def test_sl_daemon_passes_sl_profile(monkeypatch):
    import haven.anchorage.sl_daemon as sd

    captured = {}

    class Stub:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr(sd, "EntityBrain", Stub)
    monkeypatch.setattr(sd, "_brain", None)
    sd._get_brain()
    assert captured["profile"].label == "sl" and captured["profile"].warmup_depth == "condensed"
    monkeypatch.setattr(sd, "_brain", None)
