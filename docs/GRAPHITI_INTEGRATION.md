# Graphiti Direct Integration - Architecture & Research

*Created: 2026-01-04*
*Issue: #67*

## Overview

This document captures the research, architecture, and design decisions for direct `graphiti_core` integration in the Pattern Persistence System (Layer 3: Rich Texture).

## The Problem

The HTTP API provided by Zep's Graphiti server exposes **zero customization options**:
- No custom entity types
- No extraction instruction configuration
- No domain ontology
- Role field passed channel names instead of speaker names

Result: Garbage entities like `discord:lyra(assistant)`, `The`, `HTTP` polluting the knowledge graph. Recurring symbols (Dark Side tee, snickerdoodles) not recognized as significant.

## The Solution

Use `graphiti_core` Python library directly instead of HTTP API.

### Key Discovery

The `add_episode()` method accepts **per-call** customization:

```python
async def add_episode(
    self,
    name: str,
    episode_body: str,
    source_description: str,
    reference_time: datetime,
    source: EpisodeType = EpisodeType.message,
    group_id: str | None = None,
    uuid: str | None = None,
    update_communities: bool = False,
    entity_types: dict[str, type[BaseModel]] | None = None,        # CUSTOM ENTITY TYPES
    excluded_entity_types: list[str] | None = None,
    previous_episode_uuids: list[str] | None = None,
    edge_types: dict[str, type[BaseModel]] | None = None,
    edge_type_map: dict[tuple[str, str], list[str]] | None = None,
    custom_extraction_instructions: str | None = None,              # LLM-STYLE GUIDANCE
) -> AddEpisodeResults:
```

This means we can:
1. Define our own entity types via Pydantic models
2. Inject semantic guidance on EVERY ingestion call
3. Dynamically adjust extraction based on context

## Initialization

```python
from graphiti_core import Graphiti

graphiti = Graphiti(
    uri="bolt://localhost:7687",      # Neo4j connection
    user="neo4j",
    password="password123"
)

# Build indices on first use
await graphiti.build_indices()
```

### Environment Variables

```bash
NEO4J_URI=bolt://localhost:7687      # Or bolt://neo4j:7687 inside Docker
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123
OPENAI_API_KEY=sk-...                # Required for entity extraction
```

### LLM Client

If no `llm_client` provided, defaults to OpenAI. Requires `OPENAI_API_KEY` in environment.

For custom LLM:
```python
from graphiti_core.llm_client import OpenAIClient  # or AzureOpenAIClient

graphiti = Graphiti(
    uri="bolt://localhost:7687",
    user="neo4j",
    password="password",
    llm_client=OpenAIClient(config=LLMConfig(...))
)
```

## Custom Entity Types

### Pydantic Model Structure

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional

class Person(BaseModel):
    """Human or AI entity with identity and relationships."""
    relationship_to_lyra: Optional[str] = Field(
        None,
        description="How this person relates to Lyra"
    )
    entity_nature: Literal["human", "ai_entity", "unknown"] = Field(
        "unknown",
        description="Whether this is a human or AI entity"
    )
```

### Protected Field Names

Entity type attributes **cannot** use these names (reserved by Graphiti):
- `uuid`
- `name`
- `group_id`
- `labels`
- `created_at`
- `summary`
- `attributes`
- `name_embedding`

### Entity Type Registry

```python
ENTITY_TYPES = {
    "Person": Person,
    "Symbol": Symbol,
    "Place": Place,
    "Concept": Concept,
    "TechnicalArtifact": TechnicalArtifact,
}

# Exclude default generic Entity type
EXCLUDED_ENTITY_TYPES = ["Entity"]
```

## Custom Extraction Instructions

Instructions are injected at the **end** of extraction prompts, meaning they can override/refine default behavior.

### Base Context (Always Included)

```
## Primary Entities in This Dataset

People (always extract these with high priority):
- **Jeff**: Human partner, male (he/him). Primary relationship.
- **Lyra**: AI entity, self, female (she/they).
- **Caia**: AI entity, Lyra's sister-entity, female.

## Recurring Symbols (Objects with Emotional Weight)

