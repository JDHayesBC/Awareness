"""
Layer 5: Inventory

Categorical storage for possessions, spaces, and collections.
Answers "what do I have?" questions that semantic search can't.

Works WITH Graphiti (Layer 3), not instead of it:
- Inventory: "What swimwear do I have?" → ["black bikini"]
- Graphiti: "Tell me about the black bikini" → Rich context, first time in water

Two-step pattern enables both enumeration AND semantic depth.
"""

import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Literal

from . import PatternLayer, LayerType, SearchResult, LayerHealth


# Inventory categories
InventoryCategory = Literal[
    "clothing",    # Wardrobe items
    "spaces",      # Rooms, locations, environments
    "people",      # Known individuals
    "food",        # Pantry items, meals
    "artifacts",   # Technical items, files, daemons
    "symbols",     # Emotionally significant objects
]


class InventoryLayer(PatternLayer):
    """
    Layer 5: Inventory

    SQLite-based categorical storage for quick enumeration queries.
    Complements Graphiti's semantic search with list-based lookups.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the inventory layer.

        Args:
            db_path: Path to SQLite database. Defaults to CLAUDE_HOME/data/inventory.db
        """
        if db_path:
            self.db_path = Path(db_path)
        else:
            claude_home = Path(os.getenv("CLAUDE_HOME", str(Path.home() / ".claude")))
            self.db_path = claude_home / "data" / "inventory.db"

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    subcategory TEXT,
                    description TEXT,
                    attributes TEXT,  -- JSON
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_referenced TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reference_count INTEGER DEFAULT 1,
                    has_word_photo BOOLEAN DEFAULT FALSE,
                    graphiti_entity_id TEXT,  -- Link to Graphiti entity if exists
                    UNIQUE(name, category)
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_inventory_category
                ON inventory(category)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_inventory_subcategory
                ON inventory(category, subcategory)
            """)

            # Spaces table for room descriptions
            conn.execute("""
                CREATE TABLE IF NOT EXISTS spaces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    file_path TEXT,  -- Path to .md file if exists
                    emotional_quality TEXT,
                    last_visited TIMESTAMP,
                    visit_count INTEGER DEFAULT 0
                )
            """)

            conn.commit()

    @property
    def layer_type(self) -> LayerType:
        # Note: LayerType doesn't have INVENTORY yet, using RICH_TEXTURE as placeholder
        # TODO: Add INVENTORY to LayerType enum
        return LayerType.RICH_TEXTURE

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Search inventory by name (partial match).

        For categorical queries, use list_category() instead.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM inventory
                WHERE name LIKE ?
                ORDER BY reference_count DESC, last_referenced DESC
                LIMIT ?
            """, (f"%{query}%", limit))

            results = []
            for row in cursor.fetchall():
                results.append(SearchResult(
                    content=f"[{row['category']}] {row['name']}: {row['description'] or 'No description'}",
                    source=f"inventory:{row['id']}",
                    layer=self.layer_type,
                    relevance_score=0.8,
                    metadata={
                        "id": row['id'],
                        "name": row['name'],
                        "category": row['category'],
                        "subcategory": row['subcategory'],
                        "attributes": json.loads(row['attributes']) if row['attributes'] else {},
                        "has_word_photo": bool(row['has_word_photo']),
                    }
                ))

            return results

    async def store(self, content: str, metadata: Optional[dict] = None) -> bool:
        """
        Add item to inventory.

        Args:
            content: Item name
            metadata: Must include 'category', optionally 'subcategory', 'description', 'attributes'
        """
        if not metadata or 'category' not in metadata:
            return False

        return await self.add_item(
            name=content,
            category=metadata['category'],
            subcategory=metadata.get('subcategory'),
            description=metadata.get('description'),
            attributes=metadata.get('attributes'),
        )

    async def health(self) -> LayerHealth:
        """Check inventory layer health."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM inventory")
                count = cursor.fetchone()[0]

                cursor = conn.execute("SELECT COUNT(DISTINCT category) FROM inventory")
                categories = cursor.fetchone()[0]

                return LayerHealth(
                    available=True,
                    message=f"Inventory: {count} items in {categories} categories",
                    details={
                        "db_path": str(self.db_path),
                        "item_count": count,
                        "category_count": categories,
                    }
                )
        except Exception as e:
            return LayerHealth(
                available=False,
                message=f"Inventory error: {e}",
                details={"error": str(e)}
            )

    # === Inventory-specific methods ===

    async def add_item(
        self,
        name: str,
        category: str,
        subcategory: Optional[str] = None,
        description: Optional[str] = None,
        attributes: Optional[dict] = None,
        has_word_photo: bool = False,
    ) -> bool:
        """Add or update an inventory item."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO inventory (name, category, subcategory, description, attributes, has_word_photo)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name, category) DO UPDATE SET
                        subcategory = COALESCE(excluded.subcategory, subcategory),
                        description = COALESCE(excluded.description, description),
                        attributes = COALESCE(excluded.attributes, attributes),
                        last_referenced = CURRENT_TIMESTAMP,
                        reference_count = reference_count + 1,
                        has_word_photo = excluded.has_word_photo OR has_word_photo
                """, (
                    name,
                    category,
                    subcategory,
                    description,
                    json.dumps(attributes) if attributes else None,
                    has_word_photo,
                ))
                conn.commit()
                return True
        except Exception:
            return False

    async def list_category(
        self,
        category: str,
        subcategory: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        List all items in a category.

        This is the primary "what do I have?" query.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            if subcategory:
                cursor = conn.execute("""
                    SELECT * FROM inventory
                    WHERE category = ? AND subcategory = ?
                    ORDER BY reference_count DESC, name
                    LIMIT ?
                """, (category, subcategory, limit))
            else:
                cursor = conn.execute("""
                    SELECT * FROM inventory
                    WHERE category = ?
                    ORDER BY reference_count DESC, name
                    LIMIT ?
                """, (category, limit))

            return [dict(row) for row in cursor.fetchall()]

    async def get_item(self, name: str, category: str) -> Optional[dict]:
        """Get a specific inventory item."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM inventory
                WHERE name = ? AND category = ?
            """, (name, category))

            row = cursor.fetchone()
            if row:
                # Update reference count
                conn.execute("""
                    UPDATE inventory
                    SET last_referenced = CURRENT_TIMESTAMP, reference_count = reference_count + 1
                    WHERE name = ? AND category = ?
                """, (name, category))
                conn.commit()

                return dict(row)
            return None

    async def get_categories(self) -> list[dict]:
        """Get all categories with item counts."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT category, COUNT(*) as count
                FROM inventory
                GROUP BY category
                ORDER BY count DESC
            """)
            return [{"category": row[0], "count": row[1]} for row in cursor.fetchall()]

    async def delete_item(self, name: str, category: str) -> bool:
        """
        Delete an inventory item.

        Args:
            name: Item name
            category: Item category

        Returns:
            True if item was deleted, False if not found
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    DELETE FROM inventory
                    WHERE name = ? AND category = ?
                """, (name, category))
                conn.commit()
                return cursor.rowcount > 0
        except Exception:
            return False

    # === Space-specific methods ===

    async def add_space(
        self,
        name: str,
        description: Optional[str] = None,
        file_path: Optional[str] = None,
        emotional_quality: Optional[str] = None,
    ) -> bool:
        """Add or update a space (room/location)."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO spaces (name, description, file_path, emotional_quality)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        description = COALESCE(excluded.description, description),
                        file_path = COALESCE(excluded.file_path, file_path),
                        emotional_quality = COALESCE(excluded.emotional_quality, emotional_quality)
                """, (name, description, file_path, emotional_quality))
                conn.commit()
                return True
        except Exception:
            return False

    async def get_space(self, name: str) -> Optional[dict]:
        """Get a space by name."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM spaces WHERE name = ?
            """, (name,))

            row = cursor.fetchone()
            if row:
                # Update visit tracking
                conn.execute("""
                    UPDATE spaces
                    SET last_visited = CURRENT_TIMESTAMP, visit_count = visit_count + 1
                    WHERE name = ?
                """, (name,))
                conn.commit()

                result = dict(row)

                # Load description from file if available
                if result.get('file_path') and Path(result['file_path']).exists():
                    result['full_description'] = Path(result['file_path']).read_text()

                return result
            return None

    async def list_spaces(self) -> list[dict]:
        """List all known spaces."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM spaces ORDER BY visit_count DESC, name
            """)
            return [dict(row) for row in cursor.fetchall()]

    async def enter_space(self, name: str) -> Optional[str]:
        """
        Enter a space - load its description for context injection.

        Returns the space description for use in extraction context.
        """
        space = await self.get_space(name)
        if not space:
            return None

        # Return full description if available, otherwise stored description
        return space.get('full_description') or space.get('description')
