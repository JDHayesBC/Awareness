#!/usr/bin/env python3
"""
Test script to verify entity resolution fix in add_triplet_direct().

This tests that calling texture_add_triplet twice with the same entity name
results in ONE node being created, not two duplicates.
"""

import asyncio
import os
import sys
import pytest

# Add pps directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'pps'))

from pps.layers.rich_texture_v2 import RichTextureLayerV2


@pytest.mark.asyncio
async def test_entity_resolution():
    """Test that entities are reused instead of duplicated."""

    print("=" * 70)
    print("Testing Entity Resolution in add_triplet_direct()")
    print("=" * 70)

    # Initialize layer
    layer = RichTextureLayerV2()

    print("\n1. Adding first triplet: Jeff SPOUSE_OF Carol")
    result1 = await layer.add_triplet_direct(
        source="Jeff",
        relationship="SPOUSE_OF",
        target="Carol",
        fact="Jeff and Carol are married",
        source_type="Person",
        target_type="Person"
    )

    if not result1.get("success"):
        print(f"❌ First triplet failed: {result1.get('message')}")
        return False

    print(f"✓ Success: {result1['message']}")
    jeff_uuid_1 = result1['result']['source_uuid']
    carol_uuid_1 = result1['result']['target_uuid']
    print(f"  Jeff UUID: {jeff_uuid_1}")
    print(f"  Carol UUID: {carol_uuid_1}")

    print("\n2. Adding second triplet: Jeff PARENT_OF Sarah (reusing Jeff)")
    result2 = await layer.add_triplet_direct(
        source="Jeff",
        relationship="PARENT_OF",
        target="Sarah",
        fact="Jeff is Sarah's father",
        source_type="Person",
        target_type="Person"
    )

    if not result2.get("success"):
        print(f"❌ Second triplet failed: {result2.get('message')}")
        return False

    print(f"✓ Success: {result2['message']}")
    jeff_uuid_2 = result2['result']['source_uuid']
    sarah_uuid_1 = result2['result']['target_uuid']
    print(f"  Jeff UUID: {jeff_uuid_2}")
    print(f"  Sarah UUID: {sarah_uuid_1}")

    print("\n3. Adding third triplet: Carol PARENT_OF Sarah (reusing both)")
    result3 = await layer.add_triplet_direct(
        source="Carol",
        relationship="PARENT_OF",
        target="Sarah",
        fact="Carol is Sarah's mother",
        source_type="Person",
        target_type="Person"
    )

    if not result3.get("success"):
        print(f"❌ Third triplet failed: {result3.get('message')}")
        return False

    print(f"✓ Success: {result3['message']}")
    carol_uuid_2 = result3['result']['source_uuid']
    sarah_uuid_2 = result3['result']['target_uuid']
    print(f"  Carol UUID: {carol_uuid_2}")
    print(f"  Sarah UUID: {sarah_uuid_2}")

    # Verify entity reuse
    print("\n" + "=" * 70)
    print("VERIFICATION")
    print("=" * 70)

    all_passed = True

    if jeff_uuid_1 == jeff_uuid_2:
        print("✓ Jeff entity was REUSED (same UUID in both triplets)")
    else:
        print(f"❌ Jeff entity was DUPLICATED (uuid1: {jeff_uuid_1}, uuid2: {jeff_uuid_2})")
        all_passed = False

    if carol_uuid_1 == carol_uuid_2:
        print("✓ Carol entity was REUSED (same UUID in both triplets)")
    else:
        print(f"❌ Carol entity was DUPLICATED (uuid1: {carol_uuid_1}, uuid2: {carol_uuid_2})")
        all_passed = False

    if sarah_uuid_1 == sarah_uuid_2:
        print("✓ Sarah entity was REUSED (same UUID in both triplets)")
    else:
        print(f"❌ Sarah entity was DUPLICATED (uuid1: {sarah_uuid_1}, uuid2: {sarah_uuid_2})")
        all_passed = False

    # Clean up
    await layer.close()

    print("\n" + "=" * 70)
    if all_passed:
        print("✓ ALL TESTS PASSED - Entity resolution working correctly!")
    else:
        print("❌ TESTS FAILED - Entities are still being duplicated")
    print("=" * 70)

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(test_entity_resolution())
    sys.exit(0 if success else 1)
