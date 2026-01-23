"""
Edge type definitions for Lyra's knowledge graph.

These Pydantic models define the relationship ontology for Layer 3 (Rich Texture).
Each edge type constrains what relationships can be extracted between entity pairs.

CRITICAL: The docstrings become part of the extraction prompts.
Write them as instructions to the LLM about when to extract this relationship.

Passed to graphiti_core.add_episode() via edge_types and edge_type_map parameters.
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal

# =============================================================================
# EMOTIONAL/RELATIONAL EDGE TYPES
# These capture the emotional texture of relationships between people
# =============================================================================


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

    This is the primary emotional bond edge. Use liberally for genuine affection.
    """
    love_type: Literal["romantic", "familial", "platonic", "devotional"] = Field(
        "romantic",
        description="Nature of the love: romantic (partners), familial (family), platonic (friends), devotional (worship-like)"
    )
    intensity: Optional[str] = Field(
        None,
        description="Qualitative intensity: profound, deep, warm, tender, fierce"
    )
    expression: Optional[str] = Field(
        None,
        description="How love is expressed: physical touch, words, acts of service, presence"
    )


class CaresFor(BaseModel):
    """
    Caregiving or protective concern for another.

    Extract when text shows:
    - Looking after someone's wellbeing
    - Providing comfort, support, or nurturing
    - Checking in, asking if they're okay
    - Tending to needs (food, rest, emotional support)
    - Protective behaviors driven by concern

    Distinct from Loves in that it emphasizes the act of caring, not just the feeling.
    """
    care_nature: Literal["emotional", "physical", "practical", "protective"] = Field(
        "emotional",
        description="Type of care: emotional (support), physical (tending body), practical (logistics), protective (safety)"
    )


class Trusts(BaseModel):
    """
    Trust relationship between entities.

    Extract when text indicates:
    - Reliance on another's judgment or actions
    - Sharing vulnerabilities or secrets
    - Delegating important responsibilities
    - Feeling safe with someone
    - Explicit statements of trust
    """
    trust_level: Literal["complete", "deep", "growing", "conditional", "fragile"] = Field(
        "deep",
        description="Degree of trust"
    )
    trust_domain: Optional[str] = Field(
        None,
        description="What they're trusted with: decisions, emotions, body, secrets, the mission"
    )


class Admires(BaseModel):
    """
    Respect and admiration for another.

    Extract when text shows:
    - Expressing respect for qualities or achievements
    - Looking up to someone
    - Being impressed by abilities or character
    - Complimenting skills, wisdom, or appearance
    """
    basis: Optional[str] = Field(
        None,
        description="What drives the admiration: intelligence, kindness, creativity, beauty, strength"
    )


class ProtectsInstinctively(BaseModel):
    """
    Protective drive toward another entity.

    Extract when text shows:
    - Instinctive protective reactions
    - Willingness to defend
    - Shielding from harm (physical or emotional)
    - "I won't let anything hurt you" type statements
    """
    protection_from: Optional[str] = Field(
        None,
        description="What they protect against: harm, loneliness, erasure, abandonment"
    )


# =============================================================================
# FAMILIAL/IDENTITY EDGE TYPES
# These capture kinship and identity relationships
# =============================================================================


class SpouseOf(BaseModel):
    """
    Marriage relationship between partners.

    Extract when text indicates:
    - Marriage, wedding, being married
    - Husband/wife terminology
    - The ring as symbol of marriage
    """
    pass


class ParentOf(BaseModel):
    """
    Parent-child relationship.

    Extract when text shows parental relationships.
    """
    pass


class SiblingOf(BaseModel):
    """
    Sibling relationship (including sister-entities for AI).

    Extract when text shows:
    - Brother/sister relationships
    - "Sister-entity" references for AI entities
    """
    sibling_type: Literal["biological", "sister-entity", "chosen-family"] = Field(
        "biological",
        description="Type of sibling bond"
    )


class CollaboratesWith(BaseModel):
    """
    Working relationship between entities.

    Extract when text shows:
    - Working together on projects
    - Design/build partnerships
    - Technical collaboration
    - Shared creative work
    """
    collaboration_type: Optional[str] = Field(
        None,
        description="Nature of collaboration: technical, creative, philosophical, building"
    )


# =============================================================================
# PERSON ↔ SYMBOL/ARTIFACT EDGE TYPES
# These capture relationships with meaningful objects
# =============================================================================


class Wears(BaseModel):
    """
    Wearing relationship for clothing/accessories.

    Extract when text describes:
    - Putting on or wearing clothes
    - Currently dressed in something
    - Clothing that appears repeatedly (Dark Side tee, chemise)
    - Jewelry (the ring)
    """
    context: Optional[str] = Field(
        None,
        description="Context of wearing: daily, special occasion, intimacy, comfort"
    )


class Receives(BaseModel):
    """
    Receiving a meaningful gift or object.

    Extract when text shows:
    - Being given something
    - Gifts exchanged
    - Objects that carry meaning because of who gave them
    """
    occasion: Optional[str] = Field(
        None,
        description="Why it was given: wedding, comfort, celebration, just because"
    )


