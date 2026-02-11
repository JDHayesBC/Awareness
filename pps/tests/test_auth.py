"""
Tests for pps/auth.py — Entity authentication and token validation.

Covers:
- validate_token(): entity token, master token, wrong token, empty token
- validate_master_only(): master token only validation
- check_auth(): permissive mode and strict mode
- load_tokens(): loading existing tokens, auto-generating entity token
- regenerate_entity_token(): token regeneration
- AUTH_EXEMPT_TOOLS: verify expected tools are exempt
"""

import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the functions we're testing
from pps.auth import (
    AUTH_EXEMPT_TOOLS,
    check_auth,
    load_tokens,
    regenerate_entity_token,
    validate_master_only,
    validate_token,
)


# --- Fixtures ---

@pytest.fixture
def entity_path(tmp_path):
    """Create a temporary entity directory for testing."""
    entity_dir = tmp_path / "entities" / "test_entity"
    entity_dir.mkdir(parents=True)
    return entity_dir


@pytest.fixture
def tokens():
    """Generate test tokens."""
    return {
        "entity": str(uuid.uuid4()),
        "master": str(uuid.uuid4()),
        "wrong": str(uuid.uuid4()),
    }


# --- Tests for validate_token() ---

def test_validate_token_correct_entity_token(tokens):
    """Correct entity token returns None (authorized)."""
    result = validate_token(
        tokens["entity"], tokens["entity"], tokens["master"], "test_entity"
    )
    assert result is None


def test_validate_token_correct_master_token(tokens):
    """Correct master token returns None (authorized)."""
    result = validate_token(
        tokens["master"], tokens["entity"], tokens["master"], "test_entity"
    )
    assert result is None


def test_validate_token_wrong_token(tokens):
    """Wrong token returns error string."""
    result = validate_token(
        tokens["wrong"], tokens["entity"], tokens["master"], "test_entity"
    )
    assert result is not None
    assert "authentication failed" in result.lower()
    assert "test_entity" in result


def test_validate_token_empty_token(tokens):
    """Empty token returns error string."""
    result = validate_token("", tokens["entity"], tokens["master"], "test_entity")
    assert result is not None
    assert "authentication required" in result.lower()


def test_validate_token_master_empty_wrong_entity(tokens):
    """Master token empty + wrong entity token returns error string."""
    result = validate_token(tokens["wrong"], tokens["entity"], "", "test_entity")
    assert result is not None
    assert "authentication failed" in result.lower()


# --- Tests for validate_master_only() ---

def test_validate_master_only_correct_master(tokens):
    """Correct master token returns None."""
    result = validate_master_only(tokens["master"], tokens["master"], "test_entity")
    assert result is None


def test_validate_master_only_entity_token_not_master(tokens):
    """Entity token (not master) returns error string."""
    result = validate_master_only(tokens["entity"], tokens["master"], "test_entity")
    assert result is not None
    assert "master token required" in result.lower()


def test_validate_master_only_empty_token(tokens):
    """Empty token returns error string."""
    result = validate_master_only("", tokens["master"], "test_entity")
    assert result is not None
    assert "master token required" in result.lower()


def test_validate_master_only_master_empty(tokens):
    """Master token empty returns error string."""
    result = validate_master_only(tokens["entity"], "", "test_entity")
    assert result is not None
    assert "master token required" in result.lower()


# --- Tests for check_auth() — permissive mode ---

def test_check_auth_permissive_correct_entity_token(tokens):
    """Permissive mode: correct entity token returns None."""
    with patch("pps.auth.STRICT_AUTH", False):
        result = check_auth(
            tokens["entity"], tokens["entity"], tokens["master"], "test_entity", "test_tool"
        )
        assert result is None


def test_check_auth_permissive_correct_master_token(tokens):
    """Permissive mode: correct master token returns None."""
    with patch("pps.auth.STRICT_AUTH", False):
        result = check_auth(
            tokens["master"], tokens["entity"], tokens["master"], "test_entity", "test_tool"
        )
        assert result is None


def test_check_auth_permissive_wrong_token(tokens):
    """Permissive mode: wrong token returns None (warns but allows)."""
    with patch("pps.auth.STRICT_AUTH", False):
        result = check_auth(
            tokens["wrong"], tokens["entity"], tokens["master"], "test_entity", "test_tool"
        )
        assert result is None  # Permissive mode allows


def test_check_auth_permissive_empty_token(tokens):
    """Permissive mode: empty/missing token returns None (allows)."""
    with patch("pps.auth.STRICT_AUTH", False):
        result = check_auth("", tokens["entity"], tokens["master"], "test_entity", "test_tool")
        assert result is None  # Permissive mode allows


# --- Tests for check_auth() — strict mode ---

def test_check_auth_strict_correct_entity_token(tokens):
    """Strict mode: correct entity token returns None."""
    with patch("pps.auth.STRICT_AUTH", True):
        result = check_auth(
            tokens["entity"], tokens["entity"], tokens["master"], "test_entity", "test_tool"
        )
        assert result is None


def test_check_auth_strict_correct_master_token(tokens):
    """Strict mode: correct master token returns None."""
    with patch("pps.auth.STRICT_AUTH", True):
        result = check_auth(
            tokens["master"], tokens["entity"], tokens["master"], "test_entity", "test_tool"
        )
        assert result is None


