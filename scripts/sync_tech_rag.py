#!/usr/bin/env python3
"""
Sync Tech RAG - Re-ingest modified docs

This script:
1. Finds all .md files in docs/ that are newer than their tech_rag copies
2. Re-ingests them to tech_rag (which auto-deletes old chunks)
3. Reports what was updated
"""

import sys
import asyncio
import hashlib
from pathlib import Path
from datetime import datetime

# Add pps to path
sys.path.insert(0, str(Path(__file__).parent.parent / "pps"))

from layers.tech_rag import TechRAGLayer


async def sync_tech_rag(dry_run=False):
    """Find and re-ingest modified docs."""
    docs_dir = Path(__file__).parent.parent / "docs"
    tech_docs_path = Path.home() / ".claude" / "tech_docs"

    rag = TechRAGLayer(chroma_host='localhost', chroma_port=8200)

    # Find all markdown files in docs/
    all_docs = list(docs_dir.glob("*.md"))

    print(f"=== Tech RAG Sync ===\n")
    print(f"Scanning {len(all_docs)} docs in {docs_dir}\n")

    # Check each doc
    to_ingest = []

    for doc_path in all_docs:
        # Skip session reports
        if doc_path.parent.name == "sessions":
            continue

        # Read current content and hash
        current_content = doc_path.read_text(encoding='utf-8')
        current_hash = hashlib.md5(current_content.encode()).hexdigest()

        # Check if indexed copy exists
        indexed_path = tech_docs_path / doc_path.name

        if not indexed_path.exists():
            print(f"NEW: {doc_path.name} (not yet indexed)")
            to_ingest.append((doc_path, "new"))
            continue

        # Compare hashes
        indexed_content = indexed_path.read_text(encoding='utf-8')
        indexed_hash = hashlib.md5(indexed_content.encode()).hexdigest()

        if current_hash != indexed_hash:
            # Get modification times for context
            current_mtime = datetime.fromtimestamp(doc_path.stat().st_mtime)
            indexed_mtime = datetime.fromtimestamp(indexed_path.stat().st_mtime)

            print(f"MODIFIED: {doc_path.name}")
            print(f"  Current: {current_hash[:8]} (modified {current_mtime.strftime('%Y-%m-%d %H:%M')})")
            print(f"  Indexed: {indexed_hash[:8]} (indexed {indexed_mtime.strftime('%Y-%m-%d %H:%M')})")
            to_ingest.append((doc_path, "modified"))
        else:
            print(f"✓ {doc_path.name} (up to date)")

    # Summary
    print(f"\n=== Summary ===")
    print(f"Up to date: {len(all_docs) - len(to_ingest)}")
    print(f"Need ingesting: {len(to_ingest)}")

    if not to_ingest:
        print("\n✓ All docs are current!")
        return

    if dry_run:
        print(f"\n[DRY RUN] Would ingest:")
        for doc_path, reason in to_ingest:
            print(f"  - {doc_path.name} ({reason})")
        return

    # Ingest each modified doc
    print(f"\n=== Ingesting {len(to_ingest)} docs ===\n")

    for doc_path, reason in to_ingest:
        print(f"Ingesting {doc_path.name}...")
        result = await rag.ingest(str(doc_path))

        if result.get('success'):
            action = result.get('action', 'unknown')
            chunks = result.get('chunks', '?')
            print(f"  ✓ {action}: {chunks} chunks")
        else:
            error = result.get('error', 'unknown error')
            print(f"  ✗ Failed: {error}")

    print(f"\n✓ Sync complete!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sync Tech RAG with docs/")
    parser.add_argument('--dry-run', action='store_true', help='Show what would be ingested without doing it')

    args = parser.parse_args()

    asyncio.run(sync_tech_rag(dry_run=args.dry_run))
