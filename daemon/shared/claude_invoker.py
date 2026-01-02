"""
Claude CLI Invoker - Shared invocation logic for Lyra daemons.

This module provides:
- Claude CLI invocation with --resume session management
- Progressive context reduction for prompt too long errors
- Trace logging integration
- Error handling and diagnostics

Key Design Decision:
Uses --resume <sessionId> instead of --continue to allow
multiple daemons to maintain independent conversation sessions.
"""

import asyncio
import subprocess
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, Awaitable


class PromptTooLongError(Exception):
    """Raised when prompt exceeds Claude's context window."""
    pass


class ClaudeInvoker:
    """
    Handles Claude CLI invocations with session management.

    Each daemon creates its own ClaudeInvoker with a unique session_prefix,
    allowing Discord and Reflection to maintain separate conversation contexts.

    Example:
        invoker = ClaudeInvoker(
            session_prefix="discord-lyra",
            model="sonnet",
            cwd="/home/jeff/.claude"
        )
        response = await invoker.invoke("Hello!", context="greeting")
    """

    def __init__(
        self,
        session_prefix: str,
        model: str = "sonnet",
        cwd: str = "/home/jeff/.claude",
        journal_path: Optional[str] = None,
        trace_logger: Optional[object] = None,
    ):
        """
        Initialize the Claude invoker.

        Args:
            session_prefix: Unique prefix for session IDs (e.g., "discord-lyra", "reflection-lyra")
            model: Claude model to use (sonnet, opus, haiku)
            cwd: Working directory for Claude CLI
            journal_path: Path for diagnostic logs
            trace_logger: Optional TraceLogger for observability
        """
        self.session_prefix = session_prefix
        self.model = model
        self.cwd = cwd
        self.journal_path = journal_path or "/home/jeff/.claude/journals/discord"
        self.trace_logger = trace_logger

        # Session tracking
        self.current_session_id: Optional[str] = None
        self.session_initialized = False
        self.session_invocation_count = 0
        self.session_start_time: Optional[datetime] = None
        self.last_response_time: Optional[datetime] = None

        # Ensure journal directory exists
        Path(self.journal_path).mkdir(parents=True, exist_ok=True)

    def get_session_id(self, channel_id: Optional[str] = None) -> str:
        """
        Get or create a session ID.

        Args:
            channel_id: Optional channel identifier for per-channel sessions

        Returns:
            Session ID string for use with --resume
        """
        if channel_id:
            return f"{self.session_prefix}-{channel_id}"
        return self.session_prefix

    def start_new_session(self, channel_id: Optional[str] = None):
        """Start a new session, resetting tracking state."""
        self.current_session_id = self.get_session_id(channel_id)
        self.session_initialized = False
        self.session_invocation_count = 0
        self.session_start_time = datetime.now(timezone.utc)
        print(f"[SESSION] Started new session: {self.current_session_id}")

    async def invoke(
        self,
        prompt: str,
        context: str = "unknown",
        use_session: bool = True,
        channel_id: Optional[str] = None,
        timeout: int = 180,
        model_override: Optional[str] = None,
    ) -> Optional[str]:
        """
        Invoke Claude CLI with the given prompt.

        Args:
            prompt: The prompt to send
            context: Context label for logging
            use_session: Whether to use --resume for session continuity
            channel_id: Optional channel ID for per-channel sessions
            timeout: Subprocess timeout in seconds
            model_override: Override the default model for this call

        Returns:
            Claude's response or None on error
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        invocation_id = f"{timestamp}_{context}"
        model = model_override or self.model

        # Determine session ID
        session_id = self.get_session_id(channel_id) if use_session else None
        should_resume = use_session and self.session_initialized

        # Log the invocation
        print(f"[INVOKE:{context}] Starting Claude invocation at {timestamp}")
        print(f"[INVOKE:{context}] cwd={self.cwd}, model={model}, session={session_id}, resume={should_resume}")
        print(f"[INVOKE:{context}] Prompt length: {len(prompt)} chars")

        # Trace: API call start
        api_start_time = None
        if self.trace_logger:
            api_start_time = await self.trace_logger.api_call_start(
                model=model,
                prompt_tokens=len(prompt) // 4,  # Rough estimate
            )

        try:
            # Build command
            cmd = ["claude", "--model", model]
            if should_resume and session_id:
                cmd.extend(["--resume", session_id])
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
                print(f"[INVOKE:{context}] PROMPT TOO LONG - context window exceeded")
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
            self.last_response_time = datetime.now(timezone.utc)
            if not self.session_initialized:
                self.session_initialized = True
                self.session_start_time = datetime.now(timezone.utc)
                print(f"[INVOKE:{context}] Session initialized: {session_id}")

            self.session_invocation_count += 1
            print(f"[INVOKE:{context}] Session invocations: {self.session_invocation_count}")

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
        channel_id: Optional[str] = None,
        context_reducer: Optional[Callable[[str, int], str]] = None,
        max_retries: int = 3,
    ) -> Optional[str]:
        """
        Invoke with progressive context reduction on prompt too long errors.

        Args:
            prompt: Initial prompt
            context: Context label
            use_session: Whether to use session continuity
            channel_id: Optional channel ID
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
                    channel_id=channel_id,
                )
            except PromptTooLongError:
                if retry >= max_retries:
                    print(f"[INVOKE:{context}] All retries exhausted")
                    return None

                if context_reducer:
                    current_prompt = context_reducer(current_prompt, retry + 1)
                    print(f"[INVOKE:{context}] Reduced prompt to {len(current_prompt)} chars")
                else:
                    # Default: just fail if no reducer provided
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
                f.write(f"# Identity failure: {identity_failed}\n\n")
                f.write("## PROMPT SENT:\n")
                f.write(prompt)
                f.write("\n\n## RESPONSE RECEIVED:\n")
                f.write(response or "(empty)")
                f.write("\n\n## STDERR:\n")
                f.write(result.stderr or "(empty)")
            print(f"[INVOKE:{context}] Diagnostic written to {diag_file}")
        except Exception as e:
            print(f"[INVOKE:{context}] Failed to write diagnostic: {e}")
