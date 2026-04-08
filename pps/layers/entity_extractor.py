"""
Entity and relationship extraction from text using a local LLM.

This is Stage 1 of the custom knowledge graph pipeline (replacing Graphiti).
Takes raw conversation text and returns structured entities + relationships
ready for Stage 2 (resolution/dedup).

Uses an OpenAI-compatible local LLM endpoint (e.g., LM Studio with Qwen).
Falls back to env vars for configuration.

Environment variables:
    CUSTOM_LLM_BASE_URL: LLM endpoint base URL (default: http://10.0.0.120:1234/v1)
    CUSTOM_LLM_MODEL:    Model name (default: qwen3-1.7b)
    ENTITY_NAME:         Primary entity name for resolution hints
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field

import httpx

from pps.layers.extraction_context import (
    build_extraction_instructions,
    get_entity_name,
    get_speaker_from_content,
)
from pps.layers.rich_texture_edge_types import EDGE_TYPE_MAP
from pps.layers.rich_texture_entities import ENTITY_TYPES

logger = logging.getLogger(__name__)

# Valid entity type names (derived from ENTITY_TYPES registry)
VALID_ENTITY_TYPES = set(ENTITY_TYPES.keys())

# Words in entity names that signal junk extractions (Category 6: session descriptions)
_JUNK_NAME_WORDS = {"session", "random", "call with"}

# Single-word names that should never be entities (pronouns, generics)
_JUNK_EXACT_NAMES = {
    "he", "she", "they", "we", "you", "me", "i", "us", "self",
    "user", "people", "someone", "everyone", "nobody",
    "agent 1", "agent 2", "agent",
}

# Default LLM config
_DEFAULT_BASE_URL = "http://10.0.0.120:1234/v1"
_DEFAULT_MODEL = "qwen3-1.7b"


# =============================================================================
# Data classes
# =============================================================================


@dataclass
class ExtractedEntity:
    """A single entity extracted from text."""

    name: str
    entity_type: str  # One of VALID_ENTITY_TYPES
    attributes: dict = field(default_factory=dict)


@dataclass
class ExtractedRelationship:
    """A relationship between two extracted entities."""

    source_name: str
    target_name: str
    edge_type: str    # Must be a key in EDGE_TYPES and valid for the source→target type pair
    fact_text: str    # Natural language description of the relationship fact


@dataclass
class ExtractionResult:
    """Full result of one extraction call."""

    entities: list[ExtractedEntity]
    relationships: list[ExtractedRelationship]
    raw_response: str  # Preserved for debugging


# =============================================================================
# Main extractor
# =============================================================================


class EntityExtractor:
    """
    Extract entities and relationships from text using a local LLM.

    Wraps a local OpenAI-compatible endpoint (e.g., LM Studio).
    Applies post-extraction validation per the DESIGN.md taxonomy before
    returning results — bad extractions never leave this class.

    Usage::

        extractor = EntityExtractor()
        result = await extractor.extract(
            text="Jeff and Lyra were in the main room.",
            channel="terminal",
        )
        for e in result.entities:
            print(e.name, e.entity_type)
    """

    def __init__(
        self,
        llm_base_url: str | None = None,
        llm_model: str | None = None,
    ) -> None:
        self._base_url = (
            llm_base_url
            or os.environ.get("CUSTOM_LLM_BASE_URL", _DEFAULT_BASE_URL)
        ).rstrip("/")
        self._model = llm_model or os.environ.get("CUSTOM_LLM_MODEL", _DEFAULT_MODEL)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def extract(
        self,
        text: str,
        channel: str = "terminal",
        speaker: str | None = None,
        entity_name: str | None = None,
    ) -> ExtractionResult:
        """
        Extract entities and relationships from text.

        Args:
            text:        Raw conversation text or message body.
            channel:     Source channel (terminal, discord, reflection, …).
            speaker:     Who said the text. Auto-detected from content if None.
            entity_name: Primary entity for resolution hints. Defaults to
                         ENTITY_NAME env var or ENTITY_PATH folder name.

        Returns:
            ExtractionResult with validated entities and relationships.

        Raises:
            httpx.ConnectError: If the LLM endpoint is unreachable.
            RuntimeError:       If the LLM returns unusable output after retry.
        """
        resolved_speaker = speaker or get_speaker_from_content(text, channel)
        resolved_entity = entity_name or get_entity_name()

        prompt = self._build_prompt(text, channel, resolved_speaker, resolved_entity)

        raw = await self._call_llm(prompt)
        parsed = self._parse_response(raw)

        if parsed is None:
            logger.warning("Initial parse failed — retrying with simplified prompt")
            simple_prompt = self._build_simple_prompt(text)
            raw = await self._call_llm(simple_prompt)
            parsed = self._parse_response(raw)

        if parsed is None:
            raise RuntimeError(
                f"LLM returned invalid JSON after retry. Raw response: {raw[:500]!r}"
            )

        entities, relationships = self._validate_and_build(parsed, resolved_entity)

        logger.info(
            "Extraction complete: %d entities, %d relationships (%d validation rejections)",
            len(entities),
            len(relationships),
            _count_raw_items(parsed) - len(entities) - len(relationships),
        )

        return ExtractionResult(
            entities=entities,
            relationships=relationships,
            raw_response=raw,
        )

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        text: str,
        channel: str,
        speaker: str,
        entity_name: str,
    ) -> str:
        """Build the full extraction prompt using extraction_context.py."""
        context = build_extraction_instructions(
            channel=channel,
            entity_name=entity_name,
        )

        edge_type_summary = _format_edge_type_summary()

        return f"""{context}

