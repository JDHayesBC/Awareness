# Graphiti Local LLM Setup Guide

This guide documents how to use local LLMs (LM Studio, Ollama) for Graphiti entity extraction, reducing costs from ~$7/hour to essentially free.

## The Problem

Full OpenAI-based Graphiti ingestion costs ~$7/hour for entity extraction. For 11,000+ historical messages (~43 hours), that's $300+ in API costs.

## The Solution: Hybrid Mode

Use local LLM for entity extraction (the expensive part) while keeping OpenAI for embeddings (cheap and compatible with existing graph data).

### Why Hybrid?

1. **LLM extraction** is expensive - needs powerful model, many tokens per message
2. **Embeddings** are cheap (~$0.02/1M tokens) and must match existing graph dimensions
3. OpenAI embeddings are 1536 dimensions; local (nomic) are 768 - can't mix them

## Setup

### 1. Hardware Requirements

- Local machine with GPU or high-RAM CPU
- Tested on: Ryzen 395+ with 128GB RAM (NUC)
- Models need ~20-40GB VRAM/RAM depending on quantization

### 2. LM Studio Configuration

1. Install LM Studio
2. Download models:
   - **LLM**: `qwen/qwen3-32b` or `deepseek-r1-distill-qwen-32b`
   - **Embeddings**: `text-embedding-nomic-embed-text-v1.5` (only if using full local mode)
3. Enable multi-model loading (Settings → Allow multiple models)
4. Set reasonable context size (8K-32K sufficient for message extraction)
5. Start server on accessible port (default: 1234)

### 3. Environment Variables

In `pps/docker/.env`:

```bash
# Hybrid mode (recommended): Local LLM + OpenAI embeddings
GRAPHITI_LLM_BASE_URL=http://192.168.0.120:1234/v1
GRAPHITI_LLM_MODEL=qwen/qwen3-32b
GRAPHITI_EMBEDDING_PROVIDER=openai  # Keep OpenAI for compatibility
GRAPHITI_EMBEDDING_MODEL=text-embedding-3-small
```

For full local mode (requires fresh graph):
```bash
GRAPHITI_EMBEDDING_PROVIDER=local
GRAPHITI_EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
GRAPHITI_EMBEDDING_DIM=768
```

### 4. Qwen3 Thinking Mode

Qwen3 models default to "thinking mode" which outputs `<think>` reasoning tags before responses. This breaks JSON parsing for entity extraction.

**Solution**: Add `/no_think` to the system prompt.

This is already configured in `pps/layers/extraction_context.py`:
```python
BASE_EXTRACTION_CONTEXT = """
/no_think

## Primary Entities in This Dataset
...
```

### 5. Verify Setup

Test the connection:
```bash
# Test LLM
curl http://192.168.0.120:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen/qwen3-32b", "messages": [{"role": "user", "content": "Say hello"}]}'

# Test embeddings (if using local)
curl http://192.168.0.120:1234/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model": "text-embedding-nomic-embed-text-v1.5", "input": "test"}'
```

## How It Works

### Three Modes

1. **Default** (no env vars): OpenAI for everything
2. **Hybrid** (GRAPHITI_LLM_BASE_URL + EMBEDDING_PROVIDER=openai): Local LLM + OpenAI embeddings
3. **Full Local** (EMBEDDING_PROVIDER=local): Everything local (requires fresh graph)

### Code Path

`rich_texture_v2.py` → `_get_graphiti_client()`:
- Checks `GRAPHITI_LLM_BASE_URL`
- Creates `OpenAIGenericClient` for local LLM
- Creates `OpenAIEmbedder` with either local or OpenAI config
- Passes to Graphiti constructor

### Extraction Flow

1. Message comes in via `store()`
2. `build_extraction_instructions()` adds `/no_think` + context
3. Graphiti calls local LLM for entity extraction
4. Embeddings generated via OpenAI (cheap)
5. Results stored in Neo4j

## Cost Comparison

| Mode | LLM Cost | Embedding Cost | 11K Messages |
|------|----------|----------------|--------------|
| Full OpenAI | ~$7/hour | ~$0.02/1M tokens | ~$350 |
| Hybrid | $0 (local) | ~$0.02/1M tokens | ~$2 |
| Full Local | $0 | $0 | $0 (electricity only) |

## Troubleshooting

### "Vector dimensions don't match"
You're mixing OpenAI embeddings (1536) with local (768). Either:
- Use hybrid mode (OpenAI embeddings)
- Nuke graph and rebuild with local embeddings

### Qwen outputs `<think>` tags
Add `/no_think` to system prompt. Already configured in extraction_context.py.

### Model not loaded
LM Studio only loads one model by default. Enable multi-model in settings.

### Slow extraction
- Increase batch size in paced_ingestion.py
- Check GPU utilization
- Consider smaller model (8B vs 32B)

## Files Modified

- `pps/layers/rich_texture_v2.py` - Added local LLM client support
- `pps/layers/extraction_context.py` - Added `/no_think` directive
- `pps/docker/.env` - Configuration variables

## References

- [Graphiti LLM Configuration](docs/reference/graphiti-llm-configuration.md)
- [Graphiti Best Practices](docs/reference/graphiti%20best%20practices.md)
- LM Studio: https://lmstudio.ai/
