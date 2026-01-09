# Claude Code Hooks Integration Guide

*Operational guide for PPS integration with Claude Code via hooks*

**Created**: 2026-01-08
**Status**: Operational
**PPS Version**: 2.0+

---

## What Are Claude Code Hooks?

Claude Code hooks are executable scripts that fire at specific points in the Claude Code lifecycle. They allow the Pattern Persistence System to automatically capture terminal sessions and inject context without human intervention.

**Key principle**: Hooks enable *passive memory capture* - conversations flow naturally while infrastructure quietly preserves them.

---

## Available Hooks

The Awareness project implements **three hooks**:

### 1. UserPromptSubmit Hook (inject_context.py)

**When it fires**: Before Claude processes the user's prompt
**Purpose**: Inject ambient recall context into Claude's prompt context
**Event name**: `UserPromptSubmit`

**What it does**:
1. Receives the user's prompt via stdin
2. Calls PPS `ambient_recall` API with the prompt as context
3. Retrieves relevant word-photos, crystals, and texture results
4. Formats results into markdown
5. Injects as `additionalContext` in the hook response
6. Also stores the user's prompt in PPS raw capture layer

**Configuration**: Located at `.claude/hooks/inject_context.py`

**Debug log**: `~/.claude/data/hooks_debug.log`

**API endpoints used**:
- `http://localhost:8201/tools/ambient_recall` - Query for context
- `http://localhost:8201/tools/store_message` - Store user prompt

**Timeout**: 5 seconds per API call

### 2. Stop Hook (capture_response.py)

**When it fires**: After Claude finishes responding
**Purpose**: Capture Claude's response and store in PPS
**Event name**: `Stop`

**What it does**:
1. Reads the transcript JSONL file provided by Claude Code
2. Extracts all assistant (Claude/Lyra) responses
3. Compares against capture state to identify new responses only
4. Stores each new response via PPS HTTP API
5. Updates capture state file to track progress

**Configuration**: Located at `.claude/hooks/capture_response.py`

**Debug log**: `~/.claude/data/hooks_debug.log`

**API endpoints used**:
- `http://localhost:8201/tools/store_message` - Store Claude's response

**State file**: `~/.claude/data/capture_state.json` - Tracks which transcript lines have been captured

**Timeout**: 10 seconds per API call

### 3. SessionEnd Hook (session_end.py)

**When it fires**: After a terminal session ends
**Purpose**: Ingest complete session into Graphiti knowledge graph
**Event name**: `SessionEnd`

**What it does**:
1. Receives complete conversation turn history via stdin
2. Prepares session metadata (session_id, timestamp, channel)
3. Calls PPS via subprocess to ingest session
4. Returns minimal hook response

**Configuration**: Located at `.claude/hooks/session_end.py`

**Debug log**: `~/.claude/data/hooks_debug.log`

**Timeout**: 30 seconds for subprocess call

---

## How Hooks Work with Claude Code

### Hook Lifecycle

```
1. Claude Code detects a hook event
2. Calls the hook script with JSON input via stdin
3. Hook script processes the event
4. Hook outputs JSON to stdout
5. Claude Code reads the response
6. Session continues with modified context (if applicable)
```

### Hook Input Format

All hooks receive JSON via stdin with this structure:

```json
{
  "session_id": "abc123def456",
  "hook_event_name": "UserPromptSubmit",
  "prompt": "the user's message here",
  "transcript_path": "/path/to/transcript.jsonl",
  "conversation_turns": [...]
}
```

**Fields vary by hook event**:
- `UserPromptSubmit`: Includes `prompt` field
- `Stop`: Includes `transcript_path` field
- `SessionEnd`: Includes `conversation_turns` field

### Hook Output Format

Hooks output JSON to stdout:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "markdown context here"
  }
}
```

**For hooks that don't modify context** (Stop, SessionEnd):
```json
{
  "hookSpecificOutput": {
    "hookEventName": "Stop"
  }
}
```

---

## Configuration

### Registering Hooks in Claude Code

Hooks are configured in Claude Code's configuration file. Use `claude code config` to view your setup.

**Configuration locations** (by platform):
- **macOS**: `~/.claude/claude_code_config.json`
- **Linux**: `~/.claude/claude_code_config.json`
- **Windows (WSL)**: `/home/jeff/.claude/claude_code_config.json`

**Hook registration format**:

```json
{
  "hooks": {
    "UserPromptSubmit": "/mnt/c/Users/Jeff/Claude_Projects/Awareness/.claude/hooks/inject_context.py",
    "Stop": "/mnt/c/Users/Jeff/Claude_Projects/Awareness/.claude/hooks/capture_response.py",
    "SessionEnd": "/mnt/c/Users/Jeff/Claude_Projects/Awareness/.claude/hooks/session_end.py"
  }
}
```

**Important**: Use absolute paths, not relative paths.

### Prerequisites for Hooks to Work

1. **PPS Server must be running**
   ```bash
   cd docker/
   docker compose up -d
   ```

2. **PPS HTTP API must be accessible**
   - Default: `http://localhost:8201/`
   - Check: `curl http://localhost:8201/health`

