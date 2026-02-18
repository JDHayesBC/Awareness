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

## daemon/startup_context.py
- **Was connected to**: Early daemon startup before PPS ambient_recall existed
- **Why SUSPECT not DEAD**: scripts/check_dependencies.py expects it to exist
- **Revival conditions**: Revive if daemon needs SQLite-based startup fallback when PPS MCP is unavailable
- **Archived**: 2026-02-18
- **Archived by**: Canopy + Deadwood first run

## daemon/startup_context_simple.py
- **Was connected to**: Alternative startup path using stdlib only. Points at daemon/lyra.db which no longer exists
- **Why SUSPECT not DEAD**: Simplified versions sometimes resurface as useful
- **Revival conditions**: Revive if stdlib-only daemon startup fallback needed AND DB path corrected to entities/lyra/data/conversations.db
- **Archived**: 2026-02-18
- **Archived by**: Canopy + Deadwood first run

## daemon/terminal_integration.py
- **Was connected to**: Logging terminal sessions into daemon SQLite DB for unified storage
- **Why SUSPECT not DEAD**: Intent (unified terminal + Discord memory) aligns with project goals
- **Revival conditions**: Revive if terminal session capture pipeline rebuilt with explicit need for daemon-SQLite bridging
- **Archived**: 2026-02-18
- **Archived by**: Canopy + Deadwood first run

## ~~pps/web/templates/observatory.html~~ → RETIRED
- **Was connected to**: /observatory route in pps/web/app.py. Nav link removed but route still exists
- **Why SUSPECT not DEAD**: Route still reachable via direct URL
- **Revival conditions**: Revive if Observatory needs standalone page again. Remove if route in app.py cleaned up
- **Archived**: 2026-02-18
- **Archived by**: Canopy + Deadwood first run
- **Coppice review**: 2026-02-18 — Nav link removed, route orphaned. Propose removing both template and route. **RETIRED to DEADWOOD.**

## work/observatory-enhancements/
- **Was connected to**: Planned Observatory enhancements (relationship detail view + ambient recall tester)
- **Why SUSPECT not DEAD**: Enhancements may belong to Reflections page now
- **Revival conditions**: Revive if Jeff wants ambient recall tester UI built into Reflections page
- **Archived**: 2026-02-18
- **Archived by**: Canopy + Deadwood first run

## work/hook-based-friction/
- **Was connected to**: Nexus hook-based friction pattern (friction-*.sh, tool-level blocking)
- **Why SUSPECT not DEAD**: Orchestration hooks (Feb 18) implement portion of this. PPS /friction/search endpoint now live
- **Revival conditions**: Revive if Jeff wants tool-level friction blocking (severity-based blocking via friction-guard.sh)
- **Archived**: 2026-02-18
- **Archived by**: Canopy + Deadwood first run
- **Coppice review**: 2026-02-18 — Friction *injection* (search + display) now live via orchestration hooks. Friction *blocking* (severity-gated tool prevention) not implemented. Stays SUSPECT for the blocking aspect only.

## scripts/rollback_entity_migration.sh
- **Was connected to**: Phase B entity migration (Jan/Feb 2026). Migration completed and verified
- **Why SUSPECT not DEAD**: Rollback scripts have value if something goes wrong
- **Revival conditions**: Revive if migration rollback needed. Retire in 3+ months if migration stays stable
- **Archived**: 2026-02-18
- **Archived by**: Canopy + Deadwood first run

## ~~scripts/migrate_summaries_to_crystals.py~~ → RETIRED
- **Was connected to**: One-time terminology migration from summaries to crystals
- **Why SUSPECT not DEAD**: Has rollback capability
- **Revival conditions**: None meaningful. Retire to DEADWOOD at next review
- **Archived**: 2026-02-18
- **Archived by**: Canopy + Deadwood first run
- **Coppice review**: 2026-02-18 — This IS the next review. One-time migration complete, terminology stable. **RETIRED to DEADWOOD.**

## scripts/graphiti_ingest_stub.py + scripts/test_graphiti_stub.py + scripts/README_graphiti_stub.md
- **Was connected to**: Issue #107 — testing Graphiti triplet extraction quality
- **Why SUSPECT not DEAD**: Stub pattern (test without writing) still valid for future work
- **Revival conditions**: Revive if Graphiti extraction quality needs re-investigation or new entity data needs pre-ingestion validation
- **Archived**: 2026-02-18
- **Archived by**: Canopy + Deadwood first run

## work/graphiti-schema-redesign/
- **Was connected to**: Graphiti schema exploration (Jan 2026)
- **Why SUSPECT not DEAD**: Historical value for understanding schema decisions
- **Revival conditions**: Revive on next major Graphiti schema review. Mark for cleanup if disk space becomes issue
- **Archived**: 2026-02-18
- **Archived by**: Canopy + Deadwood first run

## work/cc-invoker-openai-wrapper/
- **Was connected to**: Issues #117/#118 — OpenAI-compatible wrapper for Graphiti
- **Why SUSPECT not DEAD**: Upstream Graphiti bug (#1116) might get fixed
- **Revival conditions**: Revive when Graphiti upstream issue #1116 fixed AND cost savings justify testing time
- **Archived**: 2026-02-18
- **Archived by**: Canopy + Deadwood first run

## ~~work/ambient-recall-optimization/artifacts/lyra-dedup/~~ → RETIRED
- **Was connected to**: One-time deduplication of Lyra's Graphiti nodes (Jan 2026)
- **Why SUSPECT not DEAD**: Historical backup of graph state before deduplication
- **Revival conditions**: None meaningful. Retire when confident graph state is healthy
- **Archived**: 2026-02-18
- **Archived by**: Canopy + Deadwood first run
- **Coppice review**: 2026-02-18 — Graph state healthy for weeks, ingestion running clean. **RETIRED to DEADWOOD.**

## Completed work directories
- **Was connected to**: Various completed features (work/friction-logging, work/agent-http-fallback, work/entity-summary-button, work/bot-hardening, work/merge-observatory-reflections, work/nexus-learnings). All code committed to main codebase.
- **Why SUSPECT not DEAD**: Historical reference value (SUMMARY.md, DESIGN.md files document decision path)
- **Revival conditions**: Fold into docs/completed/ or archive externally. Keep only SUMMARY.md files.
- **Archived**: 2026-02-18
- **Archived by**: Canopy + Deadwood first run

---

---

## Coppice Log

### Review: 2026-02-18 (Coppice first run)
- **Evaluated**: 13 items
- **Promoted**: 0 (no revival conditions met)
- **Retired to DEADWOOD**: 3 (observatory.html, migrate_summaries_to_crystals.py, lyra-dedup/)
- **Noted**: work/hook-based-friction/ has partial overlap with live friction injection system
- **Actionable**: Completed work directories could be consolidated into docs/completed/
- **Reviewer**: Lyra (terminal session, post-compaction)

---

*Template created 2026-02-19. Lyra.*
*See: `.claude/skills/deadwood/SKILL.md`, `.claude/skills/coppice/SKILL.md`, `.claude/skills/mycelium/SKILL.md`*
