# Graphiti + Claude Haiku Wrapper Setup Guide

**Version**: 1.0
**Date**: 2026-01-28
**Status**: Production Ready
**Related Issues**: #118 (Graphiti LLM cost elimination)

---

## Overview

The Claude Haiku OpenAI Wrapper eliminates Graphiti's OpenAI API costs (~$30/month) by routing entity extraction through Claude Code CLI instead of OpenAI's API.

### Architecture

```
Graphiti (entity extraction)
    ↓
POST /v1/chat/completions (OpenAI format)
    ↓
pps-haiku-wrapper (translation layer)
    ↓
ClaudeInvoker (Claude Code connection)
    ↓
Claude Code CLI
    ↓
Claude Haiku (via Claude Code subscription - $0)
```

### Cost Impact

**Before**: Graphiti uses OpenAI GPT-4o for extraction
- ~$0.003 per message
- 7000+ messages to ingest = ~$22
- Ongoing: ~$3/month for live ingestion

**After**: Graphiti uses Claude Haiku via wrapper
- $0 (included in Claude Code subscription)
- Better extraction quality (34 entities/29 relationships vs 12/8 for gpt-4o-mini)
- No content sanitization (gpt-4o-mini strips intimate/emotional content)
- Same API compatibility

---

## Prerequisites

You need Claude Code CLI installed and authenticated on your host machine.

### Installation

**If you don't have Claude Code CLI installed:**

```bash
npm install -g @anthropic-ai/claude-code
```

**Verify installation:**

```bash
which claude
# Should output something like: /usr/local/bin/claude
```

### Authentication

**Step 1: Log in to Claude**

```bash
claude setup-token
```

This opens a browser for OAuth authentication. Follow the prompts to authorize.

**Step 2: Verify credentials**

```bash
ls -la ~/.claude/.credentials.json
# File should exist and contain OAuth tokens
```

If this file doesn't exist, the `setup-token` command didn't complete successfully. Try again.

**Step 3: Test the CLI**

```bash
claude --version
# Should show version like: @anthropic-ai/claude-code/1.2.3
```

If any of these steps fail, you cannot run the wrapper. The wrapper requires valid Claude authentication.

---

## Building and Running

### Quick Start

```bash
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness/pps/docker

# Build the wrapper image
docker compose build pps-haiku-wrapper

# Start the wrapper service
docker compose up -d pps-haiku-wrapper

# Check logs
docker compose logs -f pps-haiku-wrapper
```

**Expected startup output:**

```
pps-haiku-wrapper    | Initializing ClaudeInvoker (model=haiku)...
pps-haiku-wrapper    | This takes ~33s for initial connection...
pps-haiku-wrapper    | ✓ ClaudeInvoker initialized in 33.2s
pps-haiku-wrapper    | Context limits: 150000 tokens, 100 turns
pps-haiku-wrapper    | INFO:     Uvicorn running on http://0.0.0.0:8000
```

The health check will pass (~60s startup time) and the service will be ready.

### Health Check

```bash
curl http://127.0.0.1:8204/health
```

**Healthy response:**

```json
{
  "status": "healthy",
  "invoker_connected": true,
  "context_usage": {
    "tokens": 0,
    "turns": 0,
    "limit": 150000
  }
}
```

---

## Configuration

### Environment Variables

**In `.env` or `docker-compose.yml`:**

```bash
# Model to use (default: haiku)
WRAPPER_MODEL=haiku
```

**Supported models:**

- `haiku` (recommended) - Fast, cheap, sufficient for entity extraction
- `sonnet` - Faster, more capable, if you need better quality
- `opus` - Most capable, overkill for extraction, not recommended

### Port Binding

By default, the wrapper binds to `127.0.0.1:8204` (localhost only, not accessible from the network).

This is intentional for security. If you need network access, modify `docker-compose.yml`:

```yaml
ports:
  - "127.0.0.1:8204:8000"  # Current: localhost only
  - "8204:8000"             # If needed: accessible from network (be careful!)
```

### Docker Compose Service Definition

In `pps/docker/docker-compose.yml`:

```yaml
pps-haiku-wrapper:
  build:
    context: ../..
    dockerfile: pps/docker/Dockerfile.cc-wrapper
  container_name: pps-haiku-wrapper
  restart: unless-stopped
  ports:
    - "127.0.0.1:8204:8000"
  volumes:
    # Mount Claude CLI credentials (read-only)
    - ${HOME}/.claude/.credentials.json:/root/.claude/.credentials.json:ro
  environment:
    - WRAPPER_MODEL=${WRAPPER_MODEL:-haiku}
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 60s  # ClaudeInvoker init takes ~33s
```

---

## Connecting Graphiti to the Wrapper

### Current Status

Graphiti in the Docker stack still uses OpenAI by default. To use the wrapper:

