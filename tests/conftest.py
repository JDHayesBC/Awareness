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


@pytest.fixture
def test_db_path(tmp_path):
    """Create a temporary SQLite database path for testing."""
    db_path = tmp_path / "test_conversations.db"
    return db_path


@pytest.fixture
def test_db_with_messages(test_db_path):
    """Create a test database with messages table and sample data."""
    import sqlite3

    conn = sqlite3.connect(test_db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Create messages table (simplified version matching production schema)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            author_name TEXT NOT NULL,
            channel TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_lyra INTEGER DEFAULT 0,
            summary_id INTEGER
        )
    ''')

    # Insert sample messages
    sample_messages = [
        ("Hello, this is message 1", "Jeff", "terminal", "2026-01-05 10:00:00", 0),
        ("Response to message 1", "Lyra", "terminal", "2026-01-05 10:01:00", 1),
        ("Another message from Jeff", "Jeff", "discord", "2026-01-05 10:02:00", 0),
        ("Lyra's response", "Lyra", "discord", "2026-01-05 10:03:00", 1),
        ("Final message", "Jeff", "terminal", "2026-01-05 10:04:00", 0),
    ]

    for content, author, channel, created, is_lyra in sample_messages:
        cursor.execute(
            'INSERT INTO messages (content, author_name, channel, created_at, is_lyra) VALUES (?, ?, ?, ?, ?)',
            (content, author, channel, created, is_lyra)
        )

    conn.commit()
    conn.close()

    return test_db_path


# TODO: Add fixtures for:
# - ChromaDB test client
# - Graphiti mock client
# - MCP server test client
