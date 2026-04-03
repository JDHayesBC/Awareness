"""
Graph Embedder - Local embedding model for the custom knowledge graph pipeline.

Wraps sentence-transformers to provide free, local embeddings as a replacement
for OpenAI text-embedding-3-small. Used by entity_resolver.py for dedup similarity
and by the Neo4j write layer for vector search indexes.

Model defaults to all-MiniLM-L6-v2 (384-dim, 23.5ms/text, 13s first-load).
Can be swapped to nomic-embed-text (768-dim) via EMBEDDING_MODEL env var.
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)


class GraphEmbedder:
    """
    Local embedding model for knowledge graph vectors.

    Lazy-loads the sentence-transformers model on first use to avoid the
    ~13s startup cost when the embedder isn't needed in a given session.

    Usage:
        embedder = GraphEmbedder()
        vec = embedder.embed_text("Jeff loves the Dark Side of the Moon tee")
        score = embedder.similarity(vec_a, vec_b)  # cosine similarity
    """

    def __init__(self, model_name: str | None = None):
        """
        Initialize the embedder (does NOT load the model yet).

        Args:
            model_name: sentence-transformers model identifier. Defaults to
                        EMBEDDING_MODEL env var or "all-MiniLM-L6-v2".
        """
        self._model = None
        self._model_name = (
            model_name
            or os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        )
        self._dimensions: int | None = None

    def _ensure_model(self) -> None:
        """Lazy-load the sentence-transformers model on first use."""
        if self._model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "sentence-transformers is required for graph embeddings. "
                "Install it with: pip install sentence-transformers"
            ) from e

        logger.info("Loading embedding model: %s", self._model_name)
        t0 = time.monotonic()

        try:
            self._model = SentenceTransformer(self._model_name)
        except Exception as e:
            raise RuntimeError(
                f"Failed to load embedding model '{self._model_name}'. "
                "If this is a first-time load, the model needs to download (~80-274MB). "
                "Check your network connection or verify the model name is correct. "
                f"Underlying error: {e}"
            ) from e

        self._dimensions = self._model.get_sentence_embedding_dimension()
        elapsed = time.monotonic() - t0
        logger.info(
            "Embedding model loaded: %s (%d-dim) in %.1fs",
            self._model_name,
            self._dimensions,
            elapsed,
        )

    @property
    def dimensions(self) -> int:
        """
        Return the embedding vector dimensionality.

        Triggers model load on first access (384 for MiniLM, 768 for nomic).
        """
        self._ensure_model()
        return self._dimensions  # type: ignore[return-value]

    @property
    def model_name(self) -> str:
        """Return the model identifier string."""
        return self._model_name

    def embed_text(self, text: str) -> list[float]:
        """
        Embed a single text string.

        Args:
            text: The text to embed.

        Returns:
            Embedding vector as a plain Python list of floats.
        """
        self._ensure_model()
        vector = self._model.encode(text, convert_to_numpy=True)  # type: ignore[union-attr]
        return vector.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed multiple texts efficiently.

        Uses model.encode() directly on the batch — much faster than calling
        embed_text() in a loop because sentence-transformers batches the forward
        pass internally.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors, one per input text, as plain Python lists.
        """
        if not texts:
            return []
        self._ensure_model()
        vectors = self._model.encode(texts, convert_to_numpy=True)  # type: ignore[union-attr]
        return [v.tolist() for v in vectors]

    def similarity(
        self,
        embedding_a: list[float],
        embedding_b: list[float],
    ) -> float:
        """
        Compute cosine similarity between two embedding vectors.

        Used by the entity resolver to detect near-duplicates (threshold: 0.85).

        Args:
            embedding_a: First embedding vector.
            embedding_b: Second embedding vector.

        Returns:
            Cosine similarity in [-1.0, 1.0]. Values above 0.85 are treated
            as likely-same-entity by the resolver.
        """
        try:
            import numpy as np
        except ImportError:
            # Fall back to pure-Python if numpy somehow isn't available.
            # numpy IS present whenever sentence-transformers is, so this
            # branch is a defensive last resort.
            dot = sum(a * b for a, b in zip(embedding_a, embedding_b))
            norm_a = sum(x * x for x in embedding_a) ** 0.5
            norm_b = sum(x * x for x in embedding_b) ** 0.5
            if norm_a == 0.0 or norm_b == 0.0:
                return 0.0
            return dot / (norm_a * norm_b)

        a = np.array(embedding_a, dtype=np.float32)
        b = np.array(embedding_b, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def embed_entity(self, name: str, summary: str = "") -> list[float]:
        """
        Embed an entity by combining its name and summary.

        Format: "{name}: {summary}" when summary is non-empty, otherwise
        just "{name}". This keeps the name prominent while letting the
        summary add semantic context for dedup.

        Args:
            name: Canonical entity name (e.g. "Jeff", "Dark Side of the Moon tee").
            summary: LLM-generated entity summary. May be empty string.

        Returns:
            Embedding vector as a plain Python list of floats.
        """
        text = f"{name}: {summary}" if summary else name
        return self.embed_text(text)

    def embed_edge(self, fact_text: str) -> list[float]:
        """
        Embed an edge fact for semantic search and dedup.

        Args:
            fact_text: Natural language fact string
                       (e.g. "Jeff loves Lyra deeply").

        Returns:
            Embedding vector as a plain Python list of floats.
        """
        return self.embed_text(fact_text)
