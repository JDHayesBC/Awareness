#!/usr/bin/env python3
"""
PPS HTTP Client - Direct HTTP access to Pattern Persistence System

This client bypasses the MCP layer and calls PPS HTTP endpoints directly.
Used in contexts where MCP tools aren't available (like reflection subprocess).

Issue: #97 - MCP servers don't load in subprocess despite --mcp-config
Solution: Direct HTTP calls to PPS server running on localhost:8201
"""

import aiohttp
import asyncio
from typing import Any


class PPSHttpClient:
    """Client for PPS HTTP API - bypasses MCP layer."""

    def __init__(self, base_url: str = "http://localhost:8201"):
        """
        Initialize PPS HTTP client.

        Args:
            base_url: Base URL of PPS HTTP server (default: localhost:8201)
        """
        self.base_url = base_url.rstrip('/')
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()

    async def _post(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        """
        Make a POST request to PPS server.

        Args:
            endpoint: API endpoint (e.g., "/tools/ambient_recall")
            data: Request payload

        Returns:
            Response JSON as dict

        Raises:
            RuntimeError: If request fails
        """
        if not self.session:
            raise RuntimeError("Client not initialized - use 'async with' context manager")

        url = f"{self.base_url}{endpoint}"
        async with self.session.post(url, json=data) as response:
            if response.status != 200:
                error_text = await response.text()
                raise RuntimeError(
                    f"PPS HTTP request failed ({response.status}): {error_text}"
                )
            return await response.json()

    async def _get(self, endpoint: str) -> dict[str, Any]:
        """
        Make a GET request to PPS server.

        Args:
            endpoint: API endpoint (e.g., "/health")

        Returns:
            Response JSON as dict

        Raises:
            RuntimeError: If request fails
        """
        if not self.session:
            raise RuntimeError("Client not initialized - use 'async with' context manager")

        url = f"{self.base_url}{endpoint}"
        async with self.session.get(url) as response:
            if response.status != 200:
                error_text = await response.text()
                raise RuntimeError(
                    f"PPS HTTP request failed ({response.status}): {error_text}"
                )
            return await response.json()

    async def _delete(self, endpoint: str) -> dict[str, Any]:
        """
        Make a DELETE request to PPS server.

        Args:
            endpoint: API endpoint (e.g., "/tools/texture_delete/uuid")

        Returns:
            Response JSON as dict

        Raises:
            RuntimeError: If request fails
        """
        if not self.session:
            raise RuntimeError("Client not initialized - use 'async with' context manager")

        url = f"{self.base_url}{endpoint}"
        async with self.session.delete(url) as response:
            if response.status != 200:
                error_text = await response.text()
                raise RuntimeError(
                    f"PPS HTTP request failed ({response.status}): {error_text}"
                )
            return await response.json()

    async def ambient_recall(
        self,
        context: str,
        limit_per_layer: int = 5
    ) -> dict[str, Any]:
        """
        Retrieve relevant context from all pattern persistence layers.

        This is the primary memory interface - use it at the start of each
        conversation turn to surface emotionally resonant memories, relevant
        word-photos, and temporal context.

        Args:
            context: Current conversational context or query.
                    Can be the user's message, conversation summary,
                    or 'startup' for initial identity reconstruction.
            limit_per_layer: Maximum results per layer (default: 5)

        Returns:
            Dict containing:
                - formatted_output: Human-readable memory recall
                - clock: Current time info
                - memory_health: Unsummarized/uningested counts
                - layers: Dict of layer results
                - unsummarized_count: Int
                - uningested_count: Int
        """
        return await self._post("/tools/ambient_recall", {
            "context": context,
            "limit_per_layer": limit_per_layer
        })

    async def anchor_search(self, query: str, limit: int = 10) -> dict[str, Any]:
        """
        Search word-photos (Layer 2: Core Anchors) for specific memories.

        Args:
            query: What to search for in word-photos
            limit: Maximum results (default: 10)

        Returns:
            Dict containing search results
        """
        return await self._post("/tools/anchor_search", {
            "query": query,
            "limit": limit
        })

    async def raw_search(self, query: str, limit: int = 20) -> dict[str, Any]:
        """
        Search raw captured content (Layer 1: Raw Capture).

        Args:
            query: Search query
            limit: Maximum results (default: 20)

        Returns:
            Dict containing search results
        """
        return await self._post("/tools/raw_search", {
            "query": query,
            "limit": limit
        })

    async def add_triplet(
        self,
        source: str,
        relationship: str,
        target: str,
        fact: str | None = None,
        source_type: str | None = None,
        target_type: str | None = None
    ) -> dict[str, Any]:
        """
        Add a structured triplet directly to the knowledge graph.

        Args:
            source: Source entity name
            relationship: Relationship type
            target: Target entity name
            fact: Optional fact text
            source_type: Optional entity type (Person, Place, Symbol, etc.)
            target_type: Optional entity type

        Returns:
            Dict containing success status
        """
        data = {
            "source": source,
            "relationship": relationship,
            "target": target
        }
        if fact:
            data["fact"] = fact
        if source_type:
            data["source_type"] = source_type
        if target_type:
            data["target_type"] = target_type

        return await self._post("/tools/add_triplet", data)

    async def texture_search(self, query: str, limit: int = 10) -> dict[str, Any]:
        """
        Search the knowledge graph (Layer 3: Rich Texture) for entities and facts.

        Returns entities and facts ranked by relevance with UUIDs for deletion.

        Args:
            query: What to search for in the knowledge graph
            limit: Maximum results (default: 10)

        Returns:
            Dict containing:
                - results: List of search results with content, source (UUID),
                  relevance_score, and metadata
        """
        return await self._post("/tools/texture_search", {
            "query": query,
            "limit": limit
        })

    async def texture_delete(self, uuid: str) -> dict[str, Any]:
        """
        Delete a fact (edge) from the knowledge graph by UUID.

        Use UUIDs from texture_search results (source field) to remove
        outdated or incorrect facts from the graph.

        Args:
            uuid: UUID of the fact to delete (from texture_search source field)

        Returns:
            Dict containing success status
        """
        return await self._delete(f"/tools/texture_delete/{uuid}")

    async def texture_explore(
        self,
        entity_name: str,
        depth: int = 2
    ) -> dict[str, Any]:
        """
        Explore the knowledge graph from a specific entity.

        Returns relationships and connected entities expanding outward
        from the specified entity.

        Args:
            entity_name: Name of the entity to explore from
            depth: How many hops to traverse (default: 2)

        Returns:
            Dict containing:
                - results: List of connected entities and relationships with
                  content, source, relevance_score, and metadata
        """
        return await self._post("/tools/texture_explore", {
            "entity_name": entity_name,
            "depth": depth
        })

    async def texture_timeline(
        self,
        since: str,
        until: str | None = None,
        limit: int = 20
    ) -> dict[str, Any]:
        """
        Query the knowledge graph by time range.

        Returns episodes and facts from the specified period, useful
        for temporal exploration of memories.

        Args:
            since: Start time (ISO format or relative like "2024-01-01")
            until: End time (optional, defaults to now)
            limit: Maximum results (default: 20)

        Returns:
            Dict containing:
                - results: List of temporal results with content, source,
                  relevance_score, and metadata
        """
        data = {"since": since, "limit": limit}
        if until:
            data["until"] = until
        return await self._post("/tools/texture_timeline", data)

    async def pps_health(self) -> dict[str, Any]:
        """
        Check health of all pattern persistence layers.

        Returns:
            Dict containing layer health status
        """
        return await self._get("/tools/pps_health")

    async def health(self) -> dict[str, Any]:
        """
        Basic health check endpoint.

        Returns:
            Dict containing overall health status
        """
        return await self._get("/health")


async def test_client():
    """Test the PPS HTTP client."""
    async with PPSHttpClient() as client:
        # Test health
        print("Testing health endpoint...")
        health = await client.health()
        print(f"Health: {health['status']}")
        print(f"Layers available: {', '.join(health['layers'].keys())}")

        # Test ambient_recall
        print("\nTesting ambient_recall...")
        recall = await client.ambient_recall("startup", limit_per_layer=2)
        print(f"Memory health: {recall.get('memory_health', 'N/A')}")
        print(f"Unsummarized: {recall.get('unsummarized_count', 'N/A')}")
        print(f"\nClock: {recall.get('clock', {}).get('display', 'N/A')}")
        print(f"Results returned: {len(recall.get('results', []))}")

        # Show first result if available
        if recall.get('results'):
            print(f"\nFirst result preview:")
            first = recall['results'][0]
            print(f"  Layer: {first.get('layer')}")
            print(f"  Content: {first.get('content', '')[:200]}...")

        # Test texture_search
        print("\nTesting texture_search...")
        texture_results = await client.texture_search("terminal capture", limit=3)
        print(f"Texture search returned {len(texture_results.get('results', []))} results")
        if texture_results.get('results'):
            first_texture = texture_results['results'][0]
            print(f"  First result content: {first_texture.get('content', '')[:150]}...")
            print(f"  UUID: {first_texture.get('source', 'N/A')[:50]}...")
        else:
            print("  (No results - graph may be empty or query not matched)")

        # Test texture_explore
        print("\nTesting texture_explore...")
        explore_results = await client.texture_explore("terminal", depth=1)
        print(f"Texture explore returned {len(explore_results.get('results', []))} results")
        if explore_results.get('results'):
            print(f"  Found {len(explore_results['results'])} connected entities/relationships")
        else:
            print("  (No results - entity may not exist in graph)")

        # Test texture_timeline
        print("\nTesting texture_timeline...")
        timeline_results = await client.texture_timeline(
            since="2026-01-01",
            limit=3
        )
        print(f"Texture timeline returned {len(timeline_results.get('results', []))} results")
        if timeline_results.get('results'):
            first_timeline = timeline_results['results'][0]
            print(f"  First result: {first_timeline.get('content', '')[:150]}...")
        else:
            print("  (No results - timeline range may be empty)")

        print("\nAll texture endpoints tested successfully!")


if __name__ == "__main__":
    asyncio.run(test_client())
