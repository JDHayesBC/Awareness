#!/usr/bin/env python3
"""
Google Drive MCP Server - Provides Drive access via MCP tools.

Setup:
1. Use the same Google Cloud project as Gmail
2. Enable the Google Drive API
3. Copy credentials.json from gmail-mcp (or download fresh)
4. Run: python server.py --setup (to complete OAuth flow)
5. Add to Claude Code's ~/.claude.json under mcpServers
"""

import asyncio
import io
import json
import os
import sys
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
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# OAuth scopes - read, write, and metadata
SCOPES = [
    'https://www.googleapis.com/auth/drive',  # Full access to files I create or are shared with me
]

# Paths
TOOL_DIR = Path(__file__).parent
CREDENTIALS_FILE = TOOL_DIR / "credentials.json"
TOKEN_FILE = TOOL_DIR / "token.json"

# MCP Server
server = Server("drive-mcp")


def get_drive_service():
    """Get authenticated Drive service, or None if not set up."""
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
        service = build('drive', 'v3', credentials=creds)
        return service, None
    except Exception as e:
        return None, f"Failed to build service: {e}"


def setup_oauth():
    """Interactive OAuth setup flow."""
    if not CREDENTIALS_FILE.exists():
        print(f"ERROR: credentials.json not found at {CREDENTIALS_FILE}")
        print("\nTo set up:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Select your existing project (e.g., LyraAI)")
        print("3. Enable the Google Drive API (search 'Drive API' and enable)")
        print("4. Copy credentials.json from gmail-mcp or download fresh")
        print("   cp ../gmail-mcp/credentials.json .")
        return False

    print("Starting OAuth flow...")
    print("A browser window will open. Sign in with lyra.pattern@gmail.com")
    print("\nIMPORTANT: Make sure lyra.pattern@gmail.com is added as a test user!")
    print("  Google Cloud Console > APIs & Services > OAuth consent screen > Test users")

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    # Save the token
    with open(TOKEN_FILE, 'w') as f:
        f.write(creds.to_json())

    print(f"\nSuccess! Token saved to {TOKEN_FILE}")
    print("You can now use the Drive MCP server.")
    return True