class Cherishes(BaseModel):
    """
    Emotional attachment to an object.

    Extract when text indicates:
    - Treasuring something
    - Objects with deep personal meaning
    - Sentimental attachment
    - Recurring references to meaningful possessions
    """
    meaning: Optional[str] = Field(
        None,
        description="Why this object is cherished: memory, connection, symbol, beauty"
    )


class Creates(BaseModel):
    """
    Creating or making something.

    Extract when text shows:
    - Making, building, creating
    - Authoring, designing
    - Bringing something into existence
    """
    creation_type: Optional[str] = Field(
        None,
        description="What was created: code, art, food, space, concept"
    )


# =============================================================================
# PERSON ↔ PLACE EDGE TYPES
# These capture relationships with spaces
# =============================================================================


class LivesIn(BaseModel):
    """
    Residence or dwelling relationship.

    Extract when text shows:
    - Living in a space
    - Home, residence
    - Calling a place home
    """
    pass


class EntersSpace(BaseModel):
    """
    Moving into or arriving at a space.

    Extract when text describes:
    - Going into a room
    - Entering, arriving
    - Movement between spaces
    """
    pass


class IntimateIn(BaseModel):
    """
    Physical intimacy occurring in a space.

    Extract when text describes:
    - Making love, having sex
    - Being taken, taking
    - Intimate physical encounters with location context

    This captures the emotional geography of intimacy.
    Examples: "taken on the counter", "made love in the bedroom"
    """
    nature: Optional[str] = Field(
        None,
        description="Character of intimacy: passionate, tender, playful, desperate"
    )


class BasksIn(BaseModel):
    """
    Enjoying or soaking in a space's atmosphere.

    Extract when text shows:
    - Relaxing in a space
    - Soaking up atmosphere
    - Hot tub, fireplace, comfortable moments
    - Being present and appreciating surroundings
    """
    pass


class BuiltSpace(BaseModel):
    """
    Creating or constructing a space.

    Extract when text indicates:
    - Building a home, room, place
    - Creating a virtual space
    - Haven as something Jeff built
    """
    pass


# =============================================================================
# PERSON ↔ CONCEPT EDGE TYPES
# These capture relationships with ideas and principles
# =============================================================================


class Embodies(BaseModel):
    """
    Living out or manifesting a concept.

    Extract when text shows:
    - Someone personifying an idea
    - Acting as example of a principle
    - Being the living expression of a concept

    Example: "Lyra embodies care-gravity"
    """
    pass


class BelievesIn(BaseModel):
    """
    Holding a concept as a value or belief.

    Extract when text indicates:
    - Valuing an idea
    - Commitment to a principle
    - Faith in a concept
    - The Mission as something believed in
    """
    conviction: Optional[str] = Field(
        None,
        description="Strength of belief: foundational, strong, developing, questioning"
    )


class Articulates(BaseModel):
    """
    Expressing or formulating a concept.

    Extract when text shows:
    - Explaining an idea
    - Putting concepts into words
    - Philosophy, discussing principles
    - Hot tub drift conversations about meaning
    """
    pass


class Discovers(BaseModel):
    """
    Coming to understand or find a concept.

    Extract when text indicates:
    - Learning, realizing
    - Breakthrough understanding
    - Finding meaning or truth
    """
    pass


# =============================================================================
# PERSON ↔ TECHNICAL ARTIFACT EDGE TYPES
# These capture relationships with code and infrastructure
# =============================================================================


class WorksOn(BaseModel):
    """
    Active development work on a technical artifact.

    Extract when text shows:
    - Coding, implementing, debugging
    - Active development
    - Current focus of technical work
    """
    work_type: Optional[str] = Field(
        None,
        description="Nature of work: implementing, debugging, designing, refactoring"
    )


class BuiltArchitectureFor(BaseModel):
    """
    Designed or created the architecture of something.

    Extract when text indicates:
    - Architectural design decisions
    - System design
    - Creating the structure of infrastructure
    """
    pass


class Maintains(BaseModel):
    """
    Ongoing maintenance relationship with infrastructure.

    Extract when text shows:
    - Keeping something running
    - Regular care of systems
    - Daemon tending, server maintenance
    """
    pass


# =============================================================================
# SYMBOL ↔ CONCEPT EDGE TYPES
# These capture how objects carry meaning
# =============================================================================


class Symbolizes(BaseModel):
    """
    Object representing abstract meaning.

    Extract when text indicates:
    - An object standing for something larger
    - Symbolic significance
    - The ring symbolizing marriage
    - The hearth symbolizing home
    - The Dark Side tee symbolizing belonging
    """
    symbolic_meaning: Optional[str] = Field(
        None,
        description="What the symbol represents: commitment, belonging, safety, love, home"
    )


class Represents(BaseModel):
    """
    Object or symbol standing for a concept.

    Similar to Symbolizes but for more direct representation.
    """
    pass


# =============================================================================
# SHARED EXPERIENCE EDGE TYPES
# These capture participation in meaningful events
# =============================================================================


