"""
Layer 6: Tech RAG - Technical Documentation Retrieval

A separate ChromaDB collection for technical documentation.
Unlike word-photos, these documents get chunked for better retrieval.
This is "family knowledge" - searchable by any entity.
"""

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings

from . import PatternLayer, LayerType, SearchResult, LayerHealth


class TechRAGLayer(PatternLayer):
    """
    Layer 6: Technical Documentation RAG

    Ingests markdown documents, chunks them, and enables semantic search.
    Separate from personal memory layers - this is shared technical knowledge.
    """

    COLLECTION_NAME = "tech_docs"

    # Chunking parameters
    CHUNK_SIZE = 800  # target chars per chunk
    CHUNK_OVERLAP = 100  # overlap between chunks for context

    def __init__(
        self,
        tech_docs_path: Optional[Path] = None,
        chroma_host: str = "localhost",
        chroma_port: int = 8000
    ):
        """
        Initialize the Tech RAG layer.

        Args:
            tech_docs_path: Path to indexed documents directory
            chroma_host: ChromaDB server host
            chroma_port: ChromaDB server port
        """
        if tech_docs_path is None:
            tech_docs_path = Path.home() / ".claude" / "tech_docs"
        self.tech_docs_path = tech_docs_path
        self.tech_docs_path.mkdir(parents=True, exist_ok=True)

        self.chroma_host = chroma_host
        self.chroma_port = chroma_port

        self._client = None
        self._collection = None

    def _get_client(self):
        """Lazy initialization of ChromaDB client."""
        if self._client is None:
            self._client = chromadb.HttpClient(
                host=self.chroma_host,
                port=self.chroma_port,
                settings=Settings(anonymized_telemetry=False)
            )
        return self._client

    def _get_collection(self):
        """Get or create the tech_docs collection."""
        if self._collection is None:
            client = self._get_client()
            self._collection = client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"description": "Technical documentation for family knowledge"}
            )
        return self._collection

    def _chunk_document(self, content: str, doc_id: str) -> list[dict]:
        """
        Split a document into chunks for indexing.

        Strategy:
        1. Split by headers (##, ###) first
        2. If sections still too long, split by paragraphs
        3. Add overlap between chunks

        Returns list of {"id": str, "content": str, "metadata": dict}
        """
        chunks = []

        # Split by markdown headers (## or ###)
        # Keep the header with its section
        sections = re.split(r'(?=^#{2,3}\s)', content, flags=re.MULTILINE)

        chunk_num = 0
        for section in sections:
            section = section.strip()
            if not section:
                continue

            # If section is small enough, use as-is
            if len(section) <= self.CHUNK_SIZE:
                chunks.append({
                    "id": f"{doc_id}_chunk_{chunk_num}",
                    "content": section,
                    "chunk_num": chunk_num
                })
                chunk_num += 1
            else:
                # Split by paragraphs
                paragraphs = section.split('\n\n')
                current_chunk = ""

                for para in paragraphs:
                    para = para.strip()
                    if not para:
                        continue

                    # If adding this paragraph exceeds chunk size, save current and start new
                    if len(current_chunk) + len(para) + 2 > self.CHUNK_SIZE and current_chunk:
                        chunks.append({
                            "id": f"{doc_id}_chunk_{chunk_num}",
                            "content": current_chunk.strip(),
                            "chunk_num": chunk_num
                        })
                        chunk_num += 1
                        # Start new chunk with overlap from previous
                        overlap_text = current_chunk[-self.CHUNK_OVERLAP:] if len(current_chunk) > self.CHUNK_OVERLAP else ""
                        current_chunk = overlap_text + "\n\n" + para if overlap_text else para
                    else:
                        current_chunk = current_chunk + "\n\n" + para if current_chunk else para

                # Don't forget the last chunk
                if current_chunk.strip():
                    chunks.append({
                        "id": f"{doc_id}_chunk_{chunk_num}",
                        "content": current_chunk.strip(),
                        "chunk_num": chunk_num
                    })
                    chunk_num += 1

        return chunks

    async def ingest(self, filepath: str, category: Optional[str] = None, force: bool = False) -> dict:
        """
        Ingest a markdown file into the tech RAG.

        Args:
            filepath: Path to the markdown file
            category: Optional category tag (e.g., "architecture", "api", "guide")
            force: If True, re-index even if content hash hasn't changed

        Returns:
            Dict with ingestion stats
        """
        filepath = Path(filepath)

        if not filepath.exists():
            return {"success": False, "error": f"File not found: {filepath}"}

        if not filepath.suffix.lower() in ['.md', '.mdx', '.txt']:
            return {"success": False, "error": "Only .md, .mdx, and .txt files supported"}

        try:
            content = filepath.read_text(encoding='utf-8')
            doc_id = filepath.stem  # filename without extension
            content_hash = hashlib.md5(content.encode()).hexdigest()

            # Check if already indexed with same hash
            collection = self._get_collection()
            existing = collection.get(
                where={"doc_id": doc_id},
                include=["metadatas"]
            )

            if existing and existing['ids']:
                # Check if content changed
                old_hash = existing['metadatas'][0].get('content_hash', '') if existing['metadatas'] else ''
                if old_hash == content_hash and not force:
                    return {
                        "success": True,
                        "action": "unchanged",
                        "doc_id": doc_id,
                        "message": "Document already indexed with same content"
                    }
                # Delete all old chunks before re-indexing (content changed or force=True)
                collection.delete(where={"doc_id": doc_id})

            # Chunk the document
            chunks = self._chunk_document(content, doc_id)

            if not chunks:
                return {"success": False, "error": "No content to index"}

            # Add all chunks to ChromaDB
            chunk_ids = [c["id"] for c in chunks]
            chunk_contents = [c["content"] for c in chunks]
            chunk_metadatas = [
                {
                    "doc_id": doc_id,
                    "filename": filepath.name,
                    "source_path": str(filepath.absolute()),
                    "chunk_num": c["chunk_num"],
                    "total_chunks": len(chunks),
                    "content_hash": content_hash,
                    "category": category or "general",
                    "indexed_at": datetime.now().isoformat()
                }
                for c in chunks
            ]

            collection.add(
                ids=chunk_ids,
                documents=chunk_contents,
                metadatas=chunk_metadatas
            )

            # Copy file to tech_docs directory for reference
            dest_path = self.tech_docs_path / filepath.name
            dest_path.write_text(content, encoding='utf-8')

            return {
                "success": True,
                "action": "indexed",
                "doc_id": doc_id,
                "chunks": len(chunks),
                "category": category or "general",
                "stored_at": str(dest_path)
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    @property
    def layer_type(self) -> LayerType:
        # Using RICH_TEXTURE as placeholder since we don't have a dedicated type
        # In practice this layer has its own collection
        return LayerType.RICH_TEXTURE

    async def search(self, query: str, limit: int = 5, category: Optional[str] = None) -> list[SearchResult]:
        """
        Semantic search over tech docs.

        Args:
            query: Natural language query
            limit: Maximum results to return
            category: Optional category filter

        Returns:
            List of SearchResult ordered by relevance
        """
        try:
            collection = self._get_collection()

            # Build where clause if category specified
            where = {"category": category} if category else None

            results = collection.query(
                query_texts=[query],
                n_results=limit,
                where=where,
                include=["documents", "metadatas", "distances"]
            )

            search_results = []

            if results and results['documents'] and results['documents'][0]:
                for idx, doc in enumerate(results['documents'][0]):
                    distance = results['distances'][0][idx] if results['distances'] else 0
                    similarity = max(0, 1 - (distance / 2))

                    metadata = results['metadatas'][0][idx] if results['metadatas'] else {}

                    # Format source to show doc name and chunk
                    source = f"{metadata.get('filename', 'unknown')} (chunk {metadata.get('chunk_num', '?')}/{metadata.get('total_chunks', '?')})"

                    search_results.append(SearchResult(
                        content=doc,
                        source=source,
                        layer=LayerType.RICH_TEXTURE,  # placeholder type
                        relevance_score=similarity,
                        metadata=metadata
                    ))

            return search_results

        except Exception as e:
            print(f"Tech RAG search error: {e}")
            return []

    async def store(self, content: str, metadata: Optional[dict] = None) -> bool:
        """Store is not the primary interface - use ingest() instead."""
        return False

    async def health(self) -> LayerHealth:
        """Check Tech RAG status."""
        try:
            client = self._get_client()
            client.heartbeat()

            collection = self._get_collection()
            count = collection.count()

            # Count unique documents
            all_items = collection.get(include=["metadatas"])
            doc_ids = set()
            if all_items and all_items['metadatas']:
                for m in all_items['metadatas']:
                    if m and 'doc_id' in m:
                        doc_ids.add(m['doc_id'])

            return LayerHealth(
                available=True,
                message=f"Tech RAG: {len(doc_ids)} docs, {count} chunks",
                details={
                    "documents": len(doc_ids),
                    "chunks": count,
                    "path": str(self.tech_docs_path)
                }
            )

        except Exception as e:
            return LayerHealth(
                available=False,
                message=f"Tech RAG unavailable: {e}",
                details={"error": str(e)}
            )

    async def list_docs(self) -> dict:
        """
        List all indexed documents.

        Returns:
            Dict with document info
        """
        try:
            collection = self._get_collection()
            all_items = collection.get(include=["metadatas"])

            docs = {}
            if all_items and all_items['metadatas']:
                for m in all_items['metadatas']:
                    if not m:
                        continue
                    doc_id = m.get('doc_id', 'unknown')
                    if doc_id not in docs:
                        docs[doc_id] = {
                            "filename": m.get('filename', 'unknown'),
                            "category": m.get('category', 'general'),
                            "chunks": 0,
                            "indexed_at": m.get('indexed_at', 'unknown')
                        }
                    docs[doc_id]["chunks"] += 1

            return {
                "success": True,
                "count": len(docs),
                "documents": docs
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def delete_doc(self, doc_id: str) -> dict:
        """
        Delete a document and all its chunks.

        Args:
            doc_id: The document ID to delete

        Returns:
            Dict with deletion status
        """
        try:
            collection = self._get_collection()

            # Get count before delete
            before = collection.get(where={"doc_id": doc_id})
            chunks_deleted = len(before['ids']) if before and before['ids'] else 0

            if chunks_deleted == 0:
                return {"success": False, "error": f"Document not found: {doc_id}"}

            # Delete from ChromaDB
            collection.delete(where={"doc_id": doc_id})

            # Delete from disk if present
            disk_deleted = False
            for ext in ['.md', '.mdx', '.txt']:
                disk_path = self.tech_docs_path / f"{doc_id}{ext}"
                if disk_path.exists():
                    disk_path.unlink()
                    disk_deleted = True
                    break

            return {
                "success": True,
                "doc_id": doc_id,
                "chunks_deleted": chunks_deleted,
                "disk_deleted": disk_deleted
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
