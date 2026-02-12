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

CREATE INDEX IF NOT EXISTS idx_messages_room_time
    ON messages(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_token_hash
    ON users(token_hash);
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

    async def create_message(self, room_id: str, user_id: str, content: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        async with self._db.execute(
            "INSERT INTO messages (room_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
            (room_id, user_id, content, now),
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

    async def get_message_count(self, room_id: str) -> int:
        async with self._db.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE room_id = ?", (room_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["cnt"] if row else 0
