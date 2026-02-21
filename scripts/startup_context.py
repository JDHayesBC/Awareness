#!/usr/bin/env python3
"""
Startup Context - SQLite-based activity summary for autonomous reflection.

Provides a quick snapshot of recent activity when waking up:
- Recent conversation activity across channels
- Active terminal sessions
- Recent partners/collaborators
- Time since last activity

This complements PPS ambient_recall by providing immediate "what's been
happening" awareness without requiring full memory reconstruction.

Usage:
    python3 scripts/startup_context.py [--days N]
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import argparse
import os


def format_timestamp(ts_str):
    """Format ISO timestamp to human-readable."""
    try:
        # Parse timestamp (handle both with and without timezone)
        if 'Z' in ts_str or '+' in ts_str:
            dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        else:
            # Assume local timezone if none specified
            dt = datetime.fromisoformat(ts_str)
            now = datetime.now()

        delta = now - dt

        # Handle future timestamps (shouldn't happen but just in case)
        if delta.total_seconds() < 0:
            return "just now"

        if delta.total_seconds() < 60:
            return "just now"
        elif delta.total_seconds() < 3600:
            mins = int(delta.total_seconds() / 60)
            return f"{mins}m ago"
        elif delta.total_seconds() < 86400:
            hours = int(delta.total_seconds() / 3600)
            return f"{hours}h ago"
        else:
            days = int(delta.total_seconds() / 86400)
            return f"{days}d ago"
    except Exception as e:
        return ts_str


def get_startup_context(entity_path, days_back=7):
    """Get startup context from SQLite conversations database."""

    db_path = Path(entity_path) / "data" / "conversations.db"

    if not db_path.exists():
        return {
            "error": f"Database not found: {db_path}",
            "entity_path": entity_path
        }

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Calculate cutoff time
    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()

    # Get recent activity summary
    cursor.execute("""
        SELECT
            channel,
            COUNT(*) as message_count,
            MAX(created_at) as last_activity,
            COUNT(DISTINCT author_name) as unique_authors
        FROM messages
        WHERE created_at > ?
        GROUP BY channel
        ORDER BY last_activity DESC
    """, (cutoff,))

    channels = []
    for row in cursor.fetchall():
        channels.append({
            "channel": row["channel"] or "unknown",
            "messages": row["message_count"],
            "last_active": format_timestamp(row["last_activity"]),
            "participants": row["unique_authors"]
        })

    # Get recent authors/partners
    cursor.execute("""
        SELECT
            author_name,
            COUNT(*) as message_count,
            MAX(created_at) as last_seen
        FROM messages
        WHERE created_at > ? AND author_name IS NOT NULL
        GROUP BY author_name
        ORDER BY last_seen DESC
        LIMIT 10
    """, (cutoff,))

    partners = []
    for row in cursor.fetchall():
        partners.append({
            "name": row["author_name"],
            "messages": row["message_count"],
            "last_seen": format_timestamp(row["last_seen"])
        })

    # Get overall stats
    cursor.execute("""
        SELECT
            COUNT(*) as total_messages,
            MIN(created_at) as first_message,
            MAX(created_at) as last_message
        FROM messages
        WHERE created_at > ?
    """, (cutoff,))

    stats = cursor.fetchone()

    # Get total conversation count
    cursor.execute("SELECT COUNT(*) as total FROM messages")
    total_row = cursor.fetchone()

    conn.close()

    return {
        "period": f"Last {days_back} days",
        "total_messages": stats["total_messages"],
        "total_conversations": total_row["total"],
        "last_activity": format_timestamp(stats["last_message"]) if stats["last_message"] else "unknown",
        "channels": channels,
        "partners": partners
    }


def print_context(context):
    """Pretty-print the startup context."""

    if "error" in context:
        print(f"❌ {context['error']}")
        return

    print("📊 Startup Context")
    print("=" * 60)
    print(f"Period: {context['period']}")
    print(f"Recent messages: {context['total_messages']}")
    print(f"Total conversations: {context['total_conversations']}")
    print(f"Last activity: {context['last_activity']}")
    print()

    if context["channels"]:
        print("📺 Active Channels:")
        for ch in context["channels"][:5]:  # Top 5
            print(f"  • {ch['channel']}: {ch['messages']} messages, {ch['participants']} participants ({ch['last_active']})")
        print()

    if context["partners"]:
        print("👥 Recent Partners:")
        for p in context["partners"][:5]:  # Top 5
            print(f"  • {p['name']}: {p['messages']} messages ({p['last_seen']})")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get SQLite startup context")
    parser.add_argument("--days", type=int, default=7, help="Days of history to check (default: 7)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    # Get entity path from environment
    entity_path = os.environ.get("ENTITY_PATH", "/home/jeff/.claude/pps-lyra")

    context = get_startup_context(entity_path, args.days)

    if args.json:
        import json
        print(json.dumps(context, indent=2))
    else:
        print_context(context)
