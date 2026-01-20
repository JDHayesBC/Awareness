# Awareness Test Suite

This directory contains tests for the Awareness Pattern Persistence System.

## Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_pps/test_chroma_fixture.py

# Run with verbose output
pytest -v

# Run tests matching a pattern
pytest -k "chroma"
```

## Test Fixtures

Test fixtures are defined in `conftest.py` and are automatically available to all tests.

### Database Fixtures

- **`test_db_path`**: Creates a temporary SQLite database path
- **`test_db_with_messages`**: Creates a test database with sample message data
- **`mock_claude_home`**: Creates a temporary CLAUDE_HOME directory structure

### ChromaDB Fixtures

- **`chroma_client`**: In-memory ChromaDB client for fast, isolated tests
  - No server required
  - Clean state for each test
  - Use for custom ChromaDB setup

- **`tech_rag_test_instance`**: Fully configured TechRAGLayer with in-memory ChromaDB
  - Recommended for most TechRAG tests
  - Includes temporary docs directory
  - Automatically uses `chroma_client` fixture

### Example Usage

#### Using `chroma_client` directly:

```python
def test_custom_chroma(chroma_client):
    collection = chroma_client.get_or_create_collection("my_collection")
    collection.add(documents=["test"], ids=["1"])
    results = collection.query(query_texts=["test"], n_results=1)
    assert len(results["ids"][0]) == 1
```

#### Using `tech_rag_test_instance`:

```python
@pytest.mark.asyncio
async def test_tech_rag(tech_rag_test_instance):
    layer = tech_rag_test_instance
    result = await layer.ingest("path/to/doc.md", category="test")
    assert result["success"]
```

## Test Organization

```
tests/
├── conftest.py              # Shared fixtures
├── README.md                # This file
└── test_pps/                # PPS layer tests
    ├── test_chroma_fixture.py      # ChromaDB fixture examples
    ├── test_entity_resolution.py   # Graphiti entity resolution
    ├── test_health.py              # PPS health checks
    ├── test_message_summaries.py   # Crystallization layer
    ├── test_tech_rag_reingest.py   # Tech RAG re-ingestion
    └── ...
```

## Writing New Tests

1. **Unit tests**: Fast, isolated, no external dependencies
   - Use in-memory fixtures (`chroma_client`, `test_db_path`)
   - Mark with appropriate markers: `@pytest.mark.asyncio` for async tests

2. **Integration tests**: Test multiple components together
   - May require running services (ChromaDB server, FalkorDB, etc.)
   - Mark with `@pytest.mark.integration`

3. **Slow tests**: Tests that take >1 second
   - Mark with `@pytest.mark.slow`
   - Can be skipped with `pytest -m "not slow"`

## Pytest Configuration

See `pytest.ini` in the project root for:
- Asyncio configuration
- Test discovery patterns
- Output options
- Marker definitions

## Continuous Integration

Tests run automatically on:
- Pull requests
- Commits to main branch
- Manual workflow dispatch

See `.github/workflows/test.yml` for CI configuration (if exists).
