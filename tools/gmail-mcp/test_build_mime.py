"""Offline tests for the MIME/header helpers in gmail-mcp/server.py (and its jeff twin)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
SERVERS = [TOOLS / "gmail-mcp" / "server.py", TOOLS / "jeff-gmail-mcp" / "server.py"]


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"srv_{path.parent.name.replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(params=SERVERS, ids=lambda p: p.parent.name)
def srv(request):
    return _load(request.param)


def test_canonical_header_case(srv):
    text = srv.build_mime("a@b.com", "Hi", "body").as_string()
    assert "\nTo: a@b.com" in "\n" + text
    assert "\nSubject: Hi" in "\n" + text
    assert "\nto:" not in text and "\nsubject:" not in text


def test_threading_headers_present_when_given(srv):
    m = srv.build_mime("a@b.com", "Re: Hi", "x", in_reply_to="<1@x>", references="<0@x> <1@x>")
    assert m["In-Reply-To"] == "<1@x>"
    assert m["References"] == "<0@x> <1@x>"


def test_threading_headers_absent_when_not_given(srv):
    m = srv.build_mime("a@b.com", "Hi", "x")
    assert m["In-Reply-To"] is None
    assert m["References"] is None


def test_normalize_headers_mixed_case(srv):
    h = srv.normalize_headers([
        {"name": "subject", "value": "sent by us"},
        {"name": "To", "value": "j@x.com"},
        {"name": "FROM", "value": "l@x.com"},
    ])
    assert h.get("subject") == "sent by us"
    assert h.get("to") == "j@x.com"
    assert h.get("from") == "l@x.com"
    assert srv.normalize_headers([]) == {}
