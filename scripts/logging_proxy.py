#!/usr/bin/env python3
"""
HTTP Logging Proxy for Graphiti Sandbox Validation

Intercepts all /v1/chat/completions calls from graphiti_core,
logs request and response details, and forwards to the real haiku wrapper.

Use this to see ALL ~38 API calls per message ingestion.

Usage:
    # Terminal 1: Start proxy
    python3 scripts/logging_proxy.py

    # Terminal 2: Run sandbox test (points graphiti at port 8297)
    python3 scripts/sandbox_test.py --count 10

    Press Ctrl+C to stop proxy and see call summary.

Args:
    --port PORT       Listen port (default: 8297)
    --upstream URL    Upstream haiku wrapper URL (default: http://localhost:8204)
    --verbose         Show full request/response bodies (default: first 500 chars)
    --quiet           Only show errors and summary, not per-call logs
"""

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from datetime import datetime

import aiohttp
from aiohttp import web


# =============================================================================
# State
# =============================================================================

call_count = 0
schema_counts: dict[str, int] = defaultdict(int)
error_count = 0
total_elapsed = 0.0


# =============================================================================
# Proxy Handler
# =============================================================================

async def proxy_handler(request: web.Request, upstream: str, verbose: bool, quiet: bool) -> web.Response:
    """Handle incoming request: log it, forward to upstream, log response."""
    global call_count, error_count, total_elapsed

    # Pass non-completions requests through silently
    if request.method == "GET" or request.path != "/v1/chat/completions":
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method=request.method,
                url=upstream + str(request.rel_url),
                data=await request.read(),
                headers={k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")},
            ) as resp:
                body = await resp.read()
                return web.Response(body=body, status=resp.status, content_type="application/json")

    # Parse request body
    raw_body = await request.read()
    try:
        req_data = json.loads(raw_body)
    except json.JSONDecodeError:
        req_data = {}

    # Extract metadata
    call_count += 1
    schema_name = (
        req_data.get("response_format", {})
        .get("json_schema", {})
        .get("name", "unknown")
    )
    model = req_data.get("model", "unknown")
    messages = req_data.get("messages", [])
    response_format_type = req_data.get("response_format", {}).get("type", "none")

    # Find last user message for context
    user_prompt_excerpt = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            user_prompt_excerpt = content[:200].replace("\n", " ")
            break

    schema_counts[schema_name] += 1

    if not quiet:
        print(f"\n[PROXY] {'─' * 20} Call #{call_count} {'─' * 20}", flush=True)
        print(f"[PROXY] Time:    {datetime.now().strftime('%H:%M:%S.%f')[:-3]}", flush=True)
        print(f"[PROXY] Schema:  {schema_name}", flush=True)
        print(f"[PROXY] Model:   {model} | Format: {response_format_type}", flush=True)
        print(f"[PROXY] Messages: {len(messages)}", flush=True)
        print(f"[PROXY] Prompt:  {user_prompt_excerpt!r}", flush=True)

        if verbose:
            print(f"[PROXY] Full request:", flush=True)
            print(json.dumps(req_data, indent=2), flush=True)

        print(f"[PROXY] → Forwarding to upstream...", flush=True)

    # Forward to upstream
    start = time.monotonic()
    status_code = 0
    resp_body = b""

    try:
        headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in ("host", "content-length")
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                upstream + "/v1/chat/completions",
                data=raw_body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                resp_body = await resp.read()
                status_code = resp.status

        elapsed = time.monotonic() - start
        total_elapsed += elapsed

        if not quiet:
            # Try to parse response for nice display
            try:
                resp_data = json.loads(resp_body)
                content_str = ""
                choices = resp_data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    content_str = content[:500] if not verbose else content
                usage = resp_data.get("usage", {})
                tokens_out = usage.get("completion_tokens", "?")
                tokens_in = usage.get("prompt_tokens", "?")

                print(
                    f"[PROXY] ← {elapsed:.2f}s | status={status_code} | "
                    f"in={tokens_in} out={tokens_out} tokens",
                    flush=True,
                )
                print(f"[PROXY] Content: {content_str}", flush=True)
            except json.JSONDecodeError:
                print(f"[PROXY] ← {elapsed:.2f}s | status={status_code} | raw: {resp_body[:200]}", flush=True)

        return web.Response(body=resp_body, status=status_code, content_type="application/json")

    except Exception as e:
        elapsed = time.monotonic() - start
        error_count += 1
        print(f"[PROXY] ERROR after {elapsed:.2f}s: {type(e).__name__}: {e}", flush=True, file=sys.stderr)
        return web.Response(
            body=json.dumps({"error": str(e)}).encode(),
            status=502,
            content_type="application/json",
        )


def print_summary():
    """Print call summary on shutdown."""
    print("\n", flush=True)
    print("[PROXY] " + "=" * 50, flush=True)
    print("[PROXY] SUMMARY", flush=True)
    print("[PROXY] " + "=" * 50, flush=True)
    print(f"[PROXY] Total calls: {call_count}", flush=True)
    print(f"[PROXY] Total errors: {error_count}", flush=True)
    if call_count > 0:
        print(f"[PROXY] Avg latency: {total_elapsed / call_count:.2f}s", flush=True)
    print(f"[PROXY] Calls by schema:", flush=True)
    for schema, count in sorted(schema_counts.items(), key=lambda x: -x[1]):
        print(f"[PROXY]   {schema:30s}: {count}", flush=True)
    print("[PROXY] " + "=" * 50, flush=True)


async def main():
    parser = argparse.ArgumentParser(description="HTTP logging proxy for Graphiti sandbox validation")
    parser.add_argument("--port", type=int, default=8297, help="Port to listen on (default: 8297)")
    parser.add_argument("--upstream", default="http://localhost:8204", help="Upstream URL (default: http://localhost:8204)")
    parser.add_argument("--verbose", action="store_true", help="Show full request/response bodies")
    parser.add_argument("--quiet", action="store_true", help="Only show errors and summary")
    args = parser.parse_args()

    print(f"[PROXY] Starting logging proxy on port {args.port}", flush=True)
    print(f"[PROXY] Forwarding to: {args.upstream}", flush=True)
    print(f"[PROXY] Verbose: {args.verbose} | Quiet: {args.quiet}", flush=True)
    print(f"[PROXY] Set GRAPHITI_LLM_BASE_URL=http://localhost:{args.port}/v1 in your test", flush=True)
    print(f"[PROXY] Press Ctrl+C to stop and see call summary", flush=True)
    print("[PROXY] " + "─" * 50, flush=True)

    upstream = args.upstream
    verbose = args.verbose
    quiet = args.quiet

    async def handler(request: web.Request) -> web.Response:
        return await proxy_handler(request, upstream, verbose, quiet)

    app = web.Application()
    app.router.add_route("*", "/{path_info:.*}", handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", args.port)
    await site.start()

    print(f"[PROXY] Listening on http://0.0.0.0:{args.port}", flush=True)

    try:
        # Run until Ctrl+C
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        print_summary()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
