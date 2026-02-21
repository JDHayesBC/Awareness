"""
Comprehensive tests for the RAG Engine API at http://localhost:8206.

Run with:
    pytest tests/test_api.py -v

Tests are organized by endpoint group. All test repos created are cleaned up
via the cleanup fixture (even on failure).
"""

import pytest
import httpx

BASE_URL = "http://localhost:8206"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def post_repo(client: httpx.Client, name: str, **overrides) -> httpx.Response:
    """Create a repo with sensible defaults."""
    payload = {
        "name": name,
        "description": f"Test repo: {name}",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "jina-embeddings-v3",
        "max_results": 5,
    }
    payload.update(overrides)
    return client.post("/api/repos", json=payload)


def delete_repo_if_exists(client: httpx.Client, name: str) -> None:
    """Delete a repo silently — used in cleanup."""
    client.delete(f"/api/repos/{name}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """Shared synchronous httpx client for the test module."""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(autouse=True)
def cleanup_test_repos(client):
    """Ensure test repos are deleted after every test regardless of outcome."""
    TEST_REPO_NAMES = [
        "pytest-crud-repo",
        "pytest-update-repo",
        "pytest-delete-repo",
        "pytest-duplicate-repo",
        "pytest-ingest-repo",
        "pytest-docs-repo",
        "pytest-search-repo",
        "pytest-doc-delete-repo",
    ]
    yield
    for name in TEST_REPO_NAMES:
        delete_repo_if_exists(client, name)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_200(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200

    def test_health_returns_ok_status(self, client):
        data = client.get("/api/health").json()
        assert data["status"] == "ok"

    def test_health_identifies_service(self, client):
        data = client.get("/api/health").json()
        assert data["service"] == "rag-engine"


# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------

class TestWebUI:
    def test_root_returns_200(self, client):
        r = client.get("/")
        assert r.status_code == 200

    def test_root_returns_html_content_type(self, client):
        r = client.get("/")
        assert "text/html" in r.headers.get("content-type", "")

    def test_root_body_contains_doctype(self, client):
        body = client.get("/").text
        assert "<!DOCTYPE html>" in body or "<!doctype html>" in body.lower()

    def test_root_body_has_rag_title(self, client):
        body = client.get("/").text
        # The template title is "RAG Engine"
        assert "RAG" in body


# ---------------------------------------------------------------------------
# Repo CRUD — Create
# ---------------------------------------------------------------------------

class TestRepoCreate:
    def test_create_repo_returns_201(self, client):
        r = post_repo(client, "pytest-crud-repo")
        assert r.status_code == 201

    def test_create_repo_response_has_name(self, client):
        data = post_repo(client, "pytest-crud-repo").json()
        assert data["name"] == "pytest-crud-repo"

    def test_create_repo_response_has_description(self, client):
        data = post_repo(client, "pytest-crud-repo").json()
        assert data["description"] == "Test repo: pytest-crud-repo"

    def test_create_repo_defaults_applied(self, client):
        r = post_repo(client, "pytest-crud-repo")
        data = r.json()
        assert data["chunk_size"] == 500
        assert data["chunk_overlap"] == 50
        assert data["max_results"] == 5
        assert data["embedding_model"] == "jina-embeddings-v3"

    def test_create_repo_document_count_starts_at_zero(self, client):
        data = post_repo(client, "pytest-crud-repo").json()
        assert data["document_count"] == 0

    def test_create_repo_has_created_at(self, client):
        data = post_repo(client, "pytest-crud-repo").json()
        assert "created_at" in data
        assert data["created_at"]  # non-empty

    def test_create_repo_duplicate_returns_409(self, client):
        post_repo(client, "pytest-duplicate-repo")
        r = post_repo(client, "pytest-duplicate-repo")
        assert r.status_code == 409

    def test_create_repo_duplicate_error_message(self, client):
        post_repo(client, "pytest-duplicate-repo")
        data = post_repo(client, "pytest-duplicate-repo").json()
        assert "already exists" in data["detail"].lower()


# ---------------------------------------------------------------------------
# Repo CRUD — List
# ---------------------------------------------------------------------------

class TestRepoList:
    def test_list_repos_returns_200(self, client):
        r = client.get("/api/repos")
        assert r.status_code == 200

    def test_list_repos_returns_list(self, client):
        data = client.get("/api/repos").json()
        assert isinstance(data, list)

    def test_list_repos_includes_created_repo(self, client):
        post_repo(client, "pytest-crud-repo")
        names = [r["name"] for r in client.get("/api/repos").json()]
        assert "pytest-crud-repo" in names

    def test_list_repos_each_item_has_required_fields(self, client):
        post_repo(client, "pytest-crud-repo")
        repos = client.get("/api/repos").json()
        pytest_repo = next((r for r in repos if r["name"] == "pytest-crud-repo"), None)
        assert pytest_repo is not None
        for field in ("name", "description", "chunk_size", "chunk_overlap",
                      "embedding_model", "max_results", "document_count", "created_at"):
            assert field in pytest_repo, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Repo CRUD — Get
# ---------------------------------------------------------------------------

class TestRepoGet:
    def test_get_repo_returns_200(self, client):
        post_repo(client, "pytest-crud-repo")
        r = client.get("/api/repos/pytest-crud-repo")
        assert r.status_code == 200

    def test_get_repo_returns_correct_data(self, client):
        post_repo(client, "pytest-crud-repo")
        data = client.get("/api/repos/pytest-crud-repo").json()
        assert data["name"] == "pytest-crud-repo"
        assert data["chunk_size"] == 500

    def test_get_repo_nonexistent_returns_404(self, client):
        r = client.get("/api/repos/pytest-definitely-does-not-exist-xyz")
        assert r.status_code == 404

    def test_get_repo_nonexistent_error_detail(self, client):
        data = client.get("/api/repos/pytest-definitely-does-not-exist-xyz").json()
        assert "not found" in data["detail"].lower()


# ---------------------------------------------------------------------------
# Repo CRUD — Update
# ---------------------------------------------------------------------------

class TestRepoUpdate:
    def test_update_repo_returns_200(self, client):
        post_repo(client, "pytest-update-repo")
        r = client.put("/api/repos/pytest-update-repo", json={"max_results": 20})
        assert r.status_code == 200

    def test_update_repo_changes_field(self, client):
        post_repo(client, "pytest-update-repo")
        data = client.put(
            "/api/repos/pytest-update-repo",
            json={"max_results": 20, "description": "updated"},
        ).json()
        assert data["max_results"] == 20
        assert data["description"] == "updated"

    def test_update_repo_preserves_unchanged_fields(self, client):
        post_repo(client, "pytest-update-repo")
        data = client.put(
            "/api/repos/pytest-update-repo",
            json={"max_results": 20},
        ).json()
        # chunk_size should still be 500 from creation
        assert data["chunk_size"] == 500

    def test_update_repo_partial_update(self, client):
        """Only description is changed; everything else remains."""
        post_repo(client, "pytest-update-repo")
        data = client.put(
            "/api/repos/pytest-update-repo",
            json={"description": "new description only"},
        ).json()
        assert data["description"] == "new description only"
        assert data["max_results"] == 5  # original value

    def test_update_nonexistent_repo_returns_404(self, client):
        r = client.put(
            "/api/repos/pytest-definitely-does-not-exist-xyz",
            json={"max_results": 5},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Repo CRUD — Delete
# ---------------------------------------------------------------------------

class TestRepoDelete:
    def test_delete_repo_returns_200(self, client):
        post_repo(client, "pytest-delete-repo")
        r = client.delete("/api/repos/pytest-delete-repo")
        assert r.status_code == 200

    def test_delete_repo_response_contains_name(self, client):
        post_repo(client, "pytest-delete-repo")
        data = client.delete("/api/repos/pytest-delete-repo").json()
        assert data["deleted"] == "pytest-delete-repo"

    def test_delete_repo_removes_from_list(self, client):
        post_repo(client, "pytest-delete-repo")
        client.delete("/api/repos/pytest-delete-repo")
        names = [r["name"] for r in client.get("/api/repos").json()]
        assert "pytest-delete-repo" not in names

    def test_delete_repo_makes_get_return_404(self, client):
        post_repo(client, "pytest-delete-repo")
        client.delete("/api/repos/pytest-delete-repo")
        r = client.get("/api/repos/pytest-delete-repo")
        assert r.status_code == 404

    def test_delete_nonexistent_repo_returns_404(self, client):
        r = client.delete("/api/repos/pytest-definitely-does-not-exist-xyz")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Ingest — error cases (no JINA_API_KEY required)
# ---------------------------------------------------------------------------

class TestIngest:
    def test_ingest_on_nonexistent_repo_returns_404(self, client):
        r = client.post(
            "/api/repos/pytest-definitely-does-not-exist-xyz/ingest",
            json={"text": "hello world"},
        )
        assert r.status_code == 404

    def test_ingest_with_no_input_returns_400(self, client):
        post_repo(client, "pytest-ingest-repo")
        r = client.post("/api/repos/pytest-ingest-repo/ingest", json={"metadata": {}})
        assert r.status_code == 400

    def test_ingest_no_input_error_message(self, client):
        post_repo(client, "pytest-ingest-repo")
        data = client.post(
            "/api/repos/pytest-ingest-repo/ingest", json={"metadata": {}}
        ).json()
        assert "text" in data["detail"].lower() or "file" in data["detail"].lower()

    def test_ingest_with_text_no_jina_key_returns_503(self, client):
        post_repo(client, "pytest-ingest-repo")
        r = client.post(
            "/api/repos/pytest-ingest-repo/ingest",
            json={"text": "some content to embed", "metadata": {}},
        )
        assert r.status_code == 503

    def test_ingest_503_error_mentions_jina_key(self, client):
        post_repo(client, "pytest-ingest-repo")
        data = client.post(
            "/api/repos/pytest-ingest-repo/ingest",
            json={"text": "some content to embed"},
        ).json()
        assert "JINA_API_KEY" in data["detail"]

    def test_ingest_with_nonexistent_file_path_returns_400(self, client):
        post_repo(client, "pytest-ingest-repo")
        r = client.post(
            "/api/repos/pytest-ingest-repo/ingest",
            json={"file_path": "/nonexistent/totally-fake-file.txt"},
        )
        assert r.status_code == 400

    def test_ingest_with_nonexistent_file_error_message(self, client):
        post_repo(client, "pytest-ingest-repo")
        data = client.post(
            "/api/repos/pytest-ingest-repo/ingest",
            json={"file_path": "/nonexistent/totally-fake-file.txt"},
        ).json()
        assert "not found" in data["detail"].lower()


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class TestDocuments:
    def test_list_documents_empty_on_new_repo(self, client):
        post_repo(client, "pytest-docs-repo")
        data = client.get("/api/repos/pytest-docs-repo/documents").json()
        assert data == []

    def test_list_documents_returns_200(self, client):
        post_repo(client, "pytest-docs-repo")
        r = client.get("/api/repos/pytest-docs-repo/documents")
        assert r.status_code == 200

    def test_list_documents_on_nonexistent_repo_returns_404(self, client):
        r = client.get("/api/repos/pytest-definitely-does-not-exist-xyz/documents")
        assert r.status_code == 404

    def test_delete_nonexistent_document_returns_404(self, client):
        post_repo(client, "pytest-doc-delete-repo")
        r = client.delete(
            "/api/repos/pytest-doc-delete-repo/documents/00000000-fake-uuid-0000"
        )
        assert r.status_code == 404

    def test_delete_document_from_nonexistent_repo_returns_404(self, client):
        r = client.delete(
            "/api/repos/pytest-definitely-does-not-exist-xyz/documents/some-doc-id"
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Search — error cases (no JINA_API_KEY required)
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_on_nonexistent_repo_returns_404(self, client):
        r = client.post(
            "/api/repos/pytest-definitely-does-not-exist-xyz/search",
            json={"query": "hello"},
        )
        assert r.status_code == 404

    def test_search_without_jina_key_returns_503(self, client):
        post_repo(client, "pytest-search-repo")
        r = client.post(
            "/api/repos/pytest-search-repo/search",
            json={"query": "find something"},
        )
        assert r.status_code == 503

    def test_search_503_error_mentions_jina_key(self, client):
        post_repo(client, "pytest-search-repo")
        data = client.post(
            "/api/repos/pytest-search-repo/search",
            json={"query": "find something"},
        ).json()
        assert "JINA_API_KEY" in data["detail"]


# ---------------------------------------------------------------------------
# Rerank — error cases (no JINA_API_KEY required)
# ---------------------------------------------------------------------------

class TestRerank:
    def test_rerank_without_jina_key_returns_503(self, client):
        r = client.post(
            "/api/rerank",
            json={
                "query": "what is machine learning",
                "documents": [
                    "Machine learning is a subset of AI.",
                    "The sky is blue.",
                    "Neural networks process data.",
                ],
            },
        )
        assert r.status_code == 503

    def test_rerank_503_error_mentions_jina_key(self, client):
        data = client.post(
            "/api/rerank",
            json={
                "query": "machine learning",
                "documents": ["doc one", "doc two"],
            },
        ).json()
        assert "JINA_API_KEY" in data["detail"]

    def test_rerank_with_top_n_param_still_503_without_key(self, client):
        r = client.post(
            "/api/rerank",
            json={
                "query": "test query",
                "documents": ["a", "b", "c"],
                "top_n": 2,
            },
        )
        assert r.status_code == 503

    def test_rerank_with_custom_model_param_still_503_without_key(self, client):
        r = client.post(
            "/api/rerank",
            json={
                "query": "test query",
                "documents": ["a", "b"],
                "model": "jina-reranker-v1-base-en",
            },
        )
        assert r.status_code == 503
