# Shared modules for Lyra daemons
"""
Shared infrastructure for Discord and Reflection daemons.

This package contains:
- claude_invoker: Claude CLI invocation with session management
- startup_protocol: Identity reconstruction and warmup logic
"""

from .claude_invoker import ClaudeInvoker, PromptTooLongError
from .startup_protocol import (
    build_startup_prompt,
    build_reflection_prompt,
    build_heartbeat_prompt,
)

__all__ = [
    'ClaudeInvoker',
    'PromptTooLongError',
    'build_startup_prompt',
    'build_reflection_prompt',
    'build_heartbeat_prompt',
]