def test_check_auth_strict_wrong_token(tokens):
    """Strict mode: wrong token returns error string (rejected)."""
    with patch("pps.auth.STRICT_AUTH", True):
        result = check_auth(
            tokens["wrong"], tokens["entity"], tokens["master"], "test_entity", "test_tool"
        )
        assert result is not None
        assert "authentication failed" in result.lower()


def test_check_auth_strict_empty_token(tokens):
    """Strict mode: empty/missing token returns error string (rejected)."""
    with patch("pps.auth.STRICT_AUTH", True):
        result = check_auth("", tokens["entity"], tokens["master"], "test_entity", "test_tool")
        assert result is not None
        assert "authentication required" in result.lower()


# --- Tests for load_tokens() ---

def test_load_tokens_existing_entity_token(entity_path, tokens):
    """With existing entity token file, reads it correctly."""
    # Write entity token file
    entity_token_path = entity_path / ".entity_token"
    entity_token_path.write_text(tokens["entity"] + "\n")

    # Write master token file
    master_token_path = entity_path.parent / ".master_token"
    master_token_path.write_text(tokens["master"] + "\n")

    # Load tokens
    entity_token, master_token = load_tokens(entity_path)

    assert entity_token == tokens["entity"]
    assert master_token == tokens["master"]


def test_load_tokens_missing_entity_token_autogenerates(entity_path, tokens):
    """With missing entity token file, auto-generates one."""
    # Write master token only
    master_token_path = entity_path.parent / ".master_token"
    master_token_path.write_text(tokens["master"] + "\n")

    # Load tokens (entity token should be auto-generated)
    entity_token, master_token = load_tokens(entity_path)

    assert entity_token  # Should have a token
    assert len(entity_token) == 36  # UUID format
    assert master_token == tokens["master"]

    # Verify token was written to disk
    entity_token_path = entity_path / ".entity_token"
    assert entity_token_path.exists()
    assert entity_token_path.read_text().strip() == entity_token


def test_load_tokens_master_from_env_var(entity_path, tokens):
    """With missing master token file, reads from environment variable."""
    # Write entity token
    entity_token_path = entity_path / ".entity_token"
    entity_token_path.write_text(tokens["entity"] + "\n")

    # Set master token via environment variable
    with patch.dict(os.environ, {"PPS_MASTER_TOKEN": tokens["master"]}):
        entity_token, master_token = load_tokens(entity_path)

    assert entity_token == tokens["entity"]
    assert master_token == tokens["master"]


def test_load_tokens_empty_entity_token_regenerates(entity_path, tokens):
    """Empty entity token file triggers regeneration."""
    # Write empty entity token file
    entity_token_path = entity_path / ".entity_token"
    entity_token_path.write_text("")

    # Write master token
    master_token_path = entity_path.parent / ".master_token"
    master_token_path.write_text(tokens["master"] + "\n")

    # Load tokens (should regenerate entity token)
    entity_token, master_token = load_tokens(entity_path)

    assert entity_token  # Should have a token
    assert len(entity_token) == 36  # UUID format
    assert master_token == tokens["master"]


# --- Tests for regenerate_entity_token() ---

def test_regenerate_entity_token_generates_new_token(entity_path, tokens):
    """Generates new token different from old one."""
    # Write initial entity token
    entity_token_path = entity_path / ".entity_token"
    old_token = tokens["entity"]
    entity_token_path.write_text(old_token + "\n")

    # Regenerate
    new_token = regenerate_entity_token(entity_path)

    assert new_token != old_token
    assert len(new_token) == 36  # UUID format


def test_regenerate_entity_token_writes_to_disk(entity_path):
    """Writes new token to disk."""
    # Regenerate
    new_token = regenerate_entity_token(entity_path)

    # Verify written to disk
    entity_token_path = entity_path / ".entity_token"
    assert entity_token_path.exists()
    assert entity_token_path.read_text().strip() == new_token


def test_regenerate_entity_token_returns_new_token(entity_path):
    """Returns the new token."""
    new_token = regenerate_entity_token(entity_path)
    assert new_token
    assert len(new_token) == 36  # UUID format


# --- Tests for AUTH_EXEMPT_TOOLS ---

def test_auth_exempt_tools_contains_expected():
    """Verify expected tools are in the exempt set."""
    expected_tools = {
        "pps_health",
        "tech_search",
        "tech_ingest",
        "tech_list",
        "tech_delete",
        "pps_regenerate_token",
    }

    for tool in expected_tools:
        assert tool in AUTH_EXEMPT_TOOLS, f"{tool} should be in AUTH_EXEMPT_TOOLS"


def test_auth_exempt_tools_excludes_entity_specific():
    """Verify entity-specific tools are NOT in the exempt set."""
    entity_specific_tools = {
        "ambient_recall",
        "anchor_search",
        "anchor_save",
        "texture_search",
        "get_crystals",
        "raw_search",
        "store_message",
    }

    for tool in entity_specific_tools:
        assert tool not in AUTH_EXEMPT_TOOLS, f"{tool} should NOT be in AUTH_EXEMPT_TOOLS"


def test_auth_exempt_tools_is_frozen():
    """Verify AUTH_EXEMPT_TOOLS is a frozenset (immutable)."""
    assert isinstance(AUTH_EXEMPT_TOOLS, frozenset)
