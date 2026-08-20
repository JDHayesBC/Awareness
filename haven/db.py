"""Haven — SQLite database layer with aiosqlite + WAL."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    is_bot INTEGER NOT NULL DEFAULT 0,
    token_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    is_dm INTEGER NOT NULL DEFAULT 0,
    created_by TEXT REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS room_members (
    room_id TEXT NOT NULL REFERENCES rooms(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (room_id, user_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id TEXT NOT NULL REFERENCES rooms(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS room_reads (
    user_id TEXT NOT NULL REFERENCES users(id),
    room_id TEXT NOT NULL REFERENCES rooms(id),
    last_read_id INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, room_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_room_time
    ON messages(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_token_hash
    ON users(token_hash);
CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user
    ON push_subscriptions(user_id);
"""


class HavenDB:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        # Migrations: add new columns if they don't exist yet
        for col_sql in [
            "ALTER TABLE users ADD COLUMN password_hash TEXT",
            "ALTER TABLE users ADD COLUMN token TEXT",
            "ALTER TABLE users ADD COLUMN google_id TEXT",
            "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE messages ADD COLUMN image_url TEXT",
        ]:
            try:
                await self._db.execute(col_sql)
                await self._db.commit()
            except Exception:
                pass  # Column already exists

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # --- Users ---

    async def create_user(
        self, username: str, display_name: str, token_hash: str, is_bot: bool = False
    ) -> dict:
        user_id = str(uuid.uuid4())
        await self._db.execute(
            "INSERT INTO users (id, username, display_name, is_bot, token_hash) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, display_name, int(is_bot), token_hash),
        )
        await self._db.commit()
        return {"id": user_id, "username": username, "display_name": display_name, "is_bot": is_bot}

    async def get_user_by_token_hash(self, token_hash: str) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM users WHERE token_hash = ?", (token_hash,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_user(self, user_id: str) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_user_by_username(self, username: str) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def list_users(self) -> list[dict]:
        async with self._db.execute("SELECT * FROM users ORDER BY username") as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def update_last_seen(self, user_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE users SET last_seen_at = ? WHERE id = ?", (now, user_id)
        )
        await self._db.commit()

    async def set_user_password(self, user_id: str, password_hash: str) -> None:
        await self._db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id)
        )
        await self._db.commit()

    async def set_user_token(self, user_id: str, token: str) -> None:
        """Store plaintext token for password/OAuth login flow."""
        await self._db.execute(
            "UPDATE users SET token = ? WHERE id = ?", (token, user_id)
        )
        await self._db.commit()

    async def get_user_by_google_id(self, google_id: str) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM users WHERE google_id = ?", (google_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def link_google_id(self, user_id: str, google_id: str) -> None:
        await self._db.execute(
            "UPDATE users SET google_id = ? WHERE id = ?", (google_id, user_id)
        )
        await self._db.commit()

    # --- Rooms ---

    async def create_room(
        self, name: str, display_name: str, created_by: str, is_dm: bool = False
    ) -> dict:
        room_id = str(uuid.uuid4())
        await self._db.execute(
            "INSERT INTO rooms (id, name, display_name, is_dm, created_by) VALUES (?, ?, ?, ?, ?)",
            (room_id, name, display_name, int(is_dm), created_by),
        )
        # Creator auto-joins
        await self._db.execute(
            "INSERT INTO room_members (room_id, user_id) VALUES (?, ?)",
            (room_id, created_by),
        )
        await self._db.commit()
        return {"id": room_id, "name": name, "display_name": display_name, "is_dm": is_dm}

    async def get_room(self, room_id: str) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM rooms WHERE id = ?", (room_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_room_by_name(self, name: str) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM rooms WHERE name = ?", (name,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_room_by_display_name(self, display_name: str) -> dict | None:
        """Resolve a room by its human-readable display_name.

        Fallback for callers who pass the friendly title (e.g.
        "Crusher Braveheart's Room") rather than the slug ("crusher-room").
        """
        async with self._db.execute(
            "SELECT * FROM rooms WHERE display_name = ?", (display_name,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def list_rooms_for_user(self, user_id: str) -> list[dict]:
        async with self._db.execute(
            """SELECT r.*, COUNT(rm2.user_id) as member_count
               FROM rooms r
               JOIN room_members rm ON r.id = rm.room_id AND rm.user_id = ?
               LEFT JOIN room_members rm2 ON r.id = rm2.room_id
               GROUP BY r.id
               ORDER BY r.name""",
            (user_id,),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def join_room(self, room_id: str, user_id: str) -> bool:
        """Join a room. Returns True if newly joined, False if already a member."""
        try:
            await self._db.execute(
                "INSERT INTO room_members (room_id, user_id) VALUES (?, ?)",
                (room_id, user_id),
            )
            await self._db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def is_room_member(self, room_id: str, user_id: str) -> bool:
        async with self._db.execute(
            "SELECT 1 FROM room_members WHERE room_id = ? AND user_id = ?",
            (room_id, user_id),
        ) as cursor:
            return await cursor.fetchone() is not None

    async def leave_room(self, room_id: str, user_id: str) -> bool:
        """Leave a room. Returns True if was a member, False if not."""
        async with self._db.execute(
            "DELETE FROM room_members WHERE room_id = ? AND user_id = ?",
            (room_id, user_id),
        ) as cursor:
            await self._db.commit()
            return cursor.rowcount > 0

    async def get_room_members(self, room_id: str) -> list[dict]:
        async with self._db.execute(
            """SELECT u.* FROM users u
               JOIN room_members rm ON u.id = rm.user_id
               WHERE rm.room_id = ?
               ORDER BY u.username""",
            (room_id,),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    # --- Messages ---

    async def create_message(
        self,
        room_id: str,
        user_id: str,
        content: str,
        image_url: str | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        async with self._db.execute(
            "INSERT INTO messages (room_id, user_id, content, created_at, image_url) "
            "VALUES (?, ?, ?, ?, ?)",
            (room_id, user_id, content, now, image_url),
        ) as cursor:
            msg_id = cursor.lastrowid
        await self._db.commit()

        # Fetch with user info
        async with self._db.execute(
            """SELECT m.*, u.username, u.display_name
               FROM messages m JOIN users u ON m.user_id = u.id
               WHERE m.id = ?""",
            (msg_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else {"id": msg_id}

    async def get_messages(
        self,
        room_id: str,
        limit: int = 50,
        before_id: int | None = None,
        since: str | None = None,
    ) -> list[dict]:
        conditions = ["m.room_id = ?"]
        params: list = [room_id]

        if before_id is not None:
            conditions.append("m.id < ?")
            params.append(before_id)
        if since:
            conditions.append("m.created_at > ?")
            params.append(since)

        where = " AND ".join(conditions)
        params.append(limit + 1)  # Fetch one extra to detect has_more

        async with self._db.execute(
            f"""SELECT m.*, u.username, u.display_name
                FROM messages m JOIN users u ON m.user_id = u.id
                WHERE {where}
                ORDER BY m.created_at DESC
                LIMIT ?""",
            params,
        ) as cursor:
            rows = [dict(row) for row in await cursor.fetchall()]

        return rows

    async def mark_room_read(
        self, user_id: str, room_id: str, up_to_id: int | None = None
    ) -> None:
        """Mark a room read for a user up to a message id (default: latest).

        The stored marker only ever advances (MAX), so an out-of-order or stale
        client 'read' can never rewind unread state.
        """
        if up_to_id is None:
            async with self._db.execute(
                "SELECT COALESCE(MAX(id), 0) AS m FROM messages WHERE room_id = ?",
                (room_id,),
            ) as cursor:
                row = await cursor.fetchone()
                up_to_id = row["m"] if row else 0
        await self._db.execute(
            """INSERT INTO room_reads (user_id, room_id, last_read_id, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id, room_id) DO UPDATE SET
                   last_read_id = MAX(last_read_id, excluded.last_read_id),
                   updated_at = CURRENT_TIMESTAMP""",
            (user_id, room_id, up_to_id),
        )
        await self._db.commit()

    async def get_unread_counts(self, user_id: str) -> dict[str, int]:
        """Return {room_id: unread_count} for every room the user belongs to.

        Unread = messages from OTHER users with an id greater than the user's
        last-read marker for that room (marker defaults to 0 = never read).
        Rooms with nothing unread are still present with a count of 0.
        """
        async with self._db.execute(
            """SELECT rm.room_id AS room_id, COUNT(m.id) AS unread
                 FROM room_members rm
                 LEFT JOIN room_reads rr
                       ON rr.room_id = rm.room_id AND rr.user_id = rm.user_id
                 LEFT JOIN messages m
                       ON m.room_id = rm.room_id
                      AND m.user_id != rm.user_id
                      AND m.id > COALESCE(rr.last_read_id, 0)
                WHERE rm.user_id = ?
                GROUP BY rm.room_id""",
            (user_id,),
        ) as cursor:
            return {row["room_id"]: row["unread"] for row in await cursor.fetchall()}

    async def set_admin(self, user_id: str, is_admin: bool = True) -> None:
        await self._db.execute(
            "UPDATE users SET is_admin = ? WHERE id = ?", (int(is_admin), user_id)
        )
        await self._db.commit()

    async def is_admin(self, user_id: str) -> bool:
        async with self._db.execute(
            "SELECT is_admin FROM users WHERE id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return bool(row["is_admin"]) if row else False

    async def regenerate_token(self, user_id: str, new_token_hash: str) -> None:
        await self._db.execute(
            "UPDATE users SET token_hash = ? WHERE id = ?", (new_token_hash, user_id)
        )
        await self._db.commit()

    async def delete_user(self, user_id: str) -> bool:
        # Remove from all rooms first
        await self._db.execute("DELETE FROM room_members WHERE user_id = ?", (user_id,))
        async with self._db.execute("DELETE FROM users WHERE id = ?", (user_id,)) as cursor:
            await self._db.commit()
            return cursor.rowcount > 0

    async def find_or_create_dm(self, user1_id: str, user2_id: str) -> dict:
        """Find existing DM between two users, or create one."""
        async with self._db.execute(
            """SELECT r.* FROM rooms r
               JOIN room_members rm1 ON r.id = rm1.room_id AND rm1.user_id = ?
               JOIN room_members rm2 ON r.id = rm2.room_id AND rm2.user_id = ?
               WHERE r.is_dm = 1""",
            (user1_id, user2_id),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)

        # Create new DM
        u1 = await self.get_user(user1_id)
        u2 = await self.get_user(user2_id)
        name = f"dm-{u1['username']}-{u2['username']}"
        display_name = f"{u1['display_name']} & {u2['display_name']}"
        room_id = str(uuid.uuid4())
        await self._db.execute(
            "INSERT INTO rooms (id, name, display_name, is_dm, created_by) VALUES (?, ?, ?, 1, ?)",
            (room_id, name, display_name, user1_id),
        )
        await self._db.execute(
            "INSERT INTO room_members (room_id, user_id) VALUES (?, ?)", (room_id, user1_id)
        )
        await self._db.execute(
            "INSERT INTO room_members (room_id, user_id) VALUES (?, ?)", (room_id, user2_id)
        )
        await self._db.commit()
        return {"id": room_id, "name": name, "display_name": display_name, "is_dm": True}

    async def get_message_count(self, room_id: str) -> int:
        async with self._db.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE room_id = ?", (room_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["cnt"] if row else 0

    # --- Push subscriptions ---

    async def add_push_subscription(
        self, user_id: str, endpoint: str, p256dh: str, auth: str
    ) -> None:
        """Upsert a push subscription for a user, keyed by endpoint.

        If the endpoint already exists (same device re-subscribing), update the
        p256dh/auth keys so the record stays current.
        """
        await self._db.execute(
            """INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(endpoint) DO UPDATE SET
                   user_id = excluded.user_id,
                   p256dh  = excluded.p256dh,
                   auth    = excluded.auth""",
            (user_id, endpoint, p256dh, auth),
        )
        await self._db.commit()

    async def get_push_subscriptions_for_user(self, user_id: str) -> list[dict]:
        """Return all active push subscriptions for a given user."""
        async with self._db.execute(
            "SELECT * FROM push_subscriptions WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def get_push_subscriptions_for_users(
        self, user_ids: list[str]
    ) -> list[dict]:
        """Return all push subscriptions for a list of user IDs in one query."""
        if not user_ids:
            return []
        placeholders = ",".join("?" * len(user_ids))
        async with self._db.execute(
            f"SELECT * FROM push_subscriptions WHERE user_id IN ({placeholders})",
            user_ids,
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def delete_push_subscription(self, endpoint: str) -> None:
        """Delete a push subscription by endpoint (used to prune expired/gone subs)."""
        await self._db.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,)
        )
        await self._db.commit()
