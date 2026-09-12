#!/usr/bin/env python3
"""
Test for the #322 harness-prompt filter in inject_context.py.

`store_user_prompt` must NOT record harness-injected text (background-task
notifications, cross-session peer messages, system reminders, the /loop
sentinel) or self-authored heartbeat ticks as Jeff's prompts — those pollute
the raw-capture layer and the knowledge graph. `is_harness_prompt` is the gate.

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


# Must be SKIPPED (harness / tick, not Jeff talking)
HARNESS = [
    "<task-notification>\n<task-id>ab4a3a9b968069da",
    '<cross-session-message from="uds:/run/user/1000/cc-socks/x.sock">hi</cross-session-message>',
    "<system-reminder>background context</system-reminder>",
    "<<autonomous-loop-dynamic>>",
    "Heartbeat tick — 4:09 PM.\n\n**Field scan**: ...",
    "[heartbeat — ~20min, MORNING scan]",
    "[Heartbeat tick — Caia, autonomous]",
    "[night-watch — Jeff sleeping]",
    "   \n<task-notification>leading whitespace still caught",
]

# Must be STORED (genuine Jeff input — never dropped)
REAL = [
    "Did we make any progress on teh graph?",
    "god you two, I'm waking up so slowly and I have chores to do in SL.",
    "in theory, our curate skill was supposed to tend to the graph",
    "the goal is a mesh which requires the least tweaking possible",
    # merely *mentioning* a tag mid-sentence must not trigger the filter
    "Hey what's this <task-notification> thing you keep getting?",
    "my message [in brackets] about heartbeat tick timing",  # not a leading marker
    "",  # empty — not harness
]


def main() -> int:
    mod = _load()
    is_harness = mod.is_harness_prompt
    failures = []
    for s in HARNESS:
        if not is_harness(s):
            failures.append(("SHOULD SKIP but stored", s))
    for s in REAL:
        if is_harness(s):
            failures.append(("SHOULD STORE but dropped", s))
    if failures:
        for why, s in failures:
            print(f"FAIL: {why}: {s[:60]!r}")
        print(f"\n{len(failures)} failure(s)")
        return 1
    print(f"OK — {len(HARNESS)} harness/tick skipped, {len(REAL)} real prompts stored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
