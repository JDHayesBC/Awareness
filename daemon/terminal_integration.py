#!/usr/bin/env python3
"""
Terminal Session Integration for Lyra Daemon

Provides a simple interface for Claude Code to log terminal interactions
to the same SQLite database used by the Discord daemon. This integrates
the existing terminal logger infrastructure with the daemon's conversation
storage system.

Usage:
    # Start a terminal session
    logger = TerminalIntegration()
    session_id = await logger.start_session(working_dir="/path/to/project")
    
    # Log interactions
    await logger.log_user_input(session_id, turn=1, content="help")
    await logger.log_claude_response(session_id, turn=1, content="Here to help!")
    
    # End session
    await logger.end_session(session_id)
"""

import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from conversation import ConversationManager


class TerminalIntegration:
    """
    Simple terminal session logging that integrates with daemon SQLite storage.
    
    This bridges the gap between the terminal logger infrastructure and the 
    Discord daemon's conversation management system, enabling unified storage.
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize terminal integration.
        
        Args:
            db_path: Path to SQLite database. Uses daemon default if None.
        """
        if db_path is None:
            # Use same database as daemon
            claude_home = Path(os.getenv("CLAUDE_HOME", str(Path.home() / ".claude")))
            db_path = claude_home / "data" / "lyra_conversations.db"
            
        self.conversation_manager = ConversationManager(db_path)
        
    async def start_session(
        self, 
        working_dir: Optional[str] = None, 
        command: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> str:
        """
        Start a new terminal session.
        
        Args:
            working_dir: Working directory for the session
            command: Initial command or session description
            session_id: Custom session ID (auto-generated if None)
            
        Returns:
            Session ID for use in subsequent logging calls
        """
        if session_id is None:
            session_id = f"terminal-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
            
        metadata = {
            "integration_version": "1.0",
            "started_via": "terminal_integration",
        }
        
        await self.conversation_manager.start_terminal_session(
            session_id=session_id,
            working_dir=working_dir,
            command=command,
            metadata=metadata
        )
        
        print(f"[TERMINAL] Started session {session_id}")
        return session_id
        
    async def end_session(self, session_id: str) -> None:
        """End a terminal session."""
        await self.conversation_manager.end_terminal_session(session_id)
        print(f"[TERMINAL] Ended session {session_id}")
        
    async def log_user_input(
        self,
        session_id: str,
        turn: int,
        content: str,
        metadata: Optional[dict] = None
    ) -> None:
        """Log user input to the terminal session."""
        await self.conversation_manager.log_terminal_interaction(
            session_id=session_id,
            turn_number=turn,
            interaction_type="user_input",
            content=content,
            metadata=metadata
        )
        
    async def log_claude_response(
        self,
        session_id: str,
        turn: int,
        content: str,
        metadata: Optional[dict] = None
    ) -> None:
        """Log Claude's response to the terminal session.""" 
        await self.conversation_manager.log_terminal_interaction(
            session_id=session_id,
            turn_number=turn,
            interaction_type="claude_response",
            content=content,
            metadata=metadata
        )
        
    async def log_system_output(
        self,
        session_id: str,
        turn: int,
        content: str,
        metadata: Optional[dict] = None
    ) -> None:
        """Log system output (tool results, etc.) to the terminal session."""
        await self.conversation_manager.log_terminal_interaction(
            session_id=session_id,
            turn_number=turn,
            interaction_type="system_output",
            content=content,
            metadata=metadata
        )
        
    async def log_tool_invocation(
        self,
        session_id: str,
        turn: int,
        tool_name: str,
        tool_input: str,
        tool_output: str,
        metadata: Optional[dict] = None
    ) -> None:
        """Log a tool invocation to the terminal session."""
        tool_metadata = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_output": tool_output,
            **(metadata or {})
        }
        
        await self.conversation_manager.log_terminal_interaction(
            session_id=session_id,
            turn_number=turn,
            interaction_type="tool_invocation",
            content=f"Tool: {tool_name}",
            metadata=tool_metadata
        )
        
    async def get_session_history(self, session_id: str, limit: int = 50) -> list[dict]:
        """Get the history for a terminal session."""
        return await self.conversation_manager.get_terminal_session_history(
            session_id=session_id, 
            limit=limit
        )
        
    async def close(self) -> None:
        """Close the database connection."""
        await self.conversation_manager.close()


# Example usage
async def example_usage():
    """Example of how to use the terminal integration."""
    logger = TerminalIntegration()
    
    try:
        # Start session
        session_id = await logger.start_session(
            working_dir="/home/jeff/project",
            command="claude --model sonnet"
        )
        
        # Log some interactions
        await logger.log_user_input(session_id, 1, "Hello Claude, help me debug this function")
        await logger.log_claude_response(session_id, 1, "I'd be happy to help you debug that function. Please share the code.")
        await logger.log_system_output(session_id, 1, "File uploaded: debug_me.py")
        
        # Log a tool usage
        await logger.log_tool_invocation(
            session_id, 1,
            tool_name="Read", 
            tool_input="debug_me.py",
            tool_output="def broken_function():\n    return 1 / 0"
        )
        
        # Get history
        history = await logger.get_session_history(session_id)
        print(f"Session has {len(history)} interactions")
        
        # End session
        await logger.end_session(session_id)
        
    finally:
        await logger.close()


if __name__ == "__main__":
    asyncio.run(example_usage())