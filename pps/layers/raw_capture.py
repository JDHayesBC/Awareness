"""
Layer 1: Raw Capture (SQLite)

Everything, unfiltered. The source of truth that can rebuild other layers if needed.
Currently reads from the Discord SQLite database; will expand to capture terminal sessions too.
"""

import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Generator

from . import PatternLayer, LayerType, SearchResult, LayerHealth

logger = logging.getLogger(__name__)

NOTHING_SEARCHABLE = (
    "Nothing searchable in that query (only punctuation or very common words)."
)

# Question words and glue. Dropped from the all-words pass when at least two
# other tokens remain, so "how does Jeff take his coffee" is not defeated by "does".
STOPWORDS = frozenset(
    "how does did do what when where who why the a an his her their my our we i "
    "you about of to in on for is was are were it that this and or".split()
)

_QUOTED_RE = re.compile(r'"([^"]*)"')
_CHUNK_RE = re.compile(r'[^\s"]+')          # whitespace-delimited piece
_RUN_RE = re.compile(r"[^\W_]+")            # letters/digits, any script
_JOIN_RE = re.compile("^[-_'.\u2019]+$")     # glue that keeps pieces one compound
_POSSESSIVE_RE = re.compile("['\u2019][sS]$")


def build_fts_terms(query: str) -> tuple[list[str], list[str], list[str]]:
    """Turn free text into (all-words terms, any-word terms, display labels).

    Every term is wrapped in double quotes so no input can be read as FTS5
    syntax (including bare AND / OR / NOT).

    Phrases: a "quoted phrase" stays a phrase, and so does a run of pieces glued
    by - _ . ' with no whitespace (hot-tub, email_id, 2026-11-17, don't). The
    unicode61 tokenizer splits on those characters at index time, so the phrase
    "hot tub" matches both "hot-tub" and "hot tub" in a message, while two
    independent words would also match rows where the words are far apart.
    A trailing 's is dropped first, so Jeff's is the plain word jeff. Any other
    punctuation separates words. Phrases are never treated as stopwords.

    Stopwords are dropped when at least two content items remain; the any-word
    terms never include stopwords. A query with no content item at all is
    unsearchable and yields empty lists.
    """
    phrases: list[str] = []
    for m in _QUOTED_RE.finditer(query):
        toks = [t.lower() for t in _RUN_RE.findall(m.group(1))]
        if toks:
            phrases.append(" ".join(toks))
    rest = _QUOTED_RE.sub(" ", query)
    words: list[str] = []
    for chunk in _CHUNK_RE.findall(rest):
        chunk = _POSSESSIVE_RE.sub("", chunk)
        parts: list[str] = []
        glued = True
        pos = 0
        for m in _RUN_RE.finditer(chunk):
            if parts and not _JOIN_RE.match(chunk[pos:m.start()]):
                glued = False
            parts.append(m.group(0).lower())
            pos = m.end()
        if not parts:
            continue
        if len(parts) > 1 and glued:
            phrases.append(" ".join(parts))
        else:
            words.extend(parts)
    phrases = list(dict.fromkeys(phrases))
    content = [w for w in words if w not in STOPWORDS]
    if not content and not phrases:
        return [], [], []
    if len(content) + len(phrases) >= 2:
        words = content
    items = [('"%s"' % p, '"%s"' % p) for p in phrases]
    seen: set[str] = set()
    for w in words:
        if w in seen:
            continue
        seen.add(w)
        items.append(('"%s"' % w, w))
    content_set = set(content)
    any_terms = [t for t, _ in items[:len(phrases)]] + [
        t for t, d in items[len(phrases):] if d in content_set
    ]
    return [t for t, _ in items], any_terms, [d for _, d in items]


@dataclass
class RawSearchOutcome:
    """Results plus a one-line receipt saying what was searched."""
    results: list = field(default_factory=list)
    receipt: str = ""
    error: Optional[str] = None   # exception class name when the search failed
    total_all: int = 0            # rows matching every term
    any_total: int = 0            # further rows matching some term


