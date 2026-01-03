"""
Pytest configuration and shared fixtures for Awareness project tests.

This file is automatically loaded by pytest and provides:
- Common fixtures for database connections
- Test environment setup
- Mock configurations for external services
"""

import pytest
import os
from pathlib import Path

# Test data directory
TEST_DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def test_data_dir():
    """Return path to test data directory."""
    return TEST_DATA_DIR


@pytest.fixture
def mock_claude_home(tmp_path):
    """Create a temporary CLAUDE_HOME structure for testing."""
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()

    # Create subdirectories
    (claude_home / "memories").mkdir()
    (claude_home / "data").mkdir()
    (claude_home / "crystals" / "current").mkdir(parents=True)
    (claude_home / "crystals" / "archive").mkdir()

    # Set environment variable
    os.environ["CLAUDE_HOME"] = str(claude_home)

    yield claude_home

    # Cleanup
    del os.environ["CLAUDE_HOME"]


# TODO: Add fixtures for:
# - ChromaDB test client
# - SQLite test database
# - Graphiti mock client
# - MCP server test client
