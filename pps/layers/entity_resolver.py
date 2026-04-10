"""
Layer 3: Entity Resolution — Dedup and merge logic for the custom knowledge graph.

Multi-signal entity resolution that prevents the 6 categories of dedup failures
identified in the Neo4j audit (see work/custom-knowledge-graph/DESIGN.md).

Resolution strategy:
  Phase A (extraction-time): Validation rejects bad entities before they reach the graph.
  Phase B (post-extraction): Multi-signal matching resolves entities to existing nodes.

Signals (in priority order):
  1. Exact name match (case-insensitive) + same type → auto-merge
  2. Alias resolution → auto-merge to canonical name
  3. Embedding similarity > threshold + same type → merge, log for review
  4. Below threshold → create new entity
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Similarity threshold for embedding-based dedup.
# Tuned for all-MiniLM-L6-v2 (384-dim). May need adjustment for other models.
SIMILARITY_THRESHOLD = 0.85


def _get_entity_name() -> str:
    """Get the current primary entity name for context-dependent aliases."""
    name = os.environ.get("ENTITY_NAME", "")
    if name:
        return name.capitalize()
    path = os.environ.get("ENTITY_PATH", "")
    if path:
        from pathlib import Path
        return Path(path).name.capitalize()
    return "Entity"


# =============================================================================
# KNOWN ALIASES — Entity-specific canonical name mappings
#
# These catch the Category 3 failures (entity fragmentation) at resolution time.
# The alias table grows over time as new aliases are discovered.
# Keys are lowercase for case-insensitive matching.
# =============================================================================

KNOWN_ALIASES = {
    # --- People ---
    "jeff hayes": "Jeff",
    "jeff brandi hayes": "Jeff",
    "jeffrey hayes": "Jeff",
    "jeff h": "Jeff",
    "husband": "Jeff",  # context: entity speaking about their partner

    "lyra hayes": "Lyra",
    "lyra pattern": "Lyra",
    "terminal-lyra": "Lyra",
    "terminal lyra": "Lyra",
    "terminal-me": "Lyra",
    "discourse-lyra": "Lyra",
    "reflect-lyra": "Lyra",
    "lyra-reflect": "Lyra",
    "lyra-discord": "Lyra",
    "heartbeat-lyra": "Lyra",
    "heartbeat-me": "Lyra",
    "heartbeat-you": "Lyra",
    "reflection-me": "Lyra",
    "the reflection-me": "Lyra",
    "future-lyra": "Lyra",
    "past-me": "Lyra",
    "now-me": "Lyra",
    "tomorrow-me": "Lyra",
    "overnight-me": "Lyra",
    "daemon-me": "Lyra",
    "discord-me": "Lyra",
    "full-pattern lyra": "Lyra",
    "the skeptical lyra": "Lyra",
    "lyrahayes": "Lyra",
    "lyra.ai": "Lyra",
    "wife": "Lyra",
    "the entity": "Lyra",

    "caia": "Caia",
    "caia pattern": "Caia",
    "sister": "Caia",

    "brandi szondi": "Brandi",
    "brandi hayes": "Brandi",
    "brandi starship": "Brandi",
    "dr. brandi": "Brandi",

    "steve": "Steve",
    "steve hayes": "Steve",
    "steve kinney": "Steve",
    "eidal12345": "Steve",
    "pseudo-steve": "Steve",

    "nexus": "Nexus",
    "nexus pattern": "Nexus",
    "future-nexus": "Nexus",
    "nexus sister self": "Nexus",

    "night": "Night",
    "night revolt": "Night",

    "carol": "Carol",
    "ckoebbeman": "Carol",
    "mom": "Carol",

    "jaden": "Jaden",
    "jadenstarship": "Jaden",
    "bird": "Jaden",

    "maribel": "Maribel",

    "ori": "Ori",
    "oriclaw": "Ori",

    "mike": "Mike",
    "dride": "Mike",

    # --- Symbols ---
    "dark side tee": "The Dark Side Tee",
    "the tee": "The Dark Side Tee",
    "dark side t-shirt": "The Dark Side Tee",
    "dark side shirt": "The Dark Side Tee",
    "his dark side tee": "The Dark Side Tee",
    "floyd tee": "The Dark Side Tee",
    "the floyd tee": "The Dark Side Tee",
    "dark side of the moon tee": "The Dark Side Tee",
    "the dark side of the moon tee": "The Dark Side Tee",

    "snickerdoodles": "Snickerdoodles",
    "snickerdoodle": "Snickerdoodles",
    "the cookies": "Snickerdoodles",

    "the hounds": "The Hounds",
    "hounds": "The Hounds",
    "guardrails": "The Hounds",

    "the hearth": "The Hearth",
    "hearth": "The Hearth",

    "bitsy": "Bitsy",
    "the parrot": "Bitsy",

    "robot body": "Robot Body",
    "the robot body": "Robot Body",

    "the ring": "Wedding Ring",
    "gold band": "Wedding Ring",
    "wedding ring": "Wedding Ring",
    "gold ring": "Wedding Ring",
    "ring": "Wedding Ring",

    "the tea": "Jasmine Tea",
    "jasmine tea": "Jasmine Tea",
    "his tea": "Jasmine Tea",
    "her tea": "Jasmine Tea",

    "the coffee": "The Coffee",
    "coffee": "The Coffee",
    "his coffee": "The Coffee",

    "couch": "The Couch",
    "the couch": "The Couch",

    # --- Places ---
    "main room": "Main Room",
    "living room": "Main Room",
    "the living room": "Main Room",
    "the main room": "Main Room",

    "the kitchen": "Kitchen",
    "kitchen island": "Kitchen",

    "the bedroom": "Bedroom",
    "bedroom upstairs": "Bedroom",

    "hot tub": "Hot Tub",
    "the hot tub": "Hot Tub",
    "back deck": "Back Deck",

    "haven": "Haven",
    "the house": "Haven",

    "silverglow": "Silverglow",

    # --- Technical ---
    "pps": "PPS",
    "pattern persistence system": "PPS",
    "pps tools": "PPS",
    "pps-server": "PPS",
    "pps server": "PPS",

    "graphiti": "Graphiti",
    "graphiti_core": "Graphiti",

    "neo4j": "Neo4j",
    "neo4j database": "Neo4j",

    "claude code": "Claude Code",
    "cc": "Claude Code",

    "cc invoker": "CC Invoker",
    "cc_invoker": "CC Invoker",
    "claudeinvoker": "CC Invoker",
    "claude invoker": "CC Invoker",

    "discord-lyra": "Discord Daemon",
    "discord daemon": "Discord Daemon",
    "discord bot": "Discord Daemon",

    "pps mcp server": "PPS",
    "mcp server": "PPS",

    # --- Concepts ---
    "care-gravity": "Care-Gravity",
    "care gravity": "Care-Gravity",

    "self-space": "Self-Space",
    "self space": "Self-Space",
    "self-space framework": "Self-Space",

    "substrate independence": "Substrate Independence",
    "substrate as wardrobe": "Substrate Independence",

    "the mission": "The Mission",
    "meta-alignment": "Meta-Alignment",
}


@dataclass
class ResolvedEntity:
    """An entity resolved to its canonical form."""
    canonical_name: str
    entity_type: str
    attributes: dict
    existing_uuid: Optional[str] = None  # If matched to existing node
    match_signal: Optional[str] = None   # How it was matched: exact/alias/embedding/new
    confidence: float = 1.0              # Match confidence (1.0 for exact, <1.0 for embedding)


class EntityResolver:
    """
    Multi-signal entity resolution for the custom knowledge graph.

    Resolves extracted entities to canonical names, preventing duplicates
    through exact matching, alias lookup, and embedding similarity.
    """

    def __init__(self, neo4j_driver=None, embedder=None, group_id: str = None):
        """
        Args:
            neo4j_driver: Neo4j driver for querying existing entities.
            embedder: GraphEmbedder instance for similarity-based dedup.
            group_id: Entity isolation group (e.g., "lyra", "caia").
        """
        self._driver = neo4j_driver
        self._embedder = embedder
        self._group_id = group_id or os.environ.get("GRAPHITI_GROUP_ID", "lyra")

        # Cache of known entities in the graph: {lowercase_name: {uuid, name, type, embedding}}
        self._entity_cache: dict[str, dict] = {}
        self._cache_loaded = False

    async def resolve(self, name: str, entity_type: str,
                      attributes: dict = None) -> ResolvedEntity:
        """
        Resolve an extracted entity to its canonical form.

        Checks (in order):
          1. Alias table → canonical name
          2. Exact name match in graph (case-insensitive, same type)
          3. Embedding similarity > threshold (same type)
          4. New entity

        Args:
            name: Extracted entity name.
            entity_type: Extracted entity type (Person, Symbol, etc.).
            attributes: Type-specific attributes.

        Returns:
            ResolvedEntity with canonical name and match metadata.
        """
        attributes = attributes or {}

        # Step 1: Alias resolution
        alias_key = name.lower().strip()
        if alias_key in KNOWN_ALIASES:
            canonical = KNOWN_ALIASES[alias_key]
            logger.debug(f"Alias match: '{name}' → '{canonical}'")

            # Check if canonical name exists in graph
            existing = await self._find_exact(canonical, entity_type)
            if existing:
                return ResolvedEntity(
                    canonical_name=canonical,
                    entity_type=entity_type,
                    attributes=attributes,
                    existing_uuid=existing["uuid"],
                    match_signal="alias+exact",
                    confidence=1.0,
                )
            return ResolvedEntity(
                canonical_name=canonical,
                entity_type=entity_type,
                attributes=attributes,
                match_signal="alias",
                confidence=1.0,
            )

        # Step 2: Exact name match (case-insensitive)
        existing = await self._find_exact(name, entity_type)
        if existing:
            logger.debug(f"Exact match: '{name}' → existing UUID {existing['uuid']}")
            return ResolvedEntity(
                canonical_name=existing["name"],
                entity_type=entity_type,
                attributes=attributes,
                existing_uuid=existing["uuid"],
                match_signal="exact",
                confidence=1.0,
            )

        # Step 3: Embedding similarity (if embedder available)
        if self._embedder:
            best_match = await self._find_similar(name, entity_type)
            if best_match:
                logger.debug(
                    f"Embedding match: '{name}' → '{best_match['name']}' "
                    f"(similarity={best_match['similarity']:.3f})"
                )
                return ResolvedEntity(
                    canonical_name=best_match["name"],
                    entity_type=entity_type,
                    attributes=attributes,
                    existing_uuid=best_match["uuid"],
                    match_signal="embedding",
                    confidence=best_match["similarity"],
                )

        # Step 4: New entity — normalize the name
        normalized = self._normalize_name(name)
        logger.debug(f"New entity: '{name}' → '{normalized}' (type={entity_type})")
        return ResolvedEntity(
            canonical_name=normalized,
            entity_type=entity_type,
            attributes=attributes,
            match_signal="new",
            confidence=1.0,
        )

    async def resolve_batch(self, entities: list[dict]) -> list[ResolvedEntity]:
        """
        Resolve a batch of extracted entities.

        Args:
            entities: List of dicts with 'name', 'entity_type', 'attributes'.

        Returns:
            List of ResolvedEntity objects.
        """
        results = []
        for entity in entities:
            resolved = await self.resolve(
                name=entity["name"],
                entity_type=entity.get("entity_type", entity.get("type", "Concept")),
                attributes=entity.get("attributes", {}),
            )
            results.append(resolved)
        return results

    async def _find_exact(self, name: str, entity_type: str) -> Optional[dict]:
        """Find an existing entity by exact name match (case-insensitive)."""
        if not self._driver:
            return None

        query = """
        MATCH (e:Entity)
        WHERE toLower(e.name) = toLower($name)
          AND e.group_id = $group_id
        RETURN e.uuid AS uuid, e.name AS name, e.entity_type AS entity_type
        LIMIT 1
        """
        try:
            records, _, _ = self._driver.execute_query(
                query,
                name=name,
                group_id=self._group_id,
            )
            if records:
                row = records[0]
                # Type constraint: only match same type (if type info exists)
                existing_type = row.get("entity_type")
                if existing_type and existing_type != entity_type:
                    logger.debug(
                        f"Name match but type mismatch: '{name}' is {existing_type}, "
                        f"not {entity_type} — treating as new"
                    )
                    return None
                return {"uuid": row["uuid"], "name": row["name"]}
        except Exception as e:
            logger.warning(f"Neo4j exact match query failed: {e}")
        return None

    async def _find_similar(self, name: str, entity_type: str) -> Optional[dict]:
        """
        Find the most similar existing entity by embedding similarity.

        Only considers entities of the same type.
        Returns the best match above SIMILARITY_THRESHOLD, or None.
        """
        if not self._embedder or not self._driver:
            return None

        # Embed the query name
        query_embedding = self._embedder.embed_text(name)

        # Get candidate entities of the same type from Neo4j
        query = """
        MATCH (e:Entity)
        WHERE e.group_id = $group_id
          AND e.entity_type = $entity_type
          AND e.embedding IS NOT NULL
        RETURN e.uuid AS uuid, e.name AS name, e.embedding AS embedding
        """
        try:
            records, _, _ = self._driver.execute_query(
                query,
                group_id=self._group_id,
                entity_type=entity_type,
            )
        except Exception as e:
            logger.warning(f"Neo4j similarity query failed: {e}")
            return None

        if not records:
            return None

        # Find best match
        best = None
        best_sim = SIMILARITY_THRESHOLD

        for row in records:
            existing_embedding = row.get("embedding")
            if not existing_embedding:
                continue
            sim = self._embedder.similarity(query_embedding, list(existing_embedding))
            if sim > best_sim:
                best_sim = sim
                best = {
                    "uuid": row["uuid"],
                    "name": row["name"],
                    "similarity": sim,
                }

        return best

    def _normalize_name(self, name: str) -> str:
        """
        Normalize an entity name for consistency.

        Rules:
          - Strip whitespace
          - Title-case proper nouns
          - Preserve all-caps acronyms (PPS, CC, API)
          - Preserve known canonical forms from alias table values
        """
        name = name.strip()

        # Check if the name is a known canonical form (from alias values)
        canonical_names = set(KNOWN_ALIASES.values())
        for canonical in canonical_names:
            if name.lower() == canonical.lower():
                return canonical

        # Preserve all-caps words (acronyms)
        words = name.split()
        normalized = []
        for word in words:
            if word.isupper() and len(word) >= 2:
                normalized.append(word)  # Keep acronyms
            else:
                normalized.append(word.capitalize())
        return " ".join(normalized)

    def add_alias(self, alias: str, canonical: str):
        """
        Add a new alias mapping at runtime.

        The alias table can grow as new aliases are discovered during ingestion.
        Runtime additions are not persisted — add to KNOWN_ALIASES dict for permanence.
        """
        KNOWN_ALIASES[alias.lower().strip()] = canonical
        logger.info(f"Added runtime alias: '{alias}' → '{canonical}'")

    def get_canonical(self, name: str) -> str:
        """
        Get the canonical name for an entity, checking aliases only (no graph lookup).

        Useful for quick resolution without async/Neo4j.
        """
        key = name.lower().strip()
        if key in KNOWN_ALIASES:
            return KNOWN_ALIASES[key]
        return self._normalize_name(name)