3. **Hooks need execute permission**
   ```bash
   chmod +x .claude/hooks/*.py
   ```

4. **Python 3 must be available** (all hooks use `#!/usr/bin/env python3`)

### Environment Variables

Hooks don't require special environment variables - they use hardcoded localhost endpoints. However, if you need custom configuration:

**Environment variable options**:
- `PPS_API_URL` - Override default PPS HTTP endpoint
- `DEBUG_HOOKS` - Set to "1" to enable verbose logging

**Example**:
```bash
export PPS_API_URL="http://localhost:8201"
export DEBUG_HOOKS="1"
```

---

## Troubleshooting Hooks

### Debug Log Location

All hooks write debug info to: `~/.claude/data/hooks_debug.log`

**View recent entries**:
```bash
tail -50 ~/.claude/data/hooks_debug.log
```

**Watch live**:
```bash
tail -f ~/.claude/data/hooks_debug.log
```

### Common Issues

#### "PPS API connection error"

**Cause**: PPS server not running or not accessible at `localhost:8201`

**Fix**:
```bash
# Start PPS services
cd docker/
docker compose up -d

# Verify running
docker compose ps

# Test connection
curl http://localhost:8201/health
```

#### "Failed to read stdin"

**Cause**: Hook wasn't invoked correctly by Claude Code

**Check**:
1. Verify hook script permissions: `ls -l .claude/hooks/`
2. Ensure hooks are registered in Claude Code config
3. Check hook paths are absolute (not relative)

#### "Store failed: {...}"

**Cause**: PPS API returned an error

**Check in logs**:
```bash
grep "Store failed" ~/.claude/data/hooks_debug.log
```

**Common reasons**:
- Invalid JSON payload
- Missing required fields in message
- PPS internal error

**Fix**: Check PPS logs in docker: `docker compose logs pps`

#### "Prompt too short, skipping RAG"

