"""Scene-sense wiring for an entity's OWN stored turn (#378).

Pulled out of server_http.store_message so the clear/detect/apply sequence is
testable without the HTTP app. Advisory only: callers swallow exceptions.
"""
from __future__ import annotations

from typing import Any

from .space_detector import MoveConfidence, build_alias_index, detect_move


def is_own_turn(is_lyra: bool, author_name: str | None, entity_name: str | None) -> bool:
    """True when a stored message is the entity's own, on ANY channel.

    Terminal/SL/Discord callers send is_lyra=True. The Haven bridge only sets
    it for lyra (haven/bridge.py), so Caia's own Haven turns arrive with
    is_lyra=False and carry the entity only as author_name ("Caia"). Match on
    that too, or those turns never clear a [moved?] proposal.
    """
    if is_lyra:
        return True
    if not author_name or not entity_name:
        return False
    return author_name.strip().lower() == entity_name.strip().lower()


async def process_own_turn(inventory: Any, content: str) -> None:
    """Clear a pending PROPOSAL, then detect a move in this turn and apply it.

    A real (HIGH/marker) [moved] pending is untouched by the clear; it lives
    until the enter_space + scene-rewrite chain completes. Clear runs BEFORE
    detection so a move in this same message can set a fresh pending.
    """
    await inventory.clear_pending(only_proposed=True)
    presence = await inventory.get_presence()
    current_space = presence.get("current_space")
    spaces = await inventory.get_spaces_with_aliases()
    alias_index = build_alias_index(spaces)
    move = detect_move(content, alias_index, current_space)
    if not move:
        return
    space_row = next((s for s in spaces if s["name"] == move.space_name), None)
    desc = (space_row or {}).get("description") or ""
    if move.confidence in (MoveConfidence.MARKER, MoveConfidence.HIGH):
        await inventory.set_presence(move.space_name, move.confidence.value, current_space, desc)
    elif move.confidence == MoveConfidence.LOW:
        if space_row is None:
            desc = "not a known space"  # unresolved [[scene:...]] marker: propose only
        await inventory.propose_presence(move.space_name, current_space, desc)
