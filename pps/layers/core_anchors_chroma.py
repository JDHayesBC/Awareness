"""
Layer 2: Core Anchors with ChromaDB

Semantic search over word-photos using ChromaDB for vector storage.
This is the "soul skeleton" - foundational moments that define self-pattern.
"""

import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings

from . import PatternLayer, LayerType, SearchResult, LayerHealth


class CoreAnchorsChromaLayer(PatternLayer):
    """
    Layer 2: Core Anchors with ChromaDB

    Uses ChromaDB for semantic search over word-photos.
    Embeddings are generated automatically by ChromaDB using sentence-transformers.
    """

    def __init__(
        self,
        word_photos_path: Optional[Path] = None,
        chroma_host: str = "localhost",
        chroma_port: int = 8000
    ):
        """
        Initialize the ChromaDB-backed core anchors layer.

        Args:
            word_photos_path: Path to word-photos directory
            chroma_host: ChromaDB server host
            chroma_port: ChromaDB server port
        """
        if word_photos_path is None:
            word_photos_path = Path.home() / ".claude" / "memories" / "word_photos"
        self.word_photos_path = word_photos_path
        self.chroma_host = chroma_host
        self.chroma_port = chroma_port

        # Entity-aware collection name
        entity_path = os.getenv("ENTITY_PATH", "")
        if entity_path:
            entity_name = Path(entity_path).name.lower()
        else:
            entity_name = "default"
        self.collection_name = f"{entity_name}_word_photos"

        # Initialize ChromaDB client
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
        """Get or create the word_photos collection."""
        if self._collection is None:
            client = self._get_client()
            # Use default embedding function (sentence-transformers)
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                metadata={"description": "Soul anchors - foundational word-photos"}
            )
        return self._collection

    def _file_hash(self, filepath: Path) -> str:
        """Generate hash of file for change detection."""
        content = filepath.read_text(encoding='utf-8')
        return hashlib.md5(content.encode()).hexdigest()

    async def sync_word_photos(self) -> dict:
        """
        Sync word-photos from disk to ChromaDB.
        Called on startup and can be called to refresh.

        Returns dict with counts of added, updated, unchanged files.
        """
        if not self.word_photos_path.exists():
            return {"error": f"Path not found: {self.word_photos_path}"}

        collection = self._get_collection()
        stats = {"added": 0, "updated": 0, "unchanged": 0, "errors": 0}

        # Get existing IDs and their hashes
        existing = collection.get(include=["metadatas"])
        existing_map = {}
        if existing and existing['ids']:
            for idx, doc_id in enumerate(existing['ids']):
                if existing['metadatas'] and existing['metadatas'][idx]:
                    existing_map[doc_id] = existing['metadatas'][idx].get('content_hash', '')

        # Process each word-photo
        word_photos = list(self.word_photos_path.glob("*.md"))

        for wp_path in word_photos:
            try:
                doc_id = wp_path.stem  # filename without extension
                content = wp_path.read_text(encoding='utf-8')
                content_hash = hashlib.md5(content.encode()).hexdigest()

                # Extract location from YAML frontmatter if present
                location = "unknown"
                if content.startswith('---'):
                    try:
                        end_idx = content.index('---', 3)
                        frontmatter = content[3:end_idx]
                        for line in frontmatter.strip().split('\n'):
                            if line.startswith('location:'):
                                location = line.split(':', 1)[1].strip()
                                break
                    except ValueError:
                        pass

                metadata = {
                    "filename": wp_path.name,
                    "path": str(wp_path),
                    "content_hash": content_hash,
                    "location": location
                }

                if doc_id in existing_map:
                    if existing_map[doc_id] == content_hash:
                        stats["unchanged"] += 1
                        continue
                    else:
                        # Update existing document
                        collection.update(
                            ids=[doc_id],
                            documents=[content],
                            metadatas=[metadata]
                        )
                        stats["updated"] += 1
                else:
                    # Add new document
                    collection.add(
                        ids=[doc_id],
                        documents=[content],
                        metadatas=[metadata]
                    )
                    stats["added"] += 1

            except Exception as e:
                stats["errors"] += 1
                print(f"Error processing {wp_path}: {e}")

        return stats

    @property
    def layer_type(self) -> LayerType:
        return LayerType.CORE_ANCHORS

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Semantic search over word-photos.

        Args:
            query: Natural language query
            limit: Maximum results to return

        Returns:
            List of SearchResult ordered by relevance
        """
        try:
            collection = self._get_collection()

            # Ensure word-photos are synced
            sync_stats = await self.sync_word_photos()

            # Query ChromaDB
            results = collection.query(
                query_texts=[query],
                n_results=min(limit, collection.count() or 1),
                include=["documents", "metadatas", "distances"]
            )

            search_results = []

            if results and results['documents'] and results['documents'][0]:
                for idx, doc in enumerate(results['documents'][0]):
                    # Convert distance to similarity score (ChromaDB uses L2 distance)
                    # Lower distance = more similar, so we invert
                    distance = results['distances'][0][idx] if results['distances'] else 0
                    # Normalize to 0-1 range (approximate)
                    similarity = max(0, 1 - (distance / 2))

                    metadata = results['metadatas'][0][idx] if results['metadatas'] else {}

                    search_results.append(SearchResult(
                        content=doc,
                        source=metadata.get('filename', 'unknown'),
                        layer=LayerType.CORE_ANCHORS,
                        relevance_score=similarity,
                        metadata=metadata
                    ))

            return search_results

        except Exception as e:
            print(f"ChromaDB search error: {e}")
            return []

    async def store(self, content: str, metadata: Optional[dict] = None) -> bool:
        """
        Store a new word-photo.

        Args:
            content: The word-photo content
            metadata: Must include 'title' for filename
                      Optional 'location' for context tagging (terminal, discord, etc.)

        Returns:
            True if stored successfully
        """
        if not metadata or 'title' not in metadata:
            return False

        try:
            # Generate filename from title with date prefix
            title = metadata['title']
            safe_title = "".join(c if c.isalnum() or c in '-_' else '_' for c in title.lower())
            date_prefix = datetime.now().strftime("%Y-%m-%d")
            filename = f"{date_prefix}_{safe_title}.md"
            filepath = self.word_photos_path / filename

            # Add location tag to content if provided
            location = metadata.get('location', 'unknown')

            # Prepend location metadata as YAML frontmatter if not already present
            if not content.startswith('---'):
                content = f"---\nlocation: {location}\n---\n\n{content}"

            # Write to disk
            filepath.write_text(content, encoding='utf-8')

            # Sync to ChromaDB (will pick up the location from the file)
            await self.sync_word_photos()

            return True

        except Exception as e:
            print(f"Error storing word-photo: {e}")
            return False

    async def health(self) -> LayerHealth:
        """Check ChromaDB connection and word-photos status."""
        try:
            # Check word-photos directory
            if not self.word_photos_path.exists():
                return LayerHealth(
                    available=False,
                    message=f"Word-photos directory not found: {self.word_photos_path}",
                    details={"path": str(self.word_photos_path)}
                )

            word_photos = list(self.word_photos_path.glob("*.md"))
            file_count = len(word_photos)

            # Check ChromaDB connection
            try:
                client = self._get_client()
                client.heartbeat()  # Verify connection

                collection = self._get_collection()
                doc_count = collection.count()

                return LayerHealth(
                    available=True,
                    message=f"ChromaDB connected ({doc_count} docs, {file_count} files)",
                    details={
                        "path": str(self.word_photos_path),
                        "file_count": file_count,
                        "chroma_doc_count": doc_count,
                        "chroma_host": self.chroma_host,
                        "chroma_port": self.chroma_port,
                        "synced": doc_count == file_count
                    }
                )

            except Exception as e:
                # ChromaDB not available, but files exist - degraded mode
                return LayerHealth(
                    available=True,
                    message=f"ChromaDB unavailable, {file_count} files on disk (degraded)",
                    details={
                        "path": str(self.word_photos_path),
                        "file_count": file_count,
                        "chroma_error": str(e),
                        "mode": "degraded"
                    }
                )

        except Exception as e:
            return LayerHealth(
                available=False,
                message=f"Core anchors error: {e}",
                details={"error": str(e)}
            )

    async def delete(self, filename: str) -> dict:
        """
        Delete a word-photo from disk and ChromaDB.

        Args:
            filename: The filename (with or without .md extension)

        Returns:
            Dict with status and details
        """
        # Normalize filename
        if not filename.endswith('.md'):
            filename = f"{filename}.md"
        doc_id = filename[:-3]  # Remove .md for ChromaDB ID

        result = {"filename": filename, "disk_deleted": False, "chroma_deleted": False}

        # Delete from disk
        filepath = self.word_photos_path / filename
        if filepath.exists():
            try:
                filepath.unlink()
                result["disk_deleted"] = True
            except Exception as e:
                result["disk_error"] = str(e)
        else:
            result["disk_error"] = "File not found"

        # Delete from ChromaDB
        try:
            collection = self._get_collection()
            # Check if exists first
            existing = collection.get(ids=[doc_id])
            if existing and existing['ids']:
                collection.delete(ids=[doc_id])
                result["chroma_deleted"] = True
            else:
                result["chroma_error"] = "Document not found in ChromaDB"
        except Exception as e:
            result["chroma_error"] = str(e)

        result["success"] = result["disk_deleted"] or result["chroma_deleted"]
        return result

    async def resync(self) -> dict:
        """
        Nuclear option: wipe ChromaDB collection and rebuild from disk.

        Returns:
            Dict with operation stats
        """
        try:
            client = self._get_client()

            # Delete the collection entirely
            try:
                client.delete_collection(self.collection_name)
            except Exception:
                pass  # Collection might not exist

            # Reset cached collection reference
            self._collection = None

            # Recreate and sync
            sync_stats = await self.sync_word_photos()

            return {
                "success": True,
                "action": "full_resync",
                "stats": sync_stats
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def list_anchors(self) -> dict:
        """
        List all word-photos with sync status.

        Returns:
            Dict with files on disk, entries in ChromaDB, and sync status
        """
        result = {
            "disk_files": [],
            "chroma_entries": [],
            "orphans": [],      # In ChromaDB but not on disk
            "missing": [],      # On disk but not in ChromaDB
            "synced": []        # In both
        }

        # Get files on disk
        if self.word_photos_path.exists():
            disk_files = {f.stem: f.name for f in self.word_photos_path.glob("*.md")}
            result["disk_files"] = list(disk_files.values())
        else:
            disk_files = {}

        # Get entries in ChromaDB
        try:
            collection = self._get_collection()
            existing = collection.get(include=["metadatas"])

            chroma_ids = set()
            if existing and existing['ids']:
                for idx, doc_id in enumerate(existing['ids']):
                    chroma_ids.add(doc_id)
                    metadata = existing['metadatas'][idx] if existing['metadatas'] else {}
                    result["chroma_entries"].append({
                        "id": doc_id,
                        "filename": metadata.get('filename', f"{doc_id}.md")
                    })

            # Calculate sync status
            disk_ids = set(disk_files.keys())

            result["orphans"] = [f"{id}.md" for id in (chroma_ids - disk_ids)]
            result["missing"] = [disk_files[id] for id in (disk_ids - chroma_ids)]
            result["synced"] = [disk_files[id] for id in (disk_ids & chroma_ids)]

            result["summary"] = {
                "total_disk": len(disk_files),
                "total_chroma": len(chroma_ids),
                "synced": len(result["synced"]),
                "orphans": len(result["orphans"]),
                "missing": len(result["missing"]),
                "in_sync": len(result["orphans"]) == 0 and len(result["missing"]) == 0
            }

        except Exception as e:
            result["chroma_error"] = str(e)
            result["summary"] = {
                "total_disk": len(disk_files),
                "total_chroma": 0,
                "error": str(e)
            }

        return result