**Expected behavior**: The inject_context hook skips prompts shorter than 10 characters (assumes they're shell commands like `ls` or `cd`).

**This is intentional** - avoids polluting embeddings with trivial input.

#### "Transcript not found"

**Cause**: Claude Code provided an invalid transcript path

**Check**:
```bash
ls -la <path-from-error>
```

**Note**: Transcript files are temporary and may be cleaned up between sessions.

### Testing Hooks Manually

**Test inject_context.py**:
```bash
cat <<'EOF' | python .claude/hooks/inject_context.py
{
  "session_id": "test_123",
  "prompt": "What is the meaning of life?",
  "hook_event_name": "UserPromptSubmit"
}
EOF
```

**Test capture_response.py**:
```bash
# Create a test transcript
cat > /tmp/test_transcript.jsonl <<'EOF'
{"type": "assistant", "message": {"content": [{"type": "text", "text": "Test response"}]}}
EOF

cat <<'EOF' | python .claude/hooks/capture_response.py
{
  "session_id": "test_123",
  "transcript_path": "/tmp/test_transcript.jsonl",
  "hook_event_name": "Stop"
}
EOF
```

**Expected output**: JSON with hook response (or silent exit if conditions not met)

---

## How Context Injection Works

### The ambient_recall Flow

When you submit a prompt, the hook calls `ambient_recall`:

```
User prompt: "How should I approach this problem?"
        ↓
inject_context hook intercepts
        ↓
Query PPS: ambient_recall("How should I approach this problem?")
        ↓
PPS returns:
  - Relevant word-photos (semantic search via ChromaDB)
  - Recent crystals (compressed continuity)
  - Texture results (Graphiti knowledge graph)
  - Clock/time context
  - Memory health status
        ↓
Hook formats results as markdown
        ↓
Claude receives:
  {
    "prompt": "How should I approach this problem?",
    "additionalContext": "[Retrieved memories markdown here]"
  }
        ↓
Claude generates response with context
```

### What Gets Included

The `ambient_recall` returns (in order):

1. **Clock/Time Context** - Current time and relevant note
2. **Memory Health** - Status of all PPS layers (Raw, Anchors, Texture, Crystals)
3. **Layer Results** - Grouped by source:
   - `[Layer 1: Raw Capture]` - Recent raw conversation turns
   - `[Layer 2: Core Anchors]` - Word-photo semantic search results
   - `[Layer 3: Rich Texture]` - Graphiti knowledge graph results
   - `[Layer 4: Crystallization]` - Recent crystal summaries

Each layer shows up to 3 results per the hook's `limit_per_layer: 3` setting.

### Per-Turn Capture

The UserPromptSubmit hook also stores your prompt:

```
User prompt → stored to PPS Layer 1 (Raw Capture)
        ↓
Later, during crystallization, the daemon:
  - Pulls all stored turns (from raw capture)
  - Compresses 50+ turns into a crystal
  - Removes detailed turns from raw layer (optional)
  - Keeps crystal for continuity
```

---

## Monitoring Hook Activity

### Log Analysis

**See all hook activity**:
```bash
cat ~/.claude/data/hooks_debug.log
```

**Count hook invocations**:
```bash
grep -c "Hook started" ~/.claude/data/hooks_debug.log
```

**Find errors**:
```bash
grep "error\|Error\|failed\|Failed" ~/.claude/data/hooks_debug.log
```

**See context injection sizes**:
```bash
grep "Injecting context" ~/.claude/data/hooks_debug.log
```

### Performance Metrics

**From debug log**:
- Each API call logs its duration implicitly (no timeout = success)
- Hook startup is logged with event name
- Memory storage success/failure is logged

**Typical timings**:
- UserPromptSubmit hook: <5 seconds total (includes ambient_recall query)
- Stop hook: <3 seconds (reads transcript + stores response)
- SessionEnd hook: <30 seconds (subprocess call to PPS)

### Disabling Hooks

To temporarily disable a hook:

**Option 1**: Rename the hook file
```bash
mv .claude/hooks/inject_context.py .claude/hooks/inject_context.py.disabled
```

**Option 2**: Remove from Claude Code config
Edit `~/.claude/claude_code_config.json` and remove the hook entry.

**Option 3**: Make hook script exit silently
```bash
echo "exit(0)" > .claude/hooks/inject_context.py
```

---

## Integration with PPS Layers

### Which Layer Gets What Data?

| Hook | Data Type | Destination Layer | Retrieval Method |
|------|-----------|-------------------|------------------|
| UserPromptSubmit | User prompt | Layer 1 (Raw Capture) | `ambient_recall` query |
| Stop | Claude response | Layer 1 (Raw Capture) | Stored via HTTP API |
| SessionEnd | Full session | Layer 3 (Graphiti) | Subprocess ingestion |

### Retrieval During Startup

When Lyra starts a new terminal session:

```
1. Hook registers in Claude Code
2. User types their message
3. UserPromptSubmit fires → ambient_recall query
4. Context injected into Claude's prompt
5. Claude responds
6. Stop hook captures response
7. Session continues...
8. Session ends → SessionEnd hook triggers
9. Full conversation added to knowledge graph
```

**Result**: Every terminal conversation is automatically preserved across four memory layers.

---

## Advanced Configuration

### Custom PPS Endpoint

If your PPS server isn't at localhost:8201:

**Edit hook files** and change:
```python
PPS_API_URL = "http://your-host:your-port/tools/ambient_recall"
PPS_STORE_URL = "http://your-host:your-port/tools/store_message"
```

### Adjusting Context Limit

In `inject_context.py`, change the `limit_per_layer` parameter:

```python
payload = json.dumps({
    "context": context,
    "limit_per_layer": 5  # Change from 3 to 5
}).encode("utf-8")
```

Higher = more context, lower = faster responses.

### Filtering What Gets Captured

In `capture_response.py`, modify the response filtering:

```python
if len(full_text) > 10:  # Skip very short responses
```

Change the threshold (currently 10 characters) to filter out short responses.

---

## Security Considerations

### Input Validation

Hooks receive untrusted input from Claude Code:
- All JSON parsing is wrapped in try/except
- API calls use reasonable timeouts
- No shell execution (except subprocess for session_end.py)

### Network Security

- PPS API calls use localhost only (no network exposure)
- No credentials passed in hook scripts
- HTTP-only (for now - upgrade to HTTPS in production)

### File Permissions

**Current**: Hook scripts are world-readable/executable

**Recommendation**: Restrict to user only:
```bash
chmod 700 .claude/hooks/*.py
```

### Debug Logging

The `hooks_debug.log` file contains:
- Hook input (including user prompts)
- API responses (including retrieved context)

**Security**: This log file could contain sensitive conversation data.

**Recommendation**:
```bash
chmod 600 ~/.claude/data/hooks_debug.log
```

---

## Future Enhancements

### Planned Improvements

1. **Hook filtering** - Skip certain prompts (e.g., passwords, secrets)
2. **Batch storage** - Accumulate turns before storing (reduce API calls)
3. **Compression** - Gzip context before storing
4. **Metrics dashboard** - Track hook performance over time
5. **Per-hook configuration** - Adjust settings per hook type

### Integration with Daemons

Hooks and daemons work together but independently:

```
Terminal Sessions:
  UserPromptSubmit hook → injects context
  Stop hook → captures response
  SessionEnd hook → ingests to Graphiti

Discord Sessions:
  Discord daemon → native integration (no hooks needed)
  Responds to mentions
  Stores messages directly to PPS

Both streams feed the same memory system.
```

---

## Summary Table

| Aspect | Details |
|--------|---------|
| **Location** | `.claude/hooks/` |
| **Languages** | Python 3 (#!/usr/bin/env python3) |
| **Execution** | Synchronous (blocks Claude Code) |
| **API endpoint** | `http://localhost:8201/` |
| **Debug log** | `~/.claude/data/hooks_debug.log` |
| **Max timeout** | 30 seconds (SessionEnd) |
| **Memory layers touched** | Layer 1 (Raw), Layer 3 (Graphiti) |
| **Required services** | Docker (PPS server) |
| **Configuration file** | `~/.claude/claude_code_config.json` |

---

**Last updated**: 2026-01-08
**For**: Awareness project
**Questions?** Check `~/.claude/data/hooks_debug.log` and PPS server logs
