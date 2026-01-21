"""
Claude Code Invoker - Persistent CC connection for low-latency daemon use.
"""

from .invoker import ClaudeInvoker, quick_query

__all__ = ["ClaudeInvoker", "quick_query"]
