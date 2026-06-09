"""
Regression tests for #138 — re-ingesting a document must REPLACE its chunks,
not accumulate stale/duplicate ones.

These run fully self-contained against the real FastAPI app (real chunking, real
ChromaDB, real SQLite) on a temp data dir. The ONLY thing stubbed is the external
Jina embeddings HTTP call (RAGEngine.embed_texts) — the network dependency, not the
transform under test. This deliberately exercises the real ingest path rather than a
synthetic stub that would dodge the dedup logic.

Run with:
    .venv/bin/python3 -m pytest rag-service/tests/test_reingest_idempotent.py -v
"""

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Make `app` importable as the rag-service does (app.main, app.storage, ...)
RAG_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(RAG_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(RAG_SERVICE_ROOT))

REPO = "pytest-reingest-repo"
SOURCE = "/docs/architecture.md"

V1_TEXT = (
    "# Architecture\n\n"
    "## Storage Layer\n\n"
    "The system uses Postgres as its primary datastore. "
    "Postgres holds all canonical records and is the source of truth.\n\n"
    "## Cache Layer\n\n"
    "Redis caches hot reads in front of Postgres.\n"
)

# v2: the storage layer was migrated to SQLite. "Postgres" must NOT survive.
V2_TEXT = (
    "# Architecture\n\n"
    "## Storage Layer\n\n"
    "The system uses SQLite as its primary datastore. "
    "SQLite holds all canonical records and is the source of truth.\n\n"
    "## Cache Layer\n\n"
    "Redis caches hot reads in front of SQLite.\n"
)


def _fake_embed(texts, model):
    """Deterministic, content-sensitive fake embedding (no network / no Jina key).

    Encodes a couple of marker-token counts into the vector so search ordering is
    meaningful: chunks mentioning 'sqlite' vs 'postgres' land in different regions.
    """
    out = []
    for t in texts:
        low = t.lower()
        out.append([
            float(low.count("postgres")),
            float(low.count("sqlite")),
            float(low.count("redis")),
            float(len(t)) / 1000.0,
        ])
    return out


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Point the app at an isolated temp data dir BEFORE importing it (DATA_DIR is
    # read at module import time in app.main).
    monkeypatch.setenv("RAG_DATA_DIR", str(tmp_path / "rag_data"))

    # Fresh import so DATA_DIR picks up the env override.
    for mod in ("app.main", "app.rag_engine", "app.storage"):
        sys.modules.pop(mod, None)
    main = importlib.import_module("app.main")

    # Stub the external embeddings call (the only network dependency).
    async def fake_embed_texts(self, texts, model):
        return _fake_embed(texts, model)

    monkeypatch.setattr(main.RAGEngine, "embed_texts", fake_embed_texts, raising=True)

    with TestClient(main.app) as c:
        # lifespan runs here -> storage + rag_engine initialised on temp dir
        c.post("/api/repos", json={
            "name": REPO,
            "description": "reingest regression",
            "chunk_size": 200,
            "chunk_overlap": 20,
            "embedding_model": "fake",
            "max_results": 10,
        })
        yield c, main


def _chunk_ids_for_repo(main) -> list[str]:
    """All ChromaDB chunk ids currently stored in the repo collection."""
    collection = main.rag_engine.client.get_collection(name=REPO)
    got = collection.get()
    return got["ids"]


def _ingest(client, text):
    return client.post(
        f"/api/repos/{REPO}/ingest",
        json={"text": text, "metadata": {"source_file": SOURCE}},
    )


def test_reingest_replaces_not_duplicates(client):
    c, main = client

    # First ingest
    r1 = _ingest(c, V1_TEXT)
    assert r1.status_code == 200, r1.text
    docs_after_v1 = c.get(f"/api/repos/{REPO}/documents").json()
    chunks_after_v1 = _chunk_ids_for_repo(main)
    assert len(docs_after_v1) == 1, "first ingest should create exactly one document"
    assert len(chunks_after_v1) >= 1

    # Re-ingest the SAME source with CHANGED content
    r2 = _ingest(c, V2_TEXT)
    assert r2.status_code == 200, r2.text

    # (a) No duplicate documents — still exactly one for this source.
    docs_after_v2 = c.get(f"/api/repos/{REPO}/documents").json()
    sources = [d["source"] for d in docs_after_v2]
    assert sources.count(SOURCE) == 1, f"source duplicated in SQLite: {sources}"
    assert len(docs_after_v2) == 1, f"expected 1 doc, got {len(docs_after_v2)}: {docs_after_v2}"

    # (b) No stale ChromaDB chunks: none of the v1 chunk ids survive, and the
    # total chunk count equals just the new version's chunks.
    chunks_after_v2 = _chunk_ids_for_repo(main)
    leaked = set(chunks_after_v1) & set(chunks_after_v2)
    assert not leaked, f"stale v1 chunk ids leaked after re-ingest: {leaked}"

    new_doc_id = docs_after_v2[0]["id"]
    expected = {cid for cid in chunks_after_v2 if cid.startswith(new_doc_id)}
    assert set(chunks_after_v2) == expected, (
        "ChromaDB holds chunks not belonging to the current doc version "
        f"(stale): {set(chunks_after_v2) - expected}"
    )

    # (c) Stored full_text is the new content, not the stale one.
    full = main.rag_engine.client.get_collection(name=REPO).get(include=["documents"])
    blob = "\n".join(full["documents"]).lower()
    assert "sqlite" in blob, "new content missing from index"
    assert "postgres" not in blob, "stale v1 content ('postgres') still present after re-ingest"


def test_search_returns_new_content_not_stale(client):
    c, main = client

    _ingest(c, V1_TEXT)
    _ingest(c, V2_TEXT)

    res = c.post(f"/api/repos/{REPO}/search", json={"query": "storage datastore", "limit": 10})
    assert res.status_code == 200, res.text
    results = res.json()["results"]
    assert results, "search returned nothing"

    joined = "\n".join(r["chunk_text"] for r in results).lower()
    assert "sqlite" in joined, "search did not surface the new (sqlite) content"
    assert "postgres" not in joined, "search surfaced stale (postgres) content after re-ingest"


def test_unchanged_reingest_still_single_copy(client):
    """Re-ingesting identical content twice also yields a single copy."""
    c, main = client

    _ingest(c, V1_TEXT)
    _ingest(c, V1_TEXT)

    docs = c.get(f"/api/repos/{REPO}/documents").json()
    assert len(docs) == 1, f"identical re-ingest duplicated the document: {docs}"

    doc_id = docs[0]["id"]
    chunk_ids = _chunk_ids_for_repo(main)
    assert chunk_ids, "no chunks stored"
    assert all(cid.startswith(doc_id) for cid in chunk_ids), (
        f"chunks not owned by the single current doc: {chunk_ids}"
    )
