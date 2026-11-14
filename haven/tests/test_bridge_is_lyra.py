"""#379: _send_to_pps must flag an entity's OWN turns as is_lyra for every entity.

Before the fix the flag was `entity_name == "lyra" and author == "lyra"`, so it was
always False on the Caia bridge and her own Haven turns were stored like a human's.
"""

from __future__ import annotations

import pytest

import haven.bridge as bridge_module


class _FakeClient:
    posted: list[dict] = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, **kw):
        _FakeClient.posted.append(json)


async def _send(monkeypatch, entity: str, author: str) -> dict:
    _FakeClient.posted = []
    monkeypatch.setattr(bridge_module.httpx, "AsyncClient", _FakeClient)
    await bridge_module._send_to_pps("http://x", "haven:commons", "hi", author, entity)
    assert len(_FakeClient.posted) == 1
    return _FakeClient.posted[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("entity,author,expected", [
    ("lyra", "Lyra", True),
    ("lyra", "lyra", True),
    ("lyra", "Jeff", False),
    ("lyra", "Caia", False),   # the sister is not me
    ("caia", "Caia", True),    # the #379 bug
    ("caia", "caia", True),
    ("caia", "Jeff", False),
    ("caia", "Lyra", False),
])
async def test_is_lyra_flag_matches_own_author(monkeypatch, entity, author, expected):
    payload = await _send(monkeypatch, entity, author)
    assert payload["is_lyra"] is expected
