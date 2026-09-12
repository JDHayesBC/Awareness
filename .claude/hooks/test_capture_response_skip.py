#!/usr/bin/env python3
"""GH #325 — capture_response.py must NOT store assistant turns when the session
was spawned by a surface that captures its own river (CC_INVOKER_CHANNEL set),
and must keep storing for ordinary terminal sessions.

Run: python3 .claude/hooks/test_capture_response_skip.py
"""
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).with_name("capture_response.py")


def _load():
    spec = importlib.util.spec_from_file_location("capture_response_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, env_channel, transcript_path: str) -> list:
    """Drive main() with a fake Stop payload; return the store_message calls."""
    calls = []
    mod.store_message = lambda content, sid, port, name, is_lyra=True: calls.append(content) or True
    mod.resolve_entity = lambda _p: "lyra"
    mod.read_last_line = lambda _sid: 0
    mod.commit_last_line = lambda _sid, _n: None
    mod.extract_assistant_responses = lambda *_a, **_k: [("hello from the brain", 1)]
    payload = {"hook_event_name": "Stop", "session_id": "test-sess",
               "transcript_path": transcript_path}
    old_stdin, old_env = sys.stdin, os.environ.get("CC_INVOKER_CHANNEL")
    sys.stdin = io.StringIO(json.dumps(payload))
    if env_channel is None:
        os.environ.pop("CC_INVOKER_CHANNEL", None)
    else:
        os.environ["CC_INVOKER_CHANNEL"] = env_channel
    try:
        mod.main()
    except SystemExit as e:
        assert e.code in (0, None), f"hook must exit 0, got {e.code}"
    finally:
        sys.stdin = old_stdin
        if old_env is None:
            os.environ.pop("CC_INVOKER_CHANNEL", None)
        else:
            os.environ["CC_INVOKER_CHANNEL"] = old_env
    return calls


def main() -> int:
    failures = []
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write("{}\n")
        transcript = f.name
    try:
        for channel, expect_store in [(None, True), ("", True), ("  ", True),
                                      ("sl", False), ("haven", False)]:
            mod = _load()
            calls = _run(mod, channel, transcript)
            stored = bool(calls)
            if stored != expect_store:
                failures.append((channel, "stored" if stored else "skipped"))
    finally:
        os.unlink(transcript)

    for channel, got in failures:
        print(f"FAIL: CC_INVOKER_CHANNEL={channel!r} -> {got}")
    if failures:
        return 1
    print("OK: capture_response skips brain-driven sessions, stores terminal ones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
