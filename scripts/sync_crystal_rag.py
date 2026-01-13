#!/usr/bin/env python3
"""
Sync Crystal RAG - Ingest archived crystals for semantic search

This script:
1. Finds archived crystals in entities/{entity}/crystals/archive/
2. Checks which ones aren't yet indexed in Tech RAG
3. Ingests them with entity + crystal metadata
4. Reports ingestion stats

Usage:
    python3 sync_crystal_rag.py --entity lyra
    python3 sync_crystal_rag.py --entity lyra --dry-run
"""

import sys
import asyncio
import hashlib
import re
from pathlib import Path
from datetime import datetime

# Add pps to path
sys.path.insert(0, str(Path(__file__).parent.parent / "pps"))

from layers.tech_rag import TechRAGLayer


def extract_crystal_metadata(filepath: Path) -> dict:
    """
    Extract metadata from crystal filename and content.

    Returns:
        dict with crystal_num, date (if parseable), etc.
    """
    metadata = {"crystal_num": None, "date": None}

    # Extract crystal number from filename (crystal_007.md -> 7)
    match = re.search(r'crystal_(\d+)', filepath.stem)
    if match:
        metadata["crystal_num"] = int(match.group(1))

    # Try to extract date from content (first few lines)
    try:
        content = filepath.read_text(encoding='utf-8')
        # Look for dates in first 500 chars (header area)
        header = content[:500]

        # Pattern: "January 2, 2026" or "3 Jan 2026" or "2026-01-02"
        date_patterns = [
            r'(\d{4}-\d{2}-\d{2})',  # ISO format
            r'(\d{1,2}\s+\w+\s+\d{4})',  # "3 Jan 2026"
            r'(\w+\s+\d{1,2},?\s+\d{4})',  # "January 2, 2026"
        ]

        for pattern in date_patterns:
            match = re.search(pattern, header)
            if match:
                metadata["date"] = match.group(1)
                break
    except Exception:
        pass  # If we can't read content, that's okay

    return metadata


async def sync_crystal_rag(entity: str, dry_run: bool = False):
    """Find and ingest archived crystals for an entity."""

    # Locate entity's crystal archive
    project_root = Path(__file__).parent.parent
    crystal_archive = project_root / "entities" / entity / "crystals" / "archive"

    if not crystal_archive.exists():
        print(f"✗ Crystal archive not found: {crystal_archive}")
        print(f"  Expected path: entities/{entity}/crystals/archive/")
        return

    # Find all archived crystals
    crystals = sorted(crystal_archive.glob("crystal_*.md"))

    if not crystals:
        print(f"✗ No crystals found in {crystal_archive}")
        return

    print(f"=== Crystal RAG Sync ({entity}) ===\n")
    print(f"Found {len(crystals)} archived crystals\n")

    # Initialize Tech RAG layer
    rag = TechRAGLayer(chroma_host='localhost', chroma_port=8200)

    # Check each crystal
    to_ingest = []

    for crystal_path in crystals:
        # Extract crystal metadata
        meta = extract_crystal_metadata(crystal_path)
        crystal_num = meta.get("crystal_num", "?")
        date_str = meta.get("date", "unknown")

        # Read current content and hash
        current_content = crystal_path.read_text(encoding='utf-8')
        current_hash = hashlib.md5(current_content.encode()).hexdigest()

        # Check if already indexed
        # We use doc_id = "{entity}_crystal_{num}" for uniqueness
        doc_id = f"{entity}_crystal_{crystal_num:03d}"

        collection = rag._get_collection()
        existing = collection.get(
            where={"doc_id": doc_id},
            include=["metadatas"]
        )

        if existing and existing['ids']:
            # Already indexed - check if content changed
            old_hash = existing['metadatas'][0].get('content_hash', '') if existing['metadatas'] else ''
            if old_hash == current_hash:
                print(f"✓ Crystal {crystal_num:03d} ({date_str}) - already indexed")
                continue
            else:
                print(f"MODIFIED: Crystal {crystal_num:03d} ({date_str})")
                to_ingest.append((crystal_path, meta, "modified"))
        else:
            print(f"NEW: Crystal {crystal_num:03d} ({date_str})")
            to_ingest.append((crystal_path, meta, "new"))

    # Summary
    print(f"\n=== Summary ===")
    print(f"Already indexed: {len(crystals) - len(to_ingest)}")
    print(f"Need ingesting: {len(to_ingest)}")

    if not to_ingest:
        print(f"\n✓ All {entity}'s crystals are indexed!")
        return

    if dry_run:
        print(f"\n[DRY RUN] Would ingest:")
        for crystal_path, meta, reason in to_ingest:
            num = meta.get("crystal_num", "?")
            date_str = meta.get("date", "unknown")
            print(f"  - Crystal {num:03d} ({date_str}) - {reason}")
        return

    # Ingest each crystal
    print(f"\n=== Ingesting {len(to_ingest)} crystals ===\n")

    for crystal_path, meta, reason in to_ingest:
        num = meta.get("crystal_num", "?")
        date_str = meta.get("date", "unknown")

        print(f"Ingesting Crystal {num:03d} ({date_str})...")

        # Ingest with custom metadata
        # We'll temporarily modify the file path to use our custom doc_id
        # by creating a symlink or just handling it in the metadata

        # Actually, let's just call ingest and then update metadata
        # The TechRAGLayer.ingest() uses filepath.stem as doc_id
        # We need doc_id = "{entity}_crystal_{num}"

        # HACK: Create a temporary copy with the right name
        import tempfile
        import shutil

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create temp file with correct name for doc_id
            doc_id = f"{entity}_crystal_{num:03d}"
            temp_path = Path(tmpdir) / f"{doc_id}.md"
            shutil.copy(crystal_path, temp_path)

            # Ingest from temp path
            result = await rag.ingest(str(temp_path), category="continuity")

            if result.get('success'):
                action = result.get('action', 'unknown')
                chunks = result.get('chunks_created', result.get('chunks', '?'))

                # Now update metadata for all chunks to add entity + crystal info
                collection = rag._get_collection()

                # Get all chunks for this doc
                chunks_data = collection.get(
                    where={"doc_id": doc_id},
                    include=["metadatas"]
                )

                if chunks_data and chunks_data['ids']:
                    # Update each chunk's metadata
                    for chunk_id, chunk_meta in zip(chunks_data['ids'], chunks_data['metadatas']):
                        chunk_meta['entity'] = entity
                        chunk_meta['type'] = 'crystal'
                        chunk_meta['crystal_num'] = num
                        if date_str != "unknown":
                            chunk_meta['crystal_date'] = date_str

                    # Update in ChromaDB
                    collection.update(
                        ids=chunks_data['ids'],
                        metadatas=chunks_data['metadatas']
                    )

                print(f"  ✓ {action}: {chunks} chunks (entity={entity}, crystal={num})")
            else:
                error = result.get('error', 'unknown error')
                print(f"  ✗ Failed: {error}")

    print(f"\n✓ Crystal sync complete for {entity}!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Sync archived crystals to Tech RAG for semantic search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 sync_crystal_rag.py --entity lyra
  python3 sync_crystal_rag.py --entity lyra --dry-run
  python3 sync_crystal_rag.py --entity nexus
        """
    )

    parser.add_argument(
        '--entity',
        required=True,
        help='Entity name (e.g., lyra, nexus)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be ingested without doing it'
    )

    args = parser.parse_args()

    asyncio.run(sync_crystal_rag(entity=args.entity, dry_run=args.dry_run))
