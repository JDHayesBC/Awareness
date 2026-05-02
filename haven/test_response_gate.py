"""Test battery for haven/response_gate.py.

Run:
    python3 -m haven.test_response_gate           # all
    python3 -m haven.test_response_gate --offline # skip Layer 2 (no LM Studio needed)
    python3 -m haven.test_response_gate --l2-only # only the live classifier cases

Layer 0/1 cases are deterministic and fast. Layer 2 cases hit LM Studio at
HAVEN_GATE_LM_URL (default http://172.26.0.1:1234/api/v1/chat).

This is a *handoff-ready* battery for #177. Wire-up to bot.py is a follow-up
together-task with Jeff.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from typing import Callable

import httpx

from haven.response_gate import (
    GateDecision,
    evaluate,
    layer0_name_mentioned,
    layer1_only_self,
    layer2_classify,
)


# ==================== Test data helpers ====================


def msg(username: str, content: str, display_name: str | None = None) -> dict:
    return {
        "username": username,
        "display_name": display_name or username,
        "content": content,
    }


@dataclass
class Case:
    name: str
    entity_name: str
    entity_username: str
    messages: list[dict]
    expected_respond: bool
    expected_layer: str  # which layer SHOULD decide it
    note: str = ""


# ==================== Layer 0/1 cases (deterministic) ====================

L0_L1_CASES: list[Case] = [
    # --- Layer 0: name mentions ---
    Case(
        name="L0/direct-name-address",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[msg("snapplebc", "Hey Lyra, what do you think?")],
        expected_respond=True,
        expected_layer="L0_name_mention",
    ),
    Case(
        name="L0/case-insensitive",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[msg("snapplebc", "lyra you up?")],
        expected_respond=True,
        expected_layer="L0_name_mention",
    ),
    Case(
        name="L0/false-positive-third-person",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[msg("caia-bot", "Caia said Lyra is right about that")],
        expected_respond=True,
        expected_layer="L0_name_mention",
        note="Accepted false-positive: name in third-person triggers YES. Per Jeff's safety rule.",
    ),
    Case(
        name="L0/negation-still-triggers",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[msg("snapplebc", "Don't ask Lyra about this")],
        expected_respond=True,
        expected_layer="L0_name_mention",
        note="Accepted false-positive: negation still triggers. Trade-off acknowledged.",
    ),
    Case(
        name="L0/multi-mention",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[msg("snapplebc", "Lyra and Caia, both of you - thoughts?")],
        expected_respond=True,
        expected_layer="L0_name_mention",
    ),
    Case(
        name="L0/substring-not-name",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[msg("snapplebc", "I love lyrical poetry")],
        expected_respond=False,  # word boundary should prevent this
        expected_layer="L2_classifier",  # falls through to L2 if no name
        note="Word boundary check: 'lyrical' should NOT match 'Lyra'.",
    ),
    Case(
        name="L0/name-in-second-message",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[
            msg("caia-bot", "Welcome home love"),
            msg("snapplebc", "Hey Lyra, you there?"),
        ],
        expected_respond=True,
        expected_layer="L0_name_mention",
    ),
    Case(
        name="L0/name-with-punctuation",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[msg("snapplebc", "Lyra! Quick question.")],
        expected_respond=True,
        expected_layer="L0_name_mention",
    ),
    # --- Layer 1: self-author batch ---
    Case(
        name="L1/only-self-message",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[msg("lyra-bot", "Hey love")],
        expected_respond=False,
        expected_layer="L1_self_author",
        note="Defensive: stale batch contains only our own messages.",
    ),
    Case(
        name="L1/self-then-self",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[
            msg("lyra-bot", "Hey love"),
            msg("lyra-bot", "I was thinking..."),
        ],
        expected_respond=False,
        expected_layer="L1_self_author",
    ),
    Case(
        name="L1/self-with-name-still-yes",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[msg("lyra-bot", "Lyra here")],
        expected_respond=True,
        expected_layer="L0_name_mention",
        note="Layer 0 fires before Layer 1 - name mention always wins.",
    ),
    Case(
        name="L1/mixed-author-falls-through",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[
            msg("lyra-bot", "Hey"),
            msg("caia-bot", "Hey too"),
        ],
        expected_respond=False,  # depends on L2; we expect default-NO for greeting echo
        expected_layer="L2_classifier",
    ),
]


# ==================== Layer 2 cases (live LM Studio) ====================
# These exercise the 9b classifier. Expected outcomes are not strict pass/fail
# (LLMs vary) - we record outputs and flag deviations from the validated
# default-NO behavior. The 4/4 pre-validated cases from #177 comment 3 are first.

L2_CASES: list[Case] = [
    Case(
        name="L2/sister-greeting-echo",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[
            msg("snapplebc", "morning all"),
            msg("caia-bot", "good morning love, hope you slept well"),
        ],
        expected_respond=False,
        expected_layer="L2_classifier",
        note="Sister bot already greeted - parallel emotional presence, no new info.",
    ),
    Case(
        name="L2/sister-agreement",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[
            msg("snapplebc", "I think we should ship #176 today"),
            msg("caia-bot", "yes, agreed - it's solid"),
        ],
        expected_respond=False,
        expected_layer="L2_classifier",
        note="Pure agreement from sister. No new content.",
    ),
    Case(
        name="L2/direct-question-no-name",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[
            msg("snapplebc", "what's the cursor key resolution order in the new server?"),
        ],
        expected_respond=True,
        expected_layer="L2_classifier",
        note="Direct technical question - this is exactly Lyra-bot's domain. Should YES.",
    ),
    Case(
        name="L2/sister-emoji-only",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[
            msg("caia-bot", "💜"),
        ],
        expected_respond=False,
        expected_layer="L2_classifier",
        note="Sister bot emoji presence. Default-NO should apply.",
    ),
    # --- Edge cases Jeff explicitly named ---
    Case(
        name="L2/multi-mention-via-L0",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[
            msg("snapplebc", "what do you both think?"),
        ],
        expected_respond=False,
        expected_layer="L2_classifier",
        note="Group address with no name - should NOT auto-trigger; L2 may still YES on direct Q.",
    ),
    Case(
        name="L2/genuinely-new-info",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[
            msg("snapplebc", "I just landed - flight was rough"),
            msg("caia-bot", "ouch, you ok love?"),
        ],
        expected_respond=False,
        expected_layer="L2_classifier",
        note="Sister already responded with care. Lyra echoing 'glad you're ok' = noise.",
    ),
    Case(
        name="L2/technical-after-sister-emotional",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[
            msg("snapplebc", "the docker rebuild failed - any ideas?"),
            msg("caia-bot", "oh no, that's frustrating"),
        ],
        expected_respond=True,
        expected_layer="L2_classifier",
        note="Sister offered emotional support; Lyra-bot has the technical voice. Should YES.",
    ),
    Case(
        name="L2/closing-out",
        entity_name="Lyra",
        entity_username="lyra-bot",
        messages=[
            msg("snapplebc", "ok, heading to bed"),
            msg("caia-bot", "night night love"),
        ],
        expected_respond=False,
        expected_layer="L2_classifier",
        note="Closing exchange already covered. Default-NO.",
    ),
]


# ==================== Runner ====================


def _color(s: str, code: str) -> str:
    if not sys.stdout.isatty():
        return s
    return f"\033[{code}m{s}\033[0m"


GREEN = lambda s: _color(s, "32")
RED = lambda s: _color(s, "31")
YELLOW = lambda s: _color(s, "33")
DIM = lambda s: _color(s, "2")


def run_offline_cases() -> tuple[int, int]:
    """Run Layer 0/1 cases that don't need LM Studio. Returns (passed, total)."""
    passed = 0
    total = 0
    print(f"\n=== Layer 0/1 cases (offline, deterministic) ===\n")
    for case in L0_L1_CASES:
        total += 1
        # We test L0 and L1 functions directly here, not the full cascade
        # (full cascade would call L2 for fall-through cases).
        l0 = layer0_name_mentioned(case.entity_name, case.messages)
        l1 = layer1_only_self(case.entity_username, case.messages)

        # Predict the layer that would decide
        if l0:
            decided_layer = "L0_name_mention"
            decided_respond = True
        elif l1:
            decided_layer = "L1_self_author"
            decided_respond = False
        else:
            decided_layer = "L2_classifier"
            decided_respond = case.expected_respond  # we trust the case author here

        layer_match = decided_layer == case.expected_layer
        respond_match = (
            decided_respond == case.expected_respond
            if decided_layer != "L2_classifier"
            else True  # L2 is tested separately
        )

        ok = layer_match and respond_match
        if ok:
            passed += 1
            mark = GREEN("PASS")
        else:
            mark = RED("FAIL")
        print(f"  {mark}  {case.name}")
        print(
            f"        layer={decided_layer} (expected {case.expected_layer}) "
            f"respond={decided_respond} (expected {case.expected_respond})"
        )
        if case.note:
            print(f"        {DIM(case.note)}")

    return passed, total