---

## Your Task

Given the message below from **{speaker}**, extract all entities and relationships.

Message:
\"{text}\"

Respond with ONLY a valid JSON object in this exact format — no explanation, no markdown fences:

{{
  "entities": [
    {{"name": "...", "type": "Person|Symbol|Place|Concept|TechnicalArtifact"}}
  ],
  "relationships": [
    {{"source": "...", "target": "...", "type": "EdgeTypeName", "fact": "A complete sentence describing the relationship."}}
  ]
}}

## Hard Rules

1. Entity names must be 1–5 words. NEVER use a sentence as an entity name.
2. Entity type must be exactly one of: Person, Symbol, Place, Concept, TechnicalArtifact
3. Reject file paths as entity names (anything starting with /, ~, or .)
4. Reject session descriptions (names containing "session", "random", "call with")
5. Always extract **Jeff** and **{entity_name}** when they appear in the text.
6. EVERY relationship MUST have a "fact" field containing a COMPLETE SENTENCE. No attributes objects. No empty facts. The fact is the most important field — it captures WHAT happened.
7. Do NOT add "attributes" to entities. Only "name" and "type".
8. Edge types must match valid pairs:

{edge_type_summary}

9. Use entity names from the extracted entities list for source/target in relationships.
10. Extract at most 6 entities and 8 relationships. Focus on the MOST IMPORTANT people and facts, skip minor technical details.
"""

    def _build_simple_prompt(self, text: str) -> str:
        """Simplified retry prompt — minimal context, just get valid JSON back."""
        return f"""Extract entities and relationships from this text as JSON.

Text: \"{text}\"

Reply with ONLY this JSON, nothing else:
{{
  "entities": [{{"name": "string", "type": "Person|Symbol|Place|Concept|TechnicalArtifact"}}],
  "relationships": [{{"source": "string", "target": "string", "type": "EdgeTypeName", "fact": "A complete sentence."}}]
}}

