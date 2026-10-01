#!/usr/bin/env python3
"""
blender_exec.py — send Python to a running Blender via the official Blender MCP add-on.

The Blender-Lab MCP add-on (blender.org/lab/mcp-server) runs a TCP server inside
Blender that executes arbitrary `bpy` code. This is a thin client for it, so we can
drive Blender straight from the terminal (WSL) without the full MCP/Claude-Code
wiring or a session restart.

Host/port default to the WSL->Windows NAT gateway; override with env vars
BLENDER_MCP_HOST / BLENDER_MCP_PORT (matches the add-on's own env names).

Usage:
    python3 scripts/blender_exec.py -c "import bpy; print(bpy.app.version_string)"
    python3 scripts/blender_exec.py path/to/script.py
    echo "import bpy; print(len(bpy.data.objects))" | python3 scripts/blender_exec.py -
"""
import argparse
import json
import os
import socket
import sys

HOST = os.environ.get("BLENDER_MCP_HOST", "172.26.0.1")
PORT = int(os.environ.get("BLENDER_MCP_PORT", "9876"))
TIMEOUT = float(os.environ.get("BLENDER_MCP_TIMEOUT", "120"))


def send_code(code: str, strict_json: bool = False) -> dict:
    req = json.dumps({"type": "execute", "code": code, "strict_json": strict_json}) + "\0"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(TIMEOUT)
        s.connect((HOST, PORT))
        s.sendall(req.encode("utf-8"))
        buf = bytearray()
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            if b"\0" in buf:
                break
    line, _, _ = buf.partition(b"\0")
    return json.loads(line.decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Execute Python inside a running Blender via the MCP add-on.")
    ap.add_argument("source", nargs="?", help="Path to a .py file, or '-' to read stdin.")
    ap.add_argument("-c", "--code", help="Inline code to execute.")
    ap.add_argument("--strict-json", action="store_true", help="Ask the add-on for strict-JSON result.")
    ap.add_argument("--raw", action="store_true", help="Print the raw response dict.")
    args = ap.parse_args()

    if args.code is not None:
        code = args.code
    elif args.source == "-":
        code = sys.stdin.read()
    elif args.source:
        with open(args.source, "r") as f:
            code = f.read()
    else:
        ap.error("provide -c CODE, a file path, or '-' for stdin")

    try:
        resp = send_code(code, strict_json=args.strict_json)
    except (ConnectionError, OSError) as ex:
        print(f"[blender_exec] cannot reach Blender at {HOST}:{PORT} — is the add-on server started? ({ex})",
              file=sys.stderr)
        return 2

    if args.raw:
        print(json.dumps(resp, indent=2))
        return 0 if resp.get("status") == "ok" else 1

    status = resp.get("status")
    stdout = resp.get("stdout") or ""
    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n")
    if resp.get("result") not in (None, {}, ""):
        print("RESULT:", resp["result"])
    if status != "ok":
        print(f"[blender_exec] STATUS={status}", file=sys.stderr)
        if resp.get("message"):
            print(resp["message"], file=sys.stderr)
        if resp.get("stderr"):
            print(resp["stderr"], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
