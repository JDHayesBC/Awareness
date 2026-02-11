"""
PPS Entity Authentication

Per-call token validation for multi-entity memory isolation.
Prevents accidental cross-contamination between entity PPS instances.

Token types:
- Entity token: Lives in $ENTITY_PATH/.entity_token, proves "I am this entity"
- Master token: Lives in entities/.master_token, Jeff's emergency override

Migration strategy:
- Phase 1: token param is OPTIONAL, PPS_STRICT_AUTH=false (default) → warns but allows
- Phase 2: all callers updated to include tokens
- Phase 3: PPS_STRICT_AUTH=true → rejects calls without valid tokens

Usage:
    from pps.auth import load_tokens, check_auth, AUTH_EXEMPT_TOOLS

    ENTITY_TOKEN, MASTER_TOKEN = load_tokens(entity_path)

    # In tool handler (centralized check):
    if name not in AUTH_EXEMPT_TOOLS:
        auth_error = check_auth(arguments.get("token", ""), ENTITY_TOKEN, MASTER_TOKEN, entity_name, name)
        if auth_error:
            return [TextContent(type="text", text=auth_error)]
"""

import os
import sys
import uuid
from pathlib import Path


# Strict mode: when True, reject calls without valid tokens
# When False, log warnings but allow (migration period)
STRICT_AUTH = os.getenv("PPS_STRICT_AUTH", "false").lower() == "true"


# Tools that don't require authentication
# pps_health: read-only diagnostic, no entity data
# tech_*: shared family knowledge (Tech RAG), not entity-private
# pps_regenerate_token: has its own master-token-only auth
AUTH_EXEMPT_TOOLS = frozenset({
    "pps_health",
    "tech_search",
    "tech_ingest",
    "tech_list",
    "tech_delete",
    "pps_regenerate_token",
})


def load_tokens(entity_path: Path) -> tuple[str, str]:
    """
    Load entity token and master token.

    Entity token: $ENTITY_PATH/.entity_token (auto-generated if missing)
    Master token: $ENTITY_PATH/../../.master_token (entities/.master_token)

    Returns (entity_token, master_token). Master token may be empty if file missing.
    """
    # Entity token — auto-generate if not present
    entity_token_path = entity_path / ".entity_token"
    if entity_token_path.exists():
        entity_token = entity_token_path.read_text().strip()
        if entity_token:
            print(f"[PPS Auth] Entity token loaded for {entity_path.name}", file=sys.stderr)
        else:
            entity_token = _generate_token(entity_token_path, entity_path.name)
    else:
        entity_token = _generate_token(entity_token_path, entity_path.name)

    # Master token — from entities/.master_token (two levels up from entity dir)
    # Or from environment variable as fallback
    master_token = ""
    master_token_path = entity_path.parent / ".master_token"
    if master_token_path.exists():
        master_token = master_token_path.read_text().strip()
        if master_token:
            print(f"[PPS Auth] Master token loaded", file=sys.stderr)
    elif os.getenv("PPS_MASTER_TOKEN"):
        master_token = os.getenv("PPS_MASTER_TOKEN", "")
        print(f"[PPS Auth] Master token from environment", file=sys.stderr)

    if not master_token:
        print(f"[PPS Auth] WARNING: No master token found. Emergency recovery will not work.", file=sys.stderr)
        print(f"[PPS Auth] Expected at: {master_token_path}", file=sys.stderr)

    return entity_token, master_token


def validate_token(provided_token: str, entity_token: str, master_token: str, entity_name: str) -> str | None:
    """
    Validate a provided token against entity and master tokens.

    Returns None if authorized, or an error message string if rejected.
    """
    if not provided_token:
        return (
            f"Entity authentication required for {entity_name}'s PPS. "
            f"Include 'token' parameter with your entity token. "
            f"Read token from $ENTITY_PATH/.entity_token"
        )

    if provided_token == entity_token:
        return None  # Authorized — entity accessing own data

    if master_token and provided_token == master_token:
        return None  # Authorized — master override

    return (
        f"Entity authentication failed for {entity_name}'s PPS. "
        f"Provided token does not match. "
        f"Re-read your token from $ENTITY_PATH/.entity_token or use master token. "
        f"Hint: If this happens after compaction, re-read the token file."
    )


def validate_master_only(provided_token: str, master_token: str, entity_name: str) -> str | None:
    """
    Validate that a token is the master token (for privileged operations).

    Returns None if authorized, or an error message string if rejected.
    """
    if not provided_token:
        return (
            f"Master token required for this operation on {entity_name}'s PPS. "
            f"This is a privileged operation (token regeneration)."
        )

    if master_token and provided_token == master_token:
        return None  # Authorized

    return (
        f"Master token required. Provided token is not the master token. "
        f"Only Jeff's master token can regenerate entity tokens."
    )


def regenerate_entity_token(entity_path: Path) -> str:
    """
    Generate a new entity token and write it to disk.
    Old token is immediately invalidated.

    Returns the new token.
    """
    token_path = entity_path / ".entity_token"
    new_token = str(uuid.uuid4())
    token_path.write_text(new_token + "\n")
    print(f"[PPS Auth] Entity token REGENERATED for {entity_path.name}", file=sys.stderr)
    return new_token


def _generate_token(token_path: Path, entity_name: str) -> str:
    """Generate a new token and write to file."""
    new_token = str(uuid.uuid4())
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(new_token + "\n")
        print(f"[PPS Auth] Generated new entity token for {entity_name} at {token_path}", file=sys.stderr)
    except Exception as e:
        print(f"[PPS Auth] WARNING: Could not write token to {token_path}: {e}", file=sys.stderr)
        print(f"[PPS Auth] Token generated in-memory only (will not persist)", file=sys.stderr)
    return new_token


def check_auth(provided_token: str, entity_token: str, master_token: str,
               entity_name: str, tool_name: str) -> str | None:
    """
    Check authentication for a tool call, respecting strict mode.

    In strict mode: returns error message if token is missing or invalid.
    In permissive mode: logs warning but returns None (allows the call).

    This is the primary auth interface for tool handlers.
    """
    error = validate_token(provided_token, entity_token, master_token, entity_name)

    if error is None:
        return None  # Valid token

    if STRICT_AUTH:
        print(f"[PPS Auth] REJECTED: {tool_name} — {error}", file=sys.stderr)
        return error
    else:
        # Permissive mode — warn but allow
        if provided_token:
            # Wrong token is always suspicious, even in permissive mode
            print(f"[PPS Auth] WARNING: Invalid token for {tool_name} on {entity_name}'s PPS", file=sys.stderr)
        # Missing token is expected during migration — only log at debug level
        return None


# Token parameter schema — reusable in tool definitions (OPTIONAL during migration)
TOKEN_PARAM_SCHEMA = {
    "type": "string",
    "description": (
        "Entity authentication token. Read from $ENTITY_PATH/.entity_token at startup. "
        "Required for all entity-specific tools when PPS_STRICT_AUTH=true. "
        "Re-read file if lost after compaction."
    )
}
