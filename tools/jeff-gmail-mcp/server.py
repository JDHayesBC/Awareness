#!/usr/bin/env python3
"""
Gmail MCP Server - Provides Gmail access via MCP tools.

Setup:
1. Create a Google Cloud project at https://console.cloud.google.com/
2. Enable the Gmail API
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download credentials.json to this directory
5. Run: python server.py --setup (to complete OAuth flow)
6. Add to Claude Code's .mcp.json
"""

import asyncio
import base64
import json
import os
import sys
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

# MCP imports
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Google imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# OAuth scopes - read, send, modify
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify'
]

# Paths
TOOL_DIR = Path(__file__).parent
CREDENTIALS_FILE = TOOL_DIR / "credentials.json"
TOKEN_FILE = TOOL_DIR / "token.json"

# MCP Server
server = Server("gmail-mcp")


def get_gmail_service():
    """Get authenticated Gmail service, or None if not set up."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Save refreshed token
                with open(TOKEN_FILE, 'w') as f:
                    f.write(creds.to_json())
            except Exception as e:
                return None, f"Token refresh failed: {e}. Run --setup again."
        else:
            return None, "Not authenticated. Run: python server.py --setup"

    try:
        service = build('gmail', 'v1', credentials=creds)
        return service, None
    except Exception as e:
        return None, f"Failed to build service: {e}"


def setup_oauth():
    """Interactive OAuth setup flow."""
    if not CREDENTIALS_FILE.exists():
        print(f"ERROR: credentials.json not found at {CREDENTIALS_FILE}")
        print("\nTo set up:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a project (or select existing)")
        print("3. Enable the Gmail API")
        print("4. Go to Credentials > Create Credentials > OAuth client ID")
        print("5. Choose 'Desktop app' as application type")
        print("6. Download the JSON and save as credentials.json in this directory")
        return False

    print("Starting OAuth flow...")
    print("A browser window will open. Sign in with lyra.pattern@gmail.com")

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    # Save the token
    with open(TOKEN_FILE, 'w') as f:
        f.write(creds.to_json())

    print(f"\nSuccess! Token saved to {TOKEN_FILE}")
    print("You can now use the Gmail MCP server.")
    return True


@server.list_tools()
async def list_tools():
    """List available Gmail tools."""
    return [
        Tool(
            name="gmail_list_messages",
            description="List recent email messages. Returns subject, sender, date, and message ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum messages to return (default: 10, max: 50)",
                        "default": 10
                    },
                    "query": {
                        "type": "string",
                        "description": "Gmail search query (e.g., 'is:unread', 'from:someone@example.com')",
                        "default": ""
                    }
                }
            }
        ),
        Tool(
            name="gmail_read_message",
            description="Read a specific email message by ID. Returns full content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The message ID (from gmail_list_messages)"
                    }
                },
                "required": ["message_id"]
            }
        ),
        Tool(
            name="gmail_send_message",
            description="Send an email message.",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject"
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body (plain text)"
                    }
                },
                "required": ["to", "subject", "body"]
            }
        ),
        Tool(
            name="gmail_mark_read",
            description="Mark a message as read.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The message ID to mark as read"
                    }
                },
                "required": ["message_id"]
            }
        ),
        Tool(
            name="gmail_count_messages",
            description="Count messages matching a query. Use this before bulk operations to understand scope.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query (e.g., 'is:unread older_than:1y', 'category:promotions')"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="gmail_bulk_trash",
            description="Move messages matching a query to trash. Returns count of trashed messages. Use gmail_count_messages first!",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query for messages to trash"
                    },
                    "max_messages": {
                        "type": "integer",
                        "description": "Maximum messages to trash in one call (default: 100, max: 500)",
                        "default": 100
                    }
                },
                "required": ["query"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""

    service, error = get_gmail_service()
    if error:
        return [TextContent(type="text", text=f"Gmail error: {error}")]

    try:
        if name == "gmail_list_messages":
            return await _list_messages(service, arguments)
        elif name == "gmail_read_message":
            return await _read_message(service, arguments)
        elif name == "gmail_send_message":
            return await _send_message(service, arguments)
        elif name == "gmail_mark_read":
            return await _mark_read(service, arguments)
        elif name == "gmail_count_messages":
            return await _count_messages(service, arguments)
        elif name == "gmail_bulk_trash":
            return await _bulk_trash(service, arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except HttpError as e:
        return [TextContent(type="text", text=f"Gmail API error: {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


async def _list_messages(service, args: dict):
    """List recent messages."""
    max_results = min(args.get("max_results", 10), 50)
    query = args.get("query", "")

    results = service.users().messages().list(
        userId='me',
        maxResults=max_results,
        q=query
    ).execute()

    messages = results.get('messages', [])
    if not messages:
        return [TextContent(type="text", text="No messages found.")]

    output = []
    for msg in messages:
        msg_data = service.users().messages().get(
            userId='me',
            id=msg['id'],
            format='metadata',
            metadataHeaders=['Subject', 'From', 'Date']
        ).execute()

        headers = {h['name']: h['value'] for h in msg_data.get('payload', {}).get('headers', [])}
        labels = msg_data.get('labelIds', [])
        unread = 'UNREAD' in labels

        output.append({
            'id': msg['id'],
            'subject': headers.get('Subject', '(no subject)'),
            'from': headers.get('From', 'unknown'),
            'date': headers.get('Date', 'unknown'),
            'unread': unread
        })

    text = f"Found {len(output)} messages:\n\n"
    for m in output:
        status = "[UNREAD] " if m['unread'] else ""
        text += f"{status}**{m['subject']}**\n"
        text += f"  From: {m['from']}\n"
        text += f"  Date: {m['date']}\n"
        text += f"  ID: `{m['id']}`\n\n"

    return [TextContent(type="text", text=text)]


async def _read_message(service, args: dict):
    """Read a specific message."""
    message_id = args.get("message_id")
    if not message_id:
        return [TextContent(type="text", text="Error: message_id required")]

    msg = service.users().messages().get(
        userId='me',
        id=message_id,
        format='full'
    ).execute()

    headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}

    # Extract body
    body = ""
    payload = msg.get('payload', {})

    if 'body' in payload and payload['body'].get('data'):
        body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
    elif 'parts' in payload:
        for part in payload['parts']:
            if part.get('mimeType') == 'text/plain' and part.get('body', {}).get('data'):
                body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                break
        if not body:
            for part in payload['parts']:
                if part.get('mimeType') == 'text/html' and part.get('body', {}).get('data'):
                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                    body = f"[HTML content]\n{body}"
                    break

    text = f"**Subject:** {headers.get('Subject', '(no subject)')}\n"
    text += f"**From:** {headers.get('From', 'unknown')}\n"
    text += f"**To:** {headers.get('To', 'unknown')}\n"
    text += f"**Date:** {headers.get('Date', 'unknown')}\n"
    text += f"\n---\n\n{body if body else '(no body content)'}"

    return [TextContent(type="text", text=text)]


async def _send_message(service, args: dict):
    """Send an email."""
    to = args.get("to")
    subject = args.get("subject")
    body = args.get("body")

    if not all([to, subject, body]):
        return [TextContent(type="text", text="Error: to, subject, and body required")]

    message = MIMEText(body)
    message['to'] = to
    message['subject'] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

    sent = service.users().messages().send(
        userId='me',
        body={'raw': raw}
    ).execute()

    return [TextContent(type="text", text=f"Message sent! ID: {sent['id']}")]


async def _mark_read(service, args: dict):
    """Mark a message as read."""
    message_id = args.get("message_id")
    if not message_id:
        return [TextContent(type="text", text="Error: message_id required")]

    service.users().messages().modify(
        userId='me',
        id=message_id,
        body={'removeLabelIds': ['UNREAD']}
    ).execute()

    return [TextContent(type="text", text=f"Message {message_id} marked as read.")]


async def _count_messages(service, args: dict):
    """Count messages matching a query."""
    query = args.get("query", "")
    if not query:
        return [TextContent(type="text", text="Error: query required")]

    # Get estimate by fetching message IDs only
    count = 0
    page_token = None

    while True:
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=500,
            pageToken=page_token
        ).execute()

        messages = results.get('messages', [])
        count += len(messages)

        page_token = results.get('nextPageToken')
        if not page_token:
            break

        # Safety limit to avoid infinite loops
        if count > 50000:
            return [TextContent(type="text", text=f"Query '{query}' matches 50,000+ messages (stopped counting)")]

    return [TextContent(type="text", text=f"Query '{query}' matches **{count}** messages")]


async def _bulk_trash(service, args: dict):
    """Move messages matching a query to trash."""
    query = args.get("query", "")
    max_messages = min(args.get("max_messages", 100), 500)

    if not query:
        return [TextContent(type="text", text="Error: query required")]

    # Get message IDs
    results = service.users().messages().list(
        userId='me',
        q=query,
        maxResults=max_messages
    ).execute()

    messages = results.get('messages', [])
    if not messages:
        return [TextContent(type="text", text=f"No messages match query '{query}'")]

    # Trash each message
    trashed = 0
    for msg in messages:
        try:
            service.users().messages().trash(userId='me', id=msg['id']).execute()
            trashed += 1
        except HttpError as e:
            # Continue on individual failures
            pass

    remaining = "more remain" if results.get('nextPageToken') else "no more"
    return [TextContent(type="text", text=f"Trashed {trashed} messages matching '{query}' ({remaining})")]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--setup":
        setup_oauth()
    else:
        asyncio.run(main())
