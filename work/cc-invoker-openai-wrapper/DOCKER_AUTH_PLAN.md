# Docker Authentication Plan for CC Wrapper

**Status**: Research Complete
**Date**: 2026-01-28
**Author**: Orchestration Agent

---

## The Authentication Challenge

The `pps-cc-wrapper` container needs to run `ClaudeInvoker`, which requires:

1. **Claude Agent SDK** (Python) - Installed via `pip install claude-agent-sdk` ✅
2. **Claude Code CLI** (Node.js) - Binary that SDK spawns to communicate with Claude
3. **Authentication Credentials** - OAuth tokens stored in `~/.claude/.credentials.json`

**Current Problem**: The Dockerfile installs the SDK but provides NO way for the CLI to authenticate with Claude. The container will fail at runtime when ClaudeInvoker tries to spawn the CLI.

---

## What We Know

### Authentication Mechanism
- Claude CLI uses OAuth 2.0 with access/refresh tokens
- Credentials stored in `~/.claude/.credentials.json` with structure:
  ```json
  {
    "claudeAiOauth": {
      "accessToken": "...",
      "refreshToken": "...",
      "expiresAt": "...",
      "scopes": [...],
      "subscriptionType": "..."
    }
  }
  ```
- The CLI reads this file on startup for authentication
- Tokens CAN expire but CLI likely auto-refreshes using the refreshToken

### Claude CLI Installation
- Host has CLI installed via npm: `~/.claude/local/node_modules/@anthropic-ai/claude-code`
- Wrapper script at `~/.claude/local/claude` just execs the real CLI
- SDK looks for CLI in these locations (in order):
  1. `~/.claude/local/claude`
  2. `~/node_modules/.bin/claude`
  3. `~/.yarn/bin/claude`

### SDK Behavior
- No API key option in `ClaudeAgentOptions` - it MUST use the CLI
- SDK spawns CLI as subprocess via `subprocess_cli.py` transport
- No alternative transport mechanism available

---

## Viable Approaches

### ❌ Option A: ANTHROPIC_API_KEY Environment Variable
**Status**: NOT SUPPORTED

The Claude Agent SDK does NOT support direct API key authentication. It requires the CLI.

**Verdict**: Dead end - SDK architecture doesn't allow this.

---

### ⚠️ Option B: Volume Mount ~/.claude/ Directory
**How it works**: 
```yaml
volumes:
  - ${HOME}/.claude:/root/.claude:ro
```

**Pros**:
- Simple - one line in docker-compose.yml
- No Dockerfile changes needed
- Credentials stay on host (not baked into image)
- Auto-refreshed tokens work (host updates, container reads)

**Cons**:
- **Breaks portability** - tied to Jeff's laptop filesystem
- Can't deploy to NUC, server, or CI without copying credentials
- Credentials file contains sensitive OAuth tokens (security risk if mounted rw)
- Node.js CLI binary might not be compatible (host arch vs container arch)

**Compatibility Risk**: The CLI is a Node.js binary - will it work if mounted from WSL host into Docker Linux container?
- Host: WSL2 Ubuntu (x86_64)
- Container: python:3.11-slim (x86_64 Linux)
- Should work IF Node.js is installed in container

**Verdict**: Works for development, NOT suitable for production or portability goal.

---

### ✅ Option C: Install CLI + Mount Credentials Only (RECOMMENDED)
**How it works**:
1. Install Node.js and Claude CLI in Dockerfile:
   ```dockerfile
   RUN apt-get update && apt-get install -y nodejs npm
   RUN npm install -g @anthropic-ai/claude-code
   ```

2. Mount ONLY credentials file (not entire ~/.claude/):
   ```yaml
   volumes:
     - ${HOME}/.claude/.credentials.json:/root/.claude/.credentials.json:ro
   ```

3. SDK spawns container-installed CLI, which reads mounted credentials

