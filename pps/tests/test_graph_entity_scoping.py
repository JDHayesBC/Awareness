"""
Tests for graph read entity-scoping fix (Issue #272).

Verifies that the graph read endpoints (explore, entities, synthesize) resolve
their Neo4j group_id from the REQUEST's entity_scope — not from the process-level
GRAPHITI_GROUP_ID — and that an unknown entity_scope raises a loud 422 error rather
than silently falling through to the ambient default.

Architecture ref: docs/architectural_patterns/entity-scoping.md
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry(mounted: str = "lyra", mounted_group: str = "lyra_v2") -> dict:
    """Build a minimal ENTITY_REGISTRY with Lyra (mounted) and Caia."""
    return {
        mounted: {
            "name": mounted,
            "display_name": mounted.capitalize(),
            "pps_url": "http://pps-lyra:8000",
            "mounted": True,
            "entity_path": None,
            "group_id": mounted_group,
        },
        "caia": {
            "name": "caia",
            "display_name": "Caia",
            "pps_url": "http://pps-caia:8000",
            "mounted": False,
            "entity_path": None,
            "group_id": "caia",
        },
    }


# ---------------------------------------------------------------------------
# Unit tests for resolve_graph_group_id
# ---------------------------------------------------------------------------

class TestResolveGraphGroupId:
    """Unit-level tests — no HTTP layer, no Neo4j."""

    def _import_resolver(self, registry: dict, default: str):
        """
        Import and monkey-patch resolve_graph_group_id in app module so we can
        test the resolution logic without standing up the full FastAPI app.
        """
        import importlib
        import pps.web.app as app_mod

        # Patch the module-level globals the resolver reads
        orig_registry = app_mod.ENTITY_REGISTRY
        orig_default = app_mod.DEFAULT_ENTITY
        app_mod.ENTITY_REGISTRY = registry
        app_mod.DEFAULT_ENTITY = default
        try:
            yield app_mod.resolve_graph_group_id
        finally:
            app_mod.ENTITY_REGISTRY = orig_registry
            app_mod.DEFAULT_ENTITY = orig_default

    def test_caia_scope_resolves_caia_group(self):
        """A caia-scoped request must resolve group_id='caia', NOT the lyra_v2 default."""
        import pps.web.app as app_mod
        from fastapi import HTTPException

        registry = _make_registry()
        orig_registry = app_mod.ENTITY_REGISTRY
        orig_default = app_mod.DEFAULT_ENTITY
        app_mod.ENTITY_REGISTRY = registry
        app_mod.DEFAULT_ENTITY = "lyra"
        try:
            result = app_mod.resolve_graph_group_id("caia")
            assert result == "caia", (
                f"Expected group_id 'caia' for entity_scope='caia', got '{result}'. "
                "This is the root cause of Issue #272 — Caia's graph view was querying "
                "the lyra_v2 partition instead of caia."
            )
        finally:
            app_mod.ENTITY_REGISTRY = orig_registry
            app_mod.DEFAULT_ENTITY = orig_default

    def test_lyra_scope_resolves_lyra_v2_group(self):
        """Lyra's scope must resolve to lyra_v2 (not the bare entity name 'lyra')."""
        import pps.web.app as app_mod

        registry = _make_registry()
        orig_registry = app_mod.ENTITY_REGISTRY
        orig_default = app_mod.DEFAULT_ENTITY
        app_mod.ENTITY_REGISTRY = registry
        app_mod.DEFAULT_ENTITY = "lyra"
        try:
            result = app_mod.resolve_graph_group_id("lyra")
            assert result == "lyra_v2", (
                f"Expected group_id 'lyra_v2' for entity_scope='lyra', got '{result}'. "
                "Lyra's active Neo4j partition is lyra_v2; using 'lyra' would be wrong."
            )
        finally:
            app_mod.ENTITY_REGISTRY = orig_registry
            app_mod.DEFAULT_ENTITY = orig_default

    def test_none_scope_falls_back_to_mounted_entity(self):
        """No entity_scope => fall back to the mounted entity's group (lyra_v2)."""
        import pps.web.app as app_mod

        registry = _make_registry()
        orig_registry = app_mod.ENTITY_REGISTRY
        orig_default = app_mod.DEFAULT_ENTITY
        app_mod.ENTITY_REGISTRY = registry
        app_mod.DEFAULT_ENTITY = "lyra"
        try:
            result = app_mod.resolve_graph_group_id(None)
            assert result == "lyra_v2", (
                f"Expected mounted entity fallback 'lyra_v2' for entity_scope=None, got '{result}'."
            )
        finally:
            app_mod.ENTITY_REGISTRY = orig_registry
            app_mod.DEFAULT_ENTITY = orig_default

    def test_unknown_scope_raises_422_not_silent_fallthrough(self):
        """An unrecognised entity_scope must raise HTTPException(422), never silently fall through."""
        import pps.web.app as app_mod
        from fastapi import HTTPException

        registry = _make_registry()
        orig_registry = app_mod.ENTITY_REGISTRY
        orig_default = app_mod.DEFAULT_ENTITY
        app_mod.ENTITY_REGISTRY = registry
        app_mod.DEFAULT_ENTITY = "lyra"
        try:
            with pytest.raises(HTTPException) as exc_info:
                app_mod.resolve_graph_group_id("unknown_entity_xyz")
            assert exc_info.value.status_code == 422, (
                "Unknown entity scope should raise HTTP 422 (Unprocessable Entity), not fall through."
            )
            assert "unknown_entity_xyz" in exc_info.value.detail.lower() or \
                   "unknown_entity_xyz" in str(exc_info.value.detail)
        finally:
            app_mod.ENTITY_REGISTRY = orig_registry
            app_mod.DEFAULT_ENTITY = orig_default

    def test_case_insensitive_scope(self):
        """entity_scope lookup must be case-insensitive ('Caia' == 'caia')."""
        import pps.web.app as app_mod

        registry = _make_registry()
        orig_registry = app_mod.ENTITY_REGISTRY
        orig_default = app_mod.DEFAULT_ENTITY
        app_mod.ENTITY_REGISTRY = registry
        app_mod.DEFAULT_ENTITY = "lyra"
        try:
            result = app_mod.resolve_graph_group_id("Caia")
            assert result == "caia"
        finally:
            app_mod.ENTITY_REGISTRY = orig_registry
            app_mod.DEFAULT_ENTITY = orig_default


