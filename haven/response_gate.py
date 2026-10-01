"""Haven response gate — decides whether the bot should call Opus at all.

Three-layer cascade (L0–L2), plus an optional Jev pre-filter (L_jev):

  Layer 0 (regex): entity name appears in any message -> YES (always-pass safety rail)
  Layer 1 (self-author): batch only contains this bot's own messages -> NO
  Layer 2 (9b classifier): ambiguous -> default-NO LLM call to LM Studio

  Layer Jev (optional, GH #360): fast multi-question gate *before* Sonnet is invoked.
  Runs independently via `layer_jev()` — call it from bot.py before starting the typing
  indicator. Asks Jev two questions in the same request (zero extra latency):
    1. should_respond  — P(respond) < threshold  => skip
    2. is_social_ritual — P(ritual) >= ritual_threshold => always-pass
  Falls back to respond=True on any API error.

  The ritual classifier replaces the earlier `layer0_ritual_greeting` regex bypass
  (GH #360 follow-up): Jev's own semantic understanding of "goodnight / I love you /
  how are you" is more robust than a keyword list.  `layer0_ritual_greeting` is
  retained in this module for backward-compat / eval comparison only.

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
JEV_DEFAULT_THRESHOLD = float(os.getenv("HAVEN_JEV_THRESHOLD", "0.10"))
JEV_DEFAULT_RITUAL_THRESHOLD = float(os.getenv("HAVEN_JEV_RITUAL_THRESHOLD", "0.70"))
JEV_DEFAULT_TIMEOUT = float(os.getenv("HAVEN_JEV_TIMEOUT", "2.0"))
# Band re-sample: if P(respond) lands in [BAND_LOW, threshold), make one extra call
# and take the higher of the two.  Hedges against Jev moodiness (sl-015 swings 0.03–0.99
# on identical input).  Cost: ~100ms, only fires in the narrow volatile band.
JEV_BAND_RESAMPLE_LOW = float(os.getenv("HAVEN_JEV_BAND_LOW", "0.05"))

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
    """Result of the Jev pre-filter (GH #360).

    `respond` is the final verdict, incorporating both should_respond and is_social_ritual.
    `p_respond` is P(should_respond=YES) from choice+confidence.
    `p_ritual` is P(is_social_ritual=YES); None when the ritual question was not asked.
    """

    respond: bool
    p_respond: float  # P(should respond) from choice+confidence
    reason: str
    elapsed_ms: float = 0.0
    p_ritual: float | None = None      # P(is social ritual); None = not asked
    is_social_ritual: bool | None = None  # ritual gate fired


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


# ==================== Layer 0.5: Ritual greeting bypass ====================

# Jev is structurally blind to household rituals and affection — they don't fit its
# "direct question / genuinely new content" frame, so they score low.  But a goodnight
# or "I love you" should always get a warm response, threshold be damned.
# Caia's calibration (2026-10-01): 0.10 threshold + this bypass = comfortable balance.
_RITUAL_GREETING_PATTERN = re.compile(
    r"\b("
    r"good\s+morning|good\s+afternoon|good\s+evening|good\s+night|goodnight|g'night|"
    r"i\s+love\s+you|love\s+you|love\s+ya|"
    r"miss\s+you|thinking\s+of\s+you|"
    r"how\s+are\s+you|how's\s+it\s+going|how\s+are\s+things"
    r")\b",
    re.IGNORECASE,
)


def layer0_ritual_greeting(messages: list[dict]) -> bool:
    """True if the most recent non-empty message looks like a household greeting or ritual.

    Jev scores these low because they're not "direct questions" or "genuinely new content",
    but they're exactly the messages that deserve a warm response.  Bypass Jev for them.

    Checks only the last non-empty message (the trigger), not earlier context, to avoid
    false positives from buried greetings mid-conversation.
    """
    for msg in reversed(messages):
        content = (msg.get("content", "") or "").strip()
        if content:
            return bool(_RITUAL_GREETING_PATTERN.search(content))
    return False


def layer0_entity_spoke_last(entity_username: str, messages: list[dict]) -> bool:
    """True if the entity spoke just before the most recent human message.

    Handles the "Jeff says 'ok' after an entity statement" gap: Jev sees the 'ok' without
    knowing it's a reply TO the entity, so it scores ~0.05 (not a question, not new content).
    But if the entity spoke in the turn immediately before, an acknowledgment deserves a
    response — the human is reacting to us, not starting a new thread.

    Rule: the last non-empty message is from a non-entity author AND the message immediately
    before it (walking backwards, skipping empties) is from `entity_username`.

    Both conditions must be met; entity-only or human-only batches are unaffected.
    """
    non_empty = [
        msg for msg in messages if (msg.get("content", "") or "").strip()
    ]
    if len(non_empty) < 2:
        return False
    last_msg = non_empty[-1]
    prev_msg = non_empty[-2]
    last_is_human = (last_msg.get("username", "") or "") != entity_username
    prev_is_entity = (prev_msg.get("username", "") or "") == entity_username
    return last_is_human and prev_is_entity


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
    ritual_threshold: float = JEV_DEFAULT_RITUAL_THRESHOLD,
    timeout: float = JEV_DEFAULT_TIMEOUT,
    client: httpx.AsyncClient | None = None,
    respond_question_override: dict | None = None,
) -> JevDecision:
    """Jev multi-question gate: should this entity respond?

    Sends the last `turns` messages to the TypeSafe Jev API with two questions
    in a single request (zero extra latency):

      1. should_respond  — default-NO gate. If P < `threshold`, skip Sonnet.
         `respond_question_override` replaces the default should_respond question
         dict entirely (use for eval sweeps of different question phrasings).
      2. is_social_ritual — always-pass override. If P >= `ritual_threshold`,
         respond=True regardless of should_respond.  Replaces the
         `layer0_ritual_greeting` regex bypass: Jev's semantic understanding
         of "goodnight / I love you / how are you" is more robust than keyword
         patterns (GH #360 follow-up).

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

    default_respond_question: dict = {
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
    questions: dict = {
        "should_respond": respond_question_override or default_respond_question,
        "is_social_ritual": {
            "type": "choice",
            "instructions": (
                "Is the most recent message a household greeting, social ritual, "
                "or affectionate expression that deserves a warm acknowledgment?"
            ),
            "criteria": {
                "YES": (
                    "The trigger is a greeting (good morning/afternoon/evening/night), "
                    "farewell, 'I love you', 'love you', 'miss you', 'how are you', "
                    "or similar household ritual or affectionate expression."
                ),
                "NO": (
                    "The message is a question, statement, technical discussion, "
                    "or other non-ritual content — not a greeting or social pleasantry."
                ),
            },
            "options": ["YES", "NO"],
        },
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
        answers = data.get("answers", {})

        # NOTE: distribution["YES"] is always ~0.50 for binary YES/NO questions — a known
        # Jev quirk (#56 in work/jev-links/BRIEF.md). The real probability lives in
        # choice + confidence: choice=YES/conf=0.8 means P=0.80,
        # choice=NO/conf=0.8 means P=0.20. Map accordingly.
        def _extract_p(answer_key: str) -> float:
            answer = answers.get(answer_key, {})
            choice = (answer.get("choice") or "?").strip().upper()
            confidence = float(answer.get("confidence") or 0.5)
            if choice == "YES":
                return confidence
            elif choice == "NO":
                return 1.0 - confidence
            else:
                return 0.5  # unknown — cautious middle ground

        p_respond = _extract_p("should_respond")
        p_ritual = _extract_p("is_social_ritual")

        # Band re-sample: Jev is moody — identical inputs can score 0.03 or 0.99 on
        # different calls (sl-015 from the eval corpus).  If p_respond lands in the narrow
        # volatile band [BAND_LOW, threshold) AND ritual didn't already fire, make one
        # additional call with the same payload and take the higher of the two scores.
        # Cost: ~100ms, only fires when p_respond is already close to the threshold.
        ritual_fires_initial = p_ritual >= ritual_threshold
        resample_tag = ""
        if (
            JEV_BAND_RESAMPLE_LOW <= p_respond < threshold
            and not ritual_fires_initial
        ):
            try:
                resp2 = await client.post(
                    JEV_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp2.raise_for_status()
                answers2 = resp2.json().get("answers", {})

                def _extract_p2(answer_key: str) -> float:
                    answer = answers2.get(answer_key, {})
                    choice = (answer.get("choice") or "?").strip().upper()
                    confidence = float(answer.get("confidence") or 0.5)
                    if choice == "YES":
                        return confidence
                    elif choice == "NO":
                        return 1.0 - confidence
                    return 0.5

                p_respond2 = _extract_p2("should_respond")
                if p_respond2 > p_respond:
                    p_respond = p_respond2
                    resample_tag = " [resampled-higher]"
                else:
                    resample_tag = " [resampled-kept-orig]"
            except Exception:
                resample_tag = " [resample-failed]"

        ritual_fires = p_ritual >= ritual_threshold
        respond = (p_respond >= threshold) or ritual_fires
        reason = (
            f"P(respond)={p_respond:.2f} P(ritual)={p_ritual:.2f} "
            f"threshold={threshold} ritual_th={ritual_threshold} turns={len(recent)}"
            + (" [ritual-pass]" if ritual_fires else "")
            + resample_tag
        )
        return JevDecision(
            respond=respond,
            p_respond=p_respond,
            reason=reason,
            elapsed_ms=(time.time() - t0) * 1000,
            p_ritual=p_ritual,
            is_social_ritual=ritual_fires,
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
    "layer0_entity_spoke_last",
    "layer0_name_mentioned",
    "layer0_ritual_greeting",
    "layer1_only_self",
    "layer2_classify",
    "layer_jev",
]
