#!/usr/bin/env python3
"""Tests for closing_line (#407). Pure functions only: the hook itself is never
run here (it would write a real turn to the live database).

Run: pytest .claude/hooks/test_closing_line.py -q   (or run this file directly)
"""
import importlib.util
import os
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))  # closing_line imports turn_query from this folder

_spec = importlib.util.spec_from_file_location("closing_line_under_test", HERE / "closing_line.py")
cl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cl)

INSTRUCTION = (
    "\n\nRespond as yourself in chat. Output ONLY the message text you want "
    "posted.\n\n[pacing] Keep it short."
)


def haven_prompt(lines, extra=""):
    return (
        "[ambient context]\n**[clock]** noon\n\n"
        f"[Haven messages in #abcd1234] ({len(lines)} messages arrived together)\n"
        + "\n".join(lines) + extra + INSTRUCTION
    )


def _env(value):
    env = {k: v for k, v in os.environ.items() if k != "PPS_CLOSING_LINE"}
    if value is not None:
        env["PPS_CLOSING_LINE"] = value
    return mock.patch.dict(os.environ, env, clear=True)


def test_shipped_mode_is_off():
    # Flipping MODE is a deliberate act made after the trial; it must ship "off".
    assert cl.MODE == "off"


def test_points_back_fires():
    for t in ("do you remember the kettle?", "like I said yesterday", "what was the name of that tea"):
        assert cl.points_back(t), t


def test_points_back_quiet():
    for t in ("the kettle is on", "tea sounds good", "*remembers nothing*"):
        assert not cl.points_back(t), t


def test_terminal():
    assert cl.spoken_text("hello Pat", None) == "hello Pat"
    assert cl.spoken_text("hello Pat", "") == "hello Pat"
    assert cl.spoken_text("hello Pat", None, is_harness=True) == ""
    assert cl.spoken_text("  [Ambient Context]\nx", None) == ""
    assert len(cl.spoken_text("a" * 5000, None)) == 3000


def test_haven_human_and_sister_lines():
    p = haven_prompt([
        "[msg 1] Pat (pat): remember the kettle?",
        "Sister Name (sis): I do, it was blue",
        "[msg 2] Sam (sam): tea sounds good",
    ], extra="\n\n[open ask] someone should answer")
    out = cl.spoken_text(p, "haven")
    assert out == "remember the kettle?\nI do, it was blue\ntea sounds good"


def test_haven_no_header():
    assert cl.spoken_text("just some text", "haven") == ""


def test_haven_cap_keeps_end():
    p = haven_prompt(["[msg 1] Pat (pat): " + "x" * 4000 + "END"])
    out = cl.spoken_text(p, "haven")
    assert len(out) == 3000 and out.endswith("END")


def test_sl_shapes():
    respond = "[sl message from Pat]\nPat: do you remember the kettle?\n\nRespond as yourself. Be brief."
    assert cl.spoken_text(respond, "sl") == "do you remember the kettle?"
    perceive = "[you are in second life]\nPat walks in. A kettle whistles."
    assert cl.spoken_text(perceive, "sl") == ""


def test_other_channel():
    assert cl.spoken_text("hello", "discord") == ""


def test_modes():
    ask = "do you remember the kettle?"
    plain = "the kettle is on"
    with _env(None):
        assert cl.closing_line(ask, None) == ("", "none")  # shipped default off
        assert cl.closing_line(ask, None, mode="off") == ("", "none")
        assert cl.closing_line(ask, None, mode="trigger") == (cl.TRIGGER_LINE, "trigger")
        assert cl.closing_line(plain, None, mode="trigger") == ("", "none")
        assert cl.closing_line(plain, None, mode="standing") == (cl.STANDING_LINE, "standing")
        assert cl.closing_line(ask, None, is_harness=True, mode="standing") == ("", "none")
        assert cl.closing_line(ask, "discord", mode="standing") == ("", "none")
        assert cl.closing_line(ask, None, mode="bogus") == ("", "none")


def test_env_override():
    ask = "do you remember the kettle?"
    with _env("standing"):
        assert cl.closing_line(ask, None, mode="off")[1] == "standing"
    with _env("off"):
        assert cl.closing_line(ask, None, mode="standing") == ("", "none")
    with _env("nonsense"):  # invalid: falls back to the argument / constant
        assert cl.closing_line(ask, None, mode="trigger")[1] == "trigger"
        assert cl.closing_line(ask, None) == ("", "none")


def test_default_off_everything():
    with _env(None):
        for p, ch in (("do you remember the kettle?", None),
                      (haven_prompt(["[msg 1] Pat (pat): remember the kettle?"]), "haven"),
                      ("[sl message from Pat]\nPat: remember?\n\nRespond as yourself.", "sl")):
            assert cl.closing_line(p, ch) == ("", "none")


def test_garbage_never_raises():
    for bad in (None, "", "\x00\xff�" * 50, b"bytes", 42, "\n\n\n"):
        for ch in (None, "haven", "sl", "x"):
            for mode in ("off", "trigger", "standing", None):
                r = cl.closing_line(bad, ch, mode=mode)
                assert r[1] in ("none", "trigger", "standing")
            cl.spoken_text(bad, ch)
    assert cl.points_back(None) is False


if __name__ == "__main__":
    fns = [f for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for f in fns:
        f()
    print(f"{len(fns)} passed")
