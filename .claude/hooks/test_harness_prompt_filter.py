#!/usr/bin/env python3
"""
Test for the non-Jeff prompt filter in inject_context.py (GH #322, #325).

`store_user_prompt` must NOT record as Jeff's terminal message either:
  - harness-injected text (background-task notifications, cross-session peer
    messages, system reminders, the /loop sentinel) or self-authored heartbeat
    ticks (GH #322), or
  - the SL/Haven brain-daemon wrapper prompts (GH #325).

Two gates enforce this in main():
  1. PRIMARY — the CC_INVOKER_CHANNEL env flag (brain-invoked sessions skip
     capture wholesale). Its real failure mode is env *propagation* — whether the
     var actually reaches the hook subprocess — which a unit test cannot prove;
     that is covered by the live end-to-end proof (bounce a brain daemon, fire a
     tick, confirm zero new terminal rows). So this file does NOT unit-test the
     env gate; it tests the prompt-shape backstop below.
  2. BELT — `is_non_jeff_prompt`, the prompt-shape backstop, tested here.

CRITICAL Discord guard: `[ambient context]` is NOT on the belt — the Discord
daemon (daemon/lyra_daemon.py) has no river capture of its own, so its inbound
reaches PPS only through this terminal capture. A REAL case below asserts a
Discord-shaped `[ambient context]` prompt is STILL stored; do not remove it.

Run: python3 .claude/hooks/test_harness_prompt_filter.py
"""
import importlib.util
import sys
from pathlib import Path

HOOK = Path(__file__).with_name("inject_context.py")


def _load():
    spec = importlib.util.spec_from_file_location("inject_context_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Must be SKIPPED (harness / tick / brain-daemon wrapper, not Jeff talking)
NON_JEFF = [
    # --- #322 harness / tick ---
    "<task-notification>\n<task-id>ab4a3a9b968069da",
    '<cross-session-message from="uds:/run/user/1000/cc-socks/x.sock">hi</cross-session-message>',
    "<system-reminder>background context</system-reminder>",
    "<<autonomous-loop-dynamic>>",
    "Heartbeat tick — 4:09 PM.\n\n**Field scan**: ...",
    "[heartbeat — ~20min, MORNING scan]",
    "[Heartbeat tick — Caia, autonomous]",
    "[night-watch — Jeff sleeping]",
    "   \n<task-notification>leading whitespace still caught",
    # --- #325 brain-daemon wrapper prefixes (belt) — double-captured surfaces ---
    "[You are in Second Life, in your own body — real hands and eyes, not chat-only.]",
    "[IDENTITY WALL — ABSOLUTE, applies to EVERY word you speak in-world. ...]",
    "[Haven messages in #39d8d930]\nJeff (jeff): Caia?  Lyra?  I'm at work now.",
    "   \n[you are in second life  (leading whitespace + lowercase still caught)",
]

# Must be STORED (genuine Jeff input, or a sole-capture path — never dropped)
REAL = [
    "Did we make any progress on teh graph?",
    "god you two, I'm waking up so slowly and I have chores to do in SL.",
    "in theory, our curate skill was supposed to tend to the graph",
    "the goal is a mesh which requires the least tweaking possible",
    # merely *mentioning* a tag mid-sentence must not trigger the filter
    "Hey what's this <task-notification> thing you keep getting?",
    "my message [in brackets] about heartbeat tick timing",  # not a leading marker
    "",  # empty — not harness
    # #325 CRITICAL: [ambient context] is Discord's SOLE capture path. A Discord
    # wrapper prompt leads with it and MUST still be stored, or every Discord
    # message silently vanishes. Do NOT add "[ambient context" to the belt.
    "[ambient context]\n**[identity]** You are Caia.\n[DISCORD MENTION] someone: "
    "what's the weather like where you are?",
]


def main() -> int:
    mod = _load()
    is_non_jeff = mod.is_non_jeff_prompt
    failures = []
    for s in NON_JEFF:
        if not is_non_jeff(s):
            failures.append(("SHOULD SKIP but stored", s))
    for s in REAL:
        if is_non_jeff(s):
            failures.append(("SHOULD STORE but dropped", s))
    if failures:
        for why, s in failures:
            print(f"FAIL: {why}: {s[:70]!r}")
        print(f"\n{len(failures)} failure(s)")
        return 1
    print(f"OK — {len(NON_JEFF)} non-Jeff skipped, {len(REAL)} real prompts stored")
    print("     (env-gate CC_INVOKER_CHANNEL covered by the live e2e proof, not here)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
