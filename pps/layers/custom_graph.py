"""
Layer 3: Custom Knowledge Graph — Direct Neo4j Implementation

Replaces Graphiti (graphiti_core) with a transparent, locally-controlled pipeline:

    text → EntityExtractor → EntityResolver → GraphEmbedder → Neo4j

Key advantages over Graphiti:
- Free, local embeddings (sentence-transformers, no OpenAI quota)
- Full control over extraction prompts and validation
- Transparent dedup via multi-signal resolution
- No 30s lazy-import overhead, no opaque internals to monkey-patch

Environment variables:
    NEO4J_URI           Neo4j connection URI   (default: bolt://localhost:7687)
    NEO4J_USER          Neo4j username         (default: neo4j)
    NEO4J_PASSWORD      Neo4j password         (required)
    GRAPHITI_GROUP_ID   Entity isolation group (default: derived from ENTITY_NAME/ENTITY_PATH)
    CUSTOM_LLM_BASE_URL Passed through to EntityExtractor
    CUSTOM_LLM_MODEL    Passed through to EntityExtractor
    EMBEDDING_MODEL     Passed through to GraphEmbedder
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from typing import Optional

from pps.layers import LayerHealth, LayerType, PatternLayer, SearchResult
from pps.layers.entity_extractor import EntityExtractor
from pps.layers.entity_resolver import EntityResolver
from pps.layers.graph_embedder import GraphEmbedder

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Defaults
# ─────────────────────────────────────────────

_DEFAULT_NEO4J_URI = "bolt://localhost:7687"
_DEFAULT_NEO4J_USER = "neo4j"


def _default_group_id() -> str:
    """Derive group_id from ENTITY_NAME or ENTITY_PATH, falling back to 'default'."""
    name = os.environ.get("ENTITY_NAME", "")
    if name:
        return name.lower()
    path = os.environ.get("ENTITY_PATH", "")
    if path:
        from pathlib import Path
        return Path(path).name.lower()
    return "default"


# ─────────────────────────────────────────────
# Cypher constants
# ─────────────────────────────────────────────

_MERGE_ENTITY = """
MERGE (e:Entity {name: $name, group_id: $gid})
ON CREATE SET
    e.uuid = $uuid,
    e.entity_type = $entity_type,
    e.summary = $summary,
    e.embedding = $embedding,
    e.created_at = datetime(),
    e.mention_count = 1
ON MATCH SET
    e.summary = CASE WHEN $summary <> '' THEN $summary ELSE e.summary END,
    e.embedding = $embedding,
    e.updated_at = datetime(),
    e.mention_count = coalesce(e.mention_count, 0) + 1
RETURN e.uuid AS uuid
"""

_MERGE_EDGE = """
MATCH (s:Entity {name: $source_name, group_id: $gid})
MATCH (t:Entity {name: $target_name, group_id: $gid})
MERGE (s)-[r:RELATES_TO {fact_hash: $fact_hash}]->(t)
ON CREATE SET
    r.uuid = $uuid,
    r.name = $edge_type,
    r.fact = $fact_text,
    r.embedding = $embedding,
    r.group_id = $gid,
    r.created_at = datetime(),
    r.mention_count = 1
ON MATCH SET
    r.updated_at = datetime(),
    r.mention_count = coalesce(r.mention_count, 0) + 1
"""

_FULLTEXT_ENTITIES = """
CALL db.index.fulltext.queryNodes('entity_name_ft', $query)
YIELD node, score
WHERE node.group_id = $gid
RETURN node.uuid AS uuid, node.name AS name, node.summary AS summary,
       node.entity_type AS entity_type, score AS ft_score
LIMIT $k
"""

_VECTOR_ENTITIES = """
CALL db.index.vector.queryNodes('entity_embedding', $k, $embedding)
YIELD node, score
WHERE node.group_id = $gid
RETURN node.uuid AS uuid, node.name AS name, node.summary AS summary,
       node.entity_type AS entity_type, score AS vec_score