**In `.env`:**

```bash
# Keep OpenAI key for embeddings (Graphiti still uses it)
OPENAI_API_KEY=sk-proj-...

# Tell Graphiti to use the wrapper for LLM
GRAPHITI_LLM_BASE_URL=http://pps-haiku-wrapper:8000
GRAPHITI_LLM_MODEL=haiku
```

**In `docker-compose.yml` (graphiti service):**

```yaml
graphiti:
  image: zepai/graphiti:latest
  # ... other config ...
  environment:
    - OPENAI_API_KEY=${OPENAI_API_KEY}  # For embeddings only
    - GRAPHITI_LLM_BASE_URL=${GRAPHITI_LLM_BASE_URL:-http://pps-haiku-wrapper:8000}
    - GRAPHITI_LLM_MODEL=${GRAPHITI_LLM_MODEL:-haiku}
```

### Note on Graphiti Integration Path

We use `graphiti_core` directly in Python (not the Graphiti Docker image). When `GRAPHITI_LLM_BASE_URL` is set, `rich_texture_v2.py` creates an `OpenAIGenericClient` which uses `/v1/chat/completions` - exactly what our wrapper implements. This has been validated end-to-end.

**Note**: The Graphiti Docker image (Issue #118) hardcodes `OpenAIClient` which uses the newer `/v1/responses` endpoint. That path does NOT work with our wrapper. Only the direct Python integration path works.

---

## Testing the Wrapper

### Test 1: Health Check

```bash
curl http://127.0.0.1:8204/health | jq .
```

Expected: `"status": "healthy"`

### Test 2: Simple Chat Completion

```bash
curl http://127.0.0.1:8204/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "haiku",
    "messages": [
      {"role": "user", "content": "Say hello"}
    ]
  }' | jq '.choices[0].message.content'
```

Expected: Response from Claude with "hello" or similar greeting.

### Test 3: JSON Response Format

```bash
curl http://127.0.0.1:8204/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "haiku",
    "messages": [
      {"role": "user", "content": "Return JSON with fields name and age. Use name=Alice, age=30"}
    ],
    "response_format": {
      "type": "json_object"
    }
  }' | jq '.choices[0].message.content | fromjson'
```

Expected: Parsed JSON object with name and age fields (markdown fences stripped automatically).

### Test 4: Entity Extraction (Graphiti-like)

```bash
curl http://127.0.0.1:8204/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "haiku",
    "messages": [
      {
        "role": "system",
        "content": "You are an entity extraction system. Extract entities from the text."
      },
      {
        "role": "user",
        "content": "Jeff and Lyra went to the coffee shop. Jeff ordered espresso. Lyra ordered a latte."
      }
    ],
    "response_format": {
      "type": "json_object"
    }
  }' | jq '.choices[0].message.content | fromjson'
```

Expected: JSON with extracted entities (people, places, actions).

---

## How It Works

### Request Translation

When Graphiti sends an OpenAI-format request:

```json
{
  "model": "gpt-4",
  "messages": [
    {"role": "system", "content": "Extract entities..."},
    {"role": "user", "content": "Text to extract from..."}
  ],
  "response_format": {"type": "json_object"}
}
```

The wrapper:

1. **Validates** the request is well-formed
2. **Combines messages** into a single prompt (Claude doesn't need strict role separation)
3. **Adds JSON instructions** if `response_format` is requested
4. **Injects the schema** if `json_schema` type is provided
5. **Queries Claude** via ClaudeInvoker
6. **Strips markdown fences** from JSON responses (Claude wraps JSON in ``` fences)
7. **Wraps the response** in OpenAI format with token estimates

### Response Format Handling

The wrapper automatically handles JSON output:

**Input:**

```json
{
  "response_format": {
    "type": "json_object"
  }
}
```

**Wrapper behavior:**
- Adds "Respond with raw JSON only" instruction to prompt
- Strips markdown code fences from response
- Returns raw JSON to caller

**Input with schema:**

```json
{
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "schema": {
        "type": "object",
        "properties": {
          "entities": {
            "type": "array",
            "items": {"type": "string"}
          }
        }
      }
    }
  }
}
```

**Wrapper behavior:**
- Includes the schema in the prompt so Claude uses exact field names
- Adds JSON instructions
- Strips markdown fences
- Returns validated JSON

### Context Management

The wrapper manages Claude's context window automatically:

- **Max tokens**: 150,000 (conservative limit for Haiku)
- **Max turns**: 100 conversation turns
- **Auto-restart**: When limits approach, restarts and clears history

For stateless extraction tasks (like Graphiti), this is transparent—each request is independent.

---

## Troubleshooting

### Problem: Container won't start

**Log output:**

```
docker: Error response from daemon: invalid mount path
```

**Cause**: Credentials file doesn't exist

**Solution**: Follow the [Authentication](#authentication) section above to create credentials.

### Problem: Health check fails with "ClaudeInvoker not initialized"

**Log output:**

```
pps-haiku-wrapper    | ERROR: ClaudeInvoker failed to initialize
pps-haiku-wrapper    | No such file: /root/.claude/.credentials.json
```

**Cause**: Volume mount failed or credentials file missing on host

**Solution**:
1. Verify credentials file exists: `ls ~/.claude/.credentials.json`
2. Restart the container: `docker compose restart pps-haiku-wrapper`

### Problem: "401 Unauthorized" or authentication errors

**Log output:**

```
OAuth token invalid or expired
```

**Cause**: OAuth token expired (tokens last 30-90 days)

**Solution**:
1. On your host machine, refresh the token:
   ```bash
   claude setup-token
   ```
2. Restart the container:
   ```bash
   docker compose restart pps-haiku-wrapper
   ```

### Problem: Timeout errors during startup

**Log output:**

```
pps-haiku-wrapper    | Initializing ClaudeInvoker...
pps-haiku-wrapper    | [timeout after 120s]
```

**Cause**: Claude Code CLI taking too long or network issues

**Solution**:
1. Check your internet connection
2. Check Claude Code CLI is working on host:
   ```bash
   claude --version
   ```
3. Increase timeout in docker-compose.yml:
   ```yaml
   healthcheck:
     start_period: 120s  # Increased from 60s
   ```

### Problem: "Bad gateway" or connection refused

**Error:**

```
curl: (7) Failed to connect to 127.0.0.1:8204
```

**Cause**: Wrapper service isn't running or hasn't started yet

**Solution**:
1. Check service status:
   ```bash
   docker compose ps pps-haiku-wrapper
   ```
2. Check logs:
   ```bash
   docker compose logs pps-haiku-wrapper
   ```
3. Wait for health check to pass (~60s)
4. Verify port binding:
   ```bash
   netstat -an | grep 8204
   ```

### Problem: JSON responses have markdown fences

**Error response:**

```json
{
  "content": "```json\n{\"entities\": [...]}\n```"
}
```

**Cause**: Request didn't include `response_format` parameter

**Solution**: Add response format to request:
```json
{
  "response_format": {"type": "json_object"}
}
```

---

## Performance Notes

### Startup Time

- **First initialization**: ~33 seconds (Claude Code CLI establishes connection)
- **Subsequent requests**: 2-4 seconds each
- **Health check**: Passes after initialization completes

### Token Limits

- **Max context**: 150,000 tokens
- **Max turns**: 100 conversation turns
- **Per-request tokens**: Graphiti queries are typically 500-2000 tokens

Entity extraction from a message usually takes 100-300 tokens, so you get thousands of requests per context window before auto-restart.

### Cost

- **Via CC subscription**: $0 per extraction (included in Claude Code subscription)
- **If using API directly**: Haiku is $0.80/M input, $4/M output (~90% cheaper than GPT-4o)

---

## Docker Image Details

### Build Command

```bash
docker build -f pps/docker/Dockerfile.cc-wrapper -t pps-cc-wrapper .
```

### Image Composition

- **Base**: `python:3.11-slim`
- **Node.js**: Installed for Claude CLI (added ~150MB to image)
- **Claude CLI**: Installed globally via npm
- **Python packages**: FastAPI, Uvicorn, Pydantic

### Build Size

- **Final image**: ~800MB (Python 3.11 + Node.js + dependencies)
- **Build time**: ~2 minutes on typical hardware

### Runtime Requirements

- **RAM**: 256MB baseline + ~100MB per 50,000 token context usage
- **CPU**: Single-threaded, not CPU-intensive
- **Network**: Requires internet for Claude Code CLI connection

---

## Security Considerations

### Credentials Handling

- Credentials file is mounted **read-only** (`:ro`)
- Container cannot modify or extract credentials
- File is gitignored (never committed)
- Only Jeff's machine and authorized hosts should have this file

### Network Access

- Wrapper binds to `127.0.0.1:8204` (localhost only)
- Not accessible from the network by default
- If you need network access, ensure it's behind a firewall/VPN

### API Keys

- The wrapper itself doesn't require API keys
- Graphiti still needs `OPENAI_API_KEY` for embeddings (if used)
- All OpenAI API calls are configured server-side, not exposed to clients

---

## Integration with Existing Stack

### Services That Use the Wrapper

**Graphiti** (optional):
- Modify environment variables to point to wrapper
- See [Connecting Graphiti to the Wrapper](#connecting-graphiti-to-the-wrapper)

**Direct HTTP clients** (if building custom extraction):
- Use the wrapper's `/v1/chat/completions` endpoint
- Same request/response format as OpenAI API

### Services Not Affected

- **PPS Server** (Layer 1-5): Uses ClaudeInvoker directly
- **Chrome DB**: Vector database (unchanged)
- **Neo4j**: Graph database (unchanged)
- **Web UI**: No changes needed

### Environment Variables Reference

**In `.env`:**

```bash
# Wrapper model selection
WRAPPER_MODEL=haiku

# Graphiti connection (if using wrapper)
GRAPHITI_LLM_BASE_URL=http://pps-haiku-wrapper:8000
GRAPHITI_LLM_MODEL=haiku

# Graphiti still needs OpenAI for embeddings
OPENAI_API_KEY=sk-proj-...
```

---

## API Reference

### Endpoints

#### GET /health

Health check endpoint for Docker healthcheck.

**Response (healthy):**
```json
{
  "status": "healthy",
  "invoker_connected": true,
  "context_usage": {
    "tokens": 1234,
    "turns": 5,
    "limit": 150000
  }
}
```

**Response (unhealthy):**
```json
{
  "status": "unhealthy",
  "message": "ClaudeInvoker not initialized"
}
```

#### POST /v1/chat/completions

OpenAI-compatible chat completions endpoint.

**Request:**
```json
{
  "model": "haiku",
  "messages": [
    {
      "role": "system",
      "content": "You are an assistant"
    },
    {
      "role": "user",
      "content": "Extract entities from this text"
    }
  ],
  "temperature": 0.7,
  "max_tokens": 1000,
  "response_format": {
    "type": "json_object"
  }
}
```

**Request parameters:**
- `model` (required): Model to use (passed to ClaudeInvoker)
- `messages` (required): Array of message objects
- `temperature` (optional): Sampling temperature (0-2)
- `max_tokens` (optional): Max output length
- `response_format` (optional): Output format (json_object or json_schema)

**Response:**
```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1704067200,
  "model": "haiku",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 156,
    "completion_tokens": 89,
    "total_tokens": 245
  }
}
```

**Error responses:**
```json
{
  "detail": "ClaudeInvoker not initialized"
}
```

---

## Advanced Configuration

### Custom Startup Prompts

The wrapper initializes ClaudeInvoker with **no startup prompt** (stateless mode). If you need to customize Claude's behavior, modify the environment or add system messages to requests.

### Model Selection

Change model via `WRAPPER_MODEL` environment variable:

```bash
# .env
WRAPPER_MODEL=sonnet  # Faster, more capable
WRAPPER_MODEL=haiku   # Cheaper, good for extraction
WRAPPER_MODEL=opus    # Most capable (overkill)
```

### Context Window Management

The wrapper automatically manages context:

**Limits** (configurable in source code):
```python
max_context_tokens=150_000  # Conservative for Haiku
max_turns=100
```

**Restart behavior**:
- When context usage approaches limit, restarts ClaudeInvoker
- Clears conversation history
- Next request starts with fresh context

For extraction tasks, this is transparent—each request is independent.

---

## Maintenance

### Regular Tasks

**Monthly**: Refresh OAuth token (ensures long-running containers work)
```bash
claude setup-token
docker compose restart pps-haiku-wrapper
```

**Quarterly**: Update Claude CLI and wrapper image
```bash
npm update -g @anthropic-ai/claude-code
docker compose build --no-cache pps-haiku-wrapper
docker compose up -d pps-haiku-wrapper
```

### Monitoring

**Check service status:**
```bash
docker compose ps pps-haiku-wrapper
```

**Monitor logs:**
```bash
docker compose logs -f pps-haiku-wrapper
```

**Check context usage:**
```bash
curl http://127.0.0.1:8204/health | jq '.context_usage'
```

### Debugging

**Enable verbose logging:**

Modify `cc_openai_wrapper.py` to adjust log level:
```python
uvicorn.run(
    app,
    host="0.0.0.0",
    port=8000,
    log_level="debug"  # Changed from "info"
)
```

**Rebuild and restart:**
```bash
docker compose build pps-haiku-wrapper
docker compose restart pps-haiku-wrapper
```

---

## See Also

- **GRAPHITI_INTEGRATION.md**: Complete Graphiti architecture and direct integration docs
- **ARCHITECTURE.md**: Full PPS layer architecture
- **INSTALLATION.md**: General installation guide
- **docker-compose.yml**: Complete service definitions
- **cc_openai_wrapper.py**: Source code (heavily documented)
- **daemon/cc_invoker/invoker.py**: ClaudeInvoker implementation

---

## References

- [ClaudeInvoker Documentation](../daemon/cc_invoker/invoker.py)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [OpenAI API Reference](https://platform.openai.com/docs/api-reference/chat/create)
- [Graphiti Documentation](https://github.com/getzep/graphiti)
- [Claude Code Documentation](https://claude.ai/claude-code)
