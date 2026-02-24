#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
Check Tech RAG health - find and fix stale document chunks.

This script:
1. Connects to ChromaDB tech_docs collection
2. Finds documents with multiple content_hash versions (stale data)
3. Optionally deletes old versions, keeping only the newest
4. Reports stats and recommendations
"""

import sys
from pathlib import Path
from collections import defaultdict

# Add pps to path
sys.path.insert(0, str(Path(__file__).parent.parent / "pps"))

from layers.tech_rag import TechRAGLayer


def analyze_tech_rag():
    """Analyze tech_rag for duplicate/stale chunks."""
    rag = TechRAGLayer(chroma_host='localhost', chroma_port=8200)

    try:
        collection = rag._get_collection()
        all_items = collection.get(include=['metadatas'])

        if not all_items or not all_items['ids']:
            print("Tech RAG is empty")
            return

        print(f"=== Tech RAG Health Check ===\n")
        print(f"Total chunks: {len(all_items['ids'])}\n")

        # Group by doc_id and track versions
        doc_versions = defaultdict(lambda: defaultdict(list))

        for idx, metadata in enumerate(all_items['metadatas']):
            if not metadata:
                continue

            doc_id = metadata.get('doc_id', 'unknown')
            content_hash = metadata.get('content_hash', 'unknown')
            indexed_at = metadata.get('indexed_at', 'unknown')
            chunk_num = metadata.get('chunk_num', '?')

            doc_versions[doc_id][content_hash].append({
                'chunk_id': all_items['ids'][idx],
                'indexed_at': indexed_at,
                'chunk_num': chunk_num
            })

        # Analyze each document
        stale_docs = []
        clean_docs = []

        for doc_id, versions in sorted(doc_versions.items()):
            if len(versions) > 1:
                stale_docs.append((doc_id, versions))
                print(f"❌ {doc_id}: {len(versions)} versions (STALE DATA!)")

                # Sort versions by indexed_at to find newest
                sorted_versions = sorted(
                    versions.items(),
                    key=lambda x: max(c['indexed_at'] for c in x[1]),
                    reverse=True
                )

                for i, (content_hash, chunks) in enumerate(sorted_versions):
                    age_marker = "← NEWEST" if i == 0 else "← OLD"
                    print(f"   - hash {content_hash[:8]}: {len(chunks)} chunks, "
                          f"indexed {chunks[0]['indexed_at'][:10]} {age_marker}")
                print()
            else:
                content_hash, chunks = list(versions.items())[0]
                clean_docs.append(doc_id)
                print(f"✓ {doc_id}: {len(chunks)} chunks "
                      f"(hash {content_hash[:8]}, indexed {chunks[0]['indexed_at'][:10]})")

        # Summary
        print(f"\n=== Summary ===")
        print(f"Clean documents: {len(clean_docs)}")
        print(f"Documents with stale data: {len(stale_docs)}")

        if stale_docs:
            print(f"\n⚠️  Found {len(stale_docs)} documents with multiple versions!")
            print(f"Old chunks are competing with current data in search results.")
            print(f"\nRecommendation: Re-ingest these documents to clean up:")
            for doc_id, _ in stale_docs:
                print(f"  - {doc_id}")
        else:
            print(f"\n✓ All documents are clean - no stale data found")

        return stale_docs

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def cleanup_stale(doc_id: str):
    """Delete old versions of a document, keeping only the newest."""
    rag = TechRAGLayer(chroma_host='localhost', chroma_port=8200)

    try:
        collection = rag._get_collection()

        # Get all chunks for this doc
        items = collection.get(
            where={"doc_id": doc_id},
            include=['metadatas']
        )

        if not items or not items['ids']:
            print(f"No chunks found for {doc_id}")
            return False

        # Group by content_hash
        versions = defaultdict(list)
        for idx, metadata in enumerate(items['metadatas']):
            content_hash = metadata.get('content_hash', 'unknown')
            indexed_at = metadata.get('indexed_at', 'unknown')
            versions[content_hash].append({
                'chunk_id': items['ids'][idx],
                'indexed_at': indexed_at
            })

        if len(versions) <= 1:
            print(f"{doc_id} has only one version, nothing to clean")
            return False

        # Find newest version
        newest_hash = max(
            versions.keys(),
            key=lambda h: max(c['indexed_at'] for c in versions[h])
        )

        # Delete all chunks except newest
        deleted_count = 0
        for content_hash, chunks in versions.items():
            if content_hash != newest_hash:
                chunk_ids = [c['chunk_id'] for c in chunks]
                collection.delete(ids=chunk_ids)
                deleted_count += len(chunk_ids)
                print(f"Deleted {len(chunk_ids)} old chunks (hash {content_hash[:8]})")

        print(f"✓ Cleaned {doc_id}: kept {len(versions[newest_hash])} newest chunks, "
              f"deleted {deleted_count} old chunks")
        return True

    except Exception as e:
        print(f"Error cleaning {doc_id}: {e}")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check Tech RAG health")
    parser.add_argument('--cleanup', metavar='DOC_ID', help='Clean up stale versions of a document')
    parser.add_argument('--cleanup-all', action='store_true', help='Clean up all stale documents')

    args = parser.parse_args()

    if args.cleanup:
        cleanup_stale(args.cleanup)
    elif args.cleanup_all:
        stale_docs = analyze_tech_rag()
        if stale_docs:
            print(f"\n=== Cleaning up {len(stale_docs)} stale documents ===\n")
            for doc_id, _ in stale_docs:
                cleanup_stale(doc_id)
            print("\n✓ Cleanup complete!")
    else:
        analyze_tech_rag()
