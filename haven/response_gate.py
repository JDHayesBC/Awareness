"""Haven response gate — decides whether the bot should call Opus at all.

Three-layer cascade, in order:
  Layer 0 (regex): entity name appears in any message -> YES (always-pass safety rail)
  Layer 1 (self-author): batch only contains this bot's own messages -> NO
  Layer 2 (9b classifier): ambiguous -> default-NO LLM call to LM Studio

Lives upstream of `invoker.query(prompt)` in `haven/bot.py`. The point: short-circuit
before Opus is invoked. An LLM cannot refuse a call - once tokens are spent, they're spent.

Issue #177. Not yet wired into bot.py - awaiting Jeff's eyes-on review.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from typing import Iterable

import httpx


# ==================== Configuration ====================

# WSL2 -> Windows host: localhost:1234 doesn't work, must use gateway IP.
# When the bot runs ON the NUC (same host as LM Studio), localhost:1234 works.
# Override per-deployment via env.
LM_STUDIO_URL = os.getenv("HAVEN_GATE_LM_URL", "http://172.26.0.1:1234/api/v1/chat")
LM_STUDIO_MODEL = os.getenv(
    "HAVEN_GATE_LM_MODEL", "qwen3.5-9b-uncensored-hauhaucs-aggressive"
)
LM_STUDIO_TIMEOUT = float(os.getenv("HAVEN_GATE_LM_TIMEOUT", "5.0"))

# Validated default-NO classifier prompt. See #177 comment 3 for empirical results.
CLASSIFIER_PROMPT_TEMPLATE = """You are a response gate for {entity_name}-bot in Haven chat. Default: NO (skip - {entity_name}-bot stays quiet).
{entity_name}-bot is one of multiple participants. Only output YES if the message:
(a) asks a direct question {entity_name}-bot is best-positioned to answer, OR
(b) introduces something genuinely new requiring {entity_name}-bot's voice.
Pure agreement, echoes, emotional parallel-presence with another bot, or acknowledgments where another bot has already responded = NO.
Output exactly one word: YES or NO."""


# ==================== Data ====================


@dataclass
class GateDecision:
    """Result of running the cascade."""

    respond: bool
    layer: str  # "L0_name_mention" | "L1_self_author" | "L2_classifier" | "L2_fallback"
    reason: str
    elapsed_ms: float = 0.0
    classifier_raw: str | None = None  # only set when L2 fired


# ==================== Layer 0: Name mention ====================


def _name_mention_pattern(entity_name: str) -> re.Pattern:
    """Compile a word-boundary pattern matching the entity name (case-insensitive)."""
    return re.compile(rf"\b{re.escape(entity_name)}\b", re.IGNORECASE)


def layer0_name_mentioned(entity_name: str, messages: list[dict]) -> bool:
    """True if entity_name appears as a word in ANY message content.

    Per Jeff's safety rule: direct reference to the entity = always respond.
    Accepts known false-positive cost (e.g., "Caia said Lyra is right" still triggers).
    Better over-eager YES on name than miss when actually addressed.
    """
    pat = _name_mention_pattern(entity_name)
    for msg in messages:
        content = msg.get("content", "") or ""
        if pat.search(content):
            return True
    return False


# ==================== Layer 1: Self-author delta ====================


def layer1_only_self(entity_username: str, messages: list[dict]) -> bool:
    """True if the entire batch is from this bot's own username (skip).

    Defensive: bot.py already filters its own messages, but if a stale batch
    holds only self-authored content, don't waste an Opus call on it.
    """
    if not messages:
        return False
    for msg in messages:
        author = msg.get("username", "") or ""
        if author != entity_username:
            return False
    return True


# ==================== Layer 2: 9b classifier ====================


def _format_messages_for_classifier(messages: list[dict]) -> str:
    """Render the batch as 'display_name (username): content' lines."""
    lines = []
    for msg in messages:
        dn = msg.get("display_name", "") or ""
        un = msg.get("username", "") or ""
        ct = msg.get("content", "") or ""
        lines.append(f"{dn} ({un}): {ct}")
    return "\n".join(lines)


async def layer2_classify(
    entity_name: str,
    messages: list[dict],
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[bool, str]:
    """Call LM Studio 9b classifier. Returns (respond, raw_output).

    Default: NO. On any error/timeout, returns (False, "<error>") - fail-closed
    means we skip rather than wasting an Opus call on uncertainty. Caller can
    override that policy if it ever proves wrong.
    """
    system_prompt = CLASSIFIER_PROMPT_TEMPLATE.format(entity_name=entity_name)
    body = _format_messages_for_classifier(messages)
    payload = {
        "model": LM_STUDIO_MODEL,
        "system_prompt": system_prompt,
        "input": body,
    }

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=LM_STUDIO_TIMEOUT)
    try:
        try:
            resp = await client.post(LM_STUDIO_URL, json=payload)
            resp.raise_for_status()
        except (httpx.HTTPError, asyncio.TimeoutError) as e:
            return (False, f"<error: {type(e).__name__}>")

        data = resp.json()
        # LM Studio /api/v1/chat shape (observed 2026-05-01):
        #   {"output": [{"type": "message", "content": "YES"}], ...}
        # Other versions / fallbacks: response/text strings, or OpenAI-style choices.
        text = ""
        if isinstance(data, dict):
            out = data.get("output")
            if isinstance(out, list):
                parts: list[str] = []
                for item in out:
                    if isinstance(item, dict):
                        c = item.get("content", "")
                        if isinstance(c, str):
                            parts.append(c)
                        elif isinstance(c, list):
                            for sub in c:
                                if isinstance(sub, dict) and isinstance(
                                    sub.get("text"), str
                                ):
                                    parts.append(sub["text"])
                text = "".join(parts)
            elif isinstance(out, str):
                text = out
            if not text:
                text = data.get("response") or data.get("text") or ""
            if not text and isinstance(data.get("choices"), list) and data["choices"]:
                first = data["choices"][0]
                if isinstance(first, dict):
                    text = (
                        first.get("text")
                        or first.get("message", {}).get("content", "")
                        or ""
                    )
        text = (text or "").strip() if isinstance(text, str) else ""
        # First whitespace-separated token, uppercase, stripped of punctuation
        first_token = re.split(r"\s+", text, maxsplit=1)[0] if text else ""
        first_token = re.sub(r"[^A-Za-z]", "", first_token).upper()
        return (first_token == "YES", text)
    finally:
        if owns_client:
            await client.aclose()


# ==================== Cascade ====================


async def evaluate(
    entity_name: str,
    entity_username: str,
    messages: list[dict],
    *,
    client: httpx.AsyncClient | None = None,
) -> GateDecision:
    """Run the three-layer cascade. Returns a GateDecision.

    `entity_name` is the human name ("Lyra"). `entity_username` is the bot's
    Haven username (e.g., "lyra-bot"). `messages` is the batch list of dicts
    with at least `username` and `content` fields.
    """
    t0 = time.time()

    # Layer 0: name mention -> YES (always-pass)
    if layer0_name_mentioned(entity_name, messages):
        return GateDecision(
            respond=True,
            layer="L0_name_mention",
            reason=f"'{entity_name}' appeared in batch",
            elapsed_ms=(time.time() - t0) * 1000,
        )

    # Layer 1: only self-authored content -> NO
    if layer1_only_self(entity_username, messages):
        return GateDecision(
            respond=False,
            layer="L1_self_author",
            reason=f"batch contains only {entity_username} messages",
            elapsed_ms=(time.time() - t0) * 1000,
        )

    # Layer 2: 9b classifier with default-NO
    respond, raw = await layer2_classify(entity_name, messages, client=client)
    return GateDecision(
        respond=respond,
        layer="L2_classifier" if not raw.startswith("<error") else "L2_fallback",
        reason=f"classifier said: {raw[:60]!r}",
        elapsed_ms=(time.time() - t0) * 1000,
        classifier_raw=raw,
    )


# ==================== Convenience for sync callers ====================


def evaluate_sync(
    entity_name: str,
    entity_username: str,
    messages: list[dict],
) -> GateDecision:
    """Sync wrapper for offline test scripts. Don't use from inside the bot loop."""
    return asyncio.run(evaluate(entity_name, entity_username, messages))


__all__ = [
    "GateDecision",
    "evaluate",
    "evaluate_sync",
    "layer0_name_mentioned",
    "layer1_only_self",
    "layer2_classify",
]
