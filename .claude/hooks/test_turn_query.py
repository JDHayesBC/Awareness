#!/usr/bin/env python3
"""Tests for turn_query.extract_turn_query (#409). Pure function only: the hook
itself is never run here (it would write a real turn to the live database).

Run: pytest .claude/hooks/test_turn_query.py -q   (or run this file directly)
"""
import importlib.util
import sys
from pathlib import Path

MOD = Path(__file__).with_name("turn_query.py")
_spec = importlib.util.spec_from_file_location("turn_query_under_test", MOD)
tq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tq)

INSTRUCTION = (
    "\n\nRespond as yourself in chat. Output ONLY the message text you want "
    "posted. To stay silent, output the exact token [[NO_RESPONSE]]."
    "\nThese messages arrived in quick succession - craft ONE cohesive response."
    "\n\n[pacing] Keep it short."
)


def haven_prompt(lines, extra=""):
    return (
        "[ambient context]\n**[clock]** noon\n- an unrelated recalled fact\n\n"
        f"[Haven messages in #abcd1234] ({len(lines)} messages arrived together)\n"
        + "\n".join(lines)
        + extra
        + INSTRUCTION
    )


def test_haven_three_messages():
    p = haven_prompt([
        "[msg 10] Pat (pat): the kettle is on",
        "[msg 11] Sam (sam): tea sounds good",
        "[msg 12] Pat (pat): milk or lemon?",
    ])
    assert tq.extract_turn_query(p, "haven") == (
        "the kettle is on\ntea sounds good\nmilk or lemon?"
    )


def test_haven_multiline_message():
    p = haven_prompt([
        "[msg 10] Pat (pat): first line",
        "second line",
        "",
        "third after a gap",
        "[msg 11] Sam (sam): single",
    ])
    assert tq.extract_turn_query(p, "haven") == (
        "first line second line third after a gap\nsingle"
    )


def test_haven_display_name_with_parentheses_and_open_ask_note():
    p = haven_prompt(
        ["[msg 3] Pat (he) (pat): who wants the garden job?"],
        extra="\n\n[open ask] You and your sister are both here.\nclaim it before you answer",
    )
    assert tq.extract_turn_query(p, "haven") == "who wants the garden job?"


def test_haven_no_messages_returns_prompt_unchanged():
    p = haven_prompt(["Caia (caia): only a sister spoke"])
    assert tq.extract_turn_query(p, "haven") == p


def test_terminal_prompt_unchanged():
    p = "[msg 1] Pat (pat): looks like a haven line but this is a terminal"
    assert tq.extract_turn_query(p, None) == p
    assert tq.extract_turn_query(p, "") == p
    assert tq.extract_turn_query(p, "discord") == p


def test_garbage_unchanged():
    for g in ["", "\x00\x01 [msg", "[Haven messages in #", "[sl message from \n", "[msg 5] x"]:
        assert tq.extract_turn_query(g, "haven") == g
        assert tq.extract_turn_query(g, "sl") == g
    assert tq.extract_turn_query("[Haven messages in #", "haven") == "[Haven messages in #"
    assert tq.extract_turn_query("", "sl") == ""
    assert tq.extract_turn_query(None, "haven") is None  # type: ignore[arg-type]


def test_cap_keeps_recent_end():
    p = haven_prompt([
        "[msg 1] Pat (pat): " + "a" * 700,
        "[msg 2] Pat (pat): " + "z" * 700,
    ])
    out = tq.extract_turn_query(p, "haven")
    assert len(out) == 800
    assert out.endswith("z" * 700)
    assert out.startswith("a")


def test_sl_respond_shape():
    p = (
        "[IDENTITY WALL] be careful\n\n[ambient context]\nstuff\n\n"
        "[sl message from Wren Example]\nWren Example: hello there,\nhow is the pond?"
        "\n\nRespond as yourself. Output ONLY the message text you want sent."
        "\n\nYou are directly addressed by name."
    )
    assert tq.extract_turn_query(p, "sl") == "hello there, how is the pond?"


def test_sl_perceive_shape_left_unchanged():
    p = (
        "[Second Life - you are present in-world right now]\nScene: a dock\n\n"
        "Since you last looked, this happened:\n- someone waved\n\n"
        "Output ONLY the words you say ALOUD"
    )
    assert tq.extract_turn_query(p, "sl") == p


def main() -> int:
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
