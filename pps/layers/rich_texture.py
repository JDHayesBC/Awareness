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
            results: list[SearchResult] = []

            # Graphiti uses POST /search endpoint
            search_url = f"{self.graphiti_url}/search"
            async with session.post(
                search_url,
                json={
                    "query": query,
                    "group_ids": [self.group_id],
                    "max_facts": limit,
                }
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    # Process facts (edges)
                    facts = data.get("facts", [])
                    for i, fact in enumerate(facts):
                        score = 1.0 - (i / max(len(facts), 1)) * 0.5
                        content = self._format_fact(fact)

                        # Extract subject/object from fact text since API doesn't provide them
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
                            }
                        ))

                    # Process entities (nodes)
                    nodes = data.get("nodes", [])
                    for i, node in enumerate(nodes):
                        score = 0.9 - (i / max(len(nodes), 1)) * 0.4
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
                            }
                        ))

            # Sort by relevance and limit
            results.sort(key=lambda r: r.relevance_score, reverse=True)
            return results[:limit]

        except aiohttp.ClientError:
            return []
        except Exception:
            return []

    def _format_fact(self, fact: dict) -> str:
        """Format a fact for display."""
        predicate = fact.get("name", "relates to")
        fact_text = fact.get("fact", "")
        
        # Extract entities from the fact text since Graphiti API doesn't provide separate fields
        subject, obj = self._extract_entities_from_fact(fact_text, predicate)

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

    def _extract_entities_from_fact(self, fact_text: str, predicate: str) -> tuple[str, str]:
        """
        Extract subject and object from a fact string.

        Facts are typically in the form "Subject verb Object" or "Subject is/has Object".
        This is a heuristic approach since the Graphiti API returns facts as text.

        Examples:
            "Jeff owns Bitsy" → ("Jeff", "Bitsy")
            "Jeff is debugging MCP servers" → ("Jeff", "MCP servers")
            "Lyra loves care-gravity" → ("Lyra", "care-gravity")
        """
        if not fact_text:
            return ("unknown", "unknown")
        

        # Common verb patterns to split on
        verb_patterns = [
            " owns ", " has ", " is ", " are ", " was ", " were ",
            " loves ", " likes ", " wants ", " needs ", " uses ",
            " created ", " made ", " built ", " wrote ",
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
                
                # For complex sentences, extract just the direct object
                if "," in obj:
                    obj = obj.split(",")[0].strip()
                if " for " in pattern and "'s " in obj:
                    # Handle "cares for Jeff's well-being" -> extract "Jeff" 
                    obj = obj.split("'s")[0].strip()
                
                # Clean up trailing punctuation
                obj = obj.rstrip(".,;:!?")
                if subject and obj:
                    return (subject, obj)

        # Fallback: split on first space after first word
        parts = fact_text.split(" ", 2)
        if len(parts) >= 3:
            return (parts[0], parts[2].rstrip(".,;:!?"))
        elif len(parts) == 2:
            return (parts[0], parts[1].rstrip(".,;:!?"))

        return (fact_text, "unknown")

    async def store(self, content: str, metadata: Optional[dict] = None) -> bool:
        """
        Store content in knowledge graph as messages.

        Graphiti will automatically extract entities and relationships.

        Args:
            content: The text content to store (conversation, note, etc.)
            metadata: Optional metadata including:
                - channel: Source channel (discord, terminal, etc.)
                - timestamp: When this occurred
                - role: Who said this (user/assistant)
        """
        try:
            session = await self._get_session()
            metadata = metadata or {}

            channel = metadata.get("channel", "unknown")
            role = metadata.get("role", "user")

            # Graphiti uses POST /messages for ingestion (requires role + role_type)
            messages_url = f"{self.graphiti_url}/messages"
            async with session.post(
                messages_url,
                json={
                    "group_id": self.group_id,
                    "messages": [
                        {
                            "role": channel,  # descriptive role name
                            "role_type": role,  # user or assistant
                            "content": content
                        }
                    ]
                }
            ) as resp:
                if resp.status in (200, 201, 202):
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

            # Graphiti uses /healthcheck endpoint
            status_url = f"{self.graphiti_url}/healthcheck"
            async with session.get(status_url) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    return LayerHealth(
                        available=True,
                        message=f"Graphiti active (group: {self.group_id})",
                        details={
                            "graphiti_url": self.graphiti_url,
                            "group_id": self.group_id,
                            "status": "operational",
                            "health_response": data,
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

        Uses search focused on the entity name to find related facts.

        Args:
            entity_name: Name of entity to explore from
            depth: How many relationship hops to traverse (currently uses search)

        Returns:
            List of connected entities and relationships
        """
        # Use search with entity name as query to find related facts
        return await self.search(entity_name, limit=depth * 10)

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

            # Get recent episodes using /episodes/{group_id} endpoint
            episodes_url = f"{self.graphiti_url}/episodes/{self.group_id}"
            async with session.get(episodes_url) as resp:
                if resp.status != 200:
                    return []

                data = await resp.json()
                results: list[SearchResult] = []

                episodes = data if isinstance(data, list) else data.get("episodes", [])
                for episode in episodes[:limit]:
                    content = episode.get("content", episode.get("name", ""))
                    created_at = episode.get("created_at", "")

                    results.append(SearchResult(
                        content=f"[{created_at}] {content[:200]}..." if len(str(content)) > 200 else f"[{created_at}] {content}",
                        source=episode.get("uuid", "unknown"),
                        layer=LayerType.RICH_TEXTURE,
                        relevance_score=0.7,
                        metadata={
                            "type": "episode",
                            "created_at": created_at,
                        }
                    ))

                return results

        except Exception:
            return []

    async def delete_edge(self, uuid: str) -> dict:
        """
        Delete a fact (edge) from the knowledge graph by UUID.

        Args:
            uuid: The UUID of the edge to delete (from search results)

        Returns:
            Dict with success status and message
        """
        try:
            session = await self._get_session()

            delete_url = f"{self.graphiti_url}/entity-edge/{uuid}"
            async with session.delete(delete_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "success": True,
                        "message": data.get("message", "Edge deleted"),
                        "uuid": uuid
                    }
                elif resp.status == 404:
                    return {
                        "success": False,
                        "message": f"Edge not found: {uuid}",
                        "uuid": uuid
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Delete failed with status {resp.status}",
                        "uuid": uuid
                    }

        except aiohttp.ClientError as e:
            return {
                "success": False,
                "message": f"Connection error: {e}",
                "uuid": uuid
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error: {e}",
                "uuid": uuid
            }
