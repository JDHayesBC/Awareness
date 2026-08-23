"""haven.brain — shared, surface-agnostic entity mind.

See haven/brain/entity_brain.py for the full extraction notes (bot.py line
ranges, what was and wasn't ported) and work/sl-presence/spec.md §4/§7 for
the architecture this subpackage implements.
"""

from __future__ import annotations

from haven.brain.entity_brain import EntityBrain, is_no_response

__all__ = ["EntityBrain", "is_no_response"]