**Pros**:
- CLI is self-contained in container (portable)
- Credentials stay on host (not baked into image)
- Read-only mount reduces security risk
- Works on any host that has credentials file
- Tokens auto-refresh (credentials file updated by host's Claude CLI)

**Cons**:
- Still requires credentials file on host
- Need to document setup: "Run `claude setup-token` on host first"
- Image size increases (~100MB for Node.js + CLI)

**Security**: Read-only mount prevents container from modifying credentials. Host's Claude CLI handles token refresh.

**Portability**: Better than Option B - only need credentials file, not entire ~/.claude/ tree. Can deploy to:
- ✅ Jeff's laptop (WSL)
- ✅ NUC (copy credentials file once)
- ❌ CI/CD (would need secrets management)
- ✅ Server (copy credentials file once)

**Verdict**: Best balance of simplicity, security, and portability for this use case.

---

### 🤔 Option D: Extract OAuth Token -> Anthropic SDK Direct
**How it works**:
1. Read OAuth access token from credentials file
2. Use `anthropic` Python SDK directly instead of `claude-agent-sdk`
3. Rewrite ClaudeInvoker to use API calls instead of CLI

**Pros**:
- TRUE portability - just need an env var
- No Node.js dependency (smaller image)
- Standard API authentication pattern

**Cons**:
- **MAJOR REWRITE** - ClaudeInvoker is built around claude-agent-sdk
- Lose MCP tool support (critical for daemon use)
- Lose conversation management features
- Token refresh handling becomes our problem
- High risk of breaking existing functionality
- Would need to reimplement context tracking, restarts, etc.

**Scope**: This is essentially "rewrite ClaudeInvoker from scratch". Out of scope for this project.

**Verdict**: Theoretically better, but effort >> value for this use case. Save for future refactor.

---

## Recommended Implementation

**Use Option C: Install CLI + Mount Credentials**

### Updated Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (Node.js for Claude CLI)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Claude CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Copy requirements and install Python dependencies
COPY pps/docker/requirements-cc-wrapper.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy daemon/cc_invoker module (needed for ClaudeInvoker)
COPY daemon/cc_invoker /app/daemon/cc_invoker

# Copy wrapper server
COPY pps/docker/cc_openai_wrapper.py .

# Expose port
EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "cc_openai_wrapper:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Updated docker-compose.yml

```yaml
pps-cc-wrapper:
  build:
    context: ../..
    dockerfile: pps/docker/Dockerfile.cc-wrapper
  container_name: pps-cc-wrapper
  restart: unless-stopped
  ports:
    - "127.0.0.1:8204:8000"
  volumes:
    # Mount Claude credentials (read-only)
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

### Setup Instructions (For Users)

**One-time setup on host**:
```bash
# Authenticate with Claude (if not already done)
claude setup-token

# Verify credentials file exists
ls -la ~/.claude/.credentials.json
```

**Build and run**:
```bash
cd pps/docker
docker compose build pps-cc-wrapper
docker compose up -d pps-cc-wrapper
docker compose logs -f pps-cc-wrapper
```

**Expected startup sequence**:
1. Container starts (~2s)
2. ClaudeInvoker initializes (~33s) - spawns CLI, reads credentials
3. Health check passes
4. Ready for requests

---

## Testing Plan

### Phase 1: Local Dockerfile Test
```bash
# Build image
cd /mnt/c/Users/Jeff/Claude_Projects/Awareness
docker build -f pps/docker/Dockerfile.cc-wrapper -t pps-cc-wrapper-test .

# Test credentials mount
docker run --rm \
  -v ~/.claude/.credentials.json:/root/.claude/.credentials.json:ro \
  -p 8000:8000 \
  pps-cc-wrapper-test

# In another terminal: test health
curl http://localhost:8000/health
```

### Phase 2: Docker Compose Integration
```bash
cd pps/docker
docker compose up pps-cc-wrapper

# Watch for:
# - "Initializing ClaudeInvoker"
# - "✓ ClaudeInvoker initialized"
# - Health check passing
```

### Phase 3: End-to-End Test
```bash
# Test chat completion
curl http://localhost:8204/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "haiku",
    "messages": [
      {"role": "user", "content": "Say hello in JSON format"}
    ]
  }' | jq .
