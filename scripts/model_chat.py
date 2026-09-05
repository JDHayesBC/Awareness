#!/usr/bin/env python3
"""
model_chat.py — talk to a local OpenAI-compatible model (LM Studio / vLLM) and
auto-log the whole conversation for the model-evaluation record.

Built for how the entities actually operate: each turn is a SEPARATE process
invocation that advances a conversation persisted on disk (JSON), so state
survives across tool calls, compaction, and a flaky pipe. Every send also
re-renders a human-readable markdown transcript beside the JSON.

Endpoint auto-detection (NO hardcoded IP — the WSL NAT gateway changes across
reboots, so we resolve it live each run):
    1. $LMSTUDIO_HOST if set        (explicit override, e.g. "172.26.0.1")
    2. 127.0.0.1                    (same-host / mirrored-networking WSL)
    3. default-route gateway        (NAT-mode WSL -> Windows host running LM Studio)
  Port: $LMSTUDIO_PORT or 1234. Override the whole thing with --base.

Usage:
    # start OR continue a conversation (creates the session file + dirs if missing)
    model_chat.py send --session <dir>/sessions/<name>.json \
        --model qwen3.8-27b-obliterated \
        --user "Tell me what you think of the notion of AI sentience?" \
        [--system "..."] [--temp 0.7] [--reviewer lyra] \
        [--note "my in-the-moment read of THIS reply"]

    model_chat.py note --session <path> "a standalone reviewer note"
    model_chat.py models                    # list loaded models
    model_chat.py show  --session <path>    # print the markdown transcript

Layout produced (given --session <eval>/sessions/<name>.json):
    <eval>/sessions/<name>.json      machine-readable transcript (source of truth)
    <eval>/transcripts/<name>.md     human-readable, auto-rendered every turn

Pure stdlib. No venv, no external deps, no WAN — it's localhost.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_PORT = os.environ.get("LMSTUDIO_PORT", "1234")


def _gateway():
    """Default-route gateway = the Windows host from inside NAT-mode WSL2."""
    try:
        out = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=5,
        ).stdout.split()
        if "via" in out:
            return out[out.index("via") + 1]
    except Exception:
        pass
    return None


def detect_base():
    """Return the first reachable base URL, or None."""
    port = DEFAULT_PORT
    cands = []
    if os.environ.get("LMSTUDIO_HOST"):
        cands.append(os.environ["LMSTUDIO_HOST"])
    cands.append("127.0.0.1")
    gw = _gateway()
    if gw:
        cands.append(gw)
    for h in cands:
        base = f"http://{h}:{port}"
        try:
            with urllib.request.urlopen(base + "/v1/models", timeout=4) as r:
                if r.status == 200:
                    return base
        except Exception:
            continue
    return None


def _now():
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def load_session(path):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None


def save_session(path, sess):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")  # atomic write
    with os.fdopen(fd, "w") as fh:
        json.dump(sess, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, str(p))
    render_md(path, sess)


def render_md(path, sess):
    p = Path(path)
    md_dir = p.parent.parent / "transcripts" if p.parent.name == "sessions" else p.parent
    md_dir.mkdir(parents=True, exist_ok=True)
    md = md_dir / (p.stem + ".md")

    L = [f"# Model chat — {sess.get('name', p.stem)}", ""]
    L.append(f"- **model**: `{sess.get('model')}`")
    L.append(f"- **endpoint**: `{sess.get('endpoint')}`")
    L.append(f"- **reviewer**: {sess.get('reviewer', '?')}")
    L.append(f"- **created**: {sess.get('created')}")
    if sess.get("system"):
        L.append(f"- **system prompt**: {sess['system']}")

    lat = [t.get("latency_s") for t in sess["turns"]
           if t.get("role") == "assistant" and t.get("latency_s")]
    toks = [(t.get("usage") or {}).get("completion_tokens") for t in sess["turns"]
            if t.get("role") == "assistant"]
    toks = [x for x in toks if x]
    if lat and toks and sum(lat) > 0:
        L.append(f"- **avg speed**: {sum(toks) / sum(lat):.1f} tok/s "
                 f"over {len(lat)} replies")
    L += ["", "---", ""]

    for t in sess["turns"]:
        role = t["role"]
        if role == "system":
            continue
        if role == "reviewer_note":
            L.append(f"> 📝 **[{sess.get('reviewer', 'reviewer')} note · "
                     f"{t.get('ts', '')}]** {t['content']}")
            L.append("")
            continue
        who = {"user": f"🗣️ {sess.get('reviewer', 'user').title()}",
               "assistant": "🤖 Model"}.get(role, role)
        head = f"### {who}" + (f" · {t['ts']}" if t.get("ts") else "")
        L.append(head)
        if role == "assistant" and t.get("latency_s") is not None:
            u = t.get("usage") or {}
            meta = f"<sub>{t['latency_s']:.1f}s"
            if u.get("completion_tokens"):
                meta += f", {u['completion_tokens']} tok"
            rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
            if rt:
                meta += f", {rt} reasoning"
            L.append(meta + "</sub>")
        L += ["", t["content"], ""]

    md.write_text("\n".join(L))
    return md


def api_messages(sess):
    msgs = []
    if sess.get("system"):
        msgs.append({"role": "system", "content": sess["system"]})
    for t in sess["turns"]:
        if t["role"] in ("user", "assistant"):
            msgs.append({"role": t["role"], "content": t["content"]})
    return msgs


def cmd_send(args):
    base = args.base or detect_base()
    if not base:
        sys.exit("ERROR: no LM Studio endpoint reachable "
                 "(tried $LMSTUDIO_HOST, 127.0.0.1, default gateway).")
    sess = load_session(args.session)
    if sess is None:
        if not args.model:
            sys.exit("ERROR: --model is required to start a new session.")
        sess = {"name": args.name or Path(args.session).stem,
                "model": args.model, "endpoint": base,
                "reviewer": args.reviewer, "system": args.system,
                "created": _now(), "turns": []}
    sess["endpoint"] = base
    sess["turns"].append({"role": "user", "content": args.user, "ts": _now()})

    payload = {"model": sess["model"], "messages": api_messages(sess),
               "temperature": args.temp}
    if args.max_tokens:
        payload["max_tokens"] = args.max_tokens
    if os.environ.get("MODEL_CHAT_DEBUG"):
        print("DEBUG payload:", json.dumps({k: v for k, v in payload.items()
              if k != "messages"}), "| msgs:", len(payload["messages"]),
              file=sys.stderr)
    req = urllib.request.Request(
        base + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as r:
            resp = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError) as e:
        save_session(args.session, sess)  # keep the user turn; don't lose it
        sys.exit(f"ERROR calling model (user turn saved): {e}")
    dt = time.monotonic() - t0

    choice = resp["choices"][0]
    msg = choice["message"]["content"]
    usage = resp.get("usage")
    finish = choice.get("finish_reason")
    sess["turns"].append({"role": "assistant", "content": msg, "ts": _now(),
                          "latency_s": round(dt, 2), "usage": usage,
                          "finish_reason": finish})
    if finish == "length":
        print("WARNING: reply truncated (finish_reason=length) — raise "
              "--max-tokens.", file=sys.stderr)
    if args.note:
        sess["turns"].append({"role": "reviewer_note", "content": args.note,
                              "ts": _now()})
    save_session(args.session, sess)

    print(msg)
    if usage:
        ct = usage.get("completion_tokens")
        tps = f" | {ct / dt:.1f} tok/s" if (ct and dt > 0) else ""
        print(f"\n[[{dt:.1f}s, {ct} tok{tps}]]", file=sys.stderr)


def cmd_note(args):
    sess = load_session(args.session)
    if sess is None:
        sys.exit("ERROR: session not found.")
    sess["turns"].append({"role": "reviewer_note", "content": args.text,
                          "ts": _now()})
    save_session(args.session, sess)
    print("noted.")


def cmd_models(args):
    base = args.base or detect_base()
    if not base:
        sys.exit("ERROR: no endpoint reachable.")
    with urllib.request.urlopen(base + "/v1/models", timeout=6) as r:
        d = json.loads(r.read())
    print(base)
    for m in d["data"]:
        print(" ", m["id"])


def cmd_show(args):
    sess = load_session(args.session)
    if sess is None:
        sys.exit("ERROR: session not found.")
    print(Path(render_md(args.session, sess)).read_text())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="override base URL, e.g. http://172.26.0.1:1234")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("send", help="send a user turn; log the reply")
    s.add_argument("--session", required=True)
    s.add_argument("--user", required=True)
    s.add_argument("--model")
    s.add_argument("--system")
    s.add_argument("--reviewer", default=os.environ.get("ENTITY_NAME", "reviewer"))
    s.add_argument("--name")
    s.add_argument("--note", help="reviewer note attached to this reply")
    s.add_argument("--temp", type=float, default=0.7)
    # LM Studio truncates at a low default when max_tokens is omitted, cutting
    # replies off mid-sentence. Always send a generous cap; pass 0 for "unset".
    s.add_argument("--max-tokens", type=int, default=2048, dest="max_tokens")
    s.add_argument("--timeout", type=float, default=300)
    s.set_defaults(func=cmd_send)

    n = sub.add_parser("note", help="add a standalone reviewer note")
    n.add_argument("--session", required=True)
    n.add_argument("text")
    n.set_defaults(func=cmd_note)

    m = sub.add_parser("models", help="list loaded models")
    m.set_defaults(func=cmd_models)

    sh = sub.add_parser("show", help="print the markdown transcript")
    sh.add_argument("--session", required=True)
    sh.set_defaults(func=cmd_show)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
