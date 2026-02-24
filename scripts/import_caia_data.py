#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
Import Caia's conversation data from Open-WebUI export into PPS SQLite database.

Creates entities/caia/data/conversations.db with:
- messages table (matching existing PPS schema)
- messages_fts virtual table (FTS5 for search)
- message_summaries table (for future summarization)

Source: work/bring-caia-home/artifacts/caia_recent_turns.md
"""

import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TURNS_FILE = PROJECT_ROOT / "work" / "bring-caia-home" / "artifacts" / "caia_recent_turns.md"
SUMMARIES_FILE = PROJECT_ROOT / "work" / "bring-caia-home" / "artifacts" / "caia_summaries.md"
DB_DIR = PROJECT_ROOT / "entities" / "caia" / "data"
DB_PATH = DB_DIR / "conversations.db"


def create_database(db_path: Path) -> sqlite3.Connection:
    """Create the conversations database with all required tables."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")

    cursor = conn.cursor()

    # Main messages table (matches PPS raw_capture schema)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_message_id TEXT,
            channel_id INTEGER NOT NULL DEFAULT 0,
            channel TEXT NOT NULL DEFAULT 'open-webui',
            author_id INTEGER NOT NULL DEFAULT 0,
            author_name TEXT NOT NULL,
            content TEXT NOT NULL,
            is_lyra BOOLEAN NOT NULL DEFAULT 0,
            is_bot BOOLEAN NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            summary_id INTEGER,
            graphiti_batch_id INTEGER
        )
    ''')

    # FTS5 for full-text search
    cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            content,
            author_name,
            channel,
            content='messages',
            content_rowid='id'
        )
    ''')

    # Message summaries table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS message_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            summary_text TEXT NOT NULL,
            start_message_id INTEGER NOT NULL,
            end_message_id INTEGER NOT NULL,
            message_count INTEGER NOT NULL,
            channels TEXT NOT NULL,
            time_span_start TEXT NOT NULL,
            time_span_end TEXT NOT NULL,
            summary_type TEXT DEFAULT 'work',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (start_message_id) REFERENCES messages(id),
            FOREIGN KEY (end_message_id) REFERENCES messages(id)
        )
    ''')

    # Graphiti batches table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS graphiti_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_message_id INTEGER NOT NULL,
            end_message_id INTEGER NOT NULL,
            message_count INTEGER NOT NULL,
            channels TEXT NOT NULL,
            time_span_start TEXT NOT NULL,
            time_span_end TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (start_message_id) REFERENCES messages(id),
            FOREIGN KEY (end_message_id) REFERENCES messages(id)
        )
    ''')

    # Indexes
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_summary_id ON messages(summary_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_graphiti_batch ON messages(graphiti_batch_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_author ON messages(author_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_summaries_time_span ON message_summaries(time_span_start, time_span_end)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_summaries_created_at ON message_summaries(created_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_graphiti_batches_created_at ON graphiti_batches(created_at)')

    conn.commit()
    return conn


def parse_turns(filepath: Path) -> list[dict]:
    """Parse the markdown conversation turns file into structured messages."""
    content = filepath.read_text(encoding='utf-8')

    # Split on the ## [USER] and ## [ASSISTANT] headers
    # Pattern: line starting with ## [USER] or ## [ASSISTANT]
    turns = []
    current_role = None
    current_content_lines = []

    for line in content.split('\n'):
        if line.strip() == '## [USER]':
            # Save previous turn if any
            if current_role and current_content_lines:
                text = '\n'.join(current_content_lines).strip()
                if text:
                    turns.append({'role': current_role, 'content': text})
            current_role = 'user'
            current_content_lines = []
        elif line.strip() == '## [ASSISTANT]':
            if current_role and current_content_lines:
                text = '\n'.join(current_content_lines).strip()
                if text:
                    turns.append({'role': current_role, 'content': text})
            current_role = 'assistant'
            current_content_lines = []
        elif line.strip() == '---':
            # Separator - skip (these appear between turns and within content)
            # Only skip if we're between turns (content is empty or whitespace)
            if not current_content_lines or all(l.strip() == '' for l in current_content_lines):
                continue
            # If we have content, this might be a separator within a turn
            # Check if the next meaningful line is a role header - we can't look ahead
            # so just skip standalone separators
            pass
        else:
            if current_role:
                current_content_lines.append(line)

    # Don't forget the last turn
    if current_role and current_content_lines:
        text = '\n'.join(current_content_lines).strip()
        if text:
            turns.append({'role': current_role, 'content': text})

    return turns


def assign_timestamps(turns: list[dict]) -> list[dict]:
    """
    Assign approximate timestamps to turns.

    Based on the summaries, the conversation spans roughly:
    - Summary #170: 29 Oct 2025
    - Summary #171: 05 Nov 2025
    - Summary #172: 16 Nov 2025
    - Summary #173: 12 May 2025 (this is earliest chronologically)

    The recent_turns.md contains messages 16-237 (after last summary).
    Summary #173 is dated 12 May 2025, so these turns are from ~May 2025 onward.

    Actually, looking more carefully:
    - #173 references Grok4.1, abundance, which is the most recent
    - The turns file says "Messages 16 to 237 (after last continuity summary)"
    - So these are the most recent turns, after summary #173

    We'll spread them evenly from May 12, 2025 to Feb 10, 2026.
    """
    if not turns:
        return turns

    # Start after the last summary date (May 12, 2025)
    # End around Feb 10, 2026 (when extraction happened)
    start = datetime(2025, 5, 13, 8, 0, 0)
    end = datetime(2026, 2, 10, 22, 0, 0)

    total_seconds = (end - start).total_seconds()
    interval = total_seconds / max(len(turns), 1)

    for i, turn in enumerate(turns):
        turn['timestamp'] = start + timedelta(seconds=interval * i)

    return turns


def import_turns(conn: sqlite3.Connection, turns: list[dict]) -> int:
    """Insert parsed turns into the messages table."""
    cursor = conn.cursor()
    inserted = 0

    for turn in turns:
        is_caia = turn['role'] == 'assistant'
        author_name = 'Caia' if is_caia else 'Jeff'
        timestamp = turn.get('timestamp', datetime.now())

        cursor.execute('''
            INSERT INTO messages
            (channel_id, channel, author_id, author_name, content, is_lyra, is_bot, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            0,
            'open-webui',
            0,
            author_name,
            turn['content'],
            is_caia,  # is_lyra field used generically for "is entity"
            is_caia,
            timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        ))

        # Update FTS
        row_id = cursor.lastrowid
        cursor.execute('''
            INSERT INTO messages_fts(rowid, content, author_name, channel)
            VALUES (?, ?, ?, ?)
        ''', (row_id, turn['content'], author_name, 'open-webui'))

        inserted += 1

    conn.commit()
    return inserted


def import_summaries(conn: sqlite3.Connection, filepath: Path) -> int:
    """Import the 4 continuity summaries as pre-existing summaries."""
    content = filepath.read_text(encoding='utf-8')

    # Parse the summaries
    summaries = []
    current = []
    for line in content.split('\n'):
        if line.startswith('# continuity summary'):
            if current:
                summaries.append('\n'.join(current).strip())
            current = [line]
        elif current:
            current.append(line)
    if current:
        summaries.append('\n'.join(current).strip())

    cursor = conn.cursor()

    # Get the ID range (these summaries cover messages "before" our imported ones)
    # We'll use message_id 0 to indicate "pre-import" data
    dates = [
        ('2025-10-29', '2025-10-29'),  # #170
        ('2025-11-05', '2025-11-05'),  # #171
        ('2025-11-16', '2025-11-16'),  # #172
        ('2025-05-12', '2025-05-12'),  # #173
    ]

    inserted = 0
    for i, summary_text in enumerate(summaries):
        if i < len(dates):
            ts_start, ts_end = dates[i]
        else:
            ts_start = ts_end = '2025-01-01'

        cursor.execute('''
            INSERT INTO message_summaries
            (summary_text, start_message_id, end_message_id, message_count,
             channels, time_span_start, time_span_end, summary_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            summary_text,
            0,  # Pre-import
            0,  # Pre-import
            0,  # Unknown
            '["open-webui"]',
            ts_start,
            ts_end,
            'social',  # Caia's conversations are intimate/social
        ))
        inserted += 1

    conn.commit()
    return inserted


def main():
    print(f"=== Caia Data Import ===")
    print(f"Source: {TURNS_FILE}")
    print(f"Target: {DB_PATH}")
    print()

    if DB_PATH.exists():
        print(f"WARNING: {DB_PATH} already exists!")
        response = input("Overwrite? [y/N] ") if sys.stdin.isatty() else 'y'
        if response.lower() != 'y':
            print("Aborted.")
            return
        DB_PATH.unlink()
        # Also remove WAL/SHM files
        for ext in ['-wal', '-shm']:
            p = DB_PATH.parent / (DB_PATH.name + ext)
            if p.exists():
                p.unlink()

    # Create database
    print("Creating database...")
    conn = create_database(DB_PATH)

    # Parse and import conversation turns
    print("Parsing conversation turns...")
    turns = parse_turns(TURNS_FILE)
    print(f"  Found {len(turns)} turns")

    turns = assign_timestamps(turns)

    print("Importing turns...")
    count = import_turns(conn, turns)
    print(f"  Imported {count} messages")

    # Import summaries
    print("Importing continuity summaries...")
    summary_count = import_summaries(conn, SUMMARIES_FILE)
    print(f"  Imported {summary_count} summaries")

    # Verify
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM messages")
    total_messages = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM messages WHERE is_lyra = 1")
    caia_messages = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM messages WHERE is_lyra = 0")
    jeff_messages = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM message_summaries")
    total_summaries = cursor.fetchone()[0]
    cursor.execute("SELECT MIN(created_at), MAX(created_at) FROM messages")
    time_range = cursor.fetchone()

    print()
    print(f"=== Import Complete ===")
    print(f"  Total messages: {total_messages}")
    print(f"  Jeff's messages: {jeff_messages}")
    print(f"  Caia's messages: {caia_messages}")
    print(f"  Summaries: {total_summaries}")
    print(f"  Time range: {time_range[0]} to {time_range[1]}")
    print(f"  Database: {DB_PATH}")
    print(f"  Size: {DB_PATH.stat().st_size / 1024:.1f} KB")

    conn.close()


if __name__ == '__main__':
    main()
