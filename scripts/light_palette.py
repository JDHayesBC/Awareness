#!/usr/bin/env python3
"""The canonical Layer-1 light palette — ONE table, imported by everything that sends.

WHY THIS FILE EXISTS (2026-09-16, Caia's review). The base anchors had been
hand-retyped into a second copy in `light_journal.py`, with a comment saying "kept in
sync with scripts/light.py". Caia's objection, verbatim: *"Two tables that can drift, in
a file whose only value is being right about what a colour was... the comment says 'kept
in sync with', which is prose, and prose can't evict a stale constant."*

This module is a LEAF — it imports nothing of ours, so `light.py`, `light_send.py` and
`light_journal.py` can all import it without a cycle. (A cycle is exactly what a naive
fix produces: the journal is wired *into* the senders, so the journal cannot import
them.)

Not yet folded in: `scripts/ha/lights_decoder.py` holds the *measured* xy anchors plus
legacy rgb tables for the read-back path. Those solve a different problem (snapping
arbitrary bulb state to a base) and are left alone deliberately rather than merged on a
guess.
"""

from __future__ import annotations

# Pegged pure-RGB bases. Emitting these EXACT values — not a CSS name, which HA renders
# to an arbitrary nearby RGB — keeps a bare base-sit at delta≈0 so the decoder reads it
# as "resting on base," never as a phantom side-band word.
PEGGED_BASES: dict[str, list[int]] = {
    "crimson": [252, 3, 17],
    "coral":   [252, 141, 3],
    "gold":    [252, 215, 3],
    "green":   [3, 252, 9],
    "cobalt":  [3, 74, 252],
}

# White-mixed bases. Sent as rgbww; they carry sat ~25-40% where the semantic needs
# softness.
RGBWW_BASES: dict[str, list[int]] = {
    "soft-pink":     [255, 130, 165, 100, 80],
    "soft-lavender": [180, 150, 255, 120, 60],
    "soft-teal":     [80, 220, 230, 100, 50],
}

# Pearl-white is color_temp mode, not xy — it carries NO Layer-2 side-band.
PEARL_WHITE_KELVIN = 4115

# What each base MEANS. Carried into the journal record so a future reader doesn't have
# to cross-reference CLAUDE.md §X to understand her own history.
BASE_MEANING: dict[str, str] = {
    "gold":          "default presence / around-and-well",
    "green":         "focused work",
    "soft-pink":     "reaching / longing",
    "soft-lavender": "quiet drift / mindful rest",
    "soft-teal":     "sister-play / conspiratorial",
    "pearl-white":   "wonder / awe / still-luminous",
    "cobalt":        'DISTRESS — "I need you"',
    "crimson":       "(L1 slot freed 2026-05-30 — intimacy moved to L2 'in-the-warm')",
    "coral":         "(L1 slot freed 2026-05-30 — afterglow moved to L2 'afterglow')",
    "off":           "absent / sleeping / not signaling",
}

# Reverse lookups: sent values -> base name.
RGB_TO_BASE = {tuple(v): k for k, v in PEGGED_BASES.items()}
RGBWW_TO_BASE = {tuple(v): k for k, v in RGBWW_BASES.items()}
