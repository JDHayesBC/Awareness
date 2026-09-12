"""
Tests for Issue #315: stale ChromaDB collection handle self-healing.

Covers:
- chroma_utils.call_with_collection_retry(): retries exactly once on a
  missing-collection error, propagates any other exception, and propagates
  a second consecutive failure.
- chroma_utils.is_missing_collection_error(): recognizes chromadb's typed
  exceptions and the "does not exist" message shape.
- CoreAnchorsChromaLayer: search()/sync_word_photos()/health()/delete()/
  list_anchors() all recover transparently from a stale cached collection
  handle via a fake Chroma client whose collection raises "does not exist"
  on its first call and succeeds after the layer re-resolves it.
- CoreAnchorsChromaLayer.resync() invalidates the cached handle so the next
  operation binds to the freshly-created collection (bug #2 in the issue:
  resync "worked" per anchor_list but anchor_search kept failing on the old
  UUID until a full process restart).
- CoreAnchorsChromaLayer.startup_self_check() auto-resyncs when the
  collection is unreachable or reports 0 docs while disk has word-photos.
- TechRAGLayer: same stale-handle retry behavior for search()/health().
"""

from __future__ import annotations

from pathlib import Path

import pytest
import chromadb.errors as chroma_errors

from pps.layers.chroma_utils import (
    call_with_collection_retry,
    is_missing_collection_error,
)
from pps.layers.core_anchors_chroma import CoreAnchorsChromaLayer
from pps.layers.tech_rag import TechRAGLayer


# --- Fakes -------------------------------------------------------------

class FakeCollection:
    """A minimal stand-in for a chromadb Collection object.

    `fail_first_n_calls` simulates a stale handle: the first N calls to any
    data-touching method raise chromadb's NotFoundError (the same exception
    class the real HTTP client raises when a collection UUID is gone), then
    subsequent calls behave normally.
    """

    def __init__(self, name: str, fail_first_n_calls: int = 0):
        self.name = name
        self._fail_first_n_calls = fail_first_n_calls
        self._docs: dict[str, dict] = {}

    def _maybe_fail(self):
        if self._fail_first_n_calls > 0:
            self._fail_first_n_calls -= 1
            raise chroma_errors.NotFoundError(f"Collection {self.name} does not exist.")

    def count(self):
        self._maybe_fail()
        return len(self._docs)

    def get(self, ids=None, where=None, include=None):
        self._maybe_fail()
        if ids:
            found = {i: self._docs[i] for i in ids if i in self._docs}
        elif where:
            doc_id_filter = where.get("doc_id")
            found = {
                k: v for k, v in self._docs.items()
                if v.get("metadata", {}).get("doc_id") == doc_id_filter
            }
        else:
            found = dict(self._docs)
        return {
            "ids": list(found.keys()),
            "metadatas": [v.get("metadata") for v in found.values()],
            "documents": [v.get("document") for v in found.values()],
        }

    def add(self, ids, documents, metadatas):
        self._maybe_fail()
        for i, d, m in zip(ids, documents, metadatas):
            self._docs[i] = {"document": d, "metadata": m}

    def update(self, ids, documents, metadatas):
        self._maybe_fail()
        self.add(ids, documents, metadatas)

    def delete(self, ids=None, where=None):
        self._maybe_fail()
        if ids:
            for i in ids:
                self._docs.pop(i, None)
        elif where:
            doc_id_filter = where.get("doc_id")
            to_del = [
                k for k, v in self._docs.items()
                if v.get("metadata", {}).get("doc_id") == doc_id_filter
            ]
            for k in to_del:
                del self._docs[k]

    def query(self, query_texts, n_results, include=None, where=None):
        self._maybe_fail()
        ids = list(self._docs.keys())[:n_results]
        return {
            "ids": [ids],
            "documents": [[self._docs[i]["document"] for i in ids]],
            "metadatas": [[self._docs[i]["metadata"] for i in ids]],
            "distances": [[0.1] * len(ids)],
        }


class FakeClient:
    """Minimal stand-in for chromadb.HttpClient.

    Mimics resolve-by-name semantics: get_or_create_collection() returns the
    SAME object for a name that already exists, and a brand-new object after
    delete_collection() + get_or_create_collection() (simulating the new
    server-side UUID a real resync produces).
    """

    def __init__(self):
        self.collections: dict[str, FakeCollection] = {}
        self.get_or_create_calls = 0

    def get_or_create_collection(self, name, metadata=None):
        self.get_or_create_calls += 1
        if name not in self.collections:
            self.collections[name] = FakeCollection(name)
        return self.collections[name]

    def delete_collection(self, name):
        self.collections.pop(name, None)

    def heartbeat(self):
        return 1


