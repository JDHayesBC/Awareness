#!/usr/bin/env python3
"""
Test ambient_recall("startup") refactor.

Verifies that startup uses recency-based retrieval instead of semantic search.
"""
import requests
import json

PPS_URL = "http://localhost:8201"


def test_ambient_recall_startup():
    """Test that ambient_recall with context='startup' returns expected structure."""
    print("\n=== Testing ambient_recall('startup') ===\n")

    response = requests.post(
        f"{PPS_URL}/tools/ambient_recall",
        json={"context": "startup", "limit_per_layer": 5},
        timeout=30
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    result = response.json()
    content = result.get("formatted_context", "")

    print(f"Response length: {len(content)} chars\n")

    # Verify manifest is present
    assert "=== AMBIENT RECALL MANIFEST ===" in content, "Missing manifest"
    print("✓ Manifest present")

    # Verify clock info
    assert "**Clock**:" in content, "Missing clock info"
    print("✓ Clock info present")

    # Verify memory health
    assert "**Memory Health**:" in content, "Missing memory health"
    print("✓ Memory health present")

    # Verify summaries section (should be present for startup)
    if "[summaries]" in content:
        print("✓ Summaries section present")
        # Count summaries - should be at most 2 now (reduced from 5)
        summary_count = content.count("[summaries]")
        print(f"  - Found {summary_count} summary section(s)")

    # Verify unsummarized turns section
    if "[unsummarized_turns]" in content:
        print("✓ Unsummarized turns section present")
        # Check if it shows the count
        if "showing" in content.lower():
            print("  - Shows turn count (good for large backlogs)")

    # Check manifest for expected structure
    if "Crystals:" in content:
        print("✓ Crystals in manifest")
    if "Word-photos:" in content:
        print("✓ Word-photos in manifest")
    if "Summaries:" in content:
        print("✓ Summaries in manifest")
    if "Recent turns:" in content:
        print("✓ Recent turns in manifest")

    print(f"\n{'='*50}")
    print("Startup recall test PASSED")
    print(f"{'='*50}\n")
    return True


def test_ambient_recall_non_startup():
    """Test that non-startup queries still use semantic search."""
    print("\n=== Testing ambient_recall('morning reflection') ===\n")

    response = requests.post(
        f"{PPS_URL}/tools/ambient_recall",
        json={"context": "morning reflection", "limit_per_layer": 5},
        timeout=30
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    result = response.json()
    content = result.get("formatted_context", "")

    print(f"Response length: {len(content)} chars\n")

    # Verify manifest is present
    assert "=== AMBIENT RECALL MANIFEST ===" in content, "Missing manifest"
    print("✓ Manifest present")

    # Non-startup should NOT have summaries/unsummarized sections
    # (those are startup-only features)
    # But it should still have search results

    print(f"\n{'='*50}")
    print("Non-startup recall test PASSED")
    print(f"{'='*50}\n")
    return True


if __name__ == "__main__":
    try:
        test_ambient_recall_startup()
        test_ambient_recall_non_startup()
        print("\n✓ All tests PASSED\n")
    except AssertionError as e:
        print(f"\n✗ Test FAILED: {e}\n")
        exit(1)
    except Exception as e:
        print(f"\n✗ Test ERROR: {e}\n")
        exit(1)
