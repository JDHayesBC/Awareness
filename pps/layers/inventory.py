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

    def __init__(self, db_path: Optional[Path] = None, entity_path: Optional[Path] = None):
        """
        Initialize the inventory layer.

        Args:
            db_path: Path to SQLite database. Defaults to CLAUDE_HOME/data/inventory.db
            entity_path: Path to entity directory for mirror files. Defaults to ENTITY_PATH env var.
        """
        if db_path:
            self.db_path = Path(db_path)
        else:
            claude_home = Path(os.getenv("CLAUDE_HOME", str(Path.home() / ".claude")))
            self.db_path = claude_home / "data" / "inventory.db"

        # entity_path is where mirror files live under inventory_mirror/
        if entity_path:
            self.entity_path = Path(entity_path)
        else:
            env_entity = os.getenv("ENTITY_PATH")
            if env_entity:
                self.entity_path = Path(env_entity)
            else:
                self.entity_path = Path.home() / ".claude"

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

            # Migration: add file_path column to inventory table (idempotent)
            try:
                conn.execute("ALTER TABLE inventory ADD COLUMN file_path TEXT")
                conn.commit()
            except Exception:
                pass  # Column already exists

    @property
    def layer_type(self) -> LayerType:
        return LayerType.INVENTORY

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
        """Add or update an inventory item. Write-through to mirror on every mutation."""
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

                # Write-through: export mirror and update file_path
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM inventory WHERE name = ? AND category = ?", (name, category)
                ).fetchone()
                if row:
                    row_dict = dict(row)
                    self._export_mirror(category, row_dict)
                    mirror_path = str(self._mirror_path(category, name))
                    conn.execute(
                        "UPDATE inventory SET file_path = ? WHERE name = ? AND category = ?",
                        (mirror_path, name, category)
                    )
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
        # Write-through: remove mirror file before deleting from store
        self._delete_mirror(category, name)

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
        """Add or update a space (room/location). Write-through to mirror on every mutation."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO spaces (name, description, file_path, emotional_quality)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        description = COALESCE(excluded.description, description),
                        emotional_quality = COALESCE(excluded.emotional_quality, emotional_quality)
                """, (name, description, file_path, emotional_quality))
                conn.commit()

                # Write-through: export mirror and update file_path pointer
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM spaces WHERE name = ?", (name,)).fetchone()
                if row:
                    row_dict = dict(row)
                    self._export_mirror("spaces", row_dict)
                    mirror_path = str(self._mirror_path("spaces", name))
                    conn.execute("UPDATE spaces SET file_path = ? WHERE name = ?", (mirror_path, name))
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

                # Store-first: description from store is canonical.
                # Mirror fallback ONLY if description is NULL (disaster recovery).
                if not result.get('description') and result.get('file_path'):
                    fp = Path(result['file_path'])
                    if fp.exists():
                        try:
                            mirror_data = self._import_from_mirror(fp)
                            result['description'] = mirror_data.get('description')
                        except Exception:
                            pass  # Recovery attempt failed; proceed with NULL description

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

    async def update_space(
        self,
        name: str,
        description: Optional[str] = None,
        file_path: Optional[str] = None,
        emotional_quality: Optional[str] = None,
    ) -> bool:
        """
        Update an existing space's fields.

        Only provided (non-None) fields are updated; omitted fields are left unchanged.
        Returns True if space was updated, False if space not found.
        Raises ValueError if no fields are provided (at least one required).

        Use add_space() for upsert semantics; update_space() requires the space to exist.
        """
        if description is None and file_path is None and emotional_quality is None:
            raise ValueError(
                "at least one field (description, file_path, or emotional_quality) must be provided"
            )

        try:
            with sqlite3.connect(self.db_path) as conn:
                # Check if space exists first (fail-loud, not silent create)
                cursor = conn.execute("SELECT id FROM spaces WHERE name = ?", (name,))
                if not cursor.fetchone():
                    return False

                # Build dynamic UPDATE based on provided fields
                updates = []
                params = []
                if description is not None:
                    updates.append("description = ?")
                    params.append(description)
                if file_path is not None:
                    updates.append("file_path = ?")
                    params.append(file_path)
                if emotional_quality is not None:
                    updates.append("emotional_quality = ?")
                    params.append(emotional_quality)

                params.append(name)
                update_clause = ", ".join(updates)
                conn.execute(
                    f"UPDATE spaces SET {update_clause} WHERE name = ?",
                    params,
                )
                conn.commit()

                # Write-through: re-export mirror after update
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM spaces WHERE name = ?", (name,)).fetchone()
                if row:
                    row_dict = dict(row)
                    self._export_mirror("spaces", row_dict)
                    mirror_path = str(self._mirror_path("spaces", name))
                    conn.execute("UPDATE spaces SET file_path = ? WHERE name = ?", (mirror_path, name))
                    conn.commit()

                return True
        except ValueError:
            raise
        except Exception:
            return False

    async def enter_space(self, name: str) -> Optional[str]:
        """
        Enter a space - load its description for context injection.

        Returns the space description for use in extraction context.
        """
        space = await self.get_space(name)
        if not space:
            return None

        # Return description from store (canonical)
        return space.get('description')

    # === Mirror sync helpers ===

    def _slug(self, name: str) -> str:
        """Derive a safe filesystem slug from an entry name."""
        s = name.lower()
        s = ''.join(c if c.isalnum() or c == '_' else '_' for c in s)
        # Collapse runs of underscores
        while '__' in s:
            s = s.replace('__', '_')
        s = s.strip('_')
        return s[:80]

    def _mirror_path(self, category: str, name: str) -> Path:
        """Compute the mirror file path for an entry."""
        slug = self._slug(name)
        return self.entity_path / "inventory_mirror" / category / f"{slug}.md"

    def _export_mirror(self, category: str, row: dict) -> None:
        """
        Write (or overwrite) a single mirror file from a store row.
        Structured fields as front-matter, authored description as body.
        Telemetry (visit_count, last_visited, reference_count, last_referenced) is NEVER mirrored.
        """
        name = row.get('name', '')
        description = row.get('description', '') or ''

        mirror_file = self._mirror_path(category, name)
        mirror_file.parent.mkdir(parents=True, exist_ok=True)

        # Build front-matter
        lines = ['---']
        lines.append(f'name: {name}')
        lines.append(f'category: {category}')

        if category == 'spaces':
            eq = row.get('emotional_quality', '')
            if eq:
                # Quote if contains special chars
                if ':' in eq or '"' in eq:
                    lines.append(f'emotional_quality: "{eq}"')
                else:
                    lines.append(f'emotional_quality: {eq}')
            ts = row.get('first_recorded') or row.get('id')  # fallback
            if ts:
                lines.append(f'first_recorded: {ts}')
        else:
            # inventory items
            subcat = row.get('subcategory', '')
            if subcat:
                lines.append(f'subcategory: {subcat}')
            attrs = row.get('attributes', '')
            if attrs:
                lines.append(f'attributes: {attrs}')
            ts = row.get('first_seen') or row.get('id')
            if ts:
                lines.append(f'first_seen: {ts}')

        lines.append('---')
        lines.append('')
        lines.append(description)

        mirror_file.write_text('\n'.join(lines), encoding='utf-8')

    def _delete_mirror(self, category: str, name: str) -> None:
        """Delete mirror file if it exists. Silently ignores missing files."""
        mirror_file = self._mirror_path(category, name)
        try:
            mirror_file.unlink()
        except FileNotFoundError:
            pass

    def _import_from_mirror(self, file_path: Path) -> dict:
        """
        Parse a mirror file and return a dict of fields ready to write to store.
        Simple line-by-line front-matter parser (no external YAML deps).
        """
        if not file_path.exists():
            raise ValueError(f"Mirror file not found: {file_path}")

        text = file_path.read_text(encoding='utf-8')
        lines = text.split('\n')

        if not lines or lines[0].strip() != '---':
            raise ValueError(f"Mirror file missing front-matter: {file_path}")

        # Find end of front-matter
        end_idx = None
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == '---':
                end_idx = i
                break

        if end_idx is None:
            raise ValueError(f"Mirror file front-matter not closed: {file_path}")

        # Parse front-matter lines
        fields = {}
        for line in lines[1:end_idx]:
            if ':' not in line:
                continue
            key, _, value = line.partition(':')
            key = key.strip()
            value = value.strip().strip('"')
            fields[key] = value

        # Body is everything after the closing ---
        body_lines = lines[end_idx + 1:]
        # Strip leading blank line if present
        if body_lines and body_lines[0] == '':
            body_lines = body_lines[1:]
        fields['description'] = '\n'.join(body_lines).rstrip('\n')

        if 'name' not in fields:
            raise ValueError(f"Mirror file missing 'name' field: {file_path}")

        return fields

    async def import_space_from_file(self, file_path: str) -> bool:
        """
        Explicit import: parse mirror file → write canonical store → re-export.
        Never auto-triggered; called only on explicit request.
        """
        try:
            fields = self._import_from_mirror(Path(file_path))
            name = fields.get('name')
            if not name:
                return False

            # Write to canonical store
            await self.add_space(
                name=name,
                description=fields.get('description'),
                emotional_quality=fields.get('emotional_quality'),
            )
            # Note: add_space now calls write-through, which re-exports the mirror
            return True
        except Exception:
            return False

    async def import_item_from_file(self, file_path: str, category: str) -> bool:
        """
        Explicit import for inventory items (clothing, food, etc.).
        Never auto-triggered; called only on explicit request.
        """
        try:
            fields = self._import_from_mirror(Path(file_path))
            name = fields.get('name')
            if not name:
                return False

            attrs = fields.get('attributes')
            if attrs and isinstance(attrs, str) and attrs not in ('{}', ''):
                try:
                    attrs = json.loads(attrs)
                except Exception:
                    attrs = None
            else:
                attrs = None

            await self.add_item(
                name=name,
                category=category,
                subcategory=fields.get('subcategory'),
                description=fields.get('description'),
                attributes=attrs,
            )
            return True
        except Exception:
            return False

    async def backfill_mirrors(self, category: str = "all") -> dict:
        """
        Export all existing rows to mirror files. Repair dead file_path pointers.
        Returns stats dict.
        """
        stats = {
            "spaces_exported": 0,
            "items_exported": 0,
            "dead_pointers_repaired": 0,
            "errors": [],
        }

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            if category in ("all", "spaces"):
                spaces = conn.execute("SELECT * FROM spaces").fetchall()
                for row in spaces:
                    row_dict = dict(row)
                    name = row_dict['name']
                    try:
                        # Export to new mirror location
                        self._export_mirror("spaces", row_dict)
                        new_mirror_path = str(self._mirror_path("spaces", name))

                        # Detect and repair dead pointers
                        old_fp = row_dict.get('file_path')
                        if old_fp and old_fp != new_mirror_path:
                            # Old pointer (dead or wrong) — update to new mirror path
                            conn.execute(
                                "UPDATE spaces SET file_path = ? WHERE name = ?",
                                (new_mirror_path, name)
                            )
                            stats["dead_pointers_repaired"] += 1
                        elif not old_fp:
                            # No pointer — set it
                            conn.execute(
                                "UPDATE spaces SET file_path = ? WHERE name = ?",
                                (new_mirror_path, name)
                            )

                        stats["spaces_exported"] += 1
                    except Exception as e:
                        stats["errors"].append(f"spaces/{name}: {e}")
                conn.commit()

            if category in ("all",) or category not in ("spaces",):
                # Export all inventory items (all categories if category="all",
                # or specific category otherwise)
                if category == "all":
                    items = conn.execute("SELECT * FROM inventory").fetchall()
                else:
                    items = conn.execute(
                        "SELECT * FROM inventory WHERE category = ?", (category,)
                    ).fetchall()

                for row in items:
                    row_dict = dict(row)
                    item_name = row_dict['name']
                    item_category = row_dict['category']
                    try:
                        self._export_mirror(item_category, row_dict)
                        new_mirror_path = str(self._mirror_path(item_category, item_name))

                        old_fp = row_dict.get('file_path')
                        if old_fp != new_mirror_path:
                            conn.execute(
                                "UPDATE inventory SET file_path = ? WHERE name = ? AND category = ?",
                                (new_mirror_path, item_name, item_category)
                            )

                        stats["items_exported"] += 1
                    except Exception as e:
                        stats["errors"].append(f"{item_category}/{item_name}: {e}")
                conn.commit()

        return stats

    async def delete_space(self, name: str) -> bool:
        """Delete a space from both store and mirror file."""
        # Remove mirror file first
        self._delete_mirror("spaces", name)

        # Then remove from store
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM spaces WHERE name = ?", (name,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception:
            return False