class RawCaptureLayer(PatternLayer):
    """
    Layer 1: Raw Capture

    Stores everything in SQLite. Nothing is truly lost.
    Currently connects to the existing Discord message database.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the raw capture layer.

        Args:
            db_path: Path to SQLite database. Defaults to $ENTITY_PATH/data/conversations.db
        """
        if db_path is None:
            # Database now in entity directory (Issue #131 migration)
            entity_path = os.getenv("ENTITY_PATH", str(Path.home() / ".claude"))
            db_path = Path(entity_path) / "data" / "conversations.db"
        self.db_path = db_path

    def _connect_with_wal(self) -> sqlite3.Connection:
        """
        Create a SQLite connection with WAL mode enabled for better concurrency.

        WAL (Write-Ahead Logging) mode allows concurrent reads and writes,
        improving performance when multiple processes access the database.

        Note: Prefer using get_connection() context manager instead of calling
        this method directly to ensure connections are properly closed.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Enable WAL mode for concurrent access
        conn.execute("PRAGMA journal_mode=WAL")
        # 5 second busy timeout for better handling of concurrent access
        conn.execute("PRAGMA busy_timeout=5000")
        # NORMAL sync mode is safe with WAL and faster than FULL
        conn.execute("PRAGMA synchronous=NORMAL")

        return conn

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database connections.

        Ensures connections are properly closed even if an exception occurs.

        Usage:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # ... do work ...
        """
        conn = self._connect_with_wal()
        try:
            yield conn
        finally:
            # Force WAL checkpoint on Docker bind mounts where .shm isn't shared
            # across the host/container boundary, causing writes to be invisible
            # from the host until the WAL is checkpointed to the main db file.
            if os.getenv("RUNNING_IN_DOCKER") or os.getenv("ENTITY_PATH", "").startswith("/app/"):
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:
                    pass  # Best effort - don't crash on checkpoint failure
            conn.close()

    @property
    def layer_type(self) -> LayerType:
        return LayerType.RAW_CAPTURE

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """
        Search raw captured content using SQLite FTS5 (strict, all-words only).

        The query is turned into quoted tokens, so punctuation cannot break the
        FTS5 parser. This keeps the old "every word must match" meaning for the
        callers that depend on it (the email dedup check, ambient recall); the
        any-word fallback and the receipt live in search_with_receipt().

        Raises on a database failure instead of returning an empty list, because
        an empty list reads as "nothing in memory".
        """
        outcome = await self.search_with_receipt(query, limit, any_fallback=False)
        if outcome.error:
            raise RuntimeError(outcome.receipt)
        return outcome.results

    async def search_with_receipt(
        self, query: str, limit: int = 10, any_fallback: bool = True
    ) -> "RawSearchOutcome":
        """
        Two-pass search that says what it searched.

        Pass 1 requires every token (common glue words dropped when at least two
        real tokens remain). Pass 2, if pass 1 did not fill the limit, adds rows
        matching any token, ranked by bm25. Never raises: a failure comes back
        with error set and a receipt that says so.
        """
        terms, any_terms, shown = build_fts_terms(query)
        if not terms:
            return RawSearchOutcome([], NOTHING_SEARCHABLE)
        try:
            with self.get_connection() as conn:
                if not self._ensure_fts(conn):
                    return RawSearchOutcome([], "Search failed: the message store has no messages table yet.", error="NoMessagesTable")
                return self._run_passes(conn, terms, any_terms, shown, limit, any_fallback)
        except Exception as e:
            logger.exception("raw_search failed for query %r", query)
            name = type(e).__name__
            return RawSearchOutcome(
                [], f'Search failed: {name}. This is not a "no results" answer.', error=name
            )

    def _ensure_fts(self, conn: sqlite3.Connection) -> bool:
        """Make sure messages_fts exists, creating it from messages if needed."""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
        )
        if cursor.fetchone() is not None:
            return True
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        if not cursor.fetchone():
            return False
        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content,
                author_name,
                channel,
                content='messages',
                content_rowid='id'
            )
        ''')
        cursor.execute('''
            INSERT INTO messages_fts(rowid, content, author_name, channel)
            SELECT id, content, author_name, channel FROM messages
        ''')
        conn.commit()
        return True

    _SELECT = '''
        SELECT m.id, m.content, m.author_name, m.channel, m.created_at,
               m.is_lyra, messages_fts.rank AS rank
        FROM messages_fts
        JOIN messages m ON messages_fts.rowid = m.id
        WHERE messages_fts MATCH ?
    '''

    def _rows_to_results(self, rows) -> list[SearchResult]:
        results = []
        for row in rows:
            # FTS5 rank is negative, lower is better
            relevance = max(0.1, min(1.0, 1.0 / (abs(row['rank']) + 1)))
            results.append(SearchResult(
                content=row['content'],
                source=f"{row['channel']}:{row['id']}",
                layer=self.layer_type,
                relevance_score=relevance,
                metadata={
                    'id': row['id'],
                    'author': row['author_name'],
                    'channel': row['channel'],
                    'timestamp': row['created_at'],
                    'is_lyra': bool(row['is_lyra']),
                    'fts_rank': row['rank'],
                },
            ))
        return results

    def _run_passes(self, conn, terms, any_terms, shown, limit, any_fallback) -> "RawSearchOutcome":
        cursor = conn.cursor()
        # Column filter: match message text only, so a name does not match
        # every row that person wrote.
        and_q = "content : (" + " ".join(terms) + ")"
        cursor.execute(
            self._SELECT + " ORDER BY messages_fts.rank, m.created_at DESC LIMIT ?",
            (and_q, limit),
        )
        pass1 = self._rows_to_results(cursor.fetchall())
        cursor.execute(
            "SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH ?", (and_q,)
        )
        total_all = cursor.fetchone()[0]
        label = ", ".join(shown)

        results = list(pass1)
        any_total = 0
        any_shown = 0
        ran_any = False
        if any_fallback and len(pass1) < limit and (len(any_terms) > 1 or any_terms != terms):
            ran_any = True
            seen = [r.metadata['id'] for r in pass1]
            or_q = "content : (" + " OR ".join(any_terms) + ")"
            excl = ""
            params: list = [or_q]
            if seen:
                excl = " AND m.id NOT IN (%s)" % ",".join("?" * len(seen))
                params += seen
            # No join: rows matching every term are a subset of rows matching any
            # term, and pass 1 returned all of its matches (it was under the limit),
            # so subtracting its length gives the extra count without one lookup per row.
            cursor.execute(
                "SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH ?", (or_q,)
            )
            any_total = max(0, cursor.fetchone()[0] - len(pass1))
            cursor.execute(
                self._SELECT + excl + " ORDER BY messages_fts.rank LIMIT ?",
                params + [limit - len(pass1)],
            )
            extra = self._rows_to_results(cursor.fetchall())
            any_shown = len(extra)
            results += extra

        if not results:
            return RawSearchOutcome([], f"No message contains any of [{label}].", total_all=0)

        noun = "message" if total_all == 1 else "messages"
        receipt = f"Searched for all of [{label}]: {total_all} {noun}."
        if total_all > len(pass1):
            receipt += f" Best {len(pass1)} shown."
        if ran_any:
            receipt += f" Any of them: {any_total} more, best {any_shown} shown."
        return RawSearchOutcome(
            results, receipt, total_all=total_all, any_total=any_total
        )

    async def store(self, content: str, metadata: Optional[dict] = None) -> bool:
        """
        Store content in raw capture.

        Args:
            content: The message content to store
            metadata: Optional metadata dict with keys:
                - author_name: Name of message author
                - channel: Channel identifier (e.g. "discord:channel-name", "terminal")
                - is_lyra: Whether this message is from Lyra
                - discord_message_id: Original Discord message ID (if applicable)
        """
        try:
            # Extract metadata with defaults
            if metadata is None:
                metadata = {}

            author_name = metadata.get('author_name', 'Unknown')
            channel = metadata.get('channel', 'terminal')
            is_lyra = metadata.get('is_lyra', False)
            discord_message_id = metadata.get('discord_message_id')

            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Insert into messages table
                # Note: channel_id is required (NOT NULL) - use 0 for terminal sources
                cursor.execute('''
                    INSERT OR IGNORE INTO messages
                    (discord_message_id, channel_id, channel, author_id, author_name, content, is_lyra, is_bot, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ''', (
                    discord_message_id,
                    0,  # channel_id - use 0 for non-Discord sources
                    channel,
                    0,  # author_id - use 0 for non-Discord sources
                    author_name,
                    content,
                    is_lyra,
                    is_lyra  # is_bot - assume Lyra messages are bot messages
                ))

                # If we inserted a new row, also update FTS5 table if it exists
                if cursor.rowcount > 0:
                    row_id = cursor.lastrowid

                    # Check if FTS5 table exists
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
                    )
                    if cursor.fetchone():
                        # Update FTS5 table
                        cursor.execute('''
                            INSERT INTO messages_fts(rowid, content, author_name, channel)
                            VALUES (?, ?, ?, ?)
                        ''', (row_id, content, author_name, channel))

                conn.commit()
                return True

        except Exception as e:
            return False

    async def health(self) -> LayerHealth:
        """Check if SQLite database is accessible."""
        try:
            if not self.db_path.exists():
                return LayerHealth(
                    available=False,
                    message=f"Database not found: {self.db_path}",
                    details={"db_path": str(self.db_path)}
                )

            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
                table_count = cursor.fetchone()[0]

            return LayerHealth(
                available=True,
                message=f"SQLite connected ({table_count} tables)",
                details={"db_path": str(self.db_path), "table_count": table_count}
            )
        except Exception as e:
            return LayerHealth(
                available=False,
                message=f"SQLite error: {e}",
                details={"error": str(e)}
            )