```

---

## Open Questions

### Q1: Does Node.js version matter?
**Answer**: The Debian apt repo has Node.js 20.x which should be fine. Claude CLI requires Node >= 18.

**Fallback**: If apt version is too old, use NodeSource PPA:
```dockerfile
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
RUN apt-get install -y nodejs
```

### Q2: What happens when OAuth token expires?
**Answer**: The host's Claude CLI (via `claude setup-token`) handles token refresh. The container reads the file, so refreshed tokens are automatically picked up on next container restart.

**Caveat**: Long-running containers might hit expiry. The mounted credentials file is read-only, so container CAN'T refresh. 

**Mitigation**: 
- Tokens last 30-90 days typically
- Restart container monthly to pick up refreshed tokens
- OR: Make mount read-write (less secure but enables auto-refresh)

### Q3: What if user doesn't have credentials file?
**Answer**: Docker compose will fail to start with "volume mount failed". 

**Documentation needed**: Clear setup instructions in README:
1. Install Claude Code: `npm install -g @anthropic-ai/claude-code`
2. Authenticate: `claude setup-token`
3. Verify: `ls ~/.claude/.credentials.json`
4. Then run docker compose

---

## Security Considerations

### Credentials Exposure Risk
- Credentials file contains OAuth tokens (sensitive)
- Read-only mount prevents container modification
- File is gitignored (not committed)
- Only Jeff's laptop and authorized hosts should have this file

### Best Practices
- ✅ Mount as read-only (`:ro`)
- ✅ Use `127.0.0.1` bind (not `0.0.0.0`) for wrapper port
- ✅ Keep wrapper on internal Docker network
- ❌ Don't commit credentials
- ❌ Don't bake credentials into image

---

## Deployment Scenarios

### Scenario 1: Jeff's Laptop (Primary Development)
**Status**: ✅ Ready

1. Credentials already exist at `~/.claude/.credentials.json`
2. Volume mount works
3. Docker compose up
4. Done

### Scenario 2: NUC (Local Server)
**Status**: ⚠️ Requires Setup

1. Copy credentials file once:
   ```bash
   scp ~/.claude/.credentials.json nuc:~/.claude/
   ```
2. Install Claude CLI on NUC (for token refresh):
   ```bash
   npm install -g @anthropic-ai/claude-code
   ```
3. Docker compose up
4. Refresh credentials periodically: `claude setup-token`

### Scenario 3: Remote Server / Cloud
**Status**: ⚠️ Requires Secrets Management

Not recommended for this approach. Use Option D (direct API) instead if deploying to cloud.

### Scenario 4: CI/CD
**Status**: ❌ Not Suitable

CI/CD needs API key approach (Option D), not OAuth file mounts.

---

## Implementation Checklist

- [ ] Update `pps/docker/Dockerfile.cc-wrapper`
  - [ ] Add Node.js installation
  - [ ] Add Claude CLI installation
  - [ ] Verify build works
- [ ] Update `pps/docker/docker-compose.yml`
  - [ ] Add credentials volume mount
  - [ ] Document requirement in comments
- [ ] Test locally
  - [ ] Build image
  - [ ] Start container
  - [ ] Verify CLI auth works
  - [ ] Test /health endpoint
  - [ ] Test /v1/chat/completions
- [ ] Documentation
  - [ ] Add setup instructions to USAGE.md
  - [ ] Document credentials requirement
  - [ ] Add troubleshooting for auth failures
  - [ ] Document token refresh process
- [ ] Update work/cc-invoker-openai-wrapper/TODO.md
  - [ ] Mark Docker auth as solved
  - [ ] Update testing checklist

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Token expiry during long runs | Medium | Medium | Document restart schedule |
| Credentials file missing | High (first-time users) | High | Clear setup docs + compose will fail-fast |
| Node.js/npm install failures | Low | High | Pin specific versions, test in CI |
| CLI version incompatibility | Low | Medium | Pin `@anthropic-ai/claude-code` version |
| Read-only mount prevents refresh | Medium | Low | Accept manual restarts or use :rw mount |

---

## Future Improvements

### Near-term (This Project)
- ✅ Get it working with mounted credentials
- Document setup clearly
- Test on NUC deployment

### Long-term (Future Work)
- Investigate Option D (direct Anthropic SDK)
  - Would enable true portability (env var auth)
  - Would eliminate Node.js dependency
  - Requires major ClaudeInvoker refactor
- Consider API key support in claude-agent-sdk
  - File upstream feature request
  - Would enable CI/CD use cases

---

## Conclusion

**Recommendation**: Proceed with **Option C** (Install CLI + Mount Credentials).

**Why**:
- Achieves the main goal: working wrapper in Docker
- Reasonable compromise: portable container, host-managed credentials
- Low implementation risk: small Dockerfile changes
- Good security: read-only mount
- Works for primary use case (Jeff's laptop + NUC)

**Blockers Resolved**:
- ✅ How to authenticate: Mount credentials file
- ✅ How to get CLI: Install via npm in container
- ✅ Portability: Good enough for this use case

**Next Step**: Update Dockerfile and docker-compose.yml, test locally, then deploy.

---

**Ready for implementation** ✅
