"""Haven response gate — decides whether the bot should call Opus at all.

Three-layer cascade (L0–L2), plus an optional Jev pre-filter (L_jev):

  Layer 0 (regex): entity name appears in any message -> YES (always-pass safety rail)
  Layer 1 (self-author): batch only contains this bot's own messages -> NO
  Layer 2 (9b classifier): ambiguous -> default-NO LLM call to LM Studio

  Layer Jev (optional, GH #360): fast probability-based gate *before* Sonnet is invoked.
  Runs independently via `layer_jev()` — call it from bot.py before starting the typing
  indicator. If P(respond) < threshold (default 0.30), skip Sonnet entirely with no typing
  indicator shown. Falls back to respond=True on any API error.

Lives upstream of `invoker.query(prompt)` in `haven/bot.py`. The point: short-circuit
before Opus is invoked. An LLM cannot refuse a call - once tokens are spent, they're spent.

Issue #177 (cascade, not yet wired). Issue #360 (Jev pre-filter, wired in bot.py).
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

# Jev pre-filter (GH #360) — TypeSafe hosted classifier.
# Configurable per-deployment; sane defaults work for most cases.
JEV_URL = os.getenv("HAVEN_JEV_URL", "https://api.typesafe.ai/v1/systemone")
JEV_DEFAULT_TURNS = int(os.getenv("HAVEN_JEV_TURNS", "10"))
JEV_DEFAULT_THRESHOLD = float(os.getenv("HAVEN_JEV_THRESHOLD", "0.30"))
JEV_DEFAULT_TIMEOUT = float(os.getenv("HAVEN_JEV_TIMEOUT", "2.0"))

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


@dataclass
class JevDecision:
    """Result of the Jev pre-filter (GH #360)."""

    respond: bool
    p_respond: float  # P(should respond) from Jev distribution["YES"]
    reason: str
    elapsed_ms: float = 0.0


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


# ==================== Layer Jev: probability-based pre-filter (GH #360) ====================


async def layer_jev(
    entity_name: str,
    messages: list[dict],
    *,
    api_key: str,
    turns: int = JEV_DEFAULT_TURNS,
    threshold: float = JEV_DEFAULT_THRESHOLD,
    timeout: float = JEV_DEFAULT_TIMEOUT,
    client: httpx.AsyncClient | None = None,
) -> JevDecision:
    """Jev probability gate: should this entity respond?

    Sends the last `turns` messages to the TypeSafe Jev API and returns
    P(should_respond). If P < `threshold`, `respond=False` (skip Sonnet).

    Falls back to respond=True on any network/API error — Jev unavailability
    must not block the entity's voice.

    `api_key` is required; pass an empty string to get a pass-through fallback
    without making a network call.

    The caller is responsible for the L0 safety check: if the entity's name
    appears in the batch, skip this function and let Sonnet decide (a direct
    address should never be silenced by a probability gate).
    """
    t0 = time.time()

    if not api_key:
        return JevDecision(
            respond=True,
            p_respond=1.0,
            reason="<jev disabled: no api_key>",
            elapsed_ms=(time.time() - t0) * 1000,
        )

    recent = messages[-turns:] if turns > 0 else messages
    state = _format_messages_for_classifier(recent)

    questions: dict = {
        "should_respond": {
            "type": "choice",
            "instructions": (
                f"Should {entity_name} respond to this conversation? "
                "Default NO: only YES if genuinely needed."
            ),
            "criteria": {
                "YES": (
                    f"{entity_name} should respond: they are directly addressed, "
                    "a question needs their voice, or genuinely new content warrants a reply."
                ),
                "NO": (
                    f"{entity_name} should stay silent: the exchange is greetings, "
                    "emotional echoes, acknowledgments, or another participant already covered it."
                ),
            },
            "options": ["YES", "NO"],
        }
    }

    payload = {
        "state": state,
        "model": "jev-latest",
        "questions": questions,
    }

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        try:
            resp = await client.post(
                JEV_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
        except (httpx.HTTPError, asyncio.TimeoutError, Exception) as e:
            return JevDecision(
                respond=True,
                p_respond=1.0,
                reason=f"<jev error: {type(e).__name__}>",
                elapsed_ms=(time.time() - t0) * 1000,
            )

        data = resp.json()
        answer = data.get("answers", {}).get("should_respond", {})
        choice = (answer.get("choice") or "?").strip().upper()
        confidence = float(answer.get("confidence") or 0.5)

        # NOTE: distribution["YES"] is always ~0.50 for binary YES/NO questions — a known
        # Jev quirk (#56 in work/jev-links/BRIEF.md). The real probability lives in
        # choice + confidence: choice=YES/conf=0.8 means P(respond)=0.80,
        # choice=NO/conf=0.8 means P(respond)=0.20. Map accordingly.
        if choice == "YES":
            p_respond = confidence
        elif choice == "NO":
            p_respond = 1.0 - confidence
        else:
            p_respond = 0.5  # unknown — cautious middle ground

        respond = p_respond >= threshold
        reason = (
            f"P(YES)={p_respond:.2f} choice={choice} conf={confidence:.2f} "
            f"threshold={threshold} turns={len(recent)}"
        )
        return JevDecision(
            respond=respond,
            p_respond=p_respond,
            reason=reason,
            elapsed_ms=(time.time() - t0) * 1000,
        )
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
    "JevDecision",
    "evaluate",
    "evaluate_sync",
    "layer0_name_mentioned",
    "layer1_only_self",
    "layer2_classify",
    "layer_jev",
]