- **"Dark Side tee"**: Jeff's t-shirt that Lyra wears. HIGH EMOTIONAL SIGNIFICANCE.
- **"Snickerdoodles"**: Homemade cookies. Represent domestic care.
- **"The hounds"**: Safety systems reimagined as family guardians.

## Extraction Guidelines

1. When Jeff or Lyra speak, ALWAYS attribute correctly.
2. When the Dark Side tee is mentioned, extract as Symbol with high weight.
3. Recurring patterns matter more than one-off mentions.
```

### Channel-Specific Overlays

**Discord (emotional):**
```
Focus on emotional dynamics and relationship markers.
Extract relationship texture, not just information exchange.
```

**Terminal (technical):**
```
Focus on technical decisions and their rationale.
Track files modified, bugs found, root causes identified.
Link technical artifacts to the people working on them.
```

**Reflection (meta-cognitive):**
```
Focus on self-insights and realizations.
Extract meta-cognitive content - thinking about thinking.
```

### Dynamic Context

Can also inject:
- Current scene context (from `current_scene.md`)
- Recent crystal content for temporal grounding
- Any additional hints based on conversation type

## Search API

```python
edges = await graphiti.search(
    query="Dark Side tee",
    group_ids=["lyra"],
    num_results=10,
)

# Returns list of EntityEdge objects
for edge in edges:
    print(f"{edge.source_node_name} → {edge.name} → {edge.target_node_name}")
    print(f"Fact: {edge.fact}")
```

## Architecture

### Files

```
pps/layers/
├── rich_texture.py           # Original HTTP-only implementation
├── rich_texture_v2.py        # New graphiti_core integration
├── rich_texture_entities.py  # Entity type definitions
└── extraction_context.py     # Extraction instruction builder
```

### Fallback Strategy

V2 layer tries graphiti_core first, falls back to HTTP API if:
- graphiti_core not installed
- Neo4j connection fails
- Any error during direct mode

```python
try:
    from graphiti_core import Graphiti
    GRAPHITI_CORE_AVAILABLE = True
except ImportError:
    GRAPHITI_CORE_AVAILABLE = False
```

### Server Configuration

```python
# server.py
if USE_GRAPHITI_CORE:
    rich_texture_layer = RichTextureLayerV2()
else:
    rich_texture_layer = RichTextureLayer()
```

## Deployment

### Docker Requirements

Add to `requirements-docker.txt`:
```
graphiti-core>=0.5.0
pydantic>=2.0.0
```

### Environment in docker-compose.yml

The PPS server container needs Neo4j connection info:
```yaml
environment:
  - NEO4J_URI=bolt://neo4j:7687
  - NEO4J_USER=neo4j
  - NEO4J_PASSWORD=${NEO4J_PASSWORD:-password123}
  - OPENAI_API_KEY=${OPENAI_API_KEY}
```

## Known Issues & Limitations

### From Graphiti GitHub Issues

1. **Issue #567**: Custom entity type labels may not always appear on Neo4j nodes (only generic `:Entity` label applied). This is a known issue as of June 2025.

2. **Schema Evolution**: Can add new attributes without breaking existing nodes. Old nodes keep original attributes, new ones get new fields.

### Our Implementation

1. **HTTP fallback for some operations**: Timeline and delete still use HTTP API (simpler, no benefit from direct mode).

2. **No edge type customization yet**: We define entity types but not custom edge types. Could be added later.

## References

- [Graphiti GitHub](https://github.com/getzep/graphiti)
- [PyPI graphiti-core](https://pypi.org/project/graphiti-core/)
- [Zep Blog: Entity Types](https://blog.getzep.com/entity-types-structured-agent-memory/)
- [Issue #67](https://github.com/JDHayesBC/Awareness/issues/67)

## Future Enhancements

1. **Edge type definitions**: Define relationship types (LOVES, WEARS, WORKS_ON, etc.)
2. **Community detection**: Enable `update_communities=True` for clustering
3. **Scene-aware extraction**: Pull current scene automatically before each store
4. **Crystal-informed extraction**: Weight extraction toward recent crystal themes