LIMIT $k
"""

_FULLTEXT_EDGES = """
CALL db.index.fulltext.queryRelationships('edge_fact_ft', $query)
YIELD relationship, score
WHERE relationship.group_id = $gid
RETURN relationship.uuid AS uuid, relationship.fact AS fact,
       relationship.name AS edge_type, score AS ft_score
LIMIT $k
"""

_VECTOR_EDGES = """
CALL db.index.vector.queryRelationships('edge_embedding', $k, $embedding)
YIELD relationship, score
WHERE relationship.group_id = $gid
RETURN relationship.uuid AS uuid, relationship.fact AS fact,
       relationship.name AS edge_type, score AS vec_score
LIMIT $k
"""

_HEALTH_QUERY = """
MATCH (e:Entity {group_id: $gid}) RETURN count(e) AS entity_count
"""

_HEALTH_EDGE_QUERY = """
MATCH ()-[r:RELATES_TO {group_id: $gid}]->() RETURN count(r) AS edge_count
"""


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _fact_hash(fact_text: str) -> str:
    """SHA-256 fingerprint of a normalized fact — used as the MERGE key for edges."""
    normalized = " ".join(fact_text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _rrf_score(rank: int, k: int = 60) -> float:
    """Reciprocal rank fusion score for a given rank position."""
    return 1.0 / (k + rank)


def _merge_rrf(
    fulltext: list[dict],
    vector: list[dict],
    id_key: str,
) -> list[dict]:
    """
    Combine fulltext and vector result lists via reciprocal rank fusion.

    Each row must have an ``id_key`` field for deduplication.
    Returns rows sorted by combined RRF score, highest first.
    """
    scores: dict[str, float] = {}
    rows: dict[str, dict] = {}

    for rank, row in enumerate(fulltext):
        uid = row[id_key]
        scores[uid] = scores.get(uid, 0.0) + _rrf_score(rank)
        rows[uid] = row

    for rank, row in enumerate(vector):
        uid = row[id_key]
        scores[uid] = scores.get(uid, 0.0) + _rrf_score(rank)
        if uid not in rows:
            rows[uid] = row

    return sorted(rows.values(), key=lambda r: scores[r[id_key]], reverse=True)


# ─────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────

class CustomGraphLayer(PatternLayer):
    """
    Custom knowledge graph layer replacing Graphiti.

    Implements the PatternLayer interface (search / store / health) backed
    by Neo4j, with local embeddings and an LLM extraction pipeline.

    Sub-components are lazy-initialised on first use so that importing this
    module does not incur the sentence-transformers startup cost (~13 s).
    """

    def __init__(
        self,
        neo4j_uri: str | None = None,
        neo4j_user: str | None = None,
        neo4j_password: str | None = None,
        group_id: str | None = None,
    ) -> None:
        self._uri = neo4j_uri or os.environ.get("NEO4J_URI", _DEFAULT_NEO4J_URI)
        self._user = neo4j_user or os.environ.get("NEO4J_USER", _DEFAULT_NEO4J_USER)
        self._password = neo4j_password or os.environ.get("NEO4J_PASSWORD", "")
        self._group_id = (
            group_id
            or os.environ.get("GRAPHITI_GROUP_ID")
            or _default_group_id()
        )

        # Lazy-initialised components — None until first use
        self._driver = None
        self._extractor: EntityExtractor | None = None
        self._embedder: GraphEmbedder | None = None
        self._resolver: EntityResolver | None = None

        self._indexes_ensured = False

    # ─────────────────────────────────────────
    # PatternLayer interface
    # ─────────────────────────────────────────

    @property
    def layer_type(self) -> LayerType:
        return LayerType.RICH_TEXTURE

    async def store(self, content: str, metadata: Optional[dict] = None) -> bool:
        """
        Ingest a text passage into the knowledge graph.

        Pipeline:
            1. Extract entities + relationships from text via LLM
            2. Resolve each entity to its canonical name (dedup/merge)
            3. Embed entities and edges with local sentence-transformers
            4. Write nodes and edges to Neo4j via MERGE

        Args:
            content:  Raw text (a conversation turn, message body, etc.)
            metadata: Optional context with keys:
                        channel   — source channel (terminal, discord, reflection)
                        speaker   — who said the text (auto-detected if absent)
                        timestamp — ISO timestamp string
                        entity_name — override for primary entity resolution hint

        Returns:
            True if at least some graph data was written, False on failure.
        """
        metadata = metadata or {}
        channel = metadata.get("channel", "terminal")
        speaker = metadata.get("speaker")
        entity_name = metadata.get("entity_name")

        try:
            driver = self._get_driver()
            await self._ensure_indexes()
        except Exception as exc:
            logger.error("CustomGraphLayer.store: Neo4j connection failed: %s", exc)
            return False

        # 1. Extract entities and relationships
        try:
            extractor = self._get_extractor()
            result = await extractor.extract(
                text=content,
                channel=channel,
                speaker=speaker,
                entity_name=entity_name,
            )
        except Exception as exc:
            logger.error("CustomGraphLayer.store: extraction failed: %s", exc)
            return False

        if not result.entities and not result.relationships:
            logger.debug("CustomGraphLayer.store: nothing extracted from text")
            return True  # Not an error — some text genuinely has no graph-worthy content

        # 2. Resolve entities + 3. Embed + 4. Write nodes
        embedder = self._get_embedder()
        resolver = self._get_resolver()

        # Track which canonical names were successfully written
        written_names: set[str] = set()

        for entity in result.entities:
            try:
                resolved = await resolver.resolve(
                    name=entity.name,
                    entity_type=entity.entity_type,
                    attributes=entity.attributes,
                )
                embedding = embedder.embed_entity(resolved.canonical_name, summary="")
                node_uuid = resolved.existing_uuid or str(uuid.uuid4())

                driver.execute_query(
                    _MERGE_ENTITY,
                    name=resolved.canonical_name,
                    gid=self._group_id,
                    uuid=node_uuid,
                    entity_type=resolved.entity_type,
                    summary="",
                    embedding=embedding,
                )
                written_names.add(resolved.canonical_name)
                logger.debug(
                    "Stored entity: '%s' (%s) [%s]",
                    resolved.canonical_name,
                    resolved.entity_type,
                    resolved.match_signal,
                )
            except Exception as exc:
                logger.warning(
                    "CustomGraphLayer.store: failed to write entity '%s': %s",
                    entity.name,
                    exc,
                )

        # 4. Write edges (only when both endpoints exist in the graph)
        for rel in result.relationships:
            try:
                # Resolve source and target to canonical names so we can look them up
                resolved_src = await resolver.resolve(
                    name=rel.source_name, entity_type="Person"
                )
                resolved_tgt = await resolver.resolve(
                    name=rel.target_name, entity_type="Person"
                )
                src_name = resolved_src.canonical_name
                tgt_name = resolved_tgt.canonical_name

                embedding = embedder.embed_edge(rel.fact_text)
                fhash = _fact_hash(rel.fact_text)

                driver.execute_query(
                    _MERGE_EDGE,
                    source_name=src_name,
                    target_name=tgt_name,
                    fact_hash=fhash,
                    gid=self._group_id,
                    uuid=str(uuid.uuid4()),
                    edge_type=rel.edge_type,
                    fact_text=rel.fact_text,
                    embedding=embedding,
                )
                logger.debug(
                    "Stored edge: '%s' -[%s]-> '%s'",
                    src_name,
                    rel.edge_type,
                    tgt_name,
                )
            except Exception as exc:
                # Missing source/target node is the most common failure here.
                # Log at debug — it's expected when extraction produces a
                # relationship whose entities were filtered out during validation.
                logger.debug(
                    "CustomGraphLayer.store: skipped edge '%s'->'%s': %s",
                    rel.source_name,
                    rel.target_name,
                    exc,
                )

        return bool(written_names)

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Hybrid search over entities and edges.

        Runs four queries in parallel (fulltext + vector for both nodes and edges),
        then combines results using reciprocal rank fusion.

        Args:
            query: Search string (keywords or natural language).
            limit: Maximum total results to return.

        Returns:
            List of SearchResult sorted by combined relevance, highest first.
        """
        try:
            driver = self._get_driver()
            await self._ensure_indexes()
        except Exception as exc:
            logger.error("CustomGraphLayer.search: Neo4j unavailable: %s", exc)
            return []

        embedder = self._get_embedder()
        try:
            query_embedding = embedder.embed_text(query)
        except Exception as exc:
            logger.warning("CustomGraphLayer.search: embedding failed: %s", exc)
            query_embedding = None

        k = max(limit, 10)  # Fetch more candidates before fusion narrows them down

        # --- Entity fulltext ---
        entity_ft: list[dict] = []
        try:
            records, _, _ = driver.execute_query(
                _FULLTEXT_ENTITIES,
                query=query,
                gid=self._group_id,
                k=k,
            )
            entity_ft = [dict(r) for r in records]
        except Exception as exc:
            logger.debug("entity fulltext search failed: %s", exc)

        # --- Entity vector ---
        entity_vec: list[dict] = []
        if query_embedding:
            try:
                records, _, _ = driver.execute_query(
                    _VECTOR_ENTITIES,
                    embedding=query_embedding,
                    gid=self._group_id,
                    k=k,
                )
                entity_vec = [dict(r) for r in records]
            except Exception as exc:
                logger.debug("entity vector search failed: %s", exc)

        # --- Edge fulltext ---
        edge_ft: list[dict] = []
        try:
            records, _, _ = driver.execute_query(
                _FULLTEXT_EDGES,
                query=query,
                gid=self._group_id,
                k=k,
            )
            edge_ft = [dict(r) for r in records]
        except Exception as exc:
            logger.debug("edge fulltext search failed: %s", exc)

        # --- Edge vector ---
        edge_vec: list[dict] = []
        if query_embedding:
            try:
                records, _, _ = driver.execute_query(
                    _VECTOR_EDGES,
                    embedding=query_embedding,
                    gid=self._group_id,
                    k=k,
                )
                edge_vec = [dict(r) for r in records]
            except Exception as exc:
                logger.debug("edge vector search failed: %s", exc)

        # Merge entity results via RRF
        merged_entities = _merge_rrf(entity_ft, entity_vec, id_key="uuid")
        # Merge edge results via RRF
        merged_edges = _merge_rrf(edge_ft, edge_vec, id_key="uuid")

        # Build SearchResult objects
        results: list[SearchResult] = []

        for i, row in enumerate(merged_entities):
            name = row.get("name", "")
            summary = row.get("summary") or ""
            entity_type = row.get("entity_type", "")
            content = f"{name} ({entity_type}): {summary}" if summary else f"{name} ({entity_type})"
            # Normalise score: first result gets 1.0, later ones scale down
            score = 1.0 / (1 + i)
            results.append(SearchResult(
                content=content,
                source=f"neo4j:entity:{row.get('uuid', '')}",
                layer=LayerType.RICH_TEXTURE,
                relevance_score=score,
                metadata={"type": "entity", "entity_type": entity_type, "name": name},
            ))

        for i, row in enumerate(merged_edges):
            fact = row.get("fact", "")
            edge_type = row.get("edge_type", "")
            content = f"[{edge_type}] {fact}" if edge_type else fact
            score = 0.9 / (1 + i)  # Edges ranked slightly below entities by default
            results.append(SearchResult(
                content=content,
                source=f"neo4j:edge:{row.get('uuid', '')}",
                layer=LayerType.RICH_TEXTURE,
                relevance_score=score,
                metadata={"type": "edge", "edge_type": edge_type},
            ))

        # Sort all results together by relevance and trim to requested limit
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results[:limit]

    async def health(self) -> LayerHealth:
        """
        Check Neo4j connectivity and return entity/edge counts.

        Returns:
            LayerHealth with available=True if Neo4j is reachable.
        """
        try:
            driver = self._get_driver()
        except Exception as exc:
            return LayerHealth(
                available=False,
                message=f"Neo4j connection failed: {exc}",
            )

        try:
            records, _, _ = driver.execute_query(
                _HEALTH_QUERY,
                gid=self._group_id,
            )
            entity_count = records[0]["entity_count"] if records else 0

            records, _, _ = driver.execute_query(
                _HEALTH_EDGE_QUERY,
                gid=self._group_id,
            )
            edge_count = records[0]["edge_count"] if records else 0

            return LayerHealth(
                available=True,
                message=f"Neo4j healthy: {entity_count} entities, {edge_count} edges (group={self._group_id})",
                details={
                    "entity_count": entity_count,
                    "edge_count": edge_count,
                    "group_id": self._group_id,
                    "neo4j_uri": self._uri,
                },
            )
        except Exception as exc:
            return LayerHealth(
                available=False,
                message=f"Neo4j query failed: {exc}",
                details={"neo4j_uri": self._uri},
            )

    # ─────────────────────────────────────────
    # Lazy initialisation helpers
    # ─────────────────────────────────────────

    def _get_driver(self):
        """Return the Neo4j driver, connecting on first call."""
        if self._driver is not None:
            return self._driver

        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise ImportError(
                "neo4j Python driver is required. Install with: pip install neo4j"
            ) from exc

        if not self._password:
            raise RuntimeError(
                "NEO4J_PASSWORD environment variable is required but not set."
            )

        self._driver = GraphDatabase.driver(
            self._uri,
            auth=(self._user, self._password),
        )
        logger.info("Connected to Neo4j at %s (group_id=%s)", self._uri, self._group_id)
        return self._driver

    def _get_extractor(self) -> EntityExtractor:
        if self._extractor is None:
            self._extractor = EntityExtractor()
        return self._extractor

    def _get_embedder(self) -> GraphEmbedder:
        if self._embedder is None:
            self._embedder = GraphEmbedder()
        return self._embedder

    def _get_resolver(self) -> EntityResolver:
        if self._resolver is None:
            self._resolver = EntityResolver(
                neo4j_driver=self._driver,
                embedder=self._get_embedder(),
                group_id=self._group_id,
            )
        return self._resolver

    # ─────────────────────────────────────────
    # Schema / index management
    # ─────────────────────────────────────────

    async def _ensure_indexes(self) -> None:
        """
        Create Neo4j full-text and vector indexes if they don't already exist.

        Called once on first use (guarded by self._indexes_ensured). Safe to
        call repeatedly — all statements use IF NOT EXISTS.
        """
        if self._indexes_ensured:
            return

        driver = self._get_driver()
        embedder = self._get_embedder()
        dims = embedder.dimensions

        index_statements = [
            # Full-text indexes
            "CREATE FULLTEXT INDEX entity_name_ft IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.summary]",
            "CREATE FULLTEXT INDEX edge_fact_ft IF NOT EXISTS FOR ()-[r:RELATES_TO]-() ON EACH [r.fact]",
            # Vector indexes (Neo4j 5.11+)
            (
                f"CREATE VECTOR INDEX entity_embedding IF NOT EXISTS "
                f"FOR (e:Entity) ON (e.embedding) "
                f"OPTIONS {{indexConfig: {{`vector.dimensions`: {dims}, "
                f"`vector.similarity_function`: 'cosine'}}}}"
            ),
            (
                f"CREATE VECTOR INDEX edge_embedding IF NOT EXISTS "
                f"FOR ()-[r:RELATES_TO]-() ON (r.embedding) "
                f"OPTIONS {{indexConfig: {{`vector.dimensions`: {dims}, "
                f"`vector.similarity_function`: 'cosine'}}}}"
            ),
        ]

        for stmt in index_statements:
            try:
                driver.execute_query(stmt)
            except Exception as exc:
                # Index may already exist with a different definition — log and
                # continue. A mismatch in dimensions would only affect quality,
                # not correctness of writes.
                logger.debug("Index statement skipped (%s): %s", exc, stmt[:80])

        self._indexes_ensured = True
        logger.info(
            "Neo4j indexes verified (dims=%d, group_id=%s)", dims, self._group_id
        )

    # ─────────────────────────────────────────
    # Teardown
    # ─────────────────────────────────────────

    def close(self) -> None:
        """Close the Neo4j driver connection. Call on shutdown."""
        if self._driver is not None:
            try:
                self._driver.close()
            except Exception as exc:
                logger.warning("Error closing Neo4j driver: %s", exc)
            self._driver = None