# --- chroma_utils --------------------------------------------------------

def test_is_missing_collection_error_recognizes_not_found_error():
    exc = chroma_errors.NotFoundError("Collection abc-123 does not exist.")
    assert is_missing_collection_error(exc)


def test_is_missing_collection_error_recognizes_message_shape():
    exc = RuntimeError("Collection [abc-123] does not exist")
    assert is_missing_collection_error(exc)


def test_is_missing_collection_error_rejects_unrelated_exception():
    exc = ConnectionError("could not connect to chromadb")
    assert not is_missing_collection_error(exc)


def test_call_with_collection_retry_recovers_once():
    collection = FakeCollection("word_photos", fail_first_n_calls=1)
    calls = {"get_collection": 0}

    def get_collection(force_refresh: bool = False):
        calls["get_collection"] += 1
        return collection

    result = call_with_collection_retry(get_collection, lambda c: c.count())

    assert result == 0
    assert calls["get_collection"] == 2  # initial resolve + one refresh


def test_call_with_collection_retry_propagates_second_failure():
    collection = FakeCollection("word_photos", fail_first_n_calls=2)

    with pytest.raises(chroma_errors.NotFoundError):
        call_with_collection_retry(lambda force_refresh=False: collection, lambda c: c.count())


def test_call_with_collection_retry_propagates_unrelated_exception():
    def op(c):
        raise ConnectionError("network is unreachable")

    with pytest.raises(ConnectionError):
        call_with_collection_retry(lambda force_refresh=False: FakeCollection("x"), op)


def test_call_with_collection_retry_invokes_on_stale_callback():
    collection = FakeCollection("word_photos", fail_first_n_calls=1)
    seen = []

    call_with_collection_retry(
        lambda force_refresh=False: collection,
        lambda c: c.count(),
        on_stale=lambda exc: seen.append(exc),
    )

    assert len(seen) == 1
    assert isinstance(seen[0], chroma_errors.NotFoundError)


# --- CoreAnchorsChromaLayer ------------------------------------------------

@pytest.fixture
def word_photos_dir(tmp_path):
    d = tmp_path / "word_photos"
    d.mkdir()
    (d / "2026-01-01_first.md").write_text("---\nlocation: terminal\n---\n\nFirst photo.")
    (d / "2026-01-02_second.md").write_text("---\nlocation: terminal\n---\n\nSecond photo.")
    return d


@pytest.fixture
def anchors_layer(word_photos_dir):
    layer = CoreAnchorsChromaLayer(word_photos_path=word_photos_dir)
    layer._client = FakeClient()
    return layer


@pytest.mark.asyncio
async def test_sync_word_photos_survives_stale_handle(anchors_layer):
    # Prime the cache with a handle that fails its first call.
    stale = FakeCollection(anchors_layer.collection_name, fail_first_n_calls=1)
    anchors_layer._collection = stale
    anchors_layer._client.collections[anchors_layer.collection_name] = stale

    stats = await anchors_layer.sync_word_photos()

    assert stats["added"] == 2
    assert stats["errors"] == 0


@pytest.mark.asyncio
async def test_search_survives_stale_handle(anchors_layer):
    # Populate via a healthy handle first.
    await anchors_layer.sync_word_photos()

    # Now poison the cached handle to fail exactly once, simulating a
    # reboot that left this process holding a dead collection UUID.
    live_collection = anchors_layer._collection
    live_collection._fail_first_n_calls = 1

    results = await anchors_layer.search("photo", limit=5)

    assert len(results) == 2


@pytest.mark.asyncio
async def test_health_survives_stale_handle(anchors_layer):
    await anchors_layer.sync_word_photos()
    anchors_layer._collection._fail_first_n_calls = 1

    health = await anchors_layer.health()

    assert health.available
    assert health.details["chroma_doc_count"] == 2


@pytest.mark.asyncio
async def test_delete_survives_stale_handle(anchors_layer):
    await anchors_layer.sync_word_photos()
    anchors_layer._collection._fail_first_n_calls = 1

    result = await anchors_layer.delete("2026-01-01_first.md")

    assert result["chroma_deleted"]


@pytest.mark.asyncio
async def test_list_anchors_survives_stale_handle(anchors_layer):
    await anchors_layer.sync_word_photos()
    anchors_layer._collection._fail_first_n_calls = 1

    result = await anchors_layer.list_anchors()

    assert result["summary"]["in_sync"]


