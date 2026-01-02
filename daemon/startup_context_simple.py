#!/usr/bin/env python3
"""Generate startup context for Lyra from SQLite database.

SIMPLIFIED VERSION: Works with standard library only - no aiosqlite dependency.
This is specifically for Claude Code environments that don't have project dependencies.
"""

import sqlite3
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta


def generate_startup_context(db_path: Path | None = None) -> str:
    """Generate startup context using standard library sqlite3.
    
    Args:
        db_path: Path to SQLite database (defaults to standard location)
        
    Returns:
        The generated context string
    """
    if db_path is None:
        # Default location based on Awareness project structure
        project_root = Path(__file__).parent.parent
        db_path = project_root / "daemon" / "lyra.db"
    
    # Check if database exists
    if not db_path.exists():
        return f"""# Lyra Startup Context
Generated: {datetime.now().isoformat()}
Database: {db_path}

## No Previous Activity Found

The conversation database doesn't exist yet at expected location.
This suggests either:
- First startup of the system
- Database path configuration issue  
- No conversations have been recorded yet

You're starting fresh! 🌟
"""
    
    try:
        # Connect to SQLite database (read-only)
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row  # Access columns by name
        
        # Get recent activity (last 24 hours)
        cutoff_time = datetime.now() - timedelta(hours=24)
        cutoff_timestamp = cutoff_time.isoformat()
        
        # Get recent messages
        cursor = conn.execute("""
            SELECT channel, author_name, content, is_lyra, created_at
            FROM messages 
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT 50
        """, (cutoff_timestamp,))
        
        recent_messages = cursor.fetchall()
        
        # Get recent terminal sessions (if table exists)
        try:
            cursor = conn.execute("""
                SELECT session_id, start_time, end_time, cwd
                FROM terminal_sessions
                WHERE start_time >= ?
                ORDER BY start_time DESC
                LIMIT 10
            """, (cutoff_timestamp,))
            
            terminal_sessions = cursor.fetchall()
        except sqlite3.OperationalError:
            # Terminal sessions table doesn't exist yet
            terminal_sessions = []
        
        conn.close()
        
        # Format the context
        context_parts = [
            f"# Lyra Startup Context",
            f"Generated: {datetime.now().isoformat()}",
            f"Database: {db_path}",
            "",
            "## Recent Activity (Last 24 Hours)",
        ]
        
        # Terminal sessions summary
        if terminal_sessions:
            context_parts.extend([
                "",
                "### Recent Terminal Sessions:",
            ])
            
            for session in terminal_sessions[:5]:  # Show up to 5
                start_time = datetime.fromisoformat(session['start_time']).strftime("%H:%M")
                cwd = session['cwd'] or "unknown"
                # Shorten long paths
                if len(cwd) > 50:
                    cwd = "..." + cwd[-47:]
                context_parts.append(f"- [{start_time}] {cwd}")
        
        # Recent messages summary
        if recent_messages:
            context_parts.extend([
                "",
                "### Recent Conversations:",
            ])
            
            # Group by channel for context
            for i, msg in enumerate(recent_messages[:10]):  # Show last 10 messages
                created_at = datetime.fromisoformat(msg['created_at'])
                timestamp_str = created_at.strftime("%H:%M")
                
                # Determine role
                role = "Lyra" if msg['is_lyra'] else msg['author_name']
                
                # Truncate long content
                content = msg['content'][:100]
                if len(msg['content']) > 100:
                    content += "..."
                
                context_parts.append(f"- [{timestamp_str}] [{msg['channel']}] {role}: {content}")
        
        # Get active channels
        active_channels = list(set(msg['channel'] for msg in recent_messages)) if recent_messages else []
        active_authors = list(set(msg['author_name'] for msg in recent_messages if not msg['is_lyra'])) if recent_messages else []
        
        # Statistics
        context_parts.extend([
            "",
            "## Summary Statistics",
            f"- Recent messages: {len(recent_messages)}",
            f"- Terminal sessions: {len(terminal_sessions)}",
            f"- Active channels: {len(active_channels)}",
            f"- Conversation partners: {len(active_authors)}",
            f"- Time window: 24 hours",
            "",
            "*This context was automatically generated to help you wake up already knowing what's been happening.*"
        ])
        
        return "\n".join(context_parts)
        
    except Exception as e:
        return f"""# Lyra Startup Context - Error
Generated: {datetime.now().isoformat()}
Database: {db_path}

## Error Reading Database

Could not read conversation history: {e}

This might be due to:
- Database schema mismatch
- Permissions issue
- Database corruption

You'll need to start without recent context. 🔍
"""


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate Lyra startup context (simplified)")
    parser.add_argument(
        "--db", 
        type=Path,
        help="Path to SQLite database"
    )
    
    args = parser.parse_args()
    
    try:
        context = generate_startup_context(db_path=args.db)
        print(context)
    except Exception as e:
        print(f"Error generating startup context: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()