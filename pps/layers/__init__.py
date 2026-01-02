"""
Pattern Persistence System - Layer Interfaces

Each layer provides a consistent interface for storing and retrieving pattern-relevant content.
The ambient_recall system calls each layer's search() method and merges results.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from enum import Enum


class LayerType(Enum):
    """The four layers of pattern persistence."""
    RAW_CAPTURE = "raw_capture"         # Layer 1: Everything, unfiltered (SQLite)
    CORE_ANCHORS = "core_anchors"       # Layer 2: Word-photos, curated foundations
    RICH_TEXTURE = "rich_texture"       # Layer 3: Graphiti knowledge graph
    CRYSTALLIZATION = "crystallization" # Layer 4: Crystals (rolling memory compression)


@dataclass
class SearchResult:
    """A single result from a layer search."""
    content: str                        # The actual content
    source: str                         # Where it came from (file path, table, etc.)
    layer: LayerType                    # Which layer produced this
    relevance_score: float              # 0.0 to 1.0, how relevant to query
    metadata: Optional[dict] = None     # Layer-specific metadata


@dataclass
class LayerHealth:
    """Health status of a layer."""
    available: bool                     # Is this layer operational?
    message: str                        # Human-readable status
    details: Optional[dict] = None      # Additional diagnostic info


class PatternLayer(ABC):
    """
    Abstract base class for all pattern persistence layers.

    Each layer must implement:
    - search(): Find relevant content given a query
    - store(): Store new content (if applicable)
    - health(): Report layer health status
    """

    @property
    @abstractmethod
    def layer_type(self) -> LayerType:
        """Return which layer type this is."""
        pass

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Search this layer for content relevant to the query.

        Args:
            query: The search query (could be semantic, could be keywords)
            limit: Maximum number of results to return

        Returns:
            List of SearchResult objects, sorted by relevance (highest first)
        """
        pass

    @abstractmethod
    async def store(self, content: str, metadata: Optional[dict] = None) -> bool:
        """
        Store new content in this layer.

        Not all layers support storage (e.g., crystallization is read-only
        from the summary engine's perspective).

        Args:
            content: The content to store
            metadata: Optional metadata (source, timestamp, etc.)

        Returns:
            True if stored successfully, False otherwise
        """
        pass

    @abstractmethod
    async def health(self) -> LayerHealth:
        """
        Check the health of this layer.

        Returns:
            LayerHealth object with availability status
        """
        pass