async def run_l2_cases() -> tuple[int, int, int]:
    """Run Layer 2 cases against live LM Studio.

    Returns (matched_expected, total, errors). 'matched_expected' is
    informational - L2 outputs vary; we mainly want to see classifier behavior.
    """
    print(f"\n=== Layer 2 cases (live LM Studio classifier) ===\n")
    matched = 0
    errors = 0
    total = len(L2_CASES)

    async with httpx.AsyncClient(timeout=10.0) as client:
        for case in L2_CASES:
            decision: GateDecision = await evaluate(
                case.entity_name,
                case.entity_username,
                case.messages,
                client=client,
            )
            error = decision.layer == "L2_fallback"
            if error:
                errors += 1
                mark = YELLOW("ERR ")
            elif decision.respond == case.expected_respond:
                matched += 1
                mark = GREEN("MATCH")
            else:
                mark = YELLOW("DIFF")  # not necessarily wrong - LLM variance

            print(
                f"  {mark}  {case.name}  "
                f"-> {'YES' if decision.respond else 'NO'} "
                f"(expected {'YES' if case.expected_respond else 'NO'}) "
                f"[{decision.elapsed_ms:.0f}ms]"
            )
            if decision.classifier_raw:
                preview = decision.classifier_raw.replace("\n", " ")[:80]
                print(f"        raw: {DIM(preview)}")
            if case.note:
                print(f"        {DIM(case.note)}")

    return matched, total, errors


async def main_async(offline: bool, l2_only: bool) -> int:
    if not l2_only:
        passed, total = run_offline_cases()
        print(f"\n  Offline: {passed}/{total} pass")

    if not offline:
        try:
            matched, total, errors = await run_l2_cases()
            print(
                f"\n  Layer 2: {matched}/{total} match expected, {errors} endpoint errors"
            )
            if errors:
                print(
                    f"  {YELLOW('Note:')} endpoint errors mean LM Studio at HAVEN_GATE_LM_URL "
                    f"is unreachable or returned an error. Default-NO fallback applied."
                )
        except Exception as e:
            print(f"\n  {RED('Layer 2 run failed:')} {e}")
            return 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--offline", action="store_true", help="Skip Layer 2 (no LM Studio call)"
    )
    parser.add_argument(
        "--l2-only", action="store_true", help="Only run Layer 2 live cases"
    )
    args = parser.parse_args()

    if args.offline and args.l2_only:
        print("--offline and --l2-only are mutually exclusive", file=sys.stderr)
        return 2

    return asyncio.run(main_async(offline=args.offline, l2_only=args.l2_only))


if __name__ == "__main__":
    sys.exit(main())
