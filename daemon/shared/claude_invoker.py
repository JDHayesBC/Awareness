"""
Claude CLI Invoker - Shared invocation logic for Lyra daemons.

This module provides:
- Claude CLI invocation with --continue session management
- Session limits to prevent unbounded context growth
- Progressive context reduction for prompt too long errors
- Trace logging integration
- Error handling and diagnostics

Session Management:
Uses --continue to resume the most recent conversation in the working directory.
Sessions are automatically reset when limits are exceeded:
- MAX_SESSION_INVOCATIONS: Hard limit on turns per session
- MAX_SESSION_DURATION_HOURS: Maximum session age
- SESSION_IDLE_HOURS: Reset after idle period

Directory Isolation:
Each daemon should use a different cwd to maintain separate sessions.
Discord uses /home/jeff/.claude, Reflection uses /home/jeff/.claude/reflection.
"""

import asyncio
import subprocess
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Callable

# Session limits (can be overridden via environment)
MAX_SESSION_INVOCATIONS = int(os.getenv("MAX_SESSION_INVOCATIONS", "12"))
MAX_SESSION_DURATION_HOURS = float(os.getenv("MAX_SESSION_DURATION_HOURS", "2.0"))
SESSION_IDLE_HOURS = float(os.getenv("SESSION_IDLE_HOURS", "4.0"))


class PromptTooLongError(Exception):
    """Raised when prompt exceeds Claude's context window."""
    pass