CRITICAL: Every relationship MUST have a "fact" sentence. No "attributes" objects anywhere.
Entity types: Person, Symbol, Place, Concept, TechnicalArtifact
Common edge types: Loves, CaresFor, CollaboratesWith, WorksOn, LivesIn, BelievesIn, Symbolizes
"""

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    async def _call_llm(self, prompt: str) -> str:
        """
        POST to the local LLM endpoint and return the response text.

        Raises:
            httpx.ConnectError: If the endpoint is unreachable.
        """
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "You are a JSON extraction tool. Output ONLY valid JSON. No reasoning, no explanation, no <think> tags."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,   # Low temperature for consistent structured output
            "max_tokens": 4096,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        return data["choices"][0]["message"]["content"]

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, raw: str) -> dict | None:
        """
        Parse the LLM response as JSON.

        Handles common LLM noise: markdown fences, <think> blocks, leading/trailing text.
        Returns None if parsing fails.
        """
        # Strip <think>...</think> blocks (qwen3 reasoning output)
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw).strip()

        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?\s*", "", cleaned).strip()
        cleaned = re.sub(r"```\s*$", "", cleaned).strip()

        # Try to extract a JSON object if there's surrounding text
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            cleaned = match.group(0)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.debug("JSON parse failed: %s — raw: %r", exc, raw[:200])
            return None

        # Minimal structure check
        if not isinstance(parsed, dict):
            return None
        if "entities" not in parsed and "relationships" not in parsed:
            return None

        return parsed

    # ------------------------------------------------------------------
    # Validation and construction
    # ------------------------------------------------------------------

    def _validate_and_build(
        self,
        parsed: dict,
        entity_name: str,
    ) -> tuple[list[ExtractedEntity], list[ExtractedRelationship]]:
        """
        Validate raw parsed data and build typed result objects.

        Applies all Phase A prevention rules from DESIGN.md.
        """
        # Build entity map first (name → type) so we can validate relationships
        raw_entities = parsed.get("entities") or []
        entities: list[ExtractedEntity] = []
        entity_type_map: dict[str, str] = {}  # normalized_name → entity_type

        for item in raw_entities:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")) if item.get("name") is not None else ""
            entity_type = str(item.get("type", "")) if item.get("type") is not None else ""
            attributes = item.get("attributes") or {}
            if not isinstance(attributes, dict):
                attributes = {}

            if not self._validate_entity(name, entity_type):
                logger.debug("Rejected entity: %r (%r)", name, entity_type)
                continue

            normalized = self._normalize_entity_name(name)
            entities.append(ExtractedEntity(
                name=normalized,
                entity_type=entity_type,
                attributes=attributes,
            ))
            entity_type_map[normalized.lower()] = entity_type

        # Validate relationships
        raw_relationships = parsed.get("relationships") or []
        relationships: list[ExtractedRelationship] = []

        for item in raw_relationships:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "")) if item.get("source") is not None else ""
            target = str(item.get("target", "")) if item.get("target") is not None else ""
            edge_type = str(item.get("type", "")) if item.get("type") is not None else ""
            fact = str(item.get("fact", "")) if item.get("fact") is not None else ""

            # Gracefully handle attributes dict instead of fact string
            # (model sometimes drifts to attributes format on complex messages)
            if not fact and "attributes" in item:
                attrs = item.get("attributes", {})
                if isinstance(attrs, dict) and attrs:
                    # Convert attributes dict to a fact string
                    fact = " ".join(f"{k}: {v}" for k, v in attrs.items() if v)

            if not source or not target or not edge_type or not fact:
                logger.debug("Skipping incomplete relationship: %r", item)
                continue

            norm_source = self._normalize_entity_name(source)
            norm_target = self._normalize_entity_name(target)

            # Look up entity types for constraint checking
            source_type = entity_type_map.get(norm_source.lower())
            target_type = entity_type_map.get(norm_target.lower())

            if not self._validate_relationship(
                source_type, target_type, edge_type, norm_source, norm_target
            ):
                logger.debug(
                    "Rejected relationship: %r -[%s]-> %r (types: %s, %s)",
                    norm_source, edge_type, norm_target, source_type, target_type,
                )
                continue

            relationships.append(ExtractedRelationship(
                source_name=norm_source,
                target_name=norm_target,
                edge_type=edge_type,
                fact_text=fact,
            ))

        return entities, relationships

    def _validate_entity(self, name: str, entity_type: str) -> bool:
        """
        Post-extraction validation. Reject bad extractions per DESIGN.md taxonomy.

        Phase A prevention rules — catches categories 2, 4, 5, 6.
        """
        if not name or not isinstance(name, str):
            return False

        # Category: too short to be meaningful (< 2 chars)
        if len(name.strip()) < 2:
            return False

        # Category 4: sentences-as-entities (> 5 words)
        if len(name.split()) > 5:
            logger.debug("Rejected (too long): %r", name)
            return False

        # Category 5: file paths (starts with /, ~, or .)
        if name.startswith(("/", "~", ".")):
            logger.debug("Rejected (file path): %r", name)
            return False

        # Category 5: embedded path separators
        if "/" in name:
            logger.debug("Rejected (path separator): %r", name)
            return False

        # Exact name rejection (pronouns, generics)
        name_lower = name.lower()
        if name_lower in _JUNK_EXACT_NAMES:
            logger.debug("Rejected (pronoun/generic): %r", name)
            return False

        # Category 6: session descriptions
        if any(junk in name_lower for junk in _JUNK_NAME_WORDS):
            logger.debug("Rejected (junk keyword): %r", name)
            return False

        # Unknown entity type
        if entity_type not in VALID_ENTITY_TYPES:
            logger.debug("Rejected (unknown type %r): %r", entity_type, name)
            return False

        return True

    def _validate_relationship(
        self,
        source_type: str | None,
        target_type: str | None,
        edge_type: str,
        source_name: str,
        target_name: str,
    ) -> bool:
        """
        Check that the edge type is valid for the source→target entity type pair.

        If source or target types are unknown (entity not in our extracted list),
        we allow the relationship through — the resolver stage will handle it.
        Edge type itself must exist in the map somewhere.
        """
        # Collect all valid edge types across the full map
        all_valid_edges = {e for edges in EDGE_TYPE_MAP.values() for e in edges}
        if edge_type not in all_valid_edges:
            logger.debug("Rejected relationship: unknown edge type %r", edge_type)
            return False

        # If we know both types, enforce the constraint
        if source_type and target_type:
            allowed = EDGE_TYPE_MAP.get((source_type, target_type), [])
            # Also check reverse direction for symmetric relationships
            allowed_reverse = EDGE_TYPE_MAP.get((target_type, source_type), [])
            if edge_type not in allowed and edge_type not in allowed_reverse:
                logger.debug(
                    "Rejected relationship: %s not valid for (%s, %s)",
                    edge_type, source_type, target_type,
                )
                return False

        return True

    def _normalize_entity_name(self, name: str) -> str:
        """
        Normalize entity name case.

        - Title case for proper nouns and regular words
        - Preserve all-caps acronyms (PPS, MCP, LLM, etc.)
        - Preserve mixed-case technical names (Neo4j, GraphQL, etc.)

        Examples:
            "coffee" → "Coffee"
            "graphiti" → "Graphiti"
            "PPS" → "PPS"
            "jeff" → "Jeff"
            "dark side tee" → "Dark Side Tee"
        """
        if not name:
            return name

        words = name.strip().split()
        normalized = []
        for word in words:
            # Preserve all-caps acronyms (all uppercase, 2+ chars)
            if word.isupper() and len(word) >= 2:
                normalized.append(word)
            # Preserve already-mixed-case technical words (has both upper and lower)
            elif not word.islower() and not word.isupper():
                normalized.append(word)
            else:
                # Apply title case for lowercase words
                normalized.append(word.capitalize())

        return " ".join(normalized)


# =============================================================================
# Helpers
# =============================================================================


def _format_edge_type_summary() -> str:
    """Build a compact summary of valid entity-pair → edge-type mappings for the prompt."""
    lines = []
    for (src, tgt), edges in EDGE_TYPE_MAP.items():
        lines.append(f"  {src} → {tgt}: {', '.join(edges)}")
    return "\n".join(lines)


def _count_raw_items(parsed: dict) -> int:
    """Count total raw entity + relationship items before validation."""
    return len(parsed.get("entities") or []) + len(parsed.get("relationships") or [])
