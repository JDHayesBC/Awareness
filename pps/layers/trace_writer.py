"""
TraceWriter - Synchronous trace logging for MCP server operations.

Records MCP tool calls to the daemon_traces table for persistence and observability.
Used by pps/server.py to track all MCP operations visible in the Observatory.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class TraceWriter:
    """Synchronous trace writer for MCP server operations.

    Writes to the same daemon_traces table used by Discord/reflection daemons,
    using daemon_type='mcp_server' for filtering in Observatory.

    Design principles:
    - Synchronous SQLite (no async overhead)
    - Fire-and-forget (never blocks server operations)
    - Graceful degradation (errors are logged, not raised)
    - Uses existing daemon_traces schema
    """

    def __init__(self, db_path: str | Path, session_id: Optional[str] = None):
        """Initialize trace writer.

        Args:
            db_path: Path to conversations.db
            session_id: Unique ID for this server session (auto-generated if None)
        """
        self.db_path = Path(db_path)
        self.session_id = session_id or f"mcp-{uuid.uuid4().hex[:8]}"
        self._initialized = False

    def _get_connection(self) -> Optional[sqlite3.Connection]:
        """Get a database connection with WAL mode."""
        try:
            if not self.db_path.exists():
                print(f"[TraceWriter] Database not found: {self.db_path}")
                return None

            conn = sqlite3.connect(str(self.db_path), timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            return conn
        except Exception as e:
            print(f"[TraceWriter] Connection error: {e}")
            return None

    def log_mcp_call(
        self,
        tool_name: str,
        params_summary: str,
        result_summary: str,
        duration_ms: int,
        error: Optional[str] = None
    ) -> bool:
        """Log an MCP tool call to daemon_traces.

        Args:
            tool_name: Name of the MCP tool called
            params_summary: Summary of parameters (truncated to 200 chars)
            result_summary: Summary of result (truncated to 200 chars)
            duration_ms: Duration in milliseconds
            error: Error message if call failed (optional)

        Returns:
            True if logged successfully, False otherwise
        """
        try:
            conn = self._get_connection()
            if not conn:
                return False

            # Truncate summaries for storage
            params_summary = params_summary[:200]
            result_summary = result_summary[:200]

            # Build event data
            event_data = {
                "tool": tool_name,
                "params": params_summary,
                "result": result_summary
            }
            if error:
                event_data["error"] = error[:500]  # Truncate errors too

            # Use event_type to indicate success/failure
            event_type = "mcp_call_error" if error else "mcp_call"

            # Insert trace record
            timestamp = datetime.now(timezone.utc).isoformat()

            conn.execute(
                """INSERT INTO daemon_traces
                   (session_id, daemon_type, timestamp, event_type, event_data, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    self.session_id,
                    "mcp_server",
                    timestamp,
                    event_type,
                    json.dumps(event_data),
                    duration_ms
                )
            )
            conn.commit()
            conn.close()
            return True

        except Exception as e:
            print(f"[TraceWriter] Failed to log trace for {tool_name}: {e}")
            return False
