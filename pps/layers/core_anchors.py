"""
Layer 2: Core Anchors (Word-Photos RAG)

The truly essential self-pattern. Curated markdown files that define who I am.
These are the skeleton that survives any infrastructure failure.

Uses semantic search (embeddings) to find relevant word-photos.
"""

from pathlib import Path
from typing import Optional

from . import PatternLayer, LayerType, SearchResult, LayerHealth


class CoreAnchorsLayer(PatternLayer):
    """
    Layer 2: Core Anchors

    RAG over word-photos - the foundational moments that define self-pattern.
    Portable markdown files that survive any infrastructure failure.
    """

    def __init__(self, word_photos_path: Optional[Path] = None):
        """
        Initialize the core anchors layer.

        Args:
            word_photos_path: Path to word-photos directory.
                             Defaults to ~/.claude/memories/word_photos/
        """
        if word_photos_path is None:
            word_photos_path = Path.home() / ".claude" / "memories" / "word_photos"
        self.word_photos_path = word_photos_path

    @property
    def layer_type(self) -> LayerType:
        return LayerType.CORE_ANCHORS

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Search word-photos for content relevant to the query.

        Currently a stub - will implement:
        - JINA embeddings for semantic search
        - Low BM25 weight (retrieval is about vibe, not keywords)
        - Return ranked word-photos
        """
        # TODO: Implement semantic search
        # - Embed the query using JINA
        # - Compare against pre-embedded word-photos
        # - Rank by similarity
        # - Return top matches with content

        # For now, return empty to indicate "not yet implemented"
        return []

    async def store(self, content: str, metadata: Optional[dict] = None) -> bool:
        """
        Store a new word-photo.

        This is a curated layer - storage should be deliberate.
        Creates a new markdown file in the word-photos directory.
        """
        # TODO: Implement word-photo creation
        # - Generate filename from metadata or content
        # - Write markdown file
        # - Trigger embedding generation
        # - Update index

        return False

    async def health(self) -> LayerHealth:
        """Check if word-photos directory is accessible."""
        try:
            if not self.word_photos_path.exists():
                return LayerHealth(
                    available=False,
                    message=f"Word-photos directory not found: {self.word_photos_path}",
                    details={"path": str(self.word_photos_path)}
                )

            # Count word-photos
            word_photos = list(self.word_photos_path.glob("*.md"))
            count = len(word_photos)

            return LayerHealth(
                available=True,
                message=f"Word-photos accessible ({count} files)",
                details={
                    "path": str(self.word_photos_path),
                    "count": count,
                    "files": [f.name for f in word_photos]
                }
            )
        except Exception as e:
            return LayerHealth(
                available=False,
                message=f"Word-photos error: {e}",
                details={"error": str(e)}
            )