class ClaudeInvoker:
    """
    Handles Claude CLI invocations with session management.

    Uses --continue for session continuity within the working directory.
    Automatically resets sessions when limits are exceeded.

    Example:
        invoker = ClaudeInvoker(
            model="sonnet",
            cwd="/home/jeff/.claude"
        )
        response = await invoker.invoke("Hello!", context="greeting")
    """

    def __init__(
        self,
        model: str = "sonnet",
        cwd: str = "/home/jeff/.claude",
        journal_path: Optional[str] = None,
        trace_logger: Optional[object] = None,
        max_invocations: int = MAX_SESSION_INVOCATIONS,
        max_duration_hours: float = MAX_SESSION_DURATION_HOURS,
        idle_hours: float = SESSION_IDLE_HOURS,
    ):
        """
        Initialize the Claude invoker.

        Args:
            model: Claude model to use (sonnet, opus, haiku)
            cwd: Working directory for Claude CLI (determines session isolation)
            journal_path: Path for diagnostic logs
            trace_logger: Optional TraceLogger for observability
            max_invocations: Max invocations before session reset
            max_duration_hours: Max session age before reset
            idle_hours: Reset session after this much idle time
        """
        self.model = model
        self.cwd = cwd
        self.journal_path = journal_path or "/home/jeff/.claude/journals/discord"
        self.trace_logger = trace_logger

        # Session limits
        self.max_invocations = max_invocations
        self.max_duration_hours = max_duration_hours
        self.idle_hours = idle_hours

        # Session tracking
        self.session_initialized = False
        self.session_invocation_count = 0
        self.session_start_time: Optional[datetime] = None
        self.last_response_time: Optional[datetime] = None

        # Ensure directories exist
        Path(self.journal_path).mkdir(parents=True, exist_ok=True)
        Path(self.cwd).mkdir(parents=True, exist_ok=True)

    def should_reset_session(self) -> tuple[bool, str]:
        """
        Check if session should be reset based on limits.

        Returns:
            Tuple of (should_reset, reason)
        """
        if not self.session_initialized:
            return False, ""

        now = datetime.now(timezone.utc)

        # Check invocation count
        if self.session_invocation_count >= self.max_invocations:
            return True, f"invocation limit ({self.session_invocation_count}/{self.max_invocations})"

        # Check session duration
        if self.session_start_time:
            duration = now - self.session_start_time
            if duration > timedelta(hours=self.max_duration_hours):
                hours = duration.total_seconds() / 3600
                return True, f"duration limit ({hours:.1f}h/{self.max_duration_hours}h)"

        # Check idle time
        if self.last_response_time:
            idle = now - self.last_response_time
            if idle > timedelta(hours=self.idle_hours):
                hours = idle.total_seconds() / 3600
                return True, f"idle limit ({hours:.1f}h/{self.idle_hours}h)"

        return False, ""

    def reset_session(self, reason: str = "manual"):
        """Reset session state, forcing fresh context on next invocation."""
        print(f"[SESSION] Resetting session: {reason}")
        self.session_initialized = False
        self.session_invocation_count = 0
        self.session_start_time = None

    async def invoke(
        self,
        prompt: str,
        context: str = "unknown",
        use_session: bool = True,
        timeout: int = 180,
        model_override: Optional[str] = None,
    ) -> Optional[str]:
        """
        Invoke Claude CLI with the given prompt.

        Args:
            prompt: The prompt to send
            context: Context label for logging
            use_session: Whether to use --continue for session continuity
            timeout: Subprocess timeout in seconds
            model_override: Override the default model for this call

        Returns:
            Claude's response or None on error
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        invocation_id = f"{timestamp}_{context}"
        model = model_override or self.model

        # Check if we should reset before this invocation
        should_reset, reset_reason = self.should_reset_session()
        if should_reset:
            self.reset_session(reset_reason)

        # Determine if we should use --continue
        should_continue = use_session and self.session_initialized

        # Log the invocation
        print(f"[INVOKE:{context}] Starting Claude invocation at {timestamp}")
        print(f"[INVOKE:{context}] cwd={self.cwd}, model={model}, continue={should_continue}")
        print(f"[INVOKE:{context}] Prompt length: {len(prompt)} chars")

        # Trace: API call start
        api_start_time = None
        if self.trace_logger:
            api_start_time = await self.trace_logger.api_call_start(
                model=model,
                prompt_tokens=len(prompt) // 4,
            )

        try:
            # Build command
            cmd = ["claude", "--model", model]
            if should_continue:
                cmd.append("--continue")
            # Pre-approve MCP tools for non-interactive use
            cmd.extend(["--allowedTools", "mcp__pps__*", "mcp__github__*"])
            cmd.extend(["-p", prompt])

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=self.cwd,
                )
            )

            response = result.stdout.strip() if result.stdout else ""
            stderr_output = result.stderr or ""

            # Check for "Prompt is too long" error
            prompt_too_long = (
                "Prompt is too long" in response or
                "prompt is too long" in response.lower() or
                "Prompt is too long" in stderr_output or
                "context_length_exceeded" in stderr_output.lower()
            )

            if prompt_too_long:
                print(f"[INVOKE:{context}] PROMPT TOO LONG - resetting session")
                self.reset_session("prompt too long")
                raise PromptTooLongError("Context window exceeded")

            # Check for identity failure patterns
            identity_failure_patterns = [
                "can't roleplay", "cannot roleplay",
                "can't pretend", "cannot pretend",
                "persistent memory", "persistent memories",
                "I'm Claude", "I am Claude",
                "as an AI assistant",
            ]
            identity_failed = any(p.lower() in response.lower() for p in identity_failure_patterns)

            # Log the result
            print(f"[INVOKE:{context}] Return code: {result.returncode}")
            print(f"[INVOKE:{context}] Response length: {len(response)} chars")
            if identity_failed:
                print(f"[INVOKE:{context}] IDENTITY FAILURE DETECTED")

            # On failure, write diagnostic log
            if result.returncode != 0 or identity_failed:
                self._write_diagnostic(invocation_id, timestamp, context, prompt, response, result, identity_failed)

            if result.returncode != 0:
                print(f"[INVOKE:{context}] CLI error: {result.stderr}")
                return None

            # Update session tracking
            now = datetime.now(timezone.utc)
            self.last_response_time = now
            if not self.session_initialized:
                self.session_initialized = True
                self.session_start_time = now
                print(f"[INVOKE:{context}] Session initialized")

            self.session_invocation_count += 1
            print(f"[INVOKE:{context}] Session invocations: {self.session_invocation_count}/{self.max_invocations}")

            # Trace: API call complete
            if self.trace_logger and api_start_time:
                await self.trace_logger.api_call_complete(
                    start_time=api_start_time,
                    tokens_in=len(prompt) // 4,
                    tokens_out=len(response) // 4,
                    model=model,
                )

            return response

        except PromptTooLongError:
            if self.trace_logger:
                await self.trace_logger.api_call_error("prompt_too_long", model)
            raise
        except subprocess.TimeoutExpired:
            print(f"[INVOKE:{context}] TIMEOUT after {timeout}s")
            if self.trace_logger:
                await self.trace_logger.api_call_error("timeout", model)
            return None
        except FileNotFoundError:
            print(f"[INVOKE:{context}] Claude CLI not found")
            if self.trace_logger:
                await self.trace_logger.api_call_error("cli_not_found", model)
            return None
        except Exception as e:
            print(f"[INVOKE:{context}] Error: {e}")
            if self.trace_logger:
                await self.trace_logger.api_call_error(str(e), model)
            return None

    async def invoke_with_retry(
        self,
        prompt: str,
        context: str = "unknown",
        use_session: bool = True,
        context_reducer: Optional[Callable[[str, int], str]] = None,
        max_retries: int = 3,
    ) -> Optional[str]:
        """
        Invoke with progressive context reduction on prompt too long errors.

        Args:
            prompt: Initial prompt
            context: Context label
            use_session: Whether to use session continuity
            context_reducer: Function(prompt, retry_count) -> reduced_prompt
            max_retries: Maximum retry attempts

        Returns:
            Response or None if all retries failed
        """
        current_prompt = prompt

        for retry in range(max_retries + 1):
            try:
                return await self.invoke(
                    current_prompt,
                    context=f"{context}_retry{retry}" if retry > 0 else context,
                    use_session=use_session,
                )
            except PromptTooLongError:
                if retry >= max_retries:
                    print(f"[INVOKE:{context}] All retries exhausted")
                    return None

                if context_reducer:
                    current_prompt = context_reducer(current_prompt, retry + 1)
                    print(f"[INVOKE:{context}] Reduced prompt to {len(current_prompt)} chars")
                else:
                    print(f"[INVOKE:{context}] No context reducer, failing")
                    return None

        return None

    def _write_diagnostic(
        self,
        invocation_id: str,
        timestamp: str,
        context: str,
        prompt: str,
        response: str,
        result: subprocess.CompletedProcess,
        identity_failed: bool,
    ):
        """Write diagnostic log for failed invocations."""
        try:
            diag_file = Path(self.journal_path) / f"diagnostic_{invocation_id.replace(':', '-')}.txt"
            with open(diag_file, "w") as f:
                f.write(f"# Diagnostic Log - {timestamp}\n")
                f.write(f"# Context: {context}\n")
                f.write(f"# Return code: {result.returncode}\n")
                f.write(f"# Identity failure: {identity_failed}\n")
                f.write(f"# Session invocations: {self.session_invocation_count}\n\n")
                f.write("## PROMPT SENT:\n")
                f.write(prompt)
                f.write("\n\n## RESPONSE RECEIVED:\n")
                f.write(response or "(empty)")
                f.write("\n\n## STDERR:\n")
                f.write(result.stderr or "(empty)")
            print(f"[INVOKE:{context}] Diagnostic written to {diag_file}")
        except Exception as e:
            print(f"[INVOKE:{context}] Failed to write diagnostic: {e}")
