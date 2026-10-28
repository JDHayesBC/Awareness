"""Haven — per-room settings vocabulary (#381).

Dependency-free so the server, the bot and the tests share one definition.
The server stores aliases; the bot maps an alias to a concrete model id.
"""

from __future__ import annotations

# Verbosity of the entity's replies in a room. "auto" resolves by room kind.
VERBOSITY_VALUES = ("auto", "short", "medium", "full")
DEFAULT_VERBOSITY = "auto"

# What "auto" means in a DM. Held at "short" (today's behaviour) until Jeff
# decides: flipping it to "full" lengthens his existing DMs, phone included
# (#381, Caia's sidebar). Per-room settings override it either way.
AUTO_DM_VERBOSITY = "short"

# Model aliases a room may select. None = "the bot's own CLAUDE_MODEL".
# Allowlist, not free text: the model changes cost (fable is ~3-4x opus).
MODEL_ALIASES: dict[str, str | None] = {
    "default": None,
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
    "fable": "claude-fable-5-1",
}
DEFAULT_MODEL = "default"


def resolve_verbosity(setting: str | None, is_dm: bool) -> str:
    """Effective verbosity (short|medium|full): auto is AUTO_DM_VERBOSITY for DMs, short for shared rooms."""
    if setting not in VERBOSITY_VALUES or setting == "auto":
        return AUTO_DM_VERBOSITY if is_dm else "short"
    return setting


def resolve_model_id(alias: str | None, default_model: str) -> str:
    """Concrete model for a room alias; unknown/default falls back to the bot's own model."""
    return MODEL_ALIASES.get(alias or DEFAULT_MODEL) or default_model
