"""Voice surface adapter: Home Assistant Voice PE -> OpenAI-style API -> EntityBrain.

GH#363 lineage: sibling of haven/discord/discord_daemon.py. The adapter owns ONLY
the surface (an OpenAI-compatible chat-completions server that HA's ``llama_cpp``
integration points at) and hands ``EntityBrain.respond()`` a (speaker, text)
pair. One model id per entity: ``model="caia"`` -> Caia's brain, ``"lyra"`` ->
Lyra's. ``None`` back ([[NO_RESPONSE]]) is spoken as the empty string.

Both sides of every turn are written to the entity's own river via
``brain.capture_to_river`` under channel ``voice`` (VOICE_CAPTURE=0 disables).

Run:  python3 -m haven.voice.voice_daemon [--fake-brain]

Env:
    VOICE_HOST / VOICE_PORT   bind address (default 0.0.0.0 / 8222)
    VOICE_ENTITIES            comma-separated entities served (default "caia,lyra")
    VOICE_SPEAKER             speaker name handed to the brain (default "Jeff")
    VOICE_API_KEY             if set, require ``Authorization: Bearer <key>``
    VOICE_CAPTURE             "0" silences river write-back (default on)
    VOICE_FAKE_BRAIN          "1" = echo brain, no Claude sessions (testing)
    CLAUDE_MODEL / CLAUDE_EFFORT  read by EntityBrain
Per-entity path, token file and PPS port are derived from the entity name
(entities/<name>/, PPS 8201 lyra / 8211 caia) since one process serves several.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PPS_PORTS = {"lyra": 8201, "caia": 8211}


def log(msg: str) -> None:
    print(f"[voice] {msg}", file=sys.stderr, flush=True)


class FakeBrain:
    """Echo brain so the HTTP contract is testable without Claude sessions."""

    def __init__(self, entity_name: str) -> None:
        self.entity_name = entity_name

    async def warmup(self) -> None:
        return None

    async def respond(self, speaker: str, text: str, *, is_dm: bool = False,
                      addressed: bool = False) -> Optional[str]:
        return f"fake {self.entity_name} heard: {text}"


def build_brain(entity_name: str):
    """Real EntityBrain for one entity, with explicit per-entity wiring."""
    from haven.brain import EntityBrain
    from haven.brain.surface_profile import voice_profile

    entity_path = PROJECT_ROOT / "entities" / entity_name
    return EntityBrain(
        entity_name=entity_name,
        entity_path=entity_path,
        entity_token=(entity_path / ".entity_token").read_text().strip(),
        pps_http_url=f"http://localhost:{PPS_PORTS.get(entity_name, 8201)}",
        channel="voice",
        profile=voice_profile(entity_name),
    )


def extract_user_text(messages: list[dict[str, Any]]) -> str:
    """Text of the LAST user message; content may be a string or text parts."""
    for msg in reversed(messages or []):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [p.get("text", "") for p in content
                     if isinstance(p, dict) and p.get("type") == "text"]
            return " ".join(p for p in parts if p).strip()
        return ""
    return ""


def _detect_addressed_entity(text: str, names: list[str]) -> str | None:
    """Return the entity name if the utterance opens with that name, else None.

    Handles common voice patterns:
      "Lyra, what do you know about..."
      "Caia can you help me..."
      "Hey Lyra, ..."

    The name must appear within the first few words (up to 4 tokens), optionally
    preceded by "hey" / "ok" / "okay", and followed by punctuation or space.
    Returns the first matching entity name (case-insensitive) or None.
    """
    # normalise: strip leading filler words the STT often prepends
    _FILLER = re.compile(r"^(hey|ok|okay|hi|so|well)\s+", re.IGNORECASE)
    stripped = _FILLER.sub("", text.strip())
    first_chunk = stripped.split()[:4]  # first 4 tokens at most
    first_text = " ".join(first_chunk).lower()
    for name in names:
        # name appears at the start, followed by punctuation or space or end
        if re.match(rf'^{re.escape(name.lower())}\b', first_text):
            return name
    return None


def _error(status: int, message: str, etype: str, code: str | None = None) -> JSONResponse:
    return JSONResponse(
        {"error": {"message": message, "type": etype, "param": None, "code": code}},
        status_code=status,
    )


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def create_app(*, fake_brain: bool = False, entities: list[str] | None = None,
               speaker: str | None = None, api_key: str | None = None,
               capture: bool | None = None, router: bool | None = None,
               router_default: str | None = None) -> FastAPI:
    names = entities or [e.strip().lower() for e in
                         os.getenv("VOICE_ENTITIES", "caia,lyra").split(",") if e.strip()]
    speaker = speaker or os.getenv("VOICE_SPEAKER", "Jeff")
    api_key = api_key if api_key is not None else (os.getenv("VOICE_API_KEY") or None)
    capture = capture if capture is not None else os.getenv("VOICE_CAPTURE", "1") != "0"
    # "router" model: HA points at model="router", daemon detects who's being addressed
    # and routes to the right entity. Falls back to router_default when undecidable.
    # Disable with VOICE_ROUTER=0 (or router=False in tests).
    router_enabled = router if router is not None else os.getenv("VOICE_ROUTER", "1") != "0"
    router_default_name = (router_default or os.getenv("VOICE_DEFAULT_ENTITY") or
                           (names[0] if names else "lyra"))
    created = int(time.time())
    brains: dict[str, Any] = {}
    locks: dict[str, asyncio.Lock] = {}
    warm: dict[str, bool] = {}

    async def _warm(name: str) -> None:
        try:
            brain = FakeBrain(name) if fake_brain else build_brain(name)
            log(f"warming up '{name}'...")
            await brain.warmup()
            brains[name], locks[name], warm[name] = brain, asyncio.Lock(), True
            log(f"'{name}' warmed up")
        except Exception as e:  # one entity failing must not take down the other
            warm[name] = False
            log(f"warmup failed for '{name}': {e}")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await asyncio.gather(*(_warm(n) for n in names))
        yield

    app = FastAPI(title="Haven voice surface", lifespan=lifespan)

    def _check_auth(request: Request) -> JSONResponse | None:
        if api_key and request.headers.get("authorization", "") != f"Bearer {api_key}":
            return _error(401, "Invalid API key.", "invalid_request_error", "invalid_api_key")
        return None

    def _model_obj(name: str) -> dict[str, Any]:
        return {"id": name, "object": "model", "created": created, "owned_by": "haven"}

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "entities": names, "warm": dict(warm)}

    def _all_model_ids() -> list[str]:
        return names + (["router"] if router_enabled else [])

    @app.get("/v1/models")
    async def list_models(request: Request):
        if (denied := _check_auth(request)):
            return denied
        return {"object": "list", "data": [_model_obj(n) for n in _all_model_ids()]}

    @app.get("/v1/models/{model_id}")
    async def get_model(model_id: str, request: Request):
        if (denied := _check_auth(request)):
            return denied
        if model_id not in _all_model_ids():
            return _error(404, f"The model '{model_id}' does not exist.",
                          "invalid_request_error", "model_not_found")
        return _model_obj(model_id)

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        if (denied := _check_auth(request)):
            return denied
        try:
            body = await request.json()
        except Exception:
            return _error(400, "Request body must be JSON.", "invalid_request_error")
        model = body.get("model")
        if model not in _all_model_ids():
            return _error(404, f"The model '{model}' does not exist.",
                          "invalid_request_error", "model_not_found")
        text = extract_user_text(body.get("messages") or [])

        # Router model: detect which entity is addressed and delegate to them.
        if router_enabled and model == "router":
            addressed = _detect_addressed_entity(text, names)
            routed_to = addressed or router_default_name
            log(
                f"router: {text[:50]!r} -> addressed={addressed or 'none'}, "
                f"routed to '{routed_to}'"
            )
            if routed_to not in names:
                return _error(503, f"Default entity '{routed_to}' not configured.",
                              "server_error")
            model = routed_to

        brain = brains.get(model)
        if brain is None:
            return _error(503, f"Entity '{model}' is not warmed up.", "server_error")

        reply = ""
        if text:
            try:
                async with locks[model]:
                    if capture:
                        await _capture(brain, speaker, text, is_lyra=False)
                    raw = await brain.respond(speaker, text, is_dm=True, addressed=True)
                reply = (raw or "").strip()
                if reply and capture:
                    await _capture(brain, model.capitalize(), reply, is_lyra=True)
            except Exception as e:
                log(f"brain.respond failed for '{model}': {e}")
                return _error(500, "The entity could not respond.", "server_error")
        log(f"{model}: heard {len(text)} chars, replied {len(reply)} chars")

        cid, now = f"chatcmpl-{uuid.uuid4().hex}", int(time.time())
        if body.get("stream"):
            def chunk(delta: dict[str, Any], finish: str | None) -> str:
                return _sse({"id": cid, "object": "chat.completion.chunk", "created": now,
                             "model": model,
                             "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})

            async def gen():
                yield chunk({"role": "assistant", "content": ""}, None)
                yield chunk({"content": reply}, None)
                yield chunk({}, "stop")
                yield "data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")
        return {
            "id": cid, "object": "chat.completion", "created": now, "model": model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": reply}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    return app


async def _capture(brain: Any, author: str, content: str, *, is_lyra: bool) -> None:
    fn = getattr(brain, "capture_to_river", None)
    if fn is None:
        return
    try:
        await fn(author, content, is_lyra=is_lyra, channel="voice")
    except Exception as e:  # capture must never break a spoken reply
        log(f"river capture error (non-fatal): {e}")


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fake-brain", action="store_true",
                    default=os.getenv("VOICE_FAKE_BRAIN") == "1")
    args = ap.parse_args()
    app = create_app(fake_brain=args.fake_brain)
    uvicorn.run(app, host=os.getenv("VOICE_HOST", "0.0.0.0"),
                port=int(os.getenv("VOICE_PORT", "8222")), log_level="info")


if __name__ == "__main__":
    main()
