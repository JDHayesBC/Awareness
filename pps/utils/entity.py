"""Entity name utilities for multi-entity PPS."""
import os
from pathlib import Path


def get_entity_name() -> str:
    """
    Get entity name. Prefers ENTITY_NAME env var, falls back to ENTITY_PATH directory name.

    In Docker, ENTITY_PATH is always /app/entity (mount point), so ENTITY_NAME
    env var is required to distinguish entities. Outside Docker, ENTITY_PATH.name works.

    Returns:
        Entity name (lowercase), or "default" if neither env var is set.

    Examples:
        ENTITY_NAME=lyra -> "lyra"
        ENTITY_NAME not set, ENTITY_PATH=/path/to/entities/caia -> "caia"
        Neither set -> "default"
    """
    entity_name = os.getenv("ENTITY_NAME", "")
    if entity_name:
        return entity_name.lower()
    entity_path = os.getenv("ENTITY_PATH", "")
    if entity_path:
        return Path(entity_path).name.lower()
    return "default"


def get_db_filename() -> str:
    """
    Get entity-specific database filename.

    Returns generic filename used by all entities.
    The database lives in ENTITY_PATH/data/{filename}.
    """
    return "conversations.db"