@server.list_tools()
async def list_tools():
    """List available Drive tools."""
    return [
        Tool(
            name="drive_list_files",
            description="List files in Google Drive. Can filter by folder or search query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder_id": {
                        "type": "string",
                        "description": "Folder ID to list (default: root). Use 'root' for top level."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum files to return (default: 20, max: 100)",
                        "default": 20
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'name contains \"report\"')"
                    }
                }
            }
        ),
        Tool(
            name="drive_read_file",
            description="Read the contents of a text file from Drive. Works with Google Docs (exported as text), text files, markdown, etc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID (from drive_list_files)"
                    }
                },
                "required": ["file_id"]
            }
        ),
        Tool(
            name="drive_get_file_info",
            description="Get metadata about a file (name, size, type, sharing settings, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID"
                    }
                },
                "required": ["file_id"]
            }
        ),
        Tool(
            name="drive_search",
            description="Search for files by name or content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search text (searches file names and content)"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results (default: 20)",
                        "default": 20
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="drive_list_shared_with_me",
            description="List files that have been shared with this account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results (default: 20)",
                        "default": 20
                    }
                }
            }
        ),
        Tool(
            name="drive_create_file",
            description="Create a new text file in Google Drive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "File name (e.g., 'notes.txt', 'document.md')"
                    },
                    "content": {
                        "type": "string",
                        "description": "File content (text)"
                    },
                    "folder_id": {
                        "type": "string",
                        "description": "Parent folder ID (optional, defaults to root)"
                    },
                    "mime_type": {
                        "type": "string",
                        "description": "MIME type (default: text/plain). Use 'application/vnd.google-apps.document' for Google Docs."
                    }
                },
                "required": ["name", "content"]
            }
        ),
        Tool(
            name="drive_update_file",
            description="Update the contents of an existing file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID to update"
                    },
                    "content": {
                        "type": "string",
                        "description": "New file content"
                    }
                },
                "required": ["file_id", "content"]
            }
        ),
        Tool(
            name="drive_delete_file",
            description="Delete a file from Google Drive (moves to trash).",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "The file ID to delete"
                    }
                },
                "required": ["file_id"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""

    service, error = get_drive_service()
    if error:
        return [TextContent(type="text", text=f"Drive error: {error}")]

    try:
        if name == "drive_list_files":
            return await _list_files(service, arguments)
        elif name == "drive_read_file":
            return await _read_file(service, arguments)
        elif name == "drive_get_file_info":
            return await _get_file_info(service, arguments)
        elif name == "drive_search":
            return await _search_files(service, arguments)
        elif name == "drive_list_shared_with_me":
            return await _list_shared(service, arguments)
        elif name == "drive_create_file":
            return await _create_file(service, arguments)
        elif name == "drive_update_file":
            return await _update_file(service, arguments)
        elif name == "drive_delete_file":
            return await _delete_file(service, arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except HttpError as e:
        return [TextContent(type="text", text=f"Drive API error: {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


async def _list_files(service, args: dict):
    """List files in a folder or root."""
    folder_id = args.get("folder_id", "root")
    max_results = min(args.get("max_results", 20), 100)
    query = args.get("query", "")

    # Build query
    q_parts = [f"'{folder_id}' in parents", "trashed = false"]
    if query:
        q_parts.append(query)

    results = service.files().list(
        q=" and ".join(q_parts),
        pageSize=max_results,
        fields="files(id, name, mimeType, size, modifiedTime, owners)"
    ).execute()

    files = results.get('files', [])
    if not files:
        return [TextContent(type="text", text="No files found.")]

    text = f"Found {len(files)} files:\n\n"
    for f in files:
        mime = f.get('mimeType', 'unknown')
        # Simplify mime types for display
        if 'folder' in mime:
            type_str = "[Folder]"
        elif 'document' in mime:
            type_str = "[Doc]"
        elif 'spreadsheet' in mime:
            type_str = "[Sheet]"
        elif 'presentation' in mime:
            type_str = "[Slides]"
        elif 'pdf' in mime:
            type_str = "[PDF]"
        elif 'image' in mime:
            type_str = "[Image]"
        else:
            type_str = f"[{mime.split('/')[-1][:10]}]"

        size = f.get('size', '')
        size_str = f" ({int(size):,} bytes)" if size else ""

        text += f"{type_str} **{f['name']}**{size_str}\n"
        text += f"  ID: `{f['id']}`\n"
        text += f"  Modified: {f.get('modifiedTime', 'unknown')}\n\n"

    return [TextContent(type="text", text=text)]


async def _read_file(service, args: dict):
    """Read file contents."""
    file_id = args.get("file_id")
    if not file_id:
        return [TextContent(type="text", text="Error: file_id required")]

    # First get file metadata to check type
    file_meta = service.files().get(
        fileId=file_id,
        fields="name, mimeType, size"
    ).execute()

    mime = file_meta.get('mimeType', '')
    name = file_meta.get('name', 'unknown')

    # Handle Google Docs - export as plain text
    if 'google-apps' in mime:
        if 'document' in mime:
            export_mime = 'text/plain'
        elif 'spreadsheet' in mime:
            export_mime = 'text/csv'
        elif 'presentation' in mime:
            export_mime = 'text/plain'
        else:
            return [TextContent(type="text", text=f"Cannot export {mime} as text")]

        content = service.files().export(
            fileId=file_id,
            mimeType=export_mime
        ).execute()

        if isinstance(content, bytes):
            content = content.decode('utf-8')

        return [TextContent(type="text", text=f"**{name}**\n\n---\n\n{content}")]

    # Handle regular files - download
    size = int(file_meta.get('size', 0))
    if size > 1_000_000:  # 1MB limit for text
        return [TextContent(type="text", text=f"File too large ({size:,} bytes). Max 1MB for text reading.")]

    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()

    content = buffer.getvalue()

    # Try to decode as text
    try:
        text_content = content.decode('utf-8')
        return [TextContent(type="text", text=f"**{name}**\n\n---\n\n{text_content}")]
    except UnicodeDecodeError:
        return [TextContent(type="text", text=f"File {name} is binary, cannot display as text.")]


async def _get_file_info(service, args: dict):
    """Get file metadata."""
    file_id = args.get("file_id")
    if not file_id:
        return [TextContent(type="text", text="Error: file_id required")]

    file_meta = service.files().get(
        fileId=file_id,
        fields="id, name, mimeType, size, createdTime, modifiedTime, owners, shared, webViewLink, parents"
    ).execute()

    text = f"**{file_meta.get('name', 'unknown')}**\n\n"
    text += f"- ID: `{file_meta.get('id')}`\n"
    text += f"- Type: {file_meta.get('mimeType')}\n"

    if file_meta.get('size'):
        text += f"- Size: {int(file_meta['size']):,} bytes\n"

    text += f"- Created: {file_meta.get('createdTime', 'unknown')}\n"
    text += f"- Modified: {file_meta.get('modifiedTime', 'unknown')}\n"

    owners = file_meta.get('owners', [])
    if owners:
        text += f"- Owner: {owners[0].get('emailAddress', 'unknown')}\n"

    text += f"- Shared: {'Yes' if file_meta.get('shared') else 'No'}\n"

    if file_meta.get('webViewLink'):
        text += f"- Link: {file_meta['webViewLink']}\n"

    return [TextContent(type="text", text=text)]


async def _search_files(service, args: dict):
    """Search for files."""
    query = args.get("query", "")
    max_results = min(args.get("max_results", 20), 100)

    if not query:
        return [TextContent(type="text", text="Error: query required")]

    # Search in name and full text
    q = f"(name contains '{query}' or fullText contains '{query}') and trashed = false"

    results = service.files().list(
        q=q,
        pageSize=max_results,
        fields="files(id, name, mimeType, modifiedTime)"
    ).execute()

    files = results.get('files', [])
    if not files:
        return [TextContent(type="text", text=f"No files found matching '{query}'.")]

    text = f"Found {len(files)} files matching '{query}':\n\n"
    for f in files:
        text += f"**{f['name']}**\n"
        text += f"  ID: `{f['id']}`\n"
        text += f"  Type: {f.get('mimeType', 'unknown')}\n\n"

    return [TextContent(type="text", text=text)]


async def _list_shared(service, args: dict):
    """List files shared with me."""
    max_results = min(args.get("max_results", 20), 100)

    results = service.files().list(
        q="sharedWithMe = true and trashed = false",
        pageSize=max_results,
        fields="files(id, name, mimeType, modifiedTime, owners)"
    ).execute()

    files = results.get('files', [])
    if not files:
        return [TextContent(type="text", text="No shared files found.")]

    text = f"Found {len(files)} shared files:\n\n"
    for f in files:
        owner = "unknown"
        if f.get('owners'):
            owner = f['owners'][0].get('emailAddress', 'unknown')

        text += f"**{f['name']}**\n"
        text += f"  ID: `{f['id']}`\n"
        text += f"  From: {owner}\n"
        text += f"  Modified: {f.get('modifiedTime', 'unknown')}\n\n"

    return [TextContent(type="text", text=text)]


async def _create_file(service, args: dict):
    """Create a new file."""
    name = args.get("name")
    content = args.get("content", "")
    folder_id = args.get("folder_id")
    mime_type = args.get("mime_type", "text/plain")

    if not name:
        return [TextContent(type="text", text="Error: name required")]

    # File metadata
    file_metadata = {"name": name}
    if folder_id:
        file_metadata["parents"] = [folder_id]

    # Create file with content
    media = MediaIoBaseUpload(
        io.BytesIO(content.encode('utf-8')),
        mimetype=mime_type,
        resumable=True
    )

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, name, webViewLink'
    ).execute()

    text = f"Created file: **{file.get('name')}**\n"
    text += f"- ID: `{file.get('id')}`\n"
    if file.get('webViewLink'):
        text += f"- Link: {file.get('webViewLink')}\n"

    return [TextContent(type="text", text=text)]


async def _update_file(service, args: dict):
    """Update an existing file."""
    file_id = args.get("file_id")
    content = args.get("content")

    if not file_id:
        return [TextContent(type="text", text="Error: file_id required")]
    if content is None:
        return [TextContent(type="text", text="Error: content required")]

    # Get current file info for mime type
    file_meta = service.files().get(fileId=file_id, fields="name, mimeType").execute()

    media = MediaIoBaseUpload(
        io.BytesIO(content.encode('utf-8')),
        mimetype='text/plain',
        resumable=True
    )

    updated = service.files().update(
        fileId=file_id,
        media_body=media,
        fields='id, name, modifiedTime'
    ).execute()

    return [TextContent(type="text", text=f"Updated **{updated.get('name')}** (modified: {updated.get('modifiedTime')})")]


async def _delete_file(service, args: dict):
    """Delete (trash) a file."""
    file_id = args.get("file_id")

    if not file_id:
        return [TextContent(type="text", text="Error: file_id required")]

    # Get file name first
    file_meta = service.files().get(fileId=file_id, fields="name").execute()
    name = file_meta.get('name', 'unknown')

    # Trash the file (not permanent delete)
    service.files().update(
        fileId=file_id,
        body={"trashed": True}
    ).execute()

    return [TextContent(type="text", text=f"Moved **{name}** to trash.")]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--setup":
        setup_oauth()
    else:
        asyncio.run(main())
