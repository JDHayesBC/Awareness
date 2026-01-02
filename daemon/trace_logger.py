"""Trace logging for daemon observability.

Provides structured event logging for Discord and reflection daemons,
enabling the PPS Observatory to show what's happening during processing.

See docs/WEB_UI_DESIGN.md Phase 3 for design context.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from conversation import ConversationManager


class EventTypes:
    """Standard event types for daemon tracing.

    Naming convention: {phase}_{action}
    - start/complete pairs for timed operations
    - singular events for instantaneous actions
    """

    # Session lifecycle
    SESSION_START = "session_start"
    SESSION_COMPLETE = "session_complete"

    # Identity reconstruction
    IDENTITY_START = "identity_reconstruction_start"
    IDENTITY_FILE_READ = "identity_file_read"
    IDENTITY_AMBIENT_RECALL = "identity_ambient_recall"
    IDENTITY_COMPLETE = "identity_reconstruction_complete"

    # Context assembly
    CONTEXT_ASSEMBLY = "context_assembly"

    # API calls to Claude
    API_CALL_START = "api_call_start"
    API_CALL_COMPLETE = "api_call_complete"
    API_CALL_ERROR = "api_call_error"

    # Tool invocations (MCP tools, etc.)
    TOOL_CALL = "tool_call"

    # Graphiti operations
    GRAPHITI_SEARCH = "graphiti_search"
    GRAPHITI_ADD = "graphiti_add"
    GRAPHITI_EXPLORE = "graphiti_explore"

    # Artifacts created
    ARTIFACT_CREATED = "artifact_created"

    # Message processing
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_SENT = "message_sent"

    # Reflection-specific
    REFLECTION_DECISION = "reflection_decision"
    CRYSTALLIZATION = "crystallization"

    # Errors and warnings
    ERROR = "error"
    WARNING = "warning"


@dataclass
class TraceLogger:
    """Logger for daemon trace events.

    Usage:
        logger = TraceLogger(conversation_manager, "discord")

        # Simple event
        await logger.log("message_received", {"author": "Jeff", "content": "Hello"})

        # Timed operation
        async with logger.timed("api_call"):
            response = await call_claude(...)

        # Identity reconstruction with automatic file tracking
        async with logger.identity_reconstruction() as identity:
            content = read_file("lyra_identity.md")
            identity.file_read("lyra_identity.md", len(content))
            ...
    """

    conversation_manager: "ConversationManager"
    daemon_type: str  # "discord", "reflection", "terminal"
    session_id: str = field(default_factory=lambda: f"{uuid.uuid4().hex[:12]}")

    # Track timing for nested operations
    _start_times: dict = field(default_factory=dict)

    async def log(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Log a trace event.

        Args:
            event_type: Type of event (see EventTypes)
            data: Event-specific data
            duration_ms: Duration for timed events
        """
        await self.conversation_manager.log_trace(
            session_id=self.session_id,
            daemon_type=self.daemon_type,
            event_type=event_type,
            event_data=data,
            duration_ms=duration_ms,
        )

    async def session_start(self, metadata: dict | None = None) -> None:
        """Log session start."""
        await self.log(EventTypes.SESSION_START, {
            "daemon_type": self.daemon_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        })

    async def session_complete(self, metadata: dict | None = None) -> None:
        """Log session completion."""
        await self.log(EventTypes.SESSION_COMPLETE, metadata)

    @asynccontextmanager
    async def timed(self, event_type: str, start_data: dict | None = None):
        """Context manager for timed operations.

        Logs {event_type}_start on entry, {event_type}_complete on exit with duration.

        Usage:
            async with logger.timed("api_call", {"model": "sonnet"}):
                response = await call_api()
        """
        start_time = time.monotonic()

        # Log start event
        await self.log(f"{event_type}_start", start_data)

        result_data = {}
        try:
            yield result_data  # Allow caller to add data to completion event
        finally:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            await self.log(
                f"{event_type}_complete",
                {**(start_data or {}), **result_data},
                duration_ms=duration_ms,
            )

    async def api_call_start(self, model: str, prompt_tokens: int | None = None) -> float:
        """Log API call start. Returns start time for duration calculation."""
        start_time = time.monotonic()
        await self.log(EventTypes.API_CALL_START, {
            "model": model,
            "prompt_tokens": prompt_tokens,
        })
        return start_time

    async def api_call_complete(
        self,
        start_time: float,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        model: str | None = None,
    ) -> None:
        """Log API call completion."""
        duration_ms = int((time.monotonic() - start_time) * 1000)
        await self.log(EventTypes.API_CALL_COMPLETE, {
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }, duration_ms=duration_ms)

    async def api_call_error(self, error: str, model: str | None = None) -> None:
        """Log API call error."""
        await self.log(EventTypes.API_CALL_ERROR, {
            "error": error,
            "model": model,
        })

    async def tool_call(
        self,
        tool_name: str,
        params_summary: str | None = None,
        result_summary: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Log a tool invocation."""
        await self.log(EventTypes.TOOL_CALL, {
            "tool": tool_name,
            "params": params_summary,
            "result": result_summary,
        }, duration_ms=duration_ms)

    async def graphiti_search(
        self,
        query: str,
        result_count: int,
        duration_ms: int | None = None,
    ) -> None:
        """Log Graphiti search operation."""
        await self.log(EventTypes.GRAPHITI_SEARCH, {
            "query": query,
            "result_count": result_count,
        }, duration_ms=duration_ms)

    async def graphiti_add(
        self,
        content_preview: str,
        entities_extracted: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Log Graphiti add operation."""
        await self.log(EventTypes.GRAPHITI_ADD, {
            "content_preview": content_preview[:100] if content_preview else None,
            "entities_extracted": entities_extracted,
        }, duration_ms=duration_ms)

    async def message_received(
        self,
        author: str,
        channel: str,
        content_preview: str,
    ) -> None:
        """Log incoming message."""
        await self.log(EventTypes.MESSAGE_RECEIVED, {
            "author": author,
            "channel": channel,
            "content_preview": content_preview[:100] if content_preview else None,
        })

    async def message_sent(
        self,
        channel: str,
        content_length: int,
    ) -> None:
        """Log outgoing message."""
        await self.log(EventTypes.MESSAGE_SENT, {
            "channel": channel,
            "content_length": content_length,
        })

    async def artifact_created(
        self,
        artifact_type: str,
        path: str | None = None,
        description: str | None = None,
    ) -> None:
        """Log artifact creation (journal, crystal, commit, etc.)."""
        await self.log(EventTypes.ARTIFACT_CREATED, {
            "type": artifact_type,
            "path": path,
            "description": description,
        })

    async def error(self, error_type: str, message: str, details: dict | None = None) -> None:
        """Log an error."""
        await self.log(EventTypes.ERROR, {
            "error_type": error_type,
            "message": message,
            **(details or {}),
        })

    async def warning(self, message: str, details: dict | None = None) -> None:
        """Log a warning."""
        await self.log(EventTypes.WARNING, {
            "message": message,
            **(details or {}),
        })


@dataclass
class IdentityReconstructionTracker:
    """Helper for tracking identity reconstruction events."""

    logger: TraceLogger
    start_time: float = field(default_factory=time.monotonic)
    files_read: list = field(default_factory=list)
    ambient_recall_results: int = 0
    total_tokens: int = 0

    async def file_read(self, filename: str, size_bytes: int, tokens: int | None = None) -> None:
        """Track a file read during identity reconstruction."""
        self.files_read.append({
            "file": filename,
            "size_bytes": size_bytes,
            "tokens": tokens,
        })
        if tokens:
            self.total_tokens += tokens

        await self.logger.log(EventTypes.IDENTITY_FILE_READ, {
            "file": filename,
            "size_bytes": size_bytes,
            "tokens": tokens,
        })

    async def ambient_recall(self, result_count: int, layers_queried: list[str] | None = None) -> None:
        """Track ambient_recall results."""
        self.ambient_recall_results = result_count
        await self.logger.log(EventTypes.IDENTITY_AMBIENT_RECALL, {
            "result_count": result_count,
            "layers_queried": layers_queried,
        })

    async def complete(self) -> None:
        """Mark identity reconstruction as complete."""
        duration_ms = int((time.monotonic() - self.start_time) * 1000)
        await self.logger.log(EventTypes.IDENTITY_COMPLETE, {
            "files_read": len(self.files_read),
            "files": [f["file"] for f in self.files_read],
            "total_tokens": self.total_tokens,
            "ambient_recall_results": self.ambient_recall_results,
        }, duration_ms=duration_ms)


@asynccontextmanager
async def identity_reconstruction(logger: TraceLogger):
    """Context manager for identity reconstruction tracing.

    Usage:
        async with identity_reconstruction(logger) as tracker:
            content = read_file("lyra_identity.md")
            await tracker.file_read("lyra_identity.md", len(content), token_count)

            results = await ambient_recall()
            await tracker.ambient_recall(len(results))
    """
    tracker = IdentityReconstructionTracker(logger)
    await logger.log(EventTypes.IDENTITY_START)

    try:
        yield tracker
    finally:
        await tracker.complete()
