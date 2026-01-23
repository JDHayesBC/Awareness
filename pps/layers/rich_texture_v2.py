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
from typing import Optional
from datetime import datetime, timezone

from . import PatternLayer, LayerType, SearchResult, LayerHealth
from .rich_texture_entities import ENTITY_TYPES, EXCLUDED_ENTITY_TYPES
from .rich_texture_edge_types import EDGE_TYPES, EDGE_TYPE_MAP
from .extraction_context import build_extraction_instructions, get_speaker_from_content

# Conditional import - fall back to HTTP if graphiti_core not available
try:
    from graphiti_core import Graphiti
    from graphiti_core.nodes import EpisodeType, EntityNode
    from graphiti_core.edges import EntityEdge
    GRAPHITI_CORE_AVAILABLE = True
except ImportError:
    GRAPHITI_CORE_AVAILABLE = False
    Graphiti = None
    EpisodeType = None
    EntityNode = None
    EntityEdge = None

# Also keep aiohttp for fallback HTTP mode
import aiohttp


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

        # Clients (lazy initialized)
        self._graphiti_client: Optional[Graphiti] = None
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._use_direct_mode = GRAPHITI_CORE_AVAILABLE

        # Context for extraction (can be updated dynamically)
        self._scene_context: Optional[str] = None
        self._crystal_context: Optional[str] = None

    async def _get_graphiti_client(self) -> Optional[Graphiti]:
        """Get or create graphiti_core client."""
        if not GRAPHITI_CORE_AVAILABLE:
            return None

        if self._graphiti_client is None:
            try:
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
        timestamp = metadata.get("timestamp", datetime.now(timezone.utc))

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

        # Fall back to HTTP API
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
            # Fall back to HTTP
            return await self._store_http(content, channel, "user")

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
        """Search using graphiti_core directly."""
        try:
            client = await self._get_graphiti_client()
            if not client:
                return []

            edges = await client.search(
                query=query,
                group_ids=[self.group_id],
                num_results=limit,
            )

            # Filter out IS_DUPLICATE_OF edges (Graphiti bug: creates X→X self-references)
            # See: pps/graph_curation_final_report.md for details
            edges = [e for e in edges if e.name != "IS_DUPLICATE_OF"]

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

            results = []
            for i, edge in enumerate(edges):
                score = 1.0 - (i / max(len(edges), 1)) * 0.5

                # Get actual node names from lookup
                source_name = node_names.get(edge.source_node_uuid, edge.source_node_uuid)
                target_name = node_names.get(edge.target_node_uuid, edge.target_node_uuid)

                # Format the edge as readable content
                content = f"{source_name} → {edge.name} → {target_name}"
                if edge.fact:
                    content = f"{content}: {edge.fact}"

                results.append(SearchResult(
                    content=content,
                    source=str(edge.uuid),
                    layer=LayerType.RICH_TEXTURE,
                    relevance_score=score,
                    metadata={
                        "type": "fact",
                        "subject": source_name,
                        "predicate": edge.name,
                        "object": target_name,
                        "valid_at": str(edge.valid_at) if edge.valid_at else None,
                        "source_labels": node_labels.get(edge.source_node_uuid, []),
                        "target_labels": node_labels.get(edge.target_node_uuid, []),
                    },
                ))

            return results

        except Exception as e:
            print(f"Direct search failed: {e}")
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
