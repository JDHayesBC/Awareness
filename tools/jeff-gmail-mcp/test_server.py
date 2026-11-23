"""Tests for bulk-trash receipt and sender counts, against a fake Gmail service.

No network, no real token. Run: pytest tools/jeff-gmail-mcp/test_server.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import server  # noqa: E402


class _Call:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class _Batch:
    def __init__(self, callback):
        self._callback = callback
        self._items: list[tuple[str, dict]] = []

    def add(self, call):
        self._items.append(call)

    def execute(self):
        for i, call in enumerate(self._items):
            self._callback(str(i), call.execute(), None)


class FakeService:
    """Mimics the slice of the Gmail client the server uses."""

    def __init__(self, messages: dict[str, list[dict]], fail_ids=()):
        self.messages_by_id = messages
        self.fail_ids = set(fail_ids)
        self.trashed: list[str] = []
        self.formats: list[str] = []

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, userId, q="", maxResults=100, pageToken=None):
        ids = [{'id': i} for i in list(self.messages_by_id)[:maxResults]]
        return _Call(lambda: {'messages': ids, 'resultSizeEstimate': len(self.messages_by_id)})

    def trash(self, userId, id):
        def run():
            if id in self.fail_ids:
                raise RuntimeError("rateLimitExceeded")
            self.trashed.append(id)
            return {}
        return _Call(run)

    def get(self, userId, id, format, metadataHeaders=None):
        self.formats.append(format)
        return _Call(lambda: {'payload': {'headers': self.messages_by_id[id]}})

    def new_batch_http_request(self, callback):
        return _Batch(callback)


def _run(coro):
    return asyncio.run(coro)[0].text


def test_bulk_trash_receipt_reports_failure():
    svc = FakeService({'a': [], 'b': [], 'c': []}, fail_ids={'b'})
    text = _run(server._bulk_trash(svc, {"query": "category:promotions", "max_messages": 10}))
    assert "Query: category:promotions" in text
    assert "Trashed: 2" in text
    assert "Failed: 1" in text
    assert "b: rateLimitExceeded" in text
    assert svc.trashed == ['a', 'c']


def test_bulk_trash_requires_query():
    assert "query required" in _run(server._bulk_trash(FakeService({}), {}))


def test_sender_counts_metadata_only():
    def hdr(frm, unsub=False):
        h = [{'name': 'From', 'value': frm}]
        if unsub:
            h.append({'name': 'List-Unsubscribe', 'value': '<mailto:x@y>'})
        return h

    svc = FakeService({
        '1': hdr('Shop <news@shop.com>', True),
        '2': hdr('news@shop.com', True),
        '3': hdr('Other <hi@shop.com>'),
        '4': hdr('Bob <bob@example.org>'),
    })
    text = _run(server._sender_counts(svc, {"query": "", "max_scan": 100}))
    assert "Scanned 4 of ~4" in text
    assert "With List-Unsubscribe header: 2" in text
    assert "2  news@shop.com" in text
    assert "3  shop.com" in text
    assert set(svc.formats) == {'metadata'}


def test_sender_counts_respects_cap():
    svc = FakeService({str(i): [{'name': 'From', 'value': f'a{i}@x.com'}] for i in range(10)})
    text = _run(server._sender_counts(svc, {"max_scan": 3}))
    assert "Scanned 3 of" in text


def test_no_send_tool_exposed():
    names = [t.name for t in _run_list()]
    assert "gmail_send_message" not in names
    assert "gmail_sender_counts" in names


def _run_list():
    from mcp.types import ListToolsRequest
    handler = server.server.request_handlers[ListToolsRequest]
    result = asyncio.run(handler(ListToolsRequest(method="tools/list")))
    return result.root.tools


def test_cli_mode_runs_a_tool_and_prints_its_text(monkeypatch, capsys):
    """--call uses the same dispatcher as the MCP server; a missing token is a plain line."""
    monkeypatch.setattr(server, "get_gmail_service", lambda: (None, "no token"))
    assert server.run_cli("gmail_count_messages", '{"query": "is:unread"}') == 0
    assert "Gmail error: no token" in capsys.readouterr().out
