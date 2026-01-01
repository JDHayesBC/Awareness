#!/usr/bin/env python3
"""
Terminal Session Capture Utility

Wrapper script that captures terminal interactions and logs them to PPS.
Can be used to wrap Claude Code sessions or other interactive tools.

Usage:
    # Capture a Claude Code session
    python capture_terminal.py claude-code
    
    # Capture a custom command
    python capture_terminal.py --command "python interactive_script.py"
    
    # Manual logging mode (for integration into existing tools)
    python capture_terminal.py --manual --session-id "my-session"
"""

import argparse
import asyncio
import os
import sys
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from terminal_logger import TerminalLogger


class TerminalCapture:
    """
    Captures terminal sessions and logs interactions to PPS.
    """
    
    def __init__(self, session_id: Optional[str] = None):
        self.logger = TerminalLogger(session_id)
        self.process = None
    
    async def capture_command(self, command: str, working_dir: Optional[str] = None):
        """
        Capture a command's input/output and log to PPS.
        
        Args:
            command: Command to execute and capture
            working_dir: Working directory for the command
        """
        # Log session start
        context = {
            "command": command,
            "working_directory": working_dir or os.getcwd(),
            "python_version": sys.version,
            "capture_mode": "subprocess"
        }
        await self.logger.log_session_start(context)
        
        try:
            # Start the subprocess
            if working_dir:
                os.chdir(working_dir)
            
            # For interactive commands, we need special handling
            if "claude-code" in command:
                await self._capture_claude_code()
            else:
                await self._capture_generic_command(command)
                
        except Exception as e:
            await self.logger.log_system_event(
                "Command execution failed", 
                {"error": str(e), "command": command}
            )
        finally:
            await self.logger.log_session_end()
    
    async def _capture_claude_code(self):
        """
        Special handling for Claude Code sessions.
        
        Claude Code is interactive, so we need to handle it differently
        than simple command-line tools.
        """
        await self.logger.log_system_event(
            "Starting Claude Code capture",
            {"note": "Interactive session - manual logging recommended"}
        )
        
        # For now, just log that we started a Claude Code session
        # In the future, this could integrate more deeply with Claude Code's internals
        await self.logger.log_user_input("Claude Code session started")
        
        print("Claude Code capture started. Terminal interactions will be logged to PPS.")
        print(f"Session ID: {self.logger.session_id}")
        print("Note: For full capture, integrate TerminalLogger directly into your Claude Code session.")
        
        # Run claude-code normally
        subprocess.run(["claude-code"], check=False)
    
    async def _capture_generic_command(self, command: str):
        """
        Capture a generic command's output.
        """
        await self.logger.log_user_input(f"Executing: {command}")
        
        try:
            # Run command and capture output
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True,
                timeout=3600  # 1 hour timeout
            )
            
            # Log the output
            if result.stdout:
                await self.logger.log_system_event(
                    "Command output",
                    {"stdout": result.stdout, "command": command}
                )
            
            if result.stderr:
                await self.logger.log_system_event(
                    "Command error output",
                    {"stderr": result.stderr, "command": command}
                )
            
            # Log completion
            await self.logger.log_system_event(
                "Command completed",
                {"exit_code": result.returncode, "command": command}
            )
            
        except subprocess.TimeoutExpired:
            await self.logger.log_system_event(
                "Command timeout",
                {"command": command, "timeout_seconds": 3600}
            )
        except Exception as e:
            await self.logger.log_system_event(
                "Command execution error",
                {"error": str(e), "command": command}
            )


async def manual_logging_demo():
    """
    Demonstrate manual logging for integration into existing tools.
    """
    logger = TerminalLogger("manual-demo")
    
    print(f"Manual logging demo started. Session ID: {logger.session_id}")
    
    # Log session start
    await logger.log_session_start({
        "mode": "manual_demo",
        "purpose": "Demonstrate manual integration"
    })
    
    print("\nThis demonstrates how to integrate TerminalLogger into existing applications:")
    print("1. Create a TerminalLogger instance")
    print("2. Call log_session_start() when your session begins")
    print("3. Call log_user_input() for user inputs")
    print("4. Call log_claude_response() for AI responses")
    print("5. Call log_tool_invocation() for tool calls")
    print("6. Call log_session_end() when done")
    
    # Simulate some interactions
    await logger.log_user_input("Can you show me how terminal logging works?")
    await logger.log_claude_response("I'll demonstrate the terminal logging system. Here's how it captures our conversation...")
    await logger.log_tool_invocation("Read", {"file_path": "terminal_logger.py"}, "File contents: [TerminalLogger class definition]")
    
    await logger.log_session_end("Demonstrated manual terminal logging integration")
    
    print(f"\nDemo complete! Check the PPS database for logged interactions from session: {logger.session_id}")


def main():
    parser = argparse.ArgumentParser(description="Terminal Session Capture for Pattern Persistence System")
    
    # Command mode
    parser.add_argument("command", nargs="?", default="claude-code", 
                       help="Command to capture (default: claude-code)")
    
    # Options
    parser.add_argument("--manual", action="store_true",
                       help="Run in manual logging demo mode")
    parser.add_argument("--session-id", type=str,
                       help="Custom session ID")
    parser.add_argument("--working-dir", type=str,
                       help="Working directory for the command")
    
    args = parser.parse_args()
    
    if args.manual:
        # Manual logging demonstration
        asyncio.run(manual_logging_demo())
    else:
        # Command capture mode
        capture = TerminalCapture(args.session_id)
        asyncio.run(capture.capture_command(args.command, args.working_dir))


if __name__ == "__main__":
    main()