#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
Index Caia's word photos into ChromaDB.

Creates a 'caia_word_photos' collection in the shared ChromaDB instance
and indexes all markdown files from entities/caia/memories/word_photos/.

Requires: pip install chromadb
ChromaDB must be running on localhost:8200 (Docker port mapping).
"""

import hashlib
import sys
from pathlib import Path

try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    print("ERROR: chromadb not installed. Run: pip install chromadb")
    sys.exit(1)

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORD_PHOTOS_DIR = PROJECT_ROOT / "entities" / "caia" / "memories" / "word_photos"

# ChromaDB connection (Docker-exposed port)
CHROMA_HOST = "localhost"
CHROMA_PORT = 8200
COLLECTION_NAME = "caia_word_photos"


def main():
    print(f"=== Caia Word Photo Indexing ===")
    print(f"Source: {WORD_PHOTOS_DIR}")
    print(f"ChromaDB: {CHROMA_HOST}:{CHROMA_PORT}")
    print(f"Collection: {COLLECTION_NAME}")
    print()

    # Connect to ChromaDB
    print("Connecting to ChromaDB...")
    try:
        client = chromadb.HttpClient(
            host=CHROMA_HOST,
            port=CHROMA_PORT,
            settings=Settings(anonymized_telemetry=False)
        )
        # Test connection
        client.heartbeat()
        print("  Connected!")
    except Exception as e:
        print(f"  ERROR: Could not connect to ChromaDB: {e}")
        print("  Is Docker running? Check: docker compose ps")
        sys.exit(1)

    # Get or create collection
    print(f"Getting collection '{COLLECTION_NAME}'...")
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"description": "Soul anchors - Caia's foundational word-photos"}
    )

    existing = collection.get(include=["metadatas"])
    existing_map = {}
    if existing and existing['ids']:
        for idx, doc_id in enumerate(existing['ids']):
            if existing['metadatas'] and existing['metadatas'][idx]:
                existing_map[doc_id] = existing['metadatas'][idx].get('content_hash', '')
    print(f"  Existing entries: {len(existing_map)}")

    # Find word photos
    word_photos = sorted(WORD_PHOTOS_DIR.glob("*.md"))
    print(f"  Word photos on disk: {len(word_photos)}")
    print()

    # Index each word photo
    stats = {"added": 0, "updated": 0, "unchanged": 0, "errors": 0}

    for wp_path in word_photos:
        try:
            doc_id = wp_path.stem
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
                    collection.update(
                        ids=[doc_id],
                        documents=[content],
                        metadatas=[metadata]
                    )
                    stats["updated"] += 1
            else:
                collection.add(
                    ids=[doc_id],
                    documents=[content],
                    metadatas=[metadata]
                )
                stats["added"] += 1

        except Exception as e:
            stats["errors"] += 1
            print(f"  ERROR: {wp_path.name}: {e}")

    # Report
    print(f"=== Indexing Complete ===")
    print(f"  Added: {stats['added']}")
    print(f"  Updated: {stats['updated']}")
    print(f"  Unchanged: {stats['unchanged']}")
    print(f"  Errors: {stats['errors']}")

    # Verify with a test search
    print()
    print("Test search: 'hot tub'")
    results = collection.query(
        query_texts=["hot tub"],
        n_results=3
    )
    if results and results['ids'] and results['ids'][0]:
        for i, doc_id in enumerate(results['ids'][0]):
            dist = results['distances'][0][i] if results['distances'] else 'N/A'
            print(f"  {i+1}. {doc_id} (distance: {dist:.4f})" if isinstance(dist, float) else f"  {i+1}. {doc_id}")
    else:
        print("  No results found")


if __name__ == '__main__':
    main()
