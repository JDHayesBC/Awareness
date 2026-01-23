# Graphiti Schema Redesign - Work Tracking

*Started: 2026-01-23*
*Goal: Design comprehensive edge type schema for Layer 3*

---

## Pending Git Commit

Git is stuck (I/O wait state - WSL2 issue). When cleared, commit:
- `docs/reports/2026-01-23_graph-curation-cycle-01.md` (moved curation report)
- `CURATION_REPORT.md` (deletion - moved)
- `work/` (this working directory)

---

## Context

**Problem**: No edge types defined → inconsistent extraction → "LOVES_IMAGE_OF_FALLING_ASLEEP_TOGETHER" style relationships

**Current state**:
- 5 entity types defined (Person, Symbol, Place, Concept, TechnicalArtifact)
- 0 edge types defined
- ~55 edges, 7% garbage, inconsistent naming

**Strategy**: Nuke and rebuild (Jeff approved - current graph has zero value)

---

## Tasks

### Phase 1: Schema Design
- [x] Read Graphiti Best Practices doc
- [x] Read current rich_texture_entities.py
- [x] Review planner agent recommendations
- [x] Design Pydantic edge type models (29 types)
- [x] Create edge_type_map (7 entity pairs)
- [x] Write rich docstrings with extraction guidance
- [x] Draft saved to work/graphiti-schema-redesign/rich_texture_edge_types_v1.py
- [x] Wrote NOTES_FOR_JEFF.md for review
- [ ] Jeff reviews and approves schema
- [ ] Copy approved schema to pps/layers/rich_texture_edge_types.py

### Phase 2: Integration
- [ ] Update rich_texture_v2.py to use edge types
- [ ] Update extraction_context.py if needed
- [ ] Test with sample conversations

### Phase 3: Migration
- [ ] Get Jeff's final approval on schema
- [ ] Backup current graph state (export)
- [ ] Nuke existing graph
- [ ] Re-ingest from raw capture layer
- [ ] Verify extraction quality

---

## Design Notes

### Edge Type Categories (from best practices)

**Emotional/Relational** (Person ↔ Person):
- Loves, CaresFor, Trusts, Adores, ProtectsInstinctively, FearsLosing

**Physical/Action** (Person ↔ Object/Place):
- Wears, Carries, Gives, Receives, Creates, Builds
- EntersSpace, BasksIn, GetsTakenOn

**Identity/Conceptual** (various):
- Embodies, BelievesIn, Discovers, Articulates
- Symbolizes, Represents, PartOf

**Technical** (Person ↔ TechnicalArtifact):
- WorksOn, Maintains, BuiltArchitectureFor, Debugs

### Key Patterns from Real Data

From curation reports, most common predicates:
- LOVES (6 uses)
- BUILT_ARCHITECTURE_FOR (5 uses)
- WEARS, GAVE, COMPLIMENTS, TRUSTS

From hot tub appendix, relationships we need:
- Person ↔ Place: GETS_TAKEN_ON, ENTERS, LIVES_IN, BASKING_IN
- Person ↔ Artifact: WEARS, RECEIVES, CHERISHES
- Person ↔ Concept: EMBODIES, BELIEVES_IN, DISCOVERS
- Symbol ↔ Concept: SYMBOLIZES, REPRESENTS

---

## Decisions

**Skip manual seeding** - Test bare extraction first. If terrible, 10 min of manual seeding gets us back to current state but better.

**Entity type expansion?** - Keep existing 5 types for now. Add "Experience" type later if needed.

**Edge type granularity** - Start comprehensive. Can always simplify if over-engineered.
