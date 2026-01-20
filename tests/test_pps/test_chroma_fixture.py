"""
Test ChromaDB test fixture.

Demonstrates usage of the chroma_client and tech_rag_test_instance fixtures
from conftest.py.

Issue #104: https://github.com/JDHayesBC/Awareness/issues/104
"""

import pytest


def test_chroma_client_fixture(chroma_client):
    """
    Test that the chroma_client fixture provides a working ChromaDB instance.

    This is the low-level fixture - use directly when you need custom ChromaDB
    setup. For TechRAG tests, prefer the tech_rag_test_instance fixture.
    """
    # Create a test collection
    collection = chroma_client.get_or_create_collection("test_collection")

    # Add some documents
    collection.add(
        documents=["This is a test document", "This is another test"],
        ids=["doc1", "doc2"],
        metadatas=[{"source": "test"}, {"source": "test"}]
    )

    # Query
    results = collection.query(
        query_texts=["test document"],
        n_results=2
    )

    # Verify
    assert len(results["ids"][0]) == 2
    assert "doc1" in results["ids"][0]
    assert "doc2" in results["ids"][0]


@pytest.mark.asyncio
async def test_tech_rag_fixture(tech_rag_test_instance):
    """
    Test that the tech_rag_test_instance fixture provides a working TechRAG layer.

    This is the high-level fixture - use for most TechRAG tests.
    Provides a fully configured TechRAGLayer with in-memory ChromaDB.
    """
    layer = tech_rag_test_instance

    # Create a test document
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("""# Test Document

## Section One
This is test content.

## Section Two
More test content here.
""")
        temp_path = Path(f.name)

    try:
        # Ingest the document
        result = await layer.ingest(str(temp_path), category="test")

        # Verify
        assert result["success"] == True
        assert result["action"] == "indexed"
        assert result["chunks"] > 0

        # Search for content
        search_results = await layer.search("test content", limit=2)

        assert search_results["success"] == True
        assert len(search_results["results"]) > 0

    finally:
        # Cleanup
        temp_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_fixture_isolation(tech_rag_test_instance):
    """
    Test that fixtures provide clean isolation between tests.

    Each test should start with an empty ChromaDB instance.
    """
    layer = tech_rag_test_instance

    # List all documents - should be empty initially
    list_result = await layer.list_docs()

    assert list_result["success"] == True
    assert len(list_result["documents"]) == 0, "ChromaDB should be empty at test start"
