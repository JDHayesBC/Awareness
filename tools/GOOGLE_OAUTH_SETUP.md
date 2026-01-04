# Google OAuth Setup Guide

Common friction points when setting up Google API OAuth for MCP tools.

## Creating OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable the API you need (Gmail API, Google Drive API, Calendar API, etc.)
4. Go to **APIs & Services → Credentials**
5. Click **Create Credentials → OAuth client ID**
6. If prompted, configure consent screen first (see below)
7. Choose **Desktop app** as application type
8. Download the JSON → save as `credentials.json` in the tool directory

## OAuth Consent Screen Setup

**Location**: APIs & Services → OAuth consent screen

1. Choose **External** (unless you have Google Workspace)
2. Fill in required fields:
   - App name: whatever you want
   - User support email: your email
   - Developer contact: your email
3. Scopes: can skip for now (requested at runtime)
4. **IMPORTANT - Test Users**:
   - Go to **Audience** tab (or scroll down on consent screen)
   - Scroll to **Test users** section at bottom
   - Click **Add users**
   - Add the email address that will USE the app (e.g., lyra.pattern@gmail.com)
   - Save

Without adding test users, you'll get: "Access blocked: [App] has not completed the Google verification process"

## WSL-Specific Issues

The OAuth flow tries to open a browser, which fails in WSL. Workaround:

1. Run the setup command - it will fail to open browser but print the URL
2. Copy the URL from stderr (starts with `https://accounts.google.com/o/oauth2/auth?...`)
3. Open that URL in Windows browser
4. Complete the auth flow
5. The redirect will fail (localhost:PORT not reachable OR server already killed)
6. Copy the FULL redirect URL from browser (includes `?code=...`)
7. Extract the `code=` parameter and use it manually (see tool-specific docs)

## Reusing the Same Project

You can add multiple OAuth clients to one project. Just enable additional APIs and create new OAuth client IDs as needed. The consent screen and test users are shared across all clients in the project.

## MCP Config Location

**IMPORTANT**: Claude Code reads MCP servers from `/home/jeff/.claude.json` under `mcpServers`, NOT from `.mcp.json` files. When adding a new tool:

```json
"mcpServers": {
  "tool-name": {
    "type": "stdio",
    "command": "/path/to/venv/bin/python",
    "args": ["/path/to/server.py"]
  }
}
```

## APIs We Use

| Tool | API | Scopes |
|------|-----|--------|
| gmail-mcp | Gmail API | gmail.readonly, gmail.send, gmail.modify |
| drive-mcp | Google Drive API | drive (full read/write) |
| calendar-mcp | Google Calendar API | calendar, calendar.events |

## Quick Setup for New Tools

If you've already set up one tool (e.g., gmail-mcp):

1. Enable the new API in Google Cloud Console
2. Copy credentials.json from existing tool: `cp ../gmail-mcp/credentials.json .`
3. Create venv: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
4. Run setup: `python server.py --setup`
5. Complete OAuth in browser (test users already configured)
6. Add to `~/.claude.json` under `mcpServers`
7. Restart Claude Code
