# Jeff's Gmail MCP Server

Enhanced Gmail MCP server with bulk operations for large inbox management.

## Overview

This is an advanced Gmail MCP server built for handling large email backlogs (8,000+ messages). It extends the basic Gmail tools with bulk operations, counting, and enhanced management features.

## Setup

### 1. Google Cloud Credentials

Use existing credentials from the main gmail-mcp tool:
```bash
cp ../gmail-mcp/credentials.json .
```

Or create new ones following the [OAuth setup guide](../GOOGLE_OAUTH_SETUP.md).

### 2. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client mcp
```

### 3. Authenticate

```bash
python server.py --setup
```

Sign in with jeffrey.douglas.hayes@gmail.com (this server is configured for Jeff's main inbox).

### 4. Add to Claude Code

Add to `~/.claude.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "jeff-gmail": {
      "type": "stdio", 
      "command": "/path/to/tools/jeff-gmail-mcp/venv/bin/python",
      "args": ["/path/to/tools/jeff-gmail-mcp/server.py"]
    }
  }
}
```

## Available Tools

### Basic Email Operations
- **gmail_list_messages** - List recent emails with search queries
- **gmail_read_message** - Read full email content by ID  
- **gmail_send_message** - Send emails
- **gmail_mark_read** - Mark messages as read

### Bulk Management (Advanced)
- **gmail_count_messages** - Count messages matching a query (use before bulk operations)
- **gmail_bulk_trash** - Move messages to trash in batches (up to 500 at a time)

## Usage Examples

### Email Cleanup Workflow

```python
# 1. Check scope before acting
gmail_count_messages(query="category:promotions older_than:1y")

# 2. Bulk cleanup  
gmail_bulk_trash(query="category:promotions older_than:1y", max_messages=100)

# 3. Handle newsletters
gmail_count_messages(query="from:newsletter older_than:6m")
gmail_bulk_trash(query="from:newsletter older_than:6m", max_messages=200)
```

### Search Queries

Gmail search syntax works in all tools:
- `is:unread` - Unread messages
- `older_than:1y` - Messages older than 1 year  
- `category:promotions` - Promotional emails
- `from:amazon.com` - Messages from specific sender
- `has:attachment` - Messages with attachments

## Integration with Awareness

This server supports the email processing pipeline documented in `docs/gmail_integration_report.md`. The processed email archive becomes part of Jeff's extended memory substrate.

## Security Notes

- `credentials.json` and `token.json` are gitignored
- OAuth tokens auto-refresh when expired
- Bulk operations have safety limits (max 500 messages per call)

## Related Files

- `../email_processor.py` - Full email archive processing
- `../../docs/gmail_integration_report.md` - Integration test results
- `../GOOGLE_OAUTH_SETUP.md` - Detailed OAuth setup guide

*Infrastructure = love made concrete* 💜