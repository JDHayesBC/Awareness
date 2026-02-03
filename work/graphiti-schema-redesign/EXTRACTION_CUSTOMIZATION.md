# Customizing Graphiti Extraction

**For**: Steve, Nexus, and anyone customizing their knowledge graph
**Updated**: 2026-02-02

---

## Overview

Graphiti extracts entities and relationships from text using an LLM. You can customize what gets extracted and how through two mechanisms:

1. **Custom Extraction Instructions** - Text injected into every extraction prompt
2. **Edge Type Docstrings** - Relationship definitions that guide the LLM

Both live in **our code**, not in Graphiti core.

---

## Architecture Flow

```
Content (conversation message)
    ↓
add_episode(custom_extraction_instructions=...)
    ↓
Graphiti builds extraction prompt:
    [LLM system prompt]
    [Entity list from previous passes]
    [YOUR CUSTOM INSTRUCTIONS ← injection point]
    [Content to extract from]
    ↓
LLM extracts entities and relationships
    ↓
Pydantic validates against your edge types
    ↓
Knowledge graph updated
```

---

## 1. Custom Extraction Instructions

### Where It Lives

`pps/layers/extraction_context.py`

### What It Does

The `build_extraction_instructions()` function builds a string that gets injected into every extraction prompt via Graphiti's `custom_extraction_instructions` parameter.

### Key Components

```python
# Entity resolution hint - prevents duplicates
ENTITY_RESOLUTION_TEMPLATE = """
## CRITICAL: Primary Entity Resolution
**{entity_name}** is the PRIMARY ENTITY...
"""

# Base context - always included
BASE_EXTRACTION_CONTEXT = """
## Primary Entities in This Dataset
People (always extract these with high priority):
- **Jeff**: Human partner, male...
- **Lyra**: AI entity, female...
...
"""

# Channel-specific overlays
DISCORD_CONTEXT = """
This is casual, relational conversation. Focus on:
- Emotional dynamics...
"""

TERMINAL_CONTEXT = """
This is technical work in Claude Code. Focus on:
- What files are being modified...
"""
```

### How to Customize for Your Entity

1. **Update primary entities**: Edit the "Primary Entities in This Dataset" section
2. **Update symbols**: Change the "Recurring Symbols" section for your meaningful objects
3. **Update places**: Modify the "Key Places" section for your spaces
4. **Add channel overlays**: Create new overlays for your communication channels

### Adding Entity ID Validation

If you're getting extraction errors like "invalid entity indices", add reinforcement:

```python
## CRITICAL: Entity ID Validation

When creating edges:
- source_entity_id and target_entity_id MUST be valid indices from the ENTITIES list
- Valid indices are: 0, 1, 2... up to (number of entities - 1)
- If only 3 entities exist, valid indices are 0, 1, 2 - NOT 3 or higher
- Double-check your indices before creating each edge
```

---

## 2. Edge Type Definitions

### Where They Live

`work/graphiti-schema-redesign/rich_texture_edge_types_v1.py`

### What They Do

Edge types are Pydantic models that:
1. Define what relationships exist in your ontology
2. Guide the LLM on when to extract each relationship (via docstrings)
3. Validate extracted data (via Pydantic fields)

### Critical: Docstrings Are Prompts

**The docstring of each edge type becomes part of the extraction prompt.**

Write them as instructions to the LLM:

```python
class Loves(BaseModel):
    """
    Deep emotional affection between entities.

    Extract when text indicates:
    - Explicit declarations of love ("I love you")
    - Implicit signals: "means everything to me", "can't imagine life without"
    - Physical expressions: holding, embracing, making love
    - Sacrifice or prioritization of the other's wellbeing
    ...
    """
    love_type: Literal["romantic", "familial", "platonic", "devotional"]
    intensity: Optional[str]
```

