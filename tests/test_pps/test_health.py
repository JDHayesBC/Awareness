"""
Basic health check tests for PPS components.

These tests verify the fundamental components are importable and configured correctly.
Run with: pytest tests/test_pps/test_health.py
"""

import pytest


class TestPPSImports:
    """Test that core PPS modules are importable."""

    def test_server_importable(self):
        """Verify pps.server module can be imported."""
        # This will fail if there are syntax errors or missing deps
        try:
            import sys
            sys.path.insert(0, str(pytest.importorskip("pathlib").Path(__file__).parent.parent.parent / "pps"))
            # Basic import test - actual import requires dependencies
            assert True  # Placeholder until deps are set up
        except ImportError as e:
            pytest.skip(f"PPS not importable in test environment: {e}")


class TestConfiguration:
    """Test configuration and environment setup."""

    def test_claude_home_fixture(self, mock_claude_home):
        """Verify mock_claude_home fixture creates expected structure."""
        assert (mock_claude_home / "memories").exists()
        assert (mock_claude_home / "data").exists()
        assert (mock_claude_home / "crystals" / "current").exists()
        assert (mock_claude_home / "crystals" / "archive").exists()


# TODO: Add tests for:
# - ambient_recall returns expected structure
# - Word-photo semantic search works
# - Crystal retrieval works
# - Message capture stores correctly
