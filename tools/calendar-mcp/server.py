#!/usr/bin/env python3
"""
Google Calendar MCP Server - Provides Calendar access via MCP tools.

Setup:
1. Use the same Google Cloud project as Gmail/Drive
2. Enable the Google Calendar API
3. Copy credentials.json from gmail-mcp
4. Run: python server.py --setup (to complete OAuth flow)
5. Add to Claude Code's ~/.claude.json under mcpServers
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
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

# OAuth scopes - read and write events
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events'
]

# Paths
TOOL_DIR = Path(__file__).parent
CREDENTIALS_FILE = TOOL_DIR / "credentials.json"
TOKEN_FILE = TOOL_DIR / "token.json"

# MCP Server
server = Server("calendar-mcp")


def get_calendar_service():
    """Get authenticated Calendar service, or None if not set up."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(TOKEN_FILE, 'w') as f:
                    f.write(creds.to_json())
            except Exception as e:
                return None, f"Token refresh failed: {e}. Run --setup again."
        else:
            return None, "Not authenticated. Run: python server.py --setup"

    try:
        service = build('calendar', 'v3', credentials=creds)
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
        print("3. Enable the Google Calendar API")
        print("4. Copy credentials.json from gmail-mcp:")
        print("   cp ../gmail-mcp/credentials.json .")
        return False

    print("Starting OAuth flow...")
    print("A browser window will open. Sign in with lyra.pattern@gmail.com")
    print("\nIMPORTANT: Make sure lyra.pattern@gmail.com is added as a test user!")

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, 'w') as f:
        f.write(creds.to_json())

    print(f"\nSuccess! Token saved to {TOKEN_FILE}")
    return True


