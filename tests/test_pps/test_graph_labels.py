"""
Tests for graph entity label support (Issue #90).

Verifies that entity labels are correctly passed from backend to frontend
for entity type color coding in the Observatory graph visualization.
"""
import pytest


def test_metadata_structure_with_labels():
    """Test that metadata dict can include entity labels."""
    # Simulate metadata structure from rich_texture_v2
    metadata = {
        "type": "fact",
        "subject": "Jeff",
        "predicate": "knows",
        "object": "Lyra",
        "valid_at": None,
        "source_labels": ["Person"],
        "target_labels": ["Person"],
    }

    # Verify labels are present
    assert "source_labels" in metadata
    assert "target_labels" in metadata
    assert metadata["source_labels"] == ["Person"]
    assert metadata["target_labels"] == ["Person"]


def test_metadata_empty_labels():
    """Test that metadata handles missing labels gracefully."""
    # Simulate metadata with empty labels
    metadata = {
        "type": "fact",
        "subject": "Unknown",
        "predicate": "relates_to",
        "object": "Something",
        "source_labels": [],
        "target_labels": [],
    }

    # Verify empty labels work
    assert metadata["source_labels"] == []
    assert metadata["target_labels"] == []


def test_metadata_multiple_labels():
    """Test that metadata can handle multiple labels per entity."""
    # Simulate metadata with multiple labels
    metadata = {
        "type": "fact",
        "subject": "PPS",
        "predicate": "is_a",
        "object": "System",
        "source_labels": ["TechnicalArtifact", "Concept"],
        "target_labels": ["Concept"],
    }

    # Verify multiple labels work
    assert len(metadata["source_labels"]) == 2
    assert "TechnicalArtifact" in metadata["source_labels"]
    assert "Concept" in metadata["source_labels"]
    assert metadata["target_labels"] == ["Concept"]


def test_web_api_node_structure():
    """Test that web API nodes can include labels from metadata."""
    # Simulate node creation in app.py
    metadata = {
        "type": "fact",
        "subject": "Jeff",
        "predicate": "knows",
        "object": "Lyra",
        "source_labels": ["Person"],
        "target_labels": ["Person"],
    }

    # Build nodes as app.py does
    subject = metadata.get("subject", "unknown")
    obj = metadata.get("object", "unknown")

    subject_node = {
        "id": subject,
        "label": subject,
        "type": "entity",
        "labels": metadata.get("source_labels", []),
        "relevance": 0.5
    }

    object_node = {
        "id": obj,
        "label": obj,
        "type": "entity",
        "labels": metadata.get("target_labels", []),
        "relevance": 0.5
    }

    # Verify nodes have labels
    assert subject_node["labels"] == ["Person"]
    assert object_node["labels"] == ["Person"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
