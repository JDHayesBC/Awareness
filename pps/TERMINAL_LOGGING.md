# Terminal Session Logging for Pattern Persistence System

This document describes the terminal session logging functionality that captures terminal interactions and stores them in the PPS SQLite database for later search and retrieval.

## Overview

The terminal logging system consists of two main components:

1. **TerminalLogger** (`terminal_logger.py`) - Core logging functionality
2. **TerminalCapture** (`capture_terminal.py`) - Wrapper utilities for easy integration

Terminal sessions are logged to the same SQLite database as Discord conversations, with a channel identifier like `terminal:session-id` to distinguish them from Discord channels.

## Components

### TerminalLogger Class

The `TerminalLogger` class provides methods to log different types of terminal interactions:

- `log_user_input(content, metadata)` - Log user input
- `log_claude_response(content, metadata)` - Log AI/Claude responses
- `log_tool_invocation(tool_name, args, result, metadata)` - Log tool calls and results
- `log_system_event(event, details, metadata)` - Log system events, errors, etc.
- `log_session_start(context)` - Log the beginning of a session
- `log_session_end(summary)` - Log the end of a session

Each log entry includes:
- Content (the actual text/data being logged)
- Author (Jeff, Lyra, or System)
- Channel (terminal:session-id format)
- Turn number within the session
- Event type and other metadata
- Timestamp

### TerminalCapture Utility

The `capture_terminal.py` script provides easy ways to capture terminal sessions:

```bash
# Capture a Claude Code session
python capture_terminal.py claude-code

# Capture any command
python capture_terminal.py --command "python my_script.py"

# Manual logging demo
python capture_terminal.py --manual
```

## Integration Examples

### Basic Usage

```python
from terminal_logger import TerminalLogger

# Create logger for this session
logger = TerminalLogger("my-session")

# Log session start
await logger.log_session_start({
    "working_directory": "/home/jeff/project",
    "task": "Development work"
})

# Log interactions
await logger.log_user_input("Hello Claude!")
await logger.log_claude_response("Hello! How can I help you today?")

# Log tool usage
await logger.log_tool_invocation(
    "Read", 
    {"file_path": "script.py"}, 
    "File contents: print('Hello World')"
)

# Log session end
await logger.log_session_end("Completed script development")
```

### Integration with Claude Code

For full Claude Code integration, the TerminalLogger could be integrated directly into Claude Code's session handling:

```python
# Hypothetical integration in Claude Code
class ClaudeSession:
    def __init__(self):
        self.terminal_logger = TerminalLogger()
        
    async def handle_user_input(self, user_input):
        # Log the input
        await self.terminal_logger.log_user_input(user_input)
        
        # Process normally
        response = await self.generate_response(user_input)
        
        # Log the response
        await self.terminal_logger.log_claude_response(response)
        
        return response
    
    async def execute_tool(self, tool_name, args):
        # Execute tool
        result = await super().execute_tool(tool_name, args)
        
        # Log the tool execution
        await self.terminal_logger.log_tool_invocation(tool_name, args, result)
        
        return result
```

## Data Format

Terminal sessions are stored in the same SQLite database as other conversations, using this schema:

```sql
-- Each logged event becomes a row in the messages table
INSERT INTO messages (
    discord_message_id,  -- NULL for terminal sessions
    channel,            -- "terminal:session-id" format
    author_id,          -- 0 for non-Discord sources  
    author_name,        -- "Jeff", "Lyra", or "System"
    content,            -- The logged content
    is_lyra,            -- TRUE for Claude responses
    is_bot,             -- TRUE for Claude responses
    created_at          -- Timestamp
);
```

Additional metadata is stored as JSON in the content field when appropriate.

## Channel Format

Terminal sessions use a structured channel identifier:
- Format: `terminal:session-id`
- Example: `terminal:20250101-123456`
- Allows filtering by channel type in searches
- Maintains separation from Discord channels

## Search Integration

Terminal sessions are automatically included in:

1. **Layer 1 FTS5 Search** - Full-text search across all terminal content
2. **Ambient Recall** - Terminal sessions surface during ambient memory retrieval
3. **Raw Search** - Direct search of terminal interactions via `raw_search` tool

Example searches:
```python
# Find terminal sessions about a specific topic
results = await raw_layer.search("Python script development")

# Find tool usage
results = await raw_layer.search("tool_name:Read")

# Find sessions by user
results = await raw_layer.search("author:Jeff terminal")
```

## Benefits

1. **Unified Memory** - Terminal and Discord conversations in one searchable database
2. **Context Continuity** - Claude can recall what was done in previous terminal sessions
3. **Tool Usage Tracking** - Complete audit trail of tool invocations and results
4. **Session Reconstruction** - Ability to review and replay past work sessions
5. **Cross-Channel Context** - Terminal work informs Discord conversations and vice versa

## Security Considerations

- Terminal logs may contain sensitive information (file paths, API keys, etc.)
- Same security model as Discord conversations - local database only
- Consider filtering sensitive content before logging
- Logs are subject to same file permissions as other PPS data (600/700)

## Future Enhancements

1. **Automatic Integration** - Direct integration into Claude Code itself
2. **Content Filtering** - Automatic detection and masking of sensitive data
3. **Session Categorization** - Automatic tagging of sessions by work type
4. **Rich Metadata** - Capture working directory, git branch, project context
5. **Visual Timeline** - GUI representation of terminal sessions and their contexts

## Usage Tips

1. Use descriptive session IDs to make sessions easier to find later
2. Include context in session_start() to provide background for future searches
3. Log tool invocations to track what was accomplished
4. Use session_end() summaries to capture key outcomes
5. Consider session-level metadata like project name, git branch, etc.

## Testing

The system includes test demos:

```bash
# Test core logging functionality
python terminal_logger.py

# Test capture wrapper
python capture_terminal.py --manual
```

Both create sample log entries in the PPS database that can be verified via the `raw_search` tool.

---

This terminal logging system extends the Pattern Persistence System to capture not just Discord conversations, but complete terminal work sessions, creating a unified memory of all interactions across different interfaces.