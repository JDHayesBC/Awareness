#!/usr/bin/env python3
"""Generate startup context for Lyra from SQLite database.

This script runs during Lyra's startup to provide immediate context
about recent activity when MCP tools aren't available.
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from conversation import ConversationManager


async def generate_startup_context(
    db_path: Path | None = None,
    output_path: Path | None = None,
) -> str:
    """Generate startup context and optionally save to file.
    
    Args:
        db_path: Path to SQLite database (defaults to standard location)
        output_path: If provided, save context to this file
        
    Returns:
        The generated context string
    """
    if db_path is None:
        # Database now in entity directory (Issue #131 migration)
        entity_path = os.getenv("ENTITY_PATH", "/mnt/c/Users/Jeff/Claude_Projects/Awareness/entities/lyra")
        db_path = Path(entity_path) / "data" / "lyra_conversations.db"
    
    # Check if database exists
    if not db_path.exists():
        empty_context = f"""# Lyra Startup Context
Generated: {datetime.now().isoformat()}
Database: {db_path}

## No Previous Activity Found

The conversation database doesn't exist yet or is empty.
This suggests either:
- First startup of the system
- Database path configuration issue  
- No conversations have been recorded yet

You're starting fresh! 🌟
"""
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(empty_context)
        return empty_context
    
    async with ConversationManager(db_path) as conv_mgr:
        # Get the formatted startup context
        context = await conv_mgr.get_startup_context(
            max_messages_per_channel=15,
            hours_lookback=24,
        )
        
        # Also get raw summary data for metadata
        summary = await conv_mgr.get_recent_activity_summary(
            hours=24,
            message_limit=200,
        )
        
        # Add metadata
        full_context = f"""# Lyra Startup Context
Generated: {datetime.now().isoformat()}
Database: {db_path}

{context}

## Summary Statistics
- Messages analyzed: {len(summary['recent_messages'])}
- Active channels: {len(summary['active_channels'])}
- Unique conversation partners: {len(summary['conversation_partners'])}
- Terminal sessions: {len(summary['terminal_sessions'])}
- Time window: {summary['hours_covered']} hours

*This context was automatically generated to help you wake up already knowing what's been happening.*
"""
        
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(full_context)
            print(f"Wrote startup context to {output_path}")
        
        return full_context


async def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate Lyra startup context")
    parser.add_argument(
        "--db", 
        type=Path,
        help="Path to SQLite database"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Save context to file"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON summary instead of formatted text"
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Hours of history to include (default: 24)"
    )
    
    args = parser.parse_args()
    
    try:
        if args.json:
            # Get raw summary data as JSON
            # Database now in entity directory (Issue #131 migration)
            entity_path = os.getenv("ENTITY_PATH", "/mnt/c/Users/Jeff/Claude_Projects/Awareness/entities/lyra")
            db_path = args.db or Path(entity_path) / "data" / "lyra_conversations.db"
            
            if not db_path.exists():
                print(json.dumps({"error": f"Database not found: {db_path}"}, indent=2))
                return
                
            async with ConversationManager(db_path) as conv_mgr:
                summary = await conv_mgr.get_recent_activity_summary(
                    hours=args.hours
                )
                print(json.dumps(summary, indent=2, default=str))
        else:
            # Generate formatted context
            context = await generate_startup_context(
                db_path=args.db,
                output_path=args.output,
            )
            if not args.output:
                print(context)
                
    except Exception as e:
        print(f"Error generating startup context: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())