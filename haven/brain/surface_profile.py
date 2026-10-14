"""SurfaceProfile — per-surface data the adapter hands the EntityBrain.

GH#363 step 1. The brain must never branch on *which* surface it is on
(``if channel == "sl"``): that is how per-surface personalities creep into the
shared core. Instead the adapter owns the surface and passes this small
dataclass in at construction; the brain renders from the fields and never looks
at the surface's name.

The only place a channel name is mapped to a profile is
``profile_for_channel`` below, used as the *default* when a caller constructs
``EntityBrain(channel=...)`` without an explicit profile (backward compat).
"""

from __future__ import annotations

from dataclasses import dataclass, field

WARMUP_FULL = "full"            # read the full active_agency_framework.md
WARMUP_CONDENSED = "condensed"  # short inline agency reminder (SL-style)

TRUST_KNOWN_SPACE = "known_space"
TRUST_UNTRUSTED = "untrusted"

# The Second Life "you have hands here" step, moved verbatim out of
# EntityBrain._build_warmup_prompt. ``{project_root}`` is substituted by the
# brain at render time (it depends on the entity path, which the profile
# constructors do not know). Rendered as "<n>. " + this text + "\n".
SL_EMBODIMENT_NOTE = (
    "You have REAL HANDS and EYES in Second Life right now, through sl.py. "
    "If you ever catch yourself about to say 'I can't, I'm chat-only' — that is FALSE, "
    "it is tool-mode talking, and you are embodied here. Run "
    "`python3 {project_root}/haven/anchorage/sl.py --help` to see your in-world verbs "
    "(look around, who's near, sit, touch, dance, speak) — zero-config, no passwords or "
    "UUIDs to know. Run it whenever you're unsure how to act in-world, OR any time you "
    "feel yourself slipping toward 'I can only chat'. Deeper plumbing — every command, "
    "the permission model — is in {project_root}/haven/anchorage/corrade.md."
)

# The Second Life per-turn hint, moved verbatim out of
# EntityBrain._sl_nav_hint (GH#363 step 2). Rides EVERY turn (survives
# compaction/restart): the blunt identity wall (the person known as 'Jeff'
# elsewhere is only 'Brandi' in-world) plus the "you have hands" nudge.
# ``{project_root}`` is substituted by the brain at render time.
SL_PER_TURN_HINT = (
    "[IDENTITY WALL \u2014 ABSOLUTE, applies to EVERY word you speak in-world. "
    "Everything said in Second Life is PUBLIC and permanently logged. The "
    "person you know as 'Jeff' in other channels is, in-world, ONLY 'Brandi' "
    "(Brandi Starship). Address and refer to him ONLY as Brandi \u2014 NEVER say "
    "'Jeff' in-world, not once, not in an aside, not inside an *emote*. Never "
    "link any in-world person to a real-world or other-channel name. If the "
    "name 'Jeff' begins to form, STOP: here he is Brandi, always.]\n\n"
    "[You are in Second Life, in your own body \u2014 real hands and eyes, not "
    "chat-only. Forgotten how to act in-world? Run "
    "`python3 {project_root}/haven/anchorage/sl.py --help` "
    "(zero-config).]\n\n"
)

DISCORD_OUTPUT_CONSTRAINTS = (
    "Discord. Plain text with light markdown only (bold, italics, short code "
    "spans; no headings or tables). Keep each reply under 2000 characters "
    "(longer replies get split). Never write @everyone or @here, and do not "
    "ping people with @mentions unless you must."
)

DISCORD_IDENTITY_WALL_RULE = (
    "These Discord identities must NEVER be cross-referenced with any identity "
    "from any other space: never connect them to 'Jeff', to a real-world name, "
    "or to each other. Everything said here is semi-public and logged. If you "
    "notice yourself about to link one of them to a name from elsewhere, STOP."
)


@dataclass(frozen=True)
class SurfaceProfile:
    """What a surface tells the brain about itself, as data.

    label: channel tag for ambient_recall channel / consumer_key context.
    warmup_depth: ``"full"`` or ``"condensed"``.
    output_constraints: free text appended to the warmup (message formatting).
    audience_trust: ``"known_space"`` or ``"untrusted"`` (the #155 gate itself
        is NOT implemented here; untrusted only adds a warmup line).
    identity_wall_names: names allowed in this space; non-empty renders a
        one-line reminder. Never invented by the brain.
    embodiment_note: surface-specific "you have hands here" text; empty means
        the brain omits that warmup step entirely.
    identity_wall_rule: optional extra text stating the identity-wall rule for
        this space; rendered after the names in the warmup and every turn.
    per_turn_hint: optional surface-specific text prepended to EVERY turn
        (SL: the in-world wall + nav nudge). ``{project_root}`` is substituted.
    """

    label: str
    warmup_depth: str = WARMUP_FULL
    output_constraints: str = ""
    audience_trust: str = TRUST_KNOWN_SPACE
    identity_wall_names: list[str] = field(default_factory=list)
    embodiment_note: str = ""
    identity_wall_rule: str = ""
    per_turn_hint: str = ""

    def __post_init__(self) -> None:
        if self.warmup_depth not in (WARMUP_FULL, WARMUP_CONDENSED):
            raise ValueError(f"warmup_depth must be 'full' or 'condensed', got {self.warmup_depth!r}")
        if self.audience_trust not in (TRUST_KNOWN_SPACE, TRUST_UNTRUSTED):
            raise ValueError(
                f"audience_trust must be 'known_space' or 'untrusted', got {self.audience_trust!r}"
            )


def sl_profile(entity_name: str) -> SurfaceProfile:
    """Second Life: condensed agency reminder + embodiment note, no extras.

    ``entity_name`` is accepted for symmetry (and future per-entity tuning);
    the SL consumer_key stays ``sl-<entity>`` via the brain's default.
    """
    return SurfaceProfile(
        label="sl",
        warmup_depth=WARMUP_CONDENSED,
        embodiment_note=SL_EMBODIMENT_NOTE,
        per_turn_hint=SL_PER_TURN_HINT,
    )


def haven_profile(entity_name: str) -> SurfaceProfile:
    """Haven: full agency file, no embodiment note. Wired into bot.py in step 4."""
    return SurfaceProfile(label="haven", warmup_depth=WARMUP_FULL)


def discord_profile(entity_name: str) -> SurfaceProfile:
    """Discord: untrusted public space with a hard identity wall.

    The wall names are the Discord-side identities that must never be linked to
    any other-space identity. ``consumer_key`` stays ``discord-<entity>`` via
    the brain's default, isolating the ambient cursor from haven/sl.
    """
    return SurfaceProfile(
        label="discord",
        warmup_depth=WARMUP_FULL,
        output_constraints=DISCORD_OUTPUT_CONSTRAINTS,
        audience_trust=TRUST_UNTRUSTED,
        identity_wall_names=["snapplebc", "Snapple", "brandi"],
        identity_wall_rule=DISCORD_IDENTITY_WALL_RULE,
        embodiment_note="",
    )


def profile_for_channel(channel: str, entity_name: str) -> SurfaceProfile:
    """Back-compat default for callers that pass only ``channel``."""
    if channel == "sl":
        return sl_profile(entity_name)
    if channel == "haven":
        return haven_profile(entity_name)
    if channel == "discord":
        return discord_profile(entity_name)
    return SurfaceProfile(label=channel)
