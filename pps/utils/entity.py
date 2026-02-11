"""Entity name utilities for multi-entity PPS."""
import os
from pathlib import Path


def get_entity_name() -> str:
    """
    Extract entity name from ENTITY_PATH env var. Returns lowercase.

    Returns:
        Entity name (lowercase) from ENTITY_PATH directory name,
        or "default" if ENTITY_PATH is not set.

    Examples:
        ENTITY_PATH=/path/to/entities/lyra -> "lyra"
        ENTITY_PATH=/path/to/entities/caia -> "caia"
        ENTITY_PATH not set -> "default"
    """
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
