# Graphiti LLM Configuration Guide

Graphiti is a framework for building temporally-aware knowledge graphs. It defaults to OpenAI but supports multiple LLM providers.

## Key Concepts

- **`model`** — Main model for complex tasks (entity/relationship extraction)
- **`small_model`** — Lighter model for simpler tasks (summarization, reranking)
- Graphiti works best with models supporting **structured output** (OpenAI and Gemini recommended)
- For non-OpenAI providers, you typically still need OpenAI for embeddings and reranking

---

## Installation

```bash
# Base installation (OpenAI)
pip install graphiti-core

# With specific providers
pip install "graphiti-core[anthropic]"
pip install "graphiti-core[google-genai]"
pip install "graphiti-core[groq]"
```

---

## Configuration Examples

### OpenAI (Default)

```python
from graphiti_core import Graphiti
from graphiti_core.llm_client import OpenAIClient, LLMConfig
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

graphiti = Graphiti(
    "bolt://localhost:7687",
    "neo4j",
    "password",
    llm_client=OpenAIClient(
        config=LLMConfig(
            model="gpt-4.1-mini",
            small_model="gpt-4.1-nano"
        )
    ),
    embedder=OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            embedding_model="text-embedding-3-small"
        )
    ),
    cross_encoder=OpenAIRerankerClient(
        config=LLMConfig(
            model="gpt-4.1-nano"
        )
    )
)
```

**Environment Variables:**
- `OPENAI_API_KEY`

---

### Anthropic (Claude)

> **Note:** Anthropic requires OpenAI for embeddings and reranking. Set both `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`.

```python
from graphiti_core import Graphiti
from graphiti_core.llm_client.anthropic_client import AnthropicClient, LLMConfig
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

graphiti = Graphiti(
    "bolt://localhost:7687",
    "neo4j",
    "password",
    llm_client=AnthropicClient(
        config=LLMConfig(
            api_key="<your-anthropic-api-key>",
            model="claude-sonnet-4-20250514",
            small_model="claude-3-5-haiku-20241022"
        )
    ),
    embedder=OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key="<your-openai-api-key>",
            embedding_model="text-embedding-3-small"
        )
    ),
    cross_encoder=OpenAIRerankerClient(
        config=LLMConfig(
            api_key="<your-openai-api-key>",
            model="gpt-4.1-nano"
        )
    )
)
```

**Environment Variables:**
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY` (for embeddings/reranking)

---

### Google Gemini

```python
from graphiti_core import Graphiti
from graphiti_core.llm_client.gemini_client import GeminiClient, LLMConfig
from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient

api_key = "<your-google-api-key>"

graphiti = Graphiti(
    "bolt://localhost:7687",
    "neo4j",
    "password",
    llm_client=GeminiClient(
        config=LLMConfig(
            api_key=api_key,
            model="gemini-2.0-flash"
        )
    ),
    embedder=GeminiEmbedder(
        config=GeminiEmbedderConfig(
            api_key=api_key,
            embedding_model="embedding-001"
        )
    ),
    cross_encoder=GeminiRerankerClient(
        config=LLMConfig(
            api_key=api_key,
            model="gemini-2.0-flash-exp"
        )
    )
)
```

**Environment Variables:**
- `GOOGLE_API_KEY`

---

### Groq

> **Note:** Use larger models (e.g., Llama 3.1 70B). Smaller models may not output correct JSON structures.

```python
from graphiti_core import Graphiti
from graphiti_core.llm_client.groq_client import GroqClient, LLMConfig
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

graphiti = Graphiti(
    "bolt://localhost:7687",
    "neo4j",
    "password",
    llm_client=GroqClient(
        config=LLMConfig(
            api_key="<your-groq-api-key>",
            model="llama-3.1-70b-versatile",
            small_model="llama-3.1-8b-instant"
        )
    ),
    embedder=OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key="<your-openai-api-key>",
            embedding_model="text-embedding-3-small"
        )
    ),
    cross_encoder=OpenAIRerankerClient(
        config=LLMConfig(
            api_key="<your-openai-api-key>",
            model="gpt-4.1-nano"
        )
    )
)
```

**Environment Variables:**
- `GROQ_API_KEY`
- `OPENAI_API_KEY` (for embeddings/reranking)

---

### Azure OpenAI

> **Important:** Azure deployments must opt into v1 API for structured outputs. See [Azure OpenAI API version lifecycle](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/api-version-lifecycle?tabs=key#api-evolution).

```python
from openai import AsyncAzureOpenAI
from graphiti_core import Graphiti
from graphiti_core.llm_client import LLMConfig, OpenAIClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

api_key = "<your-api-key>"
api_version = "<your-api-version>"
llm_endpoint = "<your-llm-endpoint>"
embedding_endpoint = "<your-embedding-endpoint>"

llm_client_azure = AsyncAzureOpenAI(
    api_key=api_key,
    api_version=api_version,
    azure_endpoint=llm_endpoint
)

embedding_client_azure = AsyncAzureOpenAI(
    api_key=api_key,
    api_version=api_version,
    azure_endpoint=embedding_endpoint
)

azure_llm_config = LLMConfig(
    small_model="gpt-4.1-nano",
    model="gpt-4.1-mini",
)

