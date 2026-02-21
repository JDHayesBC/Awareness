import aiosqlite
import json
from datetime import datetime
from uuid import uuid4


class Storage:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS repos (
                    name TEXT PRIMARY KEY,
                    config TEXT,
                    created_at TEXT
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    repo_name TEXT,
                    source TEXT,
                    full_text TEXT,
                    metadata TEXT,
                    created_at TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    FOREIGN KEY (repo_name) REFERENCES repos(name) ON DELETE CASCADE
                )
            ''')
            await db.commit()

    async def create_repo(self, name: str, config: dict):
        async with aiosqlite.connect(self.db_path) as db:
            created_at = datetime.utcnow().isoformat()
            await db.execute(
                'INSERT INTO repos (name, config, created_at) VALUES (?, ?, ?)',
                (name, json.dumps(config), created_at)
            )
            await db.commit()

    async def get_repo(self, name: str):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM repos WHERE name = ?', (name,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        'name': row['name'],
                        'config': json.loads(row['config']),
                        'created_at': row['created_at']
                    }
                return None

    async def list_repos(self):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('SELECT * FROM repos') as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        'name': row['name'],
                        'config': json.loads(row['config']),
                        'created_at': row['created_at']
                    }
                    for row in rows
                ]

    async def update_repo(self, name: str, config: dict):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE repos SET config = ? WHERE name = ?',
                (json.dumps(config), name)
            )
            await db.commit()

    async def delete_repo(self, name: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('DELETE FROM documents WHERE repo_name = ?', (name,))
            await db.execute('DELETE FROM repos WHERE name = ?', (name,))
            await db.commit()

    async def store_document(self, repo_name: str, source: str, full_text: str, metadata: dict, chunk_count: int) -> str:
        doc_id = str(uuid4())
        async with aiosqlite.connect(self.db_path) as db:
            created_at = datetime.utcnow().isoformat()
            await db.execute(
                'INSERT INTO documents (id, repo_name, source, full_text, metadata, created_at, chunk_count) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (doc_id, repo_name, source, full_text, json.dumps(metadata), created_at, chunk_count)
            )
            await db.commit()
        return doc_id

    async def get_documents(self, repo_name: str):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM documents WHERE repo_name = ?', (repo_name,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        'id': row['id'],
                        'source': row['source'],
                        'chunk_count': row['chunk_count'],
                        'created_at': row['created_at'],
                        'metadata': json.loads(row['metadata'])
                    }
                    for row in rows
                ]

    async def get_document(self, doc_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM documents WHERE id = ?', (doc_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        'id': row['id'],
                        'repo_name': row['repo_name'],
                        'source': row['source'],
                        'full_text': row['full_text'],
                        'metadata': json.loads(row['metadata']),
                        'created_at': row['created_at'],
                        'chunk_count': row['chunk_count']
                    }
                return None

    async def delete_document(self, doc_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
            await db.commit()

    async def get_document_count(self, repo_name: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT COUNT(*) FROM documents WHERE repo_name = ?', (repo_name,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