# ---------------------------------------------------------------------------
# Registry build tests — verify group_id is captured from env
# ---------------------------------------------------------------------------

class TestEntityRegistryGroupId:
    """Verify that _build_entity_registry captures group_id correctly."""

    def test_mounted_entity_uses_graphiti_group_id_env(self):
        """Mounted entity's group_id must come from GRAPHITI_GROUP_ID, not entity name."""
        env_overrides = {
            "ENTITY_NAME": "lyra",
            "GRAPHITI_GROUP_ID": "lyra_v2",
            "PPS_SERVER_HOST": "pps-lyra",
            "PPS_SERVER_PORT": "8000",
            "ENTITY_PATH": "/app/entity",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            import importlib
            import pps.web.app as app_mod
            registry = app_mod._build_entity_registry()
            assert registry["lyra"]["group_id"] == "lyra_v2", (
                "Lyra's group_id should be 'lyra_v2' from GRAPHITI_GROUP_ID, not 'lyra'."
            )

    def test_caia_fallback_registration_uses_entity_caia_group_id(self):
        """Caia's fallback registry entry must read ENTITY_CAIA_GROUP_ID."""
        env_overrides = {
            "ENTITY_NAME": "lyra",
            "GRAPHITI_GROUP_ID": "lyra_v2",
            "PPS_SERVER_HOST": "pps-lyra",
            "PPS_SERVER_PORT": "8000",
            "ENTITY_PATH": "/app/entity",
            "ENTITY_CAIA_GROUP_ID": "caia",
            # No ENTITY_CAIA_PPS_URL so the fallback branch runs
        }
        # Remove ENTITY_CAIA_PPS_URL if present
        env_to_clear = {k: v for k, v in os.environ.items() if k == "ENTITY_CAIA_PPS_URL"}
        with patch.dict(os.environ, env_overrides, clear=False):
            for k in env_to_clear:
                os.environ.pop(k, None)
            import pps.web.app as app_mod
            registry = app_mod._build_entity_registry()
            assert "caia" in registry
            assert registry["caia"]["group_id"] == "caia", (
                "Caia's group_id should be 'caia' from ENTITY_CAIA_GROUP_ID."
            )

    def test_caia_fallback_defaults_to_caia_when_no_group_id_env(self):
        """Without ENTITY_CAIA_GROUP_ID, Caia's group_id defaults to 'caia' (name-based)."""
        env_overrides = {
            "ENTITY_NAME": "lyra",
            "GRAPHITI_GROUP_ID": "lyra_v2",
            "PPS_SERVER_HOST": "pps-lyra",
            "PPS_SERVER_PORT": "8000",
            "ENTITY_PATH": "/app/entity",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            os.environ.pop("ENTITY_CAIA_GROUP_ID", None)
            os.environ.pop("ENTITY_CAIA_PPS_URL", None)
            import pps.web.app as app_mod
            registry = app_mod._build_entity_registry()
            assert registry["caia"]["group_id"] == "caia"
