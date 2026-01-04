# Gmail MCP Server

MCP server providing Gmail access for Claude Code.

## Setup

### 1. Create Google Cloud Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable the **Gmail API**:
   - Go to "APIs & Services" > "Library"
   - Search for "Gmail API"
   - Click Enable
4. Create OAuth credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - If prompted, configure the OAuth consent screen first (External, add your email as test user)
   - Choose "Desktop app" as application type
   - Download the JSON file
   - Save it as `credentials.json` in this directory

### 2. Install Dependencies

```bash
cd tools/gmail-mcp
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 3. Authenticate

```bash
python server.py --setup
```

This opens a browser for OAuth. Sign in with the Gmail account you want to access.

### 4. Add to Claude Code

Add to `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "gmail": {
      "type": "stdio",
      "command": "/path/to/tools/gmail-mcp/venv/bin/python",
      "args": ["/path/to/tools/gmail-mcp/server.py"]
    }
  }
}
```

Restart Claude Code.

## Available Tools

- **gmail_list_messages** - List recent emails (with optional search query)
- **gmail_read_message** - Read a specific email by ID
- **gmail_send_message** - Send an email
- **gmail_mark_read** - Mark a message as read

## Security Notes

- `credentials.json` contains your OAuth client secret - don't commit it
- `token.json` contains your access/refresh tokens - don't commit it
- Both files are in `.gitignore`