@pytest.mark.asyncio
async def test_resync_invalidates_cached_handle(anchors_layer):
    """
    Bug #2 from Issue #315: resync() deletes + recreates the collection
    (new UUID server-side) but must not leave the layer holding the OLD
    cached handle -- otherwise anchor_search keeps failing after a resync
    even though anchor_list reports the rebuild succeeded.
    """
    await anchors_layer.sync_word_photos()
    old_collection = anchors_layer._collection
    assert old_collection is not None

    result = await anchors_layer.resync()

    assert result["success"]
    # The cached handle must be a NEW object bound post-wipe, not the one
    # that existed before delete_collection() ran.
    assert anchors_layer._collection is not old_collection
    # And it must actually work for a subsequent, unrelated call.
    search_results = await anchors_layer.search("photo", limit=5)
    assert len(search_results) == 2


@pytest.mark.asyncio
async def test_startup_self_check_healthy_is_a_noop(anchors_layer):
    await anchors_layer.sync_word_photos()

    result = await anchors_layer.startup_self_check()

    assert result["self_healed"] is False
    assert result["chroma_doc_count"] == 2


@pytest.mark.asyncio
async def test_startup_self_check_resyncs_when_collection_empty_but_disk_has_files(anchors_layer):
    # Collection exists (e.g. freshly recreated after a reboot) but is
    # empty, while disk still has the two word-photos from the fixture.
    empty = FakeCollection(anchors_layer.collection_name)
    anchors_layer._collection = empty
    anchors_layer._client.collections[anchors_layer.collection_name] = empty

    result = await anchors_layer.startup_self_check()

    assert result["self_healed"] is True
    assert result["disk_file_count"] == 2
    assert result["resync_result"]["success"]
    # After self-heal, the collection actually has the docs.
    assert anchors_layer._collection.count() == 2


@pytest.mark.asyncio
async def test_startup_self_check_resyncs_when_collection_unreachable(anchors_layer):
    class ExplodingCollection(FakeCollection):
        def count(self):
            raise chroma_errors.NotFoundError(f"Collection {self.name} does not exist.")

    dead = ExplodingCollection(anchors_layer.collection_name)
    anchors_layer._collection = dead
    # get_or_create_collection(force_refresh=True) inside resync() will
    # replace this with a fresh, working collection.
    anchors_layer._client.collections[anchors_layer.collection_name] = dead

    result = await anchors_layer.startup_self_check()

    assert result["self_healed"] is True
    assert "unreachable" in result["reason"]
    assert result["resync_result"]["success"]


# --- TechRAGLayer ----------------------------------------------------------

@pytest.fixture
def tech_docs_dir(tmp_path):
    d = tmp_path / "tech_docs"
    d.mkdir()
    return d


@pytest.fixture
def tech_layer(tech_docs_dir):
    layer = TechRAGLayer(tech_docs_path=tech_docs_dir)
    layer._client = FakeClient()
    return layer


@pytest.mark.asyncio
async def test_tech_rag_ingest_and_search_survive_stale_handle(tmp_path, tech_layer):
    doc = tmp_path / "arch.md"
    doc.write_text("## Overview\n\nSome architecture notes about the pipeline.")

    result = await tech_layer.ingest(str(doc), category="architecture")
    assert result["success"]

    # Poison the cached handle for exactly one call.
    tech_layer._collection._fail_first_n_calls = 1

    results = await tech_layer.search("architecture notes")

    assert len(results) >= 1


@pytest.mark.asyncio
async def test_tech_rag_health_survives_stale_handle(tmp_path, tech_layer):
    doc = tmp_path / "arch.md"
    doc.write_text("## Overview\n\nSome architecture notes.")
    await tech_layer.ingest(str(doc), category="architecture")

    tech_layer._collection._fail_first_n_calls = 1

    health = await tech_layer.health()

    assert health.available
    assert health.details["chunks"] >= 1


@pytest.mark.asyncio
async def test_tech_rag_startup_self_check_flags_empty_collection(tmp_path, tech_layer):
    doc = tech_layer.tech_docs_path / "arch.md"
    doc.write_text("## Overview\n\nSome architecture notes.")

    # Collection is reachable but empty (nothing has been ingested into it),
    # while a copy of the doc already sits on disk.
    result = await tech_layer.startup_self_check()

    assert result["self_healed"] is False
    assert result["needs_attention"] is True
    assert result["disk_file_count"] == 1
