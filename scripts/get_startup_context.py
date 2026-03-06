#!/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/venv/bin/python
"""
Get Startup Context - Enhanced SQLite-based activity summary.

Provides comprehensive "waking up already here" context:
- Recent conversation activity across all channels
- Active terminal sessions and interactions
- Recent conversation partners
- Daemon activity traces
- Time ranges and activity patterns

This complements PPS ambient_recall (which provides crystals/word-photos/summaries)
by giving immediate awareness of what's been happening recently.

Database: Reads from $ENTITY_PATH/data/conversations.db (not lyra.db).
The conversations.db is the canonical source for all captured interactions.

Usage:
    python3 scripts/get_startup_context.py [--hours N] [--json]

    # Quick 24-hour view
    python3 scripts/get_startup_context.py --hours 24

    # Last week with JSON output
    python3 scripts/get_startup_context.py --hours 168 --json
"""

import sys
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import argparse
import os


def format_timestamp(ts_str):
    """Format ISO timestamp to human-readable relative time."""
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

        # Handle future timestamps
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
    except Exception:
        return ts_str


def get_channel_activity(cursor, cutoff):
    """Get recent channel activity summary."""
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

    return channels


def get_conversation_partners(cursor, cutoff):
    """Get recent conversation partners."""
    cursor.execute("""
        SELECT
            author_name,
            COUNT(*) as message_count,
            MAX(created_at) as last_seen,
            GROUP_CONCAT(DISTINCT channel) as channels
        FROM messages
        WHERE created_at > ? AND author_name IS NOT NULL AND is_lyra = 0
        GROUP BY author_name
        ORDER BY last_seen DESC
        LIMIT 10
    """, (cutoff,))

    partners = []
    for row in cursor.fetchall():
        partners.append({
            "name": row["author_name"],
            "messages": row["message_count"],
            "last_seen": format_timestamp(row["last_seen"]),
            "channels": row["channels"].split(",") if row["channels"] else []
        })

    return partners


def get_terminal_sessions(cursor, cutoff):
    """Get recent terminal session activity."""
    cursor.execute("""
        SELECT
            ts.session_id,
            ts.started_at,
            ts.ended_at,
            ts.working_dir,
            COUNT(ti.id) as interaction_count
        FROM terminal_sessions ts
        LEFT JOIN terminal_interactions ti ON ts.session_id = ti.session_id
        WHERE ts.started_at > ?
        GROUP BY ts.session_id
        ORDER BY ts.started_at DESC
        LIMIT 10
    """, (cutoff,))

    sessions = []
    for row in cursor.fetchall():
        session = {
            "session_id": row["session_id"][:12],  # Truncate for readability
            "started": format_timestamp(row["started_at"]),
            "ended": format_timestamp(row["ended_at"]) if row["ended_at"] else "active",
            "working_dir": row["working_dir"],
            "interactions": row["interaction_count"]
        }
        sessions.append(session)

    return sessions


def get_daemon_activity(cursor, cutoff):
    """Get recent daemon activity traces."""
    cursor.execute("""
        SELECT
            daemon_type,
            COUNT(*) as event_count,
            MAX(timestamp) as last_activity,
            COUNT(DISTINCT session_id) as session_count
        FROM daemon_traces
        WHERE timestamp > ?
        GROUP BY daemon_type
        ORDER BY last_activity DESC
    """, (cutoff,))

    daemons = []
    for row in cursor.fetchall():
        daemons.append({
            "daemon": row["daemon_type"],
            "events": row["event_count"],
            "sessions": row["session_count"],
            "last_active": format_timestamp(row["last_activity"])
        })

    return daemons


def get_overall_stats(cursor, cutoff):
    """Get overall activity statistics."""
    cursor.execute("""
        SELECT
            COUNT(*) as total_messages,
            MIN(created_at) as first_message,
            MAX(created_at) as last_message
        FROM messages
        WHERE created_at > ?
    """, (cutoff,))

    stats = cursor.fetchone()

    # Get total lifetime messages
    cursor.execute("SELECT COUNT(*) as total FROM messages")
    total_row = cursor.fetchone()

    return {
        "period_messages": stats["total_messages"],
        "lifetime_messages": total_row["total"],
        "last_activity": format_timestamp(stats["last_message"]) if stats["last_message"] else "unknown"
    }


def get_startup_context(entity_path, hours_back=48):
    """
    Get comprehensive startup context from SQLite conversations database.

    Args:
        entity_path: Path to entity directory
        hours_back: Hours of history to analyze

    Returns:
        Dictionary with startup context data
    """
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
    cutoff = (datetime.now() - timedelta(hours=hours_back)).isoformat()

    # Gather all context
    context = {
        "period": f"Last {hours_back} hours",
        "stats": get_overall_stats(cursor, cutoff),
        "channels": get_channel_activity(cursor, cutoff),
        "partners": get_conversation_partners(cursor, cutoff),
        "terminal_sessions": get_terminal_sessions(cursor, cutoff),
        "daemon_activity": get_daemon_activity(cursor, cutoff)
    }

    conn.close()
    return context


def print_context(context):
    """Pretty-print the startup context."""

    if "error" in context:
        print(f"Error: {context['error']}")
        return

    print("=" * 70)
    print("STARTUP CONTEXT - Recent Activity Summary")
    print("=" * 70)
    print()

    # Overall stats
    stats = context["stats"]
    print(f"Period: {context['period']}")
    print(f"Recent messages: {stats['period_messages']} (lifetime: {stats['lifetime_messages']})")
    print(f"Last activity: {stats['last_activity']}")
    print()

    # Channel activity
    if context["channels"]:
        print("Active Channels:")
        print("-" * 70)
        for ch in context["channels"][:8]:  # Top 8 channels
            print(f"  {ch['channel']:30} {ch['messages']:4} msgs  {ch['participants']:2} people  {ch['last_active']}")
        print()

    # Conversation partners
    if context["partners"]:
        print("Recent Partners:")
        print("-" * 70)
        for p in context["partners"][:8]:  # Top 8 partners
            channels_str = ", ".join(p['channels'][:2])  # First 2 channels
            if len(p['channels']) > 2:
                channels_str += "..."
            print(f"  {p['name']:20} {p['messages']:4} msgs  [{channels_str}]  {p['last_seen']}")
        print()

    # Terminal sessions
    if context["terminal_sessions"]:
        print("Terminal Sessions:")
        print("-" * 70)
        for s in context["terminal_sessions"][:5]:  # Last 5 sessions
            status = "ACTIVE" if s['ended'] == "active" else f"ended {s['ended']}"
            print(f"  {s['session_id']}  {s['interactions']:3} turns  {status}  started {s['started']}")
            if s['working_dir']:
                print(f"    → {s['working_dir']}")
        print()

    # Daemon activity
    if context["daemon_activity"]:
        print("Daemon Activity:")
        print("-" * 70)
        for d in context["daemon_activity"]:
            print(f"  {d['daemon']:15} {d['events']:5} events  {d['sessions']:2} sessions  {d['last_active']}")
        print()

    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Get SQLite-based startup context for recent activity awareness"
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=48,
        help="Hours of history to analyze (default: 48)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted text"
    )

    args = parser.parse_args()

    # Get entity path from environment
    entity_path = os.environ.get("ENTITY_PATH", "/home/jeff/.claude/pps-lyra")

    # Get context
    context = get_startup_context(entity_path, args.hours)

    # Output
    if args.json:
        print(json.dumps(context, indent=2))
    else:
        print_context(context)
