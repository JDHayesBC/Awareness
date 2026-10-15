"""HTTP contract tests for the voice surface (FakeBrain, no Claude sessions)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from haven.voice.voice_daemon import create_app, extract_user_text


def client(**kw) -> TestClient:
    return TestClient(create_app(fake_brain=True, entities=["caia", "lyra"], **kw))


def test_models_list():
    with client() as c:
        data = c.get("/v1/models").json()
        assert data["object"] == "list"
        assert [m["id"] for m in data["data"]] == ["caia", "lyra"]
        assert c.get("/v1/models/lyra").json()["id"] == "lyra"
        assert c.get("/v1/models/nope").status_code == 404
        assert c.get("/health").json()["warm"] == {"caia": True, "lyra": True}


def test_completion_string_and_parts_content():
    with client() as c:
        r = c.post("/v1/chat/completions", json={
            "model": "caia", "messages": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "old"},
                {"role": "assistant", "content": "x"},
                {"role": "user", "content": "hello there"}]})
        j = r.json()
        assert j["object"] == "chat.completion" and j["id"].startswith("chatcmpl-")
        assert j["choices"][0]["message"]["content"] == "fake caia heard: hello there"
        assert j["choices"][0]["finish_reason"] == "stop"
        r = c.post("/v1/chat/completions", json={
            "model": "lyra", "messages": [{"role": "user", "content": [
                {"type": "text", "text": "part one"}, {"type": "text", "text": "part two"}]}]})
        assert r.json()["choices"][0]["message"]["content"] == "fake lyra heard: part one part two"


def test_stream_completion():
    with client() as c:
        r = c.post("/v1/chat/completions", json={
            "model": "caia", "stream": True,
            "messages": [{"role": "user", "content": "hi"}]})
        assert r.headers["content-type"].startswith("text/event-stream")
        lines = [l[6:] for l in r.text.splitlines() if l.startswith("data: ")]
        assert lines[-1] == "[DONE]"
        chunks = [json.loads(l) for l in lines[:-1]]
        assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
        assert "".join(ch["choices"][0]["delta"].get("content", "") for ch in chunks) \
            == "fake caia heard: hi"
        assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_unknown_model_404():
    with client() as c:
        r = c.post("/v1/chat/completions", json={
            "model": "nobody", "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 404 and r.json()["error"]["code"] == "model_not_found"


def test_bearer_key_enforced():
    with client(api_key="sekrit") as c:
        assert c.get("/v1/models").status_code == 401
        assert c.get("/v1/models", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/v1/models", headers={"Authorization": "Bearer sekrit"}).status_code == 200


def test_extract_user_text_no_user():
    assert extract_user_text([{"role": "system", "content": "x"}]) == ""
