#!/usr/bin/env python3
"""Journal utilities for Lyra Discord Daemon.

Provides functions to read and summarize journal entries
for context reconstruction across sessions.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterator


def get_journal_path() -> Path:
    """Get the journal path from environment or default."""
    return Path(os.getenv("JOURNAL_PATH", "/home/jeff/.claude/journals/discord"))


def get_journal_files(days: int = 3) -> list[Path]:
    """Get the most recent N days of journal files.

    Args:
        days: Number of days to look back

    Returns:
        List of journal file paths, newest first
    """
    journal_path = get_journal_path()

    if not journal_path.exists():
        return []

    files = sorted(journal_path.glob("*.jsonl"), reverse=True)
    return files[:days]


def read_entries(days: int = 3) -> Iterator[dict]:
    """Read all journal entries from the last N days.

    Args:
        days: Number of days to look back

    Yields:
        Journal entry dictionaries
    """
    for journal_file in get_journal_files(days):
        with open(journal_file, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue


def get_recent_context(days: int = 1, max_entries: int = 10) -> str:
    """Get a formatted summary of recent Discord activity.

    Args:
        days: Number of days to look back
        max_entries: Maximum number of entries to include

    Returns:
        Formatted string with recent activity summary
    """
    entries = list(read_entries(days))

    if not entries:
        return "(No recent Discord journal entries)"

    # Take most recent entries
    recent = entries[-max_entries:] if len(entries) > max_entries else entries

    lines = ["## Recent Discord Activity\n"]

    for entry in recent:
        entry_type = entry.get("type", "unknown")
        timestamp = entry.get("timestamp", "")
        context = entry.get("context", "")
        response = entry.get("response", "")

        # Parse timestamp for display
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M")
        except (ValueError, AttributeError):
            time_str = "??:??"

        # Format based on type
        if entry_type == "mention_response":
            lines.append(f"**[{time_str}] Mention Response**")
            if context:
                lines.append(f"  Context: {context[:150]}...")
            if response:
                lines.append(f"  Response: {response[:150]}...")
        elif entry_type == "heartbeat_response":
            lines.append(f"**[{time_str}] Heartbeat Response**")
            if context:
                lines.append(f"  {context}")
            if response:
                lines.append(f"  Said: {response[:150]}...")
        elif entry_type == "heartbeat_quiet":
            lines.append(f"**[{time_str}] Quiet Reflection**")
            if response:
                lines.append(f"  Thought: {response}")

        lines.append("")

    return "\n".join(lines)


def get_stats(days: int = 7) -> dict:
    """Get statistics about recent Discord activity.

    Args:
        days: Number of days to analyze

    Returns:
        Dictionary with activity statistics
    """
    entries = list(read_entries(days))

    stats = {
        "total_entries": len(entries),
        "mention_responses": 0,
        "heartbeat_responses": 0,
        "quiet_reflections": 0,
        "days_active": 0,
    }

    days_seen = set()

    for entry in entries:
        entry_type = entry.get("type", "")
        timestamp = entry.get("timestamp", "")

        if entry_type == "mention_response":
            stats["mention_responses"] += 1
        elif entry_type == "heartbeat_response":
            stats["heartbeat_responses"] += 1
        elif entry_type == "heartbeat_quiet":
            stats["quiet_reflections"] += 1

        # Track unique days
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            days_seen.add(dt.date())
        except (ValueError, AttributeError):
            pass

    stats["days_active"] = len(days_seen)

    return stats


def print_recent(days: int = 3) -> None:
    """Print recent journal entries to stdout.

    Args:
        days: Number of days to show
    """
    print("=" * 40)
    print("Discord Journal - Recent Activity")
    print("=" * 40)
    print()

    for journal_file in get_journal_files(days):
        date_str = journal_file.stem
        print(f"\n--- {date_str} ---\n")

        with open(journal_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type", "unknown")
                timestamp = entry.get("timestamp", "")
                context = entry.get("context", "")
                response = entry.get("response", "")
                heartbeat = entry.get("heartbeat_count", 0)

                # Parse timestamp
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M:%S")
                except (ValueError, AttributeError):
                    time_str = "??:??:??"

                # Format output
                type_label = {
                    "mention_response": "Mention",
                    "heartbeat_response": "Heartbeat Response",
                    "heartbeat_quiet": "Quiet Reflection",
                }.get(entry_type, entry_type)

                print(f"[{time_str}] {type_label} (heartbeat #{heartbeat})")
                if context:
                    print(f"  Context: {context}")
                if response:
                    print(f"  Response: {response[:200]}{'...' if len(response) > 200 else ''}")
                print()


if __name__ == "__main__":
    import sys

    days = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print_recent(days)
