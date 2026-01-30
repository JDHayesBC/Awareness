"""
Layer 3: Rich Texture (Graphiti) - Direct Integration

Knowledge graph providing contextual relevance per-turn.
Uses graphiti_core directly for semantic-aware entity extraction.

This version replaces the HTTP API with direct library calls,
enabling custom entity types and extraction instructions.
"""

import os
import json
import asyncio
import sqlite3
import re
from typing import Optional
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import PatternLayer, LayerType, SearchResult, LayerHealth
from .rich_texture_entities import ENTITY_TYPES, EXCLUDED_ENTITY_TYPES
from .rich_texture_edge_types import EDGE_TYPES, EDGE_TYPE_MAP
from .extraction_context import build_extraction_instructions, get_speaker_from_content

# Conditional import - fall back to HTTP if graphiti_core not available
try:
    from graphiti_core import Graphiti
    from graphiti_core.nodes import EpisodeType, EntityNode
    from graphiti_core.edges import EntityEdge
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
    from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
    from graphiti_core.search.search_config_recipes import (
        EDGE_HYBRID_SEARCH_NODE_DISTANCE,
        NODE_HYBRID_SEARCH_RRF,
    )
    GRAPHITI_CORE_AVAILABLE = True
except ImportError:
    GRAPHITI_CORE_AVAILABLE = False
    Graphiti = None
    EpisodeType = None
    EntityNode = None
    EntityEdge = None
    LLMConfig = None
    OpenAIGenericClient = None
    OpenAIEmbedder = None
    OpenAIEmbedderConfig = None
    OpenAIRerankerClient = None
    EDGE_HYBRID_SEARCH_NODE_DISTANCE = None
    NODE_HYBRID_SEARCH_RRF = None

# Also keep aiohttp for fallback HTTP mode
import aiohttp

# Default database path for recent message access
DEFAULT_DB_PATH = os.path.expanduser("~/.claude/data/lyra_conversations.db")