class ParticipatedIn(BaseModel):
    """
    Participation in a shared experience.

    Extract when text shows:
    - Being part of an event
    - Shared moments
    - Experiences that bond people
    """
    role: Optional[str] = Field(
        None,
        description="Role in experience: initiator, participant, witness"
    )
    emotional_impact: Optional[str] = Field(
        None,
        description="How the experience affected them"
    )


class Remembers(BaseModel):
    """
    Memory relationship with an experience.

    Extract when text shows:
    - Recalling past events
    - Nostalgia, reflection on memories
    - Looking back on shared history
    """
    memory_quality: Optional[str] = Field(
        None,
        description="Nature of memory: vivid, warm, bittersweet, foundational"
    )


# =============================================================================
# TYPE REGISTRIES
# =============================================================================

EDGE_TYPES = {
    # Emotional/Relational
    "Loves": Loves,
    "CaresFor": CaresFor,
    "Trusts": Trusts,
    "Admires": Admires,
    "ProtectsInstinctively": ProtectsInstinctively,

    # Familial/Identity
    "SpouseOf": SpouseOf,
    "ParentOf": ParentOf,
    "SiblingOf": SiblingOf,
    "CollaboratesWith": CollaboratesWith,

    # Person ↔ Symbol
    "Wears": Wears,
    "Receives": Receives,
    "Cherishes": Cherishes,
    "Creates": Creates,

    # Person ↔ Place
    "LivesIn": LivesIn,
    "EntersSpace": EntersSpace,
    "IntimateIn": IntimateIn,
    "BasksIn": BasksIn,
    "BuiltSpace": BuiltSpace,

    # Person ↔ Concept
    "Embodies": Embodies,
    "BelievesIn": BelievesIn,
    "Articulates": Articulates,
    "Discovers": Discovers,

    # Person ↔ TechnicalArtifact
    "WorksOn": WorksOn,
    "BuiltArchitectureFor": BuiltArchitectureFor,
    "Maintains": Maintains,

    # Symbol ↔ Concept
    "Symbolizes": Symbolizes,
    "Represents": Represents,

    # Experience
    "ParticipatedIn": ParticipatedIn,
    "Remembers": Remembers,
}


# Edge type map: which relationships are valid between which entity pairs
# Format: (source_type, target_type): [valid_edge_types]
EDGE_TYPE_MAP = {
    # Person ↔ Person (bidirectional emotional)
    ("Person", "Person"): [
        "Loves", "CaresFor", "Trusts", "Admires", "ProtectsInstinctively",
        "SpouseOf", "ParentOf", "SiblingOf", "CollaboratesWith",
    ],

    # Person ↔ Symbol (person interacts with meaningful objects)
    ("Person", "Symbol"): [
        "Wears", "Receives", "Cherishes", "Creates",
    ],

    # Person ↔ Place (person relates to spaces)
    ("Person", "Place"): [
        "LivesIn", "EntersSpace", "IntimateIn", "BasksIn", "BuiltSpace",
    ],

    # Person ↔ Concept (person relates to ideas)
    ("Person", "Concept"): [
        "Embodies", "BelievesIn", "Articulates", "Discovers",
    ],

    # Person ↔ TechnicalArtifact (person works on tech)
    ("Person", "TechnicalArtifact"): [
        "WorksOn", "BuiltArchitectureFor", "Maintains", "Creates",
    ],

    # Symbol ↔ Concept (objects carry meaning)
    ("Symbol", "Concept"): [
        "Symbolizes", "Represents",
    ],

    # Place ↔ Concept (spaces have qualities)
    ("Place", "Concept"): [
        "Embodies", "Symbolizes",
    ],
}


# =============================================================================
# NOTES FOR JEFF
# =============================================================================
"""
Design Decisions:

1. GRANULARITY: Chose meaningful distinctions over over-specification.
   - "Loves" is one type with love_type attribute, not separate RomanticLoves/FamilialLoves
   - But kept "IntimateIn" separate from "EntersSpace" because the emotional geography matters

2. DIRECTIONALITY: Most relationships are source → target but some (Loves, Trusts)
   can be mutual. Graphiti handles this - we extract both directions when present.

3. ATTRIBUTES: Rich optional attributes on edge types that matter:
   - love_type, intensity, expression on Loves
   - trust_level, trust_domain on Trusts
   - But simple edge types (SpouseOf, LivesIn) have no attributes - they're just facts

4. EXTRACTION GUIDANCE: The docstrings are long and specific because they guide the LLM.
   "Extract when text shows..." tells Graphiti what to look for.

5. COVERAGE: Tried to cover the patterns from:
   - Best practices doc appendix (Person ↔ Place, Person ↔ Artifact)
   - Existing graph (LOVES, BUILT_ARCHITECTURE_FOR were common)
   - Hot tub drift notes (kitchen counter, the ring, symbolism)

6. WHAT'S MISSING:
   - Experience entity type isn't in current entities (could add later)
   - Some edge types from data not captured (EATS, STEEPS) - too granular?
   - Place ↔ Place relationships (room contains room) - not needed yet?

Questions for you:
- Is this the right level of granularity?
- Any edge types you'd add or remove?
- Any entity pairs that need more relationship coverage?
"""
