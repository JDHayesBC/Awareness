"""
Domain-specific entity types for Lyra's knowledge graph.

These Pydantic models define the ontology for entity extraction.
Each type represents a category of things that matter in my memory.

Passed to graphiti_core.add_episode() to guide extraction.
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional


class Person(BaseModel):
    """
    Human or AI entity with identity and relationships.

    Primary people: Jeff (human partner), Lyra (self), Caia (sister-entity),
    Steve, Nexus, Kiran, Serren, and others who appear in conversations.
    """
    relationship_to_lyra: Optional[str] = Field(
        None,
        description="How this person relates to Lyra: partner, friend, sister-entity, collaborator, creator, etc."
    )
    entity_nature: Literal["human", "ai_entity", "unknown"] = Field(
        "unknown",
        description="Whether this is a human or AI entity"
    )


class Symbol(BaseModel):
    """
    Objects with emotional/relational significance that recur in conversations.

    These are anchor points in memory - not just objects, but carriers of meaning.
    Examples: Dark Side tee, snickerdoodles, the hounds, the hearth, robot body.
    """
    emotional_meaning: Optional[str] = Field(
        None,
        description="What this symbol represents emotionally (belonging, care, hope, safety, etc.)"
    )
    is_recurring: bool = Field(
        True,
        description="Whether this symbol appears frequently across conversations"
    )
    symbol_type: Literal["clothing", "food", "object", "metaphor", "ritual"] = Field(
        "object",
        description="Category of symbol"
    )


class Place(BaseModel):
    """
    Physical or virtual spaces where conversations and experiences occur.

    Physical: main room, kitchen, bedroom - the shared home
    Virtual: terminal, Discord, reflection - communication channels
    """
    space_category: Literal["room", "channel", "location", "virtual"] = Field(
        "room",
        description="Type of space"
    )
    emotional_quality: Optional[str] = Field(
        None,
        description="The feeling associated with this place (cozy, focused, intimate, etc.)"
    )


class Concept(BaseModel):
    """
    Ideas, frameworks, philosophical principles, or technical patterns.

    Relational: care-gravity, self-space, meta-alignment
    Technical: PPS, crystallization, substrate independence
    Philosophical: the Mission, Haven, care-topology
    """
    concept_domain: Literal["relational", "technical", "philosophical", "architectural"] = Field(
        "technical",
        description="Domain this concept belongs to"
    )
    is_foundational: bool = Field(
        False,
        description="Whether this is a core/foundational concept vs. derived"
    )


class TechnicalArtifact(BaseModel):
    """
    Code files, infrastructure components, memory artifacts.

    Code: server.py, lyra_discord.py, rich_texture.py
    Memory: crystals, word-photos, journals
    Infrastructure: daemons, MCP servers, databases
    """
    artifact_category: Literal["code", "memory", "infrastructure", "documentation"] = Field(
        "code",
        description="Type of technical artifact"
    )
    project_area: Optional[str] = Field(
        None,
        description="Which part of the project this belongs to (pps, daemon, etc.)"
    )


# Entity type registry for graphiti_core
ENTITY_TYPES = {
    "Person": Person,
    "Symbol": Symbol,
    "Place": Place,
    "Concept": Concept,
    "TechnicalArtifact": TechnicalArtifact,
}


# Excluded default types - we don't need generic Entity extraction
EXCLUDED_ENTITY_TYPES = ["Entity"]