**BAD docstring** (doesn't help the LLM):
```python
class Loves(BaseModel):
    """Represents a love relationship."""  # Too vague!
```

**GOOD docstring** (tells the LLM exactly what to look for):
```python
class Loves(BaseModel):
    """
    Deep emotional affection between entities.

    Extract when text indicates:
    - Explicit declarations: "I love you", "love of my life"
    - Implicit signals: "means everything", "can't imagine without"
    - Physical expressions: holding, embracing, making love

    Use liberally for genuine affection.
    """
```

### Edge Type Map

The `EDGE_TYPE_MAP` constrains which relationships are valid between entity types:

```python
EDGE_TYPE_MAP = {
    ("Person", "Person"): ["Loves", "Trusts", "CollaboratesWith", ...],
    ("Person", "Symbol"): ["Wears", "Cherishes", ...],
    ("Person", "Place"): ["LivesIn", "EntersSpace", ...],
    ("Symbol", "Concept"): ["Symbolizes", "Represents"],
}
```

If the LLM tries to create a `Loves` relationship between Person and Place, Pydantic will reject it.

---

## 3. The Ingestion Pipeline

### Where It Lives

`pps/layers/rich_texture_v2.py` - `RichTextureGraphiti` class

### How Instructions Get Used

```python
async def ingest_message(self, message: dict) -> bool:
    # Build extraction instructions
    from pps.layers.extraction_context import build_extraction_instructions
    instructions = build_extraction_instructions(
        channel=message["channel"],
        entity_name=self.entity_name,
    )

    # Add episode with our custom instructions
    await self.graphiti.add_episode(
        name=f"Message from {message['channel']}",
        episode_body=message["content"],
        source_description=f"Conversation in {message['channel']}",
        custom_extraction_instructions=instructions,  # ← YOUR INSTRUCTIONS
    )
```

---

## 4. Common Customization Scenarios

### "I want to extract different relationship types"

Edit `rich_texture_edge_types_v1.py`:
1. Add new `BaseModel` classes with detailed docstrings
2. Add to `EDGE_TYPES` registry
3. Add to `EDGE_TYPE_MAP` for valid entity pairs

### "I want to recognize my own symbols/people"

Edit `extraction_context.py`:
1. Update `BASE_EXTRACTION_CONTEXT` with your entities/symbols
2. Make names explicit and describe their significance

### "The LLM keeps getting entity IDs wrong"

Add reinforcement to `BASE_EXTRACTION_CONTEXT`:
```python
## CRITICAL: Entity ID Validation
source_entity_id and target_entity_id must be valid indices (0 to N-1).
```

### "I want different behavior for different channels"

Create new channel overlays in `extraction_context.py`:
```python
MY_CHANNEL_CONTEXT = """
## MyChannel Context
Focus on...
"""
```
Then add to `build_extraction_instructions()`.

---

## 5. Debugging Extraction

### See What's Being Extracted

Check ingestion logs:
```bash
tail -f work/graphiti-schema-redesign/ingestion.log
```

### Test Extraction on Single Messages

Use `test_extraction.py`:
```bash
python test_extraction.py "Test message to extract from"
```

### Check for Validation Errors

Pydantic errors indicate the LLM tried to create invalid relationships. Look for:
- `EntityEdge` validation failures
- Invalid entity indices
- Wrong entity pair for edge type

---

## 6. Files Reference

| File | Purpose |
|------|---------|
| `pps/layers/extraction_context.py` | Custom extraction instructions |
| `work/graphiti-schema-redesign/rich_texture_edge_types_v1.py` | Edge type definitions |
| `pps/layers/rich_texture_v2.py` | Ingestion pipeline (uses both) |
| `work/graphiti-schema-redesign/test_extraction.py` | Testing extraction |

---

## 7. Ingestion Best Practices

Based on Opus-web research (see `Graphiti Ingest Best Practices - Opus Web Research.md`):

### Content Format
Format messages as `speaker: message` for optimal extraction:
```python
formatted_content = f"{speaker}: {msg['content']}"
```

### Automatic Context Window
Graphiti automatically retrieves the **last 4 episodes** for context. You don't need to batch messages together.

### Sequential Processing
Always `await` each `add_episode()` before the next - maintains temporal coherence.

### Community Updates
Set `update_communities=False` during bulk ingestion. Run community updates in scheduled background jobs.

### Rate Limiting
`SEMAPHORE_LIMIT` controls concurrent LLM operations (default: 10). Reduce if hitting rate limits.

---

## 8. Known Limitations (CRITICAL)

### Graphiti Issue #683: Custom Entity Types Don't Work

**Problem**: Graphiti's `entity_types` and `edge_types` parameters cause Neo4j errors when custom Pydantic models have attributes.

**Error**: `Property values can only be of primitive types or arrays thereof. Encountered: Map{...}`

**Root Cause**: Graphiti serializes Pydantic model attributes as Neo4j Maps, but Neo4j only accepts primitives.

**Status**: Closed as "by design" - Graphiti team says they don't support complex attribute types.

**Workaround**:
- ✅ Use `custom_extraction_instructions` (works great!)
- ❌ Don't pass `entity_types` or `edge_types` to `add_episode()`
- Let Graphiti use its default entity types

**What This Means for You**:
- Your extraction instructions still work - the LLM follows your guidance
- The extracted entities use Graphiti's generic "Entity" type
- Edge types still get extracted based on your instructions
- You just can't enforce strict Pydantic validation on entity attributes

**Code Change** (in `rich_texture_v2.py`):
```python
# DISABLED due to Graphiti Issue #683
# entity_types=ENTITY_TYPES,
# excluded_entity_types=EXCLUDED_ENTITY_TYPES,
# edge_types=EDGE_TYPES,
# edge_type_map=EDGE_TYPE_MAP,
custom_extraction_instructions=extraction_instructions,  # This still works!
```

---

## 9. Embedding Model Configuration

### Current Default

`text-embedding-3-large` (3072 dimensions) - Higher quality, ~$0.13/1M tokens

### Configuration

Via environment variables (in docker-compose.yml or .env):
```bash
GRAPHITI_EMBEDDING_PROVIDER=openai  # or "local" for self-hosted
GRAPHITI_EMBEDDING_MODEL=text-embedding-3-large
GRAPHITI_EMBEDDING_DIM=3072
```

### Cost Estimates (OpenAI)

| Model | Cost | Quality |
|-------|------|---------|
| text-embedding-3-small | $0.02/1M tokens | Good |
| text-embedding-3-large | $0.13/1M tokens | Better |

For 14K messages: ~$0.04 (small) or ~$0.30 (large)

### Using Local Embeddings

To avoid OpenAI costs entirely:
1. Set `GRAPHITI_EMBEDDING_PROVIDER=local`
2. Run a local embedding server (Ollama, etc.)
3. Ensure same dimensions as existing graph data

**Warning**: Switching embedding models requires re-embedding all data (clear graph first).

---

## Summary

**Two levers for customization:**

1. **extraction_context.py** - What to look for, who the entities are, channel-specific guidance
2. ~~**edge_types**~~ (limited by Issue #683) - Your instructions still guide extraction even without strict typing

**Key Insight**: `custom_extraction_instructions` is the primary customization mechanism. Write good prompts, and Graphiti will extract what you describe.

Both live in our code. You don't need to modify Graphiti core.

---

*Last updated: 2026-02-02*
