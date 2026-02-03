#!/usr/bin/env python3
"""
Terminal Session Logger for Pattern Persistence System

Captures terminal interactions and stores them in the PPS SQLite database.
Can be used as a standalone logger or integrated into Claude Code sessions.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from layers.raw_capture import RawCaptureLayer


class TerminalLogger:
    """
    Logs terminal interactions to the Pattern Persistence System.
    
    Designed to capture:
    - User inputs 
    - Claude responses
    - System outputs
    - Tool invocations and results
    - Session metadata
    """
    
    def __init__(self, session_id: Optional[str] = None):
        """
        Initialize terminal logger.
        
        Args:
            session_id: Unique identifier for this terminal session.
                       If None, generates one based on timestamp.
        """
        self.session_id = session_id or f"terminal-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        # Initialize raw capture layer
        entity_path = Path(os.getenv("ENTITY_PATH", str(Path.home() / ".claude")))
        db_path = entity_path / "data" / "lyra_conversations.db"
        self.raw_capture = RawCaptureLayer(db_path=db_path)
        
        # Track session context
        self.session_start = datetime.now()
        self.turn_number = 0
    
    async def log_user_input(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Log user input to the database.
        
        Args:
            content: The user's input text
            metadata: Optional additional metadata
        """
        self.turn_number += 1
        
        # Build metadata
        meta = {
            "author_name": "Jeff",  # Assume Jeff unless specified
            "channel": f"terminal:{self.session_id}",
            "is_lyra": False,
            "session_turn": self.turn_number,
            "session_start": self.session_start.isoformat(),
            "event_type": "user_input"
        }
        if metadata:
            meta.update(metadata)
        
        return await self.raw_capture.store(content, meta)
    
    async def log_claude_response(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Log Claude/Lyra response to the database.
        
        Args:
            content: Claude's response text
            metadata: Optional additional metadata
        """
        # Build metadata
        meta = {
            "author_name": "Lyra",
            "channel": f"terminal:{self.session_id}",
            "is_lyra": True,
            "session_turn": self.turn_number,
            "session_start": self.session_start.isoformat(),
            "event_type": "claude_response"
        }
        if metadata:
            meta.update(metadata)
        
        return await self.raw_capture.store(content, meta)
    
    async def log_tool_invocation(self, tool_name: str, tool_args: Dict[str, Any], 
                                  result: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Log tool invocation and result.
        
        Args:
            tool_name: Name of the tool that was called
            tool_args: Arguments passed to the tool
            result: Result returned by the tool
            metadata: Optional additional metadata
        """
        # Format tool invocation as structured content
        content = f"Tool: {tool_name}\nArgs: {json.dumps(tool_args, indent=2)}\nResult: {result}"
        
        # Build metadata
        meta = {
            "author_name": "System",
            "channel": f"terminal:{self.session_id}",
            "is_lyra": False,
            "session_turn": self.turn_number,
            "session_start": self.session_start.isoformat(),
            "event_type": "tool_invocation",
            "tool_name": tool_name
        }
        if metadata:
            meta.update(metadata)
        
        return await self.raw_capture.store(content, meta)
    
    async def log_system_event(self, event: str, details: Optional[Dict[str, Any]] = None, 
                              metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Log system events (errors, state changes, etc.).
        
        Args:
            event: Description of the system event
            details: Optional structured details about the event
            metadata: Optional additional metadata
        """
        # Format system event
        content = f"System Event: {event}"
        if details:
            content += f"\nDetails: {json.dumps(details, indent=2)}"
        
        # Build metadata
        meta = {
            "author_name": "System",
            "channel": f"terminal:{self.session_id}",
            "is_lyra": False,
            "session_turn": self.turn_number,
            "session_start": self.session_start.isoformat(),
            "event_type": "system_event"
        }
        if metadata:
            meta.update(metadata)
        
        return await self.raw_capture.store(content, meta)
    
    async def log_session_start(self, context: Optional[Dict[str, Any]] = None) -> bool:
        """
        Log the start of a terminal session.
        
        Args:
            context: Optional context about the session (working directory, 
                    initial task, etc.)
        """
        content = f"Terminal session started: {self.session_id}"
        if context:
            content += f"\nContext: {json.dumps(context, indent=2)}"
        
        metadata = {
            "author_name": "System",
            "channel": f"terminal:{self.session_id}", 
            "is_lyra": False,
            "session_turn": 0,
            "session_start": self.session_start.isoformat(),
            "event_type": "session_start"
        }
        
        return await self.raw_capture.store(content, metadata)
    
    async def log_session_end(self, summary: Optional[str] = None) -> bool:
        """
        Log the end of a terminal session.
        
        Args:
            summary: Optional summary of what was accomplished
        """
        duration = datetime.now() - self.session_start
        
        content = f"Terminal session ended: {self.session_id}\nDuration: {duration}\nTurns: {self.turn_number}"
        if summary:
            content += f"\nSummary: {summary}"
        
        metadata = {
            "author_name": "System",
            "channel": f"terminal:{self.session_id}",
            "is_lyra": False,
            "session_turn": self.turn_number + 1,
            "session_start": self.session_start.isoformat(),
            "event_type": "session_end",
            "session_duration_seconds": int(duration.total_seconds())
        }
        
        return await self.raw_capture.store(content, metadata)


async def demo_usage():
    """Demonstrate terminal logger usage."""
    logger = TerminalLogger("demo-session")
    
    # Log session start
    await logger.log_session_start({
        "working_directory": "/home/jeff/project",
        "initial_task": "Terminal logger development"
    })
    
    # Log a user input
    await logger.log_user_input("Hello Claude, can you help me with a Python script?")
    
    # Log Claude's response
    await logger.log_claude_response("I'd be happy to help with your Python script! What specifically are you working on?")
    
    # Log a tool invocation
    await logger.log_tool_invocation(
        "Read", 
        {"file_path": "/home/jeff/script.py"}, 
        "File contents: print('Hello World')"
    )
    
    # Log another user input
    await logger.log_user_input("Can you make this script more interesting?")
    
    # Log Claude's response
    await logger.log_claude_response("Sure! I'll enhance your script with some interactive features.")
    
    # Log session end
    await logger.log_session_end("Enhanced Python script with user interaction features")
    
    print("Demo logging completed!")


if __name__ == "__main__":
    # Run demo if called directly
    asyncio.run(demo_usage())