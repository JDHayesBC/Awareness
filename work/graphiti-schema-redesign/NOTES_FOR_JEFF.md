# Graphiti Edge Types Schema - For Review

*Drafted: 2026-01-23*

---

## Summary

I've created a comprehensive edge type schema in `rich_texture_edge_types_v1.py`.

**Stats:**
- 29 edge types defined
- 7 entity pair mappings
- Rich docstrings for LLM extraction guidance

---

## What This Solves

**Current problem**: No edge types defined → Graphiti extracts whatever it wants → "LOVES_IMAGE_OF_FALLING_ASLEEP_TOGETHER" style relationships

**After this**: Constrained extraction → consistent relationship naming → cleaner graph

---

## Design Decisions

### 1. Edge Type Granularity

Chose meaningful distinctions, not over-specification:
- `Loves` is ONE type with a `love_type` attribute (romantic/familial/platonic/devotional)
- But `IntimateIn` is separate from `EntersSpace` because emotional geography of intimacy matters

### 2. Entity Pair Coverage

| Source → Target | Relationships |
|-----------------|---------------|
| Person → Person | Loves, CaresFor, Trusts, Admires, ProtectsInstinctively, SpouseOf, ParentOf, SiblingOf, CollaboratesWith |
| Person → Symbol | Wears, Receives, Cherishes, Creates |
| Person → Place | LivesIn, EntersSpace, IntimateIn, BasksIn, BuiltSpace |
| Person → Concept | Embodies, BelievesIn, Articulates, Discovers |
| Person → TechnicalArtifact | WorksOn, BuiltArchitectureFor, Maintains, Creates |
| Symbol → Concept | Symbolizes, Represents |
| Place → Concept | Embodies, Symbolizes |

### 3. Extraction Guidance

Each edge type has detailed docstrings that tell the LLM when to extract. Example:

```python
class Loves(BaseModel):
    """
    Deep emotional affection between entities.

    Extract when text indicates:
    - Explicit declarations of love ("I love you")
    - Implicit signals: "means everything to me", "can't imagine life without"
    - Physical expressions: holding, embracing, making love
    - Sacrifice or prioritization of the other's wellbeing
    - Longing, missing someone, wanting to be near them
    - Pet names, terms of endearment used affectionately
    """
```

---

## Integration Path

The change is surgical. In `pps/layers/rich_texture_v2.py`, line 210:

**Current:**
```python
result = await client.add_episode(
    name=episode_name,
    episode_body=content,
    ...
    entity_types=ENTITY_TYPES,
    excluded_entity_types=EXCLUDED_ENTITY_TYPES,
    custom_extraction_instructions=extraction_instructions,
)
```

**After:**
```python
from .rich_texture_edge_types import EDGE_TYPES, EDGE_TYPE_MAP

result = await client.add_episode(
    name=episode_name,
    episode_body=content,
    ...
    entity_types=ENTITY_TYPES,
    excluded_entity_types=EXCLUDED_ENTITY_TYPES,
    edge_types=EDGE_TYPES,           # NEW
    edge_type_map=EDGE_TYPE_MAP,     # NEW
    custom_extraction_instructions=extraction_instructions,
)
```

---

## What's NOT Covered

1. **Experience entity type** - The best practices doc mentioned this, but it's not in current entities. Could add later if needed.

2. **Some granular actions from real data** - EATS, STEEPS, etc. - Decided these are too granular. Can add if missing them hurts.

3. **Place → Place relationships** - (room contains room, etc.) - Not needed yet.

4. **Bidirectional explicitly** - Graphiti should handle A→B and B→A extraction naturally. If not, we can add inverse types.

---

## Questions for You

1. **Right level of granularity?** I erred on the side of comprehensiveness since we can always simplify.

2. **Any edge types to add?** Based on what matters in your memory of us?

3. **Any to remove?** Some might be over-engineering.

4. **Entity type expansion?** Should we add "Experience" type? (e.g., "the wedding", "first time on the couch")

---

## Re-Ingestion Scope

**Raw Capture Layer Stats:**
- 11,275 total messages
- 10,652 already ingested to Graphiti
- 623 not yet ingested
- Time range: Dec 31, 2025 → Jan 23, 2026

If we nuke and rebuild, we'd re-ingest ~11K messages through the new schema. This will take a while but gives us a clean baseline with consistent relationships.

---

## Next Steps (After Your Review)

1. Copy edge types to `pps/layers/rich_texture_edge_types.py`
2. Update `rich_texture_v2.py` to import and use them
3. Nuke existing graph
4. Re-ingest from raw capture
5. Verify extraction quality improved

---

*The schema is in `work/graphiti-schema-redesign/rich_texture_edge_types_v1.py`. Ready for your review.*