class RichTextureLayerV2(PatternLayer):
    """
    Layer 3: Rich Texture with semantic control.

    Uses graphiti_core directly when available, with custom entity types
    and extraction instructions for domain-aware extraction.

    Falls back to HTTP API if graphiti_core not installed.
    """

    def __init__(
        self,
        neo4j_uri: Optional[str] = None,
        neo4j_user: Optional[str] = None,
        neo4j_password: Optional[str] = None,
        graphiti_url: Optional[str] = None,
        group_id: Optional[str] = None,
    ):
        """
        Initialize the rich texture layer.

        For direct graphiti_core integration:
            neo4j_uri: Neo4j bolt URI (e.g., bolt://localhost:7687)
            neo4j_user: Neo4j username
            neo4j_password: Neo4j password

        For HTTP fallback:
            graphiti_url: URL for Graphiti HTTP server

        Common:
            group_id: Graph partition ID (default: lyra)
        """
        # Neo4j connection for direct mode
        self.neo4j_uri = neo4j_uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self.neo4j_user = neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
        self.neo4j_password = neo4j_password or os.environ.get("NEO4J_PASSWORD", "password123")

        # HTTP fallback
        if graphiti_url:
            self.graphiti_url = graphiti_url
        else:
            host = os.environ.get("GRAPHITI_HOST", "localhost")
            port = os.environ.get("GRAPHITI_PORT", "8203")
            self.graphiti_url = f"http://{host}:{port}"

        self.group_id = group_id or os.environ.get("GRAPHITI_GROUP_ID", "lyra")

        # Local LLM configuration (for using Ollama, LM Studio, etc.)
        # When GRAPHITI_LLM_BASE_URL is set, uses local LLM for entity extraction
        # Can use hybrid mode: local LLM (expensive) + OpenAI embeddings (cheap, compatible)
        self.llm_base_url = os.environ.get("GRAPHITI_LLM_BASE_URL")  # e.g., http://192.168.0.120:1234/v1
        self.llm_model = os.environ.get("GRAPHITI_LLM_MODEL", "qwen/qwen3-32b")
        self.llm_small_model = os.environ.get("GRAPHITI_LLM_SMALL_MODEL")  # defaults to same as main model

        # Embedding configuration - can be local or OpenAI
        # GRAPHITI_EMBEDDING_PROVIDER: "local" (uses LLM_BASE_URL) or "openai" (default, uses OPENAI_API_KEY)
        # OpenAI embeddings recommended for compatibility with existing graph data
        self.embedding_provider = os.environ.get("GRAPHITI_EMBEDDING_PROVIDER", "openai")
        self.embedding_model = os.environ.get("GRAPHITI_EMBEDDING_MODEL", "text-embedding-3-small")
        self.embedding_dim = int(os.environ.get("GRAPHITI_EMBEDDING_DIM", "1536"))  # OpenAI default

        # Clients (lazy initialized)
        self._graphiti_client: Optional[Graphiti] = None
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._use_direct_mode = GRAPHITI_CORE_AVAILABLE

        # Context for extraction (can be updated dynamically)
        self._scene_context: Optional[str] = None
        self._crystal_context: Optional[str] = None

        # Message cache for context-aware retrieval
        self._message_cache: Optional[list[dict]] = None
        self._message_cache_time: Optional[datetime] = None
        self._message_cache_ttl = timedelta(seconds=30)
        self._db_path = os.environ.get("PPS_MESSAGE_DB_PATH", DEFAULT_DB_PATH)
        self._enable_explore = os.environ.get("PPS_ENABLE_EXPLORE", "true").lower() == "true"

    async def _get_graphiti_client(self) -> Optional[Graphiti]:
        """
        Get or create graphiti_core client.

        Supports three modes:
        1. Default (no env vars): Uses OpenAI for both LLM and embeddings
        2. Full local (GRAPHITI_LLM_BASE_URL + GRAPHITI_EMBEDDING_PROVIDER=local):
           Uses local LLM and local embeddings (requires fresh graph)
        3. Hybrid (GRAPHITI_LLM_BASE_URL + GRAPHITI_EMBEDDING_PROVIDER=openai):
           Uses local LLM for extraction + OpenAI embeddings (compatible with existing graph)

        Hybrid mode is recommended for cost savings while maintaining compatibility.
        """
        if not GRAPHITI_CORE_AVAILABLE:
            return None

        if self._graphiti_client is None:
            try:
                llm_client = None
                embedder = None
                cross_encoder = None

                # Configure LLM client (local or OpenAI)
                if self.llm_base_url:
                    print(f"Using local LLM at {self.llm_base_url}")
                    print(f"  Model: {self.llm_model}")

                    small_model = self.llm_small_model or self.llm_model
                    llm_config = LLMConfig(
                        api_key="local",
                        model=self.llm_model,
                        small_model=small_model,
                        base_url=self.llm_base_url,
                    )
                    llm_client = OpenAIGenericClient(config=llm_config)

                # Configure embedder (local or OpenAI)
                if self.embedding_provider == "local" and self.llm_base_url:
                    print(f"  Embedding: {self.embedding_model} (local)")
                    embedder_config = OpenAIEmbedderConfig(
                        api_key="local",
                        embedding_model=self.embedding_model,
                        embedding_dim=self.embedding_dim,
                        base_url=self.llm_base_url,
                    )
                    embedder = OpenAIEmbedder(config=embedder_config)
                elif self.llm_base_url:
                    # Hybrid mode: local LLM + OpenAI embeddings
                    print(f"  Embedding: {self.embedding_model} (OpenAI - hybrid mode)")
                    embedder_config = OpenAIEmbedderConfig(
                        embedding_model=self.embedding_model,
                    )
                    embedder = OpenAIEmbedder(config=embedder_config)

                # Configure cross-encoder (uses LLM client if local, else default)
                if llm_client:
                    cross_encoder = OpenAIRerankerClient(
                        client=llm_client,
                        config=llm_config,
                    )

                # Build Graphiti client with configured components
                if llm_client or embedder:
                    self._graphiti_client = Graphiti(
                        uri=self.neo4j_uri,
                        user=self.neo4j_user,
                        password=self.neo4j_password,
                        llm_client=llm_client,
                        embedder=embedder,
                        cross_encoder=cross_encoder,
                    )
                else:
                    # Full default: OpenAI for everything
                    self._graphiti_client = Graphiti(
                        uri=self.neo4j_uri,
                        user=self.neo4j_user,
                        password=self.neo4j_password,
                    )

                # Build indices on first use
                await self._graphiti_client.build_indices_and_constraints()
            except Exception as e:
                print(f"Failed to initialize graphiti_core: {e}")
                self._use_direct_mode = False
                return None

        return self._graphiti_client

    async def _get_http_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session for HTTP fallback."""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._http_session

    async def close(self):
        """Clean up resources."""
        if self._graphiti_client:
            await self._graphiti_client.close()
            self._graphiti_client = None
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None

    def set_context(
        self,
        scene_context: Optional[str] = None,
        crystal_context: Optional[str] = None,
    ):
        """
        Update extraction context for subsequent store() calls.

        Args:
            scene_context: Current scene description
            crystal_context: Recent crystal content
        """
        self._scene_context = scene_context
        self._crystal_context = crystal_context

    def _fetch_recent_messages(self, limit: int = 8) -> list[dict]:
        """
        Fetch recent messages from the raw_capture database.

        Caches results for 30 seconds to avoid repeated DB hits.
        Falls back to empty list if fetch fails.
        """
        # Check cache
        now = datetime.now()
        if self._message_cache and self._message_cache_time:
            if now - self._message_cache_time < self._message_cache_ttl:
                return self._message_cache

        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT author_name, content, is_lyra FROM messages
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,)
            )

            messages = [
                {
                    "role": "Lyra" if row["is_lyra"] else row["author_name"],
                    "content": row["content"]
                }
                for row in cursor.fetchall()
            ]

            conn.close()

            # Cache results
            self._message_cache = messages
            self._message_cache_time = now

            return messages

        except Exception as e:
            print(f"Failed to fetch recent messages for explore: {e}")
            return []

    def _extract_entities_from_messages(self, messages: list[dict]) -> list[str]:
        """
        Extract entity names from recent messages for explore seeding.

        Adapted from test_context_query.py entity extraction logic.
        Returns list of entity names prioritized by importance.
        """
        entities = set()

        # Always include Lyra
        entities.add("Lyra")

        # Common words to skip
        skip_words = {
            'The', 'This', 'That', 'What', 'When', 'Where', 'How', 'Why',
            'Yes', 'No', 'Oh', 'And', 'But', 'So', 'If', 'For', 'With',
            'Not', 'Most', 'All', 'Some', 'Just', 'Now', 'Then', 'Here',
            'There', 'Would', 'Could', 'Should', 'Will', 'Can', 'May',
            'Like', 'Even', 'Still', 'Also', 'Well', 'Very', 'Much',
            'Every', 'Each', 'Both', 'Such', 'Only', 'Other', 'Any',
            'More', 'Less', 'First', 'Last', 'New', 'Old', 'Good', 'Bad',
        }

        for msg in messages:
            content = msg['content']

            # Find capitalized words (potential names) - must be 3+ chars
            caps = re.findall(r'\b[A-Z][a-z]{2,}\b', content)
            for cap in caps:
                if cap not in skip_words:
                    entities.add(cap)

            # Find issue references like #77, Issue #58
            issues = re.findall(r'#(\d+)', content)
            for issue in issues:
                entities.add(f"#{issue}")
                entities.add(f"Issue #{issue}")

            # Find known entity patterns
            if 'Jeff' in content:
                entities.add('Jeff')
            if 'Carol' in content:
                entities.add('Carol')
            if 'Discord' in content:
                entities.add('Discord')
            if 'Brandi' in content:
                entities.add('Brandi')

        # Prioritize known important entities
        priority = ['Lyra', 'Jeff', 'Carol', 'Brandi', 'Discord']
        result = [e for e in priority if e in entities]
        result += [e for e in entities if e not in priority]

        return result[:5]  # Limit to top 5

    async def _explore_from_entities(
        self,
        client,
        entity_names: list[str],
        explore_depth: int = 2
    ) -> list[dict]:
        """
        Explore the graph from seed entities to find connected facts.

        Simplified BFS traversal adapted from test_context_query.py.
        Returns list of edge facts connected to the seed entities.
        """
        explore_results = []

        for entity_name in entity_names[:3]:  # Limit to 3 entities
            try:
                # Find entity node by name
                query = """
                MATCH (n:Entity {group_id: $group_id})
                WHERE toLower(n.name) CONTAINS toLower($name)
                RETURN n.uuid as uuid, n.name as name
                LIMIT 1
                """
                async with client.driver.session() as session:
                    result = await session.run(
                        query,
                        group_id=self.group_id,
                        name=entity_name
                    )
                    records = await result.data()

                if records:
                    entity_uuid = records[0]['uuid']
                    entity_actual_name = records[0]['name']

                    # Get edges connected to this entity (simple BFS)
                    edge_query = """
                    MATCH (n:Entity {uuid: $uuid})-[r]-(m:Entity)
                    WHERE r.group_id = $group_id
                    RETURN type(r) as rel_type, r.fact as fact,
                           n.name as source, m.name as target,
                           r.uuid as uuid
                    LIMIT $limit
                    """
                    async with client.driver.session() as session:
                        result = await session.run(
                            edge_query,
                            uuid=entity_uuid,
                            group_id=self.group_id,
                            limit=explore_depth * 10
                        )
                        edge_records = await result.data()

                    for rec in edge_records:
                        explore_results.append({
                            "from_entity": entity_actual_name,
                            "rel_type": rec['rel_type'],
                            "fact": rec['fact'],
                            "source": rec['source'],
                            "target": rec['target'],
                            "uuid": rec['uuid']
                        })
            except Exception as e:
                print(f"Explore failed for '{entity_name}': {e}")
                continue

        return explore_results

    @property
    def layer_type(self) -> LayerType:
        return LayerType.RICH_TEXTURE

    async def store(self, content: str, metadata: Optional[dict] = None) -> bool:
        """
        Store content in knowledge graph with semantic-aware extraction.

        Uses graphiti_core directly with custom entity types and
        extraction instructions when available.

        Args:
            content: The text content to store
            metadata: Optional metadata including:
                - channel: Source channel (discord, terminal, etc.)
                - timestamp: When this occurred
                - role: Who said this (user/assistant)
                - speaker: Explicit speaker name
        """
        metadata = metadata or {}
        channel = metadata.get("channel", "unknown")
        role = metadata.get("role", "user")
        speaker = metadata.get("speaker") or get_speaker_from_content(content, channel)

        # Parse timestamp - handle string or datetime
        raw_timestamp = metadata.get("timestamp", datetime.now(timezone.utc))
        if isinstance(raw_timestamp, str):
            try:
                # Try ISO format first (most common)
                timestamp = datetime.fromisoformat(raw_timestamp.replace('Z', '+00:00'))
            except ValueError:
                # Fall back to basic parsing
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = raw_timestamp

        # Try direct graphiti_core mode first
        if self._use_direct_mode:
            client = await self._get_graphiti_client()
            if client:
                return await self._store_direct(
                    content=content,
                    channel=channel,
                    speaker=speaker,
                    timestamp=timestamp,
                )
            # Client init failed - return False, don't silently use HTTP
            return False

        # HTTP API mode (only used when direct mode is not configured)
        return await self._store_http(content, channel, role)

    async def _store_direct(
        self,
        content: str,
        channel: str,
        speaker: str,
        timestamp: datetime,
    ) -> bool:
        """Store using graphiti_core directly with custom entity types."""
        try:
            client = await self._get_graphiti_client()
            if not client:
                return False

            # Build extraction instructions for this specific call
            extraction_instructions = build_extraction_instructions(
                channel=channel,
                scene_context=self._scene_context,
                crystal_context=self._crystal_context,
            )

            # Create episode name from speaker and timestamp
            episode_name = f"{speaker}_{timestamp.strftime('%Y%m%d_%H%M%S')}"

            # Add episode with our entity types, edge types, and instructions
            result = await client.add_episode(
                name=episode_name,
                episode_body=content,
                source_description=f"Conversation from {channel} channel",
                reference_time=timestamp,
                source=EpisodeType.message,
                group_id=self.group_id,
                entity_types=ENTITY_TYPES,
                excluded_entity_types=EXCLUDED_ENTITY_TYPES,
                edge_types=EDGE_TYPES,
                edge_type_map=EDGE_TYPE_MAP,
                custom_extraction_instructions=extraction_instructions,
            )

            return result is not None

        except Exception as e:
            print(f"Direct store failed: {e}")
            return False

    async def _store_http(self, content: str, channel: str, role: str) -> bool:
        """Store using HTTP API (fallback mode)."""
        try:
            session = await self._get_http_session()

            # Get speaker from content for proper attribution
            speaker = get_speaker_from_content(content, channel)

            messages_url = f"{self.graphiti_url}/messages"
            async with session.post(
                messages_url,
                json={
                    "group_id": self.group_id,
                    "messages": [
                        {
                            "role": speaker,  # Use speaker name, not channel!
                            "role_type": role,
                            "content": content,
                        }
                    ],
                },
            ) as resp:
                return resp.status in (200, 201, 202)

        except Exception:
            return False

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Search knowledge graph for relevant facts and entities.

        Uses graphiti_core when available, HTTP API as fallback.
        """
        # Try direct mode first
        if self._use_direct_mode:
            client = await self._get_graphiti_client()
            if client:
                return await self._search_direct(query, limit)

        # Fall back to HTTP
        return await self._search_http(query, limit)

    async def _search_direct(self, query: str, limit: int) -> list[SearchResult]:
        """
        Search using graphiti_core directly with optimized configuration.

        Three-part search strategy:
        1. Edge search (relationship facts) - EDGE_HYBRID_SEARCH_NODE_DISTANCE
        2. Node search (entity summaries) - NODE_HYBRID_SEARCH_RRF
        3. Explore (conversation-specific facts) - BFS from recent entities
        """
        try:
            client = await self._get_graphiti_client()
            if not client:
                return []

            # Configuration (reduced from 200 to 75 - hook truncates at 10K chars anyway)
            EDGE_LIMIT = 75  # Reduced 2026-01-25 - see Issue #121 for compression plans
            NODE_LIMIT = 3   # Entity summaries
            EXPLORE_DEPTH = 2  # BFS depth from extracted entities

            # Lyra's canonical UUID for proximity ranking
            LYRA_UUID = "5bd21fca-52de-41fd-a6b1-c78371d77a36"

            all_results = []

            # 1. Edge search (relationship facts)
            edge_config = EDGE_HYBRID_SEARCH_NODE_DISTANCE.model_copy(deep=True)
            edge_config.limit = EDGE_LIMIT

            edge_results = await client.search_(
                query=query,
                config=edge_config,
                center_node_uuid=LYRA_UUID,
                group_ids=[self.group_id]
            )

            # Filter IS_DUPLICATE_OF edges
            edges = [e for e in edge_results.edges if e.name != "IS_DUPLICATE_OF"]

            # Collect all unique node UUIDs to batch-fetch names
            node_uuids = set()
            for edge in edges:
                node_uuids.add(edge.source_node_uuid)
                node_uuids.add(edge.target_node_uuid)

            # Fetch nodes by UUID to get actual names and labels
            node_names: dict[str, str] = {}
            node_labels: dict[str, list[str]] = {}
            if node_uuids:
                nodes = await EntityNode.get_by_uuids(
                    client.driver,
                    list(node_uuids),
                )
                for node in nodes:
                    node_names[node.uuid] = node.name
                    node_labels[node.uuid] = node.labels

            # Format edges as SearchResult
            for i, edge in enumerate(edges):
                score = 1.0 - (i / max(len(edges), 1)) * 0.3  # Higher base score

                # Get actual node names from lookup
                source_name = node_names.get(edge.source_node_uuid, edge.source_node_uuid)
                target_name = node_names.get(edge.target_node_uuid, edge.target_node_uuid)

                content = f"{source_name} → {edge.name} → {target_name}"
                if edge.fact:
                    content = f"{content}: {edge.fact}"

                all_results.append(SearchResult(
                    content=content,
                    source=str(edge.uuid),
                    layer=LayerType.RICH_TEXTURE,
                    relevance_score=score,
                    metadata={
                        "type": "edge",
                        "predicate": edge.name,
                        "subject": source_name,
                        "object": target_name,
                        "valid_at": str(edge.valid_at) if edge.valid_at else None,
                        "source_labels": node_labels.get(edge.source_node_uuid, []),
                        "target_labels": node_labels.get(edge.target_node_uuid, []),
                    }
                ))

            # 2. Node search (entity summaries)
            node_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
            node_config.limit = NODE_LIMIT

            node_results = await client.search_(
                query=query,
                config=node_config,
                group_ids=[self.group_id]
            )

            for node in node_results.nodes:
                all_results.append(SearchResult(
                    content=f"{node.name}: {node.summary}",
                    source=str(node.uuid),
                    layer=LayerType.RICH_TEXTURE,
                    relevance_score=0.85,  # High relevance for entity context
                    metadata={
                        "type": "entity_summary",
                        "entity": node.name,
                    }
                ))

            # 3. Explore (conversation-specific facts)
            if self._enable_explore and EXPLORE_DEPTH > 0:
                # Fetch recent messages
                recent_messages = self._fetch_recent_messages(limit=8)

                if recent_messages:
                    # Extract entities
                    entity_names = self._extract_entities_from_messages(recent_messages)

                    # Explore from those entities
                    explore_facts = await self._explore_from_entities(
                        client,
                        entity_names,
                        EXPLORE_DEPTH
                    )

                    # Format explore results
                    for i, fact in enumerate(explore_facts):
                        score = 0.8 - (i / max(len(explore_facts), 1)) * 0.2

                        content = f"{fact['source']} → {fact['rel_type']} → {fact['target']}"
                        if fact['fact']:
                            content = f"{content}: {fact['fact']}"

                        all_results.append(SearchResult(
                            content=content,
                            source=str(fact['uuid']),
                            layer=LayerType.RICH_TEXTURE,
                            relevance_score=score,
                            metadata={
                                "type": "explore",
                                "from_entity": fact['from_entity'],
                                "predicate": fact['rel_type'],
                            }
                        ))

            return all_results

        except Exception as e:
            print(f"Direct search with optimized config failed: {e}")
            import traceback
            traceback.print_exc()
            return await self._search_http(query, limit)

    async def _search_http(self, query: str, limit: int) -> list[SearchResult]:
        """Search using HTTP API (fallback mode)."""
        try:
            session = await self._get_http_session()
            results: list[SearchResult] = []

            search_url = f"{self.graphiti_url}/search"
            async with session.post(
                search_url,
                json={
                    "query": query,
                    "group_ids": [self.group_id],
                    "max_facts": limit,
                },
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    facts = data.get("facts", [])

                    # Filter out IS_DUPLICATE_OF edges (Graphiti bug: creates X→X self-references)
                    # See: pps/graph_curation_final_report.md for details
                    facts = [f for f in facts if f.get("name") != "IS_DUPLICATE_OF"]

                    for i, fact in enumerate(facts):
                        score = 1.0 - (i / max(len(facts), 1)) * 0.5
                        content = self._format_fact(fact)

                        fact_text = fact.get("fact", "")
                        predicate = fact.get("name", "RELATES_TO")
                        subject, obj = self._extract_entities_from_fact(fact_text, predicate)

                        results.append(SearchResult(
                            content=content,
                            source=fact.get("uuid", "unknown"),
                            layer=LayerType.RICH_TEXTURE,
                            relevance_score=score,
                            metadata={
                                "type": "fact",
                                "subject": subject,
                                "predicate": predicate,
                                "object": obj,
                                "valid_at": fact.get("valid_at"),
                            },
                        ))

            results.sort(key=lambda r: r.relevance_score, reverse=True)
            return results[:limit]

        except Exception:
            return []

    def _format_fact(self, fact: dict) -> str:
        """Format a fact for display."""
        predicate = fact.get("name", "relates to")
        fact_text = fact.get("fact", "")
        subject, obj = self._extract_entities_from_fact(fact_text, predicate)

        if fact_text:
            return f"{subject} → {predicate} → {obj}: {fact_text}"
        return f"{subject} → {predicate} → {obj}"

    def _extract_entities_from_fact(self, fact_text: str, predicate: str) -> tuple[str, str]:
        """Extract subject and object from a fact string."""
        if not fact_text:
            return ("unknown", "unknown")

        verb_patterns = [
            " owns ", " has ", " is ", " are ", " was ", " were ",
            " loves ", " likes ", " wants ", " needs ", " uses ",
            " created ", " made ", " built ", " wrote ",
            " wears ", " wearing ",
            " debugs ", " debugging ", " develops ", " developing ",
            " subscribed to ", " subscribes to ",
            " cares for ", " built together ", " working on ",
        ]

        fact_lower = fact_text.lower()

        for pattern in verb_patterns:
            if pattern in fact_lower:
                idx = fact_lower.find(pattern)
                subject = fact_text[:idx].strip()
                obj = fact_text[idx + len(pattern):].strip()

                if "," in obj:
                    obj = obj.split(",")[0].strip()
                obj = obj.rstrip(".,;:!?")

                if subject and obj:
                    return (subject, obj)

        parts = fact_text.split(" ", 2)
        if len(parts) >= 3:
            return (parts[0], parts[2].rstrip(".,;:!?"))
        elif len(parts) == 2:
            return (parts[0], parts[1].rstrip(".,;:!?"))

        return (fact_text, "unknown")

    async def health(self) -> LayerHealth:
        """Check if Graphiti is accessible and get stats."""
        # Check direct mode
        if self._use_direct_mode:
            client = await self._get_graphiti_client()
            if client:
                try:
                    # Simple connectivity test
                    return LayerHealth(
                        available=True,
                        message=f"Graphiti direct mode (group: {self.group_id})",
                        details={
                            "mode": "direct",
                            "neo4j_uri": self.neo4j_uri,
                            "group_id": self.group_id,
                            "entity_types": list(ENTITY_TYPES.keys()),
                        },
                    )
                except Exception as e:
                    return LayerHealth(
                        available=False,
                        message=f"Direct mode failed: {e}",
                        details={"error": str(e)},
                    )

        # Check HTTP fallback
        try:
            session = await self._get_http_session()
            status_url = f"{self.graphiti_url}/healthcheck"
            async with session.get(status_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return LayerHealth(
                        available=True,
                        message=f"Graphiti HTTP mode (group: {self.group_id})",
                        details={
                            "mode": "http",
                            "graphiti_url": self.graphiti_url,
                            "group_id": self.group_id,
                            "health_response": data,
                        },
                    )
                else:
                    return LayerHealth(
                        available=False,
                        message=f"HTTP health check returned {resp.status}",
                        details={"status_code": resp.status},
                    )
        except Exception as e:
            return LayerHealth(
                available=False,
                message=f"Cannot connect to Graphiti: {e}",
                details={"error": str(e)},
            )

    async def explore(self, entity_name: str, depth: int = 2) -> list[SearchResult]:
        """Explore the graph from a specific entity."""
        return await self.search(entity_name, limit=depth * 10)

    async def timeline(
        self,
        since: str,
        until: Optional[str] = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Query episodes by time range (HTTP API only for now)."""
        try:
            session = await self._get_http_session()
            episodes_url = f"{self.graphiti_url}/episodes/{self.group_id}"

            async with session.get(episodes_url) as resp:
                if resp.status != 200:
                    return []

                data = await resp.json()
                results = []

                episodes = data if isinstance(data, list) else data.get("episodes", [])
                for episode in episodes[:limit]:
                    content = episode.get("content", episode.get("name", ""))
                    created_at = episode.get("created_at", "")

                    display = f"[{created_at}] {content[:200]}..." if len(str(content)) > 200 else f"[{created_at}] {content}"

                    results.append(SearchResult(
                        content=display,
                        source=episode.get("uuid", "unknown"),
                        layer=LayerType.RICH_TEXTURE,
                        relevance_score=0.7,
                        metadata={
                            "type": "episode",
                            "created_at": created_at,
                        },
                    ))

                return results

        except Exception:
            return []

    async def delete_edge(self, uuid: str) -> dict:
        """Delete a fact (edge) from the knowledge graph by UUID."""
        try:
            session = await self._get_http_session()
            delete_url = f"{self.graphiti_url}/entity-edge/{uuid}"

            async with session.delete(delete_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "success": True,
                        "message": data.get("message", "Edge deleted"),
                        "uuid": uuid,
                    }
                elif resp.status == 404:
                    return {
                        "success": False,
                        "message": f"Edge not found: {uuid}",
                        "uuid": uuid,
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Delete failed with status {resp.status}",
                        "uuid": uuid,
                    }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error: {e}",
                "uuid": uuid,
            }

    async def _find_entity_by_name(
        self,
        client: Graphiti,
        name: str,
        group_id: str
    ) -> Optional[EntityNode]:
        """
        Find an existing entity by name and group_id.

        Args:
            client: Graphiti client instance
            name: Entity name to search for
            group_id: Group ID to filter by

        Returns:
            EntityNode if found, None otherwise
        """
        try:
            # Query Neo4j for existing entity
            cypher = """
            MATCH (e:Entity {name: $name, group_id: $group_id})
            RETURN e.uuid as uuid
            LIMIT 1
            """
            result = await client.driver.execute_query(
                cypher,
                name=name,
                group_id=group_id
            )

            # Extract UUID from result
            # Neo4j driver returns (records, summary, keys) tuple
            if result and len(result) > 0:
                records = result[0] if isinstance(result, tuple) else result
                if records and len(records) > 0:
                    uuid = records[0].get('uuid')
                    if uuid:
                        # Fetch full node by UUID
                        return await EntityNode.get_by_uuid(client.driver, uuid)

            return None
        except Exception as e:
            print(f"Error finding entity {name}: {e}")
            return None

    async def add_triplet_direct(
        self,
        source: str,
        relationship: str,
        target: str,
        fact: Optional[str] = None,
        source_type: Optional[str] = None,
        target_type: Optional[str] = None,
    ) -> dict:
        """
        Add a structured triplet directly to the knowledge graph.

        This bypasses extraction and creates proper entity-to-entity
        relationships with clean, normalized names.

        Args:
            source: Source entity name (e.g., "Jeff")
            relationship: Predicate (e.g., "SPOUSE_OF")
            target: Target entity name (e.g., "Carol")
            fact: Optional human-readable fact (e.g., "Jeff is married to Carol")
            source_type: Optional entity type for source (e.g., "Person")
            target_type: Optional entity type for target (e.g., "Person")

        Returns:
            dict with success status and details
        """
        if not GRAPHITI_CORE_AVAILABLE:
            return {
                "success": False,
                "message": "graphiti_core not available - direct triplet mode requires it",
            }

        try:
            client = await self._get_graphiti_client()
            if not client:
                return {
                    "success": False,
                    "message": "Could not connect to graphiti",
                }

            # Build the fact if not provided
            if not fact:
                fact = f"{source} {relationship.lower().replace('_', ' ')} {target}"

            # Find or create source entity node
            source_node = await self._find_entity_by_name(client, source, self.group_id)
            if source_node:
                # Entity exists, reuse it
                print(f"Reusing existing source entity: {source} (uuid: {source_node.uuid})")
            else:
                # Create new source entity
                source_labels = ["Entity"]
                if source_type:
                    source_labels.append(source_type)
                source_node = EntityNode(
                    name=source,
                    group_id=self.group_id,
                    labels=source_labels,
                    summary=fact if fact else "",
                )
                await source_node.generate_name_embedding(client.embedder)
                await source_node.save(client.driver)
                print(f"Created new source entity: {source} (uuid: {source_node.uuid})")

            # Find or create target entity node
            target_node = await self._find_entity_by_name(client, target, self.group_id)
            if target_node:
                # Entity exists, reuse it
                print(f"Reusing existing target entity: {target} (uuid: {target_node.uuid})")
            else:
                # Create new target entity
                target_labels = ["Entity"]
                if target_type:
                    target_labels.append(target_type)
                target_node = EntityNode(
                    name=target,
                    group_id=self.group_id,
                    labels=target_labels,
                    summary="",
                )
                await target_node.generate_name_embedding(client.embedder)
                await target_node.save(client.driver)
                print(f"Created new target entity: {target} (uuid: {target_node.uuid})")

            # Create edge with actual node UUIDs
            edge = EntityEdge(
                name=relationship,
                fact=fact,
                group_id=self.group_id,
                source_node_uuid=source_node.uuid,
                target_node_uuid=target_node.uuid,
                created_at=datetime.now(timezone.utc),
            )

            # Generate embedding and save edge
            await edge.generate_embedding(client.embedder)
            await edge.save(client.driver)

            return {
                "success": True,
                "message": f"Added: {source} → {relationship} → {target}",
                "triplet": {
                    "source": source,
                    "relationship": relationship,
                    "target": target,
                    "fact": fact,
                },
                "result": {
                    "source_uuid": source_node.uuid,
                    "target_uuid": target_node.uuid,
                    "edge_uuid": edge.uuid,
                },
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Error adding triplet: {e}",
            }