graphiti = Graphiti(
    "bolt://localhost:7687",
    "neo4j",
    "password",
    llm_client=OpenAIClient(
        config=azure_llm_config,
        client=llm_client_azure
    ),
    embedder=OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            embedding_model="text-embedding-3-small-deployment"
        ),
        client=embedding_client_azure
    ),
    cross_encoder=OpenAIRerankerClient(
        config=LLMConfig(model=azure_llm_config.small_model),
        client=llm_client_azure
    )
)
```

**Environment Variables:**
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT_NAME`
- `AZURE_OPENAI_API_VERSION`
- `AZURE_OPENAI_EMBEDDING_API_KEY`
- `AZURE_OPENAI_EMBEDDING_ENDPOINT`
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME`
- `AZURE_OPENAI_EMBEDDING_API_VERSION`
- `AZURE_OPENAI_USE_MANAGED_IDENTITY`

---

### Ollama (Local LLMs)

> **Note:** Use `OpenAIGenericClient` (not `OpenAIClient`) because Ollama doesn't support the `/v1/responses` endpoint.

```bash
# Pull models first
ollama pull deepseek-r1:7b
ollama pull nomic-embed-text
```

```python
from graphiti_core import Graphiti
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

llm_config = LLMConfig(
    api_key="ollama",  # Ollama doesn't require a real API key
    model="deepseek-r1:7b",
    small_model="deepseek-r1:7b",
    base_url="http://localhost:11434/v1",
)

llm_client = OpenAIGenericClient(config=llm_config)

graphiti = Graphiti(
    "bolt://localhost:7687",
    "neo4j",
    "password",
    llm_client=llm_client,
    embedder=OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key="ollama",
            embedding_model="nomic-embed-text",
            embedding_dim=768,
            base_url="http://localhost:11434/v1",
        )
    ),
    cross_encoder=OpenAIRerankerClient(client=llm_client, config=llm_config),
)
```

---

### Claude Haiku via OpenAI Wrapper (Cost-Optimized)

> **Note:** This approach uses Claude Haiku via an OpenAI-compatible wrapper to eliminate API costs while maintaining full compatibility.

For setup and details, see **[graphiti-haiku-wrapper-setup.md](graphiti-haiku-wrapper-setup.md)**.

**Cost**: $0 (included in Claude Code subscription)
**Quality**: Excellent for entity extraction
**Speed**: 2-4 seconds per request

**Prerequisites**:
- Claude Code CLI installed and authenticated
- `pps-haiku-wrapper` service running (Docker container)

**Configuration**:

```python
from graphiti_core import Graphiti
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

llm_config = LLMConfig(
    api_key="dummy",  # Wrapper doesn't need a real key
    model="haiku",
    small_model="haiku",
    base_url="http://pps-haiku-wrapper:8000",  # Or http://127.0.0.1:8204
)

graphiti = Graphiti(
    "bolt://localhost:7687",
    "neo4j",
    "password",
    llm_client=OpenAIGenericClient(config=llm_config),
    embedder=OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key="<your-openai-api-key>",
            embedding_model="text-embedding-3-small",
        )
    ),
    cross_encoder=OpenAIRerankerClient(
        config=LLMConfig(
            api_key="<your-openai-api-key>",
            model="gpt-4o-mini",
        )
    )
)
```

**Environment variables** (Docker):
```bash
GRAPHITI_LLM_BASE_URL=http://pps-haiku-wrapper:8000
GRAPHITI_LLM_MODEL=haiku
OPENAI_API_KEY=sk-...  # Still needed for embeddings
```

**Cost comparison**:
- OpenAI GPT-4o: ~$0.003 per message
- Claude Haiku (via CC subscription wrapper): $0 per message
- Haiku also extracts 3x more entities with no content sanitization

---

### OpenAI-Compatible Services (Generic)

For any provider with an OpenAI-compatible API (e.g., Mistral, Together AI, Ollama, etc.):

```python
from graphiti_core import Graphiti
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

llm_config = LLMConfig(
    api_key="<your-api-key>",
    model="<your-main-model>",
    small_model="<your-small-model>",
    base_url="<your-base-url>",
)

graphiti = Graphiti(
    "bolt://localhost:7687",
    "neo4j",
    "password",
    llm_client=OpenAIGenericClient(config=llm_config),
    embedder=OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key="<your-api-key>",
            embedding_model="<your-embedding-model>",
            base_url="<your-base-url>",
        )
    ),
    cross_encoder=OpenAIRerankerClient(
        config=LLMConfig(
            api_key="<your-api-key>",
            model="<your-small-model>",
            base_url="<your-base-url>",
        )
    )
)
```

---

## LLMConfig Parameters

```python
LLMConfig(
    api_key: str,           # API key (optional if using env vars)
    model: str,             # Main model name
    small_model: str,       # Smaller model for lightweight tasks
    base_url: str,          # Base URL for API endpoint (optional)
)
```

---

## Database Connection

Graphiti requires a graph database. The connection string format:

```python
Graphiti(
    "bolt://localhost:7687",  # Neo4j URI
    "neo4j",                  # Username
    "password",               # Password
    llm_client=...,
    embedder=...,
    cross_encoder=...
)
```

**Supported databases:**
- Neo4j
- FalkorDB
- AWS Neptune
- Kuzu DB

---

## Performance Tuning

Set `SEMAPHORE_LIMIT` environment variable to control concurrent operations (default: 10).

- Lower if you get 429 rate limit errors
- Increase if your provider allows higher throughput

---

## Reference

- [Graphiti Documentation](https://help.getzep.com/graphiti/configuration/llm-configuration)
- [Graphiti GitHub](https://github.com/getzep/graphiti)
