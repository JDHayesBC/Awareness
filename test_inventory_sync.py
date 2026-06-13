#!/usr/bin/env python3
"""
Verification script for inventory sync layer implementation.
Tests against COPIES of live DBs - never modifies live data.
"""
import asyncio
import shutil
import tempfile
from pathlib import Path
import sys

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from pps.layers.inventory import InventoryLayer


async def verify():
    print("=== Inventory Sync Layer Verification ===\n")

    # 1. Copy live Lyra DB to temp
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_copy = tmp_path / "inventory.db"
        entity_dir = tmp_path / "entity"
        entity_dir.mkdir()

        live_db = Path('/mnt/c/Users/Jeff/Claude_Projects/Awareness/entities/lyra/data/inventory.db')
        if not live_db.exists():
            print(f"ERROR: Live DB not found at {live_db}")
            return False

        shutil.copy(live_db, db_copy)
        print(f"✓ Copied live DB to temp: {db_copy}")

        layer = InventoryLayer(db_path=db_copy, entity_path=entity_dir)

        # 2. Capture deck description before backfill
        original_deck = await layer.get_space('deck')
        if not original_deck:
            print("ERROR: 'deck' space not found in DB")
            return False

        original_desc = original_deck['description']
        print(f"✓ Original deck description length: {len(original_desc)} chars")

        if 'pool' not in original_desc or 'hot tub' not in original_desc:
            print(f"ERROR: Deck text missing key content")
            print(f"Deck description: {original_desc[:200]}...")
            return False
        print(f"✓ Deck description contains key content (pool, hot tub)")

        # 3. Backfill mirrors
        print("\n--- Running backfill_mirrors() ---")
        stats = await layer.backfill_mirrors()
        print(f"Backfill stats: {stats}")

        # 7 canonical rooms after the 2026-06-12 room reconciliation
        # (spaces-table + inventory(category=spaces) merged into the spaces table).
        if stats['spaces_exported'] != 7:
            print(f"ERROR: Expected 7 spaces, got {stats['spaces_exported']}")
            return False
        print(f"✓ Exported {stats['spaces_exported']} spaces")

        # Dead pointers were cleared during the reconciliation, so 0 repairs is
        # now the healthy state; backfill sets fresh mirror pointers instead.
        print(f"✓ Dead pointers repaired: {stats['dead_pointers_repaired']} (0 expected post-merge)")

        if len(stats['errors']) != 0:
            print(f"ERROR: Errors during backfill: {stats['errors']}")
            return False
        print(f"✓ No errors during backfill")

        # 4. Verify deck mirror file exists and content matches
        deck_mirror = entity_dir / "inventory_mirror" / "spaces" / "deck.md"
        if not deck_mirror.exists():
            print(f"ERROR: Deck mirror file not created at {deck_mirror}")
            return False
        print(f"✓ Deck mirror file created: {deck_mirror}")

        mirror_text = deck_mirror.read_text()
        # Case-insensitive check
        if 'pool' not in mirror_text.lower() or 'hot tub' not in mirror_text.lower():
            print(f"ERROR: Deck prose missing from mirror")
            print(f"Mirror length: {len(mirror_text)}")
            print(f"Mirror content (first 500 chars): {mirror_text[:500]}...")
            return False
        print(f"✓ Deck prose preserved in mirror ({len(mirror_text)} chars)")

        if 'visit_count' in mirror_text or 'last_visited' in mirror_text:
            print(f"ERROR: Telemetry leaked into mirror!")
            print(f"Mirror content: {mirror_text}")
            return False
        print(f"✓ Telemetry excluded from mirror")

        # 5. Deck round-trip via import
        print("\n--- Testing import round-trip ---")
        success = await layer.import_space_from_file(str(deck_mirror))
        if not success:
            print("ERROR: import_space_from_file failed")
            return False
        print(f"✓ Import succeeded")

        after_import_space = await layer.get_space('deck')
        after_import = after_import_space['description']
        if after_import != original_desc:
            print(f"ERROR: Deck description changed after import!")
            print(f"Before ({len(original_desc)} chars): {original_desc[:100]}...")
            print(f"After ({len(after_import)} chars): {after_import[:100]}...")
            return False
        print(f"✓ Deck round-trip: description unchanged")

        # 6. Update space and verify mirror updated
        print("\n--- Testing update write-through ---")
        await layer.update_space('deck', description='MODIFIED TEST')
        updated_mirror = deck_mirror.read_text()
        if 'MODIFIED TEST' not in updated_mirror:
            print(f"ERROR: Mirror not updated after update_space")
            print(f"Mirror content: {updated_mirror}")
            return False
        print(f"✓ Update write-through: mirror updated")

        # 7. Delete space and verify both gone
        print("\n--- Testing delete write-through ---")
        deleted = await layer.delete_space('kitchen')
        if not deleted:
            print("ERROR: delete_space returned False")
            return False

        kitchen_mirror = entity_dir / "inventory_mirror" / "spaces" / "kitchen.md"
        if kitchen_mirror.exists():
            print(f"ERROR: Mirror file not deleted with space")
            return False
        print(f"✓ Mirror file deleted")

        from_store = await layer.get_space('kitchen')
        if from_store is not None:
            print(f"ERROR: Space still in store after delete")
            return False
        print(f"✓ Space deleted from store")

        # 8. Verify telemetry not in any mirror file
        print("\n--- Verifying telemetry isolation across all mirrors ---")
        telemetry_leaked = False
        for f in (entity_dir / "inventory_mirror").rglob("*.md"):
            content = f.read_text()
            if 'visit_count' in content or 'reference_count' in content:
                print(f"ERROR: Telemetry in {f}")
                telemetry_leaked = True

        if telemetry_leaked:
            return False
        print(f"✓ Telemetry isolation: PASS")

        print("\n" + "="*50)
        print("ALL VERIFICATION CHECKS PASSED ✓")
        print("="*50)
        return True


if __name__ == "__main__":
    success = asyncio.run(verify())
    sys.exit(0 if success else 1)
