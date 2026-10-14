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
    """

    label: str
    warmup_depth: str = WARMUP_FULL
    output_constraints: str = ""
    audience_trust: str = TRUST_KNOWN_SPACE
    identity_wall_names: list[str] = field(default_factory=list)
    embodiment_note: str = ""

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
    )


def haven_profile(entity_name: str) -> SurfaceProfile:
    """Haven: full agency file, no embodiment note. Wired into bot.py in step 4."""
    return SurfaceProfile(label="haven", warmup_depth=WARMUP_FULL)


def profile_for_channel(channel: str, entity_name: str) -> SurfaceProfile:
    """Back-compat default for callers that pass only ``channel``."""
    if channel == "sl":
        return sl_profile(entity_name)
    if channel == "haven":
        return haven_profile(entity_name)
    return SurfaceProfile(label=channel)
