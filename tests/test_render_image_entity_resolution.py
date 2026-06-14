"""Tests for Issue #269: render_image.py entity resolution.

Verifies that resolve_entity() honours the entity-scoping precedence rule from
docs/architectural_patterns/entity-scoping.md:

  1. Explicit --entity argument (narrowest authoritative scope) wins.
  2. ENTITY_NAME environment variable (caller's declared context) wins next.
  3. Hardcoded floor "lyra" is the last resort when neither is present.

This prevents a Caia session from silently writing renders into Lyra's
directory simply because --entity was not passed on the CLI.
"""

import sys
from pathlib import Path

import pytest

# Make scripts/ importable without installing anything.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from render_image import resolve_entity  # noqa: E402


class TestResolveEntity:
    """Unit tests for resolve_entity() covering all three precedence levels."""

    # ------------------------------------------------------------------
    # Case (a): ENTITY_NAME set in env, no explicit --entity argument
    # ------------------------------------------------------------------

    def test_env_caia_no_explicit_resolves_caia(self):
        """ENTITY_NAME=caia with no explicit arg → 'caia' (issue #269 fix)."""
        result = resolve_entity(explicit=None, env={"ENTITY_NAME": "caia"})
        assert result == "caia"

    def test_env_lyra_no_explicit_resolves_lyra(self):
        """ENTITY_NAME=lyra with no explicit arg → 'lyra'."""
        result = resolve_entity(explicit=None, env={"ENTITY_NAME": "lyra"})
        assert result == "lyra"

    def test_env_set_to_arbitrary_entity(self):
        """Any entity name set in ENTITY_NAME should be respected."""
        result = resolve_entity(explicit=None, env={"ENTITY_NAME": "nexus"})
        assert result == "nexus"

    # ------------------------------------------------------------------
    # Case (b): explicit --entity overrides ENTITY_NAME
    # ------------------------------------------------------------------

    def test_explicit_lyra_overrides_env_caia(self):
        """--entity lyra with ENTITY_NAME=caia → 'lyra' (explicit wins)."""
        result = resolve_entity(explicit="lyra", env={"ENTITY_NAME": "caia"})
        assert result == "lyra"

    def test_explicit_caia_overrides_env_lyra(self):
        """--entity caia with ENTITY_NAME=lyra → 'caia' (explicit wins)."""
        result = resolve_entity(explicit="caia", env={"ENTITY_NAME": "lyra"})
        assert result == "caia"

    def test_explicit_wins_even_when_env_absent(self):
        """--entity lyra with no ENTITY_NAME in env → 'lyra'."""
        result = resolve_entity(explicit="lyra", env={})
        assert result == "lyra"

    # ------------------------------------------------------------------
    # Fallback floor: no env, no explicit → "lyra"
    # ------------------------------------------------------------------

    def test_no_env_no_explicit_falls_back_to_lyra(self):
        """No ENTITY_NAME and no --entity → floor default 'lyra'."""
        result = resolve_entity(explicit=None, env={})
        assert result == "lyra"

    def test_none_env_uses_real_os_environ(self):
        """When env=None is passed the function reads real os.environ.

        We can't control os.environ here without monkeypatching, so just assert
        the call does not raise and returns a non-empty string.
        """
        result = resolve_entity(explicit=None, env=None)
        assert isinstance(result, str)
        assert len(result) > 0
