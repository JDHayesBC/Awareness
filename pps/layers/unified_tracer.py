"""
UnifiedTracer - Shared tracing for all PPS entry points.

Records operations to the daemon_traces table for persistence and observability.
Used by both MCP server (pps/server.py) and HTTP server (pps/docker/server_http.py).
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class UnifiedTracer:
    """Unified trace writer for PPS operations across all entry points.

    Writes to the daemon_traces table used by Discord/reflection daemons,
    distinguishing entry points via daemon_type parameter.

    Design principles:
    - Synchronous SQLite (no async overhead)
    - Fire-and-forget (never blocks operations)
    - Graceful degradation (errors are logged, not raised)
    - Uses existing daemon_traces schema
    """

    def __init__(
        self,
        db_path: str | Path,
        daemon_type: str,
        session_id: Optional[str] = None
    ):
        """Initialize unified tracer.

        Args:
            db_path: Path to lyra_conversations.db
            daemon_type: Type identifier ('mcp_server', 'http_hook', etc.)
            session_id: Unique ID for this session (auto-generated if None)
        """
        self.db_path = Path(db_path)
        self.daemon_type = daemon_type
        self.session_id = session_id or f"{daemon_type}-{uuid.uuid4().hex[:8]}"
        self._initialized = False

    def _get_connection(self) -> Optional[sqlite3.Connection]:
        """Get a database connection with WAL mode."""
        try:
            if not self.db_path.exists():
                print(f"[UnifiedTracer] Database not found: {self.db_path}")
                return None

            conn = sqlite3.connect(str(self.db_path), timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            return conn
        except Exception as e:
            print(f"[UnifiedTracer] Connection error: {e}")
            return None

    def log_call(
        self,
        operation_name: str,
        params_summary: str,
        result_summary: str,
        duration_ms: int,
        error: Optional[str] = None
    ) -> bool:
        """Log an operation call to daemon_traces.

        Args:
            operation_name: Name of the operation (tool name, endpoint, etc.)
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
                "operation": operation_name,
                "params": params_summary,
                "result": result_summary
            }
            if error:
                event_data["error"] = error[:500]  # Truncate errors too

            # Use event_type to indicate success/failure
            event_type = f"{self.daemon_type}_error" if error else f"{self.daemon_type}_call"

            # Insert trace record
            timestamp = datetime.now(timezone.utc).isoformat()

            conn.execute(
                """INSERT INTO daemon_traces
                   (session_id, daemon_type, timestamp, event_type, event_data, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    self.session_id,
                    self.daemon_type,
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
            print(f"[UnifiedTracer] Failed to log trace for {operation_name}: {e}")
            return False