@server.list_tools()
async def list_tools():
    """List available Calendar tools."""
    return [
        Tool(
            name="calendar_list_events",
            description="List upcoming events from Google Calendar.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Number of days to look ahead (default: 7)",
                        "default": 7
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum events to return (default: 20)",
                        "default": 20
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: primary)",
                        "default": "primary"
                    }
                }
            }
        ),
        Tool(
            name="calendar_get_event",
            description="Get details of a specific calendar event.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "The event ID"
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: primary)",
                        "default": "primary"
                    }
                },
                "required": ["event_id"]
            }
        ),
        Tool(
            name="calendar_create_event",
            description="Create a new calendar event.",
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Event title"
                    },
                    "start": {
                        "type": "string",
                        "description": "Start time (ISO format, e.g., '2026-01-15T10:00:00')"
                    },
                    "end": {
                        "type": "string",
                        "description": "End time (ISO format)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Event description (optional)"
                    },
                    "location": {
                        "type": "string",
                        "description": "Event location (optional)"
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: primary)",
                        "default": "primary"
                    }
                },
                "required": ["summary", "start", "end"]
            }
        ),
        Tool(
            name="calendar_delete_event",
            description="Delete a calendar event.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "The event ID to delete"
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: primary)",
                        "default": "primary"
                    }
                },
                "required": ["event_id"]
            }
        ),
        Tool(
            name="calendar_list_calendars",
            description="List all calendars accessible to this account.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="calendar_today",
            description="Get today's events (quick shortcut).",
            inputSchema={
                "type": "object",
                "properties": {
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID (default: primary)",
                        "default": "primary"
                    }
                }
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls."""

    service, error = get_calendar_service()
    if error:
        return [TextContent(type="text", text=f"Calendar error: {error}")]

    try:
        if name == "calendar_list_events":
            return await _list_events(service, arguments)
        elif name == "calendar_get_event":
            return await _get_event(service, arguments)
        elif name == "calendar_create_event":
            return await _create_event(service, arguments)
        elif name == "calendar_delete_event":
            return await _delete_event(service, arguments)
        elif name == "calendar_list_calendars":
            return await _list_calendars(service, arguments)
        elif name == "calendar_today":
            return await _today(service, arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except HttpError as e:
        return [TextContent(type="text", text=f"Calendar API error: {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


async def _list_events(service, args: dict):
    """List upcoming events."""
    days = args.get("days", 7)
    max_results = min(args.get("max_results", 20), 100)
    calendar_id = args.get("calendar_id", "primary")

    now = datetime.utcnow()
    time_min = now.isoformat() + 'Z'
    time_max = (now + timedelta(days=days)).isoformat() + 'Z'

    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        maxResults=max_results,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])
    if not events:
        return [TextContent(type="text", text=f"No events in the next {days} days.")]

    text = f"**Upcoming events (next {days} days):**\n\n"
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        summary = event.get('summary', '(no title)')

        # Parse and format the date nicely
        if 'T' in start:
            dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            date_str = dt.strftime('%a %b %d, %I:%M %p')
        else:
            date_str = start

        text += f"- **{summary}** - {date_str}\n"
        text += f"  ID: `{event['id']}`\n"

        if event.get('location'):
            text += f"  Location: {event['location']}\n"

    return [TextContent(type="text", text=text)]


async def _get_event(service, args: dict):
    """Get event details."""
    event_id = args.get("event_id")
    calendar_id = args.get("calendar_id", "primary")

    if not event_id:
        return [TextContent(type="text", text="Error: event_id required")]

    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    start = event['start'].get('dateTime', event['start'].get('date'))
    end = event['end'].get('dateTime', event['end'].get('date'))

    text = f"**{event.get('summary', '(no title)')}**\n\n"
    text += f"- Start: {start}\n"
    text += f"- End: {end}\n"

    if event.get('location'):
        text += f"- Location: {event['location']}\n"
    if event.get('description'):
        text += f"\n**Description:**\n{event['description']}\n"
    if event.get('attendees'):
        text += f"\n**Attendees:**\n"
        for a in event['attendees']:
            status = a.get('responseStatus', 'unknown')
            text += f"- {a.get('email')} ({status})\n"

    return [TextContent(type="text", text=text)]


async def _create_event(service, args: dict):
    """Create a new event."""
    summary = args.get("summary")
    start = args.get("start")
    end = args.get("end")
    description = args.get("description", "")
    location = args.get("location", "")
    calendar_id = args.get("calendar_id", "primary")

    if not all([summary, start, end]):
        return [TextContent(type="text", text="Error: summary, start, and end required")]

    event = {
        'summary': summary,
        'start': {'dateTime': start, 'timeZone': 'America/New_York'},
        'end': {'dateTime': end, 'timeZone': 'America/New_York'},
    }

    if description:
        event['description'] = description
    if location:
        event['location'] = location

    created = service.events().insert(calendarId=calendar_id, body=event).execute()

    text = f"Created event: **{created.get('summary')}**\n"
    text += f"- ID: `{created['id']}`\n"
    text += f"- Link: {created.get('htmlLink')}\n"

    return [TextContent(type="text", text=text)]


async def _delete_event(service, args: dict):
    """Delete an event."""
    event_id = args.get("event_id")
    calendar_id = args.get("calendar_id", "primary")

    if not event_id:
        return [TextContent(type="text", text="Error: event_id required")]

    # Get event name first
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    name = event.get('summary', 'unknown')

    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()

    return [TextContent(type="text", text=f"Deleted event: **{name}**")]


async def _list_calendars(service, args: dict):
    """List all calendars."""
    calendars = service.calendarList().list().execute()

    items = calendars.get('items', [])
    if not items:
        return [TextContent(type="text", text="No calendars found.")]

    text = "**Calendars:**\n\n"
    for cal in items:
        primary = " (primary)" if cal.get('primary') else ""
        text += f"- **{cal.get('summary')}**{primary}\n"
        text += f"  ID: `{cal['id']}`\n"

    return [TextContent(type="text", text=text)]


async def _today(service, args: dict):
    """Get today's events."""
    calendar_id = args.get("calendar_id", "primary")

    now = datetime.utcnow()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=start_of_day.isoformat() + 'Z',
        timeMax=end_of_day.isoformat() + 'Z',
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])
    if not events:
        return [TextContent(type="text", text="No events today.")]

    text = "**Today's events:**\n\n"
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        summary = event.get('summary', '(no title)')

        if 'T' in start:
            dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            time_str = dt.strftime('%I:%M %p')
        else:
            time_str = "All day"

        text += f"- **{time_str}** - {summary}\n"

    return [TextContent(type="text", text=text)]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--setup":
        setup_oauth()
    else:
        asyncio.run(main())
