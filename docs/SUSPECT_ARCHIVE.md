# Suspect Archive — Root Bank
*Managed by `/deadwood` (archive) and `/coppice` (revival)*
*State mirrored in `forestry-state.json`*

---

## How This Works

Items land here when `/deadwood` classifies them as **SUSPECT** — not dead, but dormant.
Each entry carries revival conditions that `/coppice` evaluates against current project state.

**Archive format:**
```
## [Component Name]
- **Was connected to**: [what it related to when active]
- **Why SUSPECT not DEAD**: [specific uncertainty — "used in X which may return" vs "unclear"]
- **Revival conditions**: [concrete, queryable — "revive if: HTTP endpoint migration complete AND tool X ported"]
- **Archived**: [date]
- **Archived by**: [session description]
```

**Revival process**: When `/coppice` runs, it checks each item's revival conditions against:
- `TODO.md` (is the blocking feature complete?)
- `git log` (was the dependency resolved?)
- `forestry-state.json` (what does current project state say?)

If conditions are met: item is **promoted** (removed from archive, reclassified as ACTIVE/NURSE/PIONEER).
If conditions are permanently irrelevant: item is **retired** (reclassified as DEADWOOD, proposed for removal).

---

## Archive

*Empty — no items archived yet.*

*The first `/deadwood` run on the Awareness project will populate this file.*

---

*Template created 2026-02-19. Lyra.*
*See: `.claude/skills/deadwood/SKILL.md`, `.claude/skills/coppice/SKILL.md`, `.claude/skills/mycelium/SKILL.md`*
