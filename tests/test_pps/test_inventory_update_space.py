"""
Tests for InventoryLayer.update_space() method.

Covers:
- Basic single-field update
- Multi-field update
- Space not found (returns False)
- No-op when no fields provided (space exists, returns True)
- Persistence (get_space after update reflects changes)
- visit_count not reset by update
- add_space + update_space round-trip
"""

import pytest
import asyncio
from pathlib import Path

from pps.layers.inventory import InventoryLayer


@pytest.fixture
def inventory(tmp_path):
    """InventoryLayer backed by a temp SQLite database."""
    db_path = tmp_path / "test_inventory.db"
    return InventoryLayer(db_path=db_path)


@pytest.fixture
def event_loop():
    """Provide a fresh event loop per test."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def run(coro, loop):
    """Helper: run async coroutine synchronously."""
    return loop.run_until_complete(coro)


class TestUpdateSpaceBasic:
    """Basic update_space functionality."""

    def test_update_description_only(self, inventory, event_loop):
        """Updating description leaves other fields unchanged."""
        run(inventory.add_space("kitchen", description="Old desc", emotional_quality="warm"), event_loop)

        result = run(inventory.update_space("kitchen", description="New desc"), event_loop)

        assert result is True
        space = run(inventory.get_space("kitchen"), event_loop)
        assert space["description"] == "New desc"
        assert space["emotional_quality"] == "warm"  # unchanged

    def test_update_emotional_quality_only(self, inventory, event_loop):
        """Updating emotional_quality leaves description unchanged."""
        run(inventory.add_space("bedroom", description="Cozy space", emotional_quality="peaceful"), event_loop)

        result = run(inventory.update_space("bedroom", emotional_quality="restful"), event_loop)

        assert result is True
        space = run(inventory.get_space("bedroom"), event_loop)
        assert space["emotional_quality"] == "restful"
        assert space["description"] == "Cozy space"  # unchanged

    def test_update_file_path_only(self, inventory, event_loop):
        """Updating file_path leaves description and emotional_quality unchanged."""
        run(inventory.add_space("study", description="Work space", file_path="/old/path.md"), event_loop)

        result = run(inventory.update_space("study", file_path="/new/path.md"), event_loop)

        assert result is True
        space = run(inventory.get_space("study"), event_loop)
        assert space["file_path"] == "/new/path.md"
        assert space["description"] == "Work space"  # unchanged


class TestUpdateSpaceMultiField:
    """Update multiple fields in one call."""

    def test_update_description_and_emotional_quality(self, inventory, event_loop):
        """Both fields update; file_path is untouched."""
        run(inventory.add_space(
            "porch",
            description="Old porch",
            file_path="/porch.md",
            emotional_quality="breezy",
        ), event_loop)

        result = run(inventory.update_space(
            "porch",
            description="Updated porch",
            emotional_quality="peaceful",
        ), event_loop)

        assert result is True
        space = run(inventory.get_space("porch"), event_loop)
        assert space["description"] == "Updated porch"
        assert space["emotional_quality"] == "peaceful"
        assert space["file_path"] == "/porch.md"  # unchanged

    def test_update_all_fields(self, inventory, event_loop):
        """Updating all three fields at once works correctly."""
        run(inventory.add_space(
            "attic",
            description="Dusty attic",
            file_path="/old_attic.md",
            emotional_quality="musty",
        ), event_loop)

        result = run(inventory.update_space(
            "attic",
            description="Clean attic",
            file_path="/new_attic.md",
            emotional_quality="airy",
        ), event_loop)

        assert result is True
        space = run(inventory.get_space("attic"), event_loop)
        assert space["description"] == "Clean attic"
        assert space["file_path"] == "/new_attic.md"
        assert space["emotional_quality"] == "airy"


class TestUpdateSpaceNotFound:
    """Fail-loud behaviour when space doesn't exist."""

    def test_nonexistent_space_returns_false(self, inventory, event_loop):
        """update_space returns False for a space that doesn't exist."""
        result = run(inventory.update_space("ghost_room", description="Won't work"), event_loop)
        assert result is False

    def test_nonexistent_space_does_not_create(self, inventory, event_loop):
        """update_space must not silently create a new space."""
        run(inventory.update_space("phantom", description="Should not appear"), event_loop)
        space = run(inventory.get_space("phantom"), event_loop)
        assert space is None


class TestUpdateSpaceNoFields:
    """Validation: at least one field must be provided."""

    def test_no_fields_raises_value_error(self, inventory, event_loop):
        """Calling update_space with no update fields raises ValueError."""
        run(inventory.add_space("hall", description="Entry hall"), event_loop)

        with pytest.raises(ValueError, match="at least one field"):
            run(inventory.update_space("hall"), event_loop)

    def test_no_fields_on_nonexistent_space_also_raises(self, inventory, event_loop):
        """ValueError is raised before existence check — validation is first."""
        with pytest.raises(ValueError):
            run(inventory.update_space("ghost_room"), event_loop)


class TestUpdateSpacePersistence:
    """Changes survive get_space round-trip."""

    def test_update_persists_across_get(self, inventory, event_loop):
        """After update, get_space reflects the new values."""
        run(inventory.add_space("den", description="Before"), event_loop)
        run(inventory.update_space("den", description="After"), event_loop)

        space = run(inventory.get_space("den"), event_loop)
        assert space["description"] == "After"


class TestUpdateSpaceVisitCount:
    """update_space must not touch visit_count."""

    def test_update_does_not_reset_visit_count(self, inventory, event_loop):
        """visit_count accumulated via get_space/enter_space is not reset by update."""
        run(inventory.add_space("garden", description="Outdoor"), event_loop)
        # Trigger visit count increments via get_space (which bumps visit_count)
        run(inventory.get_space("garden"), event_loop)
        run(inventory.get_space("garden"), event_loop)

        space_before = run(inventory.get_space("garden"), event_loop)
        count_before = space_before["visit_count"]

        run(inventory.update_space("garden", description="Updated outdoor"), event_loop)

        space_after = run(inventory.get_space("garden"), event_loop)
        # visit_count will be incremented by the get_space call above, not by update
        assert space_after["visit_count"] == count_before + 1


class TestUpdateSpaceRoundTrip:
    """add_space + update_space interaction tests."""

    def test_add_then_update_then_verify(self, inventory, event_loop):
        """Full round-trip: add -> update -> list_spaces shows updated values."""
        run(inventory.add_space("pantry", description="Storage", emotional_quality="calm"), event_loop)
        run(inventory.update_space("pantry", description="Food storage", emotional_quality="organized"), event_loop)

        spaces = run(inventory.list_spaces(), event_loop)
        pantry = next((s for s in spaces if s["name"] == "pantry"), None)

        assert pantry is not None
        assert pantry["description"] == "Food storage"
        assert pantry["emotional_quality"] == "organized"

    def test_multiple_spaces_update_only_target(self, inventory, event_loop):
        """Updating one space does not affect sibling spaces."""
        run(inventory.add_space("room_a", description="Room A"), event_loop)
        run(inventory.add_space("room_b", description="Room B"), event_loop)

        run(inventory.update_space("room_a", description="Room A updated"), event_loop)

        room_b = run(inventory.get_space("room_b"), event_loop)
        assert room_b["description"] == "Room B"  # untouched
