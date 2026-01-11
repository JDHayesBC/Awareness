"""
Test Tech RAG re-ingestion behavior.

Tests that re-ingesting a document with changed content properly deletes
old chunks before adding new ones.

Issue #89: https://github.com/JDHayesBC/Awareness/issues/89
"""

import pytest
import tempfile
from pathlib import Path
from pps.layers.tech_rag import TechRAGLayer


@pytest.fixture
async def tech_rag():
    """Create a TechRAG instance pointed at test ChromaDB."""
    # Use test ChromaDB instance (assumes conftest.py sets this up)
    with tempfile.TemporaryDirectory() as tmpdir:
        tech_rag = TechRAGLayer(
            tech_docs_path=Path(tmpdir) / "tech_docs",
            chroma_host="localhost",
            chroma_port=8000
        )
        yield tech_rag

        # Cleanup: delete any test documents
        try:
            await tech_rag.delete_doc("test_doc_reingest")
        except:
            pass


@pytest.mark.asyncio
async def test_reingest_deletes_old_chunks(tech_rag):
    """
    Test that re-ingesting a modified document deletes old chunks.

    Steps:
    1. Ingest initial version of document
    2. Verify chunks are created
    3. Modify document content
    4. Re-ingest modified document
    5. Verify old chunks are gone and new chunks exist
    """
    # Create initial document
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("""# Test Document

## Section One
This is the original content of section one.
It has some text that will be indexed.

## Section Two
This is the original content of section two.
More text to be indexed here.
""")
        temp_path = Path(f.name)

    try:
        # Ingest initial version
        result1 = await tech_rag.ingest(str(temp_path), category="test")

        assert result1["success"] == True
        assert result1["action"] == "indexed"
        initial_chunks = result1["chunks"]
        assert initial_chunks > 0

        # Verify initial chunks exist in ChromaDB
        collection = tech_rag._get_collection()
        initial_items = collection.get(
            where={"doc_id": temp_path.stem},
            include=["documents", "metadatas"]
        )
        assert len(initial_items["ids"]) == initial_chunks

        # Get initial content for comparison
        initial_contents = set(initial_items["documents"])

        # Modify the document significantly
        temp_path.write_text("""# Test Document - UPDATED

## Section One REVISED
This is completely new content for section one.
The old content is gone and replaced with this.

## Section Three - NEW
This is a brand new section that wasn't in the original.
It should create new chunks.

## Section Four - ALSO NEW
Another new section with different content.
More new text here.
""")

        # Re-ingest modified version
        result2 = await tech_rag.ingest(str(temp_path), category="test")

        assert result2["success"] == True
        assert result2["action"] == "indexed"  # Should be indexed, not unchanged
        new_chunks = result2["chunks"]

        # Verify new chunks exist
        new_items = collection.get(
            where={"doc_id": temp_path.stem},
            include=["documents", "metadatas"]
        )
        assert len(new_items["ids"]) == new_chunks

        # Get new content
        new_contents = set(new_items["documents"])

        # CRITICAL: Old content should NOT be in new chunks
        # If old chunks weren't deleted, old content would still be present
        overlap = initial_contents & new_contents
        assert len(overlap) == 0, f"Found {len(overlap)} chunks with old content that should have been deleted"

        # Verify new content is present
        new_text = "brand new section"
        found_new_content = any(new_text.lower() in doc.lower() for doc in new_contents)
        assert found_new_content, "New content not found in re-indexed chunks"

        # Verify old content is gone
        old_text = "original content"
        found_old_content = any(old_text.lower() in doc.lower() for doc in new_contents)
        assert not found_old_content, "Old content still present after re-ingestion"

    finally:
        # Cleanup
        temp_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_reingest_unchanged_skips(tech_rag):
    """
    Test that re-ingesting an unchanged document skips re-indexing.

    Should detect same content hash and return "unchanged" action.
    """
    # Create document
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("""# Test Document

## Section
Some content here.
""")
        temp_path = Path(f.name)

    try:
        # Initial ingest
        result1 = await tech_rag.ingest(str(temp_path), category="test")
        assert result1["success"] == True
        assert result1["action"] == "indexed"

        # Re-ingest without changes
        result2 = await tech_rag.ingest(str(temp_path), category="test")
        assert result2["success"] == True
        assert result2["action"] == "unchanged"
        assert "already indexed" in result2["message"].lower()

    finally:
        temp_path.unlink(missing_ok=True)
        await tech_rag.delete_doc(temp_path.stem)
