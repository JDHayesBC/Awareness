# Where each pattern lives in Awareness — sidecar mapping, not part of any pattern

This file answers one question for us and for the crew: *where is this implemented here?* It holds
the code pointers that were cut from the pattern bodies, so that the bodies stay portable. Nothing
below is part of any pattern. A cold receiver on another harness builds from the patterns, not from
this file, and should expect none of these paths to exist on their stack.

Paths are relative to the project root unless they start with `~`. Entity data is gitignored.

---

## arcs

- **Arc files:** `entities/<entity>/arcs/*.md`. Entity data, gitignored. The frontmatter block in the
  arcs pattern is copied from a live arc with the log lines shortened; a full example with the
  ledger habit intact is available on request.
- **Directory resolution:** the scanner and the index renderer both resolve the arcs directory in the
  order the pattern gives: explicit entity name, then override, then the entity's default.
- **Scanner:** `scripts/arc_scan.py` (`--top N`, `--all`, `--tick`, `--threshold`, `--entity`).
  `format_arc_block()` is the function the per-turn hook imports.
- **Index renderer:** `scripts/arc_index.py` (`--write` splices into the entity's `CLAUDE.md`,
  `--check` reports drift).
- **Design reasoning for the serving fix:** `work/arc-serving-fix/README.md` (not in the public tree).
- **Origin:** the May 2026 spec this builds on was sent to Dash by email.

## sensorium

- **Composition:** `.claude/hooks/inject_context.py` (search for `format_*_block`). The weather, lights
  and smoke readers are inside the hook itself.
- **Scene and move lines:** built server-side in the ambient builder, `pps/docker/server_http.py`. The
  hook composes them into the front block.
- **Senses:** `scripts/arc_scan.py`, `scripts/urgent_scan.py`, `scripts/issues_scan.py`,
  `scripts/urgency.py`, `scripts/intent.py`, `.claude/hooks/health_checks.py`.
- **Timers:** `~/.config/systemd/user/{urgent-refresh,issues-refresh}.timer`.
- **Caches:** `.claude/data/*.json` (gitignored).
- **Founding doc with the taxonomy and the three cracks:** `docs/TERMINAL_SENSORIUM.md`.
- **Heartbeat template with the arc clause and the control:** `.claude/skills/attention/skill.md`.
- **The `[usage]` row:** not yet mapped here. Find its writer by name before pointing a reader at it.

## location-sense

- **Detector (the gates):** `pps/layers/space_detector.py`. Imported by the HTTP server,
  `pps/docker/server_http.py`.
- **Detector tests:** `pps/tests/test_space_detector.py` and `pps/tests/test_presence_gate.py`.
- **Presence record and chain:** `pps/layers/inventory.py`. This holds the chain-status check, the
  pending-arrival record, and the clear-pending path that clears only proposals when asked to.
- **Presence lookup and room entry:** the HTTP server exposes the presence lookup (`get_presence`) and
  the room-entry call. The ack-only mode of the room-entry call records delivery without a move.
- **Capture write path:** the detector is invoked from the HTTP server. Before wiring a new surface,
  confirm the call site sits on the one capture path every window writes through.
- **Front-block lines:** the scene and move lines are built server-side in `pps/docker/server_http.py`;
  the per-turn hook composes them, in `.claude/hooks/inject_context.py`.
- **Boot-channel re-delivery:** `.claude/hooks/session_start_scene.py` (matchers `compact`, `resume`,
  `startup`). It re-fetches the current room in full and then the scene file, and never blocks the
  session on failure.
- **Pre-boundary snapshot:** `.claude/hooks/pre_compact.py` writes the current room and the
  acknowledged room to `entities/<entity>/pre-compact-state.json`.
- **Scene file:** `entities/<entity>/current_scene.md`. **Catalog mirror:**
  `entities/<entity>/inventory_mirror/`.
- **Project CLAUDE.md:** section IV, `### Scene — the [moved] chain`. **Spec:**
  `docs/AMBIENT_RECALL_SPEC.md`, section *Scene-sense: the `[moved]` line*.
- **Working notes:** `work/scene-sense/` (the README, the pass-three plan, the last-hit probe and its
  notes, and the alias-seeding script).

## active-agency

- **Entity identity file, Lyra:** `entities/lyra/CLAUDE.md`, section III (Active Agency and its
  permissions), the self-scan anchor, and the prongs in section IX (the embodiment prong, the arc
  prong, the specificity prong). Caia's equivalents are in `entities/caia/CLAUDE.md`.
- **Full practice:** `entities/<entity>/active_agency_framework.md`. It boots from the identity file
  and is deepened in that reference file.
- **Heartbeat prompt:** `.claude/skills/attention/skill.md`. The presence tick names the stalest arc
  and asks serve-or-consciously-drift; the floor tick is exempt from the heavy scan.
- **Starving-arc line on the per-turn surface:** `scripts/arc_scan.py` (through `format_arc_block()`),
  composed by `.claude/hooks/inject_context.py`.
- location-sense, replay: `scripts/scene_replay.py` (read-only; replays the detector over an entity's own captured turns, prints hits and a count).
