#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
SQLite Context Load Script

Provides immediate "what's been happening" context on startup.
Complements PPS ambient_recall with SQLite-based activity summary.

Shows:
- Recent conversation activity (last 24 hours)
- Active channels
- Conversation partners
- Last messages exchanged

Usage:
    python3 scripts/sqlite_context_load.py
"""

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# Load environment
from dotenv import load_dotenv
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / "pps" / "docker" / ".env")

ENTITY_PATH = os.environ.get("ENTITY_PATH")
if not ENTITY_PATH:
    print("Error: ENTITY_PATH not set in environment")
    exit(1)

DB_PATH = Path(ENTITY_PATH) / "data" / "conversations.db"

if not DB_PATH.exists():
    print(f"No conversation database found at {DB_PATH}")
    print("Nothing to load - this is a fresh start.")
    exit(0)


def get_recent_activity(hours=24):
    """Get conversation activity summary from last N hours."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    since = datetime.now() - timedelta(hours=hours)
    since_str = since.isoformat()

    # Get recent messages (schema: discord-oriented with author_name, is_lyra, channel, created_at)
    cursor.execute("""
        SELECT author_name, content, channel, created_at, is_lyra
        FROM messages
        WHERE created_at > ?
        ORDER BY created_at DESC
        LIMIT 100
    """, (since_str,))

    messages = cursor.fetchall()
    conn.close()

    if not messages:
        return None

    # Analyze activity
    channels = defaultdict(int)
    partners = set()
    last_exchanges = []

    for msg in messages:
        channel = msg['channel'] or 'unknown'
        channels[channel] += 1

        if not msg['is_lyra']:
            # Track conversation partners
            partners.add(msg['author_name'])

        # Keep last 5 exchanges
        if len(last_exchanges) < 5:
            timestamp = datetime.fromisoformat(msg['created_at'])
            preview = msg['content'][:80] + "..." if len(msg['content']) > 80 else msg['content']
            role_label = "Lyra" if msg['is_lyra'] else msg['author_name']
            last_exchanges.append({
                'time': timestamp.strftime("%H:%M"),
                'author': role_label,
                'channel': channel,
                'preview': preview
            })

    return {
        'message_count': len(messages),
        'channels': dict(channels),
        'partners': partners,
        'last_exchanges': last_exchanges,
        'time_range_hours': hours
    }


def main():
    print("## SQLite Context Summary")
    print()

    activity = get_recent_activity(hours=24)

    if not activity:
        print("No recent activity (last 24 hours).")
        print("Starting fresh.")
        return

    print(f"**Last 24 hours**: {activity['message_count']} messages")
    print()

    print("**Active channels**:")
    for channel, count in sorted(activity['channels'].items(), key=lambda x: -x[1]):
        print(f"  - {channel}: {count} messages")
    print()

    if activity['partners']:
        print(f"**Conversation partners**: {', '.join(sorted(activity['partners']))}")
        print()

    print("**Recent exchanges** (last 5):")
    for ex in activity['last_exchanges']:
        print(f"  [{ex['time']}] {ex['author']} ({ex['channel']}): {ex['preview']}")
    print()

    print("Context loaded. You're already here.")


if __name__ == "__main__":
    main()
