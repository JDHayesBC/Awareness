"""
Layer 3: Rich Texture (Graphiti)

Knowledge graph providing contextual relevance per-turn.
10-50 facts returned, temporarily appended to prompt.
The flesh, not bone - ephemeral unless folded into response.
"""

import os
import asyncio
from typing import Optional
from datetime import datetime

import aiohttp

from . import PatternLayer, LayerType, SearchResult, LayerHealth


class RichTextureLayer(PatternLayer):
    """
    Layer 3: Rich Texture

    Graphiti knowledge graph for contextual, per-turn texture.
    Everything tossed in, semantically searchable.

    Provides:
    - Entity extraction from conversations
    - Relationship tracking between entities
    - Temporal reasoning (when things happened)
    - Graph-based queries
    """

    def __init__(self, graphiti_url: Optional[str] = None):
        """
        Initialize the rich texture layer.

        Args:
            graphiti_url: URL for Graphiti server.
                         Defaults to GRAPHITI_HOST:GRAPHITI_PORT env vars,
                         or localhost:8203 for local development.
        """
        if graphiti_url:
            self.graphiti_url = graphiti_url
        else:
            host = os.environ.get("GRAPHITI_HOST", "localhost")
            port = os.environ.get("GRAPHITI_PORT", "8203")
            self.graphiti_url = f"http://{host}:{port}"

        self.group_id = os.environ.get("GRAPHITI_GROUP_ID", "lyra")
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def _close_session(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    @property
    def layer_type(self) -> LayerType:
        return LayerType.RICH_TEXTURE

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Search knowledge graph for relevant facts and entities.

        Uses Graphiti's hybrid search (semantic + graph traversal).
        Returns entities and facts ranked by relevance.
        """
        try:
            session = await self._get_session()

            # Search for both facts and nodes
            results: list[SearchResult] = []

            # Search facts (relationships between entities)
            facts_url = f"{self.graphiti_url}/api/v1/search/facts"
            async with session.post(
                facts_url,
                json={
                    "query": query,
                    "group_id": self.group_id,
                    "num_results": limit,
                }
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for i, fact in enumerate(data.get("facts", [])):
                        # Calculate relevance score (1.0 to 0.0 based on position)
                        score = 1.0 - (i / max(len(data.get("facts", [])), 1)) * 0.5

                        # Format fact as readable content
                        content = self._format_fact(fact)

                        results.append(SearchResult(
                            content=content,
                            source=fact.get("uuid", "unknown"),
                            layer=LayerType.RICH_TEXTURE,
                            relevance_score=score,
                            metadata={
                                "type": "fact",
                                "subject": fact.get("source_node_name"),
                                "predicate": fact.get("name"),
                                "object": fact.get("target_node_name"),
                                "valid_at": fact.get("valid_at"),
                                "episode_id": fact.get("episode_uuid"),
                            }
                        ))

            # Search nodes (entities)
            nodes_url = f"{self.graphiti_url}/api/v1/search/nodes"
            async with session.post(
                nodes_url,
                json={
                    "query": query,
                    "group_id": self.group_id,
                    "num_results": limit,
                }
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for i, node in enumerate(data.get("nodes", [])):
                        # Score slightly lower than facts (facts are more specific)
                        score = 0.9 - (i / max(len(data.get("nodes", [])), 1)) * 0.4

                        content = self._format_node(node)

                        results.append(SearchResult(
                            content=content,
                            source=node.get("uuid", "unknown"),
                            layer=LayerType.RICH_TEXTURE,
                            relevance_score=score,
                            metadata={
                                "type": "entity",
                                "name": node.get("name"),
                                "labels": node.get("labels", []),
                                "created_at": node.get("created_at"),
                            }
                        ))

            # Sort by relevance and limit
            results.sort(key=lambda r: r.relevance_score, reverse=True)
            return results[:limit]

        except aiohttp.ClientError as e:
            # Connection error - Graphiti unavailable, return empty
            return []
        except Exception as e:
            # Other errors - log and return empty
            return []

    def _format_fact(self, fact: dict) -> str:
        """Format a fact for display."""
        subject = fact.get("source_node_name", "?")
        predicate = fact.get("name", "relates to")
        obj = fact.get("target_node_name", "?")
        fact_text = fact.get("fact", "")

        if fact_text:
            return f"{subject} → {predicate} → {obj}: {fact_text}"
        return f"{subject} → {predicate} → {obj}"

    def _format_node(self, node: dict) -> str:
        """Format an entity node for display."""
        name = node.get("name", "Unknown")
        labels = node.get("labels", [])
        summary = node.get("summary", "")

        label_str = ", ".join(labels) if labels else "Entity"

        if summary:
            return f"[{label_str}] {name}: {summary}"
        return f"[{label_str}] {name}"

    async def store(self, content: str, metadata: Optional[dict] = None) -> bool:
        """
        Store content in knowledge graph as an episode.

        Graphiti will automatically extract entities and relationships.

        Args:
            content: The text content to store (conversation, note, etc.)
            metadata: Optional metadata including:
                - channel: Source channel (discord, terminal, etc.)
                - timestamp: When this occurred
                - participants: Who was involved
        """
        try:
            session = await self._get_session()
            metadata = metadata or {}

            # Build episode name from metadata
            channel = metadata.get("channel", "unknown")
            timestamp = metadata.get("timestamp", datetime.now().isoformat())
            name = f"{channel}:{timestamp}"

            # Determine episode type based on content structure
            episode_type = "text"
            if ":" in content and "\n" in content:
                # Looks like conversation format (role: message)
                episode_type = "message"

            episode_url = f"{self.graphiti_url}/api/v1/episodes"
            async with session.post(
                episode_url,
                json={
                    "name": name,
                    "episode_body": content,
                    "group_id": self.group_id,
                    "source_description": channel,
                    "episode_type": episode_type,
                }
            ) as resp:
                if resp.status in (200, 201):
                    return True
                else:
                    return False

        except aiohttp.ClientError:
            return False
        except Exception:
            return False

    async def health(self) -> LayerHealth:
        """Check if Graphiti is accessible and get stats."""
        try:
            session = await self._get_session()

            status_url = f"{self.graphiti_url}/api/v1/status"
            async with session.get(status_url) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    # Try to get entity/relationship counts
                    entity_count = data.get("entity_count", "unknown")
                    relationship_count = data.get("relationship_count", "unknown")

                    return LayerHealth(
                        available=True,
                        message=f"Graphiti active ({entity_count} entities, {relationship_count} relationships)",
                        details={
                            "graphiti_url": self.graphiti_url,
                            "group_id": self.group_id,
                            "entity_count": entity_count,
                            "relationship_count": relationship_count,
                            "status": "operational",
                        }
                    )
                else:
                    return LayerHealth(
                        available=False,
                        message=f"Graphiti returned status {resp.status}",
                        details={
                            "graphiti_url": self.graphiti_url,
                            "status_code": resp.status,
                        }
                    )

        except aiohttp.ClientError as e:
            return LayerHealth(
                available=False,
                message=f"Cannot connect to Graphiti: {e}",
                details={
                    "graphiti_url": self.graphiti_url,
                    "error": str(e),
                }
            )
        except Exception as e:
            return LayerHealth(
                available=False,
                message=f"Graphiti health check failed: {e}",
                details={
                    "graphiti_url": self.graphiti_url,
                    "error": str(e),
                }
            )

    async def explore(self, entity_name: str, depth: int = 2) -> list[SearchResult]:
        """
        Explore the graph from a specific entity.

        Finds connected entities and relationships up to `depth` hops away.

        Args:
            entity_name: Name of entity to explore from
            depth: How many relationship hops to traverse

        Returns:
            List of connected entities and relationships
        """
        try:
            session = await self._get_session()

            # First, find the entity
            nodes_url = f"{self.graphiti_url}/api/v1/search/nodes"
            async with session.post(
                nodes_url,
                json={
                    "query": entity_name,
                    "group_id": self.group_id,
                    "num_results": 1,
                }
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                nodes = data.get("nodes", [])
                if not nodes:
                    return []

                center_node = nodes[0]
                center_uuid = center_node.get("uuid")

            # Get edges connected to this entity
            # Note: This is a simplified approach; full graph traversal
            # would require multiple queries or a dedicated endpoint
            edges_url = f"{self.graphiti_url}/api/v1/nodes/{center_uuid}/edges"
            results: list[SearchResult] = []

            async with session.get(edges_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for edge in data.get("edges", []):
                        content = self._format_fact(edge)
                        results.append(SearchResult(
                            content=content,
                            source=edge.get("uuid", "unknown"),
                            layer=LayerType.RICH_TEXTURE,
                            relevance_score=0.8,
                            metadata={
                                "type": "relationship",
                                "from_entity": entity_name,
                                "relationship": edge.get("name"),
                                "to_entity": edge.get("target_node_name"),
                            }
                        ))

            return results

        except Exception:
            return []

    async def timeline(
        self,
        since: str,
        until: Optional[str] = None,
        limit: int = 20
    ) -> list[SearchResult]:
        """
        Query episodes by time range.

        Args:
            since: Start time (ISO format or relative like "24h", "7d")
            until: End time (optional, defaults to now)
            limit: Maximum results

        Returns:
            Episodes/facts from the time range
        """
        try:
            session = await self._get_session()

            # Get recent episodes
            episodes_url = f"{self.graphiti_url}/api/v1/episodes"
            async with session.get(
                episodes_url,
                params={
                    "group_id": self.group_id,
                    "limit": limit,
                }
            ) as resp:
                if resp.status != 200:
                    return []

                data = await resp.json()
                results: list[SearchResult] = []

                for episode in data.get("episodes", []):
                    # Parse and filter by time if needed
                    # For now, return all recent episodes
                    content = episode.get("content", episode.get("name", ""))
                    created_at = episode.get("created_at", "")

                    results.append(SearchResult(
                        content=f"[{created_at}] {content[:200]}...",
                        source=episode.get("uuid", "unknown"),
                        layer=LayerType.RICH_TEXTURE,
                        relevance_score=0.7,
                        metadata={
                            "type": "episode",
                            "created_at": created_at,
                            "channel": episode.get("source_description"),
                        }
                    ))

                return results

        except Exception:
            return []
