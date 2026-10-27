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
from datetime import datetime, timedelta, timezone
from typing import Optional, Literal, Any

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

            # Migration: add aliases column to spaces table (idempotent)
            try:
                conn.execute("ALTER TABLE spaces ADD COLUMN aliases TEXT")
                conn.commit()
            except Exception:
                pass  # Column already exists

            # Migration: add house column to spaces table (idempotent). Nullable;
            # owners curate rows themselves. NULL = unknown house (#378 pass 3).
            try:
                conn.execute("ALTER TABLE spaces ADD COLUMN house TEXT")
                conn.commit()
            except Exception:
                pass  # Column already exists

            # Migration: create entity_presence table (idempotent)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entity_presence (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    current_space TEXT,
                    since TIMESTAMP,
                    source TEXT DEFAULT 'manual',
                    pending_arrival TEXT
                )
            """)
            # Seed exactly one row (the constraint above ensures id=1 only)
            conn.execute("INSERT OR IGNORE INTO entity_presence (id) VALUES (1)")
            conn.commit()

            # Migration: ack_space = the space whose FULL description was last
            # delivered via enter_space (#378 pass 3). Set ONLY by enter_space.
            try:
                conn.execute("ALTER TABLE entity_presence ADD COLUMN ack_space TEXT")
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

                # Write-through: export mirror and update file_path pointer.
                # Auto-populate file_path with the mirror path only when:
                #   (a) caller did not provide an explicit file_path, AND
                #   (b) the current DB value is NULL/empty.
                # Preserves user-provided narrative room file pointers across
                # subsequent add_space (upsert) and update_space calls.
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM spaces WHERE name = ?", (name,)).fetchone()
                if row:
                    row_dict = dict(row)
                    self._export_mirror("spaces", row_dict)
                    current_fp = row_dict.get("file_path")
                    if file_path is None and not current_fp:
                        mirror_path = str(self._mirror_path("spaces", name))
                        conn.execute("UPDATE spaces SET file_path = ? WHERE name = ?", (mirror_path, name))
                        conn.commit()

            return True
        except Exception:
            return False

    async def get_space(self, name: str, bump: bool = True) -> Optional[dict]:
        """Get a space by name. bump=False skips the visit-stat update."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM spaces WHERE name = ?
            """, (name,))

            row = cursor.fetchone()
            if row:
                # Update visit tracking
                if bump:
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

        # Store has no such row: the mirror answers (spec: store first, mirror
        # only on a missing row). Read-only -- hand-edits reach the store only
        # via explicit import_space_from_file.
        mirror_file = self._mirror_path("spaces", name)
        if mirror_file.exists():
            try:
                fields = self._import_from_mirror(mirror_file)
                return {
                    'name': fields.get('name', name),
                    'description': fields.get('description'),
                    'file_path': str(mirror_file),
                    'emotional_quality': fields.get('emotional_quality'),
                    'aliases': fields.get('aliases'),
                    'house': fields.get('house'),
                    'from_mirror': True,
                }
            except Exception:
                return None
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

                # Write-through: re-export mirror after update.
                # Only auto-populate file_path with the mirror path if:
                #   (a) the caller did not provide an explicit file_path, AND
                #   (b) the current DB value of file_path is NULL/empty.
                # This prevents clobbering a user-provided narrative room file
                # pointer with the internal mirror path on every update.
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM spaces WHERE name = ?", (name,)).fetchone()
                if row:
                    row_dict = dict(row)
                    self._export_mirror("spaces", row_dict)
                    current_fp = row_dict.get("file_path")
                    if file_path is None and not current_fp:
                        mirror_path = str(self._mirror_path("spaces", name))
                        conn.execute("UPDATE spaces SET file_path = ? WHERE name = ?", (mirror_path, name))
                        conn.commit()

                return True
        except ValueError:
            raise
        except Exception:
            return False

    async def enter_space(self, name: str, ack_only: bool = False) -> Optional[str]:
        """
        Enter a space - load its description for context injection.

        Returns the space description (canonical, from the store).

        Presence semantics (#378 pass 3):
          - Sets ack_space = name: the FULL description has now been delivered.
          - Writes NO pending_arrival (completing the chain must not re-flag).
          - Moving to a different room: current_space/since/source updated, visit
            stats bumped, any stale pending cleared (latest move wins).
          - Re-entering the room already current: no visit bump, since untouched,
            pending untouched (an ack is not a move).
          - ack_only=True: only ack_space changes (post-compaction re-fetch).
        """
        current = (await self.get_presence()).get("current_space")
        is_same = (current == name)
        bump = not (ack_only or is_same)

        space = await self.get_space(name, bump=bump)
        if not space:
            return None

        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            if ack_only or is_same:
                conn.execute(
                    "UPDATE entity_presence SET ack_space = ? WHERE id = 1", (name,)
                )
            else:
                conn.execute(
                    """
                    UPDATE entity_presence
                    SET current_space = ?, since = ?, source = 'enter_space',
                        ack_space = ?, pending_arrival = NULL
                    WHERE id = 1
                    """,
                    (name, now, name),
                )
            conn.commit()

        return space.get('description')

    async def get_spaces_with_aliases(self) -> list[dict]:
        """Return all spaces including the aliases column, ordered by visit_count."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM spaces ORDER BY visit_count DESC, name
            """)
            return [dict(row) for row in cursor.fetchall()]

    async def get_presence(self, clear_pending: bool = False) -> dict:
        """
        Return the current presence record: {current_space, since, source, pending_arrival}.

        If clear_pending=True and pending_arrival is not null, clears it atomically
        in the same transaction. ambient_recall no longer uses this (pending now
        lives until the entity's next own message; see clear_pending()).

        Returns {} if no presence row exists yet.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM entity_presence WHERE id = 1").fetchone()
            if not row:
                return {}

            result = dict(row)
            pending = result.get("pending_arrival")

            if clear_pending and pending:
                conn.execute(
                    "UPDATE entity_presence SET pending_arrival = NULL WHERE id = 1"
                )
                conn.commit()
                # Return the record with the pending still included — caller needs it
                # for rendering; it's been cleared from DB already.

            return result

    async def set_presence(
        self,
        space_name: str,
        source: str,
        from_space: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """
        Update entity_presence with a new current_space.

        Sets current_space, since=now (UTC), source.
        If from_space or description are provided, also sets pending_arrival as a
        JSON blob: {"from": from_space, "to": space_name, "description": desc, "at": iso}
        so ambient_recall can surface a [moved] line on the next call.

        Also bumps spaces.last_visited and visit_count for space_name (same as
        enter_space internals), so the two paths stay in sync.

        Args:
            space_name: The destination space name.
            source: One of 'detected', 'marker', 'enter_space', 'manual', 'proposed'.
            from_space: Previous space name, if known.
            description: Space description to include in pending_arrival, if known.

        Returns:
            True on success.
        """
        try:
            # Same-space guard: a detected/marker/high "move" into the room already
            # current is not a move. Drop only a proposed pending (e.g. a marker
            # written to dismiss a wrong [moved?]); leave since/source/ack_space/
            # visit_count and any real pending untouched.
            if source not in ("enter_space", "manual"):
                with sqlite3.connect(self.db_path) as conn:
                    row = conn.execute(
                        "SELECT current_space FROM entity_presence WHERE id = 1"
                    ).fetchone()
                if row and row[0] == space_name:
                    await self.clear_pending(only_proposed=True)
                    return True

            now = datetime.now(timezone.utc).isoformat()

            pending: Optional[str] = None
            if from_space is not None or description is not None:
                pa: dict[str, Any] = {
                    "from": from_space,
                    "to": space_name,
                    "at": now,
                    "source": source,
                }
                if description:
                    pa["description"] = description
                if source == "proposed":
                    pa["proposed"] = True
                pending = json.dumps(pa)

            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE entity_presence
                    SET current_space = ?,
                        since         = ?,
                        source        = ?,
                        pending_arrival = ?
                    WHERE id = 1
                """, (space_name, now, source, pending))

                # Bump visit stats for the destination space (mirrors enter_space internals)
                conn.execute("""
                    UPDATE spaces
                    SET last_visited = ?,
                        visit_count  = visit_count + 1
                    WHERE name = ?
                """, (now, space_name))

                conn.commit()

            return True
        except Exception:
            return False

    async def propose_presence(
        self,
        space_name: str,
        from_space: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """
        Record a LOW-confidence guess: writes ONLY pending_arrival (proposed=true).

        Never touches current_space, since, or spaces.last_visited/visit_count,
        so a bare re-mention can't move the entity or reset the stillness timer.
        """
        try:
            pa: dict[str, Any] = {
                "from": from_space,
                "to": space_name,
                "at": datetime.now(timezone.utc).isoformat(),
                "description": description,
                "proposed": True,
                "source": "proposed",
            }
            with sqlite3.connect(self.db_path) as conn:
                # Never overwrite an unresolved REAL pending: the chain gate
                # would silently vanish when a LOW fires mid-chain.
                row = conn.execute(
                    "SELECT pending_arrival FROM entity_presence WHERE id = 1"
                ).fetchone()
                if row and row[0]:
                    try:
                        if not json.loads(row[0]).get("proposed"):
                            return True  # proposal dropped, real pending kept
                    except Exception:
                        pass  # malformed pending: fall through and replace
                conn.execute(
                    "UPDATE entity_presence SET pending_arrival = ? WHERE id = 1",
                    (json.dumps(pa),),
                )
                conn.commit()
            return True
        except Exception:
            return False

    async def clear_pending(self, only_proposed: bool = False) -> bool:
        """
        Clear pending_arrival.

        only_proposed=True clears just a LOW `[moved?]` proposal; a real `[moved]`
        pending survives until the enter_space + scene-rewrite chain completes.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                if only_proposed:
                    row = conn.execute(
                        "SELECT pending_arrival FROM entity_presence WHERE id = 1"
                    ).fetchone()
                    raw = row[0] if row else None
                    if not raw:
                        return True
                    try:
                        proposed = bool(json.loads(raw).get("proposed"))
                    except Exception:
                        proposed = True  # malformed pending: safe to drop
                    if not proposed:
                        return True
                conn.execute("UPDATE entity_presence SET pending_arrival = NULL WHERE id = 1")
                conn.commit()
            return True
        except Exception:
            return False

    async def chain_status(self, scene_path: Path) -> dict:
        """
        Judge the [moved] chain from what the server actually delivered:
          ack_ok   -- ack_space == current_space (enter_space delivered the room)
          scene_ok -- scene file mtime (UTC) >= presence.since (portrait rewritten)
          complete -- both.
        `since` is an ISO UTC string; naive values are treated as UTC.
        """
        presence = await self.get_presence()
        current = presence.get("current_space")
        ack_ok = bool(current) and presence.get("ack_space") == current
        scene_ok = False
        try:
            since = presence.get("since")
            if since:
                since_dt = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=timezone.utc)
                mtime = datetime.fromtimestamp(Path(scene_path).stat().st_mtime, tz=timezone.utc)
                # 2s slack: WSL wall clock steps backwards ~1s; `since` is
                # container UTC vs a drvfs mtime.
                scene_ok = mtime >= since_dt - timedelta(seconds=2)
        except Exception:
            scene_ok = False
        return {"ack_ok": ack_ok, "scene_ok": scene_ok, "complete": ack_ok and scene_ok}

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
            # Authored per-owner fields: a rebuild from mirrors must not lose them.
            aliases = row.get('aliases') or ''
            if aliases:
                lines.append(f'aliases: {aliases}')
            house = row.get('house') or ''
            if house:
                lines.append(f'house: {house}')
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
            # aliases/house: absence (older mirror) or empty means "unchanged";
            # only a non-empty value is written, then the mirror is re-exported.
            updates = {k: fields[k] for k in ('aliases', 'house') if fields.get(k)}
            if updates:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    for col, val in updates.items():
                        conn.execute(f"UPDATE spaces SET {col} = ? WHERE name = ?", (val, name))
                    conn.commit()
                    row = conn.execute("SELECT * FROM spaces WHERE name = ?", (name,)).fetchone()
                    if row:
                        self._export_mirror("spaces", dict(row))
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

    def mirror_orphans(self, category: str, row_names: Optional[list[str]] = None) -> list[str]:
        """Mirror files in a category with no matching store row, by slug.

        Orphans were inert until get_space learned to answer a missing row from
        its mirror (ce28257); a stray fixture file can now become a room. Report
        them so they are seen on purpose, not found by accident.
        """
        mdir = self.entity_path / "inventory_mirror" / category
        if not mdir.exists():
            return []
        if row_names is None:
            with sqlite3.connect(self.db_path) as conn:
                table = "spaces" if category == "spaces" else "inventory"
                q = "SELECT name FROM spaces" if category == "spaces" else "SELECT name FROM inventory WHERE category = ?"
                rows = conn.execute(q, () if category == "spaces" else (category,)).fetchall()
                row_names = [r[0] for r in rows]
        slugs = {self._slug(n) for n in row_names}
        return sorted(f.stem for f in mdir.glob("*.md") if f.stem not in slugs)

    async def backfill_mirrors(self, category: str = "all") -> dict:
        """
        Export all existing rows to mirror files. Repair dead file_path pointers.
        Returns stats dict.
        """
        stats = {
            "spaces_exported": 0,
            "items_exported": 0,
            "dead_pointers_repaired": 0,
            "mirror_orphans": [],   # spaces mirror files with no store row (load-bearing since get_space reads them)
            "errors": [],
        }

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            if category in ("all", "spaces"):
                spaces = conn.execute("SELECT * FROM spaces").fetchall()
                stats["mirror_orphans"] = self.mirror_orphans("spaces", [dict(r)["name"] for r in spaces])
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
